"""Platform decision engine (§14), architecture and design agents (§15-§22)."""
import json
import os
import tempfile

import pytest

from agents_v2.architecture import ArchitectureAgent, PlatformSelectionAgent
from agents_v2.design import (
    AIDesignAgent, ApplicationDesignAgent, BIDesignAgent, DataDesignAgent,
    EngineeringAgent, GovernanceAgent, HandoverAgent, OperationsAgent, QAAgent,
)
from agents_v2.orchestrator import AGENTS, ENGINE_STAGES
from core.domain.lifecycle import STAGES
from core.platform_selection import CAPABILITIES, apply_decision, derive_criteria, evaluate
from core.tools.registry import build_project_tools
from llm.gateway.base import LLMError, ProviderConfig
from llm.gateway.gateway import LLMGateway


@pytest.fixture()
def repo():
    from persistence import repository as R
    os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'p.db')}"
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
    return LLMGateway([ProviderConfig(name="echo", kind="echo", model="m",
                                      extra={"response": json.dumps(response or {})})],
                      sleep=lambda _s: None)


AZURE_LAKEHOUSE = [
    "Migrate HMS data from on-prem SQL Server to Azure",
    "Implement governed Bronze, Silver and Gold medallion layers",
    "Automate CDC ingestion with data quality checks",
    "HIPAA compliance, PHI masking, lineage and audit required",
    "Near-real-time streaming refresh for admissions",
]
OPERATIONAL_APP = [
    "Build a transactional operational application with CRUD workflows",
    "Sub-second latency for online serving",
    "Minimise cost and licence spend",
    "Must run on-premises in our own data centre",
]


# ------------------------------------------------------- decision engine §14
def test_evaluation_is_deterministic():
    assert evaluate(AZURE_LAKEHOUSE) == evaluate(AZURE_LAKEHOUSE)


def test_engine_does_not_default_to_one_product():
    """§14: the decision must not start from 'use Databricks'."""
    lakehouse = evaluate(AZURE_LAKEHOUSE)["recommendation"]["platform"]
    app = evaluate(OPERATIONAL_APP)["recommendation"]["platform"]
    assert lakehouse != app, "different requirements must produce different winners"


def test_operational_low_latency_workload_picks_an_operational_store():
    assert evaluate(OPERATIONAL_APP)["recommendation"]["platform"] == "Azure SQL / PostgreSQL"


def test_gcp_direction_selects_a_gcp_platform():
    r = evaluate(["Analytics on Google Cloud BigQuery", "Warehouse and dashboards"])
    assert "gcp" in r["context"]["cloud_direction"]
    assert "gcp" in CAPABILITIES[r["recommendation"]["platform"]]["clouds"]


def test_criteria_weights_are_derived_from_requirement_text():
    criteria, ctx = derive_criteria(AZURE_LAKEHOUSE)
    weights = {c.name: c.weight for c in criteria}
    assert weights["governance"] > weights["cost_efficiency"]
    assert ctx["criteria_from_evidence"] > 0


def test_criteria_without_evidence_are_flagged():
    criteria, _ = derive_criteria(["Build a lakehouse"])
    unevidenced = [c for c in criteria if not c.derived]
    assert unevidenced, "criteria nobody mentioned must be marked as assumption-based"


def test_cloud_misalignment_is_penalised():
    aligned = evaluate(["Analytics on Azure with governance"])
    scores = {s["platform"]: s for s in aligned["scores"]}
    assert scores["BigQuery"]["cloud_aligned"] is False
    assert scores["Microsoft Fabric"]["cloud_aligned"] is True
    assert scores["Microsoft Fabric"]["fit"] > scores["BigQuery"]["fit"]


def test_three_options_with_reasoning():
    opts = evaluate(AZURE_LAKEHOUSE)["options"]
    assert [o["option"] for o in opts] == ["Option A", "Option B", "Option C"]
    assert opts[0]["recommended"] is True
    for o in opts:
        assert o["advantages"] and o["disadvantages"] and o["reasoning"]
        assert o["implementation_complexity"] in ("Low", "Medium", "High")


def test_recommendation_is_never_a_commitment():
    r = evaluate(AZURE_LAKEHOUSE)
    assert r["decision_status"] == "RECOMMENDED_PENDING_APPROVAL"
    assert "not a customer commitment" in r["note"]


def test_excluded_platform_is_disqualified():
    r = evaluate(AZURE_LAKEHOUSE, excluded=["Databricks"])
    dq = {s["platform"]: s for s in r["scores"]}["Databricks"]
    assert dq["disqualified"] and r["recommendation"]["platform"] != "Databricks"


def test_human_decision_may_override_the_recommendation():
    r = evaluate(AZURE_LAKEHOUSE)
    other = next(s["platform"] for s in r["scores"]
                 if s["platform"] != r["recommendation"]["platform"])
    decided = apply_decision(r, other, "Existing enterprise agreement.", "cto@customer")
    assert decided["selected_platform"] == other
    assert decided["followed_recommendation"] is False
    assert decided["decision_status"] == "DECIDED"


