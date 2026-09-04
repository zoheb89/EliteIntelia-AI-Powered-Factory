"""Core foundation: provenance, lifecycle, LLM gateway and the job engine."""
import json

import pytest

from core.domain.provenance import (
    Confidence, EvidenceRef, Provenance, Statement, reconcile, unknown,
)
from core.domain.lifecycle import (
    Approval, LifecycleState, STAGE_BY_ID, STAGES, StageStatus, downstream_of,
)
from llm.gateway.base import LLMError, LLMRequest, Message, ProviderConfig, Role
from llm.gateway.gateway import LLMGateway, StructuredOutputError
from jobs.engine import JobEngine, JobStatus, Step, StepStatus


# ------------------------------------------------------------- provenance §8
def test_fact_without_evidence_is_downgraded():
    """A FACT with no source is the exact hallucination this design prevents."""
    s = Statement("Customer runs SQL Server", provenance=Provenance.FACT)
    assert s.provenance is Provenance.AI_INFERENCE
    assert s.confidence is Confidence.LOW
    assert "Downgraded" in s.note


def test_fact_with_evidence_is_kept():
    s = Statement("Customer runs SQL Server", provenance=Provenance.FACT,
                  evidence=[EvidenceRef("ev-1", "p.4")])
    assert s.provenance is Provenance.FACT
    assert s.provenance.is_evidence_backed


def test_unknown_requires_customer_input():
    u = unknown("What is the data refresh requirement?")
    assert u.needs_customer_input
    assert u.provenance.requires_confirmation


def test_reconcile_prefers_stronger_provenance():
    """A later AI run must never overwrite a customer decision."""
    decided = Statement("Target is Snowflake", provenance=Provenance.CUSTOMER_DECISION)
    inferred = Statement("Target is Databricks", provenance=Provenance.AI_INFERENCE)
    assert reconcile(decided, inferred) is decided
    assert reconcile(inferred, decided) is decided


def test_statement_roundtrip():
    s = Statement("x", provenance=Provenance.ASSUMPTION, evidence=[EvidenceRef("e1", "l", "x")])
    assert Statement.from_dict(s.to_dict()).provenance is Provenance.ASSUMPTION


# --------------------------------------------------------------- lifecycle §2
def test_lifecycle_requirements_form_a_dag():
    seen = set()
    for stage in STAGES:
        for req in stage.requires:
            assert req in STAGE_BY_ID, f"{stage.id} requires unknown stage {req}"
            assert req in seen, f"{stage.id} requires {req}, which is defined later"
        seen.add(stage.id)


def test_first_runnable_stage_is_intent():
    assert LifecycleState().next_stage().id == "intent"


def test_stage_is_blocked_until_upstream_completes():
    st = LifecycleState()
    assert not st.can_run("discovery")
    assert st.blockers("discovery")


def test_human_approval_gate_blocks_downstream():
    st = LifecycleState()
    for sid in ("intent", "evidence", "discovery", "questions", "assessment", "requirements"):
        st.statuses[sid] = StageStatus.COMPLETE
    # requirements needs HUMAN approval before platform selection may run.
    assert STAGE_BY_ID["requirements"].approval is Approval.HUMAN
    assert not st.can_run("platform")
    assert st.pending_approval().id == "requirements"

    st.approvals["requirements"] = True
    assert st.can_run("platform")


def test_downstream_of_is_transitive():
    ds = downstream_of("requirements")
    assert "platform" in ds and "architecture" in ds and "sow" in ds


def test_progress_counts_completed_stages():
    st = LifecycleState()
    st.statuses["intent"] = StageStatus.COMPLETE
    done, total = st.progress
    assert done == 1 and total == len(STAGES)


# ------------------------------------------------------------ LLM gateway §35
def _echo(name="echo1", response=None, **kw):
    return ProviderConfig(name=name, kind="echo", model="test-model",
                          extra={"response": response} if response else {}, **kw)


def _gw(*cfgs, **kw):
    return LLMGateway(providers=list(cfgs), sleep=lambda _s: None, **kw)


def _req(text="hello", json_mode=False):
    return LLMRequest(messages=[Message(Role.USER, text)], json_mode=json_mode)


def test_gateway_is_provider_neutral():
    gw = _gw(_echo())
    r = gw.complete(_req())
    assert r.ok and r.response.provider == "echo1"


def test_unknown_provider_kind_rejected():
    with pytest.raises(Exception):
        _gw(ProviderConfig(name="x", kind="not_a_real_vendor"))


def test_gateway_falls_back_to_next_provider():
    """A failing primary must transparently fail over (spec §35)."""
    class Boom:
        kind = "boom"
        def __init__(self, config): self.config = config
        def is_configured(self): return True
        def describe(self): return {}
        def complete(self, request): raise LLMError("primary down", retryable=False)

    from llm.providers import http_providers as hp
    hp.PROVIDER_TYPES["boom"] = Boom
    try:
        gw = _gw(ProviderConfig(name="primary", kind="boom"), _echo("secondary"))
        r = gw.complete(_req())
        assert r.response.provider == "secondary"
        assert [c.ok for c in r.calls] == [False, True]
    finally:
        hp.PROVIDER_TYPES.pop("boom", None)


