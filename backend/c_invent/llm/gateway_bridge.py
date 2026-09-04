"""Bridge the legacy LLM call sites onto the provider-neutral v2 gateway.

The legacy client talks to exactly one provider. When that provider's quota is
exhausted, every stage degrades until the quota window resets — which is what
happened in production.

This adapter exposes the legacy `invoke` / `invoke_json` interface but routes
through `LLMGateway`, so a deployment can declare several providers and fail
over automatically:

    LLM_PROVIDERS=primary:openai_compatible,backup:anthropic

It is opt-in. With no `LLM_PROVIDERS` set the original client is used and
behaviour is unchanged.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from c_invent.llm.capgemini import (
    CapgeminiLLMError, CapgeminiLLMFormatError, CapgeminiLLMQuotaError,
)
from llm.gateway.base import LLMNotConfigured, LLMRequest, Message, Role
from llm.gateway.gateway import LLMGateway, StructuredOutputError, gateway_from_env


def multi_provider_configured() -> bool:
    return bool(os.getenv("LLM_PROVIDERS", "").strip())


class GatewayBackedLLM:
    """Legacy-shaped client backed by the multi-provider gateway."""

    def __init__(self, settings: Any = None, gateway: Optional[LLMGateway] = None):
        self.settings = settings
        self.gateway = gateway or gateway_from_env()

    # ------------------------------------------------------------ legacy API
    def invoke(self, user: str, system: str = "", session_id: str = "",
               extra_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = extra_params or {}
        request = LLMRequest(
            messages=[m for m in (Message(Role.SYSTEM, system) if system else None,
                                  Message(Role.USER, user)) if m],
            temperature=float(params.get("temperature", 0.0)),
            max_tokens=int(params.get("maxTokens", params.get("max_tokens", 1200))),
            timeout_seconds=int(params.get("timeout", 90)),
        )
        try:
            result = self.gateway.complete(request)
        except LLMNotConfigured as exc:
            raise CapgeminiLLMError(str(exc)) from exc
        except Exception as exc:
            raise self._translate(exc) from exc

        response = result.response
        return {"content": response.text, "raw": response.raw or {},
                "provider": response.provider, "model": response.model}

    def invoke_json(self, user: str, system: str = "",
                    extra_params: Optional[Dict[str, Any]] = None) -> Any:
        params = extra_params or {}
        request = LLMRequest(
            messages=[m for m in (Message(Role.SYSTEM, system) if system else None,
                                  Message(Role.USER, user)) if m],
            temperature=float(params.get("temperature", 0.0)),
            max_tokens=int(params.get("maxTokens", params.get("max_tokens", 1200))),
            timeout_seconds=int(params.get("timeout", 90)),
            json_mode=True,
        )
        try:
            data, _ = self.gateway.complete_json(request)
        except StructuredOutputError as exc:
            # Same contract as the legacy client: unparseable output is a failure,
            # never a placeholder that a caller might persist.
            raise CapgeminiLLMFormatError(str(exc)) from exc
        except LLMNotConfigured as exc:
            raise CapgeminiLLMError(str(exc)) from exc
        except Exception as exc:
            raise self._translate(exc) from exc
        return data

    def test_connection(self) -> Dict[str, Any]:
        return self.invoke("Reply with exactly: C INVENT TEST SUCCESS",
                           "You are a connectivity test assistant.",
                           extra_params={"maxTokens": 100})

    def describe(self) -> list:
        return self.gateway.describe()

    @staticmethod
    def _translate(exc: Exception) -> CapgeminiLLMError:
        """Preserve the quota/format distinction the call sites rely on."""
        text = str(exc).lower()
        quota = any(m in text for m in (
            "limit exceeded", "rate limit", "quota", "too many requests",
            "upgrade your plan", "insufficient credits", "billing"))
        cls = CapgeminiLLMQuotaError if quota else CapgeminiLLMError
        return cls(str(exc))


def build_llm(settings: Any):
    """Return the multi-provider client when configured, else the legacy one.

    Chosen at construction so a deployment opts in purely through configuration.
    """
    if multi_provider_configured():
        return GatewayBackedLLM(settings)
    from c_invent.llm.capgemini import CapgeminiLLM
    return CapgeminiLLM(settings)
