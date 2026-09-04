"""Agent orchestrator, tool system, estimation engine and SOW factory."""
import json
import os
import tempfile

import pytest

from agents_v2.base import AgentOutput
from agents_v2.discovery import DiscoveryAgent, RequirementsAgent
from agents_v2.orchestrator import AGENTS, GateError, Orchestrator
from core.estimation import (
    Automation, Complexity, WorkItem, estimate, work_items_from_project,
)
from core.sow import build_sow, render_markdown
from core.tools.registry import ToolRegistry, ToolSpec, build_project_tools
from llm.gateway.base import LLMError, ProviderConfig
from llm.gateway.gateway import LLMGateway


# ------------------------------------------------------------------ fixtures
@pytest.fixture()
def repo():
    from persistence import repository as R
    os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'a.db')}"
    R.reset_engine()
    R.init_db()
    with R.session_scope() as s:
        t = R.Repository.ensure_tenant(s, "t1", "T1")
        yield R.Repository(s, t.id, "tester")
    os.environ.pop("DATABASE_URL", None)
    R.reset_engine()


def _gw(response=None, fail=False):
    if fail:
        class Dead:
            kind = "dead"
            def __init__(self, config): self.config = config
            def is_configured(self): return True
            def describe(self): return {}
            def complete(self, request): raise LLMError("provider unavailable")
        from llm.providers import http_providers as hp
        hp.PROVIDER_TYPES["dead"] = Dead
        return LLMGateway([ProviderConfig(name="dead", kind="dead")], sleep=lambda _s: None)
    return LLMGateway(
        [ProviderConfig(name="echo", kind="echo", model="m",
                        extra={"response": json.dumps(response or {})})],
        sleep=lambda _s: None)


# ---------------------------------------------------------------- tools §37
def test_tool_registry_records_successful_calls():
    reg = ToolRegistry()
    reg.register(ToolSpec("add", "adds", {"a": "int", "b": "int"}, "int"),
                 lambda a, b: a + b)
    assert reg.invoke("add", a=2, b=3) == 5
    assert reg.calls[0].ok and reg.calls[0].tool == "add"


def test_tool_registry_records_failures():
    reg = ToolRegistry()
    reg.register(ToolSpec("boom", "fails"), lambda: (_ for _ in ()).throw(ValueError("nope")))
    with pytest.raises(ValueError):
        reg.invoke("boom")
    assert reg.calls[0].ok is False and "nope" in reg.calls[0].error


def test_unknown_tool_is_recorded_and_raises():
    reg = ToolRegistry()
    with pytest.raises(KeyError):
        reg.invoke("ghost")
    assert reg.calls[0].ok is False


def test_project_tools_are_scoped_and_described(repo):
    p = repo.create_project("P", intent="modernize")
    reg = build_project_tools(repo, p.id)
    assert "search_evidence" in reg.names()
    assert reg.invoke("project_summary")["intent"] == "modernize"
    assert "search_evidence(" in reg.describe()


def test_search_evidence_returns_citable_excerpts(repo):
    p = repo.create_project("P")
    repo.add_evidence(p.id, name="rfp.txt",
                      extracted_text="The hospital runs SQL Server 2019 for admissions.")
    hits = build_project_tools(repo, p.id).invoke("search_evidence", query="SQL Server")
    assert hits and hits[0]["evidence_id"] and "SQL Server" in hits[0]["excerpt"]


# --------------------------------------------------------------- agents §36
def test_discovery_agent_tags_provenance(repo):
    p = repo.create_project("P", intent="Modernize HMS")
    repo.add_evidence(p.id, name="rfp.txt", extracted_text="Hospital HMS on SQL Server.")
    payload = {
        "summary": "Modernize the HMS data platform.",
        "objectives": [{"text": "Migrate to a lakehouse", "provenance": "AI_INFERENCE"}],
        "requirements": [{"text": "Runs SQL Server", "provenance": "FACT"}],
        "unknowns": [{"text": "What are the data volumes?", "provenance": "UNKNOWN"}],
    }
    agent = DiscoveryAgent(_gw(payload), build_project_tools(repo, p.id))
    out = agent.run()

    assert out.generation_mode == "ai"
    kinds = {getattr(s, "kind", "") for s in out.statements}
    assert {"objective", "requirement", "unknown"} <= kinds
    assert any(s.provenance.value == "UNKNOWN" for s in out.statements)


