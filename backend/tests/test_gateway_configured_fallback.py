"""The gateway must use whatever provider the deployment actually configured.

Settings reported "AI provider is working" while every v2 stage fell back to
evidence-only generation, because diagnostics exercised the client built from
`ELITEINTELIA_*` while the gateway only registered providers declared through
`LLM_PROVIDERS`. One configuration, two answers.
"""
import pytest

from llm.gateway.base import ProviderConfig
from llm.gateway.gateway import gateway_from_env
from llm.providers.configured_client import ConfiguredClientProvider


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ("LLM_PROVIDERS", "LLM_ENDPOINT", "LLM_API_KEY", "LLM_MODEL",
                "LLM_DEFAULT_PROVIDER", "ELITEINTELIA_LLM_BASE_URL",
                "ELITEINTELIA_LLM_API_KEY", "CAPGEMINI_LLM_BASE_URL",
                "CAPGEMINI_LLM_API_KEY"):
        monkeypatch.delenv(key, raising=False)


def test_vendor_neutral_settings_alone_configure_the_gateway(monkeypatch):
    monkeypatch.setenv("ELITEINTELIA_LLM_BASE_URL", "https://provider.example/invoke")
    monkeypatch.setenv("ELITEINTELIA_LLM_API_KEY", "key")

    names = [p["name"] for p in gateway_from_env().describe()]
    assert names == ["configured"], "a configured client must reach the gateway"


def test_legacy_prefixed_settings_also_configure_the_gateway(monkeypatch):
    monkeypatch.setenv("CAPGEMINI_LLM_BASE_URL", "https://provider.example/invoke")
    monkeypatch.setenv("CAPGEMINI_LLM_API_KEY", "key")

    assert [p["name"] for p in gateway_from_env().describe()] == ["configured"]


def test_an_explicit_declaration_still_wins(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDERS", "sandbox:echo")
    monkeypatch.setenv("ELITEINTELIA_LLM_BASE_URL", "https://provider.example/invoke")
    monkeypatch.setenv("ELITEINTELIA_LLM_API_KEY", "key")

    described = gateway_from_env().describe()
    assert [p["kind"] for p in described] == ["echo"]


def test_nothing_configured_registers_nothing():
    assert gateway_from_env().describe() == []


def test_the_adapter_reports_unconfigured_rather_than_calling_out():
    from llm.gateway.base import LLMNotConfigured, LLMRequest, Message, Role

    provider = ConfiguredClientProvider(
        ProviderConfig(name="configured", kind="configured_client"))
    assert provider.is_configured() is False
    with pytest.raises(LLMNotConfigured):
        provider.complete(LLMRequest(messages=[Message(Role.USER, "hello")]))


def test_quota_failures_are_retryable_so_failover_can_engage(monkeypatch):
    from llm.gateway.base import LLMError, LLMRequest, Message, Role

    monkeypatch.setenv("ELITEINTELIA_LLM_BASE_URL", "https://provider.example/invoke")
    monkeypatch.setenv("ELITEINTELIA_LLM_API_KEY", "key")

    import c_invent.llm.capgemini as cap
    monkeypatch.setattr(cap.CapgeminiLLM, "invoke",
                        lambda *a, **k: (_ for _ in ()).throw(
                            RuntimeError("Quota exceeded for this month")))

    provider = ConfiguredClientProvider(
        ProviderConfig(name="configured", kind="configured_client"))
    with pytest.raises(LLMError) as excinfo:
        provider.complete(LLMRequest(messages=[Message(Role.USER, "hi")]))
    assert excinfo.value.retryable is True


def test_a_stage_runs_in_ai_mode_when_only_the_client_is_configured(monkeypatch, tmp_path):
    """The end-to-end shape of the reported bug."""
    import importlib
    import json
    import os

    import c_invent.llm.capgemini as cap
    monkeypatch.setattr(cap.CapgeminiLLM, "invoke", lambda *a, **k: json.dumps({
        "objectives": ["Modernise the nominated pipeline"],
        "requirements": [{"text": "Metadata-driven configuration"}],
        "unknowns": [], "actors": [], "systems": [], "processes": [],
        "summary": "Derived from the tracker."}))
    monkeypatch.setenv("ELITEINTELIA_LLM_BASE_URL", "https://provider.example/invoke")
    monkeypatch.setenv("ELITEINTELIA_LLM_API_KEY", "key")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'ai.db'}")

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

    pid = c.post("/api/v2/projects", json={"name": "P", "intent": "Modernise."}).json()["id"]
    c.post(f"/api/v2/projects/{pid}/evidence",
           files={"file": ("r.csv", "Req ID,Requirement\nR-1,Something required\n", "text/csv")})
    out = c.post(f"/api/v2/projects/{pid}/stages/discovery",
                 json={"background": False}).json()["output"]

    assert out["generation_mode"] == "ai"
    assert out["degraded"] is False
    assert c.get(f"/api/v2/projects/{pid}/lifecycle").json()["generation"]["any_degraded"] is False

    R.reset_engine()
    os.environ.pop("DATABASE_URL", None)


