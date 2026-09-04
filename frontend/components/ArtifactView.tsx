'use client';
/**
 * Human-readable artifact rendering.
 *
 * Raw JSON is a debugging view, not a delivery view — a business stakeholder
 * cannot read `{"objectives": [...]}`. Each artifact kind gets a purpose-built
 * layout; anything unrecognised falls back to a structured document view rather
 * than a code dump. Raw JSON stays available behind a toggle for engineers.
 */
import {useEffect, useMemo, useState} from 'react';
import {
  Target, Users, Server, Database, AlertTriangle, HelpCircle, CheckCircle2,
  Braces, FileText, Layers, GitBranch, Shield, Gauge, ArrowRight, Boxes,
  ChevronDown, ChevronRight, ListTree,
} from 'lucide-react';
import {AiExecutionEvidence} from './AiExecutionEvidence';

/* ------------------------------------------------------------------ helpers */
const label = (k: string) =>
  k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

const asList = (v: any): any[] =>
  v == null ? [] : Array.isArray(v) ? v : typeof v === 'object' ? Object.values(v) : [v];

const textOf = (v: any): string => {
  if (v == null) return '';
  if (typeof v === 'string') return v;
  if (typeof v === 'object') {
    for (const k of ['text', 'name', 'title', 'description', 'question', 'requirement']) {
      if (v[k]) return String(v[k]);
    }
    return Object.entries(v).filter(([, x]) => x != null && x !== '')
      .map(([k, x]) => `${label(k)}: ${x}`).join(' · ');
  }
  return String(v);
};

/** Sections rendered as cards, with the icon and tone that fit their meaning. */
const SECTION_STYLE: Record<string, {icon: any; tone: string}> = {
  objectives: {icon: Target, tone: 'blue'},
  processes: {icon: GitBranch, tone: 'blue'},
  actors: {icon: Users, tone: 'blue'},
  systems: {icon: Server, tone: 'slate'},
  sources: {icon: Database, tone: 'slate'},
  requirements: {icon: CheckCircle2, tone: 'cyan'},
  constraints: {icon: Shield, tone: 'amber'},
  risks: {icon: AlertTriangle, tone: 'red'},
  assumptions: {icon: HelpCircle, tone: 'amber'},
  unknowns: {icon: HelpCircle, tone: 'red'},
  next_steps: {icon: ArrowRight, tone: 'green'},
  gaps: {icon: AlertTriangle, tone: 'amber'},
  entities: {icon: Boxes, tone: 'slate'},
  metrics: {icon: Gauge, tone: 'cyan'},
  components: {icon: Layers, tone: 'blue'},
};

const HIDDEN = new Set([
  'generation_mode', 'reason', 'ai_enrichment', 'ai_enrichment_reason',
  'guardrails', 'summary', 'version', 'mode',
  'extracted_tables', 'requirement_table_summary',
]);

/* ------------------------------------------------------------------- pieces */
function Summary({text, degraded, reason}: {text: string; degraded?: boolean; reason?: string}) {
  if (!text && !degraded) return null;
  return (
    <div className={`avSummary ${degraded ? 'degraded' : ''}`}>
      {degraded && (
        <div className="avDegraded">
          <AlertTriangle size={14} />
          <span>Evidence-only — no AI analysis was applied.{reason ? ` ${reason}` : ''}</span>
        </div>
      )}
      {text && <p>{text}</p>}
    </div>
  );
}


/** A collapsible block.

    Every section was rendered expanded inside a 520px scroll box, so a stage
    with a dozen sections became one undifferentiated wall of text that had to
    be scrolled past to find anything. Collapsed-by-default turns the artifact
    into a table of contents you open where you need detail. */
