"""Discovery, Assessment and Requirements agents (spec §10, §11, §13).

Each agent gathers context through tools, asks the model for structured output,
and degrades to an evidence-only result when the model is unavailable.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from agents_v2.base import AgentOutput, BaseAgent


def _evidence_digest(tools, budget: int = 6000) -> List[dict]:
    """Read evidence up to a character budget so prompts stay bounded."""
    docs = tools.invoke("list_evidence")
    digest: List[dict] = []
    for d in docs:
        if budget <= 0:
            break
        take = min(1800, budget)
        try:
            body = tools.invoke("read_evidence", evidence_id=d["id"], max_chars=take)
        except KeyError:
            continue
        text = body.get("text") or ""
        if text:
            digest.append({"evidence_id": d["id"], "name": d["name"],
                           "document_type": d.get("document_type", ""), "text": text})
            budget -= len(text)
    return digest


def _render(digest: List[dict]) -> str:
    if not digest:
        return "No documents have been supplied yet."
    return "\n\n".join(
        f"DOCUMENT id={d['evidence_id']} name={d['name']} type={d['document_type']}\n{d['text']}"
        for d in digest)


class DiscoveryAgent(BaseAgent):
    """Convert intent + evidence into structured discovery facts (§10)."""

    id = "discovery"
    stage = "discovery"

    def gather(self) -> Dict[str, Any]:
        return {"project": self.tools.invoke("project_summary"),
                "digest": _evidence_digest(self.tools)}

    def system_prompt(self) -> str:
        return (
            "You are the Discovery Agent for an enterprise delivery platform. "
            "Produce a structured discovery record from the customer's intent and "
            "supplied documents. Cite evidence ids for anything you mark as FACT. "
            "Anything the documents do not establish must appear in `unknowns` as a "
            "specific question you would ask the customer."
        )

    def user_prompt(self, ctx: Dict[str, Any]) -> str:
        p = ctx["project"]
        return (
            f"CUSTOMER INTENT:\n{p.get('intent') or '(none supplied)'}\n\n"
            f"DOMAIN: {p.get('domain') or 'unspecified'}\n\n"
            f"SUPPLIED EVIDENCE:\n{_render(ctx['digest'])}\n\n"
            "Return JSON with exactly these keys: summary (string), "
            "objectives, processes, actors, systems, sources, requirements, "
            "constraints, risks, assumptions, unknowns, next_steps. "
            "Each of those is an array of objects: "
            '{"text": "...", "provenance": "FACT|AI_INFERENCE|ASSUMPTION|UNKNOWN", '
            '"evidence": [{"evidence_id": "...", "locator": "..."}]}.'
        )

    def parse(self, data: Any, ctx: Dict[str, Any]) -> AgentOutput:
        if not isinstance(data, dict):
            return self.deterministic(ctx, "Model returned a non-object response.")

        out = AgentOutput(agent=self.id, stage=self.stage,
                          summary=self.summary_text(data.get("summary")))
        kinds = ["objectives", "processes", "actors", "systems", "sources",
                 "requirements", "constraints", "risks", "assumptions",
                 "unknowns", "next_steps"]
        singular = {"objectives": "objective", "processes": "process", "actors": "actor",
                    "systems": "system", "sources": "source", "requirements": "requirement",
                    "constraints": "constraint", "risks": "risk",
                    "assumptions": "assumption", "unknowns": "unknown",
                    "next_steps": "next_step"}

        for key in kinds:
            for item in self.as_list(data.get(key)):
                text = self.text_of(item)
                if not text.strip():
                    continue
                prov = (item.get("provenance") if isinstance(item, dict) else None) or (
                    "UNKNOWN" if key == "unknowns" else "AI_INFERENCE")
                out.statements.append(self.statement(
                    text, prov, singular[key],
                    evidence=(item.get("evidence") if isinstance(item, dict) else None)))

        out.artifacts["discovery"] = {
            "summary": out.summary,
            **{k: [self.text_of(i) for i in self.as_list(data.get(k))] for k in kinds},
            "generation_mode": "ai",
        }
        return out

    def deterministic(self, ctx: Dict[str, Any], reason: str) -> AgentOutput:
        """Evidence-only discovery.

        Without a model this still mines the supplied documents rather than
        emitting boilerplate: an RFI/RFP tracker is a table of requirements, and
        reproducing the customer's own rows verbatim is far more use than five
        generic questions.
        """
        p, digest = ctx["project"], ctx["digest"]
        out = AgentOutput(
            agent=self.id, stage=self.stage,
            generation_mode="deterministic_evidence_only",
            summary=("Discovery derived from supplied evidence only. AI enrichment was "
                     "unavailable, so nothing beyond the documents is inferred."),
        )
        if p.get("intent"):
            out.statements.append(self.statement(
                f"Stated customer intent: {p['intent']}", "CUSTOMER_DECISION", "objective"))
        for d in digest:
            out.statements.append(self.statement(
                f"Evidence supplied: {d['name']}", "FACT", "source",
                evidence=[{"evidence_id": d["evidence_id"], "locator": "document"}]))

        # Requirement tables are the richest deterministic signal available.
        # The prompt digest is capped at ~1800 characters per document, which
        # truncates a tracker mid-table, so the full text is re-read here.
        table = {}
        try:
            from core.tabular_intake import extract_documents, summarize
            docs = []
            for d in digest:
                try:
                    body = self.tools.invoke("read_evidence",
                                             evidence_id=d["evidence_id"], max_chars=400_000)
                    docs.append({"name": d["name"], "text": body.get("text", "")})
                except Exception:
                    docs.append({"name": d["name"], "text": d.get("text", "")})
            table = extract_documents(docs)
        except Exception:
            table = {}

        requirements = []
        # A tracker row the customer has not answered is an open question, not
        # an established fact. Recording it as FACT overstates readiness — the
        # board would report a tracker of open questions as fully evidenced.
        table_questions = []
        requirement_rows: List[dict] = []
        for row in (table.get("requirements") or []):
            ref = row.get("ref") or ""
            category = row.get("category") or ""
            text = f"{('[' + ref + '] ') if ref else ''}{row['text']}" \
                   f"{(' (' + category + ')') if category else ''}"
            evidence = [{"evidence_id": digest[0]["evidence_id"] if digest else "",
                         "locator": row.get("locator", "")}]

            if row.get("is_question"):
                table_questions.append(text)
                st = self.statement(text, "UNKNOWN", "question", "LOW",
                                    evidence=evidence)
            else:
                requirements.append(text)
                # Downstream stages restate these rows. Without the citation
                # travelling with them, the restated copy is an unevidenced
                # FACT and is correctly downgraded to AI_INFERENCE — which
                # then reads as model analysis on a stage that ran no model.
                requirement_rows.append({"text": text, "evidence": evidence})
                st = self.statement(text, "FACT", "requirement", "HIGH",
                                    evidence=evidence)
            st.ref = ref
            out.statements.append(st)

        if table.get("found"):
            try:
                out.summary += " " + summarize(table)
            except Exception:
                pass

        # Only fall back to generic prompts when the evidence yielded nothing.
        unknowns = []
        # Unanswered rows that read as questions are already recorded
        # individually above; a blanket note would duplicate them, once as an
        # unknown and again as a question.
        unnoted = int(table.get("unanswered_count") or 0) - len(table_questions)
        if unnoted > 0:
            unknowns.append(f"{unnoted} requirement rows in the supplied tracker "
                            f"have no response recorded yet.")
        if not requirements and not table_questions:
            unknowns += [
                "What are the source systems and their data volumes?",
                "What data freshness is required (batch, hourly, near-real-time)?",
                "Which regulatory regimes apply to this data?",
                "Which reports and users must be supported at go-live?",
                "What is the target platform and who owns that decision?",
            ]
        for question in unknowns:
            out.statements.append(self.statement(question, "UNKNOWN", "unknown", "LOW"))

        out.artifacts["discovery"] = {
            "summary": out.summary,
            "evidence": [d["name"] for d in digest],
            "requirements": requirements,
            "requirement_rows": requirement_rows,
            "open_questions": table_questions,
            "unknowns": unknowns,
            "extracted_tables": table.get("tables", []),
            "requirement_table_summary": {
                "requirement_count": table.get("requirement_count", 0),
                "answered": table.get("answered_count", 0),
                "unanswered": table.get("unanswered_count", 0),
                "open_questions": table.get("open_question_count", 0),
                "stated_requirements": table.get("stated_requirement_count", 0),
                "categories": table.get("categories", {}),
            } if table.get("found") else {},
            "generation_mode": "deterministic_evidence_only",
            "reason": reason[:400],
        }
        return out


class AssessmentAgent(BaseAgent):
    """Current-state assessment across the §13 dimensions."""

    id = "assessment"
    stage = "assessment"

    DIMENSIONS = ["architecture", "data", "applications", "infrastructure",
                  "security", "governance", "integration", "bi", "ai_ml",
                  "operations", "people", "processes"]

    def gather(self) -> Dict[str, Any]:
        ctx: Dict[str, Any] = {"project": self.tools.invoke("project_summary"),
                               "statements": self.tools.invoke("list_statements"),
                               "unknowns": self.tools.invoke("list_unknowns")}
        try:
            ctx["discovery"] = self.tools.invoke("read_artifact", kind="discovery")["content"]
        except KeyError:
            ctx["discovery"] = None
        return ctx

    def system_prompt(self) -> str:
        return (
            "You are the Assessment Agent. Produce an evidence-based current-state "
            "assessment. A dimension with no supporting evidence must be rated "
            "'unknown' — never guess a maturity level. Readiness is a delivery "
            "judgement, not a platform connection test."
        )

    def user_prompt(self, ctx: Dict[str, Any]) -> str:
        return (
            f"PROJECT: {json.dumps(ctx['project'])}\n\n"
            f"DISCOVERY: {json.dumps(ctx.get('discovery'))[:4000]}\n\n"
            f"KNOWN STATEMENTS: {json.dumps(ctx['statements'][:60])[:3000]}\n\n"
            f"OPEN UNKNOWNS: {json.dumps(ctx['unknowns'][:30])[:1500]}\n\n"
            "Return JSON: {\"summary\": \"...\", \"dimensions\": {"
            + ", ".join(f'"{d}"' for d in self.DIMENSIONS)
            + "}, \"gaps\": [], \"risks\": [], \"technical_debt\": [], "
            "\"modernization_opportunities\": [], \"readiness\": \"READY|PARTIAL|AT_RISK|UNKNOWN\"}. "
            "Each dimension is {\"status\": \"READY|PARTIAL|AT_RISK|UNKNOWN\", "
            "\"findings\": [\"...\"], \"evidence\": []}."
        )

    def parse(self, data: Any, ctx: Dict[str, Any]) -> AgentOutput:
        if not isinstance(data, dict):
            return self.deterministic(ctx, "Model returned a non-object response.")
        out = AgentOutput(agent=self.id, stage=self.stage,
                          summary=self.summary_text(data.get("summary")))
        dims = data.get("dimensions") or {}
        for name in self.DIMENSIONS:
            d = dims.get(name) or {}
            status = str(d.get("status", "UNKNOWN")).upper()
            for f in self.as_list(d.get("findings")):
                out.statements.append(self.statement(
                    f"[{name}] {self.text_of(f)}",
                    "UNKNOWN" if status == "UNKNOWN" else "AI_INFERENCE",
                    "finding", evidence=d.get("evidence")))
        for key, kind in (("gaps", "gap"), ("risks", "risk"),
                          ("technical_debt", "technical_debt"),
                          ("modernization_opportunities", "opportunity")):
            for item in self.as_list(data.get(key)):
                out.statements.append(self.statement(self.text_of(item), "AI_INFERENCE", kind))

        out.artifacts["assessment"] = {
            "summary": out.summary,
            "dimensions": {n: dims.get(n, {"status": "UNKNOWN", "findings": []})
                           for n in self.DIMENSIONS},
            "readiness": data.get("readiness", "UNKNOWN"),
            "generation_mode": "ai",
        }
        return out

    def deterministic(self, ctx: Dict[str, Any], reason: str) -> AgentOutput:
        """Without a model, every dimension is honestly UNKNOWN."""
        out = AgentOutput(
            agent=self.id, stage=self.stage,
            generation_mode="deterministic_evidence_only",
            summary=("Assessment could not be enriched by AI. Dimensions are reported as "
                     "UNKNOWN rather than estimated, and require customer input."),
        )
        dims = {}
        for name in self.DIMENSIONS:
            dims[name] = {"status": "UNKNOWN",
                          "findings": ["No evidence assessed; customer input required."]}
            out.statements.append(self.statement(
                f"[{name}] Current state not established.", "UNKNOWN", "finding", "LOW"))
        out.artifacts["assessment"] = {
            "summary": out.summary, "dimensions": dims, "readiness": "UNKNOWN",
            "generation_mode": "deterministic_evidence_only", "reason": reason[:400],
        }
        return out


class RequirementsAgent(BaseAgent):
    """Structured functional / non-functional / security requirements (§9, §10)."""

    id = "requirements"
    stage = "requirements"

    def gather(self) -> Dict[str, Any]:
        ctx: Dict[str, Any] = {"project": self.tools.invoke("project_summary"),
                               "existing": self.tools.invoke("list_statements", kind="requirement")}
        try:
            ctx["discovery"] = self.tools.invoke("read_artifact", kind="discovery")["content"]
        except KeyError:
            ctx["discovery"] = None
        return ctx

    def system_prompt(self) -> str:
        return (
            "You are the Requirements Agent. Convert discovery output into numbered, "
            "testable requirements. Each requirement must be independently verifiable "
            "and carry a category and priority. Do not invent SLAs, volumes or "
            "compliance obligations that the evidence does not establish."
        )

    def user_prompt(self, ctx: Dict[str, Any]) -> str:
        return (
            f"PROJECT: {json.dumps(ctx['project'])}\n\n"
            f"DISCOVERY: {json.dumps(ctx.get('discovery'))[:5000]}\n\n"
            f"EXISTING REQUIREMENTS: {json.dumps(ctx['existing'][:40])[:2000]}\n\n"
            "Return JSON: {\"requirements\": [{\"ref\": \"R-1\", \"text\": \"...\", "
            "\"category\": \"functional|non_functional|security|compliance|integration|data\", "
            "\"priority\": \"must|should|could\", \"provenance\": \"FACT|AI_INFERENCE|ASSUMPTION\", "
            "\"acceptance\": \"how it is verified\", \"evidence\": []}]}"
        )

    def parse(self, data: Any, ctx: Dict[str, Any]) -> AgentOutput:
        if not isinstance(data, dict):
            return self.deterministic(ctx, "Model returned a non-object response.")
        out = AgentOutput(agent=self.id, stage=self.stage)
        rows: List[dict] = []
        for i, item in enumerate(self.as_list(data.get("requirements")), start=1):
            text = self.text_of(item)
            if not text.strip():
                continue
            ref = (item.get("ref") if isinstance(item, dict) else None) or f"R-{i}"
            s = self.statement(
                text, (item.get("provenance") if isinstance(item, dict) else "AI_INFERENCE"),
                "requirement", evidence=(item.get("evidence") if isinstance(item, dict) else None))
            s.ref = ref
            out.statements.append(s)
            rows.append({
                "ref": ref, "text": text,
                "category": (item.get("category") if isinstance(item, dict) else "") or "functional",
                "priority": (item.get("priority") if isinstance(item, dict) else "") or "should",
                "acceptance": (item.get("acceptance") if isinstance(item, dict) else "") or "",
                "provenance": s.provenance.value,
            })
        out.summary = f"{len(rows)} requirements derived from discovery evidence."
        out.artifacts["requirements"] = {"requirements": rows, "generation_mode": "ai"}
        return out

    def deterministic(self, ctx: Dict[str, Any], reason: str) -> AgentOutput:
        """Carry forward discovery requirements verbatim rather than inventing any."""
        out = AgentOutput(
            agent=self.id, stage=self.stage,
            generation_mode="deterministic_evidence_only",
            summary="Requirements carried forward from discovery without AI enrichment.")
        rows: List[dict] = []
        disc = ctx.get("discovery") or {}

        # These rows are copied verbatim; nothing is inferred here. Labelling
        # them AI_INFERENCE claimed model analysis that never ran, and showed
        # as AI-provenance statements under a stage badged "no AI". The honest
        # label is whatever produced them upstream.
        carried = ("AI_INFERENCE" if (disc.get("generation_mode") or "") == "ai"
                   else "FACT")
        confidence = "LOW" if carried == "AI_INFERENCE" else "HIGH"
        cited = {r.get("text"): r.get("evidence") or []
                 for r in self.as_list(disc.get("requirement_rows"))
                 if isinstance(r, dict)}
        for i, text in enumerate(self.as_list(disc.get("requirements")), start=1):
            t = self.text_of(text)
            if not t.strip():
                continue
            ref = f"R-{i}"
            s = self.statement(t, carried, "requirement", confidence,
                               evidence=cited.get(t) or [])
            s.ref = ref
            out.statements.append(s)
            rows.append({"ref": ref, "text": t, "category": "functional",
                         "priority": "should", "acceptance": "",
                         "provenance": s.provenance.value})
        if not rows:
            out.statements.append(self.statement(
                "No requirements could be derived; discovery must be completed first.",
                "UNKNOWN", "unknown", "LOW"))
        out.artifacts["requirements"] = {
            "requirements": rows,
            "generation_mode": "deterministic_evidence_only", "reason": reason[:400]}
        return out


class QuestionSetAgent(BaseAgent):
    """Turn every UNKNOWN into a targeted customer question (spec §11).

    Discovery records what is *not* known; this stage converts those gaps into
    questions the customer can actually answer, with suggested answer options so
    the reply lands back in the canonical model as a CUSTOMER_DECISION.
    """

    id = "questions"
    stage = "questions"

    def gather(self) -> Dict[str, Any]:
        return {"project": self.tools.invoke("project_summary"),
                "unknowns": self.tools.invoke("list_unknowns")}

    def system_prompt(self) -> str:
        return (
            "You are the Discovery Questions Agent. Convert each open unknown into a "
            "single, specific question a customer stakeholder can answer without "
            "guessing. Offer concrete answer options where the question has a bounded "
            "set of sensible replies, and name the role best placed to answer."
        )

    def user_prompt(self, ctx: Dict[str, Any]) -> str:
        return (
            f"PROJECT: {json.dumps(ctx['project'])}\n\n"
            f"OPEN UNKNOWNS:\n{json.dumps(ctx['unknowns'][:40], indent=1)[:3000]}\n\n"
            "Return JSON: {\"questions\": [{\"question\": \"...\", "
            "\"why_it_matters\": \"...\", \"options\": [\"...\"], "
            "\"owner_role\": \"e.g. Data Architect\", "
            "\"blocks\": \"which stage this blocks\"}]}"
        )

    def parse(self, data: Any, ctx: Dict[str, Any]) -> AgentOutput:
        if not isinstance(data, dict):
            return self.deterministic(ctx, "Model returned a non-object response.")
        out = AgentOutput(agent=self.id, stage=self.stage)
        rows: List[dict] = []
        for item in self.as_list(data.get("questions")):
            text = self.text_of(item)
            if not text.strip():
                continue
            row = {"question": text,
                   "why_it_matters": (item.get("why_it_matters") if isinstance(item, dict) else "") or "",
                   "options": self.as_list(item.get("options")) if isinstance(item, dict) else [],
                   "owner_role": (item.get("owner_role") if isinstance(item, dict) else "") or "Customer",
                   "blocks": (item.get("blocks") if isinstance(item, dict) else "") or "",
                   "status": "open"}
            rows.append(row)
            out.statements.append(self.statement(text, "UNKNOWN", "question", "LOW"))

        out.summary = f"{len(rows)} customer questions generated from open unknowns."
        out.artifacts["question_set"] = {"questions": rows, "generation_mode": "ai"}
        return out

    def deterministic(self, ctx: Dict[str, Any], reason: str) -> AgentOutput:
        """Carry the unknowns forward verbatim — they are already questions."""
        rows = [{"question": u["text"], "why_it_matters": "", "options": [],
                 "owner_role": "Customer", "blocks": u.get("stage", ""), "status": "open"}
                for u in ctx["unknowns"]]
        out = AgentOutput(
            agent=self.id, stage=self.stage,
            generation_mode="deterministic_evidence_only",
            summary=(f"{len(rows)} open unknowns carried forward as customer questions "
                     f"without AI refinement."))
        for r in rows:
            out.statements.append(self.statement(r["question"], "UNKNOWN", "question", "LOW"))
        out.artifacts["question_set"] = {
            "questions": rows, "generation_mode": "deterministic_evidence_only",
            "reason": reason[:400]}
        return out
