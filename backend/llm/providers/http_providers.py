"""Provider adapters (spec §1, §35).

Most enterprise gateways speak an OpenAI-compatible shape, so that adapter is
the workhorse and covers OpenAI, Azure OpenAI, self-hosted vLLM/Ollama, and most
private enterprise gateways. Anthropic, Google and Bedrock differ enough in
request/response shape to warrant their own adapters.

Every adapter is responsible only for translation. Retries, fallback, auditing
and prompt construction live above, in the gateway.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import requests

from llm.gateway.base import (
    LLMError, LLMNotConfigured, LLMProvider, LLMRequest, LLMResponse, LLMTimeout,
    Role, Usage, _Timer,
)


def _post(url: str, headers: dict, payload: dict, timeout: int, provider: str) -> dict:
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.Timeout as exc:
        raise LLMTimeout(f"{provider} timed out after {timeout}s", provider=provider) from exc
    except requests.RequestException as exc:
        raise LLMError(f"{provider} request failed: {exc}", retryable=True, provider=provider) from exc

    if r.status_code == 429 or r.status_code >= 500:
        raise LLMError(f"{provider} returned {r.status_code}: {r.text[:300]}",
                       retryable=True, provider=provider)
    if r.status_code >= 400:
        raise LLMError(f"{provider} returned {r.status_code}: {r.text[:300]}",
                       retryable=False, provider=provider)
    try:
        return r.json()
    except ValueError as exc:
        raise LLMError(f"{provider} returned non-JSON response.", provider=provider) from exc


class OpenAICompatibleProvider(LLMProvider):
    """OpenAI, Azure OpenAI, vLLM, Ollama, LM Studio, most private gateways."""

    kind = "openai_compatible"

    def complete(self, request: LLMRequest) -> LLMResponse:
        cfg = self.config
        if not cfg.endpoint:
            raise LLMNotConfigured(f"No endpoint configured for provider '{cfg.name}'.", cfg.name)

        headers = {"Content-Type": "application/json"}
        if cfg.api_key:
            # "none" means send the key bare. The configured-client path has
            # always used that convention, and an environment variable often
            # cannot be set to an empty string, so a literal "none" is the only
            # way to express "no scheme" on some hosts. Sending "none <key>"
            # would fail authentication in a way that looks like a bad key.
            scheme = (cfg.auth_scheme or "").strip()
            if scheme.lower() in ("none", "-", "null"):
                scheme = ""
            headers[cfg.auth_header] = f"{scheme} {cfg.api_key}".strip()

        payload: Dict[str, Any] = {
            "model": request.model or cfg.model,
            "messages": [m.to_dict() for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        # Not every OpenAI-compatible gateway accepts response_format, and one
        # that rejects it fails the whole call. `json_mode: off` drops the flag
        # and leaves structured output to the prompt plus the gateway's parser.
        if request.json_mode and cfg.extra.get("json_mode", "on") != "off":
            payload["response_format"] = {"type": "json_object"}
        if request.stop:
            payload["stop"] = request.stop
        payload.update(cfg.extra.get("params", {}))
        payload.update(request.extra)

        with _Timer() as t:
            data = _post(cfg.endpoint, headers, payload,
                         request.timeout_seconds or cfg.timeout_seconds, cfg.name)

        choice = (data.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or choice.get("text") or ""
        u = data.get("usage") or {}
        return LLMResponse(
            text=text, provider=cfg.name, model=payload["model"],
            usage=Usage(u.get("prompt_tokens", 0), u.get("completion_tokens", 0)),
            latency_ms=t.ms, finish_reason=choice.get("finish_reason", "stop"), raw=data,
        )


class AnthropicProvider(LLMProvider):
    """Anthropic Messages API: system prompt is a top-level field."""

    kind = "anthropic"

    def complete(self, request: LLMRequest) -> LLMResponse:
        cfg = self.config
        if not cfg.api_key:
            raise LLMNotConfigured(f"No API key configured for provider '{cfg.name}'.", cfg.name)

        endpoint = cfg.endpoint or "https://api.anthropic.com/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": cfg.api_key,
            "anthropic-version": cfg.extra.get("version", "2023-06-01"),
        }
        payload: Dict[str, Any] = {
            "model": request.model or cfg.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": [m.to_dict() for m in request.messages if m.role is not Role.SYSTEM],
        }
        system = request.system_prompt
        if system:
            payload["system"] = system
        payload.update(request.extra)

        with _Timer() as t:
            data = _post(endpoint, headers, payload,
                         request.timeout_seconds or cfg.timeout_seconds, cfg.name)

        blocks = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        u = data.get("usage") or {}
        return LLMResponse(
            text=text, provider=cfg.name, model=payload["model"],
            usage=Usage(u.get("input_tokens", 0), u.get("output_tokens", 0)),
            latency_ms=t.ms, finish_reason=data.get("stop_reason", "stop"), raw=data,
        )


class GoogleProvider(LLMProvider):
    """Google Generative Language API (Gemini)."""

    kind = "google"

    def complete(self, request: LLMRequest) -> LLMResponse:
        cfg = self.config
        if not cfg.api_key:
            raise LLMNotConfigured(f"No API key configured for provider '{cfg.name}'.", cfg.name)

        model = request.model or cfg.model or "gemini-1.5-pro"
        base = cfg.endpoint or "https://generativelanguage.googleapis.com/v1beta"
        url = f"{base.rstrip('/')}/models/{model}:generateContent?key={cfg.api_key}"

        contents = [{"role": "user" if m.role is Role.USER else "model",
                     "parts": [{"text": m.content}]}
                    for m in request.messages if m.role is not Role.SYSTEM]
        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": request.temperature,
                                 "maxOutputTokens": request.max_tokens},
        }
        system = request.system_prompt
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if request.json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        with _Timer() as t:
            data = _post(url, {"Content-Type": "application/json"}, payload,
                         request.timeout_seconds or cfg.timeout_seconds, cfg.name)

        cands = data.get("candidates") or [{}]
        parts = (cands[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
        u = data.get("usageMetadata") or {}
        return LLMResponse(
            text=text, provider=cfg.name, model=model,
            usage=Usage(u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0)),
            latency_ms=t.ms, finish_reason=cands[0].get("finishReason", "stop"), raw=data,
        )


class BedrockProvider(LLMProvider):
    """AWS Bedrock via boto3. Kept lazy so boto3 stays an optional dependency."""

    kind = "bedrock"

    def is_configured(self) -> bool:
        return bool(self.config.model)

    def complete(self, request: LLMRequest) -> LLMResponse:
        cfg = self.config
        try:
            import boto3  # noqa: PLC0415 - optional dependency
        except ImportError as exc:
            raise LLMNotConfigured("boto3 is not installed; cannot use the Bedrock provider.",
                                   cfg.name) from exc

        model = request.model or cfg.model
        if not model:
            raise LLMNotConfigured(f"No model configured for provider '{cfg.name}'.", cfg.name)

        client = boto3.client("bedrock-runtime",
                              region_name=cfg.extra.get("region") or "us-east-1")
        body: Dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": [m.to_dict() for m in request.messages if m.role is not Role.SYSTEM],
        }
        system = request.system_prompt
        if system:
            body["system"] = system

        with _Timer() as t:
            try:
                resp = client.invoke_model(modelId=model, body=json.dumps(body))
                data = json.loads(resp["body"].read())
            except Exception as exc:  # noqa: BLE001 - boto3 raises many shapes
                raise LLMError(f"Bedrock request failed: {exc}", retryable=True,
                               provider=cfg.name) from exc

        text = "".join(b.get("text", "") for b in (data.get("content") or []))
        u = data.get("usage") or {}
        return LLMResponse(
            text=text, provider=cfg.name, model=model,
            usage=Usage(u.get("input_tokens", 0), u.get("output_tokens", 0)),
            latency_ms=t.ms, raw=data,
        )


class EchoProvider(LLMProvider):
    """Deterministic provider for tests and offline development.

    Never registered automatically in production configuration; it exists so the
    workflow engine can be tested without network access or credentials.
    """

    kind = "echo"

    def is_configured(self) -> bool:
        return True

    def complete(self, request: LLMRequest) -> LLMResponse:
        canned = self.config.extra.get("response")
        if canned is None:
            last = next((m.content for m in reversed(request.messages) if m.role is Role.USER), "")
            canned = json.dumps({"echo": last[:400]}) if request.json_mode else f"ECHO: {last[:400]}"
        return LLMResponse(text=canned, provider=self.config.name,
                           model=self.config.model or "echo", latency_ms=1,
                           usage=Usage(len(str(request.messages)) // 4, len(canned) // 4))


#: Adapter registry. Extend here to support a new vendor.
from llm.providers.configured_client import ConfiguredClientProvider  # noqa: E402

PROVIDER_TYPES: Dict[str, type[LLMProvider]] = {
    OpenAICompatibleProvider.kind: OpenAICompatibleProvider,
    ConfiguredClientProvider.kind: ConfiguredClientProvider,
    AnthropicProvider.kind: AnthropicProvider,
    GoogleProvider.kind: GoogleProvider,
    BedrockProvider.kind: BedrockProvider,
    EchoProvider.kind: EchoProvider,
}