function Collapsible(
  {name, count, icon: Icon, tone = 'slate', defaultOpen = false, signal, children}:
  {name: string; count?: number; icon?: any; tone?: string; defaultOpen?: boolean;
   signal?: {version: number; open: boolean}; children: React.ReactNode},
) {
  const [open, setOpen] = useState(defaultOpen);
  const version = signal?.version ?? 0;

  // Expand-all / collapse-all overrides local state without unmounting.
  useEffect(() => {
    if (version > 0 && signal) setOpen(signal.open);
  }, [version]);   // eslint-disable-line react-hooks/exhaustive-deps

  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <section className={`avSection tone-${tone} ${open ? 'isOpen' : 'isClosed'}`}>
      <header role="button" tabIndex={0}
              onClick={() => setOpen(!open)}
              onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen(!open); } }}>
        <Chevron size={13} className="avChev" />
        {Icon && <Icon size={14} />}
        <h4>{label(name)}</h4>
        {count !== undefined && <span>{count}</span>}
      </header>
      {open && <div className="avBody">{children}</div>}
    </section>
  );
}

function SectionCard({name, items, defaultOpen, signal}:
                     {name: string; items: any[]; defaultOpen?: boolean;
                      signal?: {version: number; open: boolean}}) {
  const style = SECTION_STYLE[name] || {icon: FileText, tone: 'slate'};
  if (!items.length) return null;
  return (
    <Collapsible name={name} count={items.length} icon={style.icon} tone={style.tone}
                 defaultOpen={defaultOpen} signal={signal}>
      <ul>
        {items.map((it, i) => {
          const prov = typeof it === 'object' && it?.provenance;
          return (
            <li key={i}>
              <span>{textOf(it)}</span>
              {prov && <em className={`avProv p-${String(prov).toLowerCase()}`}>{String(prov).replace(/_/g, ' ')}</em>}
            </li>
          );
        })}
      </ul>
    </Collapsible>
  );
}

/** Assessment dimensions as a status grid rather than nested JSON. */
function Dimensions({dimensions}: {dimensions: Record<string, any>}) {
  const entries = Object.entries(dimensions || {});
  if (!entries.length) return null;
  return (
    <section className="avSection tone-slate">
      <header><Gauge size={14} /><h4>Readiness by dimension</h4><span>{entries.length}</span></header>
      <div className="avDimGrid">
        {entries.map(([name, value]: [string, any]) => {
          const status = String(value?.status || 'UNKNOWN').toUpperCase();
          return (
            <div className={`avDim s-${status.toLowerCase().replace(/[^a-z]/g, '')}`} key={name}>
              <div className="avDimTop"><strong>{label(name)}</strong><span>{status}</span></div>
              <ul>{asList(value?.findings).slice(0, 3).map((f, i) => <li key={i}>{textOf(f)}</li>)}</ul>
            </div>
          );
        })}
      </div>
    </section>
  );
}

/** Architecture components laid out as the layered diagram they describe. */
function ArchitectureLayers({components}: {components: any[]}) {
  const ORDER = ['sources', 'ingestion', 'storage', 'processing', 'serving',
                 'consumption', 'governance', 'operations'];
  const byLayer = useMemo(() => {
    const m: Record<string, any[]> = {};
    components.forEach(c => {
      const l = String(c?.layer || 'processing').toLowerCase();
      (m[l] ||= []).push(c);
    });
    return m;
  }, [components]);

  const layers = [...ORDER.filter(l => byLayer[l]),
                  ...Object.keys(byLayer).filter(l => !ORDER.includes(l))];
  if (!layers.length) return null;

  return (
    <section className="avSection tone-blue">
      <header><Layers size={14} /><h4>Architecture layers</h4><span>{components.length}</span></header>
      <div className="avFlow">
        {layers.map((l, i) => (
          <div className="avFlowItem" key={l}>
            <div className="avLayer">
              <div className="avLayerName">{label(l)}</div>
              {byLayer[l].map((c, j) => (
                <div className="avComponent" key={j}>
                  <strong>{c?.name || textOf(c)}</strong>
                  {c?.purpose && <small>{c.purpose}</small>}
                  {c?.technology && <em>{c.technology}</em>}
                </div>
              ))}
            </div>
            {i < layers.length - 1 && <ArrowRight size={15} className="avArrow" />}
          </div>
        ))}
      </div>
    </section>
  );
}

