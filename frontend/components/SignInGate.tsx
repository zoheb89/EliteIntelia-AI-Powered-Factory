'use client';
import {useState} from 'react';
import {Brand} from './Brand';
import {LogIn, ShieldCheck, LoaderCircle} from 'lucide-react';
import {useAuth} from '../lib/auth-context';

/** Blocks the app when the backend requires auth and nobody is signed in. */
export function SignInGate({children}: {children: React.ReactNode}) {
  const {user, authRequired, ready, signIn} = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  if (!ready) {
    return <div className="authBoot"><LoaderCircle className="spin" size={22} /> Loading…</div>;
  }
  if (!authRequired || user) return <>{children}</>;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr('');
    try { await signIn(email, password); }
    catch (ex: any) { setErr(ex?.message || 'Sign-in failed.'); }
    finally { setBusy(false); }
  };

  return (
    <div className="authWrap">
      <form className="authCard" onSubmit={submit}>
        <div className="authBrand">
          <Brand />
        </div>

        <h1>Sign in</h1>
        <p className="authHint">Enterprise Data &amp; AI delivery platform. Access is role-controlled.</p>

        <label className="sLabel">Work email</label>
        <input className="sInput" type="email" autoComplete="username" required
               value={email} onChange={e => setEmail(e.target.value)} placeholder="you@company.com" />

        <label className="sLabel">Password</label>
        <input className="sInput" type="password" autoComplete="current-password" required
               value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••••" />

        {err && <div className="notice error" style={{marginTop: 12}}>{err}</div>}

        <button className="primary authBtn" type="submit" disabled={busy || !email || !password}>
          {busy ? <LoaderCircle size={16} className="spin" /> : <LogIn size={16} />}
          {busy ? 'Signing in…' : 'Sign in'}
        </button>

        <div className="authFoot"><ShieldCheck size={13} /> Passwords are hashed with PBKDF2; sessions expire automatically.</div>
      </form>
    </div>
  );
}