def test_agent_downgrades_unevidenced_fact(repo):
    """A model claiming FACT without a citation must not be believed (§68)."""
    p = repo.create_project("P", intent="x")
    payload = {"summary": "s", "requirements": [
        {"text": "Customer is ISO 27001 certified", "provenance": "FACT"}]}
    out = DiscoveryAgent(_gw(payload), build_project_tools(repo, p.id)).run()
    claim = next(s for s in out.statements if "ISO 27001" in s.text)
    assert claim.provenance.value == "AI_INFERENCE"


def test_agent_keeps_fact_when_evidence_is_cited(repo):
    p = repo.create_project("P", intent="x")
    repo.add_evidence(p.id, name="doc.txt", extracted_text="ISO 27001 certified")
    payload = {"summary": "s", "requirements": [
        {"text": "Customer is ISO 27001 certified", "provenance": "FACT",
         "evidence": [{"evidence_id": "e1", "locator": "p.2"}]}]}
    out = DiscoveryAgent(_gw(payload), build_project_tools(repo, p.id)).run()
    claim = next(s for s in out.statements if "ISO 27001" in s.text)
    assert claim.provenance.value == "FACT"


def test_agent_degrades_when_provider_is_down(repo):
    """The lifecycle must never be blocked by an unavailable model (§44)."""
    p = repo.create_project("P", intent="Modernize HMS")
    repo.add_evidence(p.id, name="rfp.txt", extracted_text="HMS on SQL Server")
    out = DiscoveryAgent(_gw(fail=True), build_project_tools(repo, p.id)).run()

    assert out.generation_mode == "deterministic_evidence_only"
    assert out.degraded
    assert any(s.provenance.value == "UNKNOWN" for s in out.statements)
    assert out.warnings


def test_agent_records_tool_calls(repo):
    p = repo.create_project("P", intent="x")
    out = DiscoveryAgent(_gw({"summary": "s"}), build_project_tools(repo, p.id)).run()
    assert any(c.tool == "project_summary" for c in out.tool_calls)


def test_bad_model_output_falls_back(repo):
    """A JSON array where an object was required must not crash the stage."""
    p = repo.create_project("P", intent="x")
    out = DiscoveryAgent(_gw([1, 2, 3]), build_project_tools(repo, p.id)).run()
    assert out.generation_mode == "deterministic_evidence_only"


# --------------------------------------------------------- orchestrator §36
def test_orchestrator_enforces_gates(repo):
    p = repo.create_project("P", intent="x")
    orch = Orchestrator(_gw({"summary": "s"}))
    with pytest.raises(GateError):
        orch.run_stage(repo, p.id, "assessment")   # discovery not complete


def test_orchestrator_persists_statements_and_artifacts(repo):
    p = repo.create_project("P", intent="x")
    repo.save_artifact(p.id, "intent", "{}")
    repo.save_artifact(p.id, "evidence_index", "{}")

    payload = {"summary": "done", "objectives": [{"text": "o1"}],
               "unknowns": [{"text": "q1", "provenance": "UNKNOWN"}]}
    result = Orchestrator(_gw(payload)).run_stage(repo, p.id, "discovery")

    assert "discovery" in result.artifacts
    assert result.statements_persisted == 2
    assert repo.latest_artifact(p.id, "discovery") is not None
    assert len(repo.list_runs(p.id)) == 1


def test_orchestrator_writes_an_ai_audit_entry(repo):
    p = repo.create_project("P", intent="x")
    repo.save_artifact(p.id, "intent", "{}")
    repo.save_artifact(p.id, "evidence_index", "{}")
    Orchestrator(_gw({"summary": "s"})).run_stage(repo, p.id, "discovery")
    events = [e for e in repo.list_audit(p.id) if e.action.startswith("stage.")]
    assert events and events[0].actor_kind == "ai"


def test_every_registered_agent_owns_a_real_stage():
    from core.domain.lifecycle import STAGES
    owned = {s.agent for s in STAGES}
    for agent_id in AGENTS:
        assert agent_id in owned, f"agent '{agent_id}' owns no lifecycle stage"


# ---------------------------------------------------------- estimation §23-25
def test_estimate_is_deterministic():
    items = work_items_from_project([{}] * 10, sources=3, entities=8, reports=5)
    assert estimate(items) == estimate(items)


