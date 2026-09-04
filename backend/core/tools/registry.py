"""Tool system (spec §37).

Agents must *look things up* rather than assert from memory. A tool is a named,
schema-described function over the canonical model; the agent receives tool
results as evidence and cites them.

Every invocation is recorded, so an agent's output can be traced back to the
exact reads that produced it.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ToolSpec:
    """Description handed to the model so it can choose a tool."""

    name: str
    description: str
    parameters: Dict[str, str] = field(default_factory=dict)   # name -> description
    returns: str = ""

    def to_prompt(self) -> str:
        args = ", ".join(f"{k}: {v}" for k, v in self.parameters.items()) or "no arguments"
        return f"- {self.name}({args}) -> {self.returns or 'result'}: {self.description}"


@dataclass
class ToolCall:
    """One recorded invocation, for the AI Run Centre (§34) and traceability."""

    tool: str
    arguments: Dict[str, Any]
    ok: bool
    result_summary: str = ""
    error: str = ""
    elapsed_ms: int = 0

    def to_dict(self) -> dict:
        return {"tool": self.tool, "arguments": self.arguments, "ok": self.ok,
                "result_summary": self.result_summary[:500], "error": self.error[:300],
                "elapsed_ms": self.elapsed_ms}


class Tool:
    def __init__(self, spec: ToolSpec, fn: Callable[..., Any]):
        self.spec = spec
        self.fn = fn

    def __call__(self, **kwargs) -> Any:
        return self.fn(**kwargs)


class ToolRegistry:
    """Tools available to an agent for one project, in one tenant."""

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}
        self.calls: List[ToolCall] = []

    def register(self, spec: ToolSpec, fn: Callable[..., Any]) -> None:
        self._tools[spec.name] = Tool(spec, fn)

    def names(self) -> List[str]:
        return sorted(self._tools)

    def specs(self) -> List[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    def describe(self) -> str:
        """Tool catalogue rendered for a prompt."""
        return "\n".join(t.spec.to_prompt() for t in self._tools.values())

    def invoke(self, name: str, **kwargs) -> Any:
        """Call a tool, recording success or failure either way."""
        t0 = time.monotonic()
        tool = self._tools.get(name)
        if not tool:
            call = ToolCall(name, kwargs, False, error=f"Unknown tool '{name}'.")
            self.calls.append(call)
            raise KeyError(call.error)
        try:
            result = tool(**kwargs)
            self.calls.append(ToolCall(
                name, kwargs, True, _summarize(result),
                elapsed_ms=int((time.monotonic() - t0) * 1000)))
            return result
        except Exception as exc:  # noqa: BLE001 - recorded and re-raised
            self.calls.append(ToolCall(
                name, kwargs, False, error=f"{type(exc).__name__}: {exc}",
                elapsed_ms=int((time.monotonic() - t0) * 1000)))
            raise


def _summarize(result: Any) -> str:
    if isinstance(result, list):
        return f"{len(result)} item(s)"
    if isinstance(result, dict):
        return f"keys: {', '.join(list(result)[:8])}"
    text = str(result)
    return text[:200]


# --------------------------------------------------------------------------
# Concrete tools over the canonical model.
# --------------------------------------------------------------------------
def build_project_tools(repo, project_id: str) -> ToolRegistry:
    """Read-only tools scoped to one project.

    Deliberately read-only: agents propose, the orchestrator persists. That
    keeps writes inside the approval and provenance path (§69).
    """
    reg = ToolRegistry()

    def project_summary() -> dict:
        p = repo.get_project(project_id)
        if not p:
            raise KeyError("Project not found")
        return {"name": p.name, "intent": p.intent, "domain": p.domain,
                "customer": p.customer, "version": p.version}

    def list_evidence() -> list:
        return [{"id": e.id, "name": e.name, "document_type": e.document_type,
                 "sensitivity": e.sensitivity, "chars": len(e.extracted_text or ""),
                 "status": e.status}
                for e in repo.list_evidence(project_id)]

    def read_evidence(evidence_id: str, max_chars: int = 4000) -> dict:
        for e in repo.list_evidence(project_id):
            if e.id == evidence_id:
                return {"id": e.id, "name": e.name,
                        "text": (e.extracted_text or "")[:max_chars],
                        "truncated": len(e.extracted_text or "") > max_chars}
        raise KeyError(f"Evidence {evidence_id} not found in this project.")

    def search_evidence(query: str, limit: int = 5) -> list:
        """Keyword search across evidence text. Returns citable locators."""
        terms = [t for t in (query or "").lower().split() if len(t) > 2]
        hits: List[dict] = []
        for e in repo.list_evidence(project_id):
            text = (e.extracted_text or "")
            low = text.lower()
            score = sum(low.count(t) for t in terms)
            if score:
                idx = min((low.find(t) for t in terms if low.find(t) >= 0), default=0)
                start = max(0, idx - 120)
                hits.append({"evidence_id": e.id, "name": e.name, "score": score,
                             "locator": f"offset:{idx}",
                             "excerpt": text[start:start + 320]})
        return sorted(hits, key=lambda h: -h["score"])[:limit]

    def list_statements(kind: str = "") -> list:
        return [{"id": s.id, "ref": s.ref, "kind": s.kind, "text": s.text,
                 "provenance": s.provenance, "confidence": s.confidence}
                for s in repo.list_statements(project_id, kind or None)]

    def list_unknowns() -> list:
        return [{"id": s.id, "text": s.text, "stage": s.stage}
                for s in repo.list_statements(project_id)
                if s.provenance == "UNKNOWN"]

    def list_artifacts() -> list:
        return [{"kind": a.kind, "version": a.version, "stage": a.stage,
                 "created_at": a.created_at.isoformat() if a.created_at else None}
                for a in repo.list_artifacts(project_id)]

    def read_artifact(kind: str) -> dict:
        a = repo.latest_artifact(project_id, kind)
        if not a:
            raise KeyError(f"No artifact of kind '{kind}' exists yet.")
        try:
            content = json.loads(a.content)
        except (json.JSONDecodeError, TypeError):
            content = a.content
        return {"kind": a.kind, "version": a.version, "content": content}

    def platform_capabilities() -> dict:
        """Candidate platforms and their fit profiles — never invented (§14)."""
        from c_invent.services.platforms import PLATFORM_CATALOG
        return PLATFORM_CATALOG

    specs = [
        (ToolSpec("project_summary", "The project's name, intent, domain and version.",
                  {}, "project record"), project_summary),
        (ToolSpec("list_evidence", "List all evidence documents attached to the project.",
                  {}, "list of documents"), list_evidence),
        (ToolSpec("read_evidence", "Read the extracted text of one evidence document.",
                  {"evidence_id": "id from list_evidence", "max_chars": "optional limit"},
                  "document text"), read_evidence),
        (ToolSpec("search_evidence", "Keyword-search evidence and return citable excerpts.",
                  {"query": "search terms", "limit": "max hits"},
                  "hits with evidence_id, locator and excerpt"), search_evidence),
        (ToolSpec("list_statements", "List canonical statements, optionally by kind.",
                  {"kind": "requirement|risk|unknown|objective (optional)"},
                  "statements with provenance"), list_statements),
        (ToolSpec("list_unknowns", "List everything explicitly not yet known.",
                  {}, "open questions"), list_unknowns),
        (ToolSpec("list_artifacts", "List artifacts generated so far.", {}, "artifact index"),
         list_artifacts),
        (ToolSpec("read_artifact", "Read the latest artifact of a given kind.",
                  {"kind": "artifact kind"}, "artifact content"), read_artifact),
        (ToolSpec("platform_capabilities", "Candidate target platforms and fit profiles.",
                  {}, "platform catalogue"), platform_capabilities),
    ]
    for spec, fn in specs:
        reg.register(spec, fn)
    return reg
