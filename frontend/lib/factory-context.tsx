'use client';
/** Selected factory project, shared across the Delivery Factory pages. */
import {createContext, useCallback, useContext, useEffect, useMemo, useState} from 'react';
import {
  createFactoryProject, getProjectLifecycle, listFactoryProjects,
  type FactoryProject, type ProjectLifecycle,
} from './factory-api';

const KEY = 'eliteintelia_factory_project';

type Ctx = {
  projectId: string | null;
  project: FactoryProject | null;
  projects: FactoryProject[];
  lifecycle: ProjectLifecycle | null;
  loading: boolean;
  error: string;
  select: (id: string | null) => void;
  refresh: () => Promise<void>;
  create: (b: {name: string; intent?: string; domain?: string}) => Promise<string>;
};

const FactoryContext = createContext<Ctx | null>(null);

export function useFactory(): Ctx {
  const c = useContext(FactoryContext);
  if (!c) throw new Error('useFactory must be used inside <FactoryProvider>');
  return c;
}

export function FactoryProvider({children}: {children: React.ReactNode}) {
  const [projectId, setProjectId] = useState<string | null>(null);
  const [projects, setProjects] = useState<FactoryProject[]>([]);
  const [lifecycle, setLifecycle] = useState<ProjectLifecycle | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const stored = localStorage.getItem(KEY);
    if (stored) setProjectId(stored);
  }, []);

  const loadList = useCallback(async () => {
    try {
      const r = await listFactoryProjects();
      setProjects(r.items || []);
      setProjectId(prev => {
        if (prev && (r.items || []).some(p => p.id === prev)) return prev;
        const first = (r.items || [])[0]?.id ?? null;
        if (first && typeof window !== 'undefined') localStorage.setItem(KEY, first);
        return first;
      });
      setError('');
    } catch (e: any) {
      setError(e?.message || 'Unable to load projects');
    } finally {
      setLoading(false);
    }
  }, []);

  const refresh = useCallback(async () => {
    await loadList();
    if (!projectId) { setLifecycle(null); return; }
    try {
      setLifecycle(await getProjectLifecycle(projectId));
    } catch {
      setLifecycle(null);
    }
  }, [loadList, projectId]);

  useEffect(() => { loadList(); }, [loadList]);
  useEffect(() => {
    if (!projectId) { setLifecycle(null); return; }
    getProjectLifecycle(projectId).then(setLifecycle).catch(() => setLifecycle(null));
  }, [projectId]);

  const select = useCallback((id: string | null) => {
    setProjectId(id);
    if (typeof window === 'undefined') return;
    if (id) localStorage.setItem(KEY, id); else localStorage.removeItem(KEY);
  }, []);

  const create = useCallback(async (b: {name: string; intent?: string; domain?: string}) => {
    const r = await createFactoryProject(b);
    await loadList();
    select(r.id);
    return r.id;
  }, [loadList, select]);

  const project = useMemo(
    () => projects.find(p => p.id === projectId) || null, [projects, projectId]);

  const value = useMemo(
    () => ({projectId, project, projects, lifecycle, loading, error, select, refresh, create}),
    [projectId, project, projects, lifecycle, loading, error, select, refresh, create]);

  return <FactoryContext.Provider value={value}>{children}</FactoryContext.Provider>;
}
