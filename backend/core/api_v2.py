"""Core API surface for the canonical model (spec §63).

Mounted alongside the existing routes so the deployed application keeps working
while the new core is adopted incrementally. Everything here is tenant-scoped
and provider-neutral.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.domain.lifecycle import (
    GROUPS, STAGES, STAGE_BY_ID, Approval, LifecycleState, StageStatus, downstream_of,
)
from core.domain.provenance import (
    PROVENANCE_RANK, Confidence, EvidenceRef, Provenance, Statement,
)
from jobs.engine import JobEngine, JobStatus
from llm.gateway.base import LLMRequest, Message, Role
from llm.gateway.gateway import gateway_from_env
from persistence import repository as R

router = APIRouter(prefix="/api/v2", tags=["core"])

# Process-wide singletons. The job engine keeps state in memory for now; the
# JobRecord table exists so this can move to a durable store without API change.
_gateway = gateway_from_env()

# Serve identical repeated calls from storage. On a metered plan a re-run over
# unchanged evidence is spent quota, so this is budget protection, not a
# latency optimisation.
try:
    from llm.cache import DatabaseCache
    _gateway.cache = DatabaseCache(R.session_scope)
except Exception:                      # never let caching block start-up
    pass
_jobs = JobEngine()

DEFAULT_TENANT_SLUG = os.getenv("DEFAULT_TENANT", "default")


# --------------------------------------------------------------- dependencies
def _tenant_id(session) -> str:
    return R.Repository.ensure_tenant(session, DEFAULT_TENANT_SLUG, "Default Organization").id


def get_repo(actor: str = "system"):
    """Yield a tenant-scoped repository bound to a request-lifetime session."""
    with R.session_scope() as s:
        yield R.Repository(s, _tenant_id(s), actor)


# -------------------------------------------------------------------- schemas
class ProjectIn(BaseModel):
    name: str
    intent: str = ""
    domain: str = ""
    customer: str = ""


class StatementIn(BaseModel):
    kind: str
    text: str
    provenance: str = "AI_INFERENCE"
    confidence: str = "MEDIUM"
    stage: str = ""
    ref: str = ""
    evidence: List[dict] = Field(default_factory=list)


class ApprovalIn(BaseModel):
    subject_kind: str = "stage"
    subject_id: str
    state: str = "APPROVED"
    comment: str = ""


class PromptIn(BaseModel):
    prompt: str
    system: str = "You are a helpful enterprise delivery assistant."
    provider: Optional[str] = None
    json_mode: bool = False
    max_tokens: int = 500


# ------------------------------------------------------------------ lifecycle
@router.get("/lifecycle")
def lifecycle_definition():
    """The delivery lifecycle as data, so the UI never hard-codes stages."""
    return {
        "groups": GROUPS,
        "stages": [
            {"id": s.id, "label": s.label, "group": s.group, "agent": s.agent,
             "produces": s.produces, "requires": s.requires,
             "approval": s.approval.value, "description": s.description}
            for s in STAGES
        ],
        "provenance": [{"value": p.value, "rank": PROVENANCE_RANK[p],
                        "evidence_backed": p.is_evidence_backed,
                        "requires_confirmation": p.requires_confirmation}
                       for p in Provenance],
    }


def _state_for(repo: R.Repository, project_id: str) -> LifecycleState:
    """Lifecycle state, derived by the orchestrator so there is one source of truth."""
    from agents_v2.orchestrator import Orchestrator as _O
    return _O(_gateway, _jobs).lifecycle_state(repo, project_id)


@router.get("/projects/{project_id}/lifecycle")
def project_lifecycle(project_id: str, repo: R.Repository = Depends(get_repo)):
    if not repo.get_project(project_id):
        raise HTTPException(404, "Project not found")
    st = _state_for(repo, project_id)
    nxt, pending = st.next_stage(), st.pending_approval()
    done, total = st.progress

    # How each completed stage was actually generated. Without this the board
    # cannot distinguish AI output from an evidence-only fallback, and a
    # degraded run looks identical to a real one.
    modes: Dict[str, str] = {}
    degraded_reason = ""
    for run in repo.list_runs(project_id):
        if run.stage and run.stage not in modes:
            modes[run.stage] = run.generation_mode or "ai"
            if (run.generation_mode or "ai") != "ai" and not degraded_reason:
                try:
                    payload = json.loads(run.output_json or "{}")
                    for w in payload.get("warnings", []):
                        degraded_reason = w
                        break
                except (json.JSONDecodeError, TypeError):
                    pass

    degraded = [k for k, v in modes.items() if v != "ai"]
    return {
        "progress": {"complete": done, "total": total},
        "generation": {
            "degraded_stages": degraded,
            "ai_stages": [k for k, v in modes.items() if v == "ai"],
            "any_degraded": bool(degraded),
            "reason": degraded_reason,
        },
        "stages": {s.id: {"status": st.status(s.id).value,
                          "approved": st.approvals.get(s.id, False),
                          "generation_mode": modes.get(s.id),
                          "blockers": st.blockers(s.id)} for s in STAGES},
        "next_stage": ({"id": nxt.id, "label": nxt.label, "agent": nxt.agent,
                        "produces": nxt.produces} if nxt else None),
        "pending_approval": ({"id": pending.id, "label": pending.label,
                              "approval": pending.approval.value} if pending else None),
    }


# ------------------------------------------------------------------- projects
@router.post("/projects", status_code=201)
def create_project(body: ProjectIn, repo: R.Repository = Depends(get_repo)):
    p = repo.create_project(body.name, body.intent, body.domain, body.customer)
    return {"id": p.id, "name": p.name, "version": p.version}


@router.get("/projects")
def list_projects(repo: R.Repository = Depends(get_repo)):
    return {"items": [{"id": p.id, "name": p.name, "intent": p.intent,
                       "domain": p.domain, "version": p.version,
                       "updated_at": p.updated_at.isoformat() if p.updated_at else None}
                      for p in repo.list_projects()]}


@router.get("/projects/{project_id}")
def get_project(project_id: str, repo: R.Repository = Depends(get_repo)):
    p = repo.get_project(project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    return {
        "id": p.id, "name": p.name, "intent": p.intent, "domain": p.domain,
        "customer": p.customer, "version": p.version,
        "evidence": len(repo.list_evidence(project_id)),
        "artifacts": len(repo.list_artifacts(project_id)),
        "runs": len(repo.list_runs(project_id)),
    }


# ----------------------------------------------------------------- statements
@router.post("/projects/{project_id}/statements", status_code=201)
def add_statement(project_id: str, body: StatementIn, repo: R.Repository = Depends(get_repo)):
    """Create a statement.

    The payload is normalised through the domain `Statement` first, so the
    no-hallucination rule (§68) is enforced at the API boundary too: a claim of
    FACT with no evidence reference is downgraded rather than trusted.
    """
    try:
        provenance = Provenance(body.provenance)
    except ValueError:
        raise HTTPException(422, detail={
            "code": "BAD_PROVENANCE",
            "message": f"provenance must be one of: {', '.join(p.value for p in Provenance)}",
        })

    checked = Statement(
        text=body.text, provenance=provenance,
        confidence=Confidence(body.confidence) if body.confidence in
        {c.value for c in Confidence} else Confidence.MEDIUM,
        evidence=[EvidenceRef(**e) for e in body.evidence],
        created_by=repo.actor,
    )
    try:
        st = repo.add_statement(
            project_id, body.kind, checked.text, checked.provenance.value,
            checked.confidence.value, [e.to_dict() for e in checked.evidence],
            body.stage, body.ref)
    except KeyError:
        raise HTTPException(404, "Project not found")
    return {"id": st.id, "kind": st.kind, "provenance": st.provenance,
            "confidence": st.confidence, "note": checked.note}


@router.get("/projects/{project_id}/statements")
def list_statements(project_id: str, kind: Optional[str] = None,
                    repo: R.Repository = Depends(get_repo)):
    try:
        items = repo.list_statements(project_id, kind)
    except KeyError:
        raise HTTPException(404, "Project not found")
    return {"items": [{"id": s.id, "ref": s.ref, "kind": s.kind, "text": s.text,
                       "provenance": s.provenance, "confidence": s.confidence,
                       "evidence": json.loads(s.evidence_json or "[]")}
                      for s in items]}


@router.get("/projects/{project_id}/unknowns")
def open_questions(project_id: str, repo: R.Repository = Depends(get_repo)):
    """Everything explicitly not known — drives the customer question set (§11)."""
    try:
        items = repo.list_statements(project_id)
    except KeyError:
        raise HTTPException(404, "Project not found")
    unknowns = [s for s in items if s.provenance == Provenance.UNKNOWN.value]
    return {"items": [{"id": s.id, "text": s.text, "stage": s.stage} for s in unknowns],
            "count": len(unknowns)}


# ------------------------------------------------------------------ artifacts
# ---------------------------------------------------------------- accelerators
@router.get("/accelerators")
def accelerator_catalogue():
    """The full accelerator catalogue, grouped by category (§16, §53)."""
    from core.accelerators import catalogue
    return catalogue()


@router.get("/projects/{project_id}/accelerators")
def project_accelerators(project_id: str, repo: R.Repository = Depends(get_repo)):
    """Which accelerators this engagement's own evidence calls for."""
    from core.accelerators import applicable

    try:
        statements = repo.list_statements(project_id)
        evidence = repo.list_evidence(project_id)
        project = repo.get_project(project_id)
    except KeyError:
        raise HTTPException(404, "Project not found")

    texts = [project.intent or "", project.name or ""]
    texts += [s.text for s in statements]
    texts += [e.name or "" for e in evidence]
    texts += [(e.extracted_text or "")[:20_000] for e in evidence]

    st = _state_for(repo, project_id)
    done = [s.id for s in STAGES if st.is_complete(s.id)]
    return applicable(texts, done)


