"""Degraded generation must be visible, and evidence-only runs must still
mine real content out of requirement trackers.

Both halves address the same failure: a run where the AI provider was
unavailable produced canned questions and looked, on the board, exactly
like a successful run.
"""
import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

TRACKER = (
    "Req ID,Requirement,Category,Priority,Vendor Response\n"
    "R-001,Metadata-driven pipeline configuration,Engineering,High,Supported\n"
    "R-002,Incremental loading with watermarking,Engineering,High,\n"
    "R-003,Restart and recovery from checkpoint,Reliability,High,\n"
    "R-004,Data quality rules Bronze to Silver,Data Quality,High,Supported\n"
)


@pytest.fixture()
def client():
    from persistence import repository as R

    monkey_cleared = {}

    os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'deg.db')}"
    # No provider configured at all, so every stage falls back. The vendor
    # neutral names are cleared too: the gateway now falls back to a client
    # configured that way, which would otherwise make this test machine-dependent.
    os.environ["LLM_PROVIDERS"] = ""
    for key in [k for k in os.environ
                if k.startswith(("ELITEINTELIA_", "CAPGEMINI_"))]:
        monkey_cleared[key] = os.environ.pop(key)
    R.reset_engine()
    R.init_db()

    import importlib
    import core.api_v2 as api_v2
    importlib.reload(api_v2)

    app = FastAPI()
    app.include_router(api_v2.router)
    yield TestClient(app)

    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("LLM_PROVIDERS", None)
    os.environ.update(monkey_cleared)
    R.reset_engine()


def _degraded_discovery(c):
    pid = c.post("/api/v2/projects", json={
        "name": "Tracker", "intent": "Build a data platform.",
    }).json()["id"]
    c.post(f"/api/v2/projects/{pid}/evidence",
           files={"file": ("rfi.csv", TRACKER, "text/csv")})
    run = c.post(f"/api/v2/projects/{pid}/stages/discovery",
                 json={"background": False}).json()
    return pid, run["output"]


# ------------------------------------------------- half 1: it is reported
def test_lifecycle_reports_which_stages_had_no_ai(client):
    pid, _ = _degraded_discovery(client)
    gen = client.get(f"/api/v2/projects/{pid}/lifecycle").json()["generation"]

    assert gen["any_degraded"] is True
    assert "discovery" in gen["degraded_stages"]
    assert "discovery" not in gen["ai_stages"]
    # The reason must carry the provider's own words, not a generic label.
    assert gen["reason"]


def test_each_stage_carries_its_generation_mode(client):
    pid, _ = _degraded_discovery(client)
    stages = client.get(f"/api/v2/projects/{pid}/lifecycle").json()["stages"]

    assert stages["discovery"]["generation_mode"] == "deterministic_evidence_only"
    # Stages that never ran must not be labelled either way.
    assert stages["architecture"]["generation_mode"] is None


def test_a_project_with_no_runs_is_not_reported_as_degraded(client):
    pid = client.post("/api/v2/projects", json={"name": "Empty"}).json()["id"]
    gen = client.get(f"/api/v2/projects/{pid}/lifecycle").json()["generation"]

    assert gen["any_degraded"] is False
    assert gen["degraded_stages"] == []


# --------------------------------- half 2: it still produces real content
def test_evidence_only_discovery_extracts_the_requirement_table(client):
    pid, _ = _degraded_discovery(client)
    items = client.get(f"/api/v2/projects/{pid}/statements",
                       params={"kind": "requirement"}).json()["items"]

    assert len(items) == 4, "every tracker row should become a statement"
    texts = " ".join(i["text"] for i in items)
    assert "Metadata-driven pipeline configuration" in texts
    assert "R-004" in texts
    # Rows read verbatim off the customer's own document are facts, and
    # must not be downgraded to guesses just because no AI ran.
    assert {i["provenance"] for i in items} == {"FACT"}


def test_canned_questions_do_not_replace_extracted_requirements(client):
    """The stored deliverable must carry the table, not five canned questions."""
    import json

    from persistence import repository as R

    pid, _ = _degraded_discovery(client)
    with R.session_scope() as s:
        tenant = R.Repository.ensure_tenant(s, "default", "Default Organization").id
        art = R.Repository(s, tenant).latest_artifact(pid, "discovery")
        payload = json.loads(art.content)

    assert len(payload.get("requirements") or []) == 4
    summary = payload.get("requirement_table_summary") or {}
    assert summary.get("requirement_count") == 4
    # Two rows carry a vendor response, two do not.
    assert summary.get("unanswered") == 2


def test_the_run_summary_says_the_output_is_evidence_only(client):
    _, payload = _degraded_discovery(client)

    assert payload["degraded"] is True
    assert payload["generation_mode"] == "deterministic_evidence_only"
    assert "AI enrichment was unavailable" in payload["summary"]
    assert "4 requirement rows" in payload["summary"]


def test_carried_forward_requirements_are_not_labelled_as_inference(client):
    """A stage that ran without AI must not emit AI-provenance statements."""
    pid, _ = _degraded_discovery(client)
    client.post(f"/api/v2/projects/{pid}/stages/assessment", json={"background": False})
    client.post(f"/api/v2/projects/{pid}/stages/requirements", json={"background": False})

    items = client.get(f"/api/v2/projects/{pid}/statements").json()["items"]
    carried = [i for i in items if (i.get("ref") or "").startswith("R-")]

    assert carried, "the requirements stage should carry discovery rows forward"
    assert not [i for i in carried if i["provenance"] == "AI_INFERENCE"], \
        "verbatim carry-forward claimed model inference that never ran"


def test_the_unanswered_note_does_not_duplicate_the_questions(client):
    pid, _ = _degraded_discovery(client)
    items = client.get(f"/api/v2/projects/{pid}/statements").json()["items"]

    notes = [i for i in items if "have no response recorded yet" in i["text"]]
    assert len(notes) <= 1, "the blanket note was recorded twice"
