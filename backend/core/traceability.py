"""BRD / FRD / SRD generation and the traceability chain (spec §11, §33).

A consultancy's real differentiator is not that it wrote a requirements
document — it is being able to answer, months later, "which business objective
does this pipeline serve, and who agreed to it?".

That answer only exists if the chain is built as data:

    Business requirement -> Functional requirement -> System requirement
        -> Solution component -> Test case -> Acceptance criteria

Each document is derived from the layer above it, and every derived row keeps
the `ref` of its parent. Nothing here invents a requirement: the layers are
projections of recorded statements, so an FR always traces to a BR that a
customer actually stated, and an orphan is reported rather than hidden.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

BRD, FRD, SRD = "BRD", "FRD", "SRD"

#: Statement kinds that seed each layer.
BUSINESS_KINDS = ("objective", "outcome", "business_requirement")
FUNCTIONAL_KINDS = ("requirement", "process", "use_case")
SYSTEM_KINDS = ("constraint", "system", "interface", "non_functional")

#: Wording that marks a requirement as non-functional, which belongs in the SRD
#: rather than the FRD.
#:
#: Bare domain words are deliberately absent. Matching "compliance" or
#: "security" on its own reclassified almost every functional requirement of a
#: compliance product as non-functional — the domain noun is not a quality
#: attribute. These are measurable service characteristics instead.
NON_FUNCTIONAL = re.compile(
    r"\b(availability|latency|throughput|scalabilit|scalable|performance|"
    r"retention|encrypt\w*|uptime|rpo|rto|sla|residency|concurren\w*|"
    r"response time|audit trail|disaster recovery|backup|failover|"
    r"data volume|must remain (?:in|within))\b", re.I)


@dataclass
class TraceRow:
    """One requirement at one layer, with the parent it was derived from."""

    ref: str
    text: str
    layer: str
    parent_ref: str = ""
    provenance: str = "AI_INFERENCE"
    evidence: List[dict] = field(default_factory=list)
    category: str = ""

    def to_dict(self) -> dict:
        return {"ref": self.ref, "text": self.text, "layer": self.layer,
                "parent_ref": self.parent_ref, "provenance": self.provenance,
                "evidence": self.evidence, "category": self.category}


def _text(s: Any) -> str:
    return " ".join(str(getattr(s, "text", "") or "").split())


def _evidence(s: Any) -> List[dict]:
    raw = getattr(s, "evidence", None)
    if isinstance(raw, list):
        return raw
    import json
    try:
        return json.loads(getattr(s, "evidence_json", "") or "[]")
    except (ValueError, TypeError):
        return []


def _rows(statements: Iterable[Any], kinds: tuple, layer: str,
          prefix: str) -> List[TraceRow]:
    out: List[TraceRow] = []
    for s in statements:
        if getattr(s, "kind", "") not in kinds:
            continue
        text = _text(s)
        if not text:
            continue
        out.append(TraceRow(
            ref=f"{prefix}-{len(out) + 1:03d}", text=text, layer=layer,
            provenance=str(getattr(s, "provenance", "") or "AI_INFERENCE"),
            evidence=_evidence(s)))
    return out


#: Words too common in delivery prose to indicate a real relationship.
STOPWORDS = {
    "must", "shall", "should", "will", "system", "solution", "platform",
    "provide", "support", "ensure", "enable", "allow", "with", "from", "that",
    "this", "have", "been", "into", "each", "every", "their", "there", "which",
    "when", "where", "customer", "business", "requirement", "requirements",
    "data", "user", "users", "process", "processes", "across", "within",
}


def _tokens(text: str) -> set:
    """Significant words, crudely singularised so plurals still match."""
    words = set()
    for w in re.findall(r"[a-z]{4,}", text.lower()):
        if w in STOPWORDS:
            continue
        words.add(w[:-1] if w.endswith("s") and not w.endswith("ss") else w)
    return words


def _evidence_keys(row: TraceRow) -> set:
    return {f"{e.get('evidence_id', '')}|{e.get('locator', '')}"
            for e in (row.evidence or []) if isinstance(e, dict)}


def _link(child: TraceRow, parents: List[TraceRow]) -> str:
    """Attach a child row to the parent it most plausibly serves.

    Two signals, strongest first: shared evidence — two rows read off the same
    passage are genuinely related — then overlap of distinctive words. A row
    matching nothing is left orphaned on purpose: a false trace is worse than a
    missing one because it looks correct in the matrix.
    """
    if not parents:
        return ""

    # Shared evidence only tells us something when it singles a parent out.
    # A tracker where every row carries the same locator would otherwise
    # attach every child to whichever parent happened to be first.
    words = _tokens(child.text)
    if not words:
        return ""

    # Shared evidence only tells us something when it singles a parent out and
    # the two rows actually discuss the same thing. A locator collision — one
    # tracker row cited by everything — is not a relationship.
    child_ev = _evidence_keys(child)
    if child_ev:
        sharing = [p for p in parents
                   if (child_ev & _evidence_keys(p)) and (words & _tokens(p.text))]
        if len(sharing) == 1:
            return sharing[0].ref
    best, best_score = "", 0.0
    for p in parents:
        shared = words & _tokens(p.text)
        if not shared:
            continue
        # Normalise so a long parent does not win purely on length.
        score = len(shared) / (len(words) ** 0.5)
        if score > best_score:
            best, best_score = p.ref, score
    return best if best_score >= 0.4 else ""


def build(statements: List[Any]) -> Dict[str, Any]:
    """Project recorded statements into the three requirement layers."""
    business = _rows(statements, BUSINESS_KINDS, BRD, "BR")

    functional: List[TraceRow] = []
    system: List[TraceRow] = []
    for s in statements:
        if getattr(s, "kind", "") not in FUNCTIONAL_KINDS:
            continue
        text = _text(s)
        if not text:
            continue
        # A requirement about latency or retention is a system requirement even
        # when it was captured as a plain requirement.
        is_system = bool(NON_FUNCTIONAL.search(text))
        target, prefix, layer = ((system, "SR", SRD) if is_system
                                 else (functional, "FR", FRD))
        target.append(TraceRow(
            ref=f"{prefix}-{len(target) + 1:03d}", text=text, layer=layer,
            provenance=str(getattr(s, "provenance", "") or "AI_INFERENCE"),
            evidence=_evidence(s),
            category="non_functional" if is_system else "functional"))

    for s in statements:
        if getattr(s, "kind", "") in SYSTEM_KINDS and _text(s):
            system.append(TraceRow(
                ref=f"SR-{len(system) + 1:03d}", text=_text(s), layer=SRD,
                provenance=str(getattr(s, "provenance", "") or "AI_INFERENCE"),
                evidence=_evidence(s), category=str(getattr(s, "kind", ""))))

    for fr in functional:
        fr.parent_ref = _link(fr, business)
    for sr in system:
        sr.parent_ref = _link(sr, functional) or _link(sr, business)

    return {"business": [r.to_dict() for r in business],
            "functional": [r.to_dict() for r in functional],
            "system": [r.to_dict() for r in system]}


def chain(layers: Dict[str, Any]) -> List[dict]:
    """The full parent chain for every leaf requirement."""
    by_ref = {r["ref"]: r for group in layers.values() for r in group}
    out = []
    for row in layers.get("system", []) + layers.get("functional", []):
        path, cursor, guard = [], row, 0
        while cursor and guard < 6:
            path.append({"ref": cursor["ref"], "layer": cursor["layer"],
                         "text": cursor["text"][:160]})
            cursor = by_ref.get(cursor.get("parent_ref", ""))
            guard += 1
        out.append({"ref": row["ref"], "depth": len(path),
                    "chain": list(reversed(path)),
                    "traced_to_business": path[-1]["layer"] == BRD if path else False})
    return out


def coverage(layers: Dict[str, Any]) -> Dict[str, Any]:
    """How much of the requirement set actually traces, and what does not.

    Orphans are the point of the report: an untraceable requirement is one
    nobody can justify to the customer, and it is cheaper to find here than in
    an acceptance workshop.
    """
    functional = layers.get("functional", [])
    system = layers.get("system", [])
    linked = [r for r in functional + system if r.get("parent_ref")]
    total = len(functional) + len(system)

    orphans = [{"ref": r["ref"], "layer": r["layer"], "text": r["text"][:200]}
               for r in functional + system if not r.get("parent_ref")]
    unevidenced = [{"ref": r["ref"], "text": r["text"][:200]}
                   for r in layers.get("business", []) + functional + system
                   if not r.get("evidence")]

    return {
        "business_requirements": len(layers.get("business", [])),
        "functional_requirements": len(functional),
        "system_requirements": len(system),
        "traced": len(linked),
        "traceable_total": total,
        "percent": round(100 * len(linked) / total) if total else 0,
        "orphans": orphans,
        "unevidenced": unevidenced,
        "basis": "deterministic: derived from recorded statements and their evidence",
    }
