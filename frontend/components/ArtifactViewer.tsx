'use client';
/**
 * Renders the artifacts a stage produced. The backend has always persisted
 * these via /artifacts and /artifacts/{kind}; nothing in the UI read them,
 * so generated deliverables were invisible. This is that missing surface.
 */
import {useEffect, useMemo, useRef, useState} from 'react';
import {FileJson, Download, RefreshCw, Copy, Check, FileText, ChevronRight} from 'lucide-react';
import {getArtifacts, getArtifact, type ArtifactSummary} from '../lib/api';
import {ArtifactView} from './ArtifactView';

function download(name: string, content: string) {
  const blob = new Blob([content], {type: 'application/json'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

function prettify(content: any): string {
  if (content == null) return '';
  if (typeof content === 'string') {
    try { return JSON.stringify(JSON.parse(content), null, 2); } catch { return content; }
  }
  try { return JSON.stringify(content, null, 2); } catch { return String(content); }
}

/** Human labels for backend artifact kinds. */
const KIND_LABELS: Record<string, string> = {
  intake_pack: 'Intake Pack',
  discovery: 'Discovery Evidence',
  environment_assessment: 'Environment Assessment',
  assessment: 'Current-State Assessment',
  blueprint: 'Solution Blueprint',
  architecture: 'Architecture',
  metadata: 'Engineering Metadata',
  engineering: 'Engineering Components',
  qa: 'Quality Evidence',
  full_qa: 'Full QA Evidence',
  bi: 'BI & Analytics Products',
  application: 'Application Assets',
  validation: 'Validation Results',
  platform: 'Platform Configuration',
};
export function kindLabel(kind: string) {
  return KIND_LABELS[kind] || kind.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

export function ArtifactViewer({
  engagementId,
  filterKinds,
  title = 'Generated artifacts',
  emptyHint = 'Run this stage to generate governed artifacts.',
  refreshKey = 0,
  onStale,
}: {
  engagementId: string | null;
  filterKinds?: string[];
  title?: string;
  emptyHint?: string;
  /** Called when the selected engagement turns out not to exist. */
  onStale?: (engagementId: string) => void;
  /** Bumped by the parent when a stage completes, so freshly generated
   *  artifacts appear without the user having to press Refresh. */
  refreshKey?: number;
}) {
  const [items, setItems] = useState<ArtifactSummary[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');
  const [copied, setCopied] = useState(false);

  // Requests are generation-stamped. Selecting a different engagement while one
  // is in flight used to let the older, slower response overwrite the newer
  // result — which is how a stale id produced "Engagement not found" beside a
  // populated evidence snapshot.
  const generation = useRef(0);

  const load = async () => {
    if (!engagementId) return;
    const mine = ++generation.current;
    const requestedFor = engagementId;
    setLoading(true);
    setErr('');
    try {
      const r = await getArtifacts(requestedFor);
      if (mine !== generation.current) return;   // superseded
      const all = r.items || [];
      const shown = filterKinds?.length ? all.filter(a => filterKinds.includes(a.kind)) : all;
      setItems(shown);
      if (shown.length && !shown.some(a => a.kind === active)) setActive(shown[0].kind);
    } catch (e: any) {
      if (mine !== generation.current) return;   // superseded
      const message = e?.message || 'Unable to load artifacts';
      // A "not found" here means the selected engagement no longer exists —
      // report that plainly instead of a bare backend string, and let the
      // parent re-sync rather than leaving a dead panel.
      if (/not found/i.test(message)) {
        setItems([]);
        setErr('This engagement no longer exists. Pick another from the selector above.');
        onStale?.(requestedFor);
      } else {
        setErr(message);
      }
    } finally {
      if (mine === generation.current) setLoading(false);
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [engagementId, filterKinds?.join(','), refreshKey]);

  useEffect(() => {
    if (!engagementId || !active) { setDetail(null); return; }
    let cancelled = false;
    getArtifact(engagementId, active)
      .then(r => { if (!cancelled) setDetail(r.artifact); })
      .catch(() => { if (!cancelled) setDetail(null); });
    return () => { cancelled = true; };
  }, [engagementId, active]);

  const text = useMemo(() => prettify(detail?.content), [detail]);

  if (!engagementId) return null;

  return (
    <section className="panel artifactPanel">
      <div className="panelHead">
        <h3><FileJson size={18} /> {title}</h3>
        <button className="secondary sm" onClick={load} disabled={loading}>
          <RefreshCw size={15} className={loading ? 'spin' : ''} /> Refresh
        </button>
      </div>

      {err && <div className="notice error">{err}</div>}

      {items.length === 0 ? (
        <div className="empty"><FileText size={18} /> {loading ? 'Loading artifacts…' : emptyHint}</div>
      ) : (
        <div className="artifactLayout">
          <ul className="artifactList">
            {items.map(a => (
              <li key={a.id || a.kind}>
                <button
                  className={a.kind === active ? 'artifactItem active' : 'artifactItem'}
                  onClick={() => setActive(a.kind)}
                >
                  <span>{kindLabel(a.kind)}</span>
                  <ChevronRight size={14} />
                </button>
              </li>
            ))}
          </ul>

          <div className="artifactBody">
            {detail ? (
              <>
                <div className="artifactBar">
                  <code>{detail.kind}</code>
                  <div className="artifactActions">
                    <button
                      className="secondary sm"
                      onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); }}
                    >
                      {copied ? <Check size={15} /> : <Copy size={15} />} {copied ? 'Copied' : 'Copy'}
                    </button>
                    <button className="secondary sm" onClick={() => download(`${detail.kind}.json`, text)}>
                      <Download size={15} /> Download
                    </button>
                  </div>
                </div>
                <ArtifactView kind={detail.kind} content={detail.content} />
              </>
            ) : (
              <div className="empty">Select an artifact to inspect its evidence.</div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
