"""Platform decision engine (spec §14).

The spec is explicit that the platform decision must **not** start from a named
product. It must flow:

    requirements -> constraints -> data characteristics -> workloads
    -> security -> cost -> skills -> latency -> governance -> evaluation

So the scoring here is **deterministic and reproducible**: criteria are derived
from evidenced requirements, weighted, and applied to a capability catalogue.
A language model is used only to narrate the result, never to pick the winner —
a recommendation that changes between runs is not defensible to a customer.

Every score returns the signals that produced it, so a reviewer can challenge an
input rather than the conclusion.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# Capability catalogue. Scores are 0..1 capability ratings, not marketing
# claims, and are the platform's published assumptions — reviewable and
# overridable per tenant.
# --------------------------------------------------------------------------
CAPABILITIES: Dict[str, Dict[str, Any]] = {
    "Databricks": {
        "clouds": ["azure", "aws", "gcp"], "deployment": "SaaS / customer VPC",
        "scores": {"data_engineering": 0.96, "lakehouse": 0.97, "streaming": 0.92,
                   "ml_ai": 0.95, "warehouse": 0.82, "bi_native": 0.70,
                   "governance": 0.92, "operational_app": 0.68, "integration": 0.88,
                   "low_latency_serving": 0.62, "cost_efficiency": 0.68,
                   "ease_of_adoption": 0.66, "open_formats": 0.95},
    },
    "Microsoft Fabric": {
        "clouds": ["azure"], "deployment": "SaaS",
        "scores": {"data_engineering": 0.86, "lakehouse": 0.88, "streaming": 0.80,
                   "ml_ai": 0.80, "warehouse": 0.88, "bi_native": 0.97,
                   "governance": 0.88, "operational_app": 0.66, "integration": 0.86,
                   "low_latency_serving": 0.68, "cost_efficiency": 0.76,
                   "ease_of_adoption": 0.86, "open_formats": 0.84},
    },
    "Snowflake": {
        "clouds": ["azure", "aws", "gcp"], "deployment": "SaaS",
        "scores": {"data_engineering": 0.82, "lakehouse": 0.84, "streaming": 0.74,
                   "ml_ai": 0.78, "warehouse": 0.97, "bi_native": 0.82,
                   "governance": 0.93, "operational_app": 0.72, "integration": 0.88,
                   "low_latency_serving": 0.76, "cost_efficiency": 0.72,
                   "ease_of_adoption": 0.90, "open_formats": 0.80},
    },
    "Azure Synapse": {
        "clouds": ["azure"], "deployment": "PaaS",
        "scores": {"data_engineering": 0.78, "lakehouse": 0.74, "streaming": 0.72,
                   "ml_ai": 0.70, "warehouse": 0.86, "bi_native": 0.82,
                   "governance": 0.80, "operational_app": 0.62, "integration": 0.82,
                   "low_latency_serving": 0.66, "cost_efficiency": 0.74,
                   "ease_of_adoption": 0.76, "open_formats": 0.72},
    },
    "BigQuery": {
        "clouds": ["gcp"], "deployment": "SaaS",
        "scores": {"data_engineering": 0.82, "lakehouse": 0.80, "streaming": 0.90,
                   "ml_ai": 0.86, "warehouse": 0.95, "bi_native": 0.86,
                   "governance": 0.88, "operational_app": 0.68, "integration": 0.80,
                   "low_latency_serving": 0.80, "cost_efficiency": 0.80,
                   "ease_of_adoption": 0.88, "open_formats": 0.78},
    },
    "Amazon Redshift": {
        "clouds": ["aws"], "deployment": "PaaS",
        "scores": {"data_engineering": 0.76, "lakehouse": 0.72, "streaming": 0.70,
                   "ml_ai": 0.68, "warehouse": 0.90, "bi_native": 0.74,
                   "governance": 0.80, "operational_app": 0.64, "integration": 0.80,
                   "low_latency_serving": 0.74, "cost_efficiency": 0.78,
                   "ease_of_adoption": 0.80, "open_formats": 0.70},
    },
    "Azure SQL / PostgreSQL": {
        "clouds": ["azure", "aws", "gcp", "on_premises"], "deployment": "PaaS / IaaS",
        "scores": {"data_engineering": 0.52, "lakehouse": 0.30, "streaming": 0.42,
                   "ml_ai": 0.40, "warehouse": 0.66, "bi_native": 0.62,
                   "governance": 0.72, "operational_app": 0.95, "integration": 0.74,
                   "low_latency_serving": 0.95, "cost_efficiency": 0.90,
                   "ease_of_adoption": 0.92, "open_formats": 0.60},
    },
}

#: Signals detected in requirement text -> the criterion each one weights up.
SIGNALS: List[Tuple[str, str, float]] = [
    (r"\b(lakehouse|medallion|bronze|silver|gold|delta|iceberg)\b", "lakehouse", 2.0),
    (r"\b(etl|elt|ingest|pipeline|transform|cdc)\b", "data_engineering", 2.0),
    (r"\b(real[- ]?time|streaming|kafka|event|near[- ]?real)\b", "streaming", 2.0),
    (r"\b(machine learning|ml|ai|model|predict|forecast|genai|llm)\b", "ml_ai", 1.6),
    (r"\b(warehouse|dwh|sql analytics|olap|star schema)\b", "warehouse", 1.6),
    (r"\b(dashboard|report|bi|power bi|tableau|looker|self[- ]service)\b", "bi_native", 1.6),
    (r"\b(governance|lineage|catalog|rbac|masking|classification|steward)\b", "governance", 1.8),
    (r"\b(hipaa|gdpr|pci|sox|phi|pii|compliance|audit|regulat)\b", "governance", 2.0),
    (r"\b(application|operational app|transactional|oltp|crud|workflow)\b", "operational_app", 1.8),
    (r"\b(integrat|api|connector|sap|salesforce|rest|sftp)\b", "integration", 1.4),
    (r"\b(latency|sub[- ]second|millisecond|serving|online)\b", "low_latency_serving", 1.6),
    (r"\b(cost|budget|tco|spend|licen[cs]e|economical)\b", "cost_efficiency", 1.4),
    (r"\b(skills?|team|training|upskill|resource|capability gap)\b", "ease_of_adoption", 1.2),
    (r"\b(open source|open format|vendor lock|portab)\b", "open_formats", 1.4),
]

CLOUD_SIGNALS = {
    "azure": r"\b(azure|microsoft|fabric|synapse|adls|entra|active directory)\b",
    "aws": r"\b(aws|amazon|s3|redshift|glue)\b",
    "gcp": r"\b(gcp|google cloud|bigquery|dataflow)\b",
    "on_premises": r"\b(on[- ]?prem|on premises|data ?cent(er|re))\b",
}

#: Applied when nothing in the evidence speaks to a criterion, so a project with
#: sparse requirements still produces a sane, clearly-labelled baseline.
BASE_WEIGHT = 1.0


@dataclass
class Criterion:
    name: str
    weight: float
    evidence: List[str] = field(default_factory=list)

    @property
    def derived(self) -> bool:
        return bool(self.evidence)

    def to_dict(self) -> dict:
        return {"criterion": self.name, "weight": round(self.weight, 2),
                "derived_from_evidence": self.derived,
                "evidence": self.evidence[:4]}


@dataclass
class PlatformScore:
    platform: str
    fit: float                       # 0..100
    relative: float                  # share of the total
    clouds: List[str]
    cloud_aligned: bool
    strengths: List[str]
    weaknesses: List[str]
    breakdown: List[dict]
    disqualified: bool = False
    disqualified_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def derive_criteria(requirements: List[str], constraints: Optional[List[str]] = None
                    ) -> Tuple[List[Criterion], Dict[str, Any]]:
    """Turn evidenced requirement text into weighted criteria.

    Weights come from the customer's own words. A criterion nobody mentioned
    keeps only the base weight and is flagged as not evidence-derived, so the
    reader can see which parts of the decision rest on assumption.
    """
    corpus = " ".join(requirements + (constraints or [])).lower()
    weights: Dict[str, float] = {c: BASE_WEIGHT for c in
                                 next(iter(CAPABILITIES.values()))["scores"]}
    evidence: Dict[str, List[str]] = {c: [] for c in weights}

    for pattern, criterion, bump in SIGNALS:
        for text in requirements + (constraints or []):
            m = re.search(pattern, text.lower())
            if m:
                weights[criterion] += bump
                if len(evidence[criterion]) < 6:
                    evidence[criterion].append(text[:160])

    cloud_direction = [c for c, pat in CLOUD_SIGNALS.items() if re.search(pat, corpus)]
    criteria = [Criterion(name, weights[name], evidence[name]) for name in weights]
    context = {
        "cloud_direction": cloud_direction,
        "requirements_analysed": len(requirements),
        "criteria_from_evidence": sum(1 for c in criteria if c.derived),
        "criteria_total": len(criteria),
    }
    return criteria, context


def evaluate(requirements: List[str], constraints: Optional[List[str]] = None,
             catalogue: Optional[Dict[str, Dict[str, Any]]] = None,
             excluded: Optional[List[str]] = None) -> Dict[str, Any]:
    """Score every candidate platform. Deterministic and reproducible (§14)."""
    catalogue = catalogue or CAPABILITIES
    excluded = [e.lower() for e in (excluded or [])]
    criteria, context = derive_criteria(requirements, constraints)
    total_weight = sum(c.weight for c in criteria) or 1.0
    cloud_direction = context["cloud_direction"]

    scores: List[PlatformScore] = []
    for name, spec in catalogue.items():
        caps = spec["scores"]
        weighted = sum(caps.get(c.name, 0.5) * c.weight for c in criteria)
        fit = (weighted / total_weight) * 100

        # Cloud alignment is a real constraint, not a tiebreaker: a platform that
        # cannot run in the customer's evidenced cloud is penalised heavily.
        aligned = (not cloud_direction) or bool(set(spec["clouds"]) & set(cloud_direction))
        if cloud_direction and not aligned:
            fit *= 0.72

        breakdown = sorted(
            [{"criterion": c.name, "weight": round(c.weight, 2),
              "capability": caps.get(c.name, 0.5),
              "contribution": round(caps.get(c.name, 0.5) * c.weight, 2),
              "evidence_derived": c.derived}
             for c in criteria],
            key=lambda d: -d["contribution"])

        weighted_criteria = [c for c in criteria if c.derived]
        strengths = [b["criterion"] for b in breakdown
                     if b["capability"] >= 0.85 and b["evidence_derived"]][:4]
        weaknesses = [b["criterion"] for b in breakdown
                      if b["capability"] <= 0.70 and b["evidence_derived"]][:4]

        disqualified = name.lower() in excluded
        scores.append(PlatformScore(
            platform=name, fit=round(fit, 1), relative=0.0,
            clouds=spec["clouds"], cloud_aligned=aligned,
            strengths=strengths or [b["criterion"] for b in breakdown[:2]],
            weaknesses=weaknesses, breakdown=breakdown[:8],
            disqualified=disqualified,
            disqualified_reason="Excluded by customer constraint." if disqualified else "",
        ))

    live = [s for s in scores if not s.disqualified]
    total_fit = sum(s.fit for s in live) or 1.0
    for s in scores:
        s.relative = round((s.fit / total_fit) * 100, 1) if not s.disqualified else 0.0

    ranked = sorted(live, key=lambda s: -s.fit)
    options = _build_options(ranked, criteria, context)

    # Scoring ranks; constraints govern. A customer rule such as "we cannot use
    # AWS" must eliminate an option outright, not merely reweight it — which is
    # all it did while constraints were only corpus text for criterion weights.
    from core import constraints as _constraints
    parsed = _constraints.parse(constraints or [])
    governed = _constraints.apply(
        [s.to_dict() for s in sorted(scores, key=lambda s: -s.fit)],
        parsed, catalogue)

    return {
        "method": "deterministic_weighted_criteria",
        "context": context,
        "criteria": [c.to_dict() for c in sorted(criteria, key=lambda c: -c.weight)],
        "scores": [s.to_dict() for s in sorted(scores, key=lambda s: -s.fit)],
        "governed_decision": governed,
        "options": options,
        "recommendation": options[0] if options else None,
        "decision_status": "RECOMMENDED_PENDING_APPROVAL",
        "note": ("Architecture fit derived from evidenced requirements. This is a "
                 "recommendation for human decision, not a customer commitment (§14)."),
    }


def _build_options(ranked: List[PlatformScore], criteria: List[Criterion],
                   context: Dict[str, Any]) -> List[dict]:
    """Option A / B / C with reasoning, per §14."""
    out: List[dict] = []
    for i, s in enumerate(ranked[:3]):
        label = chr(ord("A") + i)
        gap = round(ranked[0].fit - s.fit, 1)
        out.append({
            "option": f"Option {label}",
            "platform": s.platform,
            "fit": s.fit,
            "relative": s.relative,
            "clouds": s.clouds,
            "recommended": i == 0,
            "gap_to_leader": gap,
            "advantages": _advantages(s, context),
            "disadvantages": _disadvantages(s, context),
            "implementation_complexity": _complexity(s),
            "migration_complexity": _migration(s, context),
            "reasoning": _reasoning(s, criteria, context, i == 0, gap),
        })
    return out


def _advantages(s: PlatformScore, ctx: Dict[str, Any]) -> List[str]:
    adv = []
    if ctx["cloud_direction"] and s.cloud_aligned:
        adv.append(f"Runs in the customer's evidenced cloud direction "
                   f"({', '.join(ctx['cloud_direction'])}).")
    for c in s.strengths:
        adv.append(f"Strong capability for {c.replace('_', ' ')}, which the requirements weight highly.")
    return adv or ["Meets the baseline capability profile."]


def _disadvantages(s: PlatformScore, ctx: Dict[str, Any]) -> List[str]:
    dis = []
    if ctx["cloud_direction"] and not s.cloud_aligned:
        dis.append(f"Does not align with the evidenced cloud direction "
                   f"({', '.join(ctx['cloud_direction'])}); would require a multi-cloud decision.")
    for c in s.weaknesses:
        dis.append(f"Weaker for {c.replace('_', ' ')}, which the requirements weight highly.")
    return dis or ["No material weakness identified against the evidenced criteria."]


def _complexity(s: PlatformScore) -> str:
    ease = next((b["capability"] for b in s.breakdown if b["criterion"] == "ease_of_adoption"), 0.7)
    return "Low" if ease >= 0.85 else "Medium" if ease >= 0.7 else "High"


def _migration(s: PlatformScore, ctx: Dict[str, Any]) -> str:
    if ctx["cloud_direction"] and not s.cloud_aligned:
        return "High — cross-cloud migration and egress must be planned."
    return "Medium — standard source onboarding and historical load."


def _reasoning(s: PlatformScore, criteria: List[Criterion], ctx: Dict[str, Any],
               is_top: bool, gap: float) -> str:
    top = [c for c in sorted(criteria, key=lambda c: -c.weight) if c.derived][:3]
    drivers = ", ".join(c.name.replace("_", " ") for c in top) or "baseline criteria"
    lead = (f"Highest weighted fit at {s.fit}%." if is_top
            else f"{gap} points behind the leading option.")
    evidence_note = (f"{ctx['criteria_from_evidence']} of {ctx['criteria_total']} criteria "
                     f"were derived from {ctx['requirements_analysed']} evidenced requirements; "
                     f"the remainder carry only a baseline weight.")
    return f"{lead} Decision drivers: {drivers}. {evidence_note}"


def apply_decision(evaluation: Dict[str, Any], chosen: str, rationale: str = "",
                   decided_by: str = "") -> Dict[str, Any]:
    """Record a human platform decision over the recommendation (§14, §32).

    A decision that differs from the recommendation is preserved as-is with its
    rationale — the platform advises, the customer decides.
    """
    names = [s["platform"] for s in evaluation.get("scores", [])]
    if chosen not in names:
        raise ValueError(f"'{chosen}' is not a candidate. Options: {', '.join(names)}")
    rec = (evaluation.get("recommendation") or {}).get("platform")
    return {
        **evaluation,
        "decision_status": "DECIDED",
        "selected_platform": chosen,
        "followed_recommendation": chosen == rec,
        "recommended_platform": rec,
        "decision_rationale": rationale or (
            "Selected as recommended." if chosen == rec else
            "Customer selected an alternative to the platform recommendation."),
        "decided_by": decided_by,
    }
