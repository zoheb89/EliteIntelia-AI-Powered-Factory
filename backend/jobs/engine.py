"""Asynchronous, resumable job engine (spec §42, §43, §44).

Why this exists: a long workflow must never depend on one synchronous model
call. Each job is a sequence of independently retryable steps whose output is
checkpointed, so a failure resumes from the failed step instead of rerunning
discovery from scratch.

Storage is injected, so the same engine runs against SQLite locally and
Postgres in production, and can later be driven by an external queue without
changing callers.
"""
from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    CANCELLED = "CANCELLED"
    PARTIAL = "PARTIAL"        # some steps succeeded; resumable

    @property
    def is_terminal(self) -> bool:
        return self in (JobStatus.COMPLETED, JobStatus.FAILED,
                        JobStatus.CANCELLED, JobStatus.PARTIAL)


class StepStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"        # already completed in an earlier run


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StepResult:
    step: str
    status: StepStatus
    output: Any = None
    error: str = ""
    started_at: str = ""
    finished_at: str = ""
    elapsed_ms: int = 0
    attempts: int = 0

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["status"] = self.status.value
        # Outputs can be large; the job record keeps them, the trace does not.
        d["output"] = None if self.output is None else "<stored>"
        return d


@dataclass
class Step:
    """One resumable unit of work.

    `run(context) -> output`. The returned output is checkpointed and made
    available to later steps via `context[step.id]`.
    """

    id: str
    title: str
    run: Callable[[Dict[str, Any]], Any]
    retries: int = 1
    optional: bool = False     # a failure degrades the job to PARTIAL, not FAILED


@dataclass
class Job:
    id: str
    kind: str
    project_id: str
    tenant_id: str = ""
    status: JobStatus = JobStatus.QUEUED
    steps: List[str] = field(default_factory=list)
    results: Dict[str, StepResult] = field(default_factory=dict)
    current_step: str = ""
    message: str = ""
    error: str = ""
    created_at: str = field(default_factory=_now)
    started_at: str = ""
    finished_at: str = ""
    trace: List[dict] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)

    @property
    def completed_steps(self) -> int:
        return sum(1 for r in self.results.values() if r.status is StepStatus.COMPLETED)

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def elapsed_seconds(self) -> int:
        if not self.started_at:
            return 0
        end = datetime.fromisoformat(self.finished_at) if self.finished_at else datetime.now(timezone.utc)
        return max(0, int((end - datetime.fromisoformat(self.started_at)).total_seconds()))

    def to_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "project_id": self.project_id,
            "tenant_id": self.tenant_id, "status": self.status.value,
            "steps": self.steps, "current_step": self.current_step,
            "completed_steps": self.completed_steps, "total_steps": self.total_steps,
            "message": self.message, "error": self.error,
            "created_at": self.created_at, "started_at": self.started_at,
            "finished_at": self.finished_at, "elapsed_seconds": self.elapsed_seconds,
            "results": {k: v.to_dict() for k, v in self.results.items()},
            "trace": self.trace[-50:],
        }


class JobStore(Protocol):
    """Persistence contract. Implemented for SQLite/Postgres in persistence/."""

    def save(self, job: Job) -> None: ...
    def load(self, job_id: str) -> Optional[Job]: ...
    def list_for_project(self, project_id: str) -> List[Job]: ...


