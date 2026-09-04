'use client';
/**
 * Brand mark.
 *
 * Renders the supplied logo from /logo.png. If that file is absent — or fails
 * to load — it falls back to the typeset wordmark rather than leaving a broken
 * image in the sidebar, so the shell is never dependent on an asset being
 * present.
 *
 * Ships with a vector rendering at /logo.svg. To use the official artwork
 * instead, drop it at frontend/public/logo.png — a PNG there wins because the
 * component is pointed at it with <Brand src="/logo.png" />, or simply replace
 * logo.svg with the official vector file.
 */
import {useState} from 'react';

export function Brand({src = '/logo.svg'}: {src?: string}) {
  const [failed, setFailed] = useState(false);

  if (!failed) {
    return (
      <div className="brand brandImage">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={src} alt="EliteInteliA Technologies" onError={() => setFailed(true)} />
      </div>
    );
  }

  return (
    <div className="brand">
      <div className="brandMark">EA</div>
      <div>
        <div className="brandName">Elite<span>InteliA</span></div>
        <div className="brandSub">INTELLIGENCE FACTORY</div>
      </div>
    </div>
  );
}
