"""Regression: a provider error must never be persisted as delivery evidence.

Observed in production: the AI gateway returned HTTP 200 with the body

    "⚠️ Weekly API call limit exceeded. You used all 100 LLM API calls..."

That message was stored as the Discovery artifact, the stage was marked
COMPLETE, and the lifecycle advanced to 3/8 on top of it.

Two defects combined:
  1. `invoke_json` returned `{"_raw": ...}` — a *success-shaped* value — when it
     could not parse JSON, so callers treated a failure as a result.
  2. The quota message arrived with a 200 status, so it was never recognised as
     an error at all.
"""
import json

import pytest

from c_invent.agents.orchestrator import _reject_unusable
from c_invent.llm.capgemini import (
    CapgeminiLLM, CapgeminiLLMError, CapgeminiLLMFormatError, CapgeminiLLMQuotaError,
)

QUOTA = ("⚠️ Weekly API call limit exceeded. You used all 100 LLM API calls allowed "
         "for your tier. Limit will reset on 2026-08-30 23:00 UTC. Please upgrade "
         "your plan for more requests.")


# ---------------------------------------------- provider errors sent as HTTP 200
def test_quota_message_is_rejected():
    with pytest.raises(CapgeminiLLMQuotaError) as exc:
        CapgeminiLLM._reject_provider_error(QUOTA)
    assert "limit exceeded" in str(exc.value).lower()


@pytest.mark.parametrize("body", [
    "Rate limit reached, please retry later.",
    "Quota exceeded for this billing period.",
    "Too many requests.",
    "Insufficient credits remaining.",
    "Request blocked by content policy.",
])
def test_common_provider_errors_are_rejected(body):
    with pytest.raises(CapgeminiLLMQuotaError):
        CapgeminiLLM._reject_provider_error(body)


def test_empty_response_is_rejected():
    with pytest.raises(CapgeminiLLMQuotaError):
        CapgeminiLLM._reject_provider_error("   ")


def test_a_real_completion_is_not_rejected():
    CapgeminiLLM._reject_provider_error('{"summary": "Modernize the HMS platform."}')


def test_long_analysis_mentioning_rate_limits_is_allowed():
    """A genuine answer may legitimately discuss rate limits or billing."""
    body = ("The target architecture must handle API rate limit conditions "
            "gracefully. Billing for the platform is consumption based. ") * 12
    assert len(body) > 1200
    CapgeminiLLM._reject_provider_error(body)


# ------------------------------------------------ unparseable output must raise
def test_format_error_is_a_provider_error_subclass():
    assert issubclass(CapgeminiLLMFormatError, CapgeminiLLMError)
    assert issubclass(CapgeminiLLMQuotaError, CapgeminiLLMError)


def test_invoke_json_raises_instead_of_returning_a_placeholder(monkeypatch):
    """The exact production path: unparseable output must not look like success."""
    llm = CapgeminiLLM.__new__(CapgeminiLLM)

    def fake_invoke(*_a, **_k):
        return {"content": "not json at all", "raw": {}}

    monkeypatch.setattr(llm, "invoke", fake_invoke, raising=False)
    with pytest.raises(CapgeminiLLMFormatError):
        CapgeminiLLM.invoke_json(llm, "prompt", "system")


# --------------------------------------------- orchestrator defence in depth
def test_raw_placeholder_is_rejected():
    """The exact payload that reached production."""
    poisoned = {"_raw": QUOTA, "_repair_raw": QUOTA}
    with pytest.raises(RuntimeError) as exc:
        _reject_unusable(poisoned, "Discovery")
    assert "did not return usable content" in str(exc.value)


@pytest.mark.parametrize("payload", [
    {"_raw": "x"}, {"_repair_raw": "x"}, {"_repair_error": "x"}, {"error": "boom"},
])
def test_all_placeholder_shapes_are_rejected(payload):
    with pytest.raises(RuntimeError):
        _reject_unusable(payload, "Discovery")


@pytest.mark.parametrize("payload", [None, {}, [], "text", 42])
def test_non_structured_results_are_rejected(payload):
    with pytest.raises(RuntimeError):
        _reject_unusable(payload, "Discovery")


def test_quota_text_hidden_in_a_valid_shape_is_rejected():
    """Even correctly-shaped JSON containing a provider error must not persist."""
    with pytest.raises(RuntimeError) as exc:
        _reject_unusable({"summary": QUOTA}, "Discovery")
    assert "rejected the request" in str(exc.value)


def test_a_real_discovery_payload_is_accepted():
    _reject_unusable({
        "summary": "Modernize the hospital HMS data platform.",
        "objectives": ["Migrate to a lakehouse"],
        "unknowns": ["Data volumes unknown"],
    }, "Discovery")


