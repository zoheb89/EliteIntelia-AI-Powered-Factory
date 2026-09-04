'use client';
/**
 * Global engagement + role context.
 *
 * Previously every page read localStorage independently, so a workspace opened
 * without an ?engagement= query param was a dead end. This provider makes the
 * selected engagement app-wide, survives navigation, and lets the top bar
 * switch engagements from anywhere.
 */
import {createContext, useCallback, useContext, useEffect, useMemo, useState} from 'react';
import {getEngagement, getEngagements, type Engagement} from './api';

const STORAGE_KEY = 'eliteintelia_engagement';
const ROLE_KEY = 'eliteintelia_role';

/** Personas. `stages` drives which workspaces are highlighted for that role. */
export const ROLES = [
  {id: 'all', label: 'All Capabilities', short: 'All', focus: []},
  {id: 'consultant', label: 'IT Consultant', short: 'Consultant', focus: ['/intake', '/discovery', '/architecture']},
  {id: 'product_owner', label: 'Product Owner', short: 'Product', focus: ['/', '/engagements', '/ai-analytics']},
  {id: 'stakeholder', label: 'Business Stakeholder', short: 'Business', focus: ['/', '/engagements']},
  {id: 'business_analyst', label: 'Business Analyst', short: 'BA', focus: ['/discovery', '/intake', '/ai-analytics']},
  {id: 'architect', label: 'Solution Architect', short: 'Architect', focus: ['/architecture', '/platform', '/discovery']},
  {id: 'data_engineer', label: 'Data Engineer', short: 'Data Eng', focus: ['/engineering', '/validation', '/platform']},
  {id: 'platform_engineer', label: 'Platform Engineer', short: 'Platform', focus: ['/platform', '/deploy', '/monitoring']},
  {id: 'ai_engineer', label: 'Data / AI Engineer', short: 'AI Eng', focus: ['/ai-analytics', '/engineering']},
  {id: 'devops', label: 'DevOps Engineer', short: 'DevOps', focus: ['/deploy', '/monitoring', '/platform']},
  {id: 'qa', label: 'QA / Automation Engineer', short: 'QA', focus: ['/validation', '/engineering']},
  {id: 'bi_developer', label: 'BI Developer', short: 'BI', focus: ['/ai-analytics', '/engineering']},
  {id: 'analytics', label: 'Analytics Team', short: 'Analytics', focus: ['/ai-analytics', '/monitoring']},
  {id: 'project_manager', label: 'Project Manager', short: 'PM', focus: ['/engagements', '/', '/monitoring']},
  {id: 'delivery_manager', label: 'Delivery Manager', short: 'Delivery', focus: ['/engagements', '/deploy', '/monitoring']},
] as const;

export type RoleId = (typeof ROLES)[number]['id'];

type Ctx = {
  engagementId: string | null;
  engagement: any | null;
  engagements: Engagement[];
  loading: boolean;
  error: string;
  role: RoleId;
  setRole: (r: RoleId) => void;
  select: (id: string | null) => void;
  refresh: () => Promise<void>;
  refreshList: () => Promise<void>;
  dropStale: (engagementId: string) => void;
};

const EngagementContext = createContext<Ctx | null>(null);

export function useEngagement(): Ctx {
  const c = useContext(EngagementContext);
  if (!c) throw new Error('useEngagement must be used inside <EngagementProvider>');
  return c;
}

export function EngagementProvider({children}: {children: React.ReactNode}) {
  const [engagementId, setEngagementId] = useState<string | null>(null);
  const [engagement, setEngagement] = useState<any | null>(null);
  const [engagements, setEngagements] = useState<Engagement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [role, setRoleState] = useState<RoleId>('all');

  // Resolve the initial engagement: ?engagement= wins, then localStorage.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const qs = new URLSearchParams(window.location.search).get('engagement');
    const stored = localStorage.getItem(STORAGE_KEY);
    const initial = qs || stored;
    if (initial) setEngagementId(initial);
    const storedRole = localStorage.getItem(ROLE_KEY) as RoleId | null;
    if (storedRole && ROLES.some(r => r.id === storedRole)) setRoleState(storedRole);
  }, []);

  const refreshList = useCallback(async () => {
    try {
      const r = await getEngagements();
      setEngagements(r.items || []);
      // Auto-select the only/most recent engagement so workspaces are never dead.
      setEngagementId(prev => {
        if (prev && (r.items || []).some(i => i.id === prev)) return prev;
        const first = (r.items || [])[0]?.id ?? null;
        if (first && typeof window !== 'undefined') localStorage.setItem(STORAGE_KEY, first);
        return first;
      });
    } catch (e: any) {
      setError(e?.message || 'Unable to load engagements');
    }
  }, []);

  /** Forget an engagement id the backend no longer recognises, then re-select.

   *  Without this the app stays pinned to a dead id and every panel 404s. */
  const dropStale = useCallback((staleId: string) => {
    if (typeof window !== 'undefined' &&
        localStorage.getItem(STORAGE_KEY) === staleId) {
      localStorage.removeItem(STORAGE_KEY);
    }
    setEngagement(null);
    setEngagements(prev => prev.filter(e => e.id !== staleId));
    setEngagementId(prev => (prev === staleId ? null : prev));
    setError('');
    refreshList();   // re-select from what actually exists
  }, [refreshList]);

  const refresh = useCallback(async () => {
    if (!engagementId) {
      setEngagement(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const x = await getEngagement(engagementId);
      setEngagement(x);
      setError('');
    } catch (e: any) {
      const message = e?.message || 'Unable to load engagement';
      // The stored id points at an engagement the backend no longer has —
      // typically after the database was reset under the service. Drop the
      // stale selection so the list can choose a live one, rather than leaving
      // the app pinned to something that will 404 on every panel.
      if (/not found/i.test(message)) {
        dropStale(engagementId);
        return;
      }
      setError(message);
      setEngagement(null);
    } finally {
      setLoading(false);
    }
  }, [engagementId, dropStale]);

  useEffect(() => { refreshList().finally(() => setLoading(false)); }, [refreshList]);
  useEffect(() => { refresh(); }, [refresh]);

  const select = useCallback((id: string | null) => {
    setEngagementId(id);
    if (typeof window === 'undefined') return;
    if (id) localStorage.setItem(STORAGE_KEY, id);
    else localStorage.removeItem(STORAGE_KEY);
  }, []);

  const setRole = useCallback((r: RoleId) => {
    setRoleState(r);
    if (typeof window !== 'undefined') localStorage.setItem(ROLE_KEY, r);
  }, []);

  const value = useMemo(
    () => ({engagementId, engagement, engagements, loading, error, role, setRole,
            select, refresh, refreshList, dropStale}),
    [engagementId, engagement, engagements, loading, error, role, setRole,
     select, refresh, refreshList, dropStale]
  );

  return <EngagementContext.Provider value={value}>{children}</EngagementContext.Provider>;
}
