"""Metadata-driven architecture presentation and platform-fit scoring.

This module contains no Streamlit state and no customer-specific platform choice.
It converts persisted Discovery/Assessment/Blueprint evidence into presentation
metadata used by the UI. The platform catalog supplies the capability metadata;
the scoring engine is generic and deterministic.
"""
from __future__ import annotations

import re
import math
from typing import Any, Dict, Iterable, List

from .platforms import PLATFORM_CATALOG, SUPPORTED_PLATFORMS, normalize_platform


def _text(values: Any) -> str:
    if values is None:
        return ""
    if isinstance(values, dict):
        values = list(values.values())
    if isinstance(values, (list, tuple, set)):
        return " ".join(_text(v) for v in values)
    return str(values)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _contains(text: str, phrases: Iterable[str]) -> bool:
    low = text.lower()
    return any(p.lower() in low for p in phrases)


def _evidence_text(discovery: Dict[str, Any], assessment: Dict[str, Any], blueprint: Dict[str, Any]) -> str:
    parts: List[Any] = []
    for obj in (discovery, assessment, blueprint):
        if not isinstance(obj, dict):
            continue
        for key in (
            "summary", "domain", "objectives", "processes", "systems", "sources",
            "requirements", "assumptions", "unknowns", "target_architecture",
            "data_flow", "security_governance", "environments", "delivery_phases",
            "decisions", "open_questions",
        ):
            if key in obj:
                parts.append(obj[key])
    return _text(parts)


def _cloud_hint(discovery: Dict[str, Any], assessment: Dict[str, Any], blueprint: Dict[str, Any]) -> str:
    text = _evidence_text(discovery, assessment, blueprint).lower()
    for cloud in ("Azure", "AWS", "GCP", "Google Cloud", "on-premises", "on premise"):
        if cloud.lower() in text:
            return "On-premises" if cloud.lower().startswith("on") else ("GCP" if cloud == "Google Cloud" else cloud)
    return ""


