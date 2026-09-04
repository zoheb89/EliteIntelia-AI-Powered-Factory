'use client';
/** Generated deliverables (§29). Reports are always rendered from the current
 *  canonical state, so a download can never represent an older project version. */
import {useCallback, useEffect, useState} from 'react';
import {FileDown, RefreshCw, Lock} from 'lucide-react';
import {listReports, reportUrl, type ReportRow} from '../../lib/factory-api';

export function ReportsPanel({projectId}: {projectId: string}) {
  const [items, setItems] = useState<ReportRow[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try { setItems((await listReports(projectId)).items || []); }
    catch { /* nothing generated yet */ }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  const ready = items.filter(i => i.available);
  const locked = items.filter(i => !i.available);

  return (
    <section className="panel">
      <div className="panelHead">
        <h3><FileDown size={18} /> Reports ({ready.length} available)</h3>
        <button className="secondary sm" onClick={load} disabled={loading}>
          <RefreshCw size={14} className={loading ? 'spin' : ''} /> Refresh
        </button>
      </div>

      {ready.length === 0 ? (
        <div className="empty">Run a stage to make its report available.</div>
      ) : (
        <div className="reportGrid">
          {ready.map(r => (
            <a className="reportCard" key={r.kind} href={reportUrl(projectId, r.kind)}
               target="_blank" rel="noreferrer">
              <FileDown size={16} />
              <div>
                <strong>{r.title}</strong>
                <small>from {r.present.join(', ')}</small>
              </div>
            </a>
          ))}
        </div>
      )}

      {locked.length > 0 && (
        <>
          <div className="sLabel" style={{marginTop: 14}}>Not yet available</div>
          <div className="chipRow">
            {locked.map(r => (
              <span className="chipBtn" key={r.kind} title={`Needs: ${r.uses.join(', ')}`}>
                <Lock size={11} /> {r.title}
              </span>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
