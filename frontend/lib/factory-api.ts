/**
 * Client for the /api/v2 core: canonical model, lifecycle, agents, platform
 * decision, estimation and SOW.
 *
 * Kept separate from lib/api.ts because the v2 core models *projects* with a
 * provenance-tagged canonical model, while the original API models engagements.
 * Mixing the two would blur which guarantees apply.
 */
import {API_BASE, getToken, UnauthorizedError} from "./api";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers || {});
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init?.body) headers.set("Content-Type", "application/json");

  let r: Response;
  try {
    r = await fetch(`${API_BASE}/api/v2${path}`, {...init, headers, cache: "no-store"});
  } catch (e: any) {
    throw new Error(e?.message || `Unable to reach the API at ${API_BASE}`);
  }
  const raw = await r.text();
  let payload: any = raw;
  if (raw) { try { payload = JSON.parse(raw); } catch { /* keep text */ } }

  if (r.status === 401) throw new UnauthorizedError("Sign in to continue.");
  if (!r.ok) {
    const d = payload?.detail ?? payload;
    throw new Error(typeof d === "string" ? d : d?.message || `Request failed (${r.status})`);
  }
  return payload as T;
}

/* ------------------------------------------------------------------ types */
export type Provenance =
  | "CUSTOMER_DECISION" | "FACT" | "AI_INFERENCE"
  | "RECOMMENDATION" | "ASSUMPTION" | "UNKNOWN";

export type StageDef = {
  id: string; label: string; group: string; agent: string;
  produces: string[]; requires: string[]; approval: string; description: string;
};
export type LifecycleDef = {
  groups: string[]; stages: StageDef[];
  provenance: {value: Provenance; rank: number; evidence_backed: boolean;
               requires_confirmation: boolean}[];
};
export type StageState = {status: string; approved: boolean; blockers: string[];
                          generation_mode?: string | null};
export type ProjectLifecycle = {
  progress: {complete: number; total: number};
  generation?: {degraded_stages: string[]; ai_stages: string[];
                any_degraded: boolean; reason: string};
  stages: Record<string, StageState>;
  next_stage: {id: string; label: string; agent: string; produces: string[]} | null;
  pending_approval: {id: string; label: string; approval: string} | null;
};
export type FactoryProject = {
  id: string; name: string; intent: string; domain: string; version: number;
  updated_at?: string; evidence?: number; artifacts?: number; runs?: number;
};
export type Statement = {
  id: string; ref: string; kind: string; text: string;
  provenance: Provenance; confidence: string; evidence: any[];
};
export type ArtifactRow = {
  id: string; kind: string; name: string; fmt: string; version: number;
  project_version: number; approval_state: string; superseded: boolean; created_at: string;
};
export type Coverage = {
  agents: {id: string; stages: string[]}[];
  stages: Record<string, {handler: string; detail: string}>;
  coverage: {total: number; handled: number; unhandled: string[]};
};
export type Job = {
  id: string; kind: string; status: string; current_step: string;
  completed_steps: number; total_steps: number; message: string; error: string;
  elapsed_seconds: number; trace: {timestamp: string; step: string; status: string; message: string}[];
};
export type PlatformOption = {
  option: string; platform: string; fit: number; relative: number; clouds: string[];
  recommended: boolean; gap_to_leader: number; advantages: string[];
  disadvantages: string[]; implementation_complexity: string;
  migration_complexity: string; reasoning: string;
};
export type PlatformEval = {
  method: string;
  context: {cloud_direction: string[]; requirements_analysed: number;
            criteria_from_evidence: number; criteria_total: number};
  criteria: {criterion: string; weight: number; derived_from_evidence: boolean; evidence: string[]}[];
  scores: {platform: string; fit: number; relative: number; clouds: string[];
           cloud_aligned: boolean; strengths: string[]; weaknesses: string[];
           breakdown: any[]; disqualified: boolean}[];
  options: PlatformOption[];
  recommendation: PlatformOption | null;
  decision_status: string; note: string;
  selected_platform?: string; followed_recommendation?: boolean;
  recommended_platform?: string; persisted?: boolean;
};
export type Estimate = {
  ok: boolean;
  totals: Record<string, number>;
  duration: {team_size: number; elapsed_days: number; elapsed_weeks: number;
             critical_path_days: number; critical_path: string[]};
  automation: {coverage: number; coverage_pct: number; by_class: Record<string, any>; basis: string};
  by_role: Record<string, number>;
  items: any[];
};
export type Sow = {
  project: string; generated_from_project_version: number;
  sections: Record<string, any>; open_questions: string[];
  completeness: {total_sections: number; incomplete_sections: string[];
                 complete_count: number; open_questions: number; ready: boolean; reason: string};
  issuable: boolean;
};

/* --------------------------------------------------------------- endpoints */
export const getLifecycleDef = () => req<LifecycleDef>("/lifecycle");
export const getCoverage = () => req<Coverage>("/agents");
export const getFactoryTools = () =>
  req<{tools: {name: string; description: string; parameters: Record<string, string>}[]}>("/tools");

export const listFactoryProjects = () => req<{items: FactoryProject[]}>("/projects");
export const getFactoryProject = (id: string) =>
  req<FactoryProject>(`/projects/${encodeURIComponent(id)}`);
export const createFactoryProject = (b: {name: string; intent?: string; domain?: string; customer?: string}) =>
  req<{id: string; name: string; version: number}>("/projects", {method: "POST", body: JSON.stringify(b)});

export const getProjectLifecycle = (id: string) =>
  req<ProjectLifecycle>(`/projects/${encodeURIComponent(id)}/lifecycle`);
