'use client';
/**
 * Delivery lifecycle board — the primary surface for the agent factory.
 *
 * Renders all 20 stages grouped as the spec's navigation (§75), shows exactly
 * why a stage is blocked, runs stages through their agent with live job
 * telemetry, and records human approvals at the governed gates.
 */
import {useCallback, useEffect, useMemo, useState} from 'react';
import Link from 'next/link';
import {
  Play, CheckCircle2, Lock, ShieldCheck, LoaderCircle, Cpu, Calculator,
  FileText, Database, AlertTriangle, ArrowRight, Sparkles, ZapOff,
} from 'lucide-react';
import {useFactory} from '../../lib/factory-context';
import {
  approveStage, getCoverage, getLifecycleDef, listStatements, listUnknowns,
  runFactoryStage, getNextAction, type Coverage, type LifecycleDef,
  type NextActionPayload, type Statement,
} from '../../lib/factory-api';
import {NextBestAction} from './NextBestAction';
import {JobTrace, NoProject, ProjectBar, ProvenanceBadge, StatusDot} from './shared';
import {EvidencePanel} from './EvidencePanel';
import {ReportsPanel} from './ReportsPanel';

const HANDLER_ICON: Record<string, any> = {
  agent: Cpu, engine: Calculator, data: Database, none: AlertTriangle,
};
const ENGINE_LINK: Record<string, string> = {
  estimation: '/factory/estimate', sow: '/factory/sow', commercial: '/factory/sow',
};

