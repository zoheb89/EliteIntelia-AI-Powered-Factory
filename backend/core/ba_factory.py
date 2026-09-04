"""Business Analysis artifact factory.

Builds BRD -> FRD -> SRD from the canonical project model without inventing
customer facts. The requirements artifact is the source of truth; every row
keeps its requirement reference and evidence/provenance where available.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List


def _text(value: Any) -> str:
    return str(value or "").strip()


def _rows(requirements: Iterable[dict]) -> List[dict]:
    out: List[dict] = []
    for i, r in enumerate(requirements or [], 1):
        text = _text(r.get("text"))
        if not text:
            continue
        out.append({
            "ref": _text(r.get("ref")) or f"R-{i}",
            "text": text,
            "category": _text(r.get("category")) or "functional",
            "priority": _text(r.get("priority")) or "should",
            "acceptance": _text(r.get("acceptance")),
            "provenance": _text(r.get("provenance")) or "AI_INFERENCE",
            "evidence": r.get("evidence") or [],
        })
    return out


def build(project: dict, discovery: dict | None, requirements: dict | None,
          assessment: dict | None = None) -> Dict[str, Any]:
    """Create reviewable BRD/FRD/SRD layers from persisted evidence."""
    reqs = _rows((requirements or {}).get("requirements", []))
    d = discovery or {}
    a = assessment or {}

    objectives = [str(x) for x in (d.get("objectives") or []) if _text(x)]
    processes = [str(x) for x in (d.get("processes") or []) if _text(x)]
    actors = [str(x) for x in (d.get("actors") or []) if _text(x)]
    systems = [str(x) for x in (d.get("systems") or []) if _text(x)]
    constraints = [str(x) for x in (d.get("constraints") or []) if _text(x)]
    unknowns = [str(x) for x in (d.get("unknowns") or []) if _text(x)]

    brd = {
        "title": f"Business Requirements Document — {project.get('name') or 'Engagement'}",
        "version": 1,
        "status": "DRAFT",
        "business_intent": _text(project.get("intent")),
        "domain": _text(project.get("domain")) or "UNSPECIFIED",
        "objectives": objectives,
        "stakeholders": actors,
        "business_processes": processes,
        "scope": {
            "in_scope": [r["ref"] for r in reqs],
            "out_of_scope": [],
            "unresolved": unknowns,
        },
        "business_requirements": [
            {k: r[k] for k in ("ref", "text", "category", "priority", "provenance", "evidence")}
            for r in reqs
        ],
        "constraints": constraints,
        "success_measures": [],
        "open_questions": unknowns,
        "evidence_note": "No business fact is added unless present in the canonical model.",
    }

    functional = [r for r in reqs if r["category"] in {"functional", "integration", "data"}]
    nfr = [r for r in reqs if r["category"] in {"non_functional", "security", "compliance"}]
    frd = {
        "title": f"Functional Requirements Document — {project.get('name') or 'Engagement'}",
        "version": 1,
        "status": "DRAFT",
        "functional_requirements": [
            {**{k: r[k] for k in ("ref", "text", "category", "priority", "acceptance")},
             "source_brd_ref": r["ref"]}
            for r in functional
        ],
        "non_functional_requirements": [
            {**{k: r[k] for k in ("ref", "text", "category", "priority", "acceptance")},
             "source_brd_ref": r["ref"]}
            for r in nfr
        ],
        "integrations": systems,
        "acceptance_criteria": [
            {"ref": r["ref"], "criteria": r["acceptance"]}
            for r in reqs if r["acceptance"]
        ],
        "unresolved": [r["ref"] for r in reqs if not r["acceptance"]],
    }

    srd = {
        "title": f"System Requirements Document — {project.get('name') or 'Engagement'}",
        "version": 1,
        "status": "DRAFT",
        "system_requirements": [
            {
                "ref": f"SRD-{i}",
                "source_requirement": r["ref"],
                "requirement": r["text"],
                "category": r["category"],
                "priority": r["priority"],
                "acceptance": r["acceptance"],
                "implementation_status": "TO_BE_DESIGNED",
            }
            for i, r in enumerate(reqs, 1)
        ],
        "source_systems": systems,
        "target_system": "TO_BE_DESIGNED",
        "interfaces": [],
        "security": [r["text"] for r in nfr if r["category"] == "security"],
        "compliance": [r["text"] for r in nfr if r["category"] == "compliance"],
        "performance": [r["text"] for r in nfr if r["category"] == "non_functional"],
        "architecture_dependency": bool(a),
        "open_questions": unknowns,
    }

    trace = []
    for r in reqs:
        trace.append({
            "brd_ref": r["ref"],
            "frd_refs": [r["ref"]] if r in functional or r in nfr else [],
            "srd_refs": [f"SRD-{i}"],
            "evidence": r["evidence"],
            "provenance": r["provenance"],
        })

    completeness = {
        "requirements": len(reqs),
        "with_acceptance": sum(1 for r in reqs if r["acceptance"]),
        "open_questions": len(unknowns),
        "ready_for_human_review": bool(reqs) and not unknowns,
    }
    return {
        "factory": "business_analysis",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "project_id": project.get("id"),
            "project_version": project.get("version", 1),
            "requirements_count": len(reqs),
            "generation_rule": "canonical_evidence_only",
        },
        "brd": brd,
        "frd": frd,
        "srd": srd,
        "traceability": trace,
        "completeness": completeness,
    }
