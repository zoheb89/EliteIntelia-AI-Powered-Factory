'use client';
/** Operations command centre — real run/execution telemetry from the backend. */
import {useEffect, useState} from 'react';
import {Activity, RefreshCw, CheckCircle2, AlertTriangle, Clock3, Gauge} from 'lucide-react';
import {getExecutions, getRuns} from '../../lib/api';
import {useEngagement} from '../../lib/engagement-context';

export default function MonitoringPage() {
  const {engagementId, engagement} = useEngagement();
  const [execs, setExecs] = useState<any[]>([]);
  const [runs, setRuns] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    if (!engagementId) return;
    setLoading(true);
    try {
      const [e, r] = await Promise.allSettled([getExecutions(engagementId), getRuns(engagementId)]);
      if (e.status === 'fulfilled') setExecs(e.value.items || []);
      if (r.status === 'fulfilled') setRuns(r.value);
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); const t = setInterval(load, 10000); return () => clearInterval(t); /* eslint-disable-next-line */ }, [engagementId]);

  const ok = execs.filter(e => e.status === 'success').length;
  const failed = execs.filter(e => e.status === 'failed' || e.status === 'blocked').length;
  const active = execs.filter(e => !['success', 'failed', 'blocked', 'cancelled'].includes(e.status)).length;
  const avg = execs.length
    ? Math.round(execs.reduce((s, e) => s + (e.elapsed_seconds || 0), 0) / execs.length)
    : 0;

  return (
    <>
      <div className="pageHead">
        <div>
          <div className="crumb">Home <span>›</span> Monitoring</div>
          <h1>Monitoring &amp; Operations</h1>
          <p>Live execution telemetry, run health and lifecycle operations across the engagement.</p>
        </div>
        <div className="headActions">
          <button className="secondary" onClick={load} disabled={loading}>
            <RefreshCw size={16} className={loading ? 'spin' : ''} /> Refresh
          </button>
        </div>
      </div>

      {!engagementId ? (
        <div className="panel emptyLarge">
          <h3>No engagement selected</h3>
          <p>Select an engagement to monitor its executions.</p>
          <a className="primary" href="/engagements">Browse Engagements</a>
        </div>
      ) : (
        <>
          <div className="stats">
            <Metric icon={CheckCircle2} label="Successful runs" value={String(ok)} delta="Persisted executions" />
            <Metric icon={Activity} label="Active executions" value={String(active)} delta="Currently running" />
            <Metric icon={AlertTriangle} label="Failed / blocked" value={String(failed)} delta="Needs attention" />
            <Metric icon={Gauge} label="Avg duration" value={`${avg}s`} delta="Across all runs" />
          </div>

          <section className="panel">
            <div className="panelHead"><h3><Activity size={18} /> Execution history</h3></div>
            {execs.length === 0 ? (
              <div className="empty"><Clock3 size={18} /> No executions recorded yet. Run a stage from any workspace.</div>
            ) : (
              <div className="tableWrap">
                <table className="dataTable">
                  <thead>
                    <tr><th>Execution</th><th>Stage</th><th>Status</th><th>Steps</th><th>Elapsed</th><th>Started</th></tr>
                  </thead>
                  <tbody>
                    {execs.slice().reverse().map(e => (
                      <tr key={e.id}>
                        <td><code>{(e.id || '').slice(0, 8)}</code></td>
                        <td>{(e.stage || '').replace(/_/g, ' ')}</td>
                        <td><span className={`badge ${e.status}`}>{(e.status || '').toUpperCase()}</span></td>
                        <td>{e.completed_steps ?? 0}/{e.total_steps ?? 1}</td>
                        <td>{e.elapsed_seconds ?? 0}s</td>
                        <td>{e.started_at ? new Date(e.started_at).toLocaleString() : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {runs && (
            <section className="panel">
              <div className="panelHead"><h3><Gauge size={18} /> Stage run summary</h3></div>
              <div className="assessmentGrid">
                {Object.entries(runs).filter(([, v]: any) => v && typeof v === 'object').map(([k, v]: any) => (
                  <div className="assessmentCard" key={k}>
                    <div className="assessmentCardTop">
                      <strong>{k.replace(/_/g, ' ')}</strong>
                      <span>{v.status || '—'}</span>
                    </div>
                    <p>{v.message || v.summary || 'Persisted run record.'}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {engagement?.lifecycle && (
            <section className="panel">
              <div className="panelHead"><h3><CheckCircle2 size={18} /> Lifecycle health</h3></div>
              <div className="statusRow"><span>Progress</span><b>{engagement.lifecycle.progress}/{engagement.lifecycle.total}</b></div>
              {Object.entries(engagement.lifecycle.stages || {}).map(([k, v]: any) => (
                <div className="statusRow" key={k}>
                  <span>{k.replace(/_/g, ' ')}</span><b className={v ? 'ok' : 'pending'}>{v ? 'COMPLETE' : 'PENDING'}</b>
                </div>
              ))}
            </section>
          )}
        </>
      )}
    </>
  );
}

function Metric({icon: Icon, label, value, delta}: any) {
  return (
    <div className="stat">
      <div className="statIcon"><Icon size={20} /></div>
      <div className="muted">{label}</div>
      <strong>{value}</strong>
      <div className="delta">↗ {delta}</div>
    </div>
  );
}