def test_decision_rejects_a_platform_that_was_not_scored():
    with pytest.raises(ValueError):
        apply_decision(evaluate(AZURE_LAKEHOUSE), "Imaginary DB")


def test_scores_expose_their_breakdown():
    top = evaluate(AZURE_LAKEHOUSE)["scores"][0]
    assert top["breakdown"] and "contribution" in top["breakdown"][0]


# ----------------------------------------------- platform selection agent §14
def _seed_requirements(repo, project):
    for t in AZURE_LAKEHOUSE:
        repo.add_statement(project.id, "requirement", t, provenance="AI_INFERENCE")


def test_agent_narrates_without_changing_the_ranking(repo):
    p = repo.create_project("P", intent="Modernize on Azure")
    _seed_requirements(repo, p)
    tools = build_project_tools(repo, p.id)
    expected = evaluate(AZURE_LAKEHOUSE + ["Modernize on Azure"])["recommendation"]["platform"]

    # The model tries to nominate a different platform; it must be ignored.
    out = PlatformSelectionAgent(
        _gw({"summary": "Use Amazon Redshift instead.",
             "decision_drivers": ["governance"], "risks": [], "questions_for_customer": []}),
        tools).run()

    decision = out.artifacts["platform_decision"]
    assert decision["recommended_platform"] == expected


def test_agent_marks_recommendation_provenance(repo):
    p = repo.create_project("P", intent="Azure lakehouse")
    _seed_requirements(repo, p)
    out = PlatformSelectionAgent(_gw({"summary": "s"}), build_project_tools(repo, p.id)).run()
    rec = next(s for s in out.statements
               if getattr(s, "kind", "") == "platform_recommendation")
    assert rec.provenance.value == "RECOMMENDATION"
    assert "human approval" in rec.text.lower()


def test_scoring_survives_provider_failure(repo):
    """Scoring never needed the model, so only narrative is lost (§44)."""
    p = repo.create_project("P", intent="Azure lakehouse")
    _seed_requirements(repo, p)
    out = PlatformSelectionAgent(_gw(fail=True), build_project_tools(repo, p.id)).run()
    assert out.generation_mode == "deterministic_evidence_only"
    assert out.artifacts["platform_decision"]["recommended_platform"]
    assert out.artifacts["platform_options"]["options"]


# ------------------------------------------------------ architecture agent §15
def test_architecture_agent_builds_components(repo):
    p = repo.create_project("P", intent="x")
    repo.save_artifact(p.id, "platform_decision",
                       json.dumps({"recommended_platform": "Databricks"}))
    payload = {"summary": "Layered lakehouse.",
               "components": [{"layer": "ingestion", "name": "CDC ingest",
                               "purpose": "Land source changes", "technology": "Databricks"}],
               "decisions": [{"decision": "Use medallion layering",
                              "rationale": "Auditability", "alternatives": ["Flat staging"]}],
               "data_flow": ["source", "bronze"], "risks": [], "unknowns": ["Volumes?"]}
    out = ArchitectureAgent(_gw(payload), build_project_tools(repo, p.id)).run()

    arch = out.artifacts["architecture"]
    assert arch["platform"] == "Databricks"
    assert arch["components"][0]["layer"] == "ingestion"
    assert arch["decisions"][0]["rationale"] == "Auditability"
    assert any(s.provenance.value == "UNKNOWN" for s in out.statements)


def test_architecture_fallback_is_labelled_as_a_pattern(repo):
    p = repo.create_project("P", intent="x")
    repo.save_artifact(p.id, "platform_decision",
                       json.dumps({"recommended_platform": "Snowflake"}))
    out = ArchitectureAgent(_gw(fail=True), build_project_tools(repo, p.id)).run()
    assert out.generation_mode == "deterministic_evidence_only"
    assert "standard pattern" in out.summary
    assert any("design review is required" in s.text for s in out.statements)


# ------------------------------------------------------- design agents §17-22
DESIGN_AGENTS = [DataDesignAgent, AIDesignAgent, BIDesignAgent,
                 ApplicationDesignAgent, GovernanceAgent, EngineeringAgent,
                 QAAgent, OperationsAgent, HandoverAgent]


@pytest.mark.parametrize("cls", DESIGN_AGENTS, ids=lambda c: c.id)
def test_design_agent_emits_its_artifact(repo, cls):
    p = repo.create_project("P", intent="x")
    repo.add_statement(p.id, "requirement", "Ingest orders daily")
    payload = {"summary": "done", **{k: [{"text": f"{k} item"}] for k in cls.sections},
               "unknowns": ["What is the volume?"]}
    out = cls(_gw(payload), build_project_tools(repo, p.id)).run()

    assert cls.produces in out.artifacts
    assert out.artifacts[cls.produces]["summary"] == "done"
    assert any(s.provenance.value == "UNKNOWN" for s in out.statements)


@pytest.mark.parametrize("cls", DESIGN_AGENTS, ids=lambda c: c.id)
def test_design_agent_fallback_asks_rather_than_invents(repo, cls):
    """A fabricated design is worse than an admitted gap (§68)."""
    p = repo.create_project("P", intent="x")
    out = cls(_gw(fail=True), build_project_tools(repo, p.id)).run()

    assert out.generation_mode == "deterministic_evidence_only"
    assert out.statements, f"{cls.id} produced nothing at all"
    assert all(s.provenance.value == "UNKNOWN" for s in out.statements)
    payload = out.artifacts[cls.produces]
    assert all(payload[k] == [] for k in cls.sections), "fallback must not invent content"


