"""Scope Lock and Change Request.

Effort, commercial, SOW and the delivery plan are all priced against a set of
requirements that was true at a moment in time. Without a freeze, a regenerated
stage silently widens what was agreed and nobody can answer "what changed after
we signed?".
"""
from dataclasses import dataclass

import pytest

from core.scope_lock import change_request, diff, lock, readiness, snapshot


@dataclass
class S:
    kind: str
    text: str
    ref: str = ""
    provenance: str = "FACT"


def _scope(*texts):
    return [S("requirement", t, ref=f"R-{i:03d}") for i, t in enumerate(texts, 1)]


# ------------------------------------------------------------------ snapshot
def test_the_same_scope_always_produces_the_same_hash():
    a = snapshot(_scope("Metadata-driven config", "Incremental loading"))
    b = snapshot(_scope("Metadata-driven config", "Incremental loading"))
    assert a["hash"] == b["hash"]


def test_ordering_and_whitespace_do_not_read_as_a_scope_change():
    """A re-run returning the same requirements differently ordered is not drift."""
    one = snapshot([S("requirement", "Alpha", "R-1"), S("requirement", "Beta", "R-2")])
    two = snapshot([S("requirement", "Beta", "R-2"), S("requirement", "Alpha  ", "R-1")])
    assert one["hash"] == two["hash"]


def test_only_scope_bearing_statements_are_frozen():
    snap = snapshot([S("requirement", "In scope", "R-1"),
                     S("risk", "Might slip"), S("unknown", "Who owns this?")])
    assert snap["count"] == 1
    assert snap["by_kind"]["requirement"] == 1


def test_changing_a_requirement_changes_the_hash():
    before = snapshot(_scope("Incremental loading"))
    after = snapshot(_scope("Incremental loading with watermarking"))
    assert before["hash"] != after["hash"]


# ----------------------------------------------------------------- readiness
def test_unresolved_scope_blocks_a_responsible_freeze():
    snap = snapshot([S("requirement", "Something vague", "R-1", "UNKNOWN")])
    r = readiness(snap, open_questions=3)

    assert r["ready"] is False
    assert any("UNKNOWN" in b for b in r["blockers"])
    assert any("3 customer questions" in b for b in r["blockers"])


def test_a_clean_scope_is_ready():
    assert readiness(snapshot(_scope("A clear requirement")), 0)["ready"] is True


def test_an_empty_scope_cannot_be_locked():
    assert readiness(snapshot([]), 0)["ready"] is False


# ---------------------------------------------------------------------- lock
def test_a_lock_records_who_froze_it_and_what_was_waived():
    snap = snapshot(_scope("A requirement"))
    record = lock(snap, "zoheb@wiseprotech.com", acknowledged_blockers=["2 open questions"])

    assert record["hash"] == snap["hash"]
    assert record["locked_by"] == "zoheb@wiseprotech.com"
    assert record["acknowledged_blockers"] == ["2 open questions"]
    assert record["state"] == "LOCKED"


# ---------------------------------------------------------------------- diff
def test_an_addition_after_the_lock_is_detected():
    locked = lock(snapshot(_scope("Alpha")), "human")
    d = diff(locked, snapshot(_scope("Alpha", "Beta")))

    assert d["changed"] is True
    assert [i["text"] for i in d["added"]] == ["Beta"]
    assert d["net_change"] == 1


def test_a_removal_after_the_lock_is_detected():
    locked = lock(snapshot(_scope("Alpha", "Beta")), "human")
    d = diff(locked, snapshot([S("requirement", "Alpha", "R-001")]))

    assert [i["text"] for i in d["removed"]] == ["Beta"]
    assert d["net_change"] == -1


def test_a_reworded_requirement_reads_as_modified_not_as_a_swap():
    """Matching by ref keeps a rewrite from looking like a delete plus an add."""
    locked = lock(snapshot([S("requirement", "Load daily", "R-001")]), "human")
    d = diff(locked, snapshot([S("requirement", "Load hourly", "R-001")]))

    assert d["added"] == [] and d["removed"] == []
    assert d["modified"] == [{"ref": "R-001", "from": "Load daily", "to": "Load hourly"}]


def test_an_unchanged_scope_reports_no_drift():
    snap = snapshot(_scope("Alpha"))
    assert diff(lock(snap, "human"), snap)["changed"] is False


# ------------------------------------------------------------ change request
def test_a_change_request_states_what_moved():
    locked = lock(snapshot(_scope("Alpha")), "human")
    cr = change_request(diff(locked, snapshot(_scope("Alpha", "Beta"))), "zoheb")

    assert cr["id"] == "CR-001"
    assert cr["state"] == "DRAFT"
    assert cr["requires_approval"] is True
    assert "1 statements added" in cr["summary"]
    assert cr["against_lock"] == locked["hash"]


def test_effort_is_left_unassessed_rather_than_invented():
    """A number in front of a customer must have something standing behind it."""
    locked = lock(snapshot(_scope("Alpha")), "human")
    cr = change_request(diff(locked, snapshot(_scope("Alpha", "Beta"))), "zoheb")

    assert cr["impact"]["effort"]["assessed"] is False
    assert cr["impact"]["effort"]["days"] is None
    assert cr["impact"]["cost"]["assessed"] is False


def test_effort_is_quantified_when_a_measured_rate_exists():
    locked = lock(snapshot(_scope("Alpha")), "human")
    cr = change_request(diff(locked, snapshot(_scope("Alpha", "Beta", "Gamma"))),
                        "zoheb", effort_per_requirement_days=3.5)

    assert cr["impact"]["effort"]["assessed"] is True
    assert cr["impact"]["effort"]["days"] == 7.0


# ------------------------------------------------------------------ endpoints
def test_the_scope_endpoints_govern_a_real_project(tmp_path, monkeypatch):
    import importlib
    import os

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'scope.db'}")
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

    pid = c.post("/api/v2/projects", json={"name": "P", "intent": "Build."}).json()["id"]
    for i, t in enumerate(["Metadata-driven config", "Incremental loading"], 1):
        c.post(f"/api/v2/projects/{pid}/statements",
               json={"kind": "requirement", "text": t, "provenance": "FACT",
                     "ref": f"R-{i:03d}",
                     "evidence": [{"evidence_id": "e1", "locator": "row1"}]})

    # A change request needs something to change against.
    assert c.post(f"/api/v2/projects/{pid}/scope/change-request",
                  json={}).json()["detail"]["code"] == "NOT_LOCKED"

    locked = c.post(f"/api/v2/projects/{pid}/scope/lock",
                    json={"locked_by": "zoheb"}).json()
    assert locked["version"] == 1 and locked["scope_count"] == 2

    assert c.get(f"/api/v2/projects/{pid}/scope").json()["drift"]["changed"] is False
    assert c.post(f"/api/v2/projects/{pid}/scope/change-request",
                  json={}).json()["detail"]["code"] == "NO_CHANGE"

    c.post(f"/api/v2/projects/{pid}/statements",
           json={"kind": "requirement", "text": "Real-time alerting", "provenance": "FACT",
                 "ref": "R-003", "evidence": [{"evidence_id": "e1", "locator": "row9"}]})

    assert c.get(f"/api/v2/projects/{pid}/scope").json()["drift"]["net_change"] == 1
    cr = c.post(f"/api/v2/projects/{pid}/scope/change-request",
                json={"raised_by": "zoheb", "reason": "Customer request"}).json()
    assert cr["id"] == "CR-001"
    assert cr["against_lock"] == locked["hash"]

    R.reset_engine()