# --------------------------------------------------------------- traceability
@router.get("/projects/{project_id}/traceability")
def traceability(project_id: str, repo: R.Repository = Depends(get_repo)):
    """BRD / FRD / SRD layers, the parent chain, and what fails to trace (§11)."""
    from core.traceability import build, chain, coverage

    try:
        statements = repo.list_statements(project_id)
    except KeyError:
        raise HTTPException(404, "Project not found")

    layers = build(statements)
    return {"layers": layers, "chain": chain(layers), "coverage": coverage(layers)}


# ------------------------------------------------------------------ scope lock
class ScopeLockIn(BaseModel):
    locked_by: str = "human"
    acknowledge_blockers: bool = False


class ChangeRequestIn(BaseModel):
    raised_by: str = "human"
    reason: str = ""


def _scope_snapshot(repo: R.Repository, project_id: str):
    from core.scope_lock import snapshot
    return snapshot(repo.list_statements(project_id))


def _current_lock(repo: R.Repository, project_id: str):
    art = repo.latest_artifact(project_id, "scope_lock")
    return json.loads(art.content) if art else None


@router.get("/projects/{project_id}/scope")
def scope_status(project_id: str, repo: R.Repository = Depends(get_repo)):
    """The frozen scope, the live scope, and any drift between them (§33)."""
    from core.scope_lock import diff, readiness

    try:
        current = _scope_snapshot(repo, project_id)
    except KeyError:
        raise HTTPException(404, "Project not found")

    open_questions = sum(1 for s in repo.list_statements(project_id)
                         if (s.provenance or "") == "UNKNOWN")
    locked = _current_lock(repo, project_id)
    out = {"locked": bool(locked), "current": current,
           "readiness": readiness(current, open_questions)}
    if locked:
        out["lock"] = {k: v for k, v in locked.items() if k != "items"}
        out["drift"] = diff(locked, current)
    return out


