"""Evidence stage agent (spec §8, §9).

Document ingestion itself is deterministic and persists the canonical evidence
record. This agent turns the captured evidence into an auditable evidence-index
artifact that downstream agents can consume. It never invents customer facts;
when AI is unavailable the deterministic path remains fully usable.
"""
from __future__ import annotations

from typing import Any, Dict, List

from agents_v2.base import AgentOutput, BaseAgent


class EvidenceAgent(BaseAgent):
    """Index and qualify the evidence already captured for a project."""

    id = "evidence"
    stage = "evidence"

    def gather(self) -> Dict[str, Any]:
        docs = self.tools.invoke("list_evidence")
        records: List[dict] = []
        for doc in docs:
            records.append(doc)
        return {
            "project": self.tools.invoke("project_summary"),
            "evidence": records,
        }

    def system_prompt(self) -> str:
        return (
            "You are the Evidence Agent for an enterprise delivery factory. "
            "Review only the documents already captured in the canonical evidence "
            "store. Produce an evidence index, identify material themes, sensitivity, "
            "document coverage and gaps. Never invent customer facts. Every factual "
            "observation must cite an evidence_id."
        )

    def user_prompt(self, ctx: Dict[str, Any]) -> str:
        return (
            f"PROJECT: {ctx['project']}\n\n"
            f"CAPTURED EVIDENCE:\n{ctx['evidence']}\n\n"
            "Return JSON with exactly these keys: summary, documents, themes, "
            "gaps, sensitivity, next_steps. `documents` must contain one object per "
            "captured document with evidence_id, name, document_type, status and "
            "evidence [{evidence_id, locator}]. Themes/gaps/next_steps are arrays of "
            "objects with text and evidence where applicable."
        )

    def parse(self, data: Any, ctx: Dict[str, Any]) -> AgentOutput:
        if not isinstance(data, dict):
            return self.deterministic(ctx, "Model returned a non-object response.")

        out = AgentOutput(
            agent=self.id,
            stage=self.stage,
            summary=self.summary_text(data.get("summary")),
        )
        for key, kind in (("themes", "evidence_theme"), ("gaps", "evidence_gap"),
                          ("next_steps", "next_step")):
            for item in self.as_list(data.get(key)):
                text = self.text_of(item)
                if not text.strip():
                    continue
                evidence = item.get("evidence") if isinstance(item, dict) else None
                provenance = "UNKNOWN" if key == "gaps" else "AI_INFERENCE"
                out.statements.append(self.statement(text, provenance, kind, "MEDIUM", evidence))

        documents = []
        for item in self.as_list(data.get("documents")):
            if isinstance(item, dict):
                documents.append(item)

        out.artifacts["evidence_index"] = {
            "summary": out.summary,
            "documents": documents or ctx["evidence"],
            "themes": data.get("themes") or [],
            "gaps": data.get("gaps") or [],
            "sensitivity": data.get("sensitivity") or [],
            "next_steps": data.get("next_steps") or [],
            "document_count": len(ctx["evidence"]),
            "generation_mode": "ai",
        }
        return out

    def deterministic(self, ctx: Dict[str, Any], reason: str) -> AgentOutput:
        docs = ctx["evidence"]
        out = AgentOutput(
            agent=self.id,
            stage=self.stage,
            generation_mode="deterministic_evidence_only",
            summary=(
                f"Evidence index created from {len(docs)} captured document(s). "
                "AI enrichment was unavailable; document metadata and coverage are "
                "reported without inventing customer facts."
            ),
        )

        sensitivity_counts: Dict[str, int] = {}
        document_rows: List[dict] = []
        for doc in docs:
            evidence_id = str(doc.get("id") or "")
            name = str(doc.get("name") or "Unnamed document")
            sensitivity = str(doc.get("sensitivity") or "normal")
            sensitivity_counts[sensitivity] = sensitivity_counts.get(sensitivity, 0) + 1
            document_rows.append({
                "evidence_id": evidence_id,
                "name": name,
                "document_type": doc.get("document_type") or "unknown",
                "status": doc.get("status") or "unknown",
                "sensitivity": sensitivity,
                "characters": doc.get("chars") or 0,
                "evidence": [{"evidence_id": evidence_id, "locator": "document"}],
            })
            out.statements.append(self.statement(
                f"Evidence captured: {name} ({doc.get('document_type') or 'unknown'}).",
                "FACT", "evidence", "HIGH",
                evidence=[{"evidence_id": evidence_id, "locator": "document"}],
            ))

        if not docs:
            out.statements.append(self.statement(
                "No evidence documents are currently attached to the project.",
                "UNKNOWN", "evidence_gap", "LOW",
            ))

        out.artifacts["evidence_index"] = {
            "summary": out.summary,
            "documents": document_rows,
            "document_count": len(document_rows),
            "sensitivity": sensitivity_counts,
            "gaps": [] if docs else ["Customer evidence has not been supplied yet."],
            "generation_mode": out.generation_mode,
            "degraded_reason": reason[:500],
        }
        return out
