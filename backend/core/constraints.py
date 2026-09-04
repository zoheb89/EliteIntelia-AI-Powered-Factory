"""Customer constraints as a first-class decision input (spec §14).

Scoring alone cannot express "we cannot use AWS". Before this module a
constraint only reweighted criteria, so an excluded cloud could still win on
points — the customer's own rule was reduced to a hint.

A constraint is therefore modelled explicitly and applied *after* scoring:

    AI recommendation  ->  deterministic score  ->  customer constraint
                                                        -> governed decision

Parsing is deterministic and every effect names the customer sentence that
caused it, so a rejected option can be defended: "AWS was rejected because the
customer stated 'all workloads must remain on Azure'", not "the model preferred
Azure".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

#: Decision states, strongest first.
PREFERRED, ELIGIBLE, CONDITIONAL, REJECTED = (
    "PREFERRED", "ELIGIBLE", "CONDITIONAL", "REJECTED")

HARD, SOFT = "HARD", "SOFT"

CLOUDS = {
    "aws": ["aws", "amazon web services"],
    "azure": ["azure", "microsoft cloud"],
    "gcp": ["gcp", "google cloud"],
}

#: Products the catalogue can name, so an exclusion can be matched to a row.
PRODUCT_ALIASES = {
    "databricks": ["databricks"],
    "microsoft fabric": ["microsoft fabric", "fabric"],
    "snowflake": ["snowflake"],
    "bigquery": ["bigquery", "big query"],
    "amazon redshift": ["redshift"],
    "azure synapse": ["synapse"],
    "azure sql": ["azure sql"],
}

_PROHIBITION = re.compile(
    r"\b(?:cannot|can't|can not|must not|may not|will not|won'?t|no|not|"
    r"prohibit(?:ed|s)?|forbidden|disallow(?:ed|s)?|exclude[sd]?|ruled out|"
    r"not permitted|not allowed|unacceptable)\b")
_MANDATE = re.compile(
    r"\b(?:must|shall|only|mandat(?:ed|ory)|require[sd]?|restricted to|"
    r"standardis|standardiz|exclusively)\b")
_EXISTING = re.compile(
    r"\b(?:already (?:have|use|own|licen)|existing|incumbent|current(?:ly)? (?:use|run)|"
    r"enterprise (?:agreement|licen)|investment|in place|standard(?:ised|ized)? on)\b")
_RESIDENCY = re.compile(
    r"\b(?:data residency|remain (?:in|within)|stay (?:in|within)|in-?country|"
    r"sovereign|onshore|must reside|hosted (?:in|within)|local region)\b")


@dataclass
class Constraint:
    """One customer-stated rule, with the sentence that established it."""

    kind: str                     # cloud | product | residency | investment
    value: str                    # "aws", "Databricks", "Saudi Arabia"
    severity: str                 # HARD | SOFT
    effect: str                   # exclude | require | prefer | verify
    source: str                   # the customer's own words
    weight: float = 0.0           # points applied for SOFT preferences

    def to_dict(self) -> dict:
        return {"kind": self.kind, "value": self.value, "severity": self.severity,
                "effect": self.effect, "source": self.source[:300],
                "weight": self.weight}


def _sentences(texts: List[str]) -> List[str]:
    out: List[str] = []
    for t in texts or []:
        for s in re.split(r"(?<=[.!?])\s+|\n+", str(t or "")):
            s = s.strip(" -•\t")
            if len(s) >= 8:
                out.append(s)
    return out


def _residency_region(sentence: str) -> str:
    """The place named in a residency rule, e.g. 'Saudi Arabia'."""
    m = re.search(r"(?:remain|stay|reside|hosted|kept)\s+(?:in|within)\s+"
                  r"(?:the\s+)?([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,2})", sentence)
    if m:
        return m.group(1).strip()
    m = re.search(r"\b([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)\s+data residency", sentence)
    return m.group(1).strip() if m else "the stated region"


def parse(texts: List[str]) -> List[Constraint]:
    """Derive structured constraints from customer statements."""
    found: List[Constraint] = []
    seen = set()

    def add(c: Constraint):
        key = (c.kind, c.value.lower(), c.effect)
        if key not in seen:
            seen.add(key)
            found.append(c)

    for sentence in _sentences(texts):
        low = sentence.lower()
        prohibited = bool(_PROHIBITION.search(low))
        mandated = bool(_MANDATE.search(low))
        existing = bool(_EXISTING.search(low))

        for cloud, terms in CLOUDS.items():
            if not any(t in low for t in terms):
                continue
            if prohibited:
                add(Constraint("cloud", cloud, HARD, "exclude", sentence))
            elif mandated:
                add(Constraint("cloud", cloud, HARD, "require", sentence))
            elif existing:
                add(Constraint("cloud", cloud, SOFT, "prefer", sentence, weight=8.0))

        for product, terms in PRODUCT_ALIASES.items():
            if not any(t in low for t in terms):
                continue
            if prohibited:
                add(Constraint("product", product, HARD, "exclude", sentence))
            elif existing:
                # An existing licence is real money already spent; it earns a
                # stated number of points, not an unexplained nudge.
                add(Constraint("product", product, SOFT, "prefer", sentence, weight=15.0))

        if _RESIDENCY.search(low):
            add(Constraint("residency", _residency_region(sentence), HARD,
                           "verify", sentence))

    return found


def apply(scores: List[Dict[str, Any]], constraints: List[Constraint],
          catalogue: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Turn scored candidates into governed decisions.

    `scores` are plain dicts so this stays independent of the scoring engine's
    own dataclass. Each result gains an eligibility state and the trail of
    constraints that produced it.
    """
    catalogue = catalogue or {}
    required_clouds = [c.value for c in constraints
                       if c.kind == "cloud" and c.effect == "require"]
    excluded_clouds = [c.value for c in constraints
                       if c.kind == "cloud" and c.effect == "exclude"]
    excluded_products = [c.value for c in constraints
                         if c.kind == "product" and c.effect == "exclude"]
    residency = [c for c in constraints if c.kind == "residency"]

    out: List[Dict[str, Any]] = []
    for s in scores:
        name = s.get("platform", "")
        clouds = [c.lower() for c in
                  (s.get("clouds") or catalogue.get(name, {}).get("clouds") or [])]
        trail: List[Dict[str, str]] = []
        state = ELIGIBLE
        adjusted = float(s.get("fit", 0.0))

        # Hard rules first: an excluded option cannot be rescued by points.
        for c in constraints:
            if c.effect == "exclude" and c.kind == "product" \
                    and c.value.lower() == name.lower():
                state = REJECTED
                trail.append({"constraint": c.source,
                              "effect": f"{name} is excluded by the customer."})
            if c.effect == "exclude" and c.kind == "cloud" and c.value in clouds \
                    and not (set(clouds) - set(excluded_clouds)):
                state = REJECTED
                trail.append({"constraint": c.source,
                              "effect": f"{name} runs only on {c.value.upper()}, "
                                        f"which the customer has excluded."})

        if state != REJECTED and required_clouds:
            if not set(clouds) & set(required_clouds):
                state = REJECTED
                required = ", ".join(r.upper() for r in required_clouds)
                source = next(c.source for c in constraints
                              if c.kind == "cloud" and c.effect == "require")
                trail.append({"constraint": source,
                              "effect": f"{name} cannot run on {required}."})

        # Soft preferences adjust the score, and say by how much.
        if state != REJECTED:
            for c in constraints:
                if c.effect != "prefer":
                    continue
                matches = (c.kind == "product" and c.value.lower() == name.lower()) \
                    or (c.kind == "cloud" and c.value in clouds)
                if matches:
                    adjusted += c.weight
                    label = name if c.kind == "product" else c.value.upper()
                    trail.append({"constraint": c.source,
                                  "effect": f"+{c.weight:g} for an existing investment "
                                            f"in {label}."})

            if residency:
                state = CONDITIONAL
                for c in residency:
                    trail.append({"constraint": c.source,
                                  "effect": f"Region availability in {c.value} must be "
                                            f"confirmed with the vendor before selection."})

        row = dict(s)
        row.update({"eligibility": state,
                    "constrained_fit": round(adjusted, 1),
                    "constraint_trail": trail})
        out.append(row)

    # The strongest eligible candidate is the preferred one.
    live = [r for r in out if r["eligibility"] in (ELIGIBLE, CONDITIONAL)]
    if live:
        best = max(live, key=lambda r: r["constrained_fit"])
        if best["eligibility"] == ELIGIBLE:
            best["eligibility"] = PREFERRED

    out.sort(key=lambda r: (r["eligibility"] == REJECTED, -r["constrained_fit"]))
    leading = next((r["platform"] for r in out
                    if r["eligibility"] != REJECTED), "")
    return {
        "leading_candidate": leading,
        "constraints": [c.to_dict() for c in constraints],
        "hard_constraints": sum(1 for c in constraints if c.severity == HARD),
        "rejected": [r["platform"] for r in out if r["eligibility"] == REJECTED],
        "candidates": out,
        "basis": "deterministic: customer constraints applied after scoring",
    }