export function LifecycleBoard() {
  const {projectId, lifecycle, refresh} = useFactory();
  const [def, setDef] = useState<LifecycleDef | null>(null);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [statements, setStatements] = useState<Statement[]>([]);
  const [unknowns, setUnknowns] = useState(0);
  const [nextAction, setNextAction] = useState<NextActionPayload | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState('');

  useEffect(() => {
    getLifecycleDef().then(setDef).catch(e => setMsg(e.message));
    getCoverage().then(setCoverage).catch(() => {});
  }, []);

  const loadCanonical = useCallback(async () => {
    if (!projectId) return;
    try {
      const [s, u, n] = await Promise.all([
        listStatements(projectId), listUnknowns(projectId),
        getNextAction(projectId).catch(() => null),
      ]);
      setStatements(s.items || []);
      setUnknowns(u.count || 0);
      setNextAction(n);
    } catch { /* project may be empty */ }
  }, [projectId]);

  useEffect(() => { loadCanonical(); }, [loadCanonical]);

  const run = async (stageId: string) => {
    if (!projectId) return;
    setBusy(stageId); setMsg(''); setJobId(null);
    try {
      const r = await runFactoryStage(projectId, stageId, true);
      if (r.job_id) setJobId(r.job_id);
      else { await refresh(); await loadCanonical(); setMsg(`${stageId} completed.`); }
    } catch (e: any) {
      setMsg(e?.message || 'Unable to start the stage.');
    } finally { setBusy(null); }
  };

  const approve = async (stageId: string) => {
    if (!projectId) return;
    try {
      await approveStage(projectId, stageId, 'Approved from the lifecycle board');
      await refresh();
      setMsg(`${stageId} approved. Downstream stages are now open.`);
    } catch (e: any) { setMsg(e?.message || 'Approval failed.'); }
  };

  const byGroup = useMemo(() => {
    if (!def) return [];
    return def.groups
      .map(g => ({group: g, stages: def.stages.filter(s => s.group === g)}))
      .filter(g => g.stages.length);
  }, [def]);

  const kinds = useMemo(() => {
    const m: Record<string, number> = {};
    statements.forEach(s => { m[s.provenance] = (m[s.provenance] || 0) + 1; });
    return m;
  }, [statements]);

  if (!def) return <div className="panel loading">Loading the lifecycle…</div>;

  return (
    <>
      <ProjectBar title="Delivery Lifecycle"
                  sub="Twenty governed stages from business intent to production handover." />

      {!projectId ? <NoProject /> : (
        <>
          {msg && <div className={`notice ${/fail|unable|blocked/i.test(msg) ? 'error' : ''}`}>{msg}</div>}

          {/* Canonical model summary */}
          <div className="stats">
            <Stat label="Statements" value={String(statements.length)} note="Canonical model" />
            <Stat label="Open questions" value={String(unknowns)} note="Customer input required"
                  tone={unknowns ? 'warn' : ''} />
            <Stat label="Evidence-backed" value={String((kinds.FACT || 0) + (kinds.CUSTOMER_DECISION || 0))}
                  note="FACT or customer decision" />
            <Stat label="Coverage" value={coverage ? `${coverage.coverage.handled}/${coverage.coverage.total}` : '—'}
                  note="Stages with a handler" />
          </div>

          <NextBestAction data={nextAction} onRun={run} />

          {lifecycle?.generation?.any_degraded && (
            <div className="degradedBanner">
              <ZapOff size={19} />
              <div>
                <strong>
                  No AI analysis was applied to {lifecycle.generation.degraded_stages.length}{' '}
                  {lifecycle.generation.degraded_stages.length === 1 ? 'stage' : 'stages'}.
                </strong>
                <p>
                  These stages completed using deterministic, evidence-only generation —
                  the content comes from your documents alone, with nothing inferred.
                  Re-run them once the AI provider is available to get full analysis.
                </p>
                {lifecycle.generation.reason && (
                  <code>{lifecycle.generation.reason}</code>
                )}
                <div className="degradedStages">
                  {lifecycle.generation.degraded_stages.map(sid => (
                    <span key={sid}>{sid.replace(/_/g, ' ')}</span>
                  ))}
                </div>
                <a className="secondary sm" href="/settings">Check the AI provider →</a>
              </div>
            </div>
          )}

          {jobId && <JobTrace jobId={jobId} onDone={async () => { await refresh(); await loadCanonical(); }} />}

          <EvidencePanel projectId={projectId}
                         onChange={async () => { await refresh(); await loadCanonical(); }} />

          {/* Stage board */}
          {byGroup.map(({group, stages}) => (
            <section className="panel" key={group}>
              <div className="panelTitle">{group}</div>
              <div className="stageGrid">
                {stages.map(s => {
                  const st = lifecycle?.stages[s.id];
                  const handler = coverage?.stages[s.id]?.handler || 'agent';
                  const Icon = HANDLER_ICON[handler] || Cpu;
                  const complete = st?.status === 'COMPLETE';
                  const blocked = !!st?.blockers?.length;
                  const needsApproval = complete && s.approval !== 'NONE' && !st?.approved;

                  return (
                    <div className={`stageCard ${complete ? 'done' : blocked ? 'blocked' : 'ready'}`} key={s.id}>
                      <div className="stageTop">
                        <StatusDot status={st?.status || 'PENDING'} />
                        <strong>{s.label}</strong>
                        {st?.generation_mode && st.generation_mode !== 'ai' ? (
                          <span className="handlerTag h-degraded" title="Evidence-only — no AI analysis was applied">
                            <ZapOff size={11} /> no AI
                          </span>
                        ) : st?.generation_mode === 'ai' ? (
                          <span className="handlerTag h-ai" title="Generated with AI analysis">
                            <Sparkles size={11} /> AI
                          </span>
                        ) : (
                          <span className={`handlerTag h-${handler}`} title={coverage?.stages[s.id]?.detail}>
                            <Icon size={11} /> {handler}
                          </span>
                        )}
                      </div>
                      <p className="stageDesc">{s.description}</p>

                      {blocked && (
                        <div className="stageBlockers">
                          <Lock size={12} /> {st!.blockers.join(' ')}
                        </div>
                      )}

                      <div className="stageActions">
                        {handler === 'data' && (
                          <span className="stageNote">Satisfied by captured data</span>
                        )}
                        {handler === 'engine' && (
                          <Link className="secondary sm" href={ENGINE_LINK[s.id] || '/factory'}>
                            Open engine <ArrowRight size={13} />
                          </Link>
                        )}
                        {handler === 'agent' && !complete && (
                          <button className="primary sm" disabled={blocked || busy === s.id}
                                  onClick={() => run(s.id)}>
                            {busy === s.id ? <LoaderCircle size={13} className="spin" /> : <Play size={13} />}
                            Run
                          </button>
                        )}
                        {complete && !needsApproval && s.approval !== 'NONE' && (
                          <span className="approvedTag"><ShieldCheck size={12} /> Approved</span>
                        )}
                        {needsApproval && (
                          <button className="approveBtn" onClick={() => approve(s.id)}>
                            <CheckCircle2 size={13} /> Approve
                          </button>
                        )}
                        {s.id === 'platform' && (
                          <Link className="secondary sm" href="/factory/platform">Options</Link>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          ))}

          <ReportsPanel projectId={projectId} />

          {/* Canonical statements with provenance */}
          <section className="panel">
            <div className="panelHead">
              <h3><FileText size={18} /> Canonical model ({statements.length})</h3>
              <div className="chipRow">
                {Object.entries(kinds).map(([p, n]) => (
                  <span key={p} className="chipBtn"><ProvenanceBadge value={p as any} /> {n}</span>
                ))}
              </div>
            </div>
            {statements.length === 0 ? (
              <div className="empty">Run a stage to populate the canonical model.</div>
            ) : (
              <div className="tableWrap">
                <table className="dataTable">
                  <thead><tr><th>Ref</th><th>Kind</th><th>Statement</th><th>Provenance</th></tr></thead>
                  <tbody>
                    {statements.slice(0, 60).map(s => (
                      <tr key={s.id}>
                        <td>{s.ref || '—'}</td>
                        <td>{s.kind.replace(/_/g, ' ')}</td>
                        <td className="stmtCell">{s.text}</td>
                        <td><ProvenanceBadge value={s.provenance} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </>
  );
}

function Stat({label, value, note, tone = ''}: {label: string; value: string; note: string; tone?: string}) {
  return (
    <div className="stat">
      <div className="muted">{label}</div>
      <strong className={tone === 'warn' ? 'warnValue' : ''}>{value}</strong>
      <div className="delta">{note}</div>
    </div>
  );
}