@router.post("/projects/{project_id}/scope/lock")
def scope_lock(project_id: str, body: ScopeLockIn,
               repo: R.Repository = Depends(get_repo)):
    from core.scope_lock import lock, readiness

    try:
        current = _scope_snapshot(repo, project_id)
    except KeyError:
        raise HTTPException(404, "Project not found")

    open_questions = sum(1 for s in repo.list_statements(project_id)
                         if (s.provenance or "") == "UNKNOWN")
    ready = readiness(current, open_questions)
    # Locking over open blockers is allowed, but only deliberately and on the
    # record — a freeze nobody can see the caveats on is worse than none.
    if not ready["ready"] and not body.acknowledge_blockers:
        raise HTTPException(409, detail={"code": "SCOPE_NOT_READY", **ready})

    previous = _current_lock(repo, project_id)
    record = lock(current, body.locked_by,
                  version=(previous or {}).get("version", 0) + 1,
                  acknowledged_blockers=ready["blockers"] if not ready["ready"] else [])
    repo.save_artifact(project_id, "scope_lock", json.dumps(record, indent=2),
                       name="scope_lock.json", fmt="json", stage="scope",
                       generated_by="scope_lock_engine")
    repo.audit("scope.lock", subject_kind="scope", subject_id=record["hash"][:12],
               reason=f"v{record['version']} · {record['scope_count']} items",
               after={"version": record["version"], "hash": record["hash"]},
               project_id=project_id)
    return record


