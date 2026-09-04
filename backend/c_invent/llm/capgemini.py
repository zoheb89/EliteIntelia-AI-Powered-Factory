from __future__ import annotations

import json
import time
import uuid
from typing import Any

import requests


class CapgeminiLLMError(RuntimeError):
    pass


class CapgeminiLLMQuotaError(CapgeminiLLMError):
    """The provider rejected the request (quota, rate limit, policy).

    Distinct from a transport failure because retrying will not help, and the
    operator needs to see the provider's own message.
    """


class CapgeminiLLMFormatError(CapgeminiLLMError):
    """The model answered, but not with usable JSON.

    This is a failure. Returning a placeholder here is what allowed a provider
    error message to be persisted as a completed delivery artifact.
    """


class CapgeminiLLM:
    """Capgemini Generative Engine adapter.

    This implementation follows the request contract used by the supplied
    Semantic Analytics Platform reference application:
      - POST /v2/llm/invoke
      - x-api-key authentication
      - modelInterface at the top level
      - all invocation parameters nested under `data`
      - modelKwargs (not modelParams)
    """

    def __init__(self, settings):
        self.settings = settings

    def _headers(self) -> dict[str, str]:
        key = (self.settings.llm_api_key or "").strip()
        if not key:
            raise CapgeminiLLMError(
                "Capgemini API key is empty. Set CAPGEMINI_LLM_API_KEY in "
                ".streamlit/secrets.toml or Streamlit Cloud Secrets."
            )

        # Capgemini reference implementation uses ApiKeyAuth:
        # x-api-key: <key>. Keep configurable for tenant-specific gateways,
        # but default to the proven contract.
        header = (self.settings.llm_auth_header or "x-api-key").strip()
        scheme = (self.settings.llm_auth_scheme or "none").strip().lower()
        if header.lower() == "authorization":
            value = f"Bearer {key}" if scheme == "bearer" else key
        elif scheme not in ("", "none"):
            value = f"{scheme.title()} {key}"
        else:
            value = key

        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            header: value,
        }

    def _payload(
        self,
        text: str,
        system_prompt: str = "",
        files: list[Any] | None = None,
        session_id: str | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = session_id or str(uuid.uuid4())
        model_kwargs: dict[str, Any] = {
            "maxTokens": int(self.settings.max_tokens),
            "temperature": float(self.settings.temperature),
            "streaming": False,
            "topP": 0.9,
        }
        if extra_params:
            model_kwargs.update(extra_params)

        data: dict[str, Any] = {
            "mode": self.settings.llm_mode or "chain",
            "text": text,
            "files": files or [],
            "modelName": self.settings.llm_model or "openai.gpt-5.1",
            "provider": self.settings.llm_provider or "azure",
            "systemPrompt": system_prompt,
            "sessionId": session,
            "modelKwargs": model_kwargs,
        }

        workspace_id = (self.settings.capgemini_workspace_id or "").strip()
        if workspace_id and getattr(self.settings, "include_workspace_id", False):
            data["workspaceId"] = workspace_id

        # IMPORTANT: Capgemini expects invocation fields under `data`.
        return {
            "action": "run",
            "modelInterface": self.settings.llm_interface or "langchain",
            "data": data,
        }

    def invoke(
        self,
        text: str,
        system_prompt: str = "",
        files: list[Any] | None = None,
        session_id: str | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not (self.settings.llm_base_url or "").strip():
            raise CapgeminiLLMError("Capgemini endpoint is not configured.")

        payload = self._payload(text, system_prompt, files, session_id, extra_params)
        headers = self._headers()
        timeout = int(getattr(self.settings, "llm_timeout_seconds", 90) or 90)

        try:
            response = requests.post(
                self.settings.llm_base_url.rstrip("/"),
                headers=headers,
                json=payload,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise CapgeminiLLMError(f"Capgemini connection failed: {exc}") from exc

        if response.status_code == 401:
            raise CapgeminiLLMError(
                "Capgemini authentication failed (HTTP 401). Verify "
                "CAPGEMINI_LLM_API_KEY and the x-api-key header."
            )

        if response.status_code >= 400:
            request_id = response.headers.get("x-amzn-requestid", "")
            trace_id = response.headers.get("x-amzn-trace-id", "")
            diagnostics = []
            if request_id:
                diagnostics.append(f"request_id={request_id}")
            if trace_id:
                diagnostics.append(f"trace_id={trace_id}")
            suffix = f" ({', '.join(diagnostics)})" if diagnostics else ""
            raise CapgeminiLLMError(
                f"Capgemini HTTP {response.status_code}: "
                f"{response.text[:4000]}{suffix}"
            )

        try:
            obj = response.json()
        except ValueError as exc:
            raise CapgeminiLLMError(
                f"Capgemini returned a non-JSON response: {response.text[:2000]}"
            ) from exc

        content = self._content(obj)
        # Gateways frequently return quota and policy errors as HTTP 200 with the
        # message in the body. Left undetected these are indistinguishable from a
        # real completion and get persisted as delivery evidence.
        self._reject_provider_error(content)
        return {"content": content, "raw": obj}

    #: Error payloads returned with a 200 status. Matched on the response body.
    _ERROR_MARKERS = (
        "api call limit exceeded", "rate limit", "quota exceeded",
        "usage limit", "too many requests", "please upgrade your plan",
        "insufficient credits", "billing", "subscription expired",
        "content filtered", "content policy", "request blocked",
    )

    @classmethod
    def _reject_provider_error(cls, content: str) -> None:
        """Raise when the body is a provider error rather than a completion.

        Kept conservative: the marker must appear in a short response, because a
        long analytical answer may legitimately discuss rate limits or billing.
        """
        text = (content or "").strip()
        if not text:
            raise CapgeminiLLMQuotaError(
                "The AI provider returned an empty response.")
        if len(text) > 1200:
            return
        low = text.lower()
        for marker in cls._ERROR_MARKERS:
            if marker in low:
                raise CapgeminiLLMQuotaError(
                    f"The AI provider rejected the request: {text[:400]}")

    def test_connection(self):
        return self.invoke(
            "Reply with exactly: C INVENT TEST SUCCESS",
            "You are a connectivity test assistant. Follow the user's exact instruction.",
            extra_params={"maxTokens": 100, "temperature": 0.0, "topP": 0.9, "streaming": False},
        )

    @staticmethod
    def _content(obj: Any) -> str:
        if isinstance(obj, str):
            return obj
        if isinstance(obj, dict):
            if isinstance(obj.get("content"), str):
                return obj["content"]
            data = obj.get("data")
            if isinstance(data, dict) and isinstance(data.get("content"), str):
                return data["content"]
            choices = obj.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, dict):
                    message = first.get("message")
                    if isinstance(message, dict) and isinstance(message.get("content"), str):
                        return message["content"]
                    if isinstance(first.get("text"), str):
                        return first["text"]
            for key in ("text", "output", "response", "answer"):
                if isinstance(obj.get(key), str):
                    return obj[key]
        return json.dumps(obj, indent=2, ensure_ascii=False)

    def invoke_json(self, text: str, system_prompt: str = "", **kwargs):
        """Invoke JSON mode with bounded gateway-timeout recovery.

        Capgemini may return HTTP 504 when the gateway cannot complete a
        synchronous model invocation within its server-side window. A client
        timeout value cannot fix that condition, so retries deliberately shrink
        the request instead of simply waiting longer.
        """
        extra = dict(kwargs.get("extra_params") or {})
        session_id = kwargs.get("session_id")

        attempts = [
            (text, system_prompt, extra),
            (text[:3000], system_prompt[:1400], {**extra, "maxTokens": min(int(extra.get("maxTokens", 400)), 350), "temperature": 0.0, "streaming": False, "topP": 0.9}),
            (text[:1800], system_prompt[:800], {**extra, "maxTokens": min(int(extra.get("maxTokens", 250)), 220), "temperature": 0.0, "streaming": False, "topP": 0.9}),
        ]

        last_error = None
        result = None
        for idx, (attempt_text, attempt_system, attempt_params) in enumerate(attempts):
            try:
                # Use a fresh session on gateway retries. This avoids reusing a
                # server-side invocation context that may itself be stalled.
                attempt_session = session_id if idx == 0 else str(uuid.uuid4())
                result = self.invoke(
                    attempt_text,
                    attempt_system,
                    files=None if idx else kwargs.get("files"),
                    session_id=attempt_session,
                    extra_params=attempt_params,
                )
                break
            except CapgeminiLLMError as exc:
                last_error = exc
                msg = str(exc).lower()
                if "http 504" not in msg and "timed out" not in msg and "gateway timeout" not in msg:
                    raise
                if idx < len(attempts) - 1:
                    # Small backoff gives the gateway a chance to clear the
                    # previous request without making the UI feel hung.
                    time.sleep(1.5 * (idx + 1))

        if result is None:
            raise CapgeminiLLMError(
                "Capgemini gateway timed out after 3 bounded attempts. "
                "The endpoint is reachable, but the model invocation did not "
                "complete within the gateway window. Try again or ask the "
                "Capgemini platform team to check the endpoint/model latency."
            ) from last_error

        content = result["content"].strip()
        cleaned = self._clean_json_fence(content)
        try:
            return json.loads(cleaned)
        except Exception:
            # JSON repair is also bounded. Never resend the original large
            # request after a successful model response.
            repair_text = (
                "Convert this answer to valid JSON only. No markdown. "
                "Preserve information; do not add facts.\n\n" + content[:4500]
            )
            repair_params = {
                "maxTokens": 500,
                "temperature": 0.0,
                "streaming": False,
                "topP": 0.9,
            }
            try:
                repair = self.invoke(
                    repair_text,
                    "Return valid JSON only.",
                    session_id=str(uuid.uuid4()),
                    extra_params=repair_params,
                )
                repaired = self._clean_json_fence(repair["content"].strip())
                try:
                    return json.loads(repaired)
                except Exception as repair_exc:
                    # Previously this returned {"_raw": ...}, which is shaped like
                    # success. Callers persisted it as a completed stage, so a
                    # provider error message became delivery evidence. Fail loudly.
                    raise CapgeminiLLMFormatError(
                        "The model did not return valid JSON, and the repair "
                        f"attempt also failed. First 300 characters: {content[:300]}"
                    ) from repair_exc
            except CapgeminiLLMQuotaError:
                raise
            except CapgeminiLLMError as exc:
                raise CapgeminiLLMFormatError(
                    "The model did not return valid JSON and the repair request "
                    f"could not be completed: {exc}. First 300 characters: {content[:300]}"
                ) from exc

    @staticmethod
    def _clean_json_fence(content: str) -> str:
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content
            if content.endswith("```"):
                content = content[:-3]
        return content.strip()
