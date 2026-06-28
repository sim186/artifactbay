/**
 * ArtifactBay brand mark — "Container Bay".
 * Two stacked containers (the artifacts) berthed between dock posts over a
 * waterline — store, ship, retrieve. Indigo + teal on a dark tile.
 * Gradient/filter ids are namespaced so multiple instances never collide.
 */
export function ArtifactBayMark({ size = 24, glow = true, className = '' }: { size?: number; glow?: boolean; className?: string }) {
  const uid = glow ? 'g' : 'p'
  const tile = `ab-tile-${uid}`
  const blur = `ab-glow-${uid}`
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      className={className}
      role="img"
      aria-label="ArtifactBay"
    >
      <defs>
        <linearGradient id={tile} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#1d2233" />
          <stop offset="1" stopColor="#10131c" />
        </linearGradient>
        {glow && (
          <filter id={blur} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3.5" />
          </filter>
        )}
      </defs>
      <rect x="6" y="6" width="88" height="88" rx="26" fill={`url(#${tile})`} stroke="#5b8cff" strokeWidth="2.4" />
      {/* dock posts */}
      <path d="M27 34V66M73 34V66" stroke="#9aa6bd" strokeWidth="3" strokeLinecap="round" opacity="0.55" />
      {glow && (
        <g filter={`url(#${blur})`} opacity="0.5">
          <rect x="32" y="53" width="36" height="13" rx="3" fill="#5b8cff" />
          <rect x="32" y="38" width="36" height="13" rx="3" fill="#36d6c3" />
        </g>
      )}
      {/* stacked containers (artifacts in the berth) */}
      <rect x="32" y="53" width="36" height="13" rx="3" fill="#5b8cff" />
      <rect x="32" y="38" width="36" height="13" rx="3" fill="#36d6c3" />
      {/* waterline / dock */}
      <path d="M22 72H78" stroke="#5b8cff" strokeWidth="5" strokeLinecap="round" />
    </svg>
  )
}