def test_the_adapter_returns_text_not_the_client_envelope(monkeypatch):
    """The client answers with {"content": ..., "raw": ...}, not a string.

    Passing that mapping through as `text` left JSON-mode callers parsing a
    dict, so a healthy provider still produced evidence-only stages.
    """
    from llm.gateway.base import LLMRequest, Message, Role

    monkeypatch.setenv("ELITEINTELIA_LLM_BASE_URL", "https://provider.example/invoke")
    monkeypatch.setenv("ELITEINTELIA_LLM_API_KEY", "key")

    import c_invent.llm.capgemini as cap
    monkeypatch.setattr(cap.CapgeminiLLM, "invoke", lambda *a, **k: {
        "content": '{"objectives": ["Modernise"]}',
        "raw": {"metadata": {"usage": {"total_tokens": 33}}}})

    provider = ConfiguredClientProvider(
        ProviderConfig(name="configured", kind="configured_client"))
    response = provider.complete(LLMRequest(messages=[Message(Role.USER, "hi")]))

    assert isinstance(response.text, str)
    assert response.text == '{"objectives": ["Modernise"]}'
    assert response.usage.completion_tokens > 0
    assert response.raw == {"metadata": {"usage": {"total_tokens": 33}}}


def test_json_mode_parses_a_real_provider_envelope(monkeypatch):
    """complete_json must reach a parsed object through the configured client."""
    from llm.gateway.base import LLMRequest, Message, Role
    from llm.gateway.gateway import LLMGateway

    monkeypatch.setenv("ELITEINTELIA_LLM_BASE_URL", "https://provider.example/invoke")
    monkeypatch.setenv("ELITEINTELIA_LLM_API_KEY", "key")

    import c_invent.llm.capgemini as cap
    monkeypatch.setattr(cap.CapgeminiLLM, "invoke", lambda *a, **k: {
        "content": '```json\n{"requirements": [{"text": "Incremental load"}]}\n```',
        "raw": {}})

    gw = LLMGateway()
    gw.register(ProviderConfig(name="configured", kind="configured_client"))
    data, _ = gw.complete_json(
        LLMRequest(messages=[Message(Role.USER, "extract")], json_mode=True))

    assert data == {"requirements": [{"text": "Incremental load"}]}


def test_the_request_token_budget_reaches_the_client(monkeypatch):
    """The gateway's per-request budget was dropped, pinning every call to the
    deployment default — too small for a structured record on a reasoning model."""
    from llm.gateway.base import LLMRequest, Message, Role

    monkeypatch.setenv("ELITEINTELIA_LLM_BASE_URL", "https://provider.example/invoke")
    monkeypatch.setenv("ELITEINTELIA_LLM_API_KEY", "key")

    seen = {}

    def capture(self, text, system_prompt="", **kw):
        seen.update(kw.get("extra_params") or {})
        return {"content": "ok", "raw": {}}

    import c_invent.llm.capgemini as cap
    monkeypatch.setattr(cap.CapgeminiLLM, "invoke", capture)

    provider = ConfiguredClientProvider(
        ProviderConfig(name="configured", kind="configured_client"))
    provider.complete(LLMRequest(messages=[Message(Role.USER, "hi")], max_tokens=4000))

    assert seen.get("maxTokens") == 4000


