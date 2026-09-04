'use client';
import {useEffect, useState} from 'react';
import {
  Briefcase, ChevronDown, Plus, RefreshCw, LoaderCircle, CheckCircle2,
  AlertTriangle, CircleDashed, X,
} from 'lucide-react';
import {useFactory} from '../../lib/factory-context';
import {getFactoryJob, type Job, type Provenance} from '../../lib/factory-api';

/** Provenance badge. Colour encodes how strongly a statement is known (§8). */
const PROV: Record<Provenance, {cls: string; label: string; title: string}> = {
  CUSTOMER_DECISION: {cls: 'pv-decision', label: 'CUSTOMER', title: 'Decided by the customer'},
  FACT: {cls: 'pv-fact', label: 'FACT', title: 'Evidenced in a supplied document'},
  AI_INFERENCE: {cls: 'pv-ai', label: 'AI', title: 'Inferred by a model from evidence'},
  RECOMMENDATION: {cls: 'pv-rec', label: 'RECOMMENDED', title: 'Proposed, not yet chosen'},
  ASSUMPTION: {cls: 'pv-assume', label: 'ASSUMED', title: 'Taken as true pending confirmation'},
  UNKNOWN: {cls: 'pv-unknown', label: 'UNKNOWN', title: 'Not known — customer input required'},
};

export function ProvenanceBadge({value}: {value: Provenance}) {
  const p = PROV[value] || PROV.AI_INFERENCE;
  return <span className={`pvBadge ${p.cls}`} title={p.title}>{p.label}</span>;
}

export function StatusDot({status}: {status: string}) {
  if (status === 'COMPLETE') return <CheckCircle2 size={15} className="okIcon" />;
  if (status === 'RUNNING') return <LoaderCircle size={15} className="spin runIcon" />;
  if (status === 'FAILED' || status === 'BLOCKED') return <AlertTriangle size={15} className="errIcon" />;
  return <CircleDashed size={15} className="pendIcon" />;
}

/** Project selector shared by every Delivery Factory page. */
export function ProjectBar({title, sub}: {title: string; sub?: string}) {
  const {projects, projectId, project, select, refresh, create, lifecycle} = useFactory();
  const [open, setOpen] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [form, setForm] = useState({name: '', intent: '', domain: ''});
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try { await create(form); setShowNew(false); setForm({name: '', intent: '', domain: ''}); }
    finally { setBusy(false); }
  };

  return (
    <>
      <div className="pageHead">
        <div>
          <div className="crumb">Delivery Factory <span>›</span> {title}</div>
          <h1>{title}</h1>
          {sub && <p>{sub}</p>}
        </div>
        <div className="headActions">
          <div className="switcher">
            <button className="switcherBtn" onClick={() => setOpen(!open)}>
              <Briefcase size={16} />
              <span className="switcherLabel">{project ? project.name : 'No project'}</span>
              <ChevronDown size={15} />
            </button>
            {open && (
              <div className="dropdown" onMouseLeave={() => setOpen(false)}>
                <div className="dropdownHead">Factory project</div>
                {projects.length === 0 && <div className="dropdownEmpty">No projects yet</div>}
                {projects.map(p => (
                  <button key={p.id} className={p.id === projectId ? 'dropdownItem active' : 'dropdownItem'}
                          onClick={() => { select(p.id); setOpen(false); }}>
                    <strong>{p.name}</strong>
                    <small>{p.domain || 'no domain'} · v{p.version}</small>
                  </button>
                ))}
                <button className="dropdownItem newItem" onClick={() => { setShowNew(true); setOpen(false); }}>
                  + New project
                </button>
              </div>
            )}
          </div>
          <button className="secondary" onClick={refresh}><RefreshCw size={16} /> Refresh</button>
          <button className="primary" onClick={() => setShowNew(true)}><Plus size={16} /> New</button>
        </div>
      </div>

      {lifecycle && (
        <div className="progressStrip">
          <span>Lifecycle</span>
          <div className="progress"><i style={{width: `${(lifecycle.progress.complete / lifecycle.progress.total) * 100}%`}} /></div>
          <b>{lifecycle.progress.complete}/{lifecycle.progress.total}</b>
          {lifecycle.pending_approval && (
            <span className="pendingPill">
              <AlertTriangle size={13} /> {lifecycle.pending_approval.label} awaits approval
            </span>
          )}
        </div>
      )}

      {showNew && (
        <div className="modalScrim" onClick={() => setShowNew(false)}>
          <form className="modalCard" onClick={e => e.stopPropagation()} onSubmit={submit}>
            <div className="modalHead">
              <strong>New factory project</strong>
              <button type="button" className="sIconBtn" onClick={() => setShowNew(false)}><X size={16} /></button>
            </div>
            <label className="sLabel">Project name</label>
            <input className="sInput" required value={form.name}
                   onChange={e => setForm({...form, name: e.target.value})}
                   placeholder="Hospital HMS Modernization" />
            <label className="sLabel">What do you want to build?</label>
            <textarea className="sInput sArea" rows={4} value={form.intent}
                      onChange={e => setForm({...form, intent: e.target.value})}
                      placeholder="Modernize a hospital HMS from SQL Server and build automated analytics and an operational application." />
            <label className="sLabel">Domain (optional)</label>
            <input className="sInput" value={form.domain}
                   onChange={e => setForm({...form, domain: e.target.value})} placeholder="healthcare" />
            <button className="primary" type="submit" disabled={busy || !form.name}>
              {busy ? <LoaderCircle size={15} className="spin" /> : <Plus size={15} />} Create project
            </button>
          </form>
        </div>
      )}
    </>
  );
}

