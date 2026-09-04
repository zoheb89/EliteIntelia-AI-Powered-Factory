"""Canonical persistence model (spec §40, §58, §64, §65).

Design rules enforced here:

* **Tenant isolation (§58)** — every tenant-scoped table carries `tenant_id`,
  and access goes through the repository layer which always filters on it.
* **Versioning (§65)** — approved content is never overwritten. Versioned rows
  carry `(project_id, kind, version)` and a `superseded_by` pointer.
* **Portability (§40)** — plain SQLAlchemy types only, so the same schema runs
  on SQLite for development and PostgreSQL in production.
* **Auditability (§59)** — `AuditEvent` is append-only; nothing updates it.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)


# --------------------------------------------------------------- tenancy §58
class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"
    id = Column(String(36), primary_key=True, default=_uuid)
    name = Column(String(200), nullable=False)
    slug = Column(String(80), unique=True, nullable=False)
    kind = Column(String(40), default="enterprise")   # enterprise | consulting
    settings_json = Column(Text, default="{}")
    active = Column(Boolean, default=True)


class User(Base, TimestampMixin):
    __tablename__ = "users_v2"
    id = Column(String(36), primary_key=True, default=_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    email = Column(String(255), nullable=False)
    name = Column(String(200), default="")
    role = Column(String(40), default="viewer")       # viewer | editor | admin
    password_hash = Column(Text, nullable=False)
    last_login = Column(DateTime(timezone=True))
    active = Column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),)


# --------------------------------------------------------------- projects §6
class Project(Base, TimestampMixin):
    __tablename__ = "projects_v2"
    id = Column(String(36), primary_key=True, default=_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String(300), nullable=False)
    intent = Column(Text, default="")                 # "what do you want to build?" §7
    domain = Column(String(120), default="")
    domain_pack = Column(String(80), default="")      # §53
    customer = Column(String(200), default="")
    status = Column(String(40), default="active")
    version = Column(Integer, default=1)              # canonical model version §65
    created_by = Column(String(255), default="")

    evidence = relationship("Evidence", back_populates="project", cascade="all, delete-orphan")
    __table_args__ = (Index("ix_project_tenant_status", "tenant_id", "status"),)


class ProjectVersion(Base):
    """Immutable snapshot of the canonical model, referenced by artifacts (§65)."""
    __tablename__ = "project_versions"
    id = Column(String(36), primary_key=True, default=_uuid)
    tenant_id = Column(String(36), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects_v2.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    snapshot_json = Column(Text, nullable=False)
    reason = Column(String(400), default="")
    created_by = Column(String(255), default="")
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    __table_args__ = (UniqueConstraint("project_id", "version", name="uq_project_version"),)


# --------------------------------------------------------------- evidence §8
class Evidence(Base, TimestampMixin):
    __tablename__ = "evidence"
    id = Column(String(36), primary_key=True, default=_uuid)
    tenant_id = Column(String(36), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects_v2.id"), nullable=False, index=True)
    name = Column(String(400), nullable=False)
    mime_type = Column(String(120), default="")
    size_bytes = Column(Integer, default=0)
    sha256 = Column(String(64), default="", index=True)   # dedupe + integrity §8
    source = Column(String(80), default="upload")
    document_type = Column(String(40), default="unknown") # rfi | rfp | rfq | notes | schema …
    classification = Column(String(40), default="internal")
    sensitivity = Column(String(40), default="normal")    # normal | pii | phi
    version = Column(Integer, default=1)
    status = Column(String(40), default="pending")        # pending | processed | failed
    storage_uri = Column(Text, default="")                # object storage §40
    extracted_text = Column(Text, default="")
    analysis_json = Column(Text, default="{}")
    author = Column(String(200), default="")

    project = relationship("Project", back_populates="evidence")


class EvidenceChunk(Base):
    """Retrievable unit with a locator, so citations point somewhere real (§30)."""
    __tablename__ = "evidence_chunks"
    id = Column(String(36), primary_key=True, default=_uuid)
    tenant_id = Column(String(36), nullable=False, index=True)
    evidence_id = Column(String(36), ForeignKey("evidence.id"), nullable=False, index=True)
    project_id = Column(String(36), nullable=False, index=True)
    ordinal = Column(Integer, default=0)
    locator = Column(String(200), default="")
    text = Column(Text, default="")
    embedding_ref = Column(String(200), default="")      # vector index key §40


# ------------------------------------------------- canonical statements §8/§64
class ProjectStatement(Base, TimestampMixin):
    """Requirements, risks, assumptions, unknowns, objectives — all provenance-tagged."""
    __tablename__ = "project_statements"
    id = Column(String(36), primary_key=True, default=_uuid)
    tenant_id = Column(String(36), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects_v2.id"), nullable=False, index=True)
    kind = Column(String(60), nullable=False, index=True)  # requirement | risk | unknown | objective …
    ref = Column(String(40), default="")                   # human handle, e.g. R-104
    text = Column(Text, nullable=False)
    provenance = Column(String(40), default="AI_INFERENCE")
    confidence = Column(String(20), default="MEDIUM")
    evidence_json = Column(Text, default="[]")             # [EvidenceRef]
    stage = Column(String(60), default="")
    status = Column(String(40), default="open")
    version = Column(Integer, default=1)
    superseded_by = Column(String(36), default="")
    created_by = Column(String(255), default="system")
    __table_args__ = (Index("ix_stmt_project_kind", "project_id", "kind"),)


class Decision(Base, TimestampMixin):
    """Decision Centre record (spec §32)."""
    __tablename__ = "decisions"
    id = Column(String(36), primary_key=True, default=_uuid)
    tenant_id = Column(String(36), nullable=False, index=True)
    project_id = Column(String(36), nullable=False, index=True)
    ref = Column(String(40), default="")
    question = Column(Text, nullable=False)
    options_json = Column(Text, default="[]")
    evidence_json = Column(Text, default="[]")
    recommendation = Column(Text, default="")
    reasoning = Column(Text, default="")
    risks_json = Column(Text, default="[]")
    impact = Column(Text, default="")
    owner = Column(String(255), default="")
    status = Column(String(40), default="Proposed")   # Proposed|Under Review|Approved|Rejected|Superseded
    decided_at = Column(DateTime(timezone=True))


class TraceLink(Base):
    """Delivery graph edge: requirement -> use case -> architecture -> … (§30, §56)."""
    __tablename__ = "trace_links"
    id = Column(String(36), primary_key=True, default=_uuid)
    tenant_id = Column(String(36), nullable=False, index=True)
    project_id = Column(String(36), nullable=False, index=True)
    from_kind = Column(String(60), nullable=False)
    from_id = Column(String(36), nullable=False, index=True)
    to_kind = Column(String(60), nullable=False)
    to_id = Column(String(36), nullable=False, index=True)
    relation = Column(String(60), default="derives")
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    __table_args__ = (Index("ix_trace_from", "project_id", "from_id"),
                      Index("ix_trace_to", "project_id", "to_id"))


# ------------------------------------------------------- runs, jobs, artifacts
class AgentRun(Base):
    """AI Run Centre record — full auditability of every model call (§34)."""
    __tablename__ = "agent_runs"
    id = Column(String(36), primary_key=True, default=_uuid)
    tenant_id = Column(String(36), nullable=False, index=True)
    project_id = Column(String(36), nullable=False, index=True)
    project_version = Column(Integer, default=1)
    agent = Column(String(80), nullable=False)
    stage = Column(String(60), default="")
    provider = Column(String(80), default="")
    model = Column(String(120), default="")
    prompt_version = Column(String(40), default="")
    input_refs_json = Column(Text, default="[]")
    output_json = Column(Text, default="{}")
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    cost_estimate = Column(Float, default=0.0)
    duration_ms = Column(Integer, default=0)
    confidence = Column(String(20), default="MEDIUM")
    status = Column(String(40), default="success")
    generation_mode = Column(String(60), default="ai")   # ai | deterministic_evidence_only
    reviewer = Column(String(255), default="")
    approved = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)


class JobRecord(Base):
    """Durable job state so work resumes across restarts (§42-§44)."""
    __tablename__ = "jobs"
    id = Column(String(36), primary_key=True, default=_uuid)
    tenant_id = Column(String(36), default="", index=True)
    project_id = Column(String(36), nullable=False, index=True)
    kind = Column(String(80), nullable=False)
    status = Column(String(20), default="QUEUED", index=True)
    current_step = Column(String(80), default="")
    completed_steps = Column(Integer, default=0)
    total_steps = Column(Integer, default=0)
    message = Column(Text, default="")
    error = Column(Text, default="")
    payload_json = Column(Text, default="{}")   # full serialised Job
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))


class LLMCacheEntry(Base):
    """A completed model call, keyed by request fingerprint.

    On a metered plan an identical repeated call is spent quota, not just
    latency. Persisting the answer means re-running a stage over unchanged
    evidence is free, and survives the restart that would otherwise discard
    every answer already paid for.
    """
    __tablename__ = "llm_cache_v2"
    key = Column(String(64), primary_key=True)
    tenant_id = Column(String(36), default="", index=True)
    provider = Column(String(80), default="")
    model = Column(String(120), default="")
    text = Column(Text, default="")
    hits = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=_now)
    last_used_at = Column(DateTime(timezone=True), default=_now)


class Artifact(Base):
    """Generated deliverable, pinned to the project version it came from (§28, §65)."""
    __tablename__ = "artifacts_v2"
    id = Column(String(36), primary_key=True, default=_uuid)
    tenant_id = Column(String(36), nullable=False, index=True)
    project_id = Column(String(36), nullable=False, index=True)
    project_version = Column(Integer, nullable=False)
    stage = Column(String(60), default="")
    kind = Column(String(80), nullable=False, index=True)
    name = Column(String(300), default="")
    fmt = Column(String(20), default="json")     # json|md|sql|py|yaml|pdf|docx|xlsx|pptx
    content = Column(Text, default="")
    storage_uri = Column(Text, default="")
    version = Column(Integer, default=1)
    superseded_by = Column(String(36), default="")
    approval_state = Column(String(40), default="AI_GENERATED")  # §33
    generated_by = Column(String(80), default="")
    agent_run_id = Column(String(36), default="")
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    __table_args__ = (Index("ix_artifact_project_kind", "project_id", "kind", "version"),)


class ApprovalRecord(Base):
    """Approval engine: never overwrite, always append a new state (§33)."""
    __tablename__ = "approvals_v2"
    id = Column(String(36), primary_key=True, default=_uuid)
    tenant_id = Column(String(36), nullable=False, index=True)
    project_id = Column(String(36), nullable=False, index=True)
    subject_kind = Column(String(60), nullable=False)   # stage | artifact | decision
    subject_id = Column(String(120), nullable=False)
    state = Column(String(40), default="UNDER_REVIEW")  # DRAFT|AI_GENERATED|UNDER_REVIEW|APPROVED|REJECTED|SUPERSEDED
    comment = Column(Text, default="")
    actor = Column(String(255), default="")
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)


class AuditEvent(Base):
    """Append-only audit trail (§59). Never updated, never deleted."""
    __tablename__ = "audit_events"
    id = Column(String(36), primary_key=True, default=_uuid)
    tenant_id = Column(String(36), default="", index=True)
    project_id = Column(String(36), default="", index=True)
    actor = Column(String(255), default="")
    actor_kind = Column(String(20), default="human")   # human | ai | system
    action = Column(String(120), nullable=False)
    subject_kind = Column(String(60), default="")
    subject_id = Column(String(120), default="")
    reason = Column(Text, default="")
    before_json = Column(Text, default="")
    after_json = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False, index=True)


# ----------------------------------------------------------- connections §35
class LLMProviderConfig(Base, TimestampMixin):
    """Per-tenant model provider. Secrets are stored as references, not values."""
    __tablename__ = "llm_providers"
    id = Column(String(36), primary_key=True, default=_uuid)
    tenant_id = Column(String(36), nullable=False, index=True)
    name = Column(String(80), nullable=False)
    kind = Column(String(60), nullable=False)
    endpoint = Column(Text, default="")
    model = Column(String(160), default="")
    secret_ref = Column(String(200), default="")    # never the key itself
    auth_header = Column(String(80), default="Authorization")
    auth_scheme = Column(String(40), default="Bearer")
    timeout_seconds = Column(Integer, default=90)
    max_retries = Column(Integer, default=2)
    priority = Column(Integer, default=100)
    enabled = Column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_llm_tenant_name"),)


class PlatformConnection(Base, TimestampMixin):
    """Customer cloud/data platform connection (§16). Credentials by reference only."""
    __tablename__ = "platform_connections"
    id = Column(String(36), primary_key=True, default=_uuid)
    tenant_id = Column(String(36), nullable=False, index=True)
    project_id = Column(String(36), default="", index=True)
    platform = Column(String(80), nullable=False)
    cloud = Column(String(40), default="")
    environment_mode = Column(String(40), default="existing")
    endpoint = Column(Text, default="")
    secret_ref = Column(String(200), default="")
    region = Column(String(60), default="")
    state = Column(String(40), default="NOT_SELECTED")
    verified_at = Column(DateTime(timezone=True))


ALL_TABLES = [
    Tenant, User, Project, ProjectVersion, Evidence, EvidenceChunk,
    ProjectStatement, Decision, TraceLink, AgentRun, JobRecord, Artifact,
    ApprovalRecord, AuditEvent, LLMProviderConfig, PlatformConnection,
]
