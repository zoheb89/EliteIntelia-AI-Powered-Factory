"""BRD / FRD / SRD layering and the traceability chain.

The differentiator is answering "which business objective does this serve, and
who agreed to it?" months later. That only works if the chain is data and if
requirements that trace to nothing are reported rather than quietly attached to
the nearest parent.
"""
from dataclasses import dataclass, field

from core.traceability import build, chain, coverage


@dataclass
class S:
    kind: str
    text: str
    provenance: str = "FACT"
    ref: str = ""
    evidence: list = field(default_factory=lambda: [{"evidence_id": "e1", "locator": "r1"}])


BASE = [
    S("objective", "Reduce manual effort preparing compliance responses to customer RFIs"),
    S("requirement", "Extract structured requirements from unstructured compliance documents"),
    S("requirement", "Responses must be generated within 5 seconds latency at p95"),
    S("constraint", "All data must remain in Saudi Arabia"),
]


# ------------------------------------------------------------- classification
def test_a_domain_noun_does_not_make_a_requirement_non_functional():
    """Matching "compliance" alone put every functional requirement of a
    compliance product into the SRD."""
    layers = build([S("requirement",
                      "Extract structured requirements from compliance documents")])

    assert len(layers["functional"]) == 1
    assert layers["system"] == []


def test_a_measurable_service_quality_is_a_system_requirement():
    layers = build([S("requirement", "Responses must be generated within 5 seconds latency")])

    assert len(layers["system"]) == 1
    assert layers["system"][0]["category"] == "non_functional"
    assert layers["functional"] == []


def test_objectives_seed_the_business_layer():
    layers = build(BASE)
    assert len(layers["business"]) == 1
    assert layers["business"][0]["ref"] == "BR-001"


def test_constraints_land_in_the_system_layer():
    layers = build(BASE)
    assert any("Saudi Arabia" in r["text"] for r in layers["system"])


# -------------------------------------------------------------------- linking
def test_a_requirement_that_serves_an_objective_is_linked_to_it():
    layers = build(BASE)
    fr = layers["functional"][0]
    assert fr["parent_ref"] == "BR-001"


def test_an_unrelated_requirement_is_orphaned_not_mis_attached():
    """A false trace is worse than a missing one: it looks right in the matrix."""
    layers = build(BASE + [S("requirement", "Provide a widget for the cafeteria")])
    orphan = next(r for r in layers["functional"] if "cafeteria" in r["text"])

    assert orphan["parent_ref"] == ""
    assert orphan["ref"] in [o["ref"] for o in coverage(layers)["orphans"]]


def test_shared_evidence_only_links_when_it_singles_a_parent_out():
    """A tracker where every row carries one locator must not attach everything
    to whichever parent happened to be first."""
    same = [{"evidence_id": "e1", "locator": "sheet!row1"}]
    layers = build([
        S("objective", "Alpha objective about invoicing", evidence=same),
        S("objective", "Beta objective about shipping", evidence=same),
        S("requirement", "Wholly unrelated telemetry capture", evidence=same),
    ])
    assert layers["functional"][0]["parent_ref"] == ""


# ------------------------------------------------------------------- coverage
def test_coverage_reports_the_traced_proportion_and_the_orphans():
    cov = coverage(build(BASE + [S("requirement", "Provide a widget for the cafeteria")]))

    assert cov["business_requirements"] == 1
    assert cov["traceable_total"] == cov["functional_requirements"] + cov["system_requirements"]
    assert 0 <= cov["percent"] <= 100
    assert any("cafeteria" in o["text"] for o in cov["orphans"])


def test_unevidenced_requirements_are_surfaced():
    cov = coverage(build([S("requirement", "Something asserted with no source", evidence=[])]))
    assert cov["unevidenced"], "an unevidenced requirement should be flagged"


def test_an_empty_project_reports_zero_rather_than_dividing_by_zero():
    cov = coverage(build([]))
    assert cov["percent"] == 0
    assert cov["orphans"] == []


# ---------------------------------------------------------------------- chain
def test_the_chain_walks_from_a_leaf_up_to_the_business_objective():
    layers = build(BASE)
    traced = [c for c in chain(layers) if c["traced_to_business"]]

    assert traced, "at least one requirement should reach an objective"
    top = traced[0]["chain"][0]
    assert top["layer"] == "BRD"


def test_the_projection_is_reproducible():
    assert build(BASE) == build(BASE)


# ------------------------------------------------------------------- endpoint
def test_the_endpoint_serves_the_three_layers(tmp_path, monkeypatch):
    import importlib
    import os

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'tr.db'}")
    monkeypatch.setenv("LLM_PROVIDERS", "")
    for key in [k for k in os.environ if k.startswith(("ELITEINTELIA_", "CAPGEMINI_"))]:
        monkeypatch.delenv(key, raising=False)

    from persistence import repository as R
    R.reset_engine()
    R.init_db()
    import core.api_v2 as api_v2
    importlib.reload(api_v2)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(api_v2.router)
    c = TestClient(app)

    pid = c.post("/api/v2/projects", json={"name": "P", "intent": "Automate."}).json()["id"]
    for kind, text in (("objective", "Reduce manual compliance effort"),
                       ("requirement", "Extract requirements from compliance documents")):
        c.post(f"/api/v2/projects/{pid}/statements",
               json={"kind": kind, "text": text, "provenance": "FACT",
                     "evidence": [{"evidence_id": "e1", "locator": "r1"}]})

    d = c.get(f"/api/v2/projects/{pid}/traceability").json()
    assert d["layers"]["business"] and d["layers"]["functional"]
    assert "percent" in d["coverage"]
    assert c.get("/api/v2/projects/nope/traceability").status_code == 404
    R.reset_engine()
