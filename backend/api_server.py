import io, json, os, sys, tempfile, threading, time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response, JSONResponse
from pydantic import BaseModel, Field
from fastapi.exceptions import RequestValidationError

from c_invent.services.config import load_settings
from c_invent.services.project_store import ProjectStore
from c_invent.services.document_intel import extract_upload
from c_invent.services.universal_intake import analyze_intake, build_intake_bundle
from c_invent.services.platforms import normalize_platform, derive_state, environment_fields, secret_status
from c_invent.agents.orchestrator import Orchestrator

APP_VERSION = "1.2.0-production-execution"
BACKEND_DIR = Path(__file__).resolve().parent
BASE = BACKEND_DIR.parent
os.chdir(BASE)
# os.chdir above moves the process to the repo root, and the implicit ""
# entry on sys.path resolves against the *current* directory. Pin the backend
# package root explicitly so core/, llm/, jobs/ and persistence/ stay importable.
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Storage durability is checked before anything opens the database: a SQLite file
# on ephemeral container storage looks healthy until the service restarts, at
# which point every engagement, artifact and approval is gone.
try:
    from core.durability import warn_at_startup as _warn_durability
    DURABILITY = _warn_durability()
except Exception as _dur_exc:  # noqa: BLE001 - never block startup
    DURABILITY = {"durable": None, "detail": f"Durability check unavailable: {_dur_exc}"}

settings = load_settings()
store = ProjectStore()
store.recover_stale_executions()
store.migrate_untitled_projects()
orch = Orchestrator(settings, store)

