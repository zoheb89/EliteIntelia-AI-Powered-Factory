'use client';
/**
 * Platform decision surface (§14).
 *
 * The point of this screen is transparency: it shows the weighted criteria that
 * were derived from the customer's own requirements, which of them rest on
 * evidence, and how each candidate scored — so the recommendation can be
 * challenged on its inputs rather than accepted on authority.
 */
import {useEffect, useState} from 'react';
import {CheckCircle2, LoaderCircle, Scale, Cloud, AlertTriangle, Info} from 'lucide-react';
import {useFactory} from '../../lib/factory-context';
import {decidePlatform, getPlatformOptions, type PlatformEval} from '../../lib/factory-api';
import {NoProject, ProjectBar} from './shared';

export function PlatformOptions() {
  const {projectId, refresh} = useFactory();
  const [data, setData] = useState<PlatformEval | null>(null);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState('');
  const [rationale, setRationale] = useState('');
  const [deciding, setDeciding] = useState('');

  const load = async () => {
    if (!projectId) return;
    setLoading(true); setMsg('');
    try { setData(await getPlatformOptions(projectId)); }
    catch (e: any) { setMsg(e?.message || 'Unable to load options'); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [projectId]);

  const decide = async (platform: string) => {
    if (!projectId) return;
    setDeciding(platform); setMsg('');
    try {
      const r = await decidePlatform(projectId, platform, rationale);
      setData(r);
      await refresh();
      setMsg(r.followed_recommendation
        ? `${platform} selected, matching the recommendation.`
        : `${platform} selected. This differs from the recommendation (${r.recommended_platform}); the rationale has been recorded.`);
    } catch (e: any) { setMsg(e?.message || 'Unable to record the decision'); }
    finally { setDeciding(''); }
  };

  return (
    <>
      <ProjectBar title="Platform Selection"
                  sub="Candidates scored against evidenced requirements. The platform advises; you decide." />

      {!projectId ? <NoProject /> : loading && !data ? (
        <div className="panel loading">Evaluating platforms…</div>
      ) : !data ? (
        <div className="panel emptyLarge"><h3>No evaluation yet</h3>
          <p>{msg || 'Add requirements, then run the platform stage.'}</p></div>
      ) : (
        <>
          {msg && <div className={`notice ${/unable/i.test(msg) ? 'error' : ''}`}>{msg}</div>}

          {/* How the decision was reached */}
          <section className="panel">
            <div className="panelTitle"><Scale size={17} /> How this was decided</div>
            <div className="decisionMeta">
              <div><span>Method</span><b>{data.method.replace(/_/g, ' ')}</b></div>
              <div><span>Requirements analysed</span><b>{data.context.requirements_analysed}</b></div>
              <div><span>Criteria from evidence</span>
                <b>{data.context.criteria_from_evidence}/{data.context.criteria_total}</b></div>
              <div><span>Cloud direction</span>
                <b>{data.context.cloud_direction.join(', ') || 'not evidenced'}</b></div>
              <div><span>Status</span><b>{data.decision_status.replace(/_/g, ' ')}</b></div>
            </div>
            <p className="hint"><Info size={13} /> {data.note}</p>

            <div className="criteriaGrid">
              {data.criteria.slice(0, 8).map(c => (
                <div className={`criterion ${c.derived_from_evidence ? '' : 'assumed'}`} key={c.criterion}>
                  <div className="criterionTop">
                    <strong>{c.criterion.replace(/_/g, ' ')}</strong>
                    <span>{c.weight}</span>
                  </div>
                  <div className="weightBar">
                    <i style={{width: `${Math.min(100, (c.weight / 5) * 100)}%`}} />
                  </div>
                  {c.derived_from_evidence
                    ? <small className="fromEvidence">“{c.evidence[0]?.slice(0, 70)}…”</small>
                    : <small className="assumedNote">Baseline weight — not mentioned in the evidence</small>}
                </div>
              ))}
            </div>
          </section>

          {/* Option A / B / C */}
          <div className="optionGrid">
            {(data.options || []).map(o => {
              const selected = data.selected_platform === o.platform;
              return (
                <section className={`panel optionCard ${o.recommended ? 'rec' : ''} ${selected ? 'chosen' : ''}`}
                         key={o.platform}>
                  <div className="optionTop">
                    <div>
                      <div className="optionLabel">{o.option}</div>
                      <h3>{o.platform}</h3>
                    </div>
                    <div className="fitBig">{o.fit}<small>%</small></div>
                  </div>
                  {o.recommended && <span className="recTag"><CheckCircle2 size={12} /> Recommended</span>}
                  {selected && <span className="chosenTag"><CheckCircle2 size={12} /> Selected</span>}
                  {!o.recommended && <span className="gapTag">{o.gap_to_leader} pts behind</span>}

                  <div className="cloudRow"><Cloud size={12} /> {o.clouds.join(', ')}</div>

                  <div className="prosCons">
                    <div>
                      <span className="pcHead">Advantages</span>
                      <ul>{o.advantages.slice(0, 3).map((a, i) => <li key={i}>{a}</li>)}</ul>
                    </div>
                    <div>
                      <span className="pcHead">Disadvantages</span>
                      <ul>{o.disadvantages.slice(0, 3).map((d, i) => <li key={i}>{d}</li>)}</ul>
                    </div>
                  </div>

                  <div className="complexityRow">
                    <span>Implementation <b>{o.implementation_complexity}</b></span>
                    <span>Migration <b>{o.migration_complexity.split('—')[0].trim()}</b></span>
                  </div>

                  <p className="reasoning">{o.reasoning}</p>

                  {data.decision_status !== 'DECIDED' && (
                    <button className={o.recommended ? 'primary' : 'secondary'}
                            disabled={!!deciding} onClick={() => decide(o.platform)}>
                      {deciding === o.platform ? <LoaderCircle size={14} className="spin" /> : <CheckCircle2 size={14} />}
                      Select {o.platform}
                    </button>
                  )}
                </section>
              );
            })}
          </div>

          {data.decision_status !== 'DECIDED' && (
            <section className="panel">
              <label className="sLabel">Decision rationale (recorded with the decision)</label>
              <textarea className="sInput sArea" rows={2} value={rationale}
                        onChange={e => setRationale(e.target.value)}
                        placeholder="e.g. Existing enterprise agreement and in-house skills." />
              <p className="hint">
                <AlertTriangle size={13} /> Choosing an option other than the recommendation is
                supported and recorded — the rationale is preserved in the decision trail.
              </p>
            </section>
          )}

          {/* Full comparison */}
          <section className="panel">
            <div className="panelTitle">All candidates</div>
            <div className="tableWrap">
              <table className="dataTable">
                <thead><tr><th>Platform</th><th>Fit</th><th>Relative</th><th>Clouds</th>
                  <th>Cloud aligned</th><th>Strengths</th></tr></thead>
                <tbody>
                  {(data.scores || []).map(s => (
                    <tr key={s.platform} className={s.disqualified ? 'dq' : ''}>
                      <td>{s.platform}{s.disqualified && <em> (excluded)</em>}</td>
                      <td><b>{s.fit}%</b></td>
                      <td>{s.relative}%</td>
                      <td>{s.clouds.join(', ')}</td>
                      <td>{s.cloud_aligned ? <span className="okIcon">yes</span> : <span className="errIcon">no</span>}</td>
                      <td className="stmtCell">{s.strengths.map(x => x.replace(/_/g, ' ')).join(', ')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </>
  );
}