def test_an_empty_completion_is_reported_not_swallowed(monkeypatch):
    """An exhausted budget returns "" rather than an error. Falling back on it
    silently made a working provider indistinguishable from an outage."""
    from llm.gateway.base import LLMError, LLMRequest, Message, Role

    monkeypatch.setenv("ELITEINTELIA_LLM_BASE_URL", "https://provider.example/invoke")
    monkeypatch.setenv("ELITEINTELIA_LLM_API_KEY", "key")

    import c_invent.llm.capgemini as cap
    monkeypatch.setattr(cap.CapgeminiLLM, "invoke",
                        lambda *a, **k: {"content": "   ", "raw": {}})

    provider = ConfiguredClientProvider(
        ProviderConfig(name="configured", kind="configured_client"))
    with pytest.raises(LLMError) as excinfo:
        provider.complete(LLMRequest(messages=[Message(Role.USER, "hi")], max_tokens=1200))

    assert "returned no content" in str(excinfo.value)
    assert excinfo.value.retryable is True, "a retry normally recovers this"


def test_an_empty_completion_is_retried_and_recovers(monkeypatch):
    """The empty response is intermittent, so the gateway must try again."""
    from llm.gateway.base import LLMRequest, Message, Role
    from llm.gateway.gateway import LLMGateway

    monkeypatch.setenv("ELITEINTELIA_LLM_BASE_URL", "https://provider.example/invoke")
    monkeypatch.setenv("ELITEINTELIA_LLM_API_KEY", "key")

    calls = {"n": 0}

    def flaky(self, text, system_prompt="", **kw):
        calls["n"] += 1
        return {"content": "" if calls["n"] == 1 else '{"objectives": ["Automate"]}',
                "raw": {}}

    import c_invent.llm.capgemini as cap
    monkeypatch.setattr(cap.CapgeminiLLM, "invoke", flaky)

    gw = LLMGateway()
    gw.register(ProviderConfig(name="configured", kind="configured_client",
                               max_retries=3))
    gw._sleep = lambda _s: None
    data, _ = gw.complete_json(
        LLMRequest(messages=[Message(Role.USER, "extract")], json_mode=True))

    assert calls["n"] == 2, "the empty first response should have been retried"
    assert data == {"objectives": ["Automate"]}


def test_the_auto_registered_provider_actually_retries(monkeypatch):
    monkeypatch.setenv("ELITEINTELIA_LLM_BASE_URL", "https://provider.example/invoke")
    monkeypatch.setenv("ELITEINTELIA_LLM_API_KEY", "key")

    gw = gateway_from_env()
    assert gw._configs["configured"].max_retries > 1


# ------------------------------------------------------- multi-provider failover
def test_a_quota_blocked_provider_fails_over_to_a_second_one(monkeypatch):
    """The remedy the diagnostics recommend has to actually work.

    With one provider, a weekly quota refusal degrades every stage to
    evidence-only. Declaring a second means the stage keeps its AI output.
    """
    import llm.providers.http_providers as hp
    from llm.gateway.base import LLMRequest, Message, Role
    from llm.gateway.gateway import gateway_from_env

    monkeypatch.setenv("LLM_PROVIDERS", "capgemini:configured_client,claude:anthropic")
    monkeypatch.setenv("LLM_CLAUDE_API_KEY", "sk-ant-test")
    monkeypatch.setenv("LLM_CLAUDE_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("ELITEINTELIA_LLM_BASE_URL", "https://provider.example/invoke")
    monkeypatch.setenv("ELITEINTELIA_LLM_API_KEY", "cg-key")

    import c_invent.llm.capgemini as cap
    monkeypatch.setattr(cap.CapgeminiLLM, "invoke", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("Weekly API call limit exceeded. You used all 100 LLM API calls.")))

    seen = {}

    def fake_post(endpoint, headers, payload, timeout, name):
        seen["endpoint"] = endpoint
        seen["auth"] = headers.get("x-api-key")
        seen["version"] = headers.get("anthropic-version")
        seen["system"] = payload.get("system")
        return {"content": [{"type": "text", "text": '{"objectives": ["Modernise"]}'}],
                "usage": {"input_tokens": 120, "output_tokens": 18},
                "stop_reason": "end_turn"}

    monkeypatch.setattr(hp, "_post", fake_post)

    gw = gateway_from_env()
    gw._sleep = lambda _s: None
    assert [p["name"] for p in gw.describe()] == ["capgemini", "claude"]

    data, result = gw.complete_json(LLMRequest(
        messages=[Message(Role.SYSTEM, "Extract discovery facts."),
                  Message(Role.USER, "InfiniteSPL POC")], json_mode=True))

    assert data == {"objectives": ["Modernise"]}
    assert result.response.provider == "claude"
    assert result.response.usage.total_tokens == 138

    # The Anthropic contract: system is a top-level field, not a message.
    assert "api.anthropic.com" in seen["endpoint"]
    assert seen["auth"] == "sk-ant-test"
    assert seen["version"]
    assert seen["system"] == "Extract discovery facts."

    # A weekly quota is not worth retrying — it should hand over immediately.
    attempts = [c for c in result.calls if c.provider == "capgemini"]
    assert len(attempts) == 1, "a hard quota should fail over without retrying"