@router.post("/projects/{project_id}/scope/change-request")
def scope_change_request(project_id: str, body: ChangeRequestIn,
                         repo: R.Repository = Depends(get_repo)):
    from core.scope_lock import change_request, diff

    locked = _current_lock(repo, project_id)
    if not locked:
        raise HTTPException(409, detail={"code": "NOT_LOCKED",
                                         "message": "Scope has not been locked, so "
                                                    "there is nothing to change against."})
    current = _scope_snapshot(repo, project_id)
    delta = diff(locked, current)
    if not delta["changed"]:
        raise HTTPException(409, detail={"code": "NO_CHANGE",
                                         "message": "Current scope matches the lock."})

    existing = [a for a in repo.list_artifacts(project_id) if a.kind == "change_request"]
    cr = change_request(delta, body.raised_by, body.reason, number=len(existing) + 1)
    repo.save_artifact(project_id, "change_request", json.dumps(cr, indent=2),
                       name=f"{cr['id']}.json", fmt="json", stage="scope",
                       generated_by="scope_lock_engine")
    repo.audit("scope.change_request", subject_kind="change_request",
               subject_id=cr["id"], reason=cr["summary"],
               after={"added": len(cr["added"]), "removed": len(cr["removed"])},
               project_id=project_id)
    return cr


@router.get("/projects/{project_id}/next-action")
def next_action(project_id: str, repo: R.Repository = Depends(get_repo)):
    """What should happen next on this engagement, and why (spec §2, §8)."""
    from core.next_action import recommend

    try:
        st = _state_for(repo, project_id)
        statements = repo.list_statements(project_id)
        evidence = repo.list_evidence(project_id)
    except KeyError:
        raise HTTPException(404, "Project not found")
    return recommend(st, statements, len(evidence))


@router.get("/projects/{project_id}/artifacts")
def list_artifacts(project_id: str, include_superseded: bool = False,
                   repo: R.Repository = Depends(get_repo)):
    try:
        items = repo.list_artifacts(project_id, include_superseded)
    except KeyError:
        raise HTTPException(404, "Project not found")
    return {"items": [{"id": a.id, "kind": a.kind, "name": a.name, "fmt": a.fmt,
                       "version": a.version, "project_version": a.project_version,
                       "approval_state": a.approval_state,
                       "superseded": bool(a.superseded_by),
                       "created_at": a.created_at.isoformat() if a.created_at else None}
                      for a in items]}


# ------------------------------------------------------------------ approvals
@router.post("/projects/{project_id}/approvals")
def approve(project_id: str, body: ApprovalIn, repo: R.Repository = Depends(get_repo)):
    try:
        rec = repo.approve(project_id, body.subject_kind, body.subject_id,
                           body.state, body.comment)
    except KeyError:
        raise HTTPException(404, "Project not found")
    return {"id": rec.id, "state": rec.state, "subject_id": rec.subject_id}


# ---------------------------------------------------------------- change §31
@router.get("/projects/{project_id}/impact/{stage_id}")
def change_impact(project_id: str, stage_id: str, repo: R.Repository = Depends(get_repo)):
    """What must be revisited if this stage changes."""
    if stage_id not in STAGE_BY_ID:
        raise HTTPException(404, "Unknown stage")
    if not repo.get_project(project_id):
        raise HTTPException(404, "Project not found")
    affected = downstream_of(stage_id)
    st = _state_for(repo, project_id)
    produced = {a.kind: a for a in repo.list_artifacts(project_id)}
    return {
        "stage": stage_id,
        "affected_stages": [
            {"id": sid, "label": STAGE_BY_ID[sid].label,
             "currently_complete": st.is_complete(sid),
             "artifacts_to_regenerate": [k for k in STAGE_BY_ID[sid].produces if k in produced]}
            for sid in affected
        ],
        "artifacts_invalidated": sum(
            1 for sid in affected for k in STAGE_BY_ID[sid].produces if k in produced),
    }


