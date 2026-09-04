'use client';
/**
 * Transformation Studio — visual data engineering.
 *
 * Matillion  : drag-and-drop canvas + component palette
 * Prophecy   : the DAG compiles to real dbt SQL and PySpark, live
 * Coalesce   : column-aware nodes, materializations, column-level lineage
 * dbt Labs   : models with ref(), generic tests, schema.yml, DAG order
 *
 * The graph is the single source of truth; code is always regenerated from it,
 * so the visual pipeline and the emitted code can never drift apart.
 */
import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {
  ReactFlow, Background, Controls, MiniMap, addEdge, useEdgesState, useNodesState,
  type Connection, type Edge, type Node, MarkerType,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  Database, Filter, Columns3, GitMerge, Sigma, Combine, Code2, Target,
  Save, Play, CircleAlert, CheckCircle2, Download, Workflow, FileCode2, GitBranch, LoaderCircle,
  Table2, FlaskConical, XCircle,
} from 'lucide-react';
import {StudioNodeView} from './StudioNode';
import {Inspector} from './Inspector';
import {
  getPalette, compilePipeline, getPipeline, savePipeline, runPipeline, runEngagementPipeline,
  type Pipeline, type StudioNode, type Compiled, type RunResult,
} from '../../lib/api';
import {useEngagement} from '../../lib/engagement-context';

const nodeTypes = {studioNode: StudioNodeView};

const PALETTE_ICONS: Record<string, any> = {
  source: Database, filter: Filter, select: Columns3, join: GitMerge,
  aggregate: Sigma, union: Combine, sql: Code2, target: Target,
};

let idSeq = 0;
const nextId = () => `n${Date.now().toString(36)}${(idSeq++).toString(36)}`;

/** Domain pipeline -> React Flow nodes/edges. */
function toFlow(p: Pipeline, inputsFor: (t: string) => number, errorNames: Set<string>) {
  const nodes: Node[] = (p.nodes || []).map(n => ({
    id: n.id,
    type: 'studioNode',
    position: n.position || {x: 0, y: 0},
    data: {
      ...n,
      inputs: inputsFor(n.type),
      materialization: n.config?.materialization,
      hasError: errorNames.has(n.name),
    },
  }));
  const edges: Edge[] = (p.edges || []).map(e => ({
    id: e.id,
    source: e.source,
    target: e.target,
    targetHandle: e.targetHandle ?? null,
    animated: true,
    markerEnd: {type: MarkerType.ArrowClosed, width: 16, height: 16},
  }));
  return {nodes, edges};
}

