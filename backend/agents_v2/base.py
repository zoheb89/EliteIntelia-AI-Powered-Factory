"""Agent base class for the governed EliteInteliA lifecycle."""
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
    agent: str
    stage: str
    summary: str = ""
    statements: List[Statement] = field(default_factory=list)
    artifacts: Dict[str, Any] = field(default_factory=dict)
    generation_mode: str = "ai"
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
        return {"agent": self.agent, "stage": self.stage, "summary": self.summary,
                "generation_mode": self.generation_mode, "provider": self.provider,
                "model": self.model, "degraded": self.degraded,
                "statement_count": len(self.statements), "artifacts": list(self.artifacts),
                "tool_calls": [c.to_dict() for c in self.tool_calls], "warnings": self.warnings,
                "usage": {"prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens}}


class BaseAgent(ABC):
    id: str = "agent"
    stage: str = ""
    prompt_version: str = "v1"
    CONTRACT = (
        "You analyse only the evidence supplied to you. You never invent customer facts, "
        "data volumes, SLAs, compliance certifications, pricing or platform constraints. "
        "When information is not available you return it as UNKNOWN with a specific question. "
        "Every item must carry provenance FACT, AI_INFERENCE, ASSUMPTION, RECOMMENDATION or UNKNOWN. "
        "Use FACT only when you can cite a supplied document. Return JSON only."
    )

    def __init__(self, gateway: LLMGateway, tools: ToolRegistry):
        self.gateway = gateway
        self.tools = tools

    @abstractmethod
    def gather(self) -> Dict[str, Any]: ...
    @abstractmethod
    def system_prompt(self) -> str: ...
    @abstractmethod
    def user_prompt(self, context: Dict[str, Any]) -> str: ...
    @abstractmethod
    def parse(self, data: Any, context: Dict[str, Any]) -> AgentOutput: ...
    @abstractmethod
    def deterministic(self, context: Dict[str, Any], reason: str) -> AgentOutput: ...

    @staticmethod
    def _attach_business_analysis(out: AgentOutput, context: Dict[str, Any]) -> AgentOutput:
        """Project requirements into BRD/FRD/SRD for both AI and fallback runs."""
        if out.stage != "requirements":
            return out
        try:
            from core.ba_factory import build as build_ba
            ba = build_ba(context.get("project") or {}, context.get("discovery") or {},
                          out.artifacts.get("requirements") or {}, context.get("assessment"))
            out.artifacts["brd"] = ba["brd"]
            out.artifacts["frd"] = ba["frd"]
            out.artifacts["srd"] = ba["srd"]
            out.artifacts["ba_traceability"] = ba["traceability"]
            out.artifacts["business_analysis"] = ba
            out.warnings.append("BRD, FRD and SRD projected from the canonical requirements model.")
        except Exception as exc:
            out.warnings.append(f"Business Analysis projection failed: {exc}")
        return out

    def run(self, max_tokens: int = 4000, timeout: int = 90) -> AgentOutput:
        context = self.gather()
        request = LLMRequest(
            messages=[Message(Role.SYSTEM, f"{self.CONTRACT}\n\n{self.system_prompt()}"),
                      Message(Role.USER, self.user_prompt(context))],
            temperature=0.0, max_tokens=max_tokens, timeout_seconds=timeout, json_mode=True,
        )
        try:
            data, result = self.gateway.complete_json(request)
        except Exception as exc:
            out = self.deterministic(context, f"{type(exc).__name__}: {exc}")
            out.tool_calls = list(self.tools.calls)
            out.warnings.append("AI enrichment unavailable; produced a deterministic evidence-only result.")
            return self._attach_business_analysis(out, context)

        out = self.parse(data, context)
        out.tool_calls = list(self.tools.calls)
        if result.response:
            out.provider = result.response.provider
            out.model = result.response.model
            out.prompt_tokens = result.response.usage.prompt_tokens
            out.completion_tokens = result.response.usage.completion_tokens
            out.duration_ms = result.response.latency_ms
        return self._attach_business_analysis(out, context)

    def statement(self, text: str, provenance: str = "AI_INFERENCE", kind: str = "",
                  confidence: str = "MEDIUM", evidence: Optional[List[dict]] = None) -> Statement:
        try: prov = Provenance(str(provenance).upper())
        except ValueError: prov = Provenance.ASSUMPTION
        try: conf = Confidence(str(confidence).upper())
        except ValueError: conf = Confidence.MEDIUM
        refs = []
        for e in evidence or []:
            if isinstance(e, dict) and e.get("evidence_id"):
                refs.append(EvidenceRef(evidence_id=str(e["evidence_id"]), locator=str(e.get("locator", "")), excerpt=str(e.get("excerpt", ""))))
        s = Statement(text=text, provenance=prov, confidence=conf, evidence=refs, created_by=self.id)
        s.kind = kind or "note"
        return s

    @staticmethod
    def as_list(value: Any) -> List[Any]:
        if value is None: return []
        if isinstance(value, list): return value
        if isinstance(value, dict): return list(value.values())
        return [value]

    @classmethod
    def summary_text(cls, value: Any, limit: int = 2000) -> str:
        if isinstance(value, list): return " ".join(p for p in (cls.text_of(v) for v in value) if p).strip()[:limit]
        return cls.text_of(value or "")[:limit]

    @staticmethod
    def text_of(item: Any) -> str:
        if isinstance(item, str): return item
        if isinstance(item, dict):
            for key in ("text", "requirement", "description", "name", "title", "question"):
                if item.get(key): return str(item[key])
            return json.dumps(item, ensure_ascii=False)[:400]
        return str(item)
