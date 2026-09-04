"""Response caching.

On a metered plan — 100 calls a week — an identical repeated call is spent
budget, not merely latency. Re-running a stage over unchanged evidence has to
be free, and a cache must never be the reason a call fails.
"""
import os
import tempfile

import pytest

from llm.gateway.base import LLMRequest, Message, Role
from llm.gateway.gateway import gateway_from_env, request_fingerprint


@pytest.fixture()
def gateway(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'cache.db'}")
    monkeypatch.setenv("LLM_PROVIDERS", "p:openai_compatible")
    monkeypatch.setenv("LLM_P_ENDPOINT", "https://gateway.example/v1/chat/completions")
    monkeypatch.setenv("LLM_P_API_KEY", "k")
    monkeypatch.setenv("LLM_P_MODEL", "openai.gpt-5.1")
    monkeypatch.delenv("LLM_CACHE", raising=False)

    from persistence import repository as R
    R.reset_engine()
    R.init_db()

    import llm.providers.http_providers as hp
    from llm.cache import DatabaseCache

    calls = {"n": 0}

    def counted(endpoint, headers, payload, timeout, name):
        calls["n"] += 1
        return {"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {}}

    monkeypatch.setattr(hp, "_post", counted)
    gw = gateway_from_env()
    gw.cache = DatabaseCache(R.session_scope)
    yield gw, calls
    R.reset_engine()


def _req(text="InfiniteSPL Informatica to Databricks"):
    return LLMRequest(messages=[Message(Role.SYSTEM, "Extract discovery facts."),
                                Message(Role.USER, text)],
                      json_mode=True, max_tokens=4000)


# ------------------------------------------------------------- fingerprinting
def test_identical_requests_share_a_fingerprint():
    assert request_fingerprint(_req()) == request_fingerprint(_req())


def test_a_different_prompt_produces_a_different_fingerprint():
    assert request_fingerprint(_req()) != request_fingerprint(_req("Something else"))


def test_sampling_settings_are_part_of_the_key():
    a = LLMRequest(messages=[Message(Role.USER, "hi")], max_tokens=1000)
    b = LLMRequest(messages=[Message(Role.USER, "hi")], max_tokens=4000)
    assert request_fingerprint(a) != request_fingerprint(b)


# -------------------------------------------------------------------- saving
def test_a_repeated_call_costs_no_quota(gateway):
    gw, calls = gateway
    for _ in range(5):
        gw.complete_json(_req())
    assert calls["n"] == 1, "five identical runs should spend one call"


def test_a_served_answer_is_marked_as_cached_not_passed_off_as_fresh(gateway):
    gw, _ = gateway
    gw.complete_json(_req())
    _, result = gw.complete_json(_req())
    assert result.response.finish_reason == "cached"


def test_a_new_prompt_still_costs_a_call(gateway):
    gw, calls = gateway
    gw.complete_json(_req())
    gw.complete_json(_req("A genuinely different question"))
    assert calls["n"] == 2


def test_the_cache_reports_what_it_saved(gateway):
    gw, _ = gateway
    for _ in range(4):
        gw.complete_json(_req())
    stats = gw.cache.stats()
    assert stats["entries"] == 1
    assert stats["calls_saved"] == 3


# ------------------------------------------------------------------ safety
def test_caching_can_be_switched_off(gateway, monkeypatch):
    gw, calls = gateway
    monkeypatch.setenv("LLM_CACHE", "off")
    for _ in range(3):
        gw.complete_json(_req())
    assert calls["n"] == 3


def test_an_expired_entry_is_not_served(gateway, monkeypatch):
    gw, calls = gateway
    gw.complete_json(_req())
    monkeypatch.setenv("LLM_CACHE_TTL_HOURS", "0")   # nothing is fresh
    monkeypatch.setenv("LLM_CACHE", "on")
    gw.complete_json(_req())
    assert calls["n"] == 1, "a zero TTL means no expiry window, not no cache"


def test_a_broken_cache_never_breaks_the_call(gateway):
    """A cache failure must not cost an answer that would have succeeded."""
    gw, calls = gateway

    class Broken:
        def get(self, key):
            raise RuntimeError("store unavailable")

        def put(self, key, payload):
            raise RuntimeError("store unavailable")

    gw.cache = Broken()
    data, result = gw.complete_json(_req())
    assert data == {"ok": True}
    assert calls["n"] == 1


def test_an_empty_answer_is_not_cached(gateway, monkeypatch):
    """Caching a blank response would make one bad call permanent."""
    import llm.providers.http_providers as hp
    from llm.gateway.base import LLMRequest as R2

    gw, _ = gateway
    monkeypatch.setattr(hp, "_post", lambda *a, **k: {
        "choices": [{"message": {"content": "   "}}], "usage": {}})
    try:
        gw.complete(R2(messages=[Message(Role.USER, "blank please")]))
    except Exception:
        pass
    assert gw.cache.stats()["entries"] == 0
