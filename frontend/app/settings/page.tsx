'use client';
/** Settings — connectivity diagnostics, platform catalog and persona defaults. */
import {useEffect, useState} from 'react';
import {Settings as Cog, Wifi, WifiOff, RefreshCw, CheckCircle2, CloudCog, UsersRound,
        Sparkles, XCircle, AlertTriangle, LoaderCircle, PlugZap} from 'lucide-react';
import {API_BASE, getApiHealth, getPlatformCatalog, getAiStatus, runAiTest,
        type AiStatus, type AiTest} from '../../lib/api';
import {useEngagement, ROLES, type RoleId} from '../../lib/engagement-context';

export default function SettingsPage() {
  const {role, setRole, engagements} = useEngagement();
  const [health, setHealth] = useState<any>(null);
  const [err, setErr] = useState('');
  const [catalog, setCatalog] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [ai, setAi] = useState<AiStatus | null>(null);
  const [aiTest, setAiTest] = useState<AiTest | null>(null);
  const [testing, setTesting] = useState(false);

  const check = async () => {
    setBusy(true); setErr('');
    try { setHealth(await getApiHealth()); } catch (e: any) { setErr(e?.message || 'Backend unreachable'); setHealth(null); }
    try { setCatalog(await getPlatformCatalog()); } catch { /* optional */ }
    try { setAi(await getAiStatus()); } catch { setAi(null); }
    finally { setBusy(false); }
  };

  useEffect(() => { check(); }, []);

  // The catalog returns `items` as an object keyed by platform name, not an array.
  const raw = catalog?.items ?? catalog?.platforms;
  const platforms: any[] = Array.isArray(raw)
    ? raw
    : raw && typeof raw === 'object'
      ? Object.entries(raw).map(([name, v]: [string, any]) => ({name, ...(v || {})}))
      : [];

  return (
    <>
      <div className="pageHead">
        <div>
          <div className="crumb">Home <span>›</span> Settings</div>
          <h1>Platform Settings</h1>
          <p>Connectivity, enterprise controls and role defaults for the Intelligence Factory.</p>
        </div>
        <div className="headActions">
          <button className="secondary" onClick={check} disabled={busy}>
            <RefreshCw size={16} className={busy ? 'spin' : ''} /> Re-check
          </button>
        </div>
      </div>

      <section className="panel">
        <div className="panelHead">
          <h3><Sparkles size={18} /> AI provider</h3>
          <button className="primary sm" onClick={async () => {
            setTesting(true); setAiTest(null);
            try { setAiTest(await runAiTest()); }
            catch (e: any) { setAiTest({ok: false, reachable: false, elapsed_ms: 0,
                                        message: e?.message || 'Test failed',
                                        configuration: ai as AiStatus}); }
            finally { setTesting(false); }
          }} disabled={testing}>
            {testing ? <LoaderCircle size={15} className="spin" /> : <PlugZap size={15} />}
            {testing ? 'Testing…' : 'Test AI provider'}
          </button>
        </div>

        <p className="hint" style={{marginTop: 0}}>
          Sends one real request through the same client the delivery stages use, so the
          result reflects what Discovery will actually get.
        </p>

        {ai && (
          <>
            <div className="statusRow"><span>Client</span><b>{ai.client}</b></div>
            <div className="statusRow"><span>Configured</span>
              <b className={ai.configured ? 'ok' : 'pending'}>{ai.configured ? 'YES' : 'NO'}</b></div>
            <div className="statusRow"><span>Endpoint</span><b><code>{ai.endpoint || '—'}</code></b></div>
            <div className="statusRow"><span>Model</span><b>{ai.model || '—'}</b></div>
            <div className="statusRow"><span>API key</span>
              <b className={ai.api_key_present ? 'ok' : 'pending'}>
                {ai.api_key_present ? 'PRESENT' : 'MISSING'}</b></div>
            <div className="statusRow"><span>Failover</span>
              <b>{ai.multi_provider ? `${ai.providers?.length ?? 0} providers` : 'single provider'}</b></div>
            {!ai.configured && <div className="notice error">{ai.message}</div>}
          </>
        )}

        {aiTest && (
          <div className={`aiResult ${aiTest.ok ? 'ok' : aiTest.fault === 'quota' ? 'quota' : 'bad'}`}>
            <div className="aiResultTop">
              {aiTest.ok ? <CheckCircle2 size={17} />
                : aiTest.fault === 'quota' ? <AlertTriangle size={17} /> : <XCircle size={17} />}
              <strong>
                {aiTest.ok ? 'AI provider is working'
                  : aiTest.fault === 'quota' ? 'Reachable, but the request was refused'
                  : aiTest.fault === 'auth' ? 'Authentication rejected'
                  : aiTest.fault === 'timeout' ? 'Endpoint did not answer in time'
                  : aiTest.fault === 'format' ? 'Answered, but not usably'
                  : 'Endpoint unreachable'}
              </strong>
              <span className="aiMs">{aiTest.elapsed_ms} ms</span>
            </div>
            <p>{aiTest.message}</p>
            {aiTest.remedy && <p className="aiRemedy">{aiTest.remedy}</p>}
            {aiTest.ok && aiTest.response_preview && (
              <code className="aiEcho">{aiTest.response_preview}</code>
            )}
          </div>
        )}
      </section>

      <div className="workspaceGrid">
        <section className="panel">
          <div className="panelTitle">{health ? <Wifi /> : <WifiOff />} API connectivity</div>
          <div className="statusRow"><span>API base URL</span><b><code>{API_BASE}</code></b></div>
          <div className="statusRow"><span>Status</span><b className={health ? 'ok' : 'pending'}>{health ? 'CONNECTED' : 'UNREACHABLE'}</b></div>
          {health?.product && <div className="statusRow"><span>Product</span><b>{health.product}</b></div>}
          {health?.version && <div className="statusRow"><span>Version</span><b>{health.version}</b></div>}
          <div className="statusRow"><span>Engagements loaded</span><b>{engagements.length}</b></div>
          {err && <div className="notice error">{err}</div>}
          {!health && (
            <p className="hint">
              Set <code>NEXT_PUBLIC_API_BASE_URL</code> in your Vercel project to the Render backend URL,
              then redeploy the frontend.
            </p>
          )}
        </section>

        <section className="panel">
          <div className="panelTitle"><UsersRound /> Default role view</div>
          <p className="hint">Choosing a persona highlights the workspaces that role owns across the sidebar.</p>
          <select className="textInput" value={role} onChange={e => setRole(e.target.value as RoleId)}>
            {ROLES.map(r => <option key={r.id} value={r.id}>{r.label}</option>)}
          </select>
          <div className="chipRow" style={{marginTop: 12}}>
            {ROLES.filter(r => r.id !== 'all').slice(0, 8).map(r => (
              <button key={r.id} className={r.id === role ? 'chipBtn active' : 'chipBtn'} onClick={() => setRole(r.id as RoleId)}>
                {r.short}
              </button>
            ))}
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="panelTitle"><CloudCog /> Supported target platforms</div>
        {platforms.length === 0 ? (
          <div className="empty"><Cog size={18} /> Platform catalog unavailable — the backend exposes it at <code>/api/catalog/platforms</code>.</div>
        ) : (
          <div className="assessmentGrid">
            {platforms.map((p: any, i: number) => (
              <div className="assessmentCard" key={p.id || p.name || i}>
                <div className="assessmentCardTop">
                  <strong>{p.label || p.name || p.id}</strong>
                  <span>{p.clouds ? (Array.isArray(p.clouds) ? p.clouds.join(', ') : p.clouds) : '—'}</span>
                </div>
                <p>
                  {p.description
                    || [p.type, p.endpoint_hint].filter(Boolean).join(' · ')
                    || 'Supported governed target platform.'}
                </p>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panelTitle"><CheckCircle2 /> Enterprise controls</div>
        <div className="statusRow"><span>Human approval before mutation</span><b className="ok">ENFORCED</b></div>
        <div className="statusRow"><span>Evidence-backed artifacts</span><b className="ok">REQUIRED</b></div>
        <div className="statusRow"><span>Audit trail on executions</span><b className="ok">PERSISTED</b></div>
        <div className="statusRow"><span>Credential storage</span><b className="ok">SECRET REFERENCE ONLY</b></div>
        <p className="hint">
          The platform never stores raw customer credentials — only a secret reference name resolved at execution time.
        </p>
      </section>
    </>
  );
}
