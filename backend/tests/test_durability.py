"""Storage durability detection.

Driven by a real deployment: the service ran on a Free instance while
`render.yaml` declared a persistent disk at /var/data. Disks require a paid
instance, so the disk was never attached and /var/data was ordinary container
storage. The database was wiped on every restart, which surfaced only as stale
engagement ids producing "Engagement not found" on pages that had worked
minutes earlier.
"""
import os

import pytest

from core.durability import assess


def test_declared_but_unattached_disk_is_flagged():
    """The exact production configuration: /var/data declared, never mounted."""
    r = assess(db_path="/var/data/cinvent.db", database_url="")
    assert r["durable"] is False
    assert "not actually mounted" in r["detail"]
    assert "persistent disk" in r["action"]


def test_the_warning_names_the_path():
    assert "/var/data/cinvent.db" in assess(db_path="/var/data/cinvent.db", database_url="")["detail"]


def test_plain_local_sqlite_is_not_durable():
    r = assess(db_path="data/cinvent.db", database_url="")
    assert r["durable"] is False
    assert r["backend"] == "sqlite"


def test_external_database_is_durable():
    r = assess(db_path="ignored", database_url="postgresql://user@host/db")
    assert r["durable"] is True
    assert r["backend"] == "external-database"
    assert r["action"] == ""


def test_sqlite_database_url_is_still_assessed_as_sqlite():
    """A sqlite:// URL is not an external database and must not pass."""
    r = assess(db_path="data/x.db", database_url="sqlite:///data/x.db")
    assert r["durable"] is False
    assert r["backend"] == "sqlite"


def test_root_is_not_treated_as_a_persistent_volume():
    """"/" is always a mount point; that must not read as an attached disk."""
    assert assess(db_path="/tmp/x.db", database_url="")["durable"] is False


@pytest.mark.parametrize("mount", ["/var/data", "/data", "/mnt/data", "/persistent"])
def test_common_disk_mounts_are_recognised(mount):
    r = assess(db_path=f"{mount}/cinvent.db", database_url="")
    assert "not actually mounted" in r["detail"]


def test_assess_reads_the_environment_when_no_arguments_given(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u@h/d")
    assert assess()["durable"] is True
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("CINVENT_DB_PATH", "/var/data/cinvent.db")
    assert assess()["durable"] is False


def test_health_reports_storage_durability():
    """The UI needs this to warn before data is silently lost."""
    from fastapi.testclient import TestClient
    import api_server
    body = TestClient(api_server.app).get("/health").json()
    assert "storage" in body
    assert "durable" in body["storage"]