# ---------------------------------------------------------------- audit §59
@router.get("/projects/{project_id}/audit")
def audit(project_id: str, limit: int = 200, repo: R.Repository = Depends(get_repo)):
    if not repo.get_project(project_id):
        raise HTTPException(404, "Project not found")
    return {"items": [{"action": e.action, "actor": e.actor, "actor_kind": e.actor_kind,
                       "subject_kind": e.subject_kind, "subject_id": e.subject_id,
                       "reason": e.reason,
                       "at": e.created_at.isoformat() if e.created_at else None}
                      for e in repo.list_audit(project_id, limit)]}


# ------------------------------------------------------------------- LLM §35
@router.get("/llm/providers")
def llm_providers():
    """Registered providers with secrets redacted. No vendor is assumed."""
    cache_stats = {}
    try:
        cache_stats = _gateway.cache.stats() if _gateway.cache else {}
    except Exception:
        cache_stats = {}
    return {"providers": _gateway.describe(),
            "default": _gateway.default_provider,
            "cache": cache_stats,
            "configured": bool(_gateway.describe())}


@router.post("/llm/complete")
def llm_complete(body: PromptIn):
    """Provider-neutral completion, used to verify a gateway configuration."""
    req = LLMRequest(
        messages=[Message(Role.SYSTEM, body.system), Message(Role.USER, body.prompt)],
        json_mode=body.json_mode, max_tokens=body.max_tokens,
    )
    try:
        if body.json_mode:
            data, result = _gateway.complete_json(req, body.provider)
            return {"ok": True, "json": data,
                    "calls": [c.to_dict() for c in result.calls]}
        result = _gateway.complete(req, body.provider)
        return {"ok": True, "text": result.response.text,
                "usage": result.response.usage.to_dict(),
                "provider": result.response.provider, "model": result.response.model,
                "calls": [c.to_dict() for c in result.calls]}
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator
        raise HTTPException(502, detail={"code": "LLM_ERROR", "message": str(exc)})