def test_json_mode_can_be_switched_off_for_a_gateway_that_rejects_it(monkeypatch):
    """Not every OpenAI-compatible gateway accepts response_format, and one
    that rejects it fails the entire call."""
    import llm.providers.http_providers as hp
    from llm.gateway.base import LLMRequest, Message, Role
    from llm.gateway.gateway import gateway_from_env

    for key in [k for k in __import__("os").environ
                if k.startswith(("LLM_", "ELITEINTELIA_", "CAPGEMINI_"))]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LLM_PROVIDERS", "gw:openai_compatible")
    monkeypatch.setenv("LLM_GW_ENDPOINT", "https://gateway.example/v1/chat/completions")
    monkeypatch.setenv("LLM_GW_API_KEY", "k")
    monkeypatch.setenv("LLM_GW_AUTH_HEADER", "x-api-key")
    monkeypatch.setenv("LLM_GW_AUTH_SCHEME", "")

    seen = {}

    def fake_post(endpoint, headers, payload, timeout, name):
        seen["payload"] = payload
        seen["headers"] = headers
        return {"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {}}

    monkeypatch.setattr(hp, "_post", fake_post)
    request = LLMRequest(messages=[Message(Role.USER, "hi")], json_mode=True)

    monkeypatch.setenv("LLM_GW_JSON_MODE", "off")
    gateway_from_env().complete_json(request)
    assert "response_format" not in seen["payload"]

    monkeypatch.setenv("LLM_GW_JSON_MODE", "on")
    gateway_from_env().complete_json(request)
    assert seen["payload"]["response_format"] == {"type": "json_object"}

    # A custom auth header must not be prefixed with a bearer scheme.
    assert seen["headers"]["x-api-key"] == "k"


def test_a_none_auth_scheme_sends_the_key_bare(monkeypatch):
    """Render often cannot store an empty value, so "none" has to mean no
    scheme — otherwise the header reads "none <key>" and authentication fails
    in a way that looks like a bad key."""
    import llm.providers.http_providers as hp
    from llm.gateway.base import LLMRequest, Message, ProviderConfig, Role

    seen = {}
    monkeypatch.setattr(hp, "_post", lambda e, h, p, t, n: (
        seen.update(headers=h),
        {"choices": [{"message": {"content": "ok"}}], "usage": {}})[1])

    for scheme in ("none", "NONE", "", "-"):
        hp.OpenAICompatibleProvider(ProviderConfig(
            name="cg", kind="openai_compatible", endpoint="https://x/v1/chat/completions",
            api_key="cg-key", model="m", auth_header="x-api-key", auth_scheme=scheme,
        )).complete(LLMRequest(messages=[Message(Role.USER, "hi")]))
        assert seen["headers"]["x-api-key"] == "cg-key", f"scheme={scheme!r}"

    # A real scheme is still applied.
    hp.OpenAICompatibleProvider(ProviderConfig(
        name="oai", kind="openai_compatible", endpoint="https://x/v1/chat/completions",
        api_key="sk-1", model="m", auth_header="Authorization", auth_scheme="Bearer",
    )).complete(LLMRequest(messages=[Message(Role.USER, "hi")]))
    assert seen["headers"]["Authorization"] == "Bearer sk-1"
