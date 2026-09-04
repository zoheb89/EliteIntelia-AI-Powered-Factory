"""Provenance: where every statement in the system came from.

This is the spine of the no-hallucination design (spec §8, §68). Nothing enters
the canonical project model without declaring how it is known. The UI, the
artifact factory and the approval engine all key off these values, so an AI
inference can never be presented as a customer fact.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional


class Provenance(str, Enum):
    """How a statement is known. Ordered from strongest to weakest."""

    CUSTOMER_DECISION = "CUSTOMER_DECISION"   # the customer explicitly decided this
    FACT = "FACT"                             # directly evidenced in a source document
    AI_INFERENCE = "AI_INFERENCE"             # derived by a model from evidence
    RECOMMENDATION = "RECOMMENDATION"         # proposed by the platform, not yet chosen
    ASSUMPTION = "ASSUMPTION"                 # taken as true pending confirmation
    UNKNOWN = "UNKNOWN"                       # explicitly missing; needs customer input

    @property
    def is_evidence_backed(self) -> bool:
        return self in (Provenance.FACT, Provenance.CUSTOMER_DECISION)

    @property
    def requires_confirmation(self) -> bool:
        return self in (Provenance.ASSUMPTION, Provenance.UNKNOWN, Provenance.AI_INFERENCE)


#: Rank used when two sources disagree: higher wins.
PROVENANCE_RANK = {
    Provenance.UNKNOWN: 0,
    Provenance.ASSUMPTION: 1,
    Provenance.RECOMMENDATION: 2,
    Provenance.AI_INFERENCE: 3,
    Provenance.FACT: 4,
    Provenance.CUSTOMER_DECISION: 5,
}


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class EvidenceRef:
    """A pointer back to the source that justifies a statement.

    `locator` is deliberately free-form (page number, sheet + cell, timestamp,
    chunk id) because evidence types differ; it is for humans following an
    audit trail, not for machine addressing.
    """

    evidence_id: str
    locator: str = ""
    excerpt: str = ""

    def to_dict(self) -> dict:
        return {"evidence_id": self.evidence_id, "locator": self.locator, "excerpt": self.excerpt[:500]}


@dataclass
class Statement:
    """Any assertion the platform holds about a project.

    Every requirement, risk, assumption, architecture decision and metric in the
    canonical model carries one of these, so `why do we believe this?` is always
    answerable (spec §30 traceability).
    """

    text: str
    provenance: Provenance = Provenance.AI_INFERENCE
    confidence: Confidence = Confidence.MEDIUM
    evidence: List[EvidenceRef] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str = "system"
    note: str = ""

    def __post_init__(self) -> None:
        # A claim of FACT without a source is exactly the failure mode this
        # class exists to prevent, so it is downgraded rather than trusted.
        if self.provenance is Provenance.FACT and not self.evidence:
            self.provenance = Provenance.AI_INFERENCE
            self.confidence = Confidence.LOW
            self.note = (self.note + " Downgraded: claimed FACT without an evidence reference.").strip()

    @property
    def needs_customer_input(self) -> bool:
        return self.provenance is Provenance.UNKNOWN

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "provenance": self.provenance.value,
            "confidence": self.confidence.value,
            "evidence": [e.to_dict() for e in self.evidence],
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Statement":
        return cls(
            text=d.get("text", ""),
            provenance=Provenance(d.get("provenance", "AI_INFERENCE")),
            confidence=Confidence(d.get("confidence", "MEDIUM")),
            evidence=[EvidenceRef(**e) for e in d.get("evidence", [])],
            created_by=d.get("created_by", "system"),
            note=d.get("note", ""),
        )


def unknown(question: str, note: str = "") -> Statement:
    """Build the canonical 'we do not know this yet' statement (spec §68)."""
    return Statement(
        text=question,
        provenance=Provenance.UNKNOWN,
        confidence=Confidence.LOW,
        note=note or "UNKNOWN — CUSTOMER INPUT REQUIRED",
    )


def reconcile(existing: Statement, incoming: Statement) -> Statement:
    """Pick the statement that should win when a value is re-derived.

    Stronger provenance always wins, so a later AI run can never silently
    overwrite something the customer decided.
    """
    if PROVENANCE_RANK[incoming.provenance] > PROVENANCE_RANK[existing.provenance]:
        return incoming
    if PROVENANCE_RANK[incoming.provenance] < PROVENANCE_RANK[existing.provenance]:
        return existing
    return incoming if incoming.created_at >= existing.created_at else existing
