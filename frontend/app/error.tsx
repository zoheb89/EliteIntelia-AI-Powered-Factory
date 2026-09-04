'use client';
/**
 * Route-level error boundary.
 *
 * Without this, any single throw in any client component replaced the whole
 * app with Next.js's bare "Application error: a client-side exception has
 * occurred", which says nothing and offers no way out. Two recoveries matter
 * in practice: a stale chunk after a redeploy (self-healing, one reload), and
 * a stored project id that no longer exists on the backend (clear and retry).
 */
import {useEffect, useState} from 'react';
import {AlertTriangle, RefreshCw, RotateCcw, Home} from 'lucide-react';

const RELOAD_FLAG = 'eliteintelia_chunk_reload';

function isStaleBuild(e: Error) {
  return /ChunkLoadError|Loading chunk|Failed to fetch dynamically imported/i
    .test(`${e.name} ${e.message}`);
}

export default function ErrorBoundary(
  {error, reset}: {error: Error & {digest?: string}; reset: () => void},
) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    // A redeploy invalidates the chunk hashes an open tab still asks for.
    // Reload once — guarded by a flag so a genuine failure cannot loop.
    if (isStaleBuild(error) && !sessionStorage.getItem(RELOAD_FLAG)) {
      sessionStorage.setItem(RELOAD_FLAG, '1');
      window.location.reload();
      return;
    }
    console.error('[EliteInteliA] render failure', error);
  }, [error]);

  const details = [
    `message: ${error.message}`,
    error.digest ? `digest:  ${error.digest}` : '',
    `route:   ${typeof window !== 'undefined' ? window.location.pathname : ''}`,
    `build:   ${process.env.NEXT_PUBLIC_BUILD_ID || 'dev'}`,
  ].filter(Boolean).join('\n');

  const resetState = () => {
    try {
      Object.keys(localStorage)
        .filter(k => k.startsWith('eliteintelia_'))
        .forEach(k => localStorage.removeItem(k));
    } catch { /* private mode */ }
    window.location.href = '/';
  };

  return (
    <div className="errorBoundary">
      <div className="ebCard">
        <AlertTriangle size={26} />
        <h1>This page stopped rendering</h1>
        <p>
          Something in the page threw an error. Your engagements and generated
          work are stored on the server and are not affected.
        </p>

        <pre>{details}</pre>

        <div className="ebActions">
          <button onClick={reset}><RefreshCw size={14} /> Try again</button>
          <button className="secondary" onClick={() => window.location.reload()}>
            <RotateCcw size={14} /> Reload the page
          </button>
          <button className="secondary" onClick={resetState}>
            <Home size={14} /> Reset app state
          </button>
        </div>

        <p className="ebHint">
          <b>Try again</b> re-renders this page. <b>Reset app state</b> clears the
          remembered engagement — use it if the page keeps failing after a reload,
          which usually means it is pointing at an engagement the server no longer has.
        </p>

        <button
          className="ebCopy"
          onClick={() => {
            navigator.clipboard?.writeText(`${details}\n\n${error.stack || ''}`);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
          }}
        >
          {copied ? 'Copied' : 'Copy diagnostics'}
        </button>
      </div>
    </div>
  );
}
