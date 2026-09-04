'use client';
/** Right-hand inspector: node config + column editor with dbt tests. */
import {Plus, Trash2, X} from 'lucide-react';
import type {StudioNode, StudioColumn} from '../../lib/api';

type Props = {
  node: StudioNode | null;
  materializations: string[];
  layers: string[];
  columnTests: string[];
  onChange: (patch: Partial<StudioNode>) => void;
  onDelete: () => void;
  onClose: () => void;
};

export function Inspector({node, materializations, layers, columnTests, onChange, onDelete, onClose}: Props) {
  if (!node) {
    return (
      <aside className="sInspector">
        <div className="sInspEmpty">Select a node to configure it, or drag a component from the palette.</div>
      </aside>
    );
  }

  const cfg = node.config || {};
  const cols = node.columns || [];
  const setCfg = (patch: Record<string, any>) => onChange({config: {...cfg, ...patch}});
  const setCols = (next: StudioColumn[]) => onChange({columns: next});
  const patchCol = (i: number, patch: Partial<StudioColumn>) =>
    setCols(cols.map((c, idx) => (idx === i ? {...c, ...patch} : c)));

  const toggleTest = (i: number, t: string) => {
    const cur = cols[i].tests || [];
    patchCol(i, {tests: cur.includes(t) ? cur.filter(x => x !== t) : [...cur, t]});
  };

  return (
    <aside className="sInspector">
      <div className="sInspHead">
        <strong>{node.name}</strong>
        <button className="sIconBtn" onClick={onClose} title="Close"><X size={15} /></button>
      </div>

      <div className="sInspBody">
        <label className="sLabel">Model name</label>
        <input className="sInput" value={node.name} onChange={e => onChange({name: e.target.value})} />

        <label className="sLabel">Description</label>
        <textarea className="sInput sArea" rows={2} value={node.description || ''}
                  onChange={e => onChange({description: e.target.value})}
                  placeholder="Shown in dbt docs (schema.yml)" />

        <div className="sRow2">
          <div>
            <label className="sLabel">Layer</label>
            <select className="sInput" value={node.layer || 'staging'} onChange={e => onChange({layer: e.target.value})}>
              <option value="staging">staging</option>
              {layers.map(l => <option key={l} value={l}>{l}</option>)}
            </select>
          </div>
          <div>
            <label className="sLabel">Materialization</label>
            <select className="sInput" value={cfg.materialization || 'view'} onChange={e => setCfg({materialization: e.target.value})}>
              {materializations.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
        </div>

        {cfg.materialization === 'incremental' && (
          <>
            <label className="sLabel">Unique key</label>
            <input className="sInput" value={cfg.unique_key || ''} onChange={e => setCfg({unique_key: e.target.value})} placeholder="order_id" />
          </>
        )}

        {/* Type-specific configuration */}
        {node.type === 'source' && (
          <div className="sRow2">
            <div>
              <label className="sLabel">Source</label>
              <input className="sInput" value={cfg.source_name || ''} onChange={e => setCfg({source_name: e.target.value})} placeholder="raw" />
            </div>
            <div>
              <label className="sLabel">Table</label>
              <input className="sInput" value={cfg.table || ''} onChange={e => setCfg({table: e.target.value})} placeholder="orders" />
            </div>
          </div>
        )}

        {node.type === 'filter' && (
          <>
            <label className="sLabel">Predicate (WHERE)</label>
            <textarea className="sInput sArea sMono" rows={2} value={cfg.predicate || ''}
                      onChange={e => setCfg({predicate: e.target.value})} placeholder="status <> 'cancelled'" />
          </>
        )}

        {node.type === 'join' && (
          <>
            <div className="sRow2">
              <div>
                <label className="sLabel">Join type</label>
                <select className="sInput" value={cfg.join_type || 'inner'} onChange={e => setCfg({join_type: e.target.value})}>
                  {['inner', 'left', 'right', 'full outer'].map(j => <option key={j} value={j}>{j}</option>)}
                </select>
              </div>
            </div>
            <label className="sLabel">On condition (l = first input, r = second)</label>
            <textarea className="sInput sArea sMono" rows={2} value={cfg.on || ''}
                      onChange={e => setCfg({on: e.target.value})} placeholder="l.customer_id = r.customer_id" />
          </>
        )}

        {node.type === 'sql' && (
          <>
            <label className="sLabel">SQL — use <code>{'{{input}}'}</code> for the upstream model</label>
            <textarea className="sInput sArea sMono" rows={6} value={cfg.sql || ''}
                      onChange={e => setCfg({sql: e.target.value})}
                      placeholder={'select *\nfrom {{input}}\nwhere 1 = 1'} />
          </>
        )}

        {node.type === 'aggregate' && (
          <>
            <label className="sLabel">Group by (comma separated)</label>
            <input className="sInput sMono" value={(cfg.group_by || []).join(', ')}
                   onChange={e => setCfg({group_by: e.target.value.split(',').map(s => s.trim()).filter(Boolean)})}
                   placeholder="customer_id" />
            <label className="sLabel">Measures</label>
            {(cfg.measures || []).map((m: any, i: number) => (
              <div className="sMeasure" key={i}>
                <select className="sInput sSm" value={m.fn || 'sum'}
                        onChange={e => setCfg({measures: (cfg.measures || []).map((x: any, ix: number) => ix === i ? {...x, fn: e.target.value} : x)})}>
                  {['sum', 'count', 'avg', 'min', 'max', 'countDistinct'].map(f => <option key={f} value={f}>{f}</option>)}
                </select>
                <input className="sInput sSm sMono" value={m.column || ''} placeholder="column"
                       onChange={e => setCfg({measures: (cfg.measures || []).map((x: any, ix: number) => ix === i ? {...x, column: e.target.value} : x)})} />
                <input className="sInput sSm sMono" value={m.alias || ''} placeholder="alias"
                       onChange={e => setCfg({measures: (cfg.measures || []).map((x: any, ix: number) => ix === i ? {...x, alias: e.target.value} : x)})} />
                <button className="sIconBtn" onClick={() => setCfg({measures: (cfg.measures || []).filter((_: any, ix: number) => ix !== i)})}>
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
            <button className="sAddBtn" onClick={() => setCfg({measures: [...(cfg.measures || []), {fn: 'sum', column: '', alias: ''}]})}>
              <Plus size={14} /> Add measure
            </button>
          </>
        )}

        {/* Column editor — the Coalesce-style column-aware layer */}
        <div className="sSectionHead">
          <span>Columns ({cols.length})</span>
          <button className="sAddBtn sm" onClick={() => setCols([...cols, {name: `column_${cols.length + 1}`, tests: []}])}>
            <Plus size={13} /> Add
          </button>
        </div>

        {cols.map((c, i) => (
          <div className="sColCard" key={i}>
            <div className="sColRow">
              <input className="sInput sSm sMono" value={c.name} placeholder="name"
                     onChange={e => patchCol(i, {name: e.target.value})} />
              <input className="sInput sSm sMono" value={c.type || ''} placeholder="type"
                     onChange={e => patchCol(i, {type: e.target.value})} />
              <button className="sIconBtn" onClick={() => setCols(cols.filter((_, ix) => ix !== i))}>
                <Trash2 size={14} />
              </button>
            </div>
            <input className="sInput sSm sMono" value={c.expression || ''} placeholder="expression (optional, e.g. upper(name))"
                   onChange={e => patchCol(i, {expression: e.target.value})} />
            <div className="sTestRow">
              {columnTests.map(t => (
                <button key={t} className={`sTestChip ${(c.tests || []).includes(t) ? 'on' : ''}`} onClick={() => toggleTest(i, t)}>
                  {t}
                </button>
              ))}
            </div>
          </div>
        ))}

        <button className="sDeleteBtn" onClick={onDelete}><Trash2 size={14} /> Delete node</button>
      </div>
    </aside>
  );
}
