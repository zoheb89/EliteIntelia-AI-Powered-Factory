'use client';
/** Column-aware pipeline node (Coalesce-style): shows layer, type and columns. */
import {Handle, Position, type NodeProps} from '@xyflow/react';
import {
  Database, Filter, Columns3, GitMerge, Sigma, Combine, Code2, Target, CircleAlert,
} from 'lucide-react';

const ICONS: Record<string, any> = {
  source: Database, filter: Filter, select: Columns3, join: GitMerge,
  aggregate: Sigma, union: Combine, sql: Code2, target: Target,
};

export function StudioNodeView({data, selected}: NodeProps) {
  const d = data as any;
  const Icon = ICONS[d.type] || Code2;
  const cols = (d.columns || []) as any[];
  const testCount = cols.reduce((n, c) => n + (c.tests?.length || 0), 0);
  const inputs = d.inputs ?? 1;

  return (
    <div className={`sNode ${d.layer || 'staging'} ${selected ? 'sel' : ''} ${d.hasError ? 'err' : ''}`}>
      {inputs > 0 && <Handle type="target" position={Position.Left} id="a" className="sHandle" />}
      {inputs > 1 && <Handle type="target" position={Position.Left} id="b" className="sHandle sHandleB" />}

      <div className="sNodeHead">
        <span className="sNodeIcon"><Icon size={13} /></span>
        <strong title={d.name}>{d.name}</strong>
        {d.hasError && <CircleAlert size={13} className="sErrIcon" />}
      </div>

      <div className="sNodeMeta">
        <span className={`sLayer ${d.layer || 'staging'}`}>{d.layer || 'staging'}</span>
        <span className="sMat">{d.materialization || 'view'}</span>
      </div>

      {cols.length > 0 && (
        <ul className="sCols">
          {cols.slice(0, 5).map((c, i) => (
            <li key={i}>
              <span className="sColName">{c.name}</span>
              {c.type && <span className="sColType">{c.type}</span>}
              {!!c.tests?.length && <span className="sColTest" title={c.tests.join(', ')}>{c.tests.length}</span>}
            </li>
          ))}
          {cols.length > 5 && <li className="sColMore">+{cols.length - 5} more</li>}
        </ul>
      )}

      <div className="sNodeFoot">
        <span>{cols.length} cols</span>
        {testCount > 0 && <span className="sTests">{testCount} tests</span>}
      </div>

      {d.type !== 'target' && <Handle type="source" position={Position.Right} className="sHandle" />}
    </div>
  );
}
