"""Accelerator catalogue (spec §16, §53).

The market this product sits in is a list of point tools: pipeline generators,
migration accelerators, delivery copilots, DevOps governance, consulting
frameworks. Each covers a slice. The claim EliteInteliA makes is that the
slices belong on one governed backbone — so the catalogue is not marketing
copy, it is a map from a named capability to the lifecycle stages that
actually produce it.

Every accelerator therefore declares the stages it drives and the artifacts it
produces. An accelerator that names no stage cannot be offered, which keeps the
catalogue honest as the lifecycle grows.

Applicability is deterministic: it is derived from evidenced signals in the
engagement, never from a model's opinion about which products to sell.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List

from core.domain.lifecycle import STAGE_BY_ID

#: Engine that drives an accelerator. Mirrors the product's core claim:
#: AI reasons, deterministic engines calculate, humans approve.
AI, DETERMINISTIC, HYBRID = "ai", "deterministic", "hybrid"


@dataclass(frozen=True)
class Category:
    id: str
    label: str
    description: str


@dataclass(frozen=True)
class Accelerator:
    id: str
    name: str
    category: str
    summary: str
    stages: List[str]                     # lifecycle stages it drives
    produces: List[str]                   # artifact kinds
    engine: str = HYBRID
    signals: List[str] = field(default_factory=list)   # evidence keywords
    requires: List[str] = field(default_factory=list)  # prerequisite stage ids

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "category": self.category,
                "summary": self.summary, "stages": self.stages,
                "produces": self.produces, "engine": self.engine,
                "signals": self.signals, "requires": self.requires}


CATEGORIES: List[Category] = [
    Category("discovery", "Discovery & Requirements",
             "Turn customer evidence into structured, traceable requirements."),
    Category("migration", "Migration & Re-platforming",
             "Move an existing estate onto a target platform with parity evidence."),
    Category("data_engineering", "Data Engineering",
             "Generate governed ingestion, transformation and data-quality assets."),
    Category("platform", "Platform & Governance",
             "Select, provision and govern the target platform."),
    Category("ai", "AI & Agents",
             "AI use cases, agent design, evaluation and AI governance."),
    Category("bi", "BI & Analytics",
             "Metrics, semantic models and reporting."),
    Category("application", "Application",
             "Personas, journeys, APIs and workflows."),
    Category("delivery", "Delivery & Assurance",
             "Planning, testing, release and operations."),
    Category("devops", "DevOps & Release Governance",
             "CI/CD, environments and gated deployment."),
    Category("commercial", "Commercial & Consulting",
             "RFI/RFP response, estimation, scope control and SOW."),
]

CATALOGUE: List[Accelerator] = [
    # ---------------------------------------------------------- discovery
    Accelerator(
        "rfi_response", "RFI / RFP Response Accelerator", "commercial",
        "Mine requirement trackers, match them to evidenced capability and draft "
        "responses with citations and confidence.",
        stages=["evidence", "discovery", "questions"],
        produces=["discovery", "question_set"], engine=HYBRID,
        signals=["rfi", "rfp", "rfq", "tender", "questionnaire", "compliance sheet"]),
    Accelerator(
        "requirements_traceability", "Requirements Traceability (BRD/FRD/SRD)", "discovery",
        "Project evidenced statements into business, functional and system layers "
        "with a parent chain and an orphan report.",
        stages=["discovery", "requirements"],
        produces=["requirements"], engine=DETERMINISTIC,
        signals=["requirement", "brd", "frd", "srd", "traceability", "user story"]),
    Accelerator(
        "current_state_assessment", "Current-State Assessment", "discovery",
        "Assess architecture, data, applications, security and readiness against "
        "supplied evidence.",
        stages=["assessment"], produces=["assessment"], engine=AI,
        signals=["current state", "as-is", "existing platform", "legacy"]),

    # ---------------------------------------------------------- migration
    Accelerator(
        "etl_migration", "ETL / Platform Migration", "migration",
        "Re-engineer an existing ETL estate onto the target platform with "
        "parallel-validation evidence.",
        stages=["assessment", "architecture", "engineering"],
        produces=["architecture", "engineering"], engine=HYBRID,
        signals=["informatica", "ssis", "datastage", "talend", "migration",
                 "re-platform", "replatform", "fabric", "legacy etl"]),
    Accelerator(
        "warehouse_modernisation", "Warehouse Modernisation", "migration",
        "Move a warehouse or lakehouse workload with schema, logic and "
        "reconciliation coverage.",
        stages=["assessment", "data", "engineering"],
        produces=["data_design", "engineering"], engine=HYBRID,
        signals=["teradata", "netezza", "synapse", "redshift", "oracle",
                 "sql server", "warehouse", "modernisation", "modernization"]),

    # --------------------------------------------------- data engineering
    Accelerator(
        "pipeline_generation", "Pipeline Generation", "data_engineering",
        "Generate metadata-driven ingestion and Bronze/Silver/Gold "
        "transformations with restart and recovery.",
        stages=["data", "engineering"], produces=["engineering"], engine=HYBRID,
        signals=["pipeline", "ingestion", "bronze", "silver", "gold", "medallion",
                 "etl", "elt", "batch", "incremental"]),
    Accelerator(
        "cdc_incremental", "CDC & Incremental Loading", "data_engineering",
        "Watermarking, merge logic and late-arriving data handling.",
        stages=["data", "engineering"], produces=["engineering"], engine=HYBRID,
        signals=["cdc", "change data capture", "incremental", "watermark",
                 "merge", "upsert", "slowly changing"]),
    Accelerator(
        "data_quality", "Data Quality & Reconciliation", "data_engineering",
        "Rule generation, hash checks and reconciliation against a source of record.",
        stages=["data", "testing"], produces=["test_plan"], engine=HYBRID,
        signals=["data quality", "reconciliation", "validation", "hash",
                 "completeness", "accuracy", "dq"]),
    Accelerator(
        "streaming", "Streaming & Near-Real-Time", "data_engineering",
        "Event ingestion, windowing and latency-aware serving.",
        stages=["architecture", "data", "engineering"],
        produces=["architecture", "engineering"], engine=HYBRID,
        signals=["streaming", "real-time", "real time", "kafka", "event hub",
                 "near-real-time", "low latency"]),

    # ----------------------------------------------------------- platform
    Accelerator(
        "platform_selection", "Platform Selection & Constraints", "platform",
        "Score candidate platforms against evidenced criteria, then apply hard "
        "customer constraints to produce a governed decision.",
        stages=["platform"], produces=["platform_decision"], engine=DETERMINISTIC,
        signals=["platform", "databricks", "snowflake", "fabric", "bigquery",
                 "cloud", "target state"]),
    Accelerator(
        "governance_unity", "Governance, Lineage & Access", "platform",
        "Catalog, classification, access model, lineage and retention.",
        stages=["governance"], produces=["governance"], engine=HYBRID,
        signals=["unity catalog", "governance", "lineage", "rbac", "pii",
                 "classification", "retention", "audit"]),
    Accelerator(
        "environment_provisioning", "Environment & Connectivity", "platform",
        "Environment topology, networking, identity and secret handling.",
        stages=["platform", "architecture"], produces=["architecture"], engine=HYBRID,
        signals=["vnet", "private link", "connectivity", "key vault", "identity",
                 "service principal", "environment"]),

    # ----------------------------------------------------------------- ai
    Accelerator(
        "ai_use_cases", "AI Use Case & Agent Design", "ai",
        "Identify AI use cases, design agents and define evaluation and guardrails.",
        stages=["ai"], produces=["ai_design"], engine=AI,
        signals=["ai", "machine learning", "ml", "agent", "llm", "genai",
                 "document intelligence", "rag"]),
    Accelerator(
        "ai_governance", "AI Governance & Evaluation", "ai",
        "Model provenance, evaluation harness, human-in-the-loop and audit.",
        stages=["ai", "governance"], produces=["ai_design", "governance"],
        engine=HYBRID,
        signals=["ai governance", "responsible ai", "evaluation", "human in the loop",
                 "model risk", "hallucination"]),

    # ----------------------------------------------------------------- bi
    Accelerator(
        "semantic_model", "Semantic Model & Metrics", "bi",
        "Metric definitions, semantic model and dashboard specification.",
        stages=["bi"], produces=["bi_design"], engine=HYBRID,
        signals=["power bi", "tableau", "semantic model", "kpi", "metric",
                 "dashboard", "report"]),

    # ---------------------------------------------------------- application
    Accelerator(
        "application_design", "Application & Workflow Design", "application",
        "Personas, journeys, screens, APIs and workflow definition.",
        stages=["application"], produces=["application_design"], engine=AI,
        signals=["application", "workflow", "portal", "api", "user interface",
                 "journey", "persona"]),

    # ------------------------------------------------------------ delivery
    Accelerator(
        "delivery_lifecycle", "Business Analysis → Deployment", "delivery",
        "Drive the full governed lifecycle from analysis through architecture, "
        "engineering, QA and deployment.",
        stages=["discovery", "requirements", "architecture", "engineering",
                "testing", "deployment"],
        produces=["engineering", "test_plan", "deployment_plan"], engine=HYBRID,
        signals=["end to end", "delivery", "programme", "program", "lifecycle"]),
    Accelerator(
        "test_assurance", "Test Strategy & Assurance", "delivery",
        "Test strategy, cases, data-quality gates and acceptance evidence.",
        stages=["testing"], produces=["test_plan"], engine=HYBRID,
        signals=["test", "qa", "uat", "acceptance", "assurance", "parallel run"]),
    Accelerator(
        "operations_handover", "Operations & Handover", "delivery",
        "Runbooks, monitoring, support model and production handover.",
        stages=["operations"], produces=["handover_pack"], engine=HYBRID,
        signals=["runbook", "handover", "support", "monitoring", "hypercare",
                 "operations"]),

    # -------------------------------------------------------------- devops
    Accelerator(
        "cicd_release", "CI/CD & Gated Release", "devops",
        "Pipeline definitions, environment promotion and approval-gated deployment.",
        stages=["deployment"], produces=["deployment_plan"], engine=HYBRID,
        signals=["ci/cd", "cicd", "devops", "release", "pipeline promotion",
                 "terraform", "infrastructure as code", "deployment"]),

    # ----------------------------------------------------------- commercial
    Accelerator(
        "effort_automation", "Effort & Automation Analysis", "commercial",
        "Work breakdown, automation coverage and effort calculated by a "
        "deterministic engine.",
        stages=["estimation"], produces=["estimate"], engine=DETERMINISTIC,
        signals=["effort", "estimate", "sizing", "capacity", "resourcing"]),
    Accelerator(
        "sow_generation", "SOW & Commercial Pack", "commercial",
        "Scope, deliverables, milestones, assumptions and acceptance criteria.",
        stages=["sow", "commercial"], produces=["sow"], engine=DETERMINISTIC,
        signals=["sow", "statement of work", "proposal", "commercial", "pricing",
                 "milestone"]),
    Accelerator(
        "scope_control", "Scope Lock & Change Control", "commercial",
        "Freeze an agreed scope by content hash and raise a change request for "
        "any later drift.",
        stages=["sow", "commercial"], produces=["scope_lock", "change_request"],
        engine=DETERMINISTIC,
        signals=["scope", "change request", "change order", "baseline", "freeze"]),
]

ACCELERATOR_BY_ID = {a.id: a for a in CATALOGUE}
CATEGORY_BY_ID = {c.id: c for c in CATEGORIES}


def validate() -> List[str]:
    """Structural problems in the catalogue, as human-readable strings.

    An accelerator naming a stage that does not exist cannot be delivered, and
    a catalogue that drifts from the lifecycle is worse than none: it promises
    capability the platform does not have.
    """
    problems: List[str] = []
    for a in CATALOGUE:
        if a.category not in CATEGORY_BY_ID:
            problems.append(f"{a.id}: unknown category '{a.category}'")
        if not a.stages:
            problems.append(f"{a.id}: drives no lifecycle stage")
        for stage in a.stages + a.requires:
            if stage not in STAGE_BY_ID:
                problems.append(f"{a.id}: unknown stage '{stage}'")
        if a.engine not in (AI, DETERMINISTIC, HYBRID):
            problems.append(f"{a.id}: unknown engine '{a.engine}'")
    return problems


def catalogue() -> Dict[str, Any]:
    """The full catalogue, grouped by category."""
    return {
        "categories": [
            {**c.__dict__,
             "accelerators": [a.to_dict() for a in CATALOGUE if a.category == c.id]}
            for c in CATEGORIES],
        "count": len(CATALOGUE),
        "engines": {e: sum(1 for a in CATALOGUE if a.engine == e)
                    for e in (AI, DETERMINISTIC, HYBRID)},
    }


def _corpus(texts: Iterable[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(t or "" for t in texts)).lower()


def applicable(texts: List[str], completed_stages: Iterable[str] = ()) -> Dict[str, Any]:
    """Which accelerators this engagement's evidence actually supports.

    Matching is on evidenced signals, so a recommendation can be challenged by
    pointing at the words that produced it. An accelerator with no signal in the
    evidence is reported as available rather than recommended — the difference
    between "your documents call for this" and "we also do this".
    """
    corpus = _corpus(texts)
    done = set(completed_stages or ())

    recommended, available = [], []
    for a in CATALOGUE:
        hits = sorted({s for s in a.signals if s in corpus})
        row = {**a.to_dict(), "matched_signals": hits,
               "stages_complete": sorted(s for s in a.stages if s in done),
               "stages_outstanding": sorted(s for s in a.stages if s not in done)}
        if hits:
            row["reason"] = ("Evidence mentions " +
                             ", ".join(f"'{h}'" for h in hits[:4]) + ".")
            recommended.append(row)
        else:
            available.append(row)

    recommended.sort(key=lambda r: (-len(r["matched_signals"]), r["name"]))
    return {
        "recommended": recommended,
        "available": available,
        "recommended_count": len(recommended),
        "categories_engaged": sorted({r["category"] for r in recommended}),
        "basis": "deterministic: evidenced signal matching against the catalogue",
    }
