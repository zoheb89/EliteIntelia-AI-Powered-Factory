"""Core v2 API: lifecycle, provenance enforcement, change impact, audit."""
import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from persistence import repository as R

    os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'api.db')}"
    os.environ["LLM_PROVIDERS"] = "sandbox:echo"
    R.reset_engine()
    R.init_db()

    # Import after the env is set so the module-level gateway picks it up.
    import importlib
    import core.api_v2 as api_v2
    importlib.reload(api_v2)

    app = FastAPI()
    app.include_router(api_v2.router)
    yield TestClient(app)

    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("LLM_PROVIDERS", None)
    R.reset_engine()


def _project(c, name="P", **kw):
    return c.post("/api/v2/projects", json={"name": name, **kw}).json()["id"]


# ------------------------------------------------------------------ lifecycle
def test_lifecycle_is_served_as_data(client):
    d = client.get("/api/v2/lifecycle").json()
    assert len(d["stages"]) == 20
    assert "DISCOVERY" in d["groups"]
    assert {p["value"] for p in d["provenance"]} >= {"FACT", "UNKNOWN", "CUSTOMER_DECISION"}


def test_new_project_starts_at_the_first_stage(client):
    pid = _project(client)
    d = client.get(f"/api/v2/projects/{pid}/lifecycle").json()
    assert d["progress"] == {"complete": 0, "total": 20}
    assert d["next_stage"]["id"] == "intent"


def test_downstream_stage_reports_its_blockers(client):
    pid = _project(client)
    d = client.get(f"/api/v2/projects/{pid}/lifecycle").json()
    assert d["stages"]["discovery"]["blockers"]


def test_unknown_project_returns_404(client):
    assert client.get("/api/v2/projects/does-not-exist/lifecycle").status_code == 404


# ------------------------------------------------------- provenance guard §68
def test_fact_without_evidence_is_downgraded_at_the_api(client):
    pid = _project(client)
    r = client.post(f"/api/v2/projects/{pid}/statements",
                    json={"kind": "requirement", "text": "HIPAA required",
                          "provenance": "FACT"}).json()
    assert r["provenance"] == "AI_INFERENCE"
    assert r["confidence"] == "LOW"
    assert "Downgraded" in r["note"]


def test_fact_with_evidence_is_preserved(client):
    pid = _project(client)
    r = client.post(f"/api/v2/projects/{pid}/statements",
                    json={"kind": "requirement", "text": "SQL Server 2019",
                          "provenance": "FACT",
                          "evidence": [{"evidence_id": "e1", "locator": "p.12"}]}).json()
    assert r["provenance"] == "FACT"


def test_invalid_provenance_is_rejected(client):
    pid = _project(client)
    r = client.post(f"/api/v2/projects/{pid}/statements",
                    json={"kind": "requirement", "text": "x", "provenance": "DEFINITELY_TRUE"})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "BAD_PROVENANCE"


def test_customer_decision_is_preserved_without_evidence(client):
    """Only FACT requires a citation; a customer decision is self-evidencing."""
    pid = _project(client)
    r = client.post(f"/api/v2/projects/{pid}/statements",
                    json={"kind": "requirement", "text": "We choose Snowflake",
                          "provenance": "CUSTOMER_DECISION"}).json()
    assert r["provenance"] == "CUSTOMER_DECISION"


def test_unknowns_feed_the_question_set(client):
    pid = _project(client)
    client.post(f"/api/v2/projects/{pid}/statements",
                json={"kind": "unknown", "text": "What are the data volumes?",
                      "provenance": "UNKNOWN"})
    client.post(f"/api/v2/projects/{pid}/statements",
                json={"kind": "requirement", "text": "Daily refresh",
                      "provenance": "CUSTOMER_DECISION"})
    d = client.get(f"/api/v2/projects/{pid}/unknowns").json()
    assert d["count"] == 1
    assert d["items"][0]["text"] == "What are the data volumes?"


# ----------------------------------------------------------- change impact §31
def test_change_impact_lists_downstream_stages(client):
    pid = _project(client)
    d = client.get(f"/api/v2/projects/{pid}/impact/requirements").json()
    ids = {s["id"] for s in d["affected_stages"]}
    assert {"platform", "architecture", "sow"} <= ids


def test_change_impact_rejects_unknown_stage(client):
    pid = _project(client)
    assert client.get(f"/api/v2/projects/{pid}/impact/not-a-stage").status_code == 404


# ------------------------------------------------------------------ audit §59
def test_audit_records_project_creation(client):
    pid = _project(client, "Audited")
    actions = {e["action"] for e in client.get(f"/api/v2/projects/{pid}/audit").json()["items"]}
    assert "project.created" in actions


# ------------------------------------------------------------------- LLM §35
def test_providers_are_listed_without_leaking_keys(client):
    d = client.get("/api/v2/llm/providers").json()
    assert d["configured"] is True
    assert all(p["api_key"] in ("", "***") for p in d["providers"])


def test_completion_is_provider_neutral(client):
    r = client.post("/api/v2/llm/complete", json={"prompt": "hello"}).json()
    assert r["ok"] is True
    assert r["provider"] == "sandbox"


# ------------------------------------------------------------------- jobs §63
def test_unknown_job_returns_404(client):
    assert client.get("/api/v2/jobs/nope").status_code == 404
