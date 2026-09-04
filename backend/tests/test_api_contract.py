from fastapi.testclient import TestClient

from api_server import app

client = TestClient(app)

def test_engagements_route_exists():
    r = client.get("/api/engagements")
    assert r.status_code == 200
    assert isinstance(r.json().get("items"), list)

def test_intake_multipart_contract():
    r = client.post(
        "/api/intake",
        data={"name": "Test Engagement", "text": "Automate RFP intake", "domain": "Finance"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "Intake captured"
    assert body["engagement_id"]

def test_validation_error_is_json_safe():
    r = client.post("/api/engagements/not-real/platform", content=b"\xb5")
    assert r.status_code in (400, 404, 422)
    # Most importantly, FastAPI must not turn a validation error into a 500
    assert r.status_code != 500