export const runFactoryStage = (id: string, stage: string, background = true) =>
  req<any>(`/projects/${encodeURIComponent(id)}/stages/${encodeURIComponent(stage)}`,
           {method: "POST", body: JSON.stringify({background})});
export const getFactoryJob = (jobId: string) => req<Job>(`/jobs/${encodeURIComponent(jobId)}`);

export const listStatements = (id: string, kind?: string) =>
  req<{items: Statement[]}>(`/projects/${encodeURIComponent(id)}/statements${kind ? `?kind=${encodeURIComponent(kind)}` : ""}`);
export const listUnknowns = (id: string) =>
  req<{items: {id: string; text: string; stage: string}[]; count: number}>(`/projects/${encodeURIComponent(id)}/unknowns`);
export const listFactoryArtifacts = (id: string) =>
  req<{items: ArtifactRow[]}>(`/projects/${encodeURIComponent(id)}/artifacts`);
export const approveStage = (id: string, stageId: string, comment = "") =>
  req<any>(`/projects/${encodeURIComponent(id)}/approvals`,
           {method: "POST", body: JSON.stringify({subject_kind: "stage", subject_id: stageId, state: "APPROVED", comment})});
export const getAudit = (id: string) =>
  req<{items: {action: string; actor: string; actor_kind: string; reason: string; at: string}[]}>(`/projects/${encodeURIComponent(id)}/audit`);
export const getImpact = (id: string, stage: string) =>
  req<any>(`/projects/${encodeURIComponent(id)}/impact/${encodeURIComponent(stage)}`);

export const getPlatformOptions = (id: string) =>
  req<PlatformEval>(`/projects/${encodeURIComponent(id)}/platform/options`);
export const decidePlatform = (id: string, platform: string, rationale = "") =>
  req<PlatformEval>(`/projects/${encodeURIComponent(id)}/platform/decision`,
                    {method: "POST", body: JSON.stringify({platform, rationale})});

export const runEstimate = (id: string, body: Record<string, number>) =>
  req<Estimate>(`/projects/${encodeURIComponent(id)}/estimate`, {method: "POST", body: JSON.stringify(body)});
export const getSow = (id: string) => req<Sow>(`/projects/${encodeURIComponent(id)}/sow`);
export const sowMarkdownUrl = (id: string) =>
  `${API_BASE}/api/v2/projects/${encodeURIComponent(id)}/sow?fmt=markdown`;

/* ------------------------------------------------- evidence §8/§9 + PDFs §29 */
export type EvidenceRow = {
  id: string; name: string; document_type: string; confidence: string;
  sensitivity: string; classification: string; size_bytes: number;
  characters: number; chunks: number; status: string; sha256: string; created_at: string;
};
export type IngestResult = {
  duplicate: boolean; evidence_id: string; name: string; document_type?: string;
  confidence?: string; sensitivity?: string; sensitivity_signals?: string[];
  characters?: number; chunks?: number; message: string;
};
export type ReportRow = {
  kind: string; title: string; available: boolean; uses: string[]; present: string[];
};

export async function uploadEvidence(projectId: string, file: File): Promise<IngestResult> {
  const fd = new FormData();
  fd.append('file', file, file.name);
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  // Content-Type is deliberately unset so the browser adds the multipart boundary.
  const r = await fetch(`${API_BASE}/api/v2/projects/${encodeURIComponent(projectId)}/evidence`,
                        {method: 'POST', body: fd, headers, cache: 'no-store'});
  const raw = await r.text();
  let payload: any = raw;
  if (raw) { try { payload = JSON.parse(raw); } catch { /* keep text */ } }
  if (!r.ok) {
    const d = payload?.detail ?? payload;
    throw new Error(typeof d === 'string' ? d : d?.message || `Upload failed (${r.status})`);
  }
  return payload as IngestResult;
}

export const listEvidence = (id: string) =>
  req<{items: EvidenceRow[]; count: number}>(`/projects/${encodeURIComponent(id)}/evidence`);
export const listReports = (id: string) =>
  req<{items: ReportRow[]}>(`/projects/${encodeURIComponent(id)}/reports`);
export const reportUrl = (id: string, kind: string) =>
  `${API_BASE}/api/v2/projects/${encodeURIComponent(id)}/reports/${encodeURIComponent(kind)}.pdf`;

/* ------------------------------------------------- next best action (§2) */
export type NextActionPayload = {
  state: string;
  progress: {complete: number; total: number};
  evidence: {documents: number; percent: number; evidenced: number;
             open_questions: number; total: number};
  primary: any | null;
  actions: any[];
  basis: string;
};
export const getNextAction = (id: string) =>
  req<NextActionPayload>(`/projects/${encodeURIComponent(id)}/next-action`);

/* ------------------------------------------------- accelerators (§16, §53) */
export type Accelerator = {
  id: string; name: string; category: string; summary: string;
  stages: string[]; produces: string[]; engine: string; signals: string[];
  requires: string[]; matched_signals?: string[]; reason?: string;
  stages_complete?: string[]; stages_outstanding?: string[];
};
export type AcceleratorCatalogue = {
  categories: {id: string; label: string; description: string;
               accelerators: Accelerator[]}[];
  count: number; engines: Record<string, number>;
};
export type ProjectAccelerators = {
  recommended: Accelerator[]; available: Accelerator[];
  recommended_count: number; categories_engaged: string[]; basis: string;
};
export const getAcceleratorCatalogue = () =>
  req<AcceleratorCatalogue>('/accelerators');
export const getProjectAccelerators = (id: string) =>
  req<ProjectAccelerators>(`/projects/${encodeURIComponent(id)}/accelerators`);
