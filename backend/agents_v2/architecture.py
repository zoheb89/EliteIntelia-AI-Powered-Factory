"""Platform selection and architecture agents (spec §14, §15).

`PlatformSelectionAgent` is deliberately a **hybrid**: the scoring is done by the
deterministic engine in `core.platform_selection`, and the model is used only to
narrate the result. A platform recommendation that changes between runs cannot be
defended to a customer, so the model never picks the winner.

`ArchitectureAgent` generates the target architecture *for the selected platform*,
which is why it sits behind the platform approval gate.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from agents_v2.base import AgentOutput, BaseAgent
from core.platform_selection import evaluate


class PlatformSelectionAgent(BaseAgent):
    """Evaluate candidates against evidenced requirements, then recommend (§14)."""

    id = "platform_selection"
    stage = "platform"

    def gather(self) -> Dict[str, Any]:
        requirements = [s["text"] for s in
                        self.tools.invoke("list_statements", kind="requirement")]
        constraints = [s["text"] for s in
                       self.tools.invoke("list_statements", kind="constraint")]
        project = self.tools.invoke("project_summary")
        # The customer's stated intent is itself evidence of direction.
        if project.get("intent"):
            constraints.append(project["intent"])

        # Deterministic scoring happens here, before the model is involved.
        evaluation = evaluate(requirements, constraints)
        return {"project": project, "requirements": requirements,
                "constraints": constraints, "evaluation": evaluation}

    def system_prompt(self) -> str:
        return (
            "You are the Platform Selection Agent. A deterministic engine has already "
            "scored every candidate platform against the customer's evidenced "
            "requirements. Your job is to explain that result in the customer's own "
            "terms — you must NOT change the ranking, invent a different winner, or "
            "introduce platforms that were not scored. If the top two options are "
            "close, say so plainly and describe what would break the tie."
        )

    def user_prompt(self, ctx: Dict[str, Any]) -> str:
        ev = ctx["evaluation"]
        options = [{"option": o["option"], "platform": o["platform"], "fit": o["fit"],
                    "advantages": o["advantages"], "disadvantages": o["disadvantages"]}
                   for o in ev["options"]]
        return (
            f"PROJECT: {json.dumps(ctx['project'])}\n\n"
            f"EVIDENCED REQUIREMENTS ({len(ctx['requirements'])}):\n"
            f"{json.dumps(ctx['requirements'][:30], indent=1)[:2500]}\n\n"
            f"WEIGHTED CRITERIA:\n{json.dumps(ev['criteria'][:8], indent=1)[:1500]}\n\n"
            f"SCORED OPTIONS (ranking is fixed):\n{json.dumps(options, indent=1)[:2500]}\n\n"
            "Return JSON: {\"summary\": \"2-3 sentences for an executive\", "
            "\"decision_drivers\": [\"...\"], \"tie_break\": \"what would change the "
            "recommendation, or empty\", \"risks\": [\"...\"], "
            "\"questions_for_customer\": [\"...\"]}"
        )

    def parse(self, data: Any, ctx: Dict[str, Any]) -> AgentOutput:
        ev = ctx["evaluation"]
        rec = ev.get("recommendation") or {}
        out = AgentOutput(agent=self.id, stage=self.stage)

        narrative = data if isinstance(data, dict) else {}
        out.summary = (str(narrative.get("summary", "")).strip()
                       or f"{rec.get('platform')} recommended at {rec.get('fit')}% fit.")

        # The recommendation itself is a RECOMMENDATION, never a decision.
        out.statements.append(self.statement(
            f"Recommended target platform: {rec.get('platform')} "
            f"({rec.get('fit')}% weighted fit). Requires human approval.",
            "RECOMMENDATION", "platform_recommendation", "HIGH"))

        for driver in self.as_list(narrative.get("decision_drivers")):
            out.statements.append(self.statement(
                self.text_of(driver), "AI_INFERENCE", "decision_driver"))
        for risk in self.as_list(narrative.get("risks")):
            out.statements.append(self.statement(self.text_of(risk), "AI_INFERENCE", "risk"))
        for q in self.as_list(narrative.get("questions_for_customer")):
            out.statements.append(self.statement(self.text_of(q), "UNKNOWN", "unknown", "LOW"))

        out.artifacts["platform_options"] = ev
        out.artifacts["platform_decision"] = {
            "recommended_platform": rec.get("platform"),
            "fit": rec.get("fit"),
            "decision_status": ev["decision_status"],
            "summary": out.summary,
            "decision_drivers": [self.text_of(d) for d in
                                 self.as_list(narrative.get("decision_drivers"))],
            "tie_break": narrative.get("tie_break", ""),
            "scoring_method": ev["method"],
            "generation_mode": "ai_narrative_over_deterministic_scoring",
        }
        return out

    def deterministic(self, ctx: Dict[str, Any], reason: str) -> AgentOutput:
        """Scoring never needed the model, so only the narrative is lost."""
        ev = ctx["evaluation"]
        rec = ev.get("recommendation") or {}
        out = AgentOutput(
            agent=self.id, stage=self.stage,
            generation_mode="deterministic_evidence_only",
            summary=(f"{rec.get('platform')} scores highest at {rec.get('fit')}% weighted "
                     f"fit against the evidenced requirements. Narrative enrichment was "
                     f"unavailable; the scoring is unaffected."),
        )
        out.statements.append(self.statement(
            f"Recommended target platform: {rec.get('platform')} "
            f"({rec.get('fit')}% weighted fit). Requires human approval.",
            "RECOMMENDATION", "platform_recommendation", "HIGH"))
        for c in ev["criteria"][:4]:
            if c["derived_from_evidence"]:
                out.statements.append(self.statement(
                    f"Decision driver: {c['criterion'].replace('_', ' ')} "
                    f"(weight {c['weight']}).", "AI_INFERENCE", "decision_driver"))

        out.artifacts["platform_options"] = ev
        out.artifacts["platform_decision"] = {
            "recommended_platform": rec.get("platform"), "fit": rec.get("fit"),
            "decision_status": ev["decision_status"], "summary": out.summary,
            "scoring_method": ev["method"],
            "generation_mode": "deterministic_evidence_only", "reason": reason[:400],
        }
        return out


class ArchitectureAgent(BaseAgent):
    """Target architecture for the selected platform (spec §15)."""

    id = "architecture"
    stage = "architecture"

    LAYERS = ["sources", "ingestion", "storage", "processing",
              "serving", "consumption", "governance", "operations"]

    def gather(self) -> Dict[str, Any]:
        ctx: Dict[str, Any] = {
            "project": self.tools.invoke("project_summary"),
            "requirements": [s["text"] for s in
                             self.tools.invoke("list_statements", kind="requirement")],
        }
        for kind in ("platform_decision", "assessment", "discovery"):
            try:
                ctx[kind] = self.tools.invoke("read_artifact", kind=kind)["content"]
            except KeyError:
                ctx[kind] = None
        return ctx

    def system_prompt(self) -> str:
        return (
            "You are the Architecture Agent. Design the target architecture for the "
            "platform that has already been selected — do not revisit the platform "
            "decision. Describe layers, components and the decisions behind them. "
            "Every component must trace to a requirement; if a layer cannot be "
            "designed from the evidence, mark it UNKNOWN rather than inventing it."
        )

    def user_prompt(self, ctx: Dict[str, Any]) -> str:
        platform = (ctx.get("platform_decision") or {}).get("recommended_platform", "unspecified")
        return (
            f"SELECTED PLATFORM: {platform}\n\n"
            f"PROJECT: {json.dumps(ctx['project'])}\n\n"
            f"REQUIREMENTS:\n{json.dumps(ctx['requirements'][:30], indent=1)[:3000]}\n\n"
            f"ASSESSMENT: {json.dumps(ctx.get('assessment'))[:2000]}\n\n"
            "Return JSON: {\"summary\": \"...\", \"components\": [{\"layer\": \""
            + "|".join(self.LAYERS) + "\", \"name\": \"...\", \"purpose\": \"...\", "
            "\"technology\": \"...\", \"satisfies\": [\"requirement text\"]}], "
            "\"decisions\": [{\"decision\": \"...\", \"rationale\": \"...\", "
            "\"alternatives\": [\"...\"], \"trade_offs\": \"...\"}], "
            "\"data_flow\": [\"step 1\", \"step 2\"], \"risks\": [\"...\"], "
            "\"unknowns\": [\"...\"]}"
        )

    def parse(self, data: Any, ctx: Dict[str, Any]) -> AgentOutput:
        if not isinstance(data, dict):
            return self.deterministic(ctx, "Model returned a non-object response.")
        platform = (ctx.get("platform_decision") or {}).get("recommended_platform", "unspecified")
        out = AgentOutput(agent=self.id, stage=self.stage,
                          summary=self.summary_text(data.get("summary")))

        components = []
        for c in self.as_list(data.get("components")):
            if not isinstance(c, dict):
                continue
            name = c.get("name") or self.text_of(c)
            components.append({"layer": c.get("layer", "processing"), "name": name,
                               "purpose": c.get("purpose", ""),
                               "technology": c.get("technology", ""),
                               "satisfies": self.as_list(c.get("satisfies"))})
            out.statements.append(self.statement(
                f"[{c.get('layer', 'component')}] {name}: {c.get('purpose', '')}",
                "AI_INFERENCE", "architecture_component"))

        decisions = []
        for d in self.as_list(data.get("decisions")):
            if not isinstance(d, dict):
                continue
            decisions.append({"decision": d.get("decision", ""),
                              "rationale": d.get("rationale", ""),
                              "alternatives": self.as_list(d.get("alternatives")),
                              "trade_offs": d.get("trade_offs", "")})
            out.statements.append(self.statement(
                f"Architecture decision: {d.get('decision', '')} — {d.get('rationale', '')}",
                "RECOMMENDATION", "architecture_decision"))

        for r in self.as_list(data.get("risks")):
            out.statements.append(self.statement(self.text_of(r), "AI_INFERENCE", "risk"))
        for u in self.as_list(data.get("unknowns")):
            out.statements.append(self.statement(self.text_of(u), "UNKNOWN", "unknown", "LOW"))

        out.artifacts["architecture"] = {
            "platform": platform, "summary": out.summary, "components": components,
            "decisions": decisions,
            "data_flow": [self.text_of(s) for s in self.as_list(data.get("data_flow"))],
            "generation_mode": "ai",
        }
        return out

    def deterministic(self, ctx: Dict[str, Any], reason: str) -> AgentOutput:
        """A reference medallion skeleton, explicitly labelled as a pattern."""
        platform = (ctx.get("platform_decision") or {}).get("recommended_platform", "unspecified")
        skeleton = [
            ("sources", "Source systems", "Systems of record identified during discovery"),
            ("ingestion", "Ingestion layer", "Batch and change-data-capture onboarding"),
            ("storage", "Raw zone (Bronze)", "Immutable, replayable landing of source data"),
            ("processing", "Conformed zone (Silver)", "Validated, deduplicated, conformed entities"),
            ("serving", "Curated zone (Gold)", "Business-ready subject areas and metrics"),
            ("consumption", "Consumption layer", "BI, applications, APIs and AI/ML"),
            ("governance", "Governance layer", "Catalog, lineage, access control and audit"),
            ("operations", "Operations layer", "Orchestration, monitoring and CI/CD"),
        ]
        out = AgentOutput(
            agent=self.id, stage=self.stage,
            generation_mode="deterministic_evidence_only",
            summary=(f"Reference layered architecture for {platform}. AI enrichment was "
                     f"unavailable, so this is a standard pattern rather than a design "
                     f"derived from this customer's specific requirements."),
        )
        components = [{"layer": l, "name": n, "purpose": p, "technology": platform,
                       "satisfies": []} for l, n, p in skeleton]
        for c in components:
            out.statements.append(self.statement(
                f"[{c['layer']}] {c['name']}: {c['purpose']}",
                "RECOMMENDATION", "architecture_component", "LOW"))
        out.statements.append(self.statement(
            "Architecture has not been tailored to the customer's specific "
            "requirements; a design review is required before approval.",
            "UNKNOWN", "unknown", "LOW"))

        out.artifacts["architecture"] = {
            "platform": platform, "summary": out.summary, "components": components,
            "decisions": [], "data_flow": [c["name"] for c in components],
            "generation_mode": "deterministic_evidence_only", "reason": reason[:400],
        }
        return out
