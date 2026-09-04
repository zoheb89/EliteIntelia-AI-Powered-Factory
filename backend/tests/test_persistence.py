"""Persistence: tenant isolation, versioning, traceability and audit."""
import os
import tempfile

import pytest


@pytest.fixture()
def repos():
    """Two tenants on one fresh database, to prove isolation is real."""
    from persistence import repository as R

    path = os.path.join(tempfile.mkdtemp(), "t.db")
    os.environ["DATABASE_URL"] = f"sqlite:///{path}"
    R.reset_engine()
    R.init_db()

    with R.session_scope() as s:
        a = R.Repository.ensure_tenant(s, "acme", "Acme")
        b = R.Repository.ensure_tenant(s, "globex", "Globex")
        yield R.Repository(s, a.id, "alice@acme"), R.Repository(s, b.id, "bob@globex"), R
    os.environ.pop("DATABASE_URL", None)
    R.reset_engine()


# ------------------------------------------------------------ tenancy §58
def test_project_is_scoped_to_its_tenant(repos):
    acme, globex, _ = repos
    p = acme.create_project("Acme Platform", intent="modernize")
    assert acme.get_project(p.id).name == "Acme Platform"
    assert globex.list_projects() == []


def test_cross_tenant_access_raises(repos):
    acme, globex, R = repos
    p = acme.create_project("Acme Secret")
    with pytest.raises(R.TenantScopeError):
        globex.get_project(p.id)


def test_repository_requires_a_tenant(repos):
    _, _, R = repos
    with R.session_scope() as s:
        with pytest.raises(R.TenantScopeError):
            R.Repository(s, "")


def test_evidence_is_tenant_scoped(repos):
    acme, globex, R = repos
    p = acme.create_project("P")
    acme.add_evidence(p.id, name="rfp.pdf", sha256="abc")
    assert len(acme.list_evidence(p.id)) == 1
    with pytest.raises(R.TenantScopeError):
        globex.list_evidence(p.id)


# ---------------------------------------------------------- versioning §65
def test_artifacts_version_instead_of_overwriting(repos):
    acme, _, _ = repos
    p = acme.create_project("P")
    v1 = acme.save_artifact(p.id, "discovery", '{"v":1}')
    v2 = acme.save_artifact(p.id, "discovery", '{"v":2}')

    assert v1.version == 1 and v2.version == 2
    assert acme.latest_artifact(p.id, "discovery").content == '{"v":2}'
    assert v1.superseded_by == v2.id
    assert len(acme.list_artifacts(p.id, include_superseded=True)) == 2
    assert len(acme.list_artifacts(p.id)) == 1


def test_artifact_records_the_project_version_it_came_from(repos):
    acme, _, _ = repos
    p = acme.create_project("P")
    acme.snapshot_project(p.id, {"state": "after discovery"}, reason="discovery complete")
    a = acme.save_artifact(p.id, "assessment", "{}")
    assert a.project_version == 2, "artifact must pin the canonical version"


def test_project_snapshot_bumps_version(repos):
    acme, _, _ = repos
    p = acme.create_project("P")
    assert p.version == 1
    pv = acme.snapshot_project(p.id, {"x": 1}, reason="test")
    assert pv.version == 2 and acme.get_project(p.id).version == 2


# ------------------------------------------------------- statements §8/§64
def test_statements_carry_provenance(repos):
    acme, _, _ = repos
    p = acme.create_project("P")
    acme.add_statement(p.id, "requirement", "Near-real-time refresh",
                       provenance="CUSTOMER_DECISION", ref="R-1")
    acme.add_statement(p.id, "unknown", "Data volumes unknown", provenance="UNKNOWN")

    reqs = acme.list_statements(p.id, kind="requirement")
    assert len(reqs) == 1 and reqs[0].provenance == "CUSTOMER_DECISION"
    assert len(acme.list_statements(p.id)) == 2


def test_superseded_statements_are_hidden(repos):
    acme, _, _ = repos
    p = acme.create_project("P")
    old = acme.add_statement(p.id, "requirement", "Daily batch")
    new = acme.add_statement(p.id, "requirement", "Near-real-time")
    acme.supersede_statement(old.id, new.id)
    remaining = acme.list_statements(p.id, kind="requirement")
    assert [s.text for s in remaining] == ["Near-real-time"]


# ------------------------------------------------------- traceability §30
def test_trace_walks_upstream_to_the_original_requirement(repos):
    acme, _, _ = repos
    p = acme.create_project("P")
    acme.link(p.id, "requirement", "R-1", "usecase", "U-1")
    acme.link(p.id, "usecase", "U-1", "architecture", "A-1")
    acme.link(p.id, "architecture", "A-1", "workitem", "W-1")

    chain = acme.trace_upstream(p.id, "W-1")
    assert {l.from_id for l in chain} == {"R-1", "U-1", "A-1"}


# ------------------------------------------------------------- audit §59
def test_audit_is_written_for_mutations(repos):
    acme, _, _ = repos
    p = acme.create_project("Audited")
    acme.save_artifact(p.id, "sow", "{}")
    actions = {e.action for e in acme.list_audit()}
    assert "project.created" in actions and "artifact.created" in actions


def test_audit_records_the_actor(repos):
    acme, _, _ = repos
    acme.create_project("P")
    assert acme.list_audit()[0].actor == "alice@acme"


def test_approval_state_is_appended_not_overwritten(repos):
    acme, _, _ = repos
    p = acme.create_project("P")
    assert acme.approval_state(p.id, "stage", "architecture") == "DRAFT"
    acme.approve(p.id, "stage", "architecture", "UNDER_REVIEW")
    acme.approve(p.id, "stage", "architecture", "APPROVED", comment="looks good")
    assert acme.approval_state(p.id, "stage", "architecture") == "APPROVED"


def test_agent_runs_are_recorded_for_the_run_centre(repos):
    acme, _, _ = repos
    p = acme.create_project("P")
    acme.record_run(p.id, "discovery", provider="acme-gw", model="m1",
                    prompt_tokens=100, completion_tokens=50, duration_ms=1200)
    runs = acme.list_runs(p.id)
    assert len(runs) == 1 and runs[0].provider == "acme-gw"
    assert runs[0].project_version == 1
