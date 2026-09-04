'use client';
/**
 * Auth context + sign-in gate.
 *
 * When the backend reports `auth_required: false` the app behaves exactly as
 * before, so existing deployments keep working while auth is rolled out.
 */
import {createContext, useCallback, useContext, useEffect, useMemo, useState} from 'react';
import {getAuthConfig, getMe, login as apiLogin, logout as apiLogout, getToken, type AuthUser} from './api';

type Ctx = {
  user: AuthUser | null;
  authRequired: boolean;
  ready: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => void;
  can: (level: 'viewer' | 'editor' | 'admin') => boolean;
};

const RANK: Record<string, number> = {viewer: 0, editor: 1, admin: 2};
const AuthContext = createContext<Ctx | null>(null);

export function useAuth(): Ctx {
  const c = useContext(AuthContext);
  if (!c) throw new Error('useAuth must be used inside <AuthProvider>');
  return c;
}

export function AuthProvider({children}: {children: React.ReactNode}) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authRequired, setAuthRequired] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const cfg = await getAuthConfig();
        setAuthRequired(cfg.auth_required);
        if (getToken()) {
          try { setUser((await getMe()).user); } catch { setUser(null); }
        }
      } catch {
        // Backend unreachable: don't lock the user out of a static shell.
        setAuthRequired(false);
      } finally {
        setReady(true);
      }
    })();
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const r = await apiLogin(email, password);
    setUser(r.user);
  }, []);

  const signOut = useCallback(() => { apiLogout(); setUser(null); }, []);

  const can = useCallback((level: 'viewer' | 'editor' | 'admin') => {
    if (!authRequired) return true;
    return RANK[user?.role || 'viewer'] >= RANK[level];
  }, [authRequired, user]);

  const value = useMemo(() => ({user, authRequired, ready, signIn, signOut, can}),
                        [user, authRequired, ready, signIn, signOut, can]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
