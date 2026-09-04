"""Provider-neutral LLM gateway (spec §35).

The core application must not know which model is being used. Everything above
this module speaks in `LLMRequest` / `LLMResponse`; every vendor difference is
absorbed by a provider adapter.

Adding a provider means implementing `LLMProvider` and registering it — no
change to agents, workflows or the UI.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class Message:
    role: Role
    content: str

    def to_dict(self) -> dict:
        return {"role": self.role.value, "content": self.content}


@dataclass
class LLMRequest:
    messages: List[Message]
    model: Optional[str] = None           # provider default when omitted
    temperature: float = 0.0
    max_tokens: int = 1500
    timeout_seconds: int = 90
    json_mode: bool = False               # ask for structured output
    stop: Optional[List[str]] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def system_prompt(self) -> str:
        return "\n".join(m.content for m in self.messages if m.role is Role.SYSTEM)


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def to_dict(self) -> dict:
        return {"prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens}


@dataclass
class LLMResponse:
    """A completed model call, with everything the AI Run Centre needs (§34)."""

    text: str
    provider: str
    model: str
    usage: Usage = field(default_factory=Usage)
    latency_ms: int = 0
    finish_reason: str = "stop"
    raw: Optional[dict] = None

    def to_dict(self) -> dict:
        return {"provider": self.provider, "model": self.model,
                "usage": self.usage.to_dict(), "latency_ms": self.latency_ms,
                "finish_reason": self.finish_reason,
                "chars": len(self.text or "")}


class LLMError(Exception):
    """Base class for provider failures."""

    def __init__(self, message: str, *, retryable: bool = False, provider: str = ""):
        super().__init__(message)
        self.retryable = retryable
        self.provider = provider


class LLMTimeout(LLMError):
    def __init__(self, message: str, provider: str = ""):
        super().__init__(message, retryable=True, provider=provider)


class LLMNotConfigured(LLMError):
    """Raised when a provider has no usable credentials/endpoint."""

    def __init__(self, message: str, provider: str = ""):
        super().__init__(message, retryable=False, provider=provider)


@dataclass
class ProviderConfig:
    """Everything needed to talk to one provider (spec §35)."""

    name: str
    kind: str                        # adapter key, e.g. "openai_compatible"
    endpoint: str = ""
    api_key: str = ""
    model: str = ""
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer"
    timeout_seconds: int = 90
    max_retries: int = 1
    enabled: bool = True
    extra: Dict[str, Any] = field(default_factory=dict)

    def redacted(self) -> dict:
        """Safe for logs, audit records and API responses."""
        return {"name": self.name, "kind": self.kind, "endpoint": self.endpoint,
                "model": self.model, "enabled": self.enabled,
                "api_key": "***" if self.api_key else "",
                "timeout_seconds": self.timeout_seconds}


class LLMProvider(ABC):
    """Implement this to add a provider. No other layer needs to change."""

    kind: str = "abstract"

    def __init__(self, config: ProviderConfig):
        self.config = config

    @abstractmethod
    def complete(self, request: LLMRequest) -> LLMResponse:
        """Run one completion. Raise LLMError subclasses on failure."""

    def is_configured(self) -> bool:
        return bool(self.config.endpoint or self.config.api_key)

    def describe(self) -> dict:
        return {**self.config.redacted(), "configured": self.is_configured()}


class _Timer:
    def __enter__(self):
        self._t0 = time.monotonic()
        return self

    def __exit__(self, *exc):
        self.ms = int((time.monotonic() - self._t0) * 1000)
        return False
