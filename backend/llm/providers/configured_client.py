"""Adapter exposing the deployment's configured LLM client to the gateway.

Two code paths grew independently: the legacy delivery path builds its client
from the vendor-neutral `ELITEINTELIA_*` settings, while the v2 gateway only
registered providers declared through `LLM_PROVIDERS`/`LLM_ENDPOINT`. A
deployment that configured the first and not the second ended up with a
*working* provider and an *empty* gateway, so Settings reported "AI provider is
working" while every v2 stage silently fell back to evidence-only generation.

This adapter closes that gap. It does not reimplement the wire format — it
delegates to the same client the diagnostics exercise, so what Settings proves
is exactly what the stages get.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from llm.gateway.base import (LLMError, LLMNotConfigured, LLMProvider, LLMRequest,
                              LLMResponse, LLMTimeout, Role, Usage)


class ConfiguredClientProvider(LLMProvider):
    """Bridges the configured client into the provider-neutral interface."""

    kind = "configured_client"

    def __init__(self, config):
        super().__init__(config)
        self._client: Optional[Any] = None

    # The client is built lazily: settings are read at call time so a
    # credential change does not require a process restart.
    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from c_invent.llm.capgemini import CapgeminiLLM
            from c_invent.services.config import load_settings
        except Exception as exc:                      # pragma: no cover - import guard
            raise LLMNotConfigured(f"Configured client unavailable: {exc}",
                                   provider=self.config.name) from exc
        self._client = CapgeminiLLM(load_settings())
        return self._client

    def is_configured(self) -> bool:
        try:
            from c_invent.services.config import load_settings
            s = load_settings()
            return bool((s.llm_base_url or "").strip() and (s.llm_api_key or "").strip())
        except Exception:
            return False

    def complete(self, request: LLMRequest) -> LLMResponse:
        if not self.is_configured():
            raise LLMNotConfigured(
                "No endpoint or API key configured. Set ELITEINTELIA_LLM_BASE_URL "
                "and ELITEINTELIA_LLM_API_KEY.", provider=self.config.name)

        client = self._get_client()
        user_text = "\n\n".join(m.content for m in request.messages
                                if m.role is not Role.SYSTEM).strip()
        system = request.system_prompt
        if request.json_mode:
            # The client has no structured-output flag; ask in the system prompt
            # and let the gateway's own parser extract the object.
            system = (system + "\n\nReturn only valid JSON. No prose, no code fences.").strip()

        # The gateway sets a per-request budget; dropping it left every call
        # pinned to the deployment-wide default. On a reasoning model the
        # budget also covers reasoning tokens, so a request for a large
        # structured record exhausts it and the provider answers with an
        # empty string rather than an error.
        extra = {"maxTokens": int(request.max_tokens or 0) or None,
                 "temperature": float(request.temperature)}
        extra = {k: v for k, v in extra.items() if v is not None}

        started = time.time()
        try:
            raw = client.invoke(user_text, system_prompt=system, extra_params=extra)
        except Exception as exc:
            message = str(exc)
            lowered = message.lower()
            if "timeout" in lowered or "timed out" in lowered:
                raise LLMTimeout(message, provider=self.config.name) from exc
            # Quota, rate limit and transient upstream faults are worth failing
            # over to another provider; anything else is not.
            retryable = any(w in lowered for w in
                            ("quota", "rate limit", "429", "503", "502",
                             "temporarily", "overloaded", "unavailable"))
            raise LLMError(message, retryable=retryable,
                           provider=self.config.name) from exc

        # The client returns {"content": str, "raw": provider_payload}. Passing
        # that mapping through as `text` would leave every JSON-mode caller
        # trying to parse a dict, which fails and drops the stage back to
        # evidence-only — a working provider that still looks broken.
        if isinstance(raw, dict):
            text = raw.get("content", "")
            payload = raw.get("raw") if isinstance(raw.get("raw"), dict) else None
        else:
            text, payload = raw, None
        if not isinstance(text, str):
            text = "" if text is None else str(text)

        if not text.strip():
            # Observed intermittently on large structured requests: the call
            # succeeds and returns no content. Treating that as a result made
            # the stage degrade silently, so a healthy provider was
            # indistinguishable from an outage. It is retryable — a second
            # attempt normally returns the record.
            raise LLMError(
                "The provider accepted the request but returned no content. "
                "This happens intermittently on large structured requests; "
                "retrying usually succeeds.",
                retryable=True, provider=self.config.name)

        latency = int((time.time() - started) * 1000)
        model = getattr(getattr(client, "settings", None), "llm_model", "") or self.config.model
        return LLMResponse(text=text, provider=self.config.name,
                           model=model or "configured", latency_ms=latency,
                           raw=payload,
                           usage=Usage(len(user_text) // 4, len(text) // 4))
