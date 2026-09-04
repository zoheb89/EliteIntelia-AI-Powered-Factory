'use client';
/** Statement of Work (§26, §27).
 *
 * The screen leads with completeness, because the product's position is that an
 * incomplete SOW must not be issued. Missing sections are shown as gaps rather
 * than quietly filled with plausible prose.
 */
import {useEffect, useState} from 'react';
import {FileText, LoaderCircle, Download, AlertTriangle, CheckCircle2, HelpCircle} from 'lucide-react';
import {useFactory} from '../../lib/factory-context';
import {getSow, sowMarkdownUrl, type Sow} from '../../lib/factory-api';
import {NoProject, ProjectBar} from './shared';

const MISSING = 'Not yet established. Requires customer input before this SOW can be issued.';

export function SowView() {
  const {projectId} = useFactory();
  const [sow, setSow] = useState<Sow | null>(null);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState('');

  const load = async () => {
    if (!projectId) return;
    setLoading(true); setMsg('');
    try { setSow(await getSow(projectId)); }
    catch (e: any) { setMsg(e?.message || 'Unable to assemble the SOW'); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [projectId]);

  const isMissing = (v: any) =>
    v === MISSING || (Array.isArray(v) && v.length === 1 && v[0] === MISSING);

  return (
    <>
      <ProjectBar title="Statement of Work"
                  sub="Assembled from the canonical model. Gaps are reported, never filled in." />

      {!projectId ? <NoProject /> : loading && !sow ? (
        <div className="panel loading">Assembling…</div>
      ) : !sow ? (
        <div className="panel emptyLarge"><h3>No SOW yet</h3><p>{msg || 'Run the estimation stage first.'}</p></div>
      ) : (
        <>
          {/* Issuability is the headline */}
          <section className={`panel issuanceCard ${sow.issuable ? 'ok' : 'draft'}`}>
            <div className="issuanceTop">
              {sow.issuable ? <CheckCircle2 size={22} /> : <AlertTriangle size={22} />}
              <div>
                <strong>{sow.issuable ? 'Ready to issue' : 'DRAFT — not issuable'}</strong>
                <p>{sow.completeness.reason}</p>
              </div>
              <a className="secondary" href={sowMarkdownUrl(projectId)} target="_blank" rel="noreferrer">
                <Download size={15} /> Markdown
              </a>
            </div>
            <div className="issuanceBar">
              <div className="progress">
                <i style={{width: `${(sow.completeness.complete_count / sow.completeness.total_sections) * 100}%`}} />
              </div>
              <b>{sow.completeness.complete_count}/{sow.completeness.total_sections} sections</b>
            </div>
            {!!sow.completeness.incomplete_sections.length && (
              <div className="chipRow" style={{marginTop: 10}}>
                {sow.completeness.incomplete_sections.map(s => (
                  <span className="chipBtn missing" key={s}>{s.replace(/_/g, ' ')}</span>
                ))}
              </div>
            )}
          </section>

          {!!sow.open_questions.length && (
            <section className="panel">
              <div className="panelTitle"><HelpCircle size={17} /> Open questions blocking issuance</div>
              <ul className="qList">
                {sow.open_questions.map((q, i) => <li key={i}>{q}</li>)}
              </ul>
            </section>
          )}

          {/* Sections */}
          <section className="panel">
            <div className="panelHead"><h3><FileText size={18} /> Sections</h3>
              <span className="hint">Project version {sow.generated_from_project_version}</span></div>
            <div className="sowGrid">
              {Object.entries(sow.sections).map(([key, value]) => (
                <div className={`sowSection ${isMissing(value) ? 'gap' : ''}`} key={key}>
                  <div className="sowKey">{key.replace(/_/g, ' ')}</div>
                  <div className="sowBody">{render(value)}</div>
                </div>
              ))}
            </div>
          </section>
        </>
      )}
    </>
  );
}

function render(value: any) {
  if (value === null || value === undefined) return <em>—</em>;
  if (typeof value === 'string') return <p>{value}</p>;
  if (typeof value === 'number') return <p>{value}</p>;
  if (Array.isArray(value)) {
    return (
      <ul>
        {value.slice(0, 8).map((v, i) => (
          <li key={i}>
            {typeof v === 'object' && v !== null
              ? Object.entries(v).filter(([, x]) => x !== null && x !== '')
                  .map(([k, x]) => `${k}: ${x}`).join(' · ')
              : String(v)}
          </li>
        ))}
        {value.length > 8 && <li className="more">+{value.length - 8} more</li>}
      </ul>
    );
  }
  return (
    <ul>
      {Object.entries(value).map(([k, v]) => (
        <li key={k}><b>{k.replace(/_/g, ' ')}:</b>{' '}
          {v === null || v === '' ? <em>not set</em>
            : typeof v === 'object' ? JSON.stringify(v).slice(0, 120) : String(v)}
        </li>
      ))}
    </ul>
  );
}
