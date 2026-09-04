"""Delivery lifecycle definition (spec §2) and the gates between stages.

The lifecycle is data, not control flow. Agents, the UI and the artifact factory
all read this module, so adding a stage does not mean editing branching logic in
several places.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class Approval(str, Enum):
    NONE = "NONE"            # advances automatically once produced
    HUMAN = "HUMAN"          # a person must approve before downstream runs
    CUSTOMER = "CUSTOMER"    # the customer must sign off (portal, spec §51)


class StageStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True)
class Stage:
    id: str
    label: str
    group: str                       # navigation grouping (spec §75)
    agent: str                       # agent id that produces this stage
    produces: List[str]              # artifact kinds emitted
    requires: List[str] = field(default_factory=list)   # upstream stage ids
    approval: Approval = Approval.NONE
    description: str = ""


# Ordered delivery lifecycle. `requires` encodes the gates, so the engine can
# compute readiness without a hand-maintained state machine.
STAGES: List[Stage] = [
    Stage("intent", "Business Intent", "DISCOVERY", "intake",
          ["intent"], [], Approval.NONE,
          "Capture what the customer wants to build, in their words."),
    Stage("evidence", "Evidence", "DISCOVERY", "evidence",
          ["evidence_index"], ["intent"], Approval.NONE,
          "Ingest and classify RFI/RFP/RFQ, documents, notes and schemas."),
    Stage("discovery", "Discovery", "DISCOVERY", "discovery",
          ["discovery"], ["evidence"], Approval.NONE,
          "Derive objectives, processes, actors, systems, requirements and unknowns."),
    Stage("questions", "Open Questions", "DISCOVERY", "questions",
          ["question_set"], ["discovery"], Approval.NONE,
          "Turn every UNKNOWN into a targeted customer question."),
    Stage("assessment", "Current-State Assessment", "ASSESS", "assessment",
          ["assessment"], ["discovery"], Approval.NONE,
          "Assess architecture, data, applications, security, governance and readiness."),
    Stage("requirements", "Requirements", "ASSESS", "requirements",
          ["requirements"], ["discovery"], Approval.HUMAN,
          "Structured functional, non-functional, security and compliance requirements."),
    Stage("platform", "Platform Selection", "ARCHITECT", "platform_selection",
          ["platform_options", "platform_decision"], ["requirements", "assessment"], Approval.HUMAN,
          "Evaluate candidate platforms against evidenced requirements and recommend one."),
    Stage("architecture", "Architecture", "ARCHITECT", "architecture",
          ["architecture"], ["platform"], Approval.HUMAN,
          "Target architecture, components, decisions and trade-offs."),
    Stage("data", "Data Design", "DATA", "data",
          ["data_design", "metadata"], ["architecture"], Approval.NONE,
          "Sources, mappings, models, medallion design and data quality rules."),
    Stage("ai", "AI & ML Design", "AI", "ai",
          ["ai_design"], ["architecture"], Approval.NONE,
          "AI/ML use cases, patterns, evaluation and AI governance."),
    Stage("bi", "BI & Semantic Model", "BI", "bi",
          ["bi_design"], ["data"], Approval.NONE,
          "Metrics, semantic model, dashboards and reporting requirements."),
    Stage("application", "Application Design", "APPLICATION", "application",
          ["application_design"], ["architecture"], Approval.NONE,
          "Personas, journeys, screens, APIs, data model and workflows."),
    Stage("governance", "Governance", "GOVERNANCE", "governance",
          ["governance"], ["architecture"], Approval.NONE,
          "Classification, PII/PHI, access model, lineage, retention and compliance."),
    Stage("engineering", "Engineering Plan", "ENGINEERING", "engineering",
          ["engineering_plan", "work_packages"], ["data"], Approval.NONE,
          "Work packages, pipelines, transformations, tests and deployment plan."),
    Stage("estimation", "Effort & Automation", "COMMERCIAL", "estimation",
          ["estimate", "automation_assessment"], ["engineering"], Approval.NONE,
          "Effort, automation coverage, roles, timeline and critical path."),
    Stage("sow", "Statement of Work", "COMMERCIAL", "commercial",
          ["sow"], ["estimation"], Approval.HUMAN,
          "Scope, deliverables, milestones, assumptions and acceptance criteria."),
    Stage("commercial", "Commercial", "COMMERCIAL", "commercial",
          ["commercial"], ["sow"], Approval.HUMAN,
          "Pricing inputs, rates, contingency and risk. Never auto-committed."),
    Stage("testing", "Testing", "ENGINEERING", "qa",
          ["test_plan"], ["engineering"], Approval.NONE,
          "Test strategy, cases, data quality gates and acceptance evidence."),
    Stage("deployment", "Deployment", "OPERATIONS", "operations",
          ["deployment_plan"], ["testing", "commercial"], Approval.HUMAN,
          "Deployment plan, environment checks and rollback strategy."),
    Stage("operations", "Operations & Handover", "OPERATIONS", "operations_handover",
          ["handover"], ["deployment"], Approval.NONE,
          "Runbooks, monitoring, support model and production handover."),
]

STAGE_BY_ID: Dict[str, Stage] = {s.id: s for s in STAGES}
STAGE_ORDER: List[str] = [s.id for s in STAGES]

#: Navigation groups in the order the UI should present them (spec §75).
GROUPS = ["DISCOVERY", "ASSESS", "ARCHITECT", "DATA", "AI", "BI",
          "APPLICATION", "ENGINEERING", "COMMERCIAL", "GOVERNANCE", "OPERATIONS"]


def stages_in_group(group: str) -> List[Stage]:
    return [s for s in STAGES if s.group == group]


def downstream_of(stage_id: str) -> List[str]:
    """Every stage that transitively depends on `stage_id` (spec §31)."""
    out: List[str] = []
    frontier = {stage_id}
    for s in STAGES:
        if set(s.requires) & frontier:
            out.append(s.id)
            frontier.add(s.id)
    return out


@dataclass
class LifecycleState:
    """Per-project stage status, plus the approvals recorded against them."""

    statuses: Dict[str, StageStatus] = field(default_factory=dict)
    approvals: Dict[str, bool] = field(default_factory=dict)

    def status(self, stage_id: str) -> StageStatus:
        return self.statuses.get(stage_id, StageStatus.PENDING)

    def is_complete(self, stage_id: str) -> bool:
        return self.status(stage_id) is StageStatus.COMPLETE

    def blockers(self, stage_id: str) -> List[str]:
        """Human-readable reasons `stage_id` cannot run yet."""
        stage = STAGE_BY_ID.get(stage_id)
        if not stage:
            return [f"Unknown stage: {stage_id}"]
        reasons: List[str] = []
        for req in stage.requires:
            upstream = STAGE_BY_ID[req]
            if not self.is_complete(req):
                reasons.append(f"{upstream.label} must be complete first.")
            elif upstream.approval is not Approval.NONE and not self.approvals.get(req):
                reasons.append(f"{upstream.label} is awaiting {upstream.approval.value.lower()} approval.")
        return reasons

    def can_run(self, stage_id: str) -> bool:
        return not self.blockers(stage_id)

    def next_stage(self) -> Optional[Stage]:
        """The single next runnable stage, or None when blocked or finished."""
        for s in STAGES:
            if not self.is_complete(s.id) and self.can_run(s.id):
                return s
        return None

    def pending_approval(self) -> Optional[Stage]:
        for s in STAGES:
            if (self.is_complete(s.id) and s.approval is not Approval.NONE
                    and not self.approvals.get(s.id)):
                return s
        return None

    @property
    def progress(self) -> tuple[int, int]:
        return sum(1 for s in STAGES if self.is_complete(s.id)), len(STAGES)
