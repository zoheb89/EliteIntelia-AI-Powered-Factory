from c_invent.services.platforms import derive_state, detect_platform

def test_endpoint_detection_is_not_verification():
    cfg={"platform":"Databricks","decision_status":"selected","environment_mode":"existing","endpoint":"https://dbc-123.cloud.databricks.com"}
    state=derive_state(cfg)
    assert detect_platform(cfg["endpoint"]) == "Databricks"
    assert state["state"] == "CREDENTIALS_REQUIRED"

def test_provisioning_requires_plan():
    cfg={"platform":"Snowflake","decision_status":"selected","environment_mode":"provision","cloud":"Azure"}
    assert derive_state(cfg)["state"] == "PROVISIONING_PLAN_REQUIRED"
    cfg["provisioning_plan"]={"platform":"Snowflake"}
    assert derive_state(cfg)["state"] == "PLAN_READY"

def test_unselected_has_no_platform_evidence():
    assert derive_state({})["state"] == "NOT_SELECTED"