def platform_fit(discovery: Dict[str, Any] | None = None,
                 assessment: Dict[str, Any] | None = None,
                 blueprint: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    """Return relative platform recommendation scores from evidence + catalog metadata.

    The output is a normalized fit distribution, not a prediction of customer
    behavior. It is intended to show why a platform is a stronger architectural
    candidate. The final customer decision remains explicit and human.
    """
    discovery = discovery or {}
    assessment = assessment or {}
    blueprint = blueprint or {}
    text = _evidence_text(discovery, assessment, blueprint)
    tokens = _tokens(text)
    cloud_hint = _cloud_hint(discovery, assessment, blueprint)

    weights = {
        "cloud_fit": 0.22,
        "workload_fit": 0.24,
        "data_platform_fit": 0.18,
        "governance_fit": 0.14,
        "integration_fit": 0.10,
        "analytics_ai_fit": 0.12,
    }

    def score(meta: Dict[str, Any]) -> tuple[float, Dict[str, float], List[str]]:
        profile = meta.get("fit_profile", {})
        reasons: List[str] = []
        components: Dict[str, float] = {}

        supported_clouds = set(meta.get("clouds", []))
        cloud = 1.0 if not cloud_hint else (1.0 if cloud_hint in supported_clouds else 0.45)
        components["cloud_fit"] = cloud
        if cloud_hint and cloud_hint in supported_clouds:
            reasons.append(f"Fits the evidenced {cloud_hint} cloud direction")
        elif cloud_hint:
            reasons.append(f"Cloud alignment is weaker for the evidenced {cloud_hint} direction")

        workload = 0.45
        if _contains(text, ("data engineering", "etl", "pipeline", "ingestion", "medallion", "bronze", "silver", "gold", "lakehouse")):
            workload = max(workload, float(profile.get("data_engineering", workload)))
            reasons.append("Strong fit for the stated data-engineering workload")
        if _contains(text, ("operational app", "application", "api", "transactional")):
            workload = max(workload, float(profile.get("application", workload)))
            reasons.append("Can support the operational-consumption requirement")
        components["workload_fit"] = workload

        data_platform = 0.5
        if _contains(text, ("medallion", "bronze", "silver", "gold", "data lake", "lakehouse")):
            data_platform = float(profile.get("lakehouse", data_platform))
        elif _contains(text, ("warehouse", "sql analytics")):
            data_platform = float(profile.get("warehouse", data_platform))
        components["data_platform_fit"] = data_platform

        governance = float(profile.get("governance", 0.55))
        if _contains(text, ("governance", "lineage", "rbac", "row level", "privacy", "compliance", "phi", "pii", "audit")):
            governance = min(1.0, governance + 0.12)
            reasons.append("Governance/compliance requirements are explicitly weighted")
        components["governance_fit"] = governance

        integration = float(profile.get("integration", 0.55))
        if _contains(text, ("sql server", "on-prem", "on premises", "vpn", "expressroute", "private endpoint", "cdc", "api")):
            integration = min(1.0, integration + 0.08)
        components["integration_fit"] = integration

        analytics = float(profile.get("analytics_ai", 0.55))
        if _contains(text, ("bi", "power bi", "ai", "ml", "machine learning", "self-service", "reporting", "genie")):
            analytics = min(1.0, analytics + 0.10)
            reasons.append("Matches the analytics / AI / BI direction")
        components["analytics_ai_fit"] = analytics

        raw = sum(weights[k] * components[k] for k in weights)
        return raw, components, list(dict.fromkeys(reasons))[:4]

    rows = []
    for name in SUPPORTED_PLATFORMS:
        meta = PLATFORM_CATALOG[name]
        raw, components, reasons = score(meta)
        rows.append({
            "platform": name,
            "platform_type": meta.get("type", "Unknown"),
            "clouds": list(meta.get("clouds", [])),
            "raw_score": raw,
            "components": components,
            "reasons": reasons,
        })
    rows.sort(key=lambda r: r["raw_score"], reverse=True)
    # A softmax converts small fit differences into an intuitive comparison signal.
    # This is deliberately labelled a heuristic: it is not a forecast of customer behavior.
    temperature = 0.07
    exps = [math.exp((r["raw_score"] - rows[0]["raw_score"]) / temperature) for r in rows]
    exp_total = sum(exps) or 1.0
    for rank, (row, exp_value) in enumerate(zip(rows, exps), 1):
        row["rank"] = rank
        row["fit_score"] = round(row["raw_score"] * 100, 1)
        row["relative_share"] = round((row["raw_score"] / sum(max(0.001, x["raw_score"]) for x in rows)) * 100, 1)
        row["selection_likelihood"] = round((exp_value / exp_total) * 100, 1)
        row["recommendation"] = "Strong candidate" if rank == 1 else ("Viable alternative" if rank <= 3 else "Lower fit for current evidence")
    return rows


def selected_platform_evaluation(rows: List[Dict[str, Any]], selected: str) -> Dict[str, Any]:
    selected = normalize_platform(selected)
    for row in rows:
        if row["platform"] == selected:
            return row
    return {}


def architecture_model(discovery: Dict[str, Any] | None,
                       blueprint: Dict[str, Any] | None,
                       selected_platform: str = "") -> Dict[str, Any]:
    discovery = discovery or {}
    blueprint = blueprint or {}
    systems = discovery.get("systems") or []
    sources = discovery.get("sources") or []
    target = normalize_platform(selected_platform or blueprint.get("target_platform") or "") or "Target data platform"
    cloud = _cloud_hint(discovery, {}, blueprint) or "Target cloud / hosting"

    source_label = "On-premises HMS / source systems"
    if systems:
        source_label = " + ".join(str(x).replace("_", " ").title() for x in systems[:2])
    source_detail = "SQL Server / enterprise sources"
    if sources:
        source_detail = ", ".join(str(x).replace("_", " ").title() for x in sources[:3])

    return {
        "source": {"title": source_label, "detail": source_detail},
        "connectivity": {"title": "Secure connectivity", "detail": "VPN / ExpressRoute / private connectivity as approved"},
        "ingestion": {"title": "Ingestion & orchestration", "detail": "Batch / CDC / streaming pattern selected from SLA and source evidence"},
        "bronze": {"title": "Bronze", "detail": "Raw, auditable, replayable source-aligned data"},
        "silver": {"title": "Silver", "detail": "Validated, conformed and quality-controlled entities"},
        "gold": {"title": "Gold", "detail": "Business-ready subject areas, KPIs and semantic data products"},
        "consumption": {"title": "Consumption", "detail": "BI · operational applications · AI/ML · APIs / governed shares"},
        "platform": {"title": target, "detail": f"{cloud} · target compute / data platform"},
        "cross_cutting": [
            "Identity & access", "Catalog / lineage", "Data quality", "Audit & observability", "CI/CD & policy gates", "Backup / recovery",
        ],
    }
