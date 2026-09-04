'use client';
/**
 * Unified workspace renderer.
 *
 * Every workspace route used to render one identical generic page, so the rich
 * per-stage output the backend produces was never visible. This version drives
 * itself from WORKSPACES metadata: real pipelines, upstream gating, persisted
 * artifacts and role ownership per stage.
 */
import {
  ArrowRight, CheckCircle2, Clock3, Database, FileText, Layers3, Sparkles, Play,
  Download, ShieldCheck, LoaderCircle, Activity, AlertTriangle, Lock, Users,
} from 'lucide-react';
import {useEffect, useMemo, useRef, useState} from 'react';
import {getExecution, runStage, approve, downloadUrl} from '../lib/api';
import {WORKSPACES} from '../lib/workspaces';
import {useEngagement, ROLES} from '../lib/engagement-context';
import {ArtifactViewer} from './ArtifactViewer';

const TERMINAL = ['success', 'failed', 'blocked', 'cancelled'];
const terminal = (s?: string) => TERMINAL.includes(s || '');

export function WorkspacePage({route}: {route: string}) {
  const def = WORKSPACES[route];
  const {engagementId, engagement: eng, refresh, loading, role, dropStale} = useEngagement();

  const [execution, setExecution] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  // Bumped when a stage finishes so the artifact list reloads itself.
  const [artifactVersion, setArtifactVersion] = useState(0);
  const pollRef = useRef<number | null>(null);
  const pollingIdRef = useRef<string | null>(null);

  useEffect(() => () => { if (pollRef.current) window.clearTimeout(pollRef.current); pollingIdRef.current = null; }, []);

  const refreshExecution = async (executionId: string) => {
    if (!engagementId) return;
    if (pollingIdRef.current && pollingIdRef.current !== executionId) return;
    pollingIdRef.current = executionId;
    try {
      const r = await getExecution(engagementId, executionId);
      const next = r.execution;
      setExecution(next);
      if (!terminal(next?.status)) {
        setBusy(true);
        pollRef.current = window.setTimeout(() => refreshExecution(executionId), 600);
      } else {
        if (pollRef.current) window.clearTimeout(pollRef.current);
        pollingIdRef.current = null;
        setBusy(false);
        await refresh();
        setArtifactVersion(v => v + 1);
        if (next.status === 'success') setMsg(next.message || 'Execution completed successfully.');
        else if (next.status === 'blocked') setMsg(next.message || 'Execution is blocked by a lifecycle gate.');
        else setMsg(next.message || 'Execution failed.');
      }
    } catch (e: any) {
      pollingIdRef.current = null;
      setBusy(false);
      setMsg(e?.message || 'Unable to read execution status.');
    }
  };

  // Resume telemetry if an execution was already running when we arrived.
  useEffect(() => {
    const active = eng?.lifecycle?.active_execution;
    if (active && !terminal(active.status)) {
      setExecution(active);
      setBusy(true);
      refreshExecution(active.id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eng?.lifecycle?.active_execution?.id]);

  const execute = async () => {
    if (!eng || busy) return;
    setMsg('');
    setBusy(true);
    try {
      const r = await runStage(eng.project.id, def.stage);
      setExecution(r.execution);
      setMsg(r.status === 'ALREADY_RUNNING' ? 'Execution is already running.' : 'Execution queued. Live telemetry active.');
      refreshExecution(r.execution_id);
    } catch (e: any) {
      setBusy(false);
      setMsg(e?.message || 'Unable to start execution.');
    }
  };

  const approveBlueprint = async () => {
    if (!eng || !def.approvalKind) return;
    try {
      await approve(eng.project.id, def.approvalKind);
      setMsg('Blueprint approved. Downstream gates are now open.');
      await refresh();
    } catch (e: any) { setMsg(e?.message || 'Approval failed.'); }
  };

  /* ---------------------------------------------------------------- derived */
  const trace = execution?.trace || [];
  const traceByStep = useMemo(() => {
    const m: any = {};
    for (const e of trace) if (e.step) m[e.step] = e;
    return m;
  }, [trace]);

  const runState = (key: string) => {
    const t = traceByStep[key];
    if (t?.status === 'running') return 'RUNNING';
    if (t?.status === 'success') return 'COMPLETE';
    if (t?.status === 'failed') return 'FAILED';
    if (t?.status === 'blocked') return 'BLOCKED';
    const s = eng?.lifecycle?.runs?.[key]?.status;
    if (s === 'success') return 'COMPLETE';
    if (s === 'failed') return 'FAILED';
    return 'PENDING';
  };

  const pipeline = def.pipeline;
  const completed = pipeline.filter(([k]) => runState(k) === 'COMPLETE').length;
  const activeStep = execution?.current_step || null;
  const running = !!execution && !terminal(execution.status);
  const elapsed = execution?.started_at && running
    ? Math.max(execution?.elapsed_seconds || 0, Math.floor((Date.now() - new Date(execution.started_at).getTime()) / 1000))
    : (execution?.elapsed_seconds || 0);

  // Upstream gate: is the required prior stage complete?
  const upstreamOk = !def.requires
    || !!eng?.lifecycle?.stages?.[def.requires]
    || eng?.lifecycle?.runs?.[def.requires]?.status === 'success';
  const needsApproval = def.requires === 'blueprint' && eng && !eng.lifecycle?.approvals?.blueprint;
  const canRun = !!eng && pipeline.length > 0 && upstreamOk && !needsApproval;

  // True when the backend fell back to deterministic, evidence-only generation.
  const degraded = def.pipeline.some(([k]) => {
    const o = eng?.lifecycle?.runs?.[k]?.output;
    return o?.ai_enrichment === 'unavailable' || o?.generation_mode === 'deterministic_evidence_only';
  });

  // Why enrichment was unavailable. A quota or billing failure needs the
  // operator's attention, so the provider's own message is shown rather than a
  // generic "AI unavailable" that hides an actionable problem.
  const degradedReason: string = def.pipeline.reduce((acc: string, [k]: any) => {
    const o = eng?.lifecycle?.runs?.[k]?.output;
    return acc || (o?.ai_enrichment_reason ?? '');
  }, '');
  const quotaProblem = /limit exceeded|rate limit|quota|upgrade your plan|credits/i
    .test(degradedReason);

  const assessment = eng?.lifecycle?.runs?.assessment?.output;
  const blueprint = eng?.lifecycle?.runs?.blueprint?.output;
  const platformState = eng?.project?.platform_config?.verified_at
    ? 'VERIFIED' : eng?.project?.platform_config?.decision_status || 'NOT_SELECTED';

  const ownerRoles = def.owners.map(o => ROLES.find(r => r.id === o)?.label).filter(Boolean);
  const isMyWorkspace = role === 'all' || def.owners.includes(role);

  /* ------------------------------------------------------------------ view */
  if (!engagementId && !loading) {
    return (
      <>
        <PageHead def={def} />
        <div className="panel emptyLarge">
          <h3>No engagement selected</h3>
          <p>Create an engagement from the Intake Center, or pick one from Engagements. Your selection follows you across every workspace.</p>
          <div className="headActions" style={{justifyContent: 'center', marginTop: 14}}>
            <a className="primary" href="/intake">Start New Engagement</a>
            <a className="secondary" href="/engagements">Browse Engagements</a>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <PageHead def={def} eng={eng} />

      {eng && (
        <div className="headActions workspaceActions">
          <span className={isMyWorkspace ? 'ownerTag mine' : 'ownerTag'}>
            <Users size={14} /> {ownerRoles.slice(0, 3).join(' · ')}
          </span>
          <a className="secondary" href={downloadUrl(eng.project.id, 'pdf')}><Download size={16} /> PDF Report</a>
          {pipeline.length > 0 && (
            <button className="primary" onClick={execute} disabled={busy || !canRun} title={!canRun ? 'Upstream stage or approval required' : ''}>
              {busy ? <LoaderCircle size={16} className="spin" /> : <Play size={16} />} {busy ? 'Running…' : 'Run Stage'}
            </button>
          )}
        </div>
      )}

      {/* Upstream gate notice */}
      {eng && pipeline.length > 0 && !canRun && (
        <div className="panel gateBox">
          <strong><Lock size={16} /> Stage gated</strong>
          <p>
            {needsApproval
              ? 'The Solution Blueprint requires human approval before this stage can execute. Open Architecture to approve.'
              : `This stage requires the upstream "${def.requires?.replace(/_/g, ' ')}" stage to complete first.`}
          </p>
          <a className="secondary" href={needsApproval ? '/architecture' : `/${(def.requires || '').includes('blueprint') ? 'architecture' : 'discovery'}`}>
            Open upstream workspace
          </a>
        </div>
      )}

      {/* Execution pipeline + live telemetry */}
      {eng && pipeline.length > 0 && (
        <div className={`panel architecturePipeline ${running ? 'live' : ''}`}>
          <div className="panelTitle">
            <Activity className={running ? 'pulse' : ''} /> {def.title} execution pipeline
            {running && <span className="liveBadge">LIVE</span>}
          </div>
          <div className="pipelineHeader">
            <div>
              <strong>
                {running
                  ? `${Math.min((execution?.completed_steps || 0) + 1, pipeline.length)} of ${pipeline.length} steps`
                  : `${completed} of ${pipeline.length} steps complete`}
              </strong>
              {execution?.id && running && <span> · execution {execution.id.slice(0, 8)}</span>}
            </div>
            <span>{running ? (execution.message || 'Processing persisted engagement evidence.') : 'Each step is persisted and becomes the input to the next controlled stage.'}</span>
          </div>

          <div className="pipelineSteps">
            {pipeline.map(([key, title, description], i) => {
              let state = runState(key);
              if (running && activeStep === key) state = 'RUNNING';
              return (
                <div className={`pipelineStep ${state.toLowerCase()} ${activeStep === key ? 'active' : ''}`} key={key}>
                  <div className="pipelineIcon">
                    {state === 'RUNNING' ? <LoaderCircle className="spin" size={19} />
                      : state === 'COMPLETE' ? <CheckCircle2 size={19} />
                      : state === 'FAILED' || state === 'BLOCKED' ? <AlertTriangle size={19} />
                      : <span>{i + 1}</span>}
                  </div>
                  <div className="pipelineBody">
                    <div className="pipelineTop">
                      <strong>{title}</strong>
                      <b className={state === 'COMPLETE' ? 'ok' : state === 'RUNNING' ? 'running' : state === 'FAILED' || state === 'BLOCKED' ? 'failedText' : 'pending'}>{state}</b>
                    </div>
                    <p>{traceByStep[key]?.message || description}</p>
                    {state === 'RUNNING' && <div className="progressTrack"><div className="progressIndeterminate" /></div>}
                  </div>
                </div>
              );
            })}
          </div>

          {trace.length > 0 && (
            <div className="executionTrace">
              <div className="traceTitle">Live execution trace</div>
              <div className="traceList">
                {trace.slice(-12).map((e: any, i: number) => (
                  <div className="traceRow" key={`${e.timestamp}-${i}`}>
                    <span className={`traceDot ${e.status}`} />
                    <span className="traceTime">{new Date(e.timestamp).toLocaleTimeString()}</span>
                    <b>{e.step}</b><span>{e.message}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {execution && (
            <div className="executionFooter">
              <span>Execution: <b>{execution.id.slice(0, 8)}</b></span>
              <span>Status: <b>{(execution.status || '').toUpperCase()}</b></span>
              <span>Elapsed: <b>{elapsed}s</b></span>
              <span>Current step: <b>{execution.current_step || 'Queued'}</b></span>
              <span>{trace.length} trace events</span>
            </div>
          )}
        </div>
      )}

      {msg && <div className={`notice ${/failed|error|blocked/i.test(msg) ? 'error' : ''}`}><CheckCircle2 size={18} />{msg}</div>}

      {/* Degraded-mode transparency: never let a deterministic result look like AI output. */}
      {eng && degraded && (
        <div className={`notice ${quotaProblem ? 'error' : 'warn'}`}>
          <AlertTriangle size={18} />
          <span>
            <b>{quotaProblem ? 'AI provider rejected the request.' : 'AI enrichment unavailable.'}</b>{' '}
            This stage completed using deterministic, evidence-only generation — no AI
            analysis was applied.
            {degradedReason && <><br /><code className="degradedReason">{degradedReason}</code></>}
          </span>
        </div>
      )}

      {/* Assessment detail (architecture) */}
      {eng && route === '/architecture' && assessment && (
        <div className="panel assessmentPanel">
          <div className="panelTitle"><ShieldCheck /> Current-State Assessment <span className="inlineStatus ok">PERSISTED</span></div>
          <p>{assessment.summary}</p>
          <div className="assessmentGrid">
            {Object.entries(assessment.dimensions || {}).map(([key, value]: any) => (
              <div className="assessmentCard" key={key}>
                <div className="assessmentCardTop"><strong>{key.replace(/_/g, ' ')}</strong><span>{value.status}</span></div>
                <p>{(value.evidence || []).slice(0, 3).join(' · ')}</p>
              </div>
            ))}
          </div>
          <div className="assessmentMeta">
            <span>Decision: <b>{assessment.decision || '—'}</b></span>
            <span>Risks: <b>{assessment.risks?.length || 0}</b></span>
            <span>Unknowns: <b>{assessment.unknowns?.length || 0}</b></span>
          </div>
        </div>
      )}

      {eng && route === '/architecture' && blueprint && eng.lifecycle?.approvals?.blueprint && (
        <div className="panel assessmentPanel">
          <div className="panelTitle"><CheckCircle2 /> Solution Blueprint <span className="inlineStatus ok">APPROVED</span></div>
          <p>{blueprint.summary || 'Approved target architecture is ready for downstream platform and metadata gates.'}</p>
        </div>
      )}

      {/* The artifacts this stage produced — previously never rendered. */}
      {eng && def.artifactKinds.length > 0 && (
        <ArtifactViewer
          engagementId={engagementId}
          filterKinds={def.artifactKinds}
          refreshKey={artifactVersion}
          onStale={dropStale}
          title={`${def.title} artifacts`}
          emptyHint={canRun ? 'Run this stage to generate governed artifacts.' : 'Complete the upstream stage to unlock these artifacts.'}
        />
      )}

      {/* Lifecycle control */}
      {eng && (
        <div className="workspaceGrid">
          <div className="panel">
            <div className="panelTitle"><ShieldCheck /> Lifecycle control</div>
            <div className="statusRow"><span>Engagement</span><b>{eng.project.name}</b></div>
            <div className="statusRow"><span>Progress</span><b>{eng.lifecycle.progress}/{eng.lifecycle.total}</b></div>
            {Object.entries(eng.lifecycle.stages || {}).map(([k, v]: any) => (
              <div className="statusRow" key={k}>
                <span>{k.replace(/_/g, ' ')}</span>
                <b className={v ? 'ok' : 'pending'}>{v ? 'COMPLETE' : 'PENDING'}</b>
              </div>
            ))}
            {route === '/discovery' && eng.lifecycle.stages?.discovery && (
              <a className="primary" href="/architecture"><ArrowRight size={17} /> Continue to Solution Architecture</a>
            )}
            {route === '/architecture' && eng.lifecycle.runs?.blueprint?.status === 'success' && !eng.lifecycle.approvals?.blueprint && (
              <button className="primary" onClick={approveBlueprint}>Approve Blueprint</button>
            )}
            {route === '/architecture' && eng.lifecycle.stages?.architecture && !eng.lifecycle.stages?.platform && (
              <a className="primary" href="/platform"><ArrowRight size={17} /> Continue to Platform &amp; Environment</a>
            )}
          </div>

          <div className="panel">
            <div className="panelTitle"><Clock3 /> Evidence snapshot</div>
            <p>Documents: <b>{eng.documents?.length ?? 0}</b></p>
            <p>Artifacts: <b>{eng.artifacts?.length ?? 0}</b></p>
            <p>Platform: <b>{eng.project.platform_config?.platform || 'Not selected'}</b></p>
            <p>Platform state: <b>{platformState}</b></p>
            <p>Blueprint approval: <b>{eng.lifecycle?.approvals?.blueprint ? 'APPROVED' : 'REQUIRED'}</b></p>
            <a className="secondary" href={downloadUrl(eng.project.id, 'zip')}>Download Intake Pack</a>
          </div>
        </div>
      )}
    </>
  );
}

function PageHead({def, eng}: {def: any; eng?: any}) {
  return (
    <div className="pageHead">
      <div>
        <div className="crumb">Home <span>›</span> {def.nav}{eng && <> <span>›</span> {eng.project.name}</>}</div>
        <h1>{def.title}</h1>
        <p>{def.blurb}</p>
      </div>
    </div>
  );
}