def test_data_agent_also_emits_metadata(repo):
    p = repo.create_project("P", intent="x")
    payload = {"summary": "s", "entities": [{"text": "Patient"}],
               "mappings": [{"text": "src.p -> silver.patient"}],
               "quality_rules": [{"text": "patient_id not null"}],
               "sources": [], "medallion": [], "unknowns": []}
    out = DataDesignAgent(_gw(payload), build_project_tools(repo, p.id)).run()
    assert out.artifacts["metadata"]["entities"] == ["Patient"]


def test_engineering_agent_also_emits_work_packages(repo):
    p = repo.create_project("P", intent="x")
    payload = {"summary": "s", "work_packages": [{"text": "WP-1 Ingest"}],
               "pipelines": [], "transformations": [], "orchestration": [],
               "tests": [], "unknowns": []}
    out = EngineeringAgent(_gw(payload), build_project_tools(repo, p.id)).run()
    assert out.artifacts["work_packages"]["packages"] == ["WP-1 Ingest"]


# --------------------------------------------------------------- coverage §2
def test_every_stage_has_a_handler():
    data_satisfied = {"intent", "evidence"}
    unhandled = [s.id for s in STAGES
                 if s.agent not in AGENTS
                 and s.id not in data_satisfied
                 and s.id not in ENGINE_STAGES]
    assert unhandled == [], f"stages with no handler: {unhandled}"


def test_no_agent_is_orphaned():
    owned = {s.agent for s in STAGES}
    assert [a for a in AGENTS if a not in owned] == []


def test_each_agent_produces_the_artifacts_its_stage_declares():
    """A stage that never emits its declared artifact can never complete."""
    from core.domain.lifecycle import STAGE_BY_ID
    for stage_id, stage in STAGE_BY_ID.items():
        cls = AGENTS.get(stage.agent)
        produces = getattr(cls, "produces", None)
        if cls and produces:
            assert produces in stage.produces, (
                f"{cls.id} emits '{produces}' but stage '{stage_id}' expects {stage.produces}")


# --------------------------------------------------- reachability regression
def test_every_declared_artifact_is_actually_produced():
    """Regression: `questions` declared `question_set` and `commercial` declared
    `commercial`, but nothing emitted either — so those stages could never
    complete and the deployment gate stayed shut forever.
    """
    from core.domain.lifecycle import STAGE_BY_ID

    # Artifact kinds emitted by the deterministic engines, via the API layer.
    ENGINE_ARTIFACTS = {
        "estimation": {"estimate", "automation_assessment"},
        "sow": {"sow"},
        "commercial": {"commercial"},
    }
    DATA_STAGES = {"intent", "evidence"}

    unreachable = []
    for sid, stage in STAGE_BY_ID.items():
        if sid in DATA_STAGES:
            continue
        if sid in ENGINE_ARTIFACTS:
            if not (set(stage.produces) & ENGINE_ARTIFACTS[sid]):
                unreachable.append(f"{sid}: engine emits {ENGINE_ARTIFACTS[sid]}, "
                                   f"stage declares {stage.produces}")
            continue
        cls = AGENTS.get(stage.agent)
        assert cls, f"stage '{sid}' has no agent"
        produces = getattr(cls, "produces", None)
        if produces and produces not in stage.produces:
            unreachable.append(f"{sid}: agent emits '{produces}', "
                               f"stage declares {stage.produces}")
    assert unreachable == [], "stages that can never complete: " + "; ".join(unreachable)


def test_question_set_agent_converts_unknowns(repo):
    from agents_v2.discovery import QuestionSetAgent
    p = repo.create_project("P", intent="x")
    repo.add_statement(p.id, "unknown", "What are the data volumes?", provenance="UNKNOWN")
    payload = {"questions": [{"question": "What are the daily record volumes per source?",
                              "why_it_matters": "Sizing", "options": ["<1M", "1-10M", ">10M"],
                              "owner_role": "Data Architect", "blocks": "architecture"}]}
    out = QuestionSetAgent(_gw(payload), build_project_tools(repo, p.id)).run()
    qs = out.artifacts["question_set"]["questions"]
    assert qs[0]["options"] == ["<1M", "1-10M", ">10M"]
    assert all(s.provenance.value == "UNKNOWN" for s in out.statements)


def test_question_set_fallback_carries_unknowns_forward(repo):
    from agents_v2.discovery import QuestionSetAgent
    p = repo.create_project("P", intent="x")
    repo.add_statement(p.id, "unknown", "Which regulations apply?", provenance="UNKNOWN")
    out = QuestionSetAgent(_gw(fail=True), build_project_tools(repo, p.id)).run()
    assert out.generation_mode == "deterministic_evidence_only"
    assert out.artifacts["question_set"]["questions"][0]["question"] == "Which regulations apply?"
