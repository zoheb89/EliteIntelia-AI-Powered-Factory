'use client';
/**
 * Accelerator catalogue.
 *
 * The market this sits in is a shelf of point tools — pipeline generators,
 * migration accelerators, delivery copilots, DevOps governance, consulting
 * frameworks. Each covers a slice. The claim here is that the slices run on
 * one governed backbone, so every accelerator names the lifecycle stages it
 * actually drives; nothing in this list is a capability the platform cannot
 * deliver.
 *
 * When an engagement is open, the catalogue splits into what that engagement's
 * own evidence calls for and what is merely available — a distinction the
 * reason line makes checkable.
 */
import {useEffect, useState} from 'react';
import {Boxes, Sparkles, Calculator, Blend, Search} from 'lucide-react';
import {getAcceleratorCatalogue, getProjectAccelerators,
        type AcceleratorCatalogue as Cat, type ProjectAccelerators} from '../lib/factory-api';

const ENGINE = {
  ai: {icon: Sparkles, label: 'AI', hint: 'a model reasons over the evidence'},
  deterministic: {icon: Calculator, label: 'Engine',
                  hint: 'calculated, reproducible, no model involved'},
  hybrid: {icon: Blend, label: 'AI + Engine',
           hint: 'AI proposes, a deterministic engine calculates'},
} as const;

function EngineTag({engine}: {engine: string}) {
  const e = ENGINE[engine as keyof typeof ENGINE] || ENGINE.hybrid;
  const Icon = e.icon;
  return <span className={`accEngine e-${engine}`} title={e.hint}>
    <Icon size={10} /> {e.label}
  </span>;
}

export function AcceleratorCatalogue({projectId}: {projectId?: string | null}) {
  const [cat, setCat] = useState<Cat | null>(null);
  const [mine, setMine] = useState<ProjectAccelerators | null>(null);
  const [q, setQ] = useState('');

  useEffect(() => { getAcceleratorCatalogue().then(setCat).catch(() => {}); }, []);

  // The catalogue is mounted on pages outside the factory provider, so the
  // open project is resolved from storage rather than from React context.
  useEffect(() => {
    let id = projectId ?? null;
    if (!id && typeof window !== 'undefined') {
      try { id = localStorage.getItem('eliteintelia_factory_project'); } catch { id = null; }
    }
    if (!id) { setMine(null); return; }
    getProjectAccelerators(id).then(setMine).catch(() => setMine(null));
  }, [projectId]);

  if (!cat) return null;
  const recommended = new Map((mine?.recommended || []).map(r => [r.id, r]));
  const needle = q.trim().toLowerCase();

  return (
    <section className="accWrap">
      <header className="accHead">
        <Boxes size={17} />
        <div>
          <h2>Accelerators</h2>
          <p>{cat.count} accelerators across {cat.categories.length} categories
            {mine ? ` · ${mine.recommended_count} indicated by this engagement's evidence` : ''}</p>
        </div>
        <div className="accSearch">
          <Search size={13} />
          <input value={q} onChange={e => setQ(e.target.value)}
                 placeholder="Filter accelerators" aria-label="Filter accelerators" />
        </div>
      </header>

      {cat.categories.map(c => {
        const items = c.accelerators.filter(a =>
          !needle || a.name.toLowerCase().includes(needle)
                  || a.summary.toLowerCase().includes(needle));
        if (!items.length) return null;
        return (
          <div className="accCat" key={c.id}>
            <div className="accCatHead">
              <h3>{c.label}</h3>
              <span>{c.description}</span>
            </div>
            <div className="accGrid">
              {items.map(a => {
                const rec = recommended.get(a.id);
                return (
                  <article className={`accCard ${rec ? 'isRec' : ''}`} key={a.id}>
                    <div className="accTop">
                      <strong>{a.name}</strong>
                      <EngineTag engine={a.engine} />
                    </div>
                    <p>{a.summary}</p>
                    {rec && <div className="accReason">{rec.reason}</div>}
                    <div className="accStages">
                      {a.stages.map(s => <span key={s}>{s.replace(/_/g, ' ')}</span>)}
                    </div>
                  </article>
                );
              })}
            </div>
          </div>
        );
      })}
      {mine && <footer className="accBasis">{mine.basis}</footer>}
    </section>
  );
}
