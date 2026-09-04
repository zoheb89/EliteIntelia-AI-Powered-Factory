from c_invent.services.platforms import derive_state


def test_databricks_verified_state_requires_verified_at(monkeypatch):
    monkeypatch.setenv("DATABRICKS_TOKEN", "test-token")
    cfg = {
        "platform": "Databricks",
        "decision_status": "selected",
        "environment_mode": "existing",
        "endpoint": "https://dbc-test.cloud.databricks.com",
        "credential_ref": "DATABRICKS_TOKEN",
        "verified_at": "2026-08-25T10:00:00+00:00",
    }
    assert derive_state(cfg)["state"] == "VERIFIED"


def test_unverified_customer_platform_is_not_ready_for_metadata():
    monkeypatch = None
    cfg = {
        "platform": "Databricks",
        "decision_status": "selected",
        "environment_mode": "existing",
        "endpoint": "https://dbc-test.cloud.databricks.com",
        "credential_ref": "",
    }
    assert derive_state(cfg)["state"] == "CREDENTIALS_REQUIRED"