def test_automation_reduces_effort_below_manual_baseline():
    r = estimate(work_items_from_project([{}] * 10, sources=3, entities=8, reports=5))
    t = r["totals"]
    assert t["total_days"] < t["manual_days"]
    assert 0 < r["automation"]["coverage"] < 1


def test_review_effort_is_never_zero_for_generated_work():
    """AI-generated output still has to be reviewed (§23)."""
    r = estimate([WorkItem("W1", "Pipelines", "pipeline", 10)])
    assert r["totals"]["review_days"] > 0


def test_manual_work_gets_no_automation_saving():
    r = estimate([WorkItem("W1", "Env setup", "environment", 2)])
    assert r["totals"]["saved_days"] == 0
    assert r["items"][0]["automation"] == Automation.MANUAL.value


def test_complexity_multipliers_increase_effort():
    simple = estimate([WorkItem("W", "p", "pipeline", 5)])
    hard = estimate([WorkItem("W", "p", "pipeline", 5,
                              Complexity(technical=1.5, data=1.4, governance=1.3))])
    assert hard["totals"]["total_days"] > simple["totals"]["total_days"]


def test_critical_path_follows_dependencies():
    r = estimate(work_items_from_project([{}] * 5, sources=2, entities=4, reports=3))
    path = r["duration"]["critical_path"]
    assert path[0] == "WI-DISC"
    assert r["duration"]["critical_path_days"] > 0


def test_estimate_handles_empty_input():
    assert estimate([])["ok"] is False


def test_effort_splits_by_role():
    r = estimate(work_items_from_project([{}] * 6, sources=2, entities=5, reports=4))
    assert "Data Engineer" in r["by_role"]
    assert sum(r["by_role"].values()) == pytest.approx(r["totals"]["total_days"], abs=0.5)


# ------------------------------------------------------------------ SOW §26
def _statements():
    return [{"kind": "requirement", "text": "Near-real-time refresh"},
            {"kind": "objective", "text": "Modernize the platform"},
            {"kind": "risk", "text": "Legacy schema is undocumented"},
            {"kind": "assumption", "text": "Azure is the approved cloud"}]


def test_sow_contains_every_specified_section():
    from core.sow import SECTIONS
    sow = build_sow({"name": "P", "intent": "i", "version": 1}, _statements())
    assert set(SECTIONS) <= set(sow["sections"])


def test_sow_is_not_issuable_while_questions_are_open():
    stmts = _statements() + [{"kind": "unknown", "text": "What are the data volumes?"}]
    sow = build_sow({"name": "P", "intent": "i", "version": 1}, stmts)
    assert sow["issuable"] is False
    assert sow["open_questions"] == ["What are the data volumes?"]


def test_sow_marks_missing_sections_rather_than_inventing_them():
    """An SOW that invents scope is a commercial liability (§68)."""
    sow = build_sow({"name": "P", "intent": "", "version": 1}, [])
    assert sow["completeness"]["incomplete_sections"]
    assert sow["issuable"] is False
    assert "Requires customer input" in json.dumps(sow["sections"])


def test_sow_never_commits_pricing():
    est = estimate(work_items_from_project([{}] * 5, sources=2, entities=4, reports=2))
    sow = build_sow({"name": "P", "intent": "i", "version": 2}, _statements(), est)
    commercial = sow["sections"]["commercial_inputs"]
    assert all(v is None for v in commercial["rate_card"].values())
    assert "does not set or commit pricing" in commercial["note"]


def test_sow_uses_the_estimate_when_available():
    est = estimate(work_items_from_project([{}] * 8, sources=3, entities=6, reports=4))
    sow = build_sow({"name": "P", "intent": "i", "version": 2}, _statements(), est)
    assert sow["sections"]["effort"]["with_contingency_days"] == \
        est["totals"]["with_contingency_days"]
    assert sow["sections"]["milestones"][0]["week"] >= 1


def test_sow_pins_the_project_version():
    sow = build_sow({"name": "P", "intent": "i", "version": 7}, _statements())
    assert sow["generated_from_project_version"] == 7


def test_markdown_render_flags_draft_status():
    sow = build_sow({"name": "P", "intent": "i", "version": 1},
                    _statements() + [{"kind": "unknown", "text": "Volumes?"}])
    md = render_markdown(sow)
    assert md.startswith("# Statement of Work")
    assert "DRAFT — not issuable" in md
    assert "Open Questions" in md