app = FastAPI(title="EliteInteliA Intelligence Factory API", version=APP_VERSION)
cors_raw = os.getenv("CORS_ORIGINS") or os.getenv("FRONTEND_ALLOWED_ORIGINS") or "*"
origins = [x.strip().rstrip("/") for x in cors_raw.split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------------------------------
# Authentication. Opt-in via AUTH_REQUIRED so existing deployments keep working
# while auth is rolled out; when enabled, every /api route needs a bearer token.
# --------------------------------------------------------------------------
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from c_invent.services.auth import (
    AuthError, UserStore, auth_required, issue_token, verify_token, require_role, ROLES,
)

users = UserStore()
_seeded = users.bootstrap_admin()
if _seeded:
    print(f"[auth] bootstrapped admin account: {_seeded}")

_bearer = HTTPBearer(auto_error=False)


def current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> dict:
    """Resolve the caller. When auth is disabled, act as a local admin."""
    if not auth_required():
        if creds and creds.credentials:
            try:
                return verify_token(creds.credentials)
            except AuthError:
                pass
        return {"sub": "local@dev", "role": "admin", "name": "Local", "anonymous": True}
    if not creds or not creds.credentials:
        raise HTTPException(401, detail={"code": "AUTH_REQUIRED", "message": "Sign in to continue."})
    try:
        return verify_token(creds.credentials)
    except AuthError as exc:
        raise HTTPException(401, detail={"code": "AUTH_INVALID", "message": str(exc)})


def editor(user: dict = Depends(current_user)) -> dict:
    """Guard for state-changing operations."""
    try:
        require_role(user, "editor")
    except AuthError as exc:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": str(exc)})
    return user


def admin(user: dict = Depends(current_user)) -> dict:
    try:
        require_role(user, "admin")
    except AuthError as exc:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": str(exc)})
    return user


def _json_safe(value):
    """Convert FastAPI/Pydantic validation details to JSON-safe primitives.

    FastAPI can include raw multipart bytes in a validation error's `input`
    field. Calling the default encoder on those bytes can raise a secondary
    UnicodeDecodeError and hide the real 422 response from the browser.
    """
    if isinstance(value, bytes):
        return f"<binary: {len(value)} bytes>"
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return a stable JSON 422 instead of failing while encoding bytes."""
    return JSONResponse(
        status_code=422,
        content={
            "status": "validation_error",
            "message": "The request could not be validated.",
            "path": request.url.path,
            "errors": _json_safe(exc.errors()),
        },
    )

AGENTS = [
    "discovery", "environment_assessment", "assessment", "blueprint", "metadata",
    "engineering", "qa", "application", "bi", "full_qa"
]
STAGES = [
    ("intake", "Intake"), ("discovery", "Discovery & Assess"),
    ("architecture", "Architecture"), ("platform", "Platform & Environment"),
    ("engineering", "Data & Engineering"), ("ai", "AI & Analytics"),
    ("validation", "Validation & QA"), ("deploy", "Deploy & Activate"),
]

class PlatformConfig(BaseModel):
    platform: str
    cloud: str = ""
    environment_mode: str = "existing"
    endpoint: str = ""
    credential_ref: str = ""
    auth_method: str = ""
    environment_name: str = ""
    region: str = ""
    decision_status: str = "selected"

class ApprovalRequest(BaseModel):
    comment: str = "Approved through EliteInteliA Intelligence Factory"

class DiscoveryRequest(BaseModel):
    prompt: str = Field(default="Analyze the supplied engagement evidence and identify the business intent, processes, actors, systems, sources, requirements, assumptions, unknowns and next steps.")
    context: str = ""

class TextIntake(BaseModel):
    name: str = "New Engagement"
    text: str = ""
    domain: str = ""


def project_or_404(pid: str):
    p = store.get_project(pid)
    if not p:
        raise HTTPException(404, "Engagement not found")
    return p


def run_summary(pid: str):
    runs = {}
    for agent in AGENTS:
        r = store.latest_run(pid, agent, success_only=False)
        if r:
            runs[agent] = {
                "id": r.get("id"), "status": r.get("status"),
                "created_at": r.get("created_at"), "output": r.get("output"),
            }
    return runs


def lifecycle(pid: str):
    p = store.get_project(pid)
    runs = run_summary(pid)
    discovery = store.latest_run(pid, "discovery", success_only=True)
    environment = store.latest_run(pid, "environment_assessment", success_only=True)
    assessment = store.latest_run(pid, "assessment", success_only=True)
    blueprint = store.latest_run(pid, "blueprint", success_only=True)
    approval = store.latest_approval(pid, "blueprint")
    blueprint_current = bool(
        blueprint and discovery and environment and assessment
        and blueprint.get("created_at", "") >= assessment.get("created_at", "")
        and assessment.get("created_at", "") >= environment.get("created_at", "")
        and environment.get("created_at", "") >= discovery.get("created_at", "")
    )
    approval_current = bool(approval and blueprint and approval.get("created_at", "") >= blueprint.get("created_at", ""))
    approvals = {"blueprint": approval_current}
    blueprint_success = blueprint_current
    stage_done = {
        "intake": bool(store.artifact_exists(pid, "intake_pack")),
        "discovery": runs.get("discovery", {}).get("status") == "success",
        # Architecture is complete only when the current Discovery → Environment →
        # Current-State → Blueprint chain has completed.
        "architecture": blueprint_success,
        "platform": derive_state(p.get("platform_config") or {}).get("state") == "VERIFIED",
        "engineering": runs.get("engineering", {}).get("status") == "success",
        "ai": any(runs.get(k, {}).get("status") == "success" for k in ("bi", "application")),
        "validation": any(runs.get(k, {}).get("status") == "success" for k in ("qa", "full_qa")),
        "deploy": False,
    }
    progress = sum(stage_done.values())
    gates = {
        "blueprint_approval": "APPROVED" if approvals["blueprint"] else ("REQUIRED" if blueprint_success else "NOT_READY"),
        "engineering_ready": bool(blueprint_success and approvals["blueprint"]),
        "platform_ready": derive_state(p.get("platform_config") or {}).get("state") == "VERIFIED",
        "metadata_ready": runs.get("metadata", {}).get("status") == "success",
    }
    active_execution = store.active_execution(pid)
    latest_execution = store.latest_execution(pid)
    return {"stages": stage_done, "progress": progress, "total": len(STAGES), "runs": runs, "approvals": approvals, "gates": gates,
            "active_execution": active_execution, "latest_execution": latest_execution}

@app.get("/health")
def health():
    return {
        "status": "ok",
        "product": "EliteInteliA Intelligence Factory",
        "version": APP_VERSION,
        # Surfaced so the UI can warn before data is silently lost.
        "storage": DURABILITY,
    }

@app.get("/api/engagements")
def engagements():
    out = []
    for p in store.list_projects():
        state = lifecycle(p["id"])
        stage = next((label for key, label in STAGES if not state["stages"].get(key)), "Completed")
        out.append({
            "id": p["id"], "title": p.get("name") or "New Engagement", "customer": p.get("name") or "Customer",
            "source": p.get("source") or "Notes", "domain": p.get("domain") or "Unknown", "description": p.get("description") or "",
            "stage": stage, "progress": state["progress"], "total": state["total"],
            "status": "Completed" if state["progress"] == state["total"] else ("Active" if state["progress"] > 1 else "Intake"),
            "date": (p.get("updated_at") or "")[:10], "platform_state": derive_state(p.get("platform_config") or {}),
        })
    return {"items": out}

@app.get("/api/engagements/{pid}")
def engagement(pid: str):
    p = project_or_404(pid)
    state = lifecycle(pid)
    docs = store.documents(pid)
    artifacts = store.artifacts(pid)
    return {
        "project": {**p, "platform_config": p.get("platform_config") or {}},
        "lifecycle": state,
        "documents": [{k: d.get(k) for k in ("id","name","mime_type","size_bytes","created_at","metadata_json")} for d in docs],
        "artifacts": [{k: a.get(k) for k in ("id","kind","name","language","created_at")} for a in artifacts],
    }

def _readable_engagement_name(raw: str) -> str:
    """Turn an uploaded filename into a human engagement title.

    Clients fall back to the raw filename when the user does not type a name,
    which produced titles like
    "RFP_-_Databricks_Platform_-_11-06-2026.pdf_report (1).pdf".
    """
    import re

    value = (raw or "").strip()
    if not value:
        return "New Engagement"

    # Drop repeated/trailing extensions. `\b` cannot be used because "_" is a word
    # character, so ".pdf_report" would not match.
    value = re.sub(r"\.(pdf|docx?|xlsx?|pptx?|txt|eml|msg|csv|json)(?![a-z0-9])", " ", value, flags=re.I)
    # Drop duplicate-download markers "(1)" and export suffixes.
    value = re.sub(r"\(\s*\d+\s*\)", " ", value)
    value = re.sub(r"(?:^|[\s_-])report(?![a-z0-9])", " ", value, flags=re.I)
    # Separators -> spaces. Dashes are only spaced when they already separate
    # words, so dates such as 11-06-2026 stay intact.
    value = value.replace("_", " ").replace("+", " ")
    value = re.sub(r"\s+-\s*|\s*-\s+", " - ", value)
    value = re.sub(r"\s+", " ", value).strip(" -\t")

    return value or "New Engagement"


@app.post("/api/intake")
async def intake(name: str = Form("New Engagement"), text: str = Form(""), domain: str = Form(""), file: Optional[UploadFile] = File(None), _: dict = Depends(editor)):
    docs = []
    if file:
        raw = await file.read()
        class UploadShim:
            def __init__(self, name, data): self.name, self._data = name, data
            def getvalue(self): return self._data
        extracted, meta = extract_upload(UploadShim(file.filename or "upload", raw))
        docs.append({"name": file.filename or "upload", "text": extracted, "mime_type": file.content_type or "application/octet-stream", "size_bytes": len(raw), "metadata": meta})
    analysis = analyze_intake(text, docs)
    detected_domain = (analysis.get("domain_signals") or [{}])[0].get("domain", domain or "")
    name = _readable_engagement_name(name)
    pid = store.create_project(name=name, domain=domain or detected_domain, description=text, source=analysis.get("document_type_summary", {}) and max(analysis["document_type_summary"], key=analysis["document_type_summary"].get) or "notes")
    for d in docs:
        store.save_document(pid, d["name"], d["mime_type"], d["size_bytes"], d["text"], d["metadata"])
    pack = orch.capture_intake(pid)
    store.save_artifact(pid, "intake_analysis", "intake_analysis.json", "json", json.dumps(analysis, indent=2, ensure_ascii=False))
    summary_types = analysis.get("document_type_summary") or {"notes": 1}
    return {"engagement_id": pid, "name": name, "document_type": max(summary_types, key=summary_types.get), "status": "Intake captured", "analysis": analysis, "extracted_summary": analysis.get("recommended_next_step"), "lifecycle": lifecycle(pid)}

@app.post("/api/engagements/{pid}/intake-pack")
def intake_pack(pid: str):
    project_or_404(pid)
    return orch.capture_intake(pid)

@app.post("/api/engagements/{pid}/discovery")
def discovery(pid: str, req: DiscoveryRequest):
    p = project_or_404(pid)
    return orch.run_discovery(pid, req.prompt or p.get("description", ""), req.context)

def _has_error(result):
    return isinstance(result, dict) and bool(result.get("error"))


def _execute_stage_background(pid: str, stage: str, execution_id: str, request: DiscoveryRequest):
    """Run a stage outside the HTTP request so the UI can observe real progress.

    The execution record is the source of truth for live status. Individual agent
    runs remain the durable stage outputs used by lifecycle gates.
    """
    def event(status, step, message, completed=None, total=None, error=None, phase=None,
              execution_status=None, finish=None):
        # `status` describes the individual trace event. `execution_status` is the
        # status of the whole persisted execution. They must be independent: a
        # completed child step must NOT mark the three-step pipeline complete.
        trace = {"step": step, "status": status, "message": message}
        if phase:
            trace["phase"] = phase
        store.update_execution(
            execution_id,
            status=execution_status or (status if status in {"failed", "blocked", "cancelled"} else "running"),
            current_step=step,
            completed_steps=completed,
            message=message,
            trace_event=trace,
            error=error,
            finished=finish if finish is not None else (execution_status in {"success", "failed", "blocked", "cancelled"}),
        )

    def observed(step, title, action, completed, total):
        """Execute a potentially slow provider call while persisting visible heartbeats.

        The UI must never look frozen simply because the LLM/provider is still
        working. Heartbeats are telemetry only; they never fabricate completion.
        """
        stop = threading.Event()
        started = time.monotonic()

        def heartbeat():
            while not stop.wait(4.0):
                elapsed = int(time.monotonic() - started)
                event(
                    "running", step,
                    f"{title} is still running — provider analysis in progress ({elapsed}s elapsed).",
                    completed, total, phase="heartbeat"
                )

        thread = threading.Thread(target=heartbeat, name=f"execution-heartbeat-{execution_id[:8]}", daemon=True)
        thread.start()
        try:
            return action()
        finally:
            stop.set()
            thread.join(timeout=0.25)

    try:
        total = 3 if stage in {"architecture", "blueprint"} else (2 if stage == "engineering" else 1)
        event("running", stage, "Execution started", 0, total)

        if stage == "architecture":
            steps = [
                ("environment_assessment", "Environment Assessment", "Evaluating customer platform, environment and access evidence.", lambda: orch.run_environment_assessment(pid)),
                ("assessment", "Current-State Assessment", "Building evidence-based readiness, maturity, risks, dependencies and unknowns.", lambda: orch.run_assessment(pid)),
                ("blueprint", "Solution Blueprint", "Generating target architecture, platform fit, data flow, security and operating model.", lambda: orch.run_blueprint(pid)),
            ]
            completed = 0
            discovery = store.latest_run(pid, "discovery", success_only=True)
            previous = discovery
            for key, title, working, action in steps:
                existing = store.latest_run(pid, key, success_only=True)
                fresh = bool(existing and (not previous or existing.get("created_at", "") >= previous.get("created_at", "")))
                if fresh:
                    completed += 1
                    event("success", key, f"{title} already complete; using persisted result.", completed, total, execution_status="running")
                    previous = existing
                    continue
                event("running", key, working, completed, total)
                result = observed(key, title, action, completed, total)
                if _has_error(result):
                    code = "ENVIRONMENT_ASSESSMENT_FAILED" if key == "environment_assessment" else ("ASSESSMENT_FAILED" if key == "assessment" else "BLUEPRINT_FAILED")
                    message = result.get("error") or f"{title} failed."
                    event("failed", key, message, completed, total, {"code": code, "message": message})
                    return
                completed += 1
                existing = store.latest_run(pid, key, success_only=True)
                previous = existing or previous
                event("success", key, f"{title} complete.", completed, total, execution_status="running")
            event("success", "blueprint", "Architecture analysis completed: Environment Assessment → Current-State Assessment → Solution Blueprint.", completed, total, execution_status="success", finish=True)
            return

        if stage == "engineering":
            # Engineering is itself a controlled two-step delivery pipeline. Once the
            # Blueprint is approved and the customer platform is verified, metadata
            # is generated automatically before Bronze/Silver/Gold generation.
            metadata = store.latest_run(pid, "metadata", success_only=True)
            blueprint = store.latest_run(pid, "blueprint", success_only=True)
            approved = bool(blueprint and store.latest_approval(pid, "blueprint") and store.latest_approval(pid, "blueprint").get("created_at", "") >= blueprint.get("created_at", ""))
            if not blueprint or not approved:
                message = "Engineering requires an approved current Solution Blueprint."
                event("blocked", "metadata", message, 0, 2, {"code": "BLUEPRINT_APPROVAL_REQUIRED", "message": message})
                return
            if not metadata or metadata.get("created_at", "") < blueprint.get("created_at", ""):
                event("running", "metadata", "Generating canonical engineering metadata from the approved Blueprint.", 0, 2)
                result = observed("metadata", "Engineering Metadata", lambda: orch.run_metadata(pid), 0, 2)
                if _has_error(result):
                    message = result.get("error") or "Metadata generation failed."
                    blocked = any(token in message.lower() for token in ("requires", "must", "before", "approval"))
                    event("blocked" if blocked else "failed", "metadata", message, 0, 2, {"code": "METADATA_GATE" if blocked else "METADATA_FAILED", "message": message})
                    return
                event("success", "metadata", "Engineering metadata generated.", 1, 2, execution_status="running")
            else:
                event("running", "metadata", "Using current persisted engineering metadata.", 1, 2)
            event("running", "engineering", "Generating resumable Bronze/Silver/Gold and data-quality components.", 1, 2)
            result = observed("engineering", "Data Engineering", lambda: orch.run_engineering(pid), 1, 2)
            if _has_error(result):
                message = result.get("error") or "Engineering generation failed."
                blocked = any(token in message.lower() for token in ("requires", "must", "before", "not selected", "not verified", "approval"))
                event("blocked" if blocked else "failed", "engineering", message, 1, 2, {"code": "ENGINEERING_GATE" if blocked else "ENGINEERING_FAILED", "message": message})
                return
            event("success", "engineering", result.get("summary") if isinstance(result, dict) else "Engineering completed.", 2, 2, execution_status="success", finish=True)
            return

        actions = {
            "discovery": ("Discovery & Assessment", lambda: orch.run_discovery(pid, request.prompt or store.get_project(pid).get("description", ""), request.context or "")),
            "platform": ("Environment Assessment", lambda: orch.run_environment_assessment(pid)),
            "environment_assessment": ("Environment Assessment", lambda: orch.run_environment_assessment(pid)),
            "assessment": ("Current-State Assessment", lambda: orch.run_assessment(pid)),
            "blueprint": ("Solution Blueprint", lambda: orch.run_blueprint(pid)),
            "metadata": ("Engineering Metadata", lambda: orch.run_metadata(pid)),
            "engineering": ("Data Engineering", lambda: orch.run_engineering(pid)),
            "qa": ("Validation & QA", lambda: orch.run_qa(pid)),
            "application": ("Application Architecture", lambda: orch.run_application_architecture(pid)),
            "bi": ("AI & Analytics", lambda: orch.run_bi(pid)),
            "full_qa": ("Full Validation", lambda: orch.run_full_qa(pid)),
            "validation": ("POC Validation Pack", lambda: orch.run_poc_validation_pack(pid)),
        }
        if stage not in actions:
            event("failed", stage, f"Unsupported stage: {stage}", 0, total, {"code": "UNSUPPORTED_STAGE", "message": f"Unsupported stage: {stage}"})
            return
        title, action = actions[stage]
        event("running", stage, f"{title} is running.", 0, total)
        result = observed(stage, title, action, 0, total)
        if _has_error(result):
            # Lifecycle dependency failures are BLOCKED; execution/runtime failures are FAILED.
            message = result.get("error") or f"{title} failed."
            blocked = any(token in message.lower() for token in ("requires", "must", "before", "not ready", "not selected", "not verified", "approval"))
            status = "blocked" if blocked else "failed"
            event(status, stage, message, 0, total, {"code": "STAGE_EXECUTION_BLOCKED" if blocked else "STAGE_EXECUTION_FAILED", "stage": stage, "message": message})
            return
        # A result dict without a "summary" key previously yielded a None message,
        # which produced an empty trace event and left the stale "… is running."
        # text as the final status. Always fall back to a real completion message.
        summary = result.get("summary") if isinstance(result, dict) else None
        if not isinstance(summary, str) or not summary.strip():
            summary = f"{title} completed."
        event("success", stage, summary, total, total, execution_status="success", finish=True)
    except Exception as exc:
        message = str(exc)
        event("failed", stage, message, 0, 3 if stage in {"architecture", "blueprint"} else (2 if stage == "engineering" else 1), {"code": "UNHANDLED_EXECUTION_ERROR", "stage": stage, "message": message})


@app.post("/api/engagements/{pid}/stages/{stage}", status_code=202)
def stage(pid: str, stage: str, background_tasks: BackgroundTasks, req: Optional[DiscoveryRequest] = None, _: dict = Depends(editor)):
    """Queue a controlled stage execution and return immediately.

    Long-running LLM/platform operations never execute on the HTTP event loop.
    Clients receive an execution id and poll the persisted execution record.
    """
    project_or_404(pid)
    request = req or DiscoveryRequest()
    supported = {"discovery", "architecture", "platform", "environment_assessment", "assessment", "blueprint", "metadata", "engineering", "qa", "application", "bi", "full_qa", "validation"}
    if stage not in supported:
        raise HTTPException(400, detail={"code": "UNSUPPORTED_STAGE", "stage": stage, "supported_stages": sorted(supported)})

    active = store.active_execution(pid, stage if stage != "blueprint" else "architecture")
    if active:
        return {"status": "ALREADY_RUNNING", "execution_id": active["id"], "execution": active, "lifecycle": lifecycle(pid)}

    # Architecture completion exposes the downstream gate: "next_stage": "platform".
    # Architecture is the controlled three-step pipeline. Direct blueprint execution
    # remains available only as an internal/retry action, but the UI uses architecture.
    total = 3 if stage == "architecture" else (2 if stage == "engineering" else 1)
    execution_id = store.create_execution(pid, "architecture" if stage == "blueprint" else stage, total, "Queued")
    background_tasks.add_task(_execute_stage_background, pid, stage, execution_id, request)
    execution = store.get_execution(execution_id)
    return {
        "status": "QUEUED",
        "execution_id": execution_id,
        "execution": execution,
        "lifecycle": lifecycle(pid),
        "poll_after_ms": 800,
    }


@app.get("/api/engagements/{pid}/executions")
def executions(pid: str):
    project_or_404(pid)
    return {"items": store.executions(pid)}


@app.get("/api/engagements/{pid}/executions/{execution_id}")
def execution(pid: str, execution_id: str):
    project_or_404(pid)
    item = store.get_execution(execution_id)
    if not item or item.get("project_id") != pid:
        raise HTTPException(404, "Execution not found")
    return {"execution": item, "execution_trace": item.get("trace", []), "lifecycle": lifecycle(pid)}


@app.post("/api/engagements/{pid}/approvals/{artifact_type}")
def approve(pid: str, artifact_type: str, req: ApprovalRequest, _: dict = Depends(editor)):
    project_or_404(pid)
    store.add_approval(pid, artifact_type, req.comment)
    return {"status": "APPROVED", "artifact_type": artifact_type, "lifecycle": lifecycle(pid)}

@app.post("/api/engagements/{pid}/platform")
def save_platform(pid: str, cfg: PlatformConfig, _: dict = Depends(editor)):
    project = project_or_404(pid)
    payload = cfg.model_dump()
    payload["platform"] = normalize_platform(payload["platform"])
    store.save_platform_config(pid, payload)
    return {"platform_config": store.get_platform_config(pid), "state": derive_state(payload)}

@app.post("/api/engagements/{pid}/platform/plan")
def platform_plan(pid: str):
    project_or_404(pid)
    return orch.generate_platform_plan(pid)

@app.post("/api/engagements/{pid}/platform/verify")
def platform_verify(pid: str):
    project = project_or_404(pid)
    result = orch.run_environment_assessment(pid)
    return {"result": result, "platform_config": store.get_platform_config(pid), "state": derive_state(store.get_platform_config(pid))}

@app.get("/api/engagements/{pid}/runs")
def runs(pid: str):
    project_or_404(pid)
    return run_summary(pid)

@app.get("/api/engagements/{pid}/artifacts")
def artifacts(pid: str):
    project_or_404(pid)
    return {"items": store.artifacts(pid)}

@app.get("/api/engagements/{pid}/artifacts/{kind}")
def artifact_detail(pid: str, kind: str):
    project_or_404(pid)
    item = store.latest_artifact(pid, kind)
    if not item:
        raise HTTPException(404, "Artifact not found")
    content = item.get("content") or ""
    try:
        content = json.loads(content)
    except Exception:
        pass
    return {"artifact": {**{k: item.get(k) for k in ("id","kind","name","language","created_at")}, "content": content}}

@app.get("/api/engagements/{pid}/download/intake.zip")
def download_intake(pid: str):
    project = project_or_404(pid)
    docs = store.documents(pid)
    analysis_run = store.latest_run(pid, "discovery", success_only=False)
    analysis = analysis_run.get("output") if analysis_run else analyze_intake(project.get("description", ""), docs)
    data = build_intake_bundle(analysis, [{"name": d["name"], "text": d.get("text", "")} for d in docs])
    return StreamingResponse(io.BytesIO(data), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{project.get("name","engagement").replace(" ","_")}_intake_pack.zip"'})

@app.get("/api/engagements/{pid}/report.pdf")
def report_pdf(pid: str):
    project = project_or_404(pid)
    state = lifecycle(pid)
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=42, leftMargin=42, topMargin=42, bottomMargin=42)
        styles = getSampleStyleSheet()
        story = [Paragraph("EliteInteliA Intelligence Factory", styles["Title"]), Paragraph(project.get("name", "Engagement"), styles["Heading1"]), Spacer(1, 10)]
        story.append(Paragraph(project.get("description") or "No customer intent supplied.", styles["BodyText"]))
        story.append(Spacer(1, 16))
        rows = [["Lifecycle stage", "Status"]] + [[label, "Complete" if state["stages"].get(key) else "Pending"] for key, label in STAGES]
        table = Table(rows, colWidths=[320, 130])
        table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0d1829")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#d8e1eb")), ("PADDING", (0,0), (-1,-1), 7)]))
        story += [table, Spacer(1, 16), Paragraph("Evidence and AI outputs remain subject to customer validation and lifecycle gates. Platform direction is not treated as provisioned customer evidence until verification succeeds.", styles["BodyText"])]
        doc.build(story)
        buf.seek(0)
        return Response(content=buf.getvalue(), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{project.get("name","engagement").replace(" ","_")}_report.pdf"'})
    except Exception as exc:
        raise HTTPException(500, f"PDF generation failed: {exc}")

# --------------------------------------------------------------------------
# Auth endpoints
# --------------------------------------------------------------------------
class LoginRequest(BaseModel):
    email: str
    password: str


class CreateUserRequest(BaseModel):
    email: str
    password: str
    name: str = ""
    role: str = "viewer"


class RoleRequest(BaseModel):
    role: str


@app.get("/api/auth/config")
def auth_config():
    """Lets the frontend know whether to show the sign-in gate."""
    return {"auth_required": auth_required(), "roles": list(ROLES), "users": users.count()}


@app.post("/api/auth/login")
def login(req: LoginRequest):
    try:
        user = users.authenticate(req.email, req.password)
    except AuthError as exc:
        raise HTTPException(401, detail={"code": "AUTH_FAILED", "message": str(exc)})
    return {"token": issue_token(user["email"], user["role"], user["name"]), "user": user}


@app.get("/api/auth/me")
def me(user: dict = Depends(current_user)):
    return {"user": {"email": user.get("sub"), "role": user.get("role"), "name": user.get("name")},
            "auth_required": auth_required()}


@app.get("/api/auth/users")
def list_users(_: dict = Depends(admin)):
    return {"items": users.list_users()}


@app.post("/api/auth/users", status_code=201)
def create_user(req: CreateUserRequest, _: dict = Depends(admin)):
    try:
        return {"user": users.create(req.email, req.password, req.name, req.role)}
    except AuthError as exc:
        raise HTTPException(400, detail={"code": "USER_CREATE_FAILED", "message": str(exc)})


@app.put("/api/auth/users/{email}/role")
def update_role(email: str, req: RoleRequest, _: dict = Depends(admin)):
    try:
        users.set_role(email, req.role)
    except AuthError as exc:
        raise HTTPException(400, detail={"code": "ROLE_UPDATE_FAILED", "message": str(exc)})
    return {"updated": True, "email": email, "role": req.role}


@app.delete("/api/auth/users/{email}")
def delete_user(email: str, user: dict = Depends(admin)):
    if email.lower().strip() == (user.get("sub") or "").lower():
        raise HTTPException(400, detail={"code": "SELF_DELETE", "message": "You cannot delete your own account."})
    users.delete(email)
    return {"deleted": True, "email": email}


# --------------------------------------------------------------------------
# Core v2 API: canonical model, lifecycle, provenance, provider-neutral LLM
# gateway and jobs (spec §63). Mounted alongside the existing routes so the
# deployed application keeps working while the core is adopted incrementally.
# --------------------------------------------------------------------------
try:
    from persistence.repository import init_db as _init_core_db
    from core.api_v2 import router as core_router

    _init_core_db()
    app.include_router(core_router)
except Exception as _core_exc:  # noqa: BLE001 - core must never break the live API
    print(f"[core] v2 API not mounted: {_core_exc}")


# --------------------------------------------------------------------------
# AI provider diagnostics.
#
# The Delivery stages call `orch.llm`, so a test that exercises anything else
# proves nothing. These endpoints test that exact client and report the
# provider's own message on failure, which is what distinguishes a quota block
# from a bad key or an unreachable endpoint.
# --------------------------------------------------------------------------
def _ai_configuration() -> dict:
    """Redacted view of what the delivery stages will actually use."""
    from c_invent.llm.gateway_bridge import multi_provider_configured

    multi = multi_provider_configured()
    cfg = {
        "client": type(orch.llm).__name__,
        "multi_provider": multi,
        "endpoint": settings.llm_base_url or "",
        "model": settings.llm_model or "",
        "provider": settings.llm_provider or "",
        "auth_header": settings.llm_auth_header or "",
        "api_key_present": bool(settings.llm_api_key),
        "timeout_seconds": settings.llm_timeout_seconds,
    }
    if multi:
        try:
            cfg["providers"] = orch.llm.describe()
        except Exception:
            cfg["providers"] = []
    return cfg


@app.get("/api/ai/status")
def ai_status():
    """What is configured, without spending a call."""
    cfg = _ai_configuration()
    if not cfg["endpoint"] and not cfg.get("providers"):
        cfg["configured"] = False
        cfg["message"] = ("No AI endpoint is configured. Set ELITEINTELIA_LLM_BASE_URL and "
                          "ELITEINTELIA_LLM_API_KEY, or declare LLM_PROVIDERS.")
    elif not cfg["api_key_present"] and not cfg.get("providers"):
        cfg["configured"] = False
        cfg["message"] = "An endpoint is set but no API key is present."
    else:
        cfg["configured"] = True
        cfg["message"] = "Configured. Run a test to confirm the provider answers."
    return cfg


@app.post("/api/ai/test")
def ai_test():
    """Send one real request through the client the delivery stages use.

    Deliberately tiny: it costs a single call, which matters when the failure
    being diagnosed is a quota limit.
    """
    from c_invent.llm.capgemini import CapgeminiLLMFormatError, CapgeminiLLMQuotaError

    cfg = _ai_configuration()
    started = time.monotonic()
    try:
        result = orch.llm.invoke(
            "Reply with exactly: ELITEINTELIA TEST SUCCESS",
            "You are a connectivity test assistant. Follow the instruction exactly.",
            extra_params={"maxTokens": 40, "temperature": 0.0, "streaming": False},
        )
        content = (result.get("content") or "").strip()
        return {
            "ok": True,
            "reachable": True,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "provider": result.get("provider") or cfg["provider"],
            "model": result.get("model") or cfg["model"],
            "response_preview": content[:200],
            "message": "The AI provider answered. Delivery stages will use AI generation.",
            "configuration": cfg,
        }
    except CapgeminiLLMQuotaError as exc:
        return {
            "ok": False, "reachable": True, "fault": "quota",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "message": str(exc)[:500],
            "remedy": ("The endpoint and credentials work, but the provider refused this "
                       "request. Raise the plan/quota, or declare a second provider via "
                       "LLM_PROVIDERS so delivery stages fail over instead of degrading."),
            "configuration": cfg,
        }
    except CapgeminiLLMFormatError as exc:
        return {
            "ok": False, "reachable": True, "fault": "format",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "message": str(exc)[:500],
            "remedy": "The provider answered but not in a usable form. Check the model name.",
            "configuration": cfg,
        }
    except Exception as exc:  # noqa: BLE001 - the operator needs the real reason
        text = str(exc)
        fault = ("auth" if "401" in text or "authentication" in text.lower()
                 else "timeout" if "timed out" in text.lower() or "504" in text
                 else "unreachable")
        remedy = {
            "auth": "Authentication was rejected. Check the API key and auth header.",
            "timeout": "The endpoint accepted the request but did not answer in time.",
            "unreachable": "The endpoint could not be reached. Check the base URL and network egress.",
        }[fault]
        return {
            "ok": False, "reachable": fault != "unreachable", "fault": fault,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "message": text[:500], "remedy": remedy, "configuration": cfg,
        }


@app.get("/api/catalog/platforms")
def platforms():
    from c_invent.services.platforms import PLATFORM_CATALOG
    return {"items": PLATFORM_CATALOG, "environment_fields": {k: environment_fields(k) for k in ("existing", "provision")}}


# --------------------------------------------------------------------------
# Transformation Studio: visual pipeline -> dbt models + PySpark + lineage.
# The DAG is the source of truth; code is always regenerated from it so the
# canvas and the emitted code cannot drift apart.
# --------------------------------------------------------------------------
class PipelinePayload(BaseModel):
    name: str = "pipeline"
    nodes: list = Field(default_factory=list)
    edges: list = Field(default_factory=list)


@app.get("/api/studio/palette")
def studio_palette():
    from c_invent.services.pipeline_compiler import (
        NODE_TYPES, MATERIALIZATIONS, LAYERS, COLUMN_TESTS, starter_pipeline,
    )
    return {
        "node_types": NODE_TYPES,
        "materializations": MATERIALIZATIONS,
        "layers": LAYERS,
        "column_tests": COLUMN_TESTS,
        "starter": starter_pipeline(),
    }


@app.post("/api/studio/compile")
def studio_compile(payload: PipelinePayload):
    """Stateless compile so the canvas can preview code without an engagement."""
    from c_invent.services.pipeline_compiler import compile_pipeline
    return compile_pipeline(payload.model_dump())


class PipelineRunPayload(PipelinePayload):
    engine: str = "sandbox"


@app.post("/api/studio/run")
def studio_run(payload: PipelineRunPayload):
    """Execute the pipeline and return per-model row counts, samples and tests.

    The default `sandbox` engine runs the generated SQL against an in-memory
    database seeded with synthetic rows, so logic can be validated with no
    customer credentials. Results are always labelled with the engine used.
    """
    from c_invent.services.pipeline_runner import run_pipeline
    data = payload.model_dump()
    engine = data.pop("engine", "sandbox")
    return run_pipeline(data, engine=engine, settings=settings, store=store)


@app.post("/api/engagements/{pid}/pipeline/run")
def run_engagement_pipeline(pid: str, payload: PipelineRunPayload, _: dict = Depends(editor)):
    project_or_404(pid)
    from c_invent.services.pipeline_runner import run_pipeline
    data = payload.model_dump()
    engine = data.pop("engine", "sandbox")
    result = run_pipeline(data, engine=engine, settings=settings, store=store)
    store.save_artifact(pid, "pipeline_run", "pipeline_run.json", "json",
                        json.dumps(result, indent=2, ensure_ascii=False, default=str))
    store.add_audit(pid, f"studio:run:{engine}",
                    "success" if result.get("ok") else "failed",
                    json.dumps({"engine": engine, "ok": result.get("ok")})[:1000])
    return result


@app.get("/api/engagements/{pid}/pipeline")
def get_pipeline(pid: str):
    project_or_404(pid)
    from c_invent.services.pipeline_compiler import starter_pipeline
    item = store.latest_artifact(pid, "pipeline")
    if not item:
        return {"pipeline": starter_pipeline(), "persisted": False}
    try:
        return {"pipeline": json.loads(item.get("content") or "{}"), "persisted": True}
    except Exception:
        return {"pipeline": starter_pipeline(), "persisted": False}


@app.post("/api/engagements/{pid}/pipeline")
def save_pipeline(pid: str, payload: PipelinePayload, _: dict = Depends(editor)):
    """Persist the DAG and its generated code as governed artifacts."""
    project_or_404(pid)
    from c_invent.services.pipeline_compiler import compile_pipeline

    pipeline = payload.model_dump()
    compiled = compile_pipeline(pipeline)

    store.save_artifact(pid, "pipeline", "pipeline.json", "json",
                        json.dumps(pipeline, indent=2, ensure_ascii=False))
    if compiled.get("ok"):
        bundle = {
            "project": compiled.get("project"),
            "order": compiled.get("order"),
            "models": compiled.get("models"),
            "schema_yml": compiled.get("schema_yml"),
            "pyspark": compiled.get("pyspark"),
            "stats": compiled.get("stats"),
        }
        store.save_artifact(pid, "dbt_project", "dbt_project.json", "json",
                            json.dumps(bundle, indent=2, ensure_ascii=False))
        store.save_artifact(pid, "pyspark_job", "pipeline_job.py", "python",
                            compiled.get("pyspark") or "")
        store.save_artifact(pid, "column_lineage", "column_lineage.json", "json",
                            json.dumps(compiled.get("lineage") or [], indent=2))
        store.add_audit(pid, "studio:pipeline_saved", "success",
                        json.dumps(compiled.get("stats") or {})[:2000])
    return {"saved": True, "compiled": compiled}
