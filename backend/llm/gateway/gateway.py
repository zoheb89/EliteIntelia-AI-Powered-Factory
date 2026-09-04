"""The LLM gateway: routing, retries, fallback and structured output (spec §35).

Agents call `gateway.complete(...)` or `gateway.complete_json(...)` and never
learn which vendor answered. Provider selection, retry policy and failover all
live here so they are applied uniformly and can be audited in one place.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from llm.gateway.base import (
    LLMError, LLMNotConfigured, LLMProvider, LLMRequest, LLMResponse,
    Message, ProviderConfig, Role, Usage,
)
from llm.providers.http_providers import PROVIDER_TYPES

# Models sometimes wrap JSON in prose or a fenced block despite instructions.
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


class StructuredOutputError(LLMError):
    """The model answered, but not with usable JSON."""


@dataclass
class GatewayCall:
    """One audited attempt, for the AI Run Centre (spec §34)."""

    provider: str
    model: str
    ok: bool
    latency_ms: int
    attempt: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class GatewayResult:
    response: Optional[LLMResponse]
    calls: List[GatewayCall] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.response is not None

    @property
    def total_tokens(self) -> int:
        return sum(c.prompt_tokens + c.completion_tokens for c in self.calls)


def request_fingerprint(request: LLMRequest) -> str:
    """A stable key for an identical model call.

    Two requests with the same messages, model and sampling settings must
    produce the same key so a re-run costs nothing. Provider is deliberately
    excluded: the answer to a question does not change because it was asked
    through a different door.
    """
    payload = json.dumps({
        "messages": [m.to_dict() for m in request.messages],
        "model": request.model or "",
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
        "json_mode": request.json_mode,
        "stop": request.stop or [],
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class LLMGateway:
    """Provider-neutral entry point for every model call in the platform."""

    def __init__(self, providers: Optional[List[ProviderConfig]] = None,
                 default_provider: str = "", sleep: Callable[[float], None] = time.sleep,
                 cache: Optional[Any] = None):
        self._configs: Dict[str, ProviderConfig] = {}
        self._instances: Dict[str, LLMProvider] = {}
        self._order: List[str] = []
        self._default = default_provider
        self._sleep = sleep
        # An optional store with get(key) -> dict | None and put(key, dict).
        # On a metered plan a repeated call is wasted quota, not just latency:
        # re-running a stage over unchanged evidence should cost nothing.
        self.cache = cache
        for cfg in providers or []:
            self.register(cfg)

    # ------------------------------------------------------------- registry
    def register(self, config: ProviderConfig) -> None:
        adapter = PROVIDER_TYPES.get(config.kind)
        if not adapter:
            raise LLMNotConfigured(
                f"Unknown provider kind '{config.kind}'. "
                f"Known kinds: {', '.join(sorted(PROVIDER_TYPES))}."
            )
        self._configs[config.name] = config
        self._instances[config.name] = adapter(config)
        if config.name not in self._order:
            self._order.append(config.name)
        if not self._default:
            self._default = config.name

    def get(self, name: str) -> LLMProvider:
        if name not in self._instances:
            raise LLMNotConfigured(f"Provider '{name}' is not registered.")
        return self._instances[name]

    def describe(self) -> List[dict]:
        return [self._instances[n].describe() for n in self._order]

    @property
    def default_provider(self) -> str:
        return self._default

    def _chain(self, provider: Optional[str]) -> List[str]:
        """Preferred provider first, then the remaining enabled ones (§35 fallback)."""
        first = provider or self._default
        rest = [n for n in self._order
                if n != first and self._configs[n].enabled and self._instances[n].is_configured()]
        return ([first] if first in self._instances else []) + rest

    # -------------------------------------------------------------- calling
    def complete(self, request: LLMRequest, provider: Optional[str] = None,
                 allow_fallback: bool = True) -> GatewayResult:
        """Run a completion with retries, then fail over to other providers."""
        chain = self._chain(provider)
        if not chain:
            raise LLMNotConfigured("No LLM provider is configured.")

        calls: List[GatewayCall] = []
        last: Optional[LLMError] = None

        key = request_fingerprint(request)
        if self.cache is not None:
            try:
                hit = self.cache.get(key)
            except Exception:                      # a cache must never break a call
                hit = None
            if hit:
                resp = LLMResponse(
                    text=hit.get("text", ""), provider=hit.get("provider", "cache"),
                    model=hit.get("model", ""), latency_ms=0,
                    finish_reason="cached",
                    usage=Usage(0, 0))
                calls.append(GatewayCall(hit.get("provider", "cache"),
                                         hit.get("model", ""), True, 0, 1))
                return GatewayResult(resp, calls)

        for name in (chain if allow_fallback else chain[:1]):
            impl = self._instances[name]
            cfg = self._configs[name]
            if not cfg.enabled:
                continue
            for attempt in range(1, max(1, cfg.max_retries) + 1):
                try:
                    resp = impl.complete(request)
                    if self.cache is not None and resp.text.strip():
                        try:
                            self.cache.put(key, {"text": resp.text, "model": resp.model,
                                                 "provider": resp.provider})
                        except Exception:
                            pass                   # caching is best-effort
                    calls.append(GatewayCall(name, resp.model, True, resp.latency_ms, attempt,
                                             resp.usage.prompt_tokens, resp.usage.completion_tokens))
                    return GatewayResult(resp, calls)
                except LLMError as exc:
                    last = exc
                    calls.append(GatewayCall(name, cfg.model, False, 0, attempt, error=str(exc)[:300]))
                    if not exc.retryable:
                        break  # move to the next provider rather than retrying
                    if attempt < cfg.max_retries:
                        self._sleep(min(2 ** (attempt - 1), 8))

        raise last or LLMError("All configured providers failed.")

    def complete_json(self, request: LLMRequest, provider: Optional[str] = None,
                      repair: bool = True) -> tuple[Any, GatewayResult]:
        """Completion that must return JSON.

        Tries json mode, then extracts from a fenced block, then asks the model
        once to repair its own output. Raises rather than returning something
        that only looks like data.
        """
        request.json_mode = True
        result = self.complete(request, provider)
        text = (result.response.text if result.response else "") or ""

        parsed = _try_parse(text)
        if parsed is not None:
            return parsed, result

        if repair:
            fix = LLMRequest(
                messages=[
                    Message(Role.SYSTEM, "You convert text into valid JSON. Reply with JSON only."),
                    Message(Role.USER, f"Convert this into valid JSON. Reply with JSON only:\n\n{text[:6000]}"),
                ],
                temperature=0.0, max_tokens=request.max_tokens, json_mode=True,
                timeout_seconds=request.timeout_seconds,
            )
            repaired = self.complete(fix, provider)
            result.calls.extend(repaired.calls)
            parsed = _try_parse(repaired.response.text if repaired.response else "")
            if parsed is not None:
                return parsed, result

        raise StructuredOutputError("The model did not return valid JSON.")


def _try_parse(text: str) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = _FENCE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # Fall back to the outermost object/array in the response.
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    return None


# ------------------------------------------------------------------ config
def gateway_from_env() -> LLMGateway:
    """Build a gateway from environment variables.

    Providers are declared as `LLM_PROVIDERS=name:kind,name:kind`, with per
    provider settings under `LLM_<NAME>_*`. A single-provider deployment can
    instead set LLM_PROVIDER/LLM_ENDPOINT/LLM_API_KEY/LLM_MODEL.

    No vendor is assumed or defaulted (spec §1).
    """
    gw = LLMGateway()
    declared = os.getenv("LLM_PROVIDERS", "").strip()

    if declared:
        for token in [t for t in declared.split(",") if t.strip()]:
            name, _, kind = token.partition(":")
            name, kind = name.strip(), (kind.strip() or "openai_compatible")
            prefix = f"LLM_{name.upper().replace('-', '_')}_"
            gw.register(ProviderConfig(
                name=name, kind=kind,
                endpoint=os.getenv(prefix + "ENDPOINT", ""),
                api_key=os.getenv(prefix + "API_KEY", ""),
                model=os.getenv(prefix + "MODEL", ""),
                auth_header=os.getenv(prefix + "AUTH_HEADER", "Authorization"),
                auth_scheme=os.getenv(prefix + "AUTH_SCHEME", "Bearer"),
                timeout_seconds=int(os.getenv(prefix + "TIMEOUT", "90")),
                max_retries=int(os.getenv(prefix + "RETRIES", "2")),
                extra={"region": os.getenv(prefix + "REGION", ""),
                       "json_mode": os.getenv(prefix + "JSON_MODE", "on")},
            ))
    elif os.getenv("LLM_ENDPOINT") or os.getenv("LLM_API_KEY"):
        gw.register(ProviderConfig(
            name=os.getenv("LLM_PROVIDER", "default"),
            kind=os.getenv("LLM_KIND", "openai_compatible"),
            endpoint=os.getenv("LLM_ENDPOINT", ""),
            api_key=os.getenv("LLM_API_KEY", ""),
            model=os.getenv("LLM_MODEL", ""),
            auth_header=os.getenv("LLM_AUTH_HEADER", "Authorization"),
            auth_scheme=os.getenv("LLM_AUTH_SCHEME", "Bearer"),
            timeout_seconds=int(os.getenv("LLM_TIMEOUT", "90")),
            max_retries=int(os.getenv("LLM_RETRIES", "2")),
        ))

    if not gw.describe():
        # Nothing was declared for the gateway, but the deployment may still
        # have a working client configured the vendor-neutral way. Falling back
        # to it is what keeps Settings ("AI provider is working") and the
        # delivery stages honest about each other — otherwise every stage
        # degrades to evidence-only while diagnostics report success.
        try:
            from llm.providers.configured_client import ConfiguredClientProvider
            probe = ConfiguredClientProvider(ProviderConfig(
                name="configured", kind=ConfiguredClientProvider.kind))
            if probe.is_configured():
                gw.register(ProviderConfig(
                    name="configured", kind=ConfiguredClientProvider.kind,
                    max_retries=int(os.getenv("LLM_RETRIES", "3")),
                    timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "90"))))
        except Exception:
            pass

    if os.getenv("LLM_DEFAULT_PROVIDER"):
        gw._default = os.getenv("LLM_DEFAULT_PROVIDER", "")
    return gw
