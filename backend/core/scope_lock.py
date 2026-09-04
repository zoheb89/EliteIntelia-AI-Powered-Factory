"""Scope Lock and Change Request (spec §33, §65).

Everything downstream of scope — effort, commercial, SOW, delivery plan — is
priced against a set of requirements that was true at a moment in time. Without
a freeze, a regenerated stage can silently widen what was agreed, and nobody
can answer "what changed after we signed?".

A lock is a content hash over the scope-bearing statements. It proves what was
agreed without trusting anyone's memory of it, and any later difference becomes
a Change Request rather than an invisible edit.

Deterministic throughout: the same scope always produces the same hash, and the
same difference always produces the same change record.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

#: Statement kinds that define commercial scope. A risk or an assumption may
#: inform the price, but it is not the thing being bought.
SCOPE_KINDS = ("requirement", "constraint", "deliverable", "objective")

DRAFT, SUBMITTED, APPROVED, REJECTED = "DRAFT", "SUBMITTED", "APPROVED", "REJECTED"

#: Provenance that cannot be counted as agreed scope.
UNSETTLED = ("UNKNOWN",)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _item(statement: Any) -> Dict[str, str]:
    """The scope-bearing fields of one statement, ignoring volatile metadata."""
    return {
        "ref": str(getattr(statement, "ref", "") or ""),
        "kind": str(getattr(statement, "kind", "") or ""),
        "text": " ".join(str(getattr(statement, "text", "") or "").split()),
        "provenance": str(getattr(statement, "provenance", "") or ""),
    }


def snapshot(statements: List[Any]) -> Dict[str, Any]:
    """A stable, hashable picture of the current scope.

    Ordering is normalised so an unrelated re-run that returns the same
    requirements in a different order does not read as a scope change.
    """
    items = sorted((_item(s) for s in statements
                    if getattr(s, "kind", "") in SCOPE_KINDS),
                   key=lambda i: (i["kind"], i["ref"], i["text"]))
    payload = json.dumps(items, sort_keys=True, separators=(",", ":"))
    return {
        "items": items,
        "count": len(items),
        "hash": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "by_kind": {k: sum(1 for i in items if i["kind"] == k) for k in SCOPE_KINDS},
    }


def readiness(snap: Dict[str, Any], open_questions: int = 0,
              approvals_outstanding: Optional[List[str]] = None) -> Dict[str, Any]:
    """Whether this scope can responsibly be frozen, and what is in the way."""
    blockers: List[str] = []
    if not snap["count"]:
        blockers.append("No scope-bearing statements have been recorded yet.")
    unsettled = [i for i in snap["items"] if i["provenance"] in UNSETTLED]
    if unsettled:
        blockers.append(
            f"{len(unsettled)} scope statements are still UNKNOWN and would be "
            f"frozen as unresolved.")
    if open_questions:
        blockers.append(f"{open_questions} customer questions are unanswered.")
    for stage in (approvals_outstanding or []):
        blockers.append(f"{stage} has not been approved.")
    return {"ready": not blockers, "blockers": blockers,
            "scope_items": snap["count"]}


def lock(snap: Dict[str, Any], locked_by: str, version: int = 1,
         acknowledged_blockers: Optional[List[str]] = None) -> Dict[str, Any]:
    """Freeze a scope. The record is the evidence, so it names who froze it."""
    return {
        "version": version,
        "hash": snap["hash"],
        "locked_at": _now(),
        "locked_by": locked_by,
        "scope_count": snap["count"],
        "by_kind": snap["by_kind"],
        "items": snap["items"],
        "acknowledged_blockers": acknowledged_blockers or [],
        "state": "LOCKED",
    }


def diff(locked: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    """What changed since the lock.

    Matching is by `ref` where present and by text otherwise, so a reworded
    requirement that keeps its reference reads as modified rather than as one
    deletion plus one addition.
    """
    def key(i: Dict[str, str]) -> str:
        return f"ref:{i['ref']}" if i["ref"] else f"txt:{i['text'].lower()}"

    was = {key(i): i for i in locked.get("items", [])}
    now = {key(i): i for i in current.get("items", [])}

    added = [now[k] for k in now.keys() - was.keys()]
    removed = [was[k] for k in was.keys() - now.keys()]
    modified = [{"ref": was[k]["ref"], "from": was[k]["text"], "to": now[k]["text"]}
                for k in was.keys() & now.keys()
                if was[k]["text"] != now[k]["text"]]

    changed = bool(added or removed or modified)
    return {
        "changed": changed,
        "locked_hash": locked.get("hash", ""),
        "current_hash": current.get("hash", ""),
        "added": sorted(added, key=lambda i: (i["kind"], i["ref"], i["text"])),
        "removed": sorted(removed, key=lambda i: (i["kind"], i["ref"], i["text"])),
        "modified": sorted(modified, key=lambda m: (m["ref"], m["from"])),
        "net_change": len(added) - len(removed),
    }


def change_request(delta: Dict[str, Any], raised_by: str, reason: str = "",
                   number: int = 1,
                   effort_per_requirement_days: float = 0.0) -> Dict[str, Any]:
    """Turn a scope difference into a governed change record.

    Effort is extrapolated only when a measured per-requirement rate is
    supplied by the estimation engine. Inventing a number here would put a
    figure in front of a customer that nothing stands behind, so the field
    stays explicitly unassessed instead.
    """
    added, removed = delta.get("added", []), delta.get("removed", [])
    modified = delta.get("modified", [])
    net = len(added) - len(removed)

    if effort_per_requirement_days > 0:
        effort = {"basis": "measured per-requirement rate from the estimate",
                  "days": round(net * effort_per_requirement_days, 1),
                  "assessed": True}
    else:
        effort = {"basis": "no measured rate available; run Effort & Automation "
                           "to quantify",
                  "days": None, "assessed": False}

    impacts = []
    if added:
        impacts.append(f"{len(added)} statements added to scope.")
    if removed:
        impacts.append(f"{len(removed)} statements removed from scope.")
    if modified:
        impacts.append(f"{len(modified)} statements reworded or restated.")

    return {
        "id": f"CR-{number:03d}",
        "state": DRAFT,
        "raised_by": raised_by,
        "raised_at": _now(),
        "reason": reason,
        "against_lock": delta.get("locked_hash", ""),
        "summary": " ".join(impacts) or "No change detected.",
        "added": added,
        "removed": removed,
        "modified": modified,
        "impact": {
            "scope": {"net_statements": net, "assessed": True},
            "effort": effort,
            "cost": {"basis": "follows effort; recalculate commercial after approval",
                     "assessed": False},
            "timeline": {"basis": "depends on approved effort and resourcing",
                         "assessed": False},
        },
        "requires_approval": True,
    }