class InMemoryJobStore:
    """Default store. Adequate for a single process; swap for the DB store in prod."""

    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()

    def save(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.id] = job

    def load(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def list_for_project(self, project_id: str) -> List[Job]:
        return [j for j in self._jobs.values() if j.project_id == project_id]


class JobEngine:
    """Runs step sequences with checkpointing, retry and resume."""

    def __init__(self, store: Optional[JobStore] = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.store = store or InMemoryJobStore()
        self._sleep = sleep

    def create(self, kind: str, project_id: str, steps: List[Step],
               tenant_id: str = "", context: Optional[Dict[str, Any]] = None) -> Job:
        job = Job(id=str(uuid.uuid4()), kind=kind, project_id=project_id,
                  tenant_id=tenant_id, steps=[s.id for s in steps],
                  context=dict(context or {}))
        job.results = {s.id: StepResult(s.id, StepStatus.PENDING) for s in steps}
        self.store.save(job)
        return job

    def _emit(self, job: Job, step: str, status: str, message: str) -> None:
        job.trace.append({"timestamp": _now(), "step": step, "status": status, "message": message})
        job.message = message
        self.store.save(job)

    def run(self, job: Job, steps: List[Step], resume: bool = True) -> Job:
        """Execute the job. Already-completed steps are skipped when resuming."""
        job.status = JobStatus.RUNNING
        job.started_at = job.started_at or _now()
        job.error = ""
        self._emit(job, "", "running", f"{job.kind} started.")

        for step in steps:
            prior = job.results.get(step.id)
            if resume and prior and prior.status is StepStatus.COMPLETED:
                job.context[step.id] = prior.output
                self._emit(job, step.id, "success",
                           f"{step.title} already complete; using the persisted result.")
                continue

            job.current_step = step.id
            result = StepResult(step.id, StepStatus.RUNNING, started_at=_now())
            job.results[step.id] = result
            self._emit(job, step.id, "running", f"{step.title} is running.")

            attempts = max(1, step.retries)
            last_error = ""
            for attempt in range(1, attempts + 1):
                result.attempts = attempt
                t0 = time.monotonic()
                try:
                    output = step.run(job.context)
                    result.output = output
                    result.status = StepStatus.COMPLETED
                    result.elapsed_ms = int((time.monotonic() - t0) * 1000)
                    result.finished_at = _now()
                    job.context[step.id] = output
                    self._emit(job, step.id, "success", f"{step.title} complete.")
                    break
                except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
                    last_error = f"{type(exc).__name__}: {exc}"
                    result.elapsed_ms = int((time.monotonic() - t0) * 1000)
                    if attempt < attempts:
                        self._emit(job, step.id, "retrying",
                                   f"{step.title} failed (attempt {attempt}/{attempts}); retrying.")
                        self._sleep(min(2 ** (attempt - 1), 8))
                    else:
                        result.status = StepStatus.FAILED
                        result.error = last_error
                        result.finished_at = _now()
                        job.context.setdefault("_errors", []).append(
                            {"step": step.id, "error": last_error,
                             "traceback": traceback.format_exc()[-2000:]})

            if result.status is StepStatus.FAILED:
                if step.optional:
                    self._emit(job, step.id, "failed",
                               f"{step.title} failed but is optional; continuing.")
                    continue
                # Everything completed so far is kept, so the job can resume.
                job.status = JobStatus.PARTIAL if job.completed_steps else JobStatus.FAILED
                job.error = last_error
                job.finished_at = _now()
                self._emit(job, step.id, "failed",
                           f"{step.title} failed: {last_error}. "
                           f"Completed work is preserved; the job can be resumed.")
                return job

        job.status = JobStatus.COMPLETED
        job.current_step = ""
        job.finished_at = _now()
        self._emit(job, "", "success", f"{job.kind} completed.")
        return job

    def resume(self, job_id: str, steps: List[Step]) -> Job:
        job = self.store.load(job_id)
        if not job:
            raise KeyError(f"Job {job_id} not found.")
        if job.status is JobStatus.COMPLETED:
            return job
        return self.run(job, steps, resume=True)

    def cancel(self, job_id: str) -> Optional[Job]:
        job = self.store.load(job_id)
        if job and not job.status.is_terminal:
            job.status = JobStatus.CANCELLED
            job.finished_at = _now()
            self._emit(job, job.current_step, "cancelled", "Cancelled by request.")
        return job

    def submit(self, job: Job, steps: List[Step]) -> Job:
        """Run in a background thread and return immediately (spec §42)."""
        threading.Thread(target=self.run, args=(job, steps), daemon=True,
                         name=f"job-{job.id[:8]}").start()
        return job