/** Platform options as comparison bars, not a table of numbers. */
function PlatformOptions({options}: {options: any[]}) {
  if (!options?.length) return null;
  const max = Math.max(...options.map(o => Number(o?.fit) || 0), 1);
  return (
    <section className="avSection tone-cyan">
      <header><Gauge size={14} /><h4>Platform fit</h4><span>{options.length}</span></header>
      {options.map((o, i) => (
        <div className={`avBarRow ${o?.recommended ? 'rec' : ''}`} key={i}>
          <span className="avBarName">
            {o?.platform || o?.option}
            {o?.recommended && <em>recommended</em>}
          </span>
          <div className="avBar"><i style={{width: `${((Number(o?.fit) || 0) / max) * 100}%`}} /></div>
          <b>{o?.fit}%</b>
        </div>
      ))}
    </section>
  );
}

/** Requirements mined from a customer tracker, shown as the table they came from. */
function RequirementTable({summary, tables}: {summary: any; tables: any[]}) {
  const rows = (tables || []).flatMap((t: any) => (t.requirements || []));
  if (!rows.length) return null;
  return (
    <section className="avSection tone-cyan">
      <header>
        <CheckCircle2 size={14} /><h4>Requirements extracted from customer tracker</h4>
        <span>{summary?.requirement_count ?? rows.length}</span>
      </header>
      {summary && (
        <div className="avReqStats">
          <span><b>{summary.answered ?? 0}</b> answered</span>
          <span className={summary.unanswered ? 'warn' : ''}>
            <b>{summary.unanswered ?? 0}</b> unanswered
          </span>
          {Object.entries(summary.categories || {}).slice(0, 5).map(([c, n]: any) => (
            <span key={c}>{c} <b>{n}</b></span>
          ))}
        </div>
      )}
      <div className="tableWrap">
        <table className="dataTable avReqTable">
          <thead><tr><th>Ref</th><th>Requirement</th><th>Category</th>
            <th>Priority</th><th>Response</th><th>Source</th></tr></thead>
          <tbody>
            {rows.slice(0, 80).map((r: any, i: number) => (
              <tr key={i} className={r.answered ? '' : 'unanswered'}>
                <td>{r.ref || '—'}</td>
                <td className="stmtCell">{r.text}</td>
                <td>{r.category || '—'}</td>
                <td>{r.priority || '—'}</td>
                <td>{r.response || <em className="avPending">pending</em>}</td>
                <td><code>{String(r.locator || '').split('::').pop()}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** A nested object rendered as a labelled block instead of being dropped.

    Agents return grouped fields — {mvp_goal, business_outcomes, scope, ...} —
    which are neither an array (no SectionCard) nor a scalar (no KeyValues), so
    the document view showed nothing and only Raw JSON carried the content. */
function NestedBlock({name, value, defaultOpen, signal}:
                     {name: string; value: Record<string, any>; defaultOpen?: boolean;
                      signal?: {version: number; open: boolean}}) {
  const entries = Object.entries(value).filter(([, v]) => v != null && v !== '');
  if (!entries.length) return null;
  const style = SECTION_STYLE[name] || {icon: FileText, tone: 'slate'};
  return (
    <Collapsible name={name} count={entries.length} icon={style.icon}
                 tone={style.tone} defaultOpen={defaultOpen} signal={signal}>
      <dl className="avKv">
        {entries.map(([k, v]) => (
          <div key={k}>
            <dt>{label(k)}</dt>
            <dd>
              {Array.isArray(v)
                ? <ul className="avNestedList">{v.map((x, i) => <li key={i}>{textOf(x)}</li>)}</ul>
                : textOf(v)}
            </dd>
          </div>
        ))}
      </dl>
    </Collapsible>
  );
}

function KeyValues({data, signal}:
                   {data: Record<string, any>; signal?: {version: number; open: boolean}}) {
  const rows = Object.entries(data).filter(
    ([k, v]) => !HIDDEN.has(k) && (typeof v !== 'object' || v === null));
  if (!rows.length) return null;
  return (
    <Collapsible name="details" count={rows.length} icon={FileText} signal={signal}>
      <dl className="avKv">
        {rows.map(([k, v]) => (
          <div key={k}><dt>{label(k)}</dt><dd>{String(v)}</dd></div>
        ))}
      </dl>
    </Collapsible>
  );
}

/* -------------------------------------------------------------------- main */
export function ArtifactView({kind, content, executionId}:
                             {kind: string; content: any; executionId?: string}) {
  const [raw, setRaw] = useState(false);
  // Bumping `version` re-applies `open` to every section without remounting,
  // so expand-all and collapse-all work on blocks that manage their own state.
  const [signal, setSignal] = useState({version: 0, open: false});
  const setAll = (open: boolean) =>
    setSignal(s => ({version: s.version + 1, open}));

  const data = useMemo(() => {
    if (typeof content === 'string') {
      try { return JSON.parse(content); } catch { return {text: content}; }
    }
    return content ?? {};
  }, [content]);

  const isObject = data && typeof data === 'object' && !Array.isArray(data);
  const degraded = isObject &&
    (data.generation_mode === 'deterministic_evidence_only' || data.ai_enrichment === 'unavailable');

  const sections = useMemo(() => {
    if (!isObject) return [];
    return Object.entries(data)
      .filter(([k, v]) => !HIDDEN.has(k) && Array.isArray(v) && v.length)
      .map(([k, v]) => ({name: k, items: v as any[]}));
  }, [data, isObject]);

  const nested = useMemo(() => {
    if (!isObject) return [] as {name: string; value: Record<string, any>}[];
    return Object.entries(data)
      .filter(([k, v]) => !HIDDEN.has(k) && v && typeof v === 'object'
                          && !Array.isArray(v) && k !== 'dimensions'
                          && Object.keys(v).length > 0)
      .map(([k, v]) => ({name: k, value: v as Record<string, any>}));
  }, [data, isObject]);

  const body = (
    <>
      <AiExecutionEvidence artifact={isObject ? data : null} executionId={executionId} />

      <Summary text={isObject ? textOf(data.summary) : ''} degraded={degraded}
               reason={isObject ? textOf(data.reason || data.ai_enrichment_reason) : ''} />

      {isObject && Array.isArray(data.extracted_tables) && data.extracted_tables.length > 0 &&
        <RequirementTable summary={data.requirement_table_summary} tables={data.extracted_tables} />}
      {isObject && data.dimensions && <Dimensions dimensions={data.dimensions} />}
      {isObject && Array.isArray(data.components) && data.components.length > 0 &&
        <ArchitectureLayers components={data.components} />}
      {isObject && Array.isArray(data.options) && data.options.length > 0 &&
        <PlatformOptions options={data.options} />}

      {sections
        .filter(s => !(s.name === 'components' || s.name === 'options'))
        .map((s, i) => <SectionCard key={s.name} name={s.name} items={s.items}
                                    defaultOpen={i < 2} signal={signal} />)}

      {nested.map(n => <NestedBlock key={n.name} name={n.name} value={n.value}
                                    signal={signal} />)}

      {isObject && <KeyValues data={data} signal={signal} />}

      {!isObject && (
        <section className="avSection tone-slate">
          <header><FileText size={14} /><h4>Content</h4></header>
          <p className="avPlain">{typeof data === 'string' ? data : JSON.stringify(data)}</p>
        </section>
      )}
    </>
  );

  // Scalar-only artifacts still have content; KeyValues renders them. Treating
  // "no recognised section" as empty hid real data behind a false message.
  const scalarFields = isObject
    ? Object.entries(data).filter(([k, v]) => !HIDDEN.has(k) && (typeof v !== 'object' || v === null)).length
    : 0;
  const empty = !degraded && !sections.length && !nested.length && isObject
    && !data.summary && !data.dimensions && !data.components && scalarFields === 0;

  return (
    <div className="artifactView">
      <div className="avToolbar">
        <span className="avKind">{label(kind)}</span>
        {!raw && !empty && (
          <div className="avExpand">
            <button onClick={() => setAll(true)}><ListTree size={12} /> Expand all</button>
            <button onClick={() => setAll(false)}>Collapse all</button>
          </div>
        )}
        <button className={raw ? 'avToggle on' : 'avToggle'} onClick={() => setRaw(!raw)}>
          <Braces size={13} /> {raw ? 'Document view' : 'Raw JSON'}
        </button>
      </div>

      {raw ? (
        <pre className="artifactCode">{JSON.stringify(data, null, 2)}</pre>
      ) : empty ? (
        <div className="empty">This artifact has no readable content yet.</div>
      ) : body}
    </div>
  );
}
