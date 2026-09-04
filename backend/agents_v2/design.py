"""Design agents for the delivery stages (spec §17-§22).

These share one shape — consume upstream artifacts, emit a structured design
plus provenance-tagged statements — so `DesignAgent` carries the behaviour and
each concrete agent only declares what makes it different.

Each agent's deterministic fallback emits a *checklist of what must be
established*, never a fabricated design. An invented data model or governance
control is worse than an admitted gap.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from agents_v2.base import AgentOutput, BaseAgent


class DesignAgent(BaseAgent):
    """Shared behaviour for evidence-consuming design stages."""

    #: Upstream artifact kinds to load into the prompt.
    consumes: List[str] = []
    #: Artifact kind this agent emits.
    produces: str = ""
    #: JSON keys expected back, mapped to the statement kind they become.
    sections: Dict[str, str] = {}
    #: Questions used when the model is unavailable.
    fallback_questions: List[str] = []
    role: str = "Design Agent"
    focus: str = ""

    def gather(self) -> Dict[str, Any]:
        ctx: Dict[str, Any] = {
            "project": self.tools.invoke("project_summary"),
            "requirements": [s["text"] for s in
                             self.tools.invoke("list_statements", kind="requirement")],
        }
        for kind in self.consumes:
            try:
                ctx[kind] = self.tools.invoke("read_artifact", kind=kind)["content"]
            except KeyError:
                ctx[kind] = None
        return ctx

    def system_prompt(self) -> str:
        return (
            f"You are the {self.role}. {self.focus} Work only from the upstream "
            "artifacts and requirements supplied. Anything the evidence does not "
            "establish must be returned in `unknowns` as a specific question, never "
            "filled in with a plausible default."
        )

    def user_prompt(self, ctx: Dict[str, Any]) -> str:
        upstream = {k: ctx.get(k) for k in self.consumes if ctx.get(k)}
        keys = ", ".join(f'"{k}": []' for k in self.sections)
        return (
            f"PROJECT: {json.dumps(ctx['project'])}\n\n"
            f"REQUIREMENTS:\n{json.dumps(ctx['requirements'][:25], indent=1)[:2500]}\n\n"
            f"UPSTREAM ARTIFACTS:\n{json.dumps(upstream, indent=1)[:4000]}\n\n"
            f"Return JSON: {{\"summary\": \"...\", {keys}, \"unknowns\": []}}. "
            "Each array element is an object with at least a \"text\" field; include "
            "\"provenance\" where you can justify it."
        )

    def parse(self, data: Any, ctx: Dict[str, Any]) -> AgentOutput:
        if not isinstance(data, dict):
            return self.deterministic(ctx, "Model returned a non-object response.")
        out = AgentOutput(agent=self.id, stage=self.stage,
                          summary=self.summary_text(data.get("summary")))
        payload: Dict[str, Any] = {"summary": out.summary, "generation_mode": "ai"}

        for key, kind in self.sections.items():
            items = self.as_list(data.get(key))
            payload[key] = [self.text_of(i) for i in items]
            for item in items:
                text = self.text_of(item)
                if not text.strip():
                    continue
                prov = (item.get("provenance") if isinstance(item, dict) else None) or "AI_INFERENCE"
                out.statements.append(self.statement(
                    text, prov, kind,
                    evidence=(item.get("evidence") if isinstance(item, dict) else None)))

        unknowns = [self.text_of(u) for u in self.as_list(data.get("unknowns"))]
        payload["unknowns"] = unknowns
        for u in unknowns:
            out.statements.append(self.statement(u, "UNKNOWN", "unknown", "LOW"))

        out.artifacts[self.produces] = payload
        return out

    def deterministic(self, ctx: Dict[str, Any], reason: str) -> AgentOutput:
        out = AgentOutput(
            agent=self.id, stage=self.stage,
            generation_mode="deterministic_evidence_only",
            summary=(f"{self.role} could not enrich this stage. The items below are "
                     f"what must be established with the customer, not a design."),
        )
        for q in self.fallback_questions:
            out.statements.append(self.statement(q, "UNKNOWN", "unknown", "LOW"))
        out.artifacts[self.produces] = {
            "summary": out.summary,
            **{k: [] for k in self.sections},
            "unknowns": list(self.fallback_questions),
            "generation_mode": "deterministic_evidence_only",
            "reason": reason[:400],
        }
        return out


class DataDesignAgent(DesignAgent):
    """Sources, mappings, models, medallion design, quality rules (§17)."""

    id, stage, produces = "data", "data", "data_design"
    consumes = ["architecture", "discovery"]
    role = "Data Design Agent"
    focus = ("Design the data layer: source inventory, source-to-target mapping, "
             "entities, medallion layers, quality rules and lineage.")
    sections = {"sources": "source", "entities": "data_entity",
                "mappings": "mapping", "quality_rules": "data_quality_rule",
                "medallion": "data_layer"}
    fallback_questions = [
        "What are the source systems, their owners and their data volumes?",
        "Which entities are in scope for the first release?",
        "What are the record counts and growth rates per source?",
        "What data quality rules must be enforced before Gold?",
        "What is the required data retention and archival policy?",
    ]

    def parse(self, data: Any, ctx: Dict[str, Any]) -> AgentOutput:
        out = super().parse(data, ctx)
        # Metadata is emitted separately so the engineering stage can consume it.
        payload = out.artifacts.get(self.produces, {})
        out.artifacts["metadata"] = {
            "entities": payload.get("entities", []),
            "mappings": payload.get("mappings", []),
            "quality_rules": payload.get("quality_rules", []),
            "generation_mode": payload.get("generation_mode", "ai"),
        }
        return out


class AIDesignAgent(DesignAgent):
    """AI/ML use cases, patterns, evaluation and governance (§18)."""

    id, stage, produces = "ai", "ai", "ai_design"
    consumes = ["architecture", "discovery"]
    role = "AI Design Agent"
    focus = ("Identify AI and ML use cases that the evidence actually supports, with "
             "the pattern, data dependency and evaluation approach for each.")
    sections = {"use_cases": "ai_use_case", "patterns": "ai_pattern",
                "evaluation": "ai_evaluation", "governance": "ai_governance"}
    fallback_questions = [
        "Which business decisions would benefit from prediction or automation?",
        "What historical data exists to train on, and over what period?",
        "What accuracy or business threshold makes a model worth deploying?",
        "Who is accountable for model decisions and their review?",
    ]


class BIDesignAgent(DesignAgent):
    """Metrics, semantic model, dashboards (§19)."""

    id, stage, produces = "bi", "bi", "bi_design"
    consumes = ["data_design", "discovery"]
    role = "BI Design Agent"
    focus = ("Define business metrics, the semantic model (facts, dimensions, "
             "measures) and the reports that answer the stated business questions.")
    sections = {"metrics": "metric", "dimensions": "dimension",
                "facts": "fact", "reports": "report"}
    fallback_questions = [
        "What are the top business questions each report must answer?",
        "How is each KPI defined and calculated, and who owns that definition?",
        "Which BI tool is the customer standard?",
        "What row-level security applies to reporting users?",
    ]


class ApplicationDesignAgent(DesignAgent):
    """Personas, journeys, screens, APIs, workflows (§20)."""

    id, stage, produces = "application", "application", "application_design"
    consumes = ["architecture", "discovery"]
    role = "Application Design Agent"
    focus = ("Design the operational application: personas, user journeys, screens, "
             "APIs, data model, roles and workflows.")
    sections = {"personas": "persona", "journeys": "user_journey",
                "screens": "application", "apis": "api_endpoint",
                "workflows": "workflow", "roles": "application_role"}
    fallback_questions = [
        "Who are the application's users and what is each one trying to accomplish?",
        "Which operational workflows must the application support at go-live?",
        "What systems must the application integrate with?",
        "What are the authentication and authorisation requirements?",
    ]


class GovernanceAgent(DesignAgent):
    """Classification, PII/PHI, access model, lineage, compliance (§21)."""

    id, stage, produces = "governance", "governance", "governance"
    consumes = ["data_design", "architecture", "assessment"]
    role = "Governance Agent"
    focus = ("Define data classification, PII/PHI handling, the access model, "
             "masking, retention, lineage and the compliance checklist.")
    sections = {"classification": "data_classification",
                "access_controls": "security_requirement",
                "compliance": "compliance_requirement",
                "retention": "retention_policy", "lineage": "lineage_requirement"}
    fallback_questions = [
        "Which regulatory regimes apply (HIPAA, GDPR, PCI, local law)?",
        "Which fields contain personal or health information?",
        "What is the access model, and who approves access requests?",
        "What are the retention and deletion obligations per data domain?",
    ]


class EngineeringAgent(DesignAgent):
    """Work packages, pipelines, transformations, tests, deployment (§17)."""

    id, stage, produces = "engineering", "engineering", "engineering_plan"
    consumes = ["data_design", "metadata", "architecture"]
    role = "Engineering Agent"
    focus = ("Produce the engineering plan: work packages, pipelines, "
             "transformations, orchestration, tests and the deployment approach.")
    sections = {"work_packages": "work_package", "pipelines": "pipeline",
                "transformations": "transformation", "orchestration": "orchestration",
                "tests": "test_case"}
    fallback_questions = [
        "What are the environment topology and promotion path?",
        "What orchestration and scheduling standards apply?",
        "What is the expected batch window or streaming SLA?",
    ]

    def parse(self, data: Any, ctx: Dict[str, Any]) -> AgentOutput:
        out = super().parse(data, ctx)
        payload = out.artifacts.get(self.produces, {})
        out.artifacts["work_packages"] = {
            "packages": payload.get("work_packages", []),
            "generation_mode": payload.get("generation_mode", "ai"),
        }
        return out


class QAAgent(DesignAgent):
    """Test strategy, cases, quality gates, acceptance evidence."""

    id, stage, produces = "qa", "testing", "test_plan"
    consumes = ["engineering_plan", "data_design"]
    role = "QA Agent"
    focus = ("Define the test strategy: unit, integration, data quality, "
             "reconciliation, performance and user acceptance testing.")
    sections = {"strategy": "test_strategy", "test_cases": "test_case",
                "quality_gates": "quality_gate",
                "acceptance_criteria": "acceptance_criterion"}
    fallback_questions = [
        "What defines acceptance for each deliverable?",
        "What reconciliation tolerance is acceptable between source and target?",
        "Who signs off user acceptance testing?",
    ]


class OperationsAgent(DesignAgent):
    """Deployment plan, runbooks, monitoring, handover."""

    id, stage, produces = "operations", "deployment", "deployment_plan"
    consumes = ["engineering_plan", "test_plan", "architecture"]
    role = "Operations Agent"
    focus = ("Plan deployment and operations: environments, promotion, rollback, "
             "monitoring, alerting, runbooks and the support model.")
    sections = {"environments": "environment", "deployment_steps": "deployment_step",
                "monitoring": "monitoring_requirement", "runbooks": "runbook",
                "rollback": "rollback_step"}
    fallback_questions = [
        "What is the target go-live date and acceptable cutover window?",
        "Who operates the platform after handover?",
        "What are the availability and recovery objectives (RTO/RPO)?",
    ]


class HandoverAgent(DesignAgent):
    """Production handover and run operations."""

    id, stage, produces = "operations_handover", "operations", "handover"
    consumes = ["deployment_plan", "test_plan"]
    role = "Handover Agent"
    focus = ("Produce the handover pack: documentation, runbooks, support model, "
             "known issues and the ongoing operating rhythm.")
    sections = {"documentation": "handover_document", "support_model": "support_model",
                "known_issues": "known_issue", "training": "training_requirement"}
    fallback_questions = [
        "Which team assumes ongoing ownership?",
        "What hypercare period has been agreed?",
        "What training does the receiving team require?",
    ]