def test_long_legitimate_payload_mentioning_limits_is_accepted():
    """A large real result must not be rejected for discussing rate limits."""
    payload = {"summary": "Architecture must handle API rate limit conditions.",
               "requirements": [f"Requirement {i} with detail about billing and quota "
                                f"handling in the target platform." for i in range(40)]}
    assert len(json.dumps(payload)) > 1500
    _reject_unusable(payload, "Discovery")


def test_error_message_names_the_stage():
    with pytest.raises(RuntimeError) as exc:
        _reject_unusable({"_raw": QUOTA}, "Blueprint")
    assert "Blueprint" in str(exc.value)


# ------------------------------------------------- multi-provider failover
"""One provider's quota exhaustion must not degrade every stage."""
import os

from c_invent.llm.gateway_bridge import (
    GatewayBackedLLM, build_llm, multi_provider_configured,
)
from llm.gateway.base import LLMError, ProviderConfig
from llm.gateway.gateway import LLMGateway
from llm.providers import http_providers as hp


class _Exhausted:
    kind = "exhausted_test"
    def __init__(self, config): self.config = config
    def is_configured(self): return True
    def describe(self): return {"name": self.config.name, "api_key": "***"}
    def complete(self, request):
        raise LLMError(QUOTA, retryable=False, provider=self.config.name)


hp.PROVIDER_TYPES["exhausted_test"] = _Exhausted


def _bridge(*configs):
    return GatewayBackedLLM(None, LLMGateway(list(configs), sleep=lambda _s: None))


def _echo(name, payload):
    return ProviderConfig(name=name, kind="echo", model="m",
                          extra={"response": json.dumps(payload)})


def test_backup_provider_serves_when_primary_quota_is_exhausted():
    llm = _bridge(ProviderConfig(name="primary", kind="exhausted_test"),
                  _echo("backup", {"summary": "real analysis", "objectives": ["o1"]}))
    assert llm.invoke_json("prompt", "system")["summary"] == "real analysis"


def test_quota_surfaces_when_every_provider_is_exhausted():
    llm = _bridge(ProviderConfig(name="primary", kind="exhausted_test"),
                  ProviderConfig(name="secondary", kind="exhausted_test"))
    with pytest.raises(CapgeminiLLMQuotaError):
        llm.invoke_json("prompt", "system")


def test_bridge_raises_on_unparseable_output_rather_than_placeholder():
    """The bridge must keep the legacy contract: never return a `_raw` shape."""
    llm = GatewayBackedLLM(None, LLMGateway(
        [ProviderConfig(name="p", kind="echo", model="m",
                        extra={"response": "definitely not json"})],
        sleep=lambda _s: None))
    with pytest.raises(CapgeminiLLMFormatError):
        llm.invoke_json("prompt", "system")


def test_multi_provider_is_opt_in(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDERS", raising=False)
    assert multi_provider_configured() is False
    assert type(build_llm(None)).__name__ == "CapgeminiLLM"

    monkeypatch.setenv("LLM_PROVIDERS", "primary:openai_compatible")
    assert multi_provider_configured() is True
    assert type(build_llm(None)).__name__ == "GatewayBackedLLM"


def test_bridge_keys_are_redacted():
    llm = _bridge(ProviderConfig(name="p", kind="echo", api_key="super-secret"))
    assert "super-secret" not in json.dumps(llm.describe())


def test_a_successful_run_records_how_it_was_generated(monkeypatch, tmp_path):
    """Only failures were ever stamped, so a successful AI run carried no
    proof it was AI and the UI could show no honest evidence."""
    import json as _json

    from c_invent.agents import orchestrator as O

    calls = {}

    class FakeLLM:
        settings = type("S", (), {"llm_provider": "azure",
                                  "llm_model": "openai.gpt-5.1"})()

        def invoke_json(self, user, system="", **kw):
            calls["hit"] = True
            return {"summary": "Derived from the evidence.",
                    "facts": ["A stated fact"], "assumptions": []}

    class FakeStore:
        def __init__(self):
            self.runs = []

        def get_project(self, _pid):
            return {"name": "P"}

        def documents(self, _pid):
            return [{"name": "intake.pdf", "text": "Automate compliance responses."}]

        def save_run(self, pid, agent, status, instructions, out):
            self.runs.append((status, out))

        def add_audit(self, *a, **k):
            pass

    orch = O.Orchestrator.__new__(O.Orchestrator)
    orch.llm = FakeLLM()
    orch.store = FakeStore()

    out = orch._run("p1", "discovery", "Extract discovery facts.")

    assert calls.get("hit") is True
    assert out["generation_mode"] == "ai"
    assert out["ai_model"] == "openai.gpt-5.1"
    assert out["ai_provider"] == "azure"
    assert "ai_elapsed_ms" in out
    assert orch.store.runs[0][0] == "success"
