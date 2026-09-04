"""Next Best Action — what should happen next on this engagement, and why.

A menu-driven lifecycle makes the operator work out which of twenty stages is
runnable, what is blocking the rest, and who has to act. This module answers
that from recorded state alone.

It is deliberately deterministic. A recommendation that changes between two
identical runs cannot be defended to a customer, and the one place a model must
never improvise is the instruction telling a delivery team what to do next.
Evidence and gates decide; the model is not consulted (spec §8, §68).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from core.domain.lifecycle import (STAGES, STAGE_BY_ID, Approval, LifecycleState,
                                   StageStatus)

#: Provenance values that count as established rather than proposed.
EVIDENCED = {"FACT", "CUSTOMER_DECISION"}

#: Who owns each kind of action. Roles mirror the delivery organisation so the
#: recommendation names a person's job, not a button.
OWNER_BY_HANDLER = {
    "intake": "Business Analyst",
    "evidence": "Business Analyst",
    "discovery": "Business Analyst",
    "questions": "Business Analyst",
    "assessment": "Solution Architect",
    "requirements": "Business Analyst",
    "platform": "Solution Architect",
    "platform_selection": "Solution Architect",
    "architecture": "Solution Architect",
    "data": "Data Engineer",
    "ai": "AI Engineer",
    "bi": "BI Developer",
    "application": "Application Architect",
    "engineering": "Data Engineer",
    "testing": "QA Engineer",
    "qa": "QA Engineer",
    "estimate": "Delivery Manager",
    "estimation": "Delivery Manager",
    "sow": "Delivery Manager",
    "commercial": "Delivery Manager",
    "governance": "Governance Lead",
    "deployment": "DevOps Engineer",
    "operations": "Delivery Manager",
    "operations_handover": "Delivery Manager",
}


@dataclass
class Action:
    """One recommended step, with the reason it is being recommended."""

    id: str
    title: str
    why: str
    owner: str
    kind: str                      # collect_evidence | run_stage | approve | answer_questions
    stage_id: str = ""
    priority: int = 50             # lower runs first
    automatable: bool = False      # can the platform do it, or must a person?
    blocked_by: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "why": self.why,
                "owner": self.owner, "kind": self.kind, "stage_id": self.stage_id,
                "automatable": self.automatable, "blocked_by": self.blocked_by}


def _owner_for(stage_id: str) -> str:
    stage = STAGE_BY_ID.get(stage_id)
    return OWNER_BY_HANDLER.get(getattr(stage, "agent", ""), "Delivery Manager")


def engagement_state(state: LifecycleState, evidence_count: int) -> str:
    """A short label for where the engagement actually is."""
    done, total = state.progress
    if not evidence_count and done <= 1:
        return "AWAITING EVIDENCE"
    if state.pending_approval():
        return "AWAITING APPROVAL"
    if done == 0:
        return "INTAKE"
    if done >= total:
        return "COMPLETE"
    for s in STAGES:
        if state.is_complete(s.id):
            latest = s
    return f"{latest.group} IN PROGRESS"


def evidence_completeness(statements: List[Any]) -> Dict[str, Any]:
    """How much of what we hold is established rather than assumed.

    Deliberately a ratio of recorded statements, not a model's opinion of
    confidence: an invented percentage is worse than none at all.
    """
    considered = [s for s in statements
                  if getattr(s, "kind", "") not in ("source",)]
    if not considered:
        return {"percent": 0, "evidenced": 0, "open_questions": 0, "total": 0}

    evidenced = sum(1 for s in considered
                    if (getattr(s, "provenance", "") or "") in EVIDENCED)
    open_questions = sum(1 for s in considered
                         if (getattr(s, "provenance", "") or "") == "UNKNOWN")
    return {"percent": round(100 * evidenced / len(considered)),
            "evidenced": evidenced,
            "open_questions": open_questions,
            "total": len(considered)}


def recommend(state: LifecycleState, statements: List[Any],
              evidence_count: int, limit: int = 6) -> Dict[str, Any]:
    """Rank what should happen next on this engagement."""
    actions: List[Action] = []
    completeness = evidence_completeness(statements)

    # 1. Nothing can be derived from an empty room.
    if not evidence_count:
        actions.append(Action(
            id="collect-evidence",
            title="Upload the customer's RFI, RFP, SOW or notes",
            why="No evidence has been supplied, so every downstream stage would "
                "be inference rather than fact.",
            owner="Business Analyst", kind="collect_evidence", priority=0))

    # 2. An approval gate stops more work than anything else, so it outranks
    #    new generation: running further stages only deepens unapproved work.
    pending = state.pending_approval()
    if pending:
        blocked = [s.label for s in STAGES
                   if pending.id in s.requires and not state.is_complete(s.id)]
        actions.append(Action(
            id=f"approve-{pending.id}",
            title=f"Review and approve {pending.label}",
            why=(f"{pending.label} is complete but needs "
                 f"{pending.approval.value.lower()} approval"
                 + (f", which is holding up {', '.join(blocked[:3])}." if blocked else ".")),
            owner=_owner_for(pending.id), kind="approve",
            stage_id=pending.id, priority=5))

    # 3. Unanswered customer questions are the usual reason evidence stalls.
    if completeness["open_questions"]:
        actions.append(Action(
            id="answer-open-questions",
            title=(f"Get customer answers to {completeness['open_questions']} open "
                   f"question{'' if completeness['open_questions'] == 1 else 's'}"),
            why="These are recorded as UNKNOWN, so anything built on them is an "
                "assumption that will not survive scope lock.",
            owner="Business Analyst", kind="answer_questions", priority=20))

    # 4. The next stage that can actually run.
    nxt = state.next_stage()
    if nxt:
        actions.append(Action(
            id=f"run-{nxt.id}",
            title=f"Run {nxt.label}",
            why=nxt.description or f"{nxt.label} is the next stage whose inputs are satisfied.",
            owner=_owner_for(nxt.id), kind="run_stage", stage_id=nxt.id,
            priority=10, automatable=True))

    # 5. Name what is blocked and what would release it, rather than leaving
    #    the operator to infer it from greyed-out buttons.
    for s in STAGES:
        if state.is_complete(s.id):
            continue
        reasons = state.blockers(s.id)
        if reasons and s is not nxt:
            actions.append(Action(
                id=f"blocked-{s.id}", title=f"{s.label} is blocked",
                why=" ".join(reasons), owner=_owner_for(s.id), kind="blocked",
                stage_id=s.id, priority=80, blocked_by=reasons))
            if len([a for a in actions if a.kind == "blocked"]) >= 3:
                break

    actions.sort(key=lambda a: a.priority)
    done, total = state.progress
    return {
        "state": engagement_state(state, evidence_count),
        "progress": {"complete": done, "total": total},
        "evidence": {"documents": evidence_count, **completeness},
        "primary": actions[0].to_dict() if actions else None,
        "actions": [a.to_dict() for a in actions[:limit]],
        "basis": "deterministic: lifecycle gates, approvals and recorded provenance",
    }
