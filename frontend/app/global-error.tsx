'use client';
/**
 * Last-resort boundary: catches failures in the root layout itself, where
 * app/error.tsx cannot mount. It must ship its own <html>/<body> and cannot
 * rely on the app's stylesheet having loaded, so the styling is inline.
 */
export default function GlobalError(
  {error, reset}: {error: Error & {digest?: string}; reset: () => void},
) {
  return (
    <html lang="en">
      <body style={{margin: 0, minHeight: '100vh', display: 'grid',
                    placeItems: 'center', background: '#0b1017',
                    color: '#e6edf3', fontFamily: 'system-ui, sans-serif'}}>
        <div style={{maxWidth: 520, padding: 32, textAlign: 'center'}}>
          <h1 style={{fontSize: 19, marginBottom: 10}}>
            EliteInteliA could not start
          </h1>
          <p style={{fontSize: 13.5, lineHeight: 1.65, color: '#8b98a9'}}>
            The application shell failed to load. Your data on the server is
            unaffected. Reload to try again.
          </p>
          <pre style={{textAlign: 'left', fontSize: 11, background: '#00000055',
                       padding: 12, borderRadius: 8, overflowX: 'auto',
                       color: '#c9d4e0'}}>
            {error.message}{error.digest ? `\ndigest: ${error.digest}` : ''}
          </pre>
          <button
            onClick={reset}
            style={{marginTop: 14, padding: '9px 18px', borderRadius: 8,
                    border: '1px solid #2b3a4d', background: '#16202c',
                    color: '#e6edf3', cursor: 'pointer', fontSize: 13}}>
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}
