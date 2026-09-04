"""AI provider diagnostics.

There was no way to answer "is the LLM working?" from the app. The v2 endpoints
test the gateway, but delivery stages call the legacy client — so a passing
gateway test proved nothing about what Discovery would actually get.

These endpoints exercise `orch.llm`, the exact client the stages use.
"""
import pytest
from fastapi.testclient import TestClient

import api_server
from c_invent.llm.capgemini import CapgeminiLLMFormatError, CapgeminiLLMQuotaError

QUOTA = "⚠️ Weekly API call limit exceeded. You used all 100 LLM API calls allowed for your tier."


@pytest.fixture()
def client():
    return TestClient(api_server.app)


def test_status_reports_the_client_the_stages_use(client):
    d = client.get("/api/ai/status").json()
    assert d["client"] in ("CapgeminiLLM", "GatewayBackedLLM")
    assert "configured" in d and "message" in d


def test_status_never_returns_the_api_key(client):
    body = client.get("/api/ai/status").text
    key = api_server.settings.llm_api_key
    assert "api_key_present" in body
    if key:
        assert key not in body


def test_test_reports_success(client, monkeypatch):
    monkeypatch.setattr(api_server.orch.llm, "invoke",
                        lambda *a, **k: {"content": "ELITEINTELIA TEST SUCCESS", "raw": {}},
                        raising=False)
    d = client.post("/api/ai/test").json()
    assert d["ok"] is True and d["reachable"] is True
    assert "ELITEINTELIA TEST SUCCESS" in d["response_preview"]


def test_quota_is_distinguished_from_a_broken_endpoint(client, monkeypatch):
    """The operator must be able to tell "refused" from "unreachable"."""
    def quota(*_a, **_k):
        raise CapgeminiLLMQuotaError(f"The AI provider rejected the request: {QUOTA}")
    monkeypatch.setattr(api_server.orch.llm, "invoke", quota, raising=False)

    d = client.post("/api/ai/test").json()
    assert d["ok"] is False
    assert d["fault"] == "quota"
    assert d["reachable"] is True, "quota means the endpoint works; that must be visible"
    assert "limit exceeded" in d["message"].lower()
    assert "LLM_PROVIDERS" in d["remedy"]


def test_authentication_failure_is_identified(client, monkeypatch):
    def auth(*_a, **_k):
        raise RuntimeError("Capgemini HTTP 401: invalid api key")
    monkeypatch.setattr(api_server.orch.llm, "invoke", auth, raising=False)
    d = client.post("/api/ai/test").json()
    assert d["fault"] == "auth" and d["reachable"] is True


def test_unreachable_endpoint_is_identified(client, monkeypatch):
    def down(*_a, **_k):
        raise RuntimeError("Capgemini connection failed: NameResolutionError")
    monkeypatch.setattr(api_server.orch.llm, "invoke", down, raising=False)
    d = client.post("/api/ai/test").json()
    assert d["fault"] == "unreachable" and d["reachable"] is False


def test_timeout_is_identified(client, monkeypatch):
    def slow(*_a, **_k):
        raise RuntimeError("Capgemini gateway timed out after 3 bounded attempts")
    monkeypatch.setattr(api_server.orch.llm, "invoke", slow, raising=False)
    assert client.post("/api/ai/test").json()["fault"] == "timeout"


def test_every_failure_carries_a_remedy(client, monkeypatch):
    """A diagnosis without a next step is not a diagnosis."""
    for exc in (CapgeminiLLMQuotaError("quota exceeded"),
                CapgeminiLLMFormatError("bad json"),
                RuntimeError("Capgemini HTTP 401: nope"),
                RuntimeError("connection failed")):
        def raiser(*_a, _e=exc, **_k):
            raise _e
        monkeypatch.setattr(api_server.orch.llm, "invoke", raiser, raising=False)
        d = client.post("/api/ai/test").json()
        assert d["ok"] is False
        assert d.get("remedy"), f"no remedy for {type(exc).__name__}"


def test_test_reports_elapsed_time(client, monkeypatch):
    monkeypatch.setattr(api_server.orch.llm, "invoke",
                        lambda *a, **k: {"content": "ok", "raw": {}}, raising=False)
    assert isinstance(client.post("/api/ai/test").json()["elapsed_ms"], int)
