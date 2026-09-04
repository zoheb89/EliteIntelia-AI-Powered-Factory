'use client';
/**
 * Evidence ingestion (§8, §9).
 *
 * The upload result is shown in full — detected document type, confidence,
 * sensitivity and chunk count — because classification changes which extraction
 * rules apply downstream. A silent upload that was misclassified would quietly
 * corrupt discovery.
 */
import {useCallback, useEffect, useRef, useState} from 'react';
import {
  FileUp, LoaderCircle, ShieldAlert, FileText, Copy, RefreshCw, CheckCircle2,
} from 'lucide-react';
import {
  listEvidence, uploadEvidence, type EvidenceRow, type IngestResult,
} from '../../lib/factory-api';

const TYPE_LABEL: Record<string, string> = {
  rfp: 'RFP', rfi: 'RFI', rfq: 'RFQ', sow: 'SOW', schema: 'Schema',
  architecture: 'Architecture', meeting_notes: 'Meeting notes',
  requirements: 'Requirements', notes: 'Notes', unknown: 'Unclassified',
};

export function EvidencePanel({projectId, onChange}: {projectId: string; onChange?: () => void}) {
  const [items, setItems] = useState<EvidenceRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<IngestResult[]>([]);
  const [err, setErr] = useState('');
  const [drag, setDrag] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try { setItems((await listEvidence(projectId)).items || []); }
    catch { /* project may be new */ }
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  const upload = async (files: FileList | File[]) => {
    const list = Array.from(files);
    if (!list.length) return;
    setBusy(true); setErr(''); setResults([]);
    const out: IngestResult[] = [];
    for (const f of list) {
      try { out.push(await uploadEvidence(projectId, f)); }
      catch (e: any) { setErr(`${f.name}: ${e?.message || 'upload failed'}`); }
    }
    setResults(out);
    setBusy(false);
    await load();
    onChange?.();
  };

  return (
    <section className="panel">
      <div className="panelHead">
        <h3><FileUp size={18} /> Evidence ({items.length})</h3>
        <button className="secondary sm" onClick={load}><RefreshCw size={14} /> Refresh</button>
      </div>

      <label
        className={`dropzone compact ${drag ? 'over' : ''}`}
        onDragOver={e => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={e => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files); }}
      >
        <input ref={inputRef} type="file" multiple className="hidden"
               accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv,.json,.xml,.md,.eml,.msg"
               onChange={e => e.target.files && upload(e.target.files)} />
        {busy ? <LoaderCircle size={22} className="spin" /> : <FileUp size={22} />}
        <strong>{busy ? 'Ingesting…' : 'Drag documents here, or click to browse'}</strong>
        <span>RFI · RFP · RFQ · SOW · schemas · notes · PDF, DOCX, XLSX, PPTX, TXT, CSV, EML</span>
      </label>

      {err && <div className="notice error">{err}</div>}

      {/* What classification actually decided */}
      {results.map((r, i) => (
        <div className={`ingestResult ${r.duplicate ? 'dupe' : ''}`} key={i}>
          {r.duplicate ? <Copy size={15} /> : <CheckCircle2 size={15} />}
          <div>
            <strong>{r.name}</strong>
            <p>{r.message}</p>
            {!r.duplicate && (
              <div className="ingestTags">
                <span className="typeTag">{TYPE_LABEL[r.document_type || ''] || r.document_type}</span>
                <span className="confTag">{r.confidence} confidence</span>
                {r.sensitivity && r.sensitivity !== 'normal' && (
                  <span className="sensTag"><ShieldAlert size={11} /> {r.sensitivity.toUpperCase()}</span>
                )}
                <span className="muted">{r.characters?.toLocaleString()} chars · {r.chunks} chunks</span>
              </div>
            )}
          </div>
        </div>
      ))}

      {items.length > 0 && (
        <div className="tableWrap" style={{marginTop: 12}}>
          <table className="dataTable">
            <thead><tr><th>Document</th><th>Type</th><th>Sensitivity</th>
              <th>Size</th><th>Chunks</th><th>Status</th></tr></thead>
            <tbody>
              {items.map(e => (
                <tr key={e.id}>
                  <td><FileText size={13} /> {e.name}</td>
                  <td><span className="typeTag">{TYPE_LABEL[e.document_type] || e.document_type}</span></td>
                  <td>{e.sensitivity === 'normal'
                    ? <span className="muted">normal</span>
                    : <span className="sensTag"><ShieldAlert size={11} /> {e.sensitivity.toUpperCase()}</span>}</td>
                  <td>{(e.size_bytes / 1024).toFixed(1)} KB</td>
                  <td>{e.chunks}</td>
                  <td>{e.status === 'processed'
                    ? <span className="okIcon">processed</span>
                    : <span className="errIcon">{e.status}</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