# ------------------------------------------------------------------ jobs §63
@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = _jobs.store.load(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job.to_dict()


@router.get("/projects/{project_id}/jobs")
def project_jobs(project_id: str):
    return {"items": [j.to_dict() for j in _jobs.store.list_for_project(project_id)]}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    job = _jobs.cancel(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job.to_dict()


# ==========================================================================
# Agents, estimation and SOW (spec §36, §25, §26, §27)
# ==========================================================================
from agents_v2.orchestrator import AGENTS, ENGINE_STAGES, GateError, Orchestrator  # noqa: E402
from core.estimation import Complexity, estimate, work_items_from_project  # noqa: E402
from core.sow import build_sow, render_markdown  # noqa: E402

_orchestrator = Orchestrator(_gateway, _jobs)


class RunStageIn(BaseModel):
    background: bool = True


class EstimateIn(BaseModel):
    contingency: float = 0.15
    team_size: int = 5
    technical: float = 1.0
    data: float = 1.0
    integration: float = 1.0
    governance: float = 1.0
    environment: float = 1.0
    sources: int = 0
    entities: int = 0
    reports: int = 0


DATA_SATISFIED = ("intent", "evidence")


@router.get("/agents")
def list_agents():
    """How every lifecycle stage is handled: agent, engine, or captured data."""
    handled_by = {}
    for st in STAGES:
        if st.id in DATA_SATISFIED:
            handled_by[st.id] = {"handler": "data", "detail": "Satisfied by captured data."}
        elif st.id in ENGINE_STAGES:
            handled_by[st.id] = {"handler": "engine", "detail": ENGINE_STAGES[st.id]}
        elif st.agent in AGENTS:
            handled_by[st.id] = {"handler": "agent", "detail": st.agent}
        else:
            handled_by[st.id] = {"handler": "none", "detail": "Not implemented."}
    return {
        "agents": [{"id": aid, "stages": [s.id for s in STAGES if s.agent == aid]}
                   for aid in sorted(AGENTS)],
        "stages": handled_by,
        "coverage": {
            "total": len(STAGES),
            "handled": sum(1 for v in handled_by.values() if v["handler"] != "none"),
            "unhandled": [k for k, v in handled_by.items() if v["handler"] == "none"],
        },
    }


class PlatformDecisionIn(BaseModel):
    platform: str
    rationale: str = ""


@router.get("/projects/{project_id}/platform/options")
def platform_options(project_id: str, repo: R.Repository = Depends(get_repo)):
    """Scored platform options. Deterministic, reproducible, evidence-derived (§14)."""
    if not repo.get_project(project_id):
        raise HTTPException(404, "Project not found")
    a = repo.latest_artifact(project_id, "platform_options")
    if a:
        return json.loads(a.content)

    # Not run yet: evaluate live from current requirements so the UI can preview.
    from core.platform_selection import evaluate
    reqs = [s.text for s in repo.list_statements(project_id, "requirement")]
    cons = [s.text for s in repo.list_statements(project_id, "constraint")]
    p = repo.get_project(project_id)
    if p.intent:
        cons.append(p.intent)
    return {**evaluate(reqs, cons), "persisted": False}


@router.post("/projects/{project_id}/platform/decision")
def platform_decision(project_id: str, body: PlatformDecisionIn,
                      repo: R.Repository = Depends(get_repo)):
    """Record the human platform decision (§14, §32).

    A choice that differs from the recommendation is preserved with its
    rationale — the platform advises, the customer decides.
    """
    if not repo.get_project(project_id):
        raise HTTPException(404, "Project not found")
    a = repo.latest_artifact(project_id, "platform_options")
    if not a:
        raise HTTPException(409, detail={
            "code": "NO_EVALUATION",
            "message": "Run the platform selection stage before recording a decision."})

    from core.platform_selection import apply_decision
    try:
        decided = apply_decision(json.loads(a.content), body.platform,
                                 body.rationale, repo.actor)
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "INVALID_PLATFORM", "message": str(exc)})

    repo.save_artifact(project_id, "platform_decision",
                       json.dumps(decided, indent=2, default=str),
                       stage="platform", generated_by="human_decision")
    repo.add_statement(project_id, "platform_decision",
                       f"Selected target platform: {body.platform}."
                       + ("" if decided["followed_recommendation"]
                          else f" This differs from the recommendation "
                               f"({decided['recommended_platform']})."),
                       provenance="CUSTOMER_DECISION", confidence="HIGH", stage="platform")
    repo.audit("platform.decided", "stage", "platform",
               reason=body.rationale or "Platform selected.",
               after={"platform": body.platform,
                      "followed_recommendation": decided["followed_recommendation"]},
               project_id=project_id)
    return decided


@router.get("/tools")
def list_tools():
    """Tool catalogue exposed to agents (§37)."""
    from core.tools.registry import build_project_tools

    class _Null:
        def get_project(self, _pid): return None
        def list_evidence(self, _pid): return []
        def list_statements(self, _pid, _k=None): return []
        def list_artifacts(self, _pid, *_a, **_k): return []
        def latest_artifact(self, _pid, _k): return None

    reg = build_project_tools(_Null(), "spec")
    return {"tools": [{"name": s.name, "description": s.description,
                       "parameters": s.parameters, "returns": s.returns}
                      for s in reg.specs()]}