def test_gateway_retries_retryable_errors():
    calls = {"n": 0}

    class Flaky:
        kind = "flaky"
        def __init__(self, config): self.config = config
        def is_configured(self): return True
        def describe(self): return {}
        def complete(self, request):
            calls["n"] += 1
            if calls["n"] < 2:
                raise LLMError("temporary", retryable=True)
            from llm.gateway.base import LLMResponse
            return LLMResponse(text="ok", provider="flaky", model="m")

    from llm.providers import http_providers as hp
    hp.PROVIDER_TYPES["flaky"] = Flaky
    try:
        gw = _gw(ProviderConfig(name="flaky", kind="flaky", max_retries=3))
        assert gw.complete(_req()).response.text == "ok"
        assert calls["n"] == 2
    finally:
        hp.PROVIDER_TYPES.pop("flaky", None)


def test_complete_json_parses_plain_json():
    gw = _gw(_echo(response='{"a": 1}'))
    data, _ = gw.complete_json(_req(json_mode=True))
    assert data == {"a": 1}


def test_complete_json_extracts_from_code_fence():
    gw = _gw(_echo(response='Here you go:\n```json\n{"a": 2}\n```\nHope that helps.'))
    data, _ = gw.complete_json(_req(json_mode=True))
    assert data == {"a": 2}


def test_complete_json_raises_rather_than_guessing():
    gw = _gw(_echo(response="I cannot help with that."))
    with pytest.raises(StructuredOutputError):
        gw.complete_json(_req(json_mode=True), repair=False)


def test_describe_redacts_api_keys():
    gw = _gw(ProviderConfig(name="p", kind="echo", api_key="super-secret"))
    assert gw.describe()[0]["api_key"] == "***"
    assert "super-secret" not in json.dumps(gw.describe())


# -------------------------------------------------------------- jobs §42-§44
def _steps(*specs):
    return [Step(sid, sid.title(), fn, retries=r, optional=o) for sid, fn, r, o in specs]


def test_job_runs_all_steps_in_order():
    seen = []
    steps = _steps(("a", lambda c: seen.append("a") or 1, 1, False),
                   ("b", lambda c: seen.append("b") or 2, 1, False))
    eng = JobEngine(sleep=lambda _s: None)
    job = eng.run(eng.create("test", "p1", steps), steps)
    assert job.status is JobStatus.COMPLETED
    assert seen == ["a", "b"]


def test_step_output_is_available_to_later_steps():
    steps = _steps(("first", lambda c: 21, 1, False),
                   ("second", lambda c: c["first"] * 2, 1, False))
    eng = JobEngine(sleep=lambda _s: None)
    job = eng.run(eng.create("test", "p1", steps), steps)
    assert job.results["second"].output == 42


def test_failure_preserves_completed_work_as_partial():
    """The 504 lesson: never lose discovery because blueprint failed."""
    def boom(_c): raise RuntimeError("provider exploded")
    steps = _steps(("ok", lambda c: "kept", 1, False), ("bad", boom, 1, False))
    eng = JobEngine(sleep=lambda _s: None)
    job = eng.run(eng.create("test", "p1", steps), steps)
    assert job.status is JobStatus.PARTIAL
    assert job.results["ok"].status is StepStatus.COMPLETED
    assert job.results["ok"].output == "kept"


def test_resume_skips_completed_steps():
    runs = {"a": 0, "b": 0}

    def a(_c): runs["a"] += 1; return "A"
    def b(_c):
        runs["b"] += 1
        if runs["b"] == 1:
            raise RuntimeError("transient")
        return "B"

    steps = _steps(("a", a, 1, False), ("b", b, 1, False))
    eng = JobEngine(sleep=lambda _s: None)
    job = eng.run(eng.create("test", "p1", steps), steps)
    assert job.status is JobStatus.PARTIAL

    resumed = eng.resume(job.id, steps)
    assert resumed.status is JobStatus.COMPLETED
    assert runs["a"] == 1, "completed step must not re-run"
    assert runs["b"] == 2


def test_retries_then_succeeds():
    n = {"i": 0}

    def flaky(_c):
        n["i"] += 1
        if n["i"] < 3:
            raise RuntimeError("temporary")
        return "ok"

    steps = _steps(("s", flaky, 3, False))
    eng = JobEngine(sleep=lambda _s: None)
    job = eng.run(eng.create("t", "p", steps), steps)
    assert job.status is JobStatus.COMPLETED
    assert job.results["s"].attempts == 3


def test_optional_step_failure_does_not_stop_the_job():
    def boom(_c): raise RuntimeError("nope")
    steps = _steps(("opt", boom, 1, True), ("after", lambda c: "ran", 1, False))
    eng = JobEngine(sleep=lambda _s: None)
    job = eng.run(eng.create("t", "p", steps), steps)
    assert job.status is JobStatus.COMPLETED
    assert job.results["after"].output == "ran"


def test_job_serialises_for_the_api():
    steps = _steps(("a", lambda c: "x", 1, False))
    eng = JobEngine(sleep=lambda _s: None)
    d = eng.run(eng.create("t", "p", steps), steps).to_dict()
    assert d["status"] == "COMPLETED" and d["total_steps"] == 1
    json.dumps(d)  # must be JSON-serialisable for the API layer
