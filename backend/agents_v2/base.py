"""Agent base class (spec §36, §67, §68).

An agent turns evidence into a structured, provenance-tagged proposal. It never
writes to the database directly — it returns an `AgentOutput`, and the
orchestrator persists it inside the approval and audit path (§69).

Three guarantees are enforced here rather than left to each agent:

1. **Tools before assertion (§37)** — agents gather context through the tool
   registry, and those calls are recorded alongside the output.
2. **Provenance on every statement (§8)** — output is normalised through the
   domain `Statement`, so an unevidenced `FACT` is downgraded automatically.
3. **Never fail the lifecycle (§44)** — if the model is unavailable, the agent
   falls back to a deterministic, evidence-only result that is explicitly
   labelled as such. It is never dressed up as AI output.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.domain.provenance import Confidence, EvidenceRef, Provenance, Statement
from core.tools.registry import ToolCall, ToolRegistry
from llm.gateway.base import LLMRequest, Message, Role
from llm.gateway.gateway import LLMGateway


@dataclass
class AgentOutput:
    """What an agent proposes. The orchestrator decides what to persist."""

    agent: str
    stage: str
    summary: str = ""
    statements: List[Statement] = field(default_factory=list)
    artifacts: Dict[str, Any] = field(default_factory=dict)   # kind -> content
    generation_mode: str = "ai"        # ai | deterministic_evidence_only
    provider: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_ms: int = 0
    tool_calls: List[ToolCall] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def degraded(self) -> bool:
        return self.generation_mode != "ai"

    def statements_of(self, kind: str) -> List[Statement]:
        return [s for s in self.statements if getattr(s, "kind", "") == kind]

    def to_dict(self) -> dict:
        return {
            "agent": self.agent, "stage": self.stage, "summary": self.summary,
            "generation_mode": self.generation_mode, "provider": self.provider,
            "model": self.model, "degraded": self.degraded,
            "statement_count": len(self.statements),
            "artifacts": list(self.artifacts),
            "tool_calls": [c.to_dict() for c in self.tool_calls],
            "warnings": self.warnings,
            "usage": {"prompt_tokens": self.prompt_tokens,
                      "completion_tokens": self.completion_tokens},
        }


class BaseAgent(ABC):
    """Subclass this to add an agent. Registered in `agents_v2.registry`."""

    id: str = "agent"
    stage: str = ""
    prompt_version: str = "v1"
    #: Guidance shared by all agents; keeps the no-hallucination contract uniform.
    CONTRACT = (
        "You analyse only the evidence supplied to you. You never invent customer "
        "facts, data volumes, SLAs, compliance certifications, pricing or platform "
        "constraints. When information is not available you return it as UNKNOWN "
        "with a specific question for the customer. Every item you return must "
        "carry a provenance of FACT, AI_INFERENCE, ASSUMPTION, RECOMMENDATION or "
        "UNKNOWN. Use FACT only when you can cite a supplied document. "
        "Return JSON only."
    )

    def __init__(self, gateway: LLMGateway, tools: ToolRegistry):
        self.gateway = gateway
        self.tools = tools

    # ---------------------------------------------------------- subclass API
    @abstractmethod
    def gather(self) -> Dict[str, Any]:
        """Collect context via tools. Returned dict is rendered into the prompt."""

    @abstractmethod
    def system_prompt(self) -> str:
        """Role-specific instructions, appended to CONTRACT."""

    @abstractmethod
    def user_prompt(self, context: Dict[str, Any]) -> str:
        """The task, including the gathered context."""

    @abstractmethod
    def parse(self, data: Any, context: Dict[str, Any]) -> AgentOutput:
        """Turn the model's JSON into an AgentOutput."""

    @abstractmethod
    def deterministic(self, context: Dict[str, Any], reason: str) -> AgentOutput:
        """Evidence-only result used when the model is unavailable (§44)."""

    # ------------------------------------------------------------- execution
    def run(self, max_tokens: int = 4000, timeout: int = 90) -> AgentOutput:
        context = self.gather()

        request = LLMRequest(
            messages=[
                Message(Role.SYSTEM, f"{self.CONTRACT}\n\n{self.system_prompt()}"),
                Message(Role.USER, self.user_prompt(context)),
            ],
            temperature=0.0, max_tokens=max_tokens, timeout_seconds=timeout, json_mode=True,
        )

        try:
            data, result = self.gateway.complete_json(request)
        except Exception as exc:  # noqa: BLE001 - degrade, never block the lifecycle
            out = self.deterministic(context, f"{type(exc).__name__}: {exc}")
            out.tool_calls = list(self.tools.calls)
            out.warnings.append(
                "AI enrichment unavailable; produced a deterministic evidence-only result.")
            return out

        out = self.parse(data, context)
        out.tool_calls = list(self.tools.calls)
        if result.response:
            out.provider = result.response.provider
            out.model = result.response.model
            out.prompt_tokens = result.response.usage.prompt_tokens
            out.completion_tokens = result.response.usage.completion_tokens
            out.duration_ms = result.response.latency_ms
        return out

    # --------------------------------------------------------------- helpers
    def statement(self, text: str, provenance: str = "AI_INFERENCE",
                  kind: str = "", confidence: str = "MEDIUM",
                  evidence: Optional[List[dict]] = None) -> Statement:
        """Build a provenance-checked statement from model output.

        Unrecognised provenance from a model degrades to ASSUMPTION rather than
        being trusted or dropped.
        """
        try:
            prov = Provenance(str(provenance).upper())
        except ValueError:
            prov = Provenance.ASSUMPTION
        try:
            conf = Confidence(str(confidence).upper())
        except ValueError:
            conf = Confidence.MEDIUM

        refs = []
        for e in evidence or []:
            if isinstance(e, dict) and e.get("evidence_id"):
                refs.append(EvidenceRef(evidence_id=str(e["evidence_id"]),
                                        locator=str(e.get("locator", "")),
                                        excerpt=str(e.get("excerpt", ""))))
        s = Statement(text=text, provenance=prov, confidence=conf,
                      evidence=refs, created_by=self.id)
        s.kind = kind or "note"   # attached for convenience; persisted separately
        return s

    @staticmethod
    def as_list(value: Any) -> List[Any]:
        """Models return a string, a list, or a dict of lists. Normalise all three."""
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return list(value.values())
        return [value]

    @classmethod
    def summary_text(cls, value: Any, limit: int = 2000) -> str:
        """Flatten a summary the model may return as an object or a list.

        The prompt asks for `{"text": ...}` objects throughout, so the summary
        comes back that way too; stringifying it put a Python dict literal on
        the board.
        """
        if isinstance(value, list):
            parts = [cls.text_of(v) for v in value]
            return " ".join(p for p in parts if p).strip()[:limit]
        return cls.text_of(value or "")[:limit]

    @staticmethod
    def text_of(item: Any) -> str:
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            for key in ("text", "requirement", "description", "name", "title", "question"):
                if item.get(key):
                    return str(item[key])
            return json.dumps(item, ensure_ascii=False)[:400]
        return str(item)
