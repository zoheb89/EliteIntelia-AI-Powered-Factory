"""Customer constraints must govern the decision, not merely tilt it.

Before this layer a constraint was only corpus text feeding criterion weights,
so "we cannot use AWS" could not eliminate an AWS-only platform — it could
still win on points. A rule the customer stated has to be able to remove an
option outright, and the removal has to be explainable.
"""
from core import constraints as K
from core.platform_selection import CAPABILITIES, evaluate


def _scored(**fits):
    return [{"platform": p, "fit": f, "clouds": CAPABILITIES[p]["clouds"]}
            for p, f in fits.items()]


# ----------------------------------------------------------------- parsing
def test_a_prohibition_is_read_as_a_hard_constraint():
    [c] = K.parse(["We cannot use AWS under any circumstances."])
    assert (c.kind, c.value, c.severity, c.effect) == ("cloud", "aws", K.HARD, "exclude")
    assert "cannot use AWS" in c.source


def test_a_mandate_is_read_as_a_hard_requirement():
    cs = K.parse(["All workloads must run on Azure only."])
    assert any(c.kind == "cloud" and c.value == "azure"
               and c.severity == K.HARD and c.effect == "require" for c in cs)


def test_an_existing_investment_is_a_weighted_preference_not_a_rule():
    cs = K.parse(["We already have Microsoft Fabric enterprise licensing."])
    fabric = next(c for c in cs if c.value == "microsoft fabric")
    assert fabric.severity == K.SOFT
    assert fabric.effect == "prefer"
    assert fabric.weight == 15.0


def test_data_residency_is_captured_with_the_region():
    [c] = K.parse(["All data must remain in Saudi Arabia."])
    assert c.kind == "residency"
    assert c.value == "Saudi Arabia"
    assert c.severity == K.HARD


def test_ordinary_prose_produces_no_constraints():
    assert K.parse(["The customer would like faster reporting."]) == []


# ------------------------------------------------------------- elimination
def test_an_excluded_cloud_rejects_a_platform_that_only_runs_there():
    out = K.apply(_scored(**{"Amazon Redshift": 92.0, "Databricks": 70.0}),
                  K.parse(["We cannot use AWS."]), CAPABILITIES)
    by = {r["platform"]: r for r in out["candidates"]}

    # Redshift scored higher and is still rejected: points cannot override a rule.
    assert by["Amazon Redshift"]["eligibility"] == K.REJECTED
    assert by["Databricks"]["eligibility"] != K.REJECTED
    assert "AWS" in by["Amazon Redshift"]["constraint_trail"][0]["effect"]


def test_a_multi_cloud_platform_survives_a_single_cloud_exclusion():
    """Databricks also runs on Azure and GCP, so excluding AWS must not kill it."""
    out = K.apply(_scored(Databricks=88.0), K.parse(["We cannot use AWS."]), CAPABILITIES)
    assert out["candidates"][0]["eligibility"] != K.REJECTED


def test_a_cloud_mandate_rejects_platforms_that_cannot_run_there():
    out = K.apply(_scored(**{"BigQuery": 90.0, "Microsoft Fabric": 60.0}),
                  K.parse(["Everything must run on Azure only."]), CAPABILITIES)
    by = {r["platform"]: r for r in out["candidates"]}

    assert by["BigQuery"]["eligibility"] == K.REJECTED
    assert by["Microsoft Fabric"]["eligibility"] != K.REJECTED


def test_every_rejection_names_the_customer_sentence_that_caused_it():
    out = K.apply(_scored(**{"Amazon Redshift": 90.0}),
                  K.parse(["We cannot use AWS."]), CAPABILITIES)
    trail = out["candidates"][0]["constraint_trail"]

    assert trail, "a rejection with no reason cannot be defended"
    assert "cannot use AWS" in trail[0]["constraint"]


# -------------------------------------------------------------- preference
def test_an_existing_licence_can_change_the_ranking_and_shows_the_points():
    """The customer's own example: Fabric trails on fit but leads once the
    existing licence is counted."""
    out = K.apply(_scored(**{"Databricks": 84.7, "Microsoft Fabric": 83.6}),
                  K.parse(["We already have Microsoft Fabric enterprise licensing."]),
                  CAPABILITIES)

    assert out["leading_candidate"] == "Microsoft Fabric"
    fabric = out["candidates"][0]
    assert fabric["constrained_fit"] == 98.6
    assert "+15" in fabric["constraint_trail"][0]["effect"]


def test_residency_makes_candidates_conditional_rather_than_assumed_available():
    """We hold no region data, so claiming availability would be an invention."""
    out = K.apply(_scored(Databricks=88.0),
                  K.parse(["All data must remain in Saudi Arabia."]), CAPABILITIES)
    row = out["candidates"][0]

    assert row["eligibility"] == K.CONDITIONAL
    assert "Saudi Arabia" in row["constraint_trail"][0]["effect"]


# ------------------------------------------------------------- integration
def test_the_scoring_engine_returns_a_governed_decision():
    ev = evaluate(["Enterprise BI and AI capabilities"],
                  ["We cannot use AWS.",
                   "We already have Microsoft Fabric enterprise licensing."])
    g = ev["governed_decision"]

    assert "Amazon Redshift" in g["rejected"]
    assert g["leading_candidate"] == "Microsoft Fabric"
    assert "deterministic" in g["basis"]


def test_the_governed_decision_is_reproducible():
    args = (["Enterprise BI"], ["We cannot use AWS."])
    assert evaluate(*args)["governed_decision"] == evaluate(*args)["governed_decision"]