@router.post("/projects/{project_id}/stages/{stage_id}")
def run_stage(project_id: str, stage_id: str, body: RunStageIn = RunStageIn(),
              repo: R.Repository = Depends(get_repo)):
    """Execute a lifecycle stage through its agent.

    Runs as a background job by default so a slow model call never blocks the
    request (§42). The response carries a job id to poll.
    """
    if stage_id not in STAGE_BY_ID:
        raise HTTPException(404, detail={"code": "UNKNOWN_STAGE", "stage": stage_id})
    if not repo.get_project(project_id):
        raise HTTPException(404, "Project not found")

    stage = STAGE_BY_ID[stage_id]
    if stage.agent not in AGENTS:
        raise HTTPException(501, detail={
            "code": "AGENT_NOT_IMPLEMENTED",
            "message": f"No agent is implemented for stage '{stage_id}' yet.",
            "agent": stage.agent})

    try:
        _orchestrator.check_gate(repo, project_id, stage_id)
    except GateError as exc:
        raise HTTPException(409, detail={"code": "STAGE_BLOCKED", "message": str(exc)})

    if not body.background:
        result = _orchestrator.run_stage(repo, project_id, stage_id)
        return {"status": "COMPLETED", "stage": stage_id,
                "artifacts": result.artifacts,
                "statements": result.statements_persisted,
                "output": result.output.to_dict()}

    tenant = repo.tenant_id
    actor = repo.actor

    from contextlib import contextmanager

    @contextmanager
    def repo_factory():
        # A fresh session: the job runs after this request's session has closed.
        with R.session_scope() as s:
            yield R.Repository(s, tenant, actor)

    job = _orchestrator.submit_stage(repo_factory, project_id, stage_id, tenant)
    return {"status": "QUEUED", "job_id": job.id, "stage": stage_id,
            "poll": f"/api/v2/jobs/{job.id}"}


@router.post("/projects/{project_id}/estimate")
def project_estimate(project_id: str, body: EstimateIn,
                     repo: R.Repository = Depends(get_repo)):
    """Deterministic effort, automation and duration estimate (§23-§25)."""
    if not repo.get_project(project_id):
        raise HTTPException(404, "Project not found")

    reqs = [{"text": s.text} for s in repo.list_statements(project_id, "requirement")]
    sources = body.sources or len(repo.list_statements(project_id, "source"))
    items = work_items_from_project(
        requirements=reqs, sources=sources, entities=body.entities,
        reports=body.reports,
        complexity=Complexity(body.technical, body.data, body.integration,
                              body.governance, body.environment))
    result = estimate(items, contingency=body.contingency, team_size=body.team_size)
    repo.save_artifact(project_id, "estimate",
                       json.dumps(result, indent=2, default=str),
                       stage="estimation", generated_by="estimation_engine")
    repo.save_artifact(project_id, "automation_assessment",
                       json.dumps(result.get("automation", {}), indent=2, default=str),
                       stage="estimation", generated_by="estimation_engine")
    return result


@router.get("/projects/{project_id}/sow")
def project_sow(project_id: str, fmt: str = "json",
                repo: R.Repository = Depends(get_repo)):
    """Assemble the SOW deterministically from the canonical model (§26)."""
    p = repo.get_project(project_id)
    if not p:
        raise HTTPException(404, "Project not found")

    statements = [{"kind": s.kind, "text": s.text, "provenance": s.provenance}
                  for s in repo.list_statements(project_id)]

    est = {}
    a = repo.latest_artifact(project_id, "estimate")
    if a:
        try:
            est = json.loads(a.content)
        except json.JSONDecodeError:
            est = {}

    arch = {}
    ar = repo.latest_artifact(project_id, "architecture")
    if ar:
        try:
            arch = json.loads(ar.content)
        except json.JSONDecodeError:
            arch = {}

    sow = build_sow({"name": p.name, "intent": p.intent, "domain": p.domain,
                     "version": p.version}, statements, est, arch)

    if fmt == "markdown":
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(render_markdown(sow))

    repo.save_artifact(project_id, "sow", json.dumps(sow, indent=2, default=str),
                       stage="sow", generated_by="sow_factory")
    # The commercial stage consumes the pricing-input section of the SOW. Emitting
    # it as its own artifact is what lets that stage — and the deployment gate
    # behind it — actually complete.
    repo.save_artifact(
        project_id, "commercial",
        json.dumps({"commercial_inputs": sow["sections"]["commercial_inputs"],
                    "effort": sow["sections"]["effort"],
                    "roles": sow["sections"]["roles"],
                    "issuable": sow["issuable"],
                    "generation_mode": "deterministic_from_canonical_model"},
                   indent=2, default=str),
        stage="commercial", generated_by="commercial_factory")
    return sow


# ==========================================================================
# Evidence ingestion (§8, §9) and report generation (§29)
# ==========================================================================
from fastapi import File, UploadFile  # noqa: E402
from fastapi.responses import Response  # noqa: E402

