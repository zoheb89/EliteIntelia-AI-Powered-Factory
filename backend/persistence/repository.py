"""Database session management and tenant-scoped repositories (spec §40, §58).

Tenant isolation is enforced structurally: a repository is constructed *for* a
tenant, and every query it issues filters on that tenant. Callers cannot forget
the filter because they never write the filter.

`DATABASE_URL` selects the backend. SQLite is used for local development and
the free tier; PostgreSQL for production. No engine-specific SQL is used.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from persistence.models import (
    AgentRun, Artifact, ApprovalRecord, AuditEvent, Base, Decision, Evidence,
    EvidenceChunk, JobRecord, LLMProviderConfig, PlatformConnection, Project,
    ProjectStatement, ProjectVersion, Tenant, TraceLink, User,
)


def database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        # SQLAlchemy 2.x needs the psycopg/psycopg2 dialect, not the bare scheme.
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg2://", 1)
        return url
    path = os.getenv("CINVENT_DB_PATH", "data/cinvent.db")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    return f"sqlite:///{path}"


_engine = None
_Session: Optional[sessionmaker] = None


def get_engine():
    global _engine, _Session
    if _engine is None:
        url = database_url()
        kwargs: Dict[str, Any] = {"future": True, "pool_pre_ping": True}
        if url.startswith("sqlite"):
            # check_same_thread=False so background job threads can use the session.
            kwargs["connect_args"] = {"check_same_thread": False}
        else:
            kwargs.update(pool_size=5, max_overflow=10)
        _engine = create_engine(url, **kwargs)

        if url.startswith("sqlite"):
            @event.listens_for(_engine, "connect")
            def _sqlite_pragmas(dbapi_conn, _rec):  # noqa: ANN001
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                cur.execute("PRAGMA journal_mode=WAL")   # concurrent reads during writes
                cur.close()

        _Session = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def init_db() -> None:
    """Create tables. Alembic owns migrations; this is for dev and tests."""
    Base.metadata.create_all(get_engine())


def reset_engine() -> None:
    """Drop cached engine so tests can point at a different database."""
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine, _Session = None, None


@contextmanager
def session_scope() -> Iterator[Session]:
    get_engine()
    assert _Session is not None
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TenantScopeError(PermissionError):
    """Raised when a record is accessed from outside its tenant."""


class Repository:
    """All data access for one tenant. Constructed per request.

    Every method filters on `tenant_id`; cross-tenant reads raise rather than
    returning None, so a bug surfaces loudly instead of leaking silently.
    """

    def __init__(self, session: Session, tenant_id: str, actor: str = "system"):
        if not tenant_id:
            raise TenantScopeError("A tenant_id is required for all data access.")
        self.s = session
        self.tenant_id = tenant_id
        self.actor = actor

    # ------------------------------------------------------------- tenants
    @staticmethod
    def ensure_tenant(session: Session, slug: str, name: str = "") -> Tenant:
        t = session.scalar(select(Tenant).where(Tenant.slug == slug))
        if not t:
            t = Tenant(slug=slug, name=name or slug.title())
            session.add(t)
            session.flush()
        return t

    # ------------------------------------------------------------ projects
    def create_project(self, name: str, intent: str = "", domain: str = "",
                       customer: str = "") -> Project:
        p = Project(tenant_id=self.tenant_id, name=name, intent=intent,
                    domain=domain, customer=customer, created_by=self.actor)
        self.s.add(p)
        self.s.flush()
        self.audit("project.created", "project", p.id, after={"name": name}, project_id=p.id)
        return p

    def get_project(self, project_id: str) -> Optional[Project]:
        p = self.s.get(Project, project_id)
        if p is None:
            return None
        if p.tenant_id != self.tenant_id:
            raise TenantScopeError("Project belongs to a different tenant.")
        return p

    def list_projects(self) -> List[Project]:
        return list(self.s.scalars(
            select(Project).where(Project.tenant_id == self.tenant_id)
            .order_by(Project.updated_at.desc())))

    def snapshot_project(self, project_id: str, snapshot: dict, reason: str = "") -> ProjectVersion:
        """Bump the canonical version and store an immutable snapshot (§65)."""
        p = self.get_project(project_id)
        if not p:
            raise KeyError("Project not found")
        p.version = (p.version or 1) + 1
        pv = ProjectVersion(tenant_id=self.tenant_id, project_id=project_id,
                            version=p.version, snapshot_json=json.dumps(snapshot, default=str),
                            reason=reason, created_by=self.actor)
        self.s.add(pv)
        self.s.flush()
        return pv

    # ------------------------------------------------------------ evidence
    def add_evidence(self, project_id: str, **kw) -> Evidence:
        self._assert_project(project_id)
        e = Evidence(tenant_id=self.tenant_id, project_id=project_id, **kw)
        self.s.add(e)
        self.s.flush()
        self.audit("evidence.added", "evidence", e.id, after={"name": e.name}, project_id=project_id)
        return e

    def list_evidence(self, project_id: str) -> List[Evidence]:
        self._assert_project(project_id)
        return list(self.s.scalars(
            select(Evidence).where(Evidence.tenant_id == self.tenant_id,
                                   Evidence.project_id == project_id)
            .order_by(Evidence.created_at)))

    def find_evidence_by_hash(self, project_id: str, sha256: str) -> Optional[Evidence]:
        return self.s.scalar(select(Evidence).where(
            Evidence.tenant_id == self.tenant_id, Evidence.project_id == project_id,
            Evidence.sha256 == sha256))

    def add_chunks(self, evidence_id: str, project_id: str, chunks: List[dict]) -> int:
        for i, c in enumerate(chunks):
            self.s.add(EvidenceChunk(tenant_id=self.tenant_id, evidence_id=evidence_id,
                                     project_id=project_id, ordinal=i,
                                     locator=c.get("locator", ""), text=c.get("text", "")))
        self.s.flush()
        return len(chunks)

    # ---------------------------------------------------------- statements
    def add_statement(self, project_id: str, kind: str, text: str,
                      provenance: str = "AI_INFERENCE", confidence: str = "MEDIUM",
                      evidence: Optional[list] = None, stage: str = "",
                      ref: str = "") -> ProjectStatement:
        self._assert_project(project_id)
        st = ProjectStatement(
            tenant_id=self.tenant_id, project_id=project_id, kind=kind, text=text,
            provenance=provenance, confidence=confidence, stage=stage, ref=ref,
            evidence_json=json.dumps(evidence or []), created_by=self.actor)
        self.s.add(st)
        self.s.flush()
        return st

    def list_statements(self, project_id: str, kind: Optional[str] = None) -> List[ProjectStatement]:
        self._assert_project(project_id)
        q = select(ProjectStatement).where(ProjectStatement.tenant_id == self.tenant_id,
                                           ProjectStatement.project_id == project_id,
                                           ProjectStatement.superseded_by == "")
        if kind:
            q = q.where(ProjectStatement.kind == kind)
        return list(self.s.scalars(q.order_by(ProjectStatement.created_at)))

    def supersede_statement(self, statement_id: str, replacement_id: str) -> None:
        st = self.s.get(ProjectStatement, statement_id)
        if st and st.tenant_id == self.tenant_id:
            st.superseded_by = replacement_id
            self.s.flush()

    # ----------------------------------------------------------- artifacts
    def save_artifact(self, project_id: str, kind: str, content: str, *,
                      name: str = "", fmt: str = "json", stage: str = "",
                      generated_by: str = "", agent_run_id: str = "") -> Artifact:
        """Insert a new version. Existing versions are superseded, never edited (§65)."""
        p = self._assert_project(project_id)
        latest = self.latest_artifact(project_id, kind)
        version = (latest.version + 1) if latest else 1
        a = Artifact(tenant_id=self.tenant_id, project_id=project_id,
                     project_version=p.version or 1, kind=kind, name=name or f"{kind}.{fmt}",
                     fmt=fmt, content=content, stage=stage, version=version,
                     generated_by=generated_by, agent_run_id=agent_run_id)
        self.s.add(a)
        self.s.flush()
        if latest:
            latest.superseded_by = a.id
        self.audit("artifact.created", "artifact", a.id,
                   after={"kind": kind, "version": version}, project_id=project_id)
        return a

    def latest_artifact(self, project_id: str, kind: str) -> Optional[Artifact]:
        self._assert_project(project_id)
        return self.s.scalar(
            select(Artifact).where(Artifact.tenant_id == self.tenant_id,
                                   Artifact.project_id == project_id,
                                   Artifact.kind == kind,
                                   Artifact.superseded_by == "")
            .order_by(Artifact.version.desc()))

    def list_artifacts(self, project_id: str, include_superseded: bool = False) -> List[Artifact]:
        self._assert_project(project_id)
        q = select(Artifact).where(Artifact.tenant_id == self.tenant_id,
                                   Artifact.project_id == project_id)
        if not include_superseded:
            q = q.where(Artifact.superseded_by == "")
        return list(self.s.scalars(q.order_by(Artifact.created_at.desc())))

    # ---------------------------------------------------------- agent runs
    def record_run(self, project_id: str, agent: str, **kw) -> AgentRun:
        p = self._assert_project(project_id)
        run = AgentRun(tenant_id=self.tenant_id, project_id=project_id, agent=agent,
                       project_version=p.version or 1, **kw)
        self.s.add(run)
        self.s.flush()
        return run

    def list_runs(self, project_id: str) -> List[AgentRun]:
        self._assert_project(project_id)
        return list(self.s.scalars(
            select(AgentRun).where(AgentRun.tenant_id == self.tenant_id,
                                   AgentRun.project_id == project_id)
            .order_by(AgentRun.created_at.desc())))

    # ---------------------------------------------------------- approvals
    def approve(self, project_id: str, subject_kind: str, subject_id: str,
                state: str = "APPROVED", comment: str = "") -> ApprovalRecord:
        self._assert_project(project_id)
        rec = ApprovalRecord(tenant_id=self.tenant_id, project_id=project_id,
                             subject_kind=subject_kind, subject_id=subject_id,
                             state=state, comment=comment, actor=self.actor)
        self.s.add(rec)
        self.s.flush()
        self.audit(f"approval.{state.lower()}", subject_kind, subject_id, reason=comment,
                   project_id=project_id)
        return rec

    def approval_state(self, project_id: str, subject_kind: str, subject_id: str) -> str:
        rec = self.s.scalar(
            select(ApprovalRecord).where(ApprovalRecord.tenant_id == self.tenant_id,
                                         ApprovalRecord.project_id == project_id,
                                         ApprovalRecord.subject_kind == subject_kind,
                                         ApprovalRecord.subject_id == subject_id)
            .order_by(ApprovalRecord.created_at.desc()))
        return rec.state if rec else "DRAFT"

    # -------------------------------------------------------------- trace
    def link(self, project_id: str, from_kind: str, from_id: str,
             to_kind: str, to_id: str, relation: str = "derives") -> TraceLink:
        self._assert_project(project_id)
        t = TraceLink(tenant_id=self.tenant_id, project_id=project_id,
                      from_kind=from_kind, from_id=from_id,
                      to_kind=to_kind, to_id=to_id, relation=relation)
        self.s.add(t)
        self.s.flush()
        return t

    def trace_upstream(self, project_id: str, node_id: str) -> List[TraceLink]:
        """Answer 'why does this exist?' by walking edges backwards (§30)."""
        self._assert_project(project_id)
        out, frontier, seen = [], [node_id], set()
        while frontier:
            current = frontier.pop()
            if current in seen:
                continue
            seen.add(current)
            links = list(self.s.scalars(
                select(TraceLink).where(TraceLink.tenant_id == self.tenant_id,
                                        TraceLink.project_id == project_id,
                                        TraceLink.to_id == current)))
            out.extend(links)
            frontier.extend(l.from_id for l in links)
        return out

    # -------------------------------------------------------------- audit
    def audit(self, action: str, subject_kind: str = "", subject_id: str = "",
              reason: str = "", before: Any = None, after: Any = None,
              actor_kind: str = "human", project_id: str = "") -> AuditEvent:
        ev = AuditEvent(tenant_id=self.tenant_id, project_id=project_id, actor=self.actor,
                        actor_kind=actor_kind, action=action, subject_kind=subject_kind,
                        subject_id=subject_id, reason=reason,
                        before_json=json.dumps(before, default=str) if before is not None else "",
                        after_json=json.dumps(after, default=str) if after is not None else "")
        self.s.add(ev)
        self.s.flush()
        return ev

    def list_audit(self, project_id: str = "", limit: int = 200) -> List[AuditEvent]:
        q = select(AuditEvent).where(AuditEvent.tenant_id == self.tenant_id)
        if project_id:
            q = q.where(AuditEvent.project_id == project_id)
        return list(self.s.scalars(q.order_by(AuditEvent.created_at.desc()).limit(limit)))

    # ------------------------------------------------------------ helpers
    def _assert_project(self, project_id: str) -> Project:
        p = self.get_project(project_id)
        if not p:
            raise KeyError(f"Project {project_id} not found in this tenant.")
        return p