export function Studio() {
  const {engagementId} = useEngagement();
  const [palette, setPalette] = useState<any>(null);
  const [pipeline, setPipeline] = useState<Pipeline>({name: 'pipeline', nodes: [], edges: []});
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [compiled, setCompiled] = useState<Compiled | null>(null);
  const [tab, setTab] = useState<'sql' | 'yml' | 'spark' | 'lineage' | 'data'>('sql');
  const [run, setRun] = useState<RunResult | null>(null);
  const [running, setRunning] = useState(false);
  const [engine, setEngine] = useState<'sandbox' | 'databricks'>('sandbox');
  const [activeModel, setActiveModel] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');
  const wrapRef = useRef<HTMLDivElement>(null);

  const inputsFor = useCallback(
    (t: string) => palette?.node_types?.[t]?.inputs ?? 1,
    [palette]
  );

  /* ------------------------------------------------------------- bootstrap */
  useEffect(() => {
    (async () => {
      try {
        const p = await getPalette();
        setPalette(p);
        let initial = p.starter;
        if (engagementId) {
          try { initial = (await getPipeline(engagementId)).pipeline; } catch { /* use starter */ }
        }
        setPipeline(initial);
      } catch (e: any) {
        setMsg(e?.message || 'Unable to load the studio palette.');
      }
    })();
  }, [engagementId]);

  /* ------------------------------- keep flow in sync with the domain model */
  const errorNames = useMemo(() => {
    const s = new Set<string>();
    (compiled?.errors || []).forEach(err => {
      (pipeline.nodes || []).forEach(n => { if (err.includes(n.name)) s.add(n.name); });
    });
    return s;
  }, [compiled, pipeline.nodes]);

  useEffect(() => {
    if (!palette) return;
    const {nodes: fn, edges: fe} = toFlow(pipeline, inputsFor, errorNames);
    setNodes(fn);
    setEdges(fe);
  }, [pipeline, palette, inputsFor, errorNames, setNodes, setEdges]);

  /* ------------------------------------------------- live compile (debounced) */
  useEffect(() => {
    if (!pipeline.nodes?.length) { setCompiled(null); return; }
    const t = setTimeout(async () => {
      try {
        const r = await compilePipeline(pipeline);
        setCompiled(r);
        setActiveModel(prev => (r.models.some(m => m.name === prev) ? prev : r.models[0]?.name ?? null));
      } catch (e: any) {
        setMsg(e?.message || 'Compile failed.');
      }
    }, 350);
    return () => clearTimeout(t);
  }, [pipeline]);

  /* --------------------------------------------------------------- mutations */
  const patchNode = (id: string, patch: Partial<StudioNode>) =>
    setPipeline(p => ({...p, nodes: p.nodes.map(n => (n.id === id ? {...n, ...patch} : n))}));

  const addNode = (type: string) => {
    const count = pipeline.nodes.filter(n => n.type === type).length + 1;
    const node: StudioNode = {
      id: nextId(),
      type,
      name: `${type}_${count}`,
      layer: type === 'source' ? 'bronze' : type === 'target' ? 'gold' : 'silver',
      position: {x: 120 + (pipeline.nodes.length % 5) * 60, y: 140 + (pipeline.nodes.length % 6) * 70},
      config: {materialization: type === 'target' ? 'table' : 'view'},
      columns: [],
    };
    setPipeline(p => ({...p, nodes: [...p.nodes, node]}));
    setSelected(node.id);
  };

  const deleteNode = (id: string) => {
    setPipeline(p => ({
      ...p,
      nodes: p.nodes.filter(n => n.id !== id),
      edges: p.edges.filter(e => e.source !== id && e.target !== id),
    }));
    setSelected(null);
  };

  const onConnect = useCallback((c: Connection) => {
    setPipeline(p => {
      // Respect node arity: a 1-input node cannot accept a second edge.
      const target = p.nodes.find(n => n.id === c.target);
      const max = target ? inputsFor(target.type) : 1;
      const existing = p.edges.filter(e => e.target === c.target);
      if (existing.length >= max) return p;
      if (c.source === c.target) return p;
      return {
        ...p,
        edges: [...p.edges, {
          id: `e${Date.now().toString(36)}`,
          source: c.source!, target: c.target!,
          targetHandle: c.targetHandle || undefined,
        }],
      };
    });
    setEdges(eds => addEdge({...c, animated: true, markerEnd: {type: MarkerType.ArrowClosed}}, eds));
  }, [inputsFor, setEdges]);

  // Persist node drags back into the domain model.
  const onNodeDragStop = useCallback((_: any, node: Node) => {
    patchNode(node.id, {position: node.position});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = async () => {
    if (!engagementId) { setMsg('Select an engagement to save this pipeline.'); return; }
    setSaving(true); setMsg('');
    try {
      const r = await savePipeline(engagementId, pipeline);
      setCompiled(r.compiled);
      setMsg(r.compiled.ok
        ? `Saved. ${r.compiled.stats?.models ?? 0} dbt models, ${r.compiled.stats?.tests ?? 0} tests and the PySpark job were persisted as artifacts.`
        : 'Saved the graph, but compilation reported errors.');
    } catch (e: any) { setMsg(e?.message || 'Save failed.'); }
    finally { setSaving(false); }
  };

  const execute = async () => {
    if (running) return;
    setRunning(true); setMsg('');
    try {
      const r = engagementId
        ? await runEngagementPipeline(engagementId, pipeline, engine)
        : await runPipeline(pipeline, engine);
      setRun(r);
      setTab('data');
      setMsg(r.ok
        ? `Run complete on ${r.engine}: ${(r.nodes || []).length} models, ${r.tests?.filter(t => t.status === 'pass').length ?? 0}/${r.tests?.length ?? 0} tests passed.`
        : (r.message || 'Run failed.'));
    } catch (e: any) { setMsg(e?.message || 'Run failed.'); }
    finally { setRunning(false); }
  };

  const selectedNode = pipeline.nodes.find(n => n.id === selected) || null;
  const model = compiled?.models.find(m => m.name === activeModel) || compiled?.models[0];

  const codeText = tab === 'sql' ? (model?.sql || '')
    : tab === 'yml' ? (compiled?.schema_yml || '')
    : tab === 'spark' ? (compiled?.pyspark || '') : '';

  const dl = (name: string, body: string) => {
    const url = URL.createObjectURL(new Blob([body], {type: 'text/plain'}));
    const a = document.createElement('a'); a.href = url; a.download = name; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="studio">
      {/* Palette */}
      <aside className="sPalette">
        <div className="sPaletteHead">Components</div>
        {palette && Object.entries(palette.node_types as Record<string, any>).map(([key, t]) => {
          const Icon = PALETTE_ICONS[key] || Code2;
          return (
            <button key={key} className="sPaletteItem" onClick={() => addNode(key)} title={t.description}>
              <span className={`sPaletteIcon ${t.category}`}><Icon size={14} /></span>
              <span className="sPaletteText"><strong>{t.label}</strong><small>{t.category}</small></span>
            </button>
          );
        })}

        {compiled?.stats && (
          <div className="sStats">
            <div className="sPaletteHead">Pipeline</div>
            <div><span>Models</span><b>{compiled.stats.models}</b></div>
            <div><span>Tests</span><b>{compiled.stats.tests}</b></div>
            <div><span>Sources</span><b>{compiled.stats.sources}</b></div>
            <div><span>Targets</span><b>{compiled.stats.targets}</b></div>
          </div>
        )}
      </aside>

      {/* Canvas + code */}
      <div className="sMain">
        <div className="sToolbar">
          <input className="sName" value={pipeline.name}
                 onChange={e => setPipeline(p => ({...p, name: e.target.value}))} />
          {compiled && (compiled.ok
            ? <span className="sBadge ok"><CheckCircle2 size={13} /> Compiles</span>
            : <span className="sBadge err"><CircleAlert size={13} /> {(compiled.errors || []).length} error(s)</span>)}
          <div className="sToolbarRight">
            <button className="secondary sm" onClick={() => dl(`${pipeline.name}.json`, JSON.stringify(pipeline, null, 2))}>
              <Download size={14} /> Export DAG
            </button>
            <select className="sInput sSm sEngine" value={engine} onChange={e => setEngine(e.target.value as any)} title="Execution engine">
              <option value="sandbox">Sandbox</option>
              <option value="databricks">Databricks</option>
            </select>
            <button className="secondary sm" onClick={execute} disabled={running || !compiled?.ok}>
              {running ? <LoaderCircle size={14} className="spin" /> : <Play size={14} />} Run
            </button>
            <button className="primary sm" onClick={save} disabled={saving || !engagementId}>
              {saving ? <LoaderCircle size={14} className="spin" /> : <Save size={14} />} Save &amp; Compile
            </button>
          </div>
        </div>

        {msg && <div className={`notice ${/fail|error/i.test(msg) ? 'error' : ''}`}>{msg}</div>}
        {compiled && !compiled.ok && (
          <div className="notice error">
            {(compiled.errors || []).map((e, i) => <div key={i}>• {e}</div>)}
          </div>
        )}

        <div className="sCanvas" ref={wrapRef}>
          <ReactFlow
            nodes={nodes} edges={edges}
            onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
            onConnect={onConnect} onNodeDragStop={onNodeDragStop}
            onNodeClick={(_, n) => setSelected(n.id)}
            onPaneClick={() => setSelected(null)}
            nodeTypes={nodeTypes}
            fitView proOptions={{hideAttribution: true}}
            defaultEdgeOptions={{animated: true}}
          >
            <Background gap={18} size={1} color="#22324a" />
            <Controls showInteractive={false} />
            {/* Width/height must be props: React Flow writes them as inline styles. */}
            <MiniMap pannable zoomable className="sMiniMap" style={{width: 130, height: 86}}
                     nodeColor={(n: any) => ({bronze: '#b4762e', silver: '#8fa3bd', gold: '#d4a017'}[n.data?.layer as string] || '#2ed7e8')} />
          </ReactFlow>
        </div>

        {/* Generated code — Prophecy-style visual↔code */}
        <div className={`sCode${tab === "data" ? " tall" : ""}`}>
          <div className="sCodeTabs">
            <button className={tab === 'sql' ? 'on' : ''} onClick={() => setTab('sql')}><FileCode2 size={14} /> dbt SQL</button>
            <button className={tab === 'yml' ? 'on' : ''} onClick={() => setTab('yml')}><Workflow size={14} /> schema.yml</button>
            <button className={tab === 'spark' ? 'on' : ''} onClick={() => setTab('spark')}><Code2 size={14} /> PySpark</button>
            <button className={tab === 'lineage' ? 'on' : ''} onClick={() => setTab('lineage')}><GitBranch size={14} /> Lineage</button>
            <button className={tab === 'data' ? 'on' : ''} onClick={() => setTab('data')}>
              <Table2 size={14} /> Data{run ? ` (${run.engine})` : ''}
            </button>
            <div className="sCodeRight">
              {tab === 'sql' && compiled && (
                <select className="sInput sSm" value={activeModel || ''} onChange={e => setActiveModel(e.target.value)}>
                  {(compiled.models || []).map(m => <option key={m.name} value={m.name}>{m.path}</option>)}
                </select>
              )}
              {tab !== 'lineage' && (
                <button className="secondary sm" onClick={() =>
                  dl(tab === 'sql' ? `${model?.name || 'model'}.sql` : tab === 'yml' ? 'schema.yml' : 'pipeline_job.py', codeText)}>
                  <Download size={14} />
                </button>
              )}
            </div>
          </div>

          {tab === 'data' ? (
            <div className="sData">
              {!run ? (
                <div className="empty"><Table2 size={18} /> Press <b>Run</b> to execute the pipeline and preview results.</div>
              ) : (
                <>
                  <div className="sRunBanner">{run.ok ? <CheckCircle2 size={14} /> : <XCircle size={14} />}<span>{run.message}</span></div>
                  {(run.nodes || []).map(n => (
                    <div className="sRunNode" key={n.model}>
                      <div className="sRunHead">
                        <strong>{n.model}</strong>
                        <span className={`sBadge ${n.status === 'success' ? 'ok' : 'err'}`}>{n.status}</span>
                        {n.row_count != null && <span className="sRows">{n.row_count} rows</span>}
                        {n.elapsed_ms != null && <span className="sMs">{n.elapsed_ms}ms</span>}
                      </div>
                      {n.error && <div className="sRunErr">{n.error}</div>}
                      {n.sample && n.sample.rows.length > 0 && (
                        <div className="tableWrap">
                          <table className="dataTable sPreview">
                            <thead><tr>{n.sample.columns.map(c => <th key={c}>{c}</th>)}</tr></thead>
                            <tbody>
                              {n.sample.rows.map((r, i) => (
                                <tr key={i}>{r.map((v, j) => <td key={j}>{v === null ? <em>null</em> : String(v)}</td>)}</tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  ))}
                  {!!run.tests?.length && (
                    <div className="sRunNode">
                      <div className="sRunHead"><FlaskConical size={14} /><strong>Data quality tests</strong>
                        <span className="sRows">{(run.tests || []).filter(t => t.status === 'pass').length}/{(run.tests || []).length} passed</span>
                      </div>
                      <div className="sTestGrid">
                        {(run.tests || []).map((t, i) => (
                          <div className={`sTestRes ${t.status}`} key={i}>
                            {t.status === 'pass' ? <CheckCircle2 size={12} /> : <XCircle size={12} />}
                            <code>{t.model}.{t.column}</code><span>{t.test}</span>
                            {t.failing_rows ? <b>{t.failing_rows}</b> : null}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          ) : tab === 'lineage' ? (
            <div className="sLineage">
              {(compiled?.lineage || []).length === 0
                ? <div className="empty">Add columns to nodes to generate column-level lineage.</div>
                : ((compiled!.lineage || []).map((l, i) => (
                    <div className="sLinRow" key={i}>
                      <code className="from">{l.from}</code>
                      <span className="arrow">→</span>
                      <code className="to">{l.to}</code>
                      {l.transform !== 'direct' && <span className="xf">{l.transform}</span>}
                    </div>
                  )))}
            </div>
          ) : (
            <pre className="sCodeBody">{codeText || '-- Build a pipeline to generate code'}</pre>
          )}
        </div>
      </div>

      <Inspector
        node={selectedNode}
        materializations={palette?.materializations || []}
        layers={palette?.layers || []}
        columnTests={palette?.column_tests || []}
        onChange={patch => selected && patchNode(selected, patch)}
        onDelete={() => selected && deleteNode(selected)}
        onClose={() => setSelected(null)}
      />
    </div>
  );
}