from core import evidence as EV  # noqa: E402
from core.reports import REPORTS, available_reports, build_report  # noqa: E402


@router.post("/projects/{project_id}/evidence", status_code=201)
async def upload_evidence(project_id: str, file: UploadFile = File(...),
                          repo: R.Repository = Depends(get_repo)):
    """Ingest one document: extract, classify, hash, chunk (§8, §9)."""
    if not repo.get_project(project_id):
        raise HTTPException(404, "Project not found")
    data = await file.read()
    if not data:
        raise HTTPException(422, detail={"code": "EMPTY_FILE",
                                         "message": "The uploaded file is empty."})
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(413, detail={"code": "FILE_TOO_LARGE",
                                         "message": "Maximum upload size is 25 MB."})
    try:
        return EV.ingest(repo, project_id, file.filename or "upload", data,
                         file.content_type or "")
    except Exception as exc:  # noqa: BLE001 - surfaced rather than swallowed
        raise HTTPException(500, detail={"code": "INGEST_FAILED", "message": str(exc)[:300]})


@router.get("/projects/{project_id}/evidence")
def list_evidence(project_id: str, repo: R.Repository = Depends(get_repo)):
    try:
        items = repo.list_evidence(project_id)
    except KeyError:
        raise HTTPException(404, "Project not found")
    out = []
    for e in items:
        try:
            analysis = json.loads(e.analysis_json or "{}")
        except json.JSONDecodeError:
            analysis = {}
        out.append({
            "id": e.id, "name": e.name, "document_type": e.document_type,
            "confidence": analysis.get("confidence", ""), "sensitivity": e.sensitivity,
            "classification": e.classification, "size_bytes": e.size_bytes,
            "characters": len(e.extracted_text or ""), "chunks": analysis.get("chunks", 0),
            "status": e.status, "sha256": (e.sha256 or "")[:16],
            "created_at": e.created_at.isoformat() if e.created_at else None,
        })
    return {"items": out, "count": len(out)}


@router.get("/projects/{project_id}/reports")
def list_reports(project_id: str, repo: R.Repository = Depends(get_repo)):
    """Which PDF reports can be produced from what exists right now (§29)."""
    if not repo.get_project(project_id):
        raise HTTPException(404, "Project not found")
    kinds = {a.kind for a in repo.list_artifacts(project_id)}
    return {"items": available_reports(kinds)}


@router.get("/projects/{project_id}/reports/{kind}.pdf")
def download_report(project_id: str, kind: str, repo: R.Repository = Depends(get_repo)):
    """Render a stage report as a PDF from the current canonical state."""
    p = repo.get_project(project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    if kind not in REPORTS:
        raise HTTPException(404, detail={"code": "UNKNOWN_REPORT",
                                         "available": sorted(REPORTS)})

    artifacts: Dict[str, Any] = {}
    degraded: List[str] = []
    for name in REPORTS[kind]["artifacts"]:
        a = repo.latest_artifact(project_id, name)
        if not a:
            continue
        try:
            content = json.loads(a.content)
        except (json.JSONDecodeError, TypeError):
            content = a.content
        artifacts[name] = content
        if isinstance(content, dict) and content.get("generation_mode", "ai") != "ai":
            degraded.append(name)

    if not artifacts:
        raise HTTPException(409, detail={
            "code": "NOTHING_TO_REPORT",
            "message": f"No content exists for '{kind}' yet. Run the stage first."})

    statements = [{"ref": s.ref, "text": s.text, "provenance": s.provenance,
                   "kind": s.kind}
                  for s in repo.list_statements(project_id)
                  if not kind or s.stage in (kind, "") or True][:120]

    note = (f"Sections drawn from {', '.join(degraded)} were produced without AI "
            f"enrichment and contain evidence-only content.") if degraded else ""

    pdf = build_report(kind, {"name": p.name, "intent": p.intent, "domain": p.domain,
                              "version": p.version}, artifacts, statements, note)
    repo.audit("report.generated", "report", kind, project_id=project_id,
               after={"bytes": len(pdf)})
    filename = f"{p.name[:40].replace(' ', '_')}_{kind}.pdf"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
