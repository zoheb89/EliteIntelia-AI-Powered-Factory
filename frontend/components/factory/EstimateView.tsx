'use client';
/** Effort, automation coverage and duration (§23-§25). Deterministic, so the
 *  inputs are exposed and adjustable rather than hidden behind a number. */
import {useState} from 'react';
import {Calculator, LoaderCircle, TrendingDown, Clock, Users, GitBranch} from 'lucide-react';
import {useFactory} from '../../lib/factory-context';
import {runEstimate, type Estimate} from '../../lib/factory-api';
import {NoProject, ProjectBar} from './shared';

const AUTOMATION_LABEL: Record<string, string> = {
  FULL_AUTOMATION: 'Full automation',
  AI_ASSISTED: 'AI-assisted (human review)',
  HUMAN_DECISION: 'Human decision',
  MANUAL: 'Manual / specialist',
};

export function EstimateView() {
  const {projectId} = useFactory();
  const [inputs, setInputs] = useState({
    entities: 18, reports: 12, sources: 5, team_size: 6, contingency: 0.15,
    technical: 1.2, data: 1.3, integration: 1.0, governance: 1.4, environment: 1.0,
  });
  const [est, setEst] = useState<Estimate | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');

  const run = async () => {
    if (!projectId) return;
    setBusy(true); setMsg('');
    try { setEst(await runEstimate(projectId, inputs)); }
    catch (e: any) { setMsg(e?.message || 'Estimate failed'); }
    finally { setBusy(false); }
  };

  const num = (k: keyof typeof inputs, label: string, step = 1) => (
    <div key={k}>
      <label className="sLabel">{label}</label>
      <input className="sInput sSm" type="number" step={step} value={inputs[k]}
             onChange={e => setInputs({...inputs, [k]: Number(e.target.value)})} />
    </div>
  );

  return (
    <>
      <ProjectBar title="Effort & Automation"
                  sub="Computed from the canonical model — reproducible, and every multiplier is shown." />

      {!projectId ? <NoProject /> : (
        <>
          <section className="panel">
            <div className="panelTitle"><Calculator size={17} /> Estimation inputs</div>
            <div className="inputGrid">
              {num('sources', 'Source systems')}
              {num('entities', 'Data entities')}
              {num('reports', 'Reports')}
              {num('team_size', 'Team size')}
              {num('contingency', 'Contingency', 0.05)}
              {num('technical', 'Technical complexity', 0.1)}
              {num('data', 'Data complexity', 0.1)}
              {num('integration', 'Integration complexity', 0.1)}
              {num('governance', 'Governance complexity', 0.1)}
              {num('environment', 'Environment complexity', 0.1)}
            </div>
            <button className="primary" onClick={run} disabled={busy}>
              {busy ? <LoaderCircle size={15} className="spin" /> : <Calculator size={15} />} Calculate
            </button>
            {msg && <div className="notice error">{msg}</div>}
          </section>

          {est?.ok && (
            <>
              <div className="stats">
                <Metric icon={TrendingDown} label="Manual baseline"
                        value={`${est.totals.manual_days}d`} note="Without the platform" />
                <Metric icon={Calculator} label="Delivered effort"
                        value={`${est.totals.with_contingency_days}d`} note="Including contingency" />
                <Metric icon={TrendingDown} label="Automation saving"
                        value={`${est.automation.coverage_pct}%`} note={`${est.totals.saved_days} days saved`} />
                <Metric icon={Clock} label="Duration"
                        value={`${est.duration.elapsed_weeks}w`} note={`${est.duration.team_size} people`} />
              </div>

              <div className="workspaceGrid">
                <section className="panel">
                  <div className="panelTitle"><Users size={17} /> Effort by role</div>
                  {Object.entries(est.by_role).map(([role, days]) => {
                    const max = Math.max(...Object.values(est.by_role));
                    return (
                      <div className="roleRow" key={role}>
                        <span>{role}</span>
                        <div className="roleBar"><i style={{width: `${(days / max) * 100}%`}} /></div>
                        <b>{days}d</b>
                      </div>
                    );
                  })}
                </section>

                <section className="panel">
                  <div className="panelTitle"><GitBranch size={17} /> Critical path</div>
                  <p className="hint">{est.duration.critical_path_days} days along the longest dependency chain.</p>
                  <ol className="pathList">
                    {est.duration.critical_path.map(p => <li key={p}>{p}</li>)}
                  </ol>
                </section>
              </div>

              <section className="panel">
                <div className="panelTitle">Automation breakdown</div>
                <p className="hint">{est.automation.basis}</p>
                <div className="tableWrap">
                  <table className="dataTable">
                    <thead><tr><th>Class</th><th>Items</th><th>Days</th></tr></thead>
                    <tbody>
                      {Object.entries(est.automation.by_class).map(([k, v]: any) => (
                        <tr key={k}><td>{AUTOMATION_LABEL[k] || k}</td>
                          <td>{v.items}</td><td>{v.days}d</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              <section className="panel">
                <div className="panelTitle">Work items</div>
                <div className="tableWrap">
                  <table className="dataTable">
                    <thead><tr><th>Item</th><th>Role</th><th>Automation</th>
                      <th>Manual</th><th>Engineering</th><th>Review</th><th>Total</th></tr></thead>
                    <tbody>
                      {(est.items || []).map((i: any) => (
                        <tr key={i.item_id}>
                          <td>{i.title}</td><td>{i.role}</td>
                          <td><span className={`autoTag a-${i.automation}`}>{AUTOMATION_LABEL[i.automation] || i.automation}</span></td>
                          <td>{i.manual_days}d</td><td>{i.engineering_days}d</td>
                          <td>{i.review_days}d</td><td><b>{i.total_days}d</b></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}
        </>
      )}
    </>
  );
}

function Metric({icon: Icon, label, value, note}: any) {
  return (
    <div className="stat">
      <div className="statIcon"><Icon size={19} /></div>
      <div className="muted">{label}</div>
      <strong>{value}</strong>
      <div className="delta">{note}</div>
    </div>
  );
}
