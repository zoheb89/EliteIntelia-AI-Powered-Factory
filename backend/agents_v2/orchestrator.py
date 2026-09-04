"""Agent orchestrator (spec §36).

    User -> Intent Router -> Orchestrator -> Agent -> Tools
         -> Canonical Project Model -> Artifact Generator -> Approval

The orchestrator owns everything an individual agent must not: gate checking,
persistence, provenance-safe writes, versioning, audit and the AI-run record.
Agents stay pure — they propose, the orchestrator commits.

Every agent execution runs as a resumable job (§42-§44), so a provider failure
never costs completed work.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Type

from agents_v2.base import AgentOutput, BaseAgent
from agents_v2.evidence import EvidenceAgent
from agents_v2.architecture import ArchitectureAgent, PlatformSelectionAgent
from agents_v2.design import (
    AIDesignAgent, ApplicationDesignAgent, BIDesignAgent, DataDesignAgent,
    EngineeringAgent, GovernanceAgent, HandoverAgent, OperationsAgent, QAAgent,
)
from agents_v2.discovery import (
    AssessmentAgent, DiscoveryAgent, QuestionSetAgent, RequirementsAgent,
)
from core.domain.lifecycle import STAGE_BY_ID, Approval, LifecycleState, StageStatus
from core.tools.registry import build_project_tools
from jobs.engine import Job, JobEngine, Step
from llm.gateway.gateway import LLMGateway

#: Agent registry. Adding an agent is a one-line change here.
AGENTS: Dict[str, Type[BaseAgent]] = {
    a.id: a for a in (
        EvidenceAgent,
        DiscoveryAgent, QuestionSetAgent, AssessmentAgent, RequirementsAgent,
        PlatformSelectionAgent, ArchitectureAgent,
        DataDesignAgent, AIDesignAgent, BIDesignAgent, ApplicationDesignAgent,
        GovernanceAgent, EngineeringAgent, QAAgent, OperationsAgent, HandoverAgent,
    )
}


#: Stages produced by deterministic engines rather than an LLM agent.
#: Estimation, SOW and commercial output must be reproducible and defensible,
#: so they are computed from the canonical model, not generated (§25, §26, §27).
ENGINE_STAGES: Dict[str, str] = {
    "estimation": "POST /api/v2/projects/{id}/estimate",
    "sow": "GET /api/v2/projects/{id}/sow",
    "commercial": "GET /api/v2/projects/{id}/sow",
}


class GateError(PermissionError):
    """Raised when a stage cannot run because upstream work is incomplete."""


@dataclass
class StageResult:
    stage: str
    agent: str
    output: AgentOutput
    artifacts: List[str]
    statements_persisted: int
    run_id: str


class Orchestrator:
    """Runs agents against a project, inside the governance path."""

    def __init__(self, gateway: LLMGateway, jobs: Optional[JobEngine] = None):
        self.gateway = gateway
        self.jobs = jobs or JobEngine()

    # ----------------------------------------------------------- lifecycle
    def lifecycle_state(self, repo, project_id: str) -> LifecycleState:
        """Derive state from what has actually been persisted.

        Not every stage is agent work. `intent` is satisfied the moment the
        customer states what they want to build, and `evidence` the moment a
        document is attached (spec §7, §8). Treating those as data-satisfied
        rather than agent-produced is what lets the lifecycle actually start.
        """
        st = LifecycleState()
        produced = {a.kind for a in repo.list_artifacts(project_id)}
        project = repo.get_project(project_id)

        data_satisfied = {
            "intent": bool(project and (project.intent or "").strip()),
            "evidence": bool(repo.list_evidence(project_id)),
        }

        for stage in STAGE_BY_ID.values():
            complete = bool(stage.produces and set(stage.produces) & produced)
            if data_satisfied.get(stage.id):
                complete = True
            if complete:
                st.statuses[stage.id] = StageStatus.COMPLETE
            if stage.approval is not Approval.NONE:
                st.approvals[stage.id] = (
                    repo.approval_state(project_id, "stage", stage.id) == "APPROVED")
        return st

    #: Stages satisfied by captured data rather than an agent run.
    DATA_SATISFIED_STAGES = ("intent", "evidence")

    def check_gate(self, repo, project_id: str, stage_id: str) -> None:
        stage = STAGE_BY_ID.get(stage_id)
        if not stage:
            raise KeyError(f"Unknown stage '{stage_id}'.")
        blockers = self.lifecycle_state(repo, project_id).blockers(stage_id)
        if blockers:
            raise GateError(" ".join(blockers))

    # ------------------------------------------------------------- running
    def run_stage(self, repo, project_id: str, stage_id: str,
                  enforce_gate: bool = True) -> StageResult:
        """Execute one stage synchronously and persist the result."""
        stage = STAGE_BY_ID.get(stage_id)
        if not stage:
            raise KeyError(f"Unknown stage '{stage_id}'.")
        agent_cls = AGENTS.get(stage.agent)
        if not agent_cls:
            raise KeyError(f"No agent registered for stage '{stage_id}' (agent '{stage.agent}').")
        if enforce_gate:
            self.check_gate(repo, project_id, stage_id)

        tools = build_project_tools(repo, project_id)
        agent = agent_cls(self.gateway, tools)
        output = agent.run()
        return self._persist(repo, project_id, stage_id, output)

    def _persist(self, repo, project_id: str, stage_id: str,
                 output: AgentOutput) -> StageResult:
        """Commit an agent proposal: statements, artifacts, run record, audit.

        Statements are written through the repository with their provenance
        already normalised by `BaseAgent.statement`, so nothing enters the
        canonical model as an unevidenced fact.
        """
        run = repo.record_run(
            project_id, output.agent, stage=stage_id,
            provider=output.provider, model=output.model,
            prompt_tokens=output.prompt_tokens, completion_tokens=output.completion_tokens,
            duration_ms=output.duration_ms,
            generation_mode=output.generation_mode,
            output_json=json.dumps(output.to_dict(), default=str)[:20000],
            input_refs_json=json.dumps([c.tool for c in output.tool_calls]),
            status="success",
        )

        persisted = 0
        for s in output.statements:
            repo.add_statement(
                project_id, kind=getattr(s, "kind", "note"), text=s.text,
                provenance=s.provenance.value, confidence=s.confidence.value,
                evidence=[e.to_dict() for e in s.evidence],
                stage=stage_id, ref=getattr(s, "ref", ""))
            persisted += 1

        kinds: List[str] = []
        for kind, content in output.artifacts.items():
            body = content if isinstance(content, str) else json.dumps(
                content, indent=2, ensure_ascii=False, default=str)
            repo.save_artifact(project_id, kind, body, stage=stage_id,
                               generated_by=output.agent, agent_run_id=run.id, fmt="json")
            kinds.append(kind)

        repo.audit(f"stage.{stage_id}.completed", "stage", stage_id,
                   reason=output.summary[:400],
                   after={"artifacts": kinds, "statements": persisted,
                          "generation_mode": output.generation_mode},
                   actor_kind="ai", project_id=project_id)

        return StageResult(stage=stage_id, agent=output.agent, output=output,
                           artifacts=kinds, statements_persisted=persisted, run_id=run.id)

    # ---------------------------------------------------------------- jobs
    def submit_stage(self, repo_factory: Callable[[], Any], project_id: str,
                     stage_id: str, tenant_id: str = "") -> Job:
        """Queue a stage as a background job (§42).

        `repo_factory` returns a repository bound to a *fresh* session, because
        the job runs on another thread after the request session has closed.
        """
        stage = STAGE_BY_ID.get(stage_id)
        if not stage:
            raise KeyError(f"Unknown stage '{stage_id}'.")

        def gate(_ctx):
            with repo_factory() as repo:
                self.check_gate(repo, project_id, stage_id)
                return {"stage": stage_id, "gate": "passed"}

        def execute(_ctx):
            with repo_factory() as repo:
                result = self.run_stage(repo, project_id, stage_id, enforce_gate=False)
                return {"artifacts": result.artifacts,
                        "statements": result.statements_persisted,
                        "generation_mode": result.output.generation_mode,
                        "summary": result.output.summary,
                        "degraded": result.output.degraded}

        steps = [
            Step("gate", f"{stage.label} readiness check", gate, retries=1),
            Step("execute", f"{stage.label} generation", execute, retries=2),
        ]
        job = self.jobs.create(f"stage:{stage_id}", project_id, steps, tenant_id=tenant_id)
        return self.jobs.submit(job, steps)

    def steps_for(self, stage_id: str) -> List[str]:
        return ["gate", "execute"]
