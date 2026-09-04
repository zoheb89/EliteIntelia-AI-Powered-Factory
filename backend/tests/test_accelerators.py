"""Accelerator catalogue and applicability.

The catalogue is a map from a named capability to the lifecycle stages that
produce it. If it drifts from the lifecycle it starts promising capability the
platform does not have, so its structure is asserted, not assumed.
"""
from core.accelerators import (AI, CATALOGUE, DETERMINISTIC, HYBRID,
                               applicable, catalogue, validate)
from core.domain.lifecycle import STAGE_BY_ID


# ------------------------------------------------------------------ structure
def test_the_catalogue_is_structurally_sound():
    assert validate() == []


def test_every_accelerator_drives_at_least_one_real_stage():
    """An accelerator naming no stage — or a stage that does not exist —
    cannot actually be delivered."""
    for a in CATALOGUE:
        assert a.stages, f"{a.id} drives no stage"
        for stage in a.stages:
            assert stage in STAGE_BY_ID, f"{a.id} names unknown stage {stage}"


def test_accelerator_ids_are_unique():
    ids = [a.id for a in CATALOGUE]
    assert len(ids) == len(set(ids))


def test_the_catalogue_spans_the_delivery_lifecycle():
    """The claim is one backbone, not a point tool: discovery through operations."""
    covered = {s for a in CATALOGUE for s in a.stages}
    for stage in ("discovery", "requirements", "platform", "architecture", "data",
                  "ai", "bi", "engineering", "testing", "deployment", "operations",
                  "estimation", "sow", "governance"):
        assert stage in covered, f"no accelerator covers {stage}"


def test_deterministic_engines_own_the_calculating_work():
    """Effort, scope and platform scoring must not be model opinions."""
    by_id = {a.id: a for a in CATALOGUE}
    for acc in ("effort_automation", "sow_generation", "scope_control",
                "platform_selection", "requirements_traceability"):
        assert by_id[acc].engine == DETERMINISTIC, f"{acc} should be deterministic"


def test_grouping_returns_every_accelerator_exactly_once():
    grouped = catalogue()
    total = sum(len(c["accelerators"]) for c in grouped["categories"])
    assert total == grouped["count"] == len(CATALOGUE)
    assert sum(grouped["engines"].values()) == len(CATALOGUE)


# --------------------------------------------------------------- applicability
INFINITE_SPL = [
    "Re-engineer the Informatica Bronze and Gold pipeline from Microsoft Fabric "
    "into Databricks with incremental loading, CDC, data quality and reconciliation.",
    "Power BI reports must be validated against the new Gold layer.",
]


def test_evidence_selects_the_accelerators_it_calls_for():
    out = applicable(INFINITE_SPL)
    picked = {r["id"] for r in out["recommended"]}

    assert {"etl_migration", "cdc_incremental", "data_quality",
            "pipeline_generation", "semantic_model"} <= picked


def test_an_unmatched_accelerator_is_available_not_recommended():
    """"Your documents call for this" and "we also do this" are different claims."""
    out = applicable(INFINITE_SPL)
    assert "application_design" in {r["id"] for r in out["available"]}
    assert "application_design" not in {r["id"] for r in out["recommended"]}


def test_every_recommendation_cites_the_words_that_produced_it():
    for row in applicable(INFINITE_SPL)["recommended"]:
        assert row["matched_signals"], f"{row['id']} recommended with no signal"
        assert row["reason"].startswith("Evidence mentions")


def test_recommendations_are_ranked_by_strength_of_signal():
    rec = applicable(INFINITE_SPL)["recommended"]
    counts = [len(r["matched_signals"]) for r in rec]
    assert counts == sorted(counts, reverse=True)


def test_no_evidence_recommends_nothing():
    out = applicable([])
    assert out["recommended"] == []
    assert len(out["available"]) == len(CATALOGUE)


def test_completed_stages_are_reported_against_each_accelerator():
    out = applicable(INFINITE_SPL, completed_stages=["discovery", "evidence"])
    rfi = next(r for r in out["recommended"] + out["available"]
               if r["id"] == "rfi_response")
    assert "discovery" in rfi["stages_complete"]
    assert "questions" in rfi["stages_outstanding"]


def test_matching_is_reproducible():
    assert applicable(INFINITE_SPL) == applicable(INFINITE_SPL)


# ------------------------------------------------------------------- endpoints
def test_the_endpoints_serve_the_catalogue_and_a_project_view(tmp_path, monkeypatch):
    import importlib
    import os

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'acc.db'}")
    monkeypatch.setenv("LLM_PROVIDERS", "")
    for key in [k for k in os.environ if k.startswith(("ELITEINTELIA_", "CAPGEMINI_"))]:
        monkeypatch.delenv(key, raising=False)

    from persistence import repository as R
    R.reset_engine()
    R.init_db()
    import core.api_v2 as api_v2
    importlib.reload(api_v2)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(api_v2.router)
    c = TestClient(app)

    assert c.get("/api/v2/accelerators").json()["count"] == len(CATALOGUE)

    pid = c.post("/api/v2/projects",
                 json={"name": "P", "intent": INFINITE_SPL[0]}).json()["id"]
    d = c.get(f"/api/v2/projects/{pid}/accelerators").json()
    assert d["recommended_count"] > 0
    assert "migration" in d["categories_engaged"]
    assert c.get("/api/v2/projects/nope/accelerators").status_code == 404
    R.reset_engine()