export function NoProject() {
  return (
    <div className="panel emptyLarge">
      <h3>No factory project selected</h3>
      <p>Create a project to start the delivery lifecycle, or pick one from the selector above.</p>
    </div>
  );
}

/** Polls a background job and renders its live trace (§42). */
export function JobTrace({jobId, onDone}: {jobId: string; onDone?: (j: Job) => void}) {
  const [job, setJob] = useState<Job | null>(null);

  useEffect(() => {
    let alive = true;
    let timer: any;
    const tick = async () => {
      try {
        const j = await getFactoryJob(jobId);
        if (!alive) return;
        setJob(j);
        if (['COMPLETED', 'FAILED', 'PARTIAL', 'CANCELLED'].includes(j.status)) {
          onDone?.(j);
          return;
        }
        timer = setTimeout(tick, 600);
      } catch { /* stop polling on error */ }
    };
    tick();
    return () => { alive = false; clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  if (!job) return <div className="empty"><LoaderCircle size={16} className="spin" /> Queued…</div>;
  const running = !['COMPLETED', 'FAILED', 'PARTIAL', 'CANCELLED'].includes(job.status);

  return (
    <div className={`panel architecturePipeline ${running ? 'live' : ''}`}>
      <div className="panelTitle">
        {running ? <LoaderCircle size={16} className="spin" /> : <CheckCircle2 size={16} />}
        {job.kind} {running && <span className="liveBadge">LIVE</span>}
      </div>
      <div className="pipelineHeader">
        <div><strong>{job.completed_steps} of {job.total_steps} steps</strong>
          <span> · {job.status} · {job.elapsed_seconds}s</span></div>
        <span>{job.message}</span>
      </div>
      <div className="executionTrace">
        <div className="traceList">
          {job.trace.slice(-10).map((t, i) => (
            <div className="traceRow" key={i}>
              <span className={`traceDot ${t.status}`} />
              <span className="traceTime">{new Date(t.timestamp).toLocaleTimeString()}</span>
              <b>{t.step || '—'}</b><span>{t.message}</span>
            </div>
          ))}
        </div>
      </div>
      {job.error && <div className="notice error">{job.error}</div>}
    </div>
  );
}
