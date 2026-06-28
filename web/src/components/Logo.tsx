/**
 * Foundry brand mark — "Molten Ember".
 * Cool indigo vault (the repository) + molten lava F (the freshly-forged artifact).
 * Gradient ids are namespaced so multiple instances never collide.
 */
export function FoundryMark({ size = 24, glow = true, className = '' }: { size?: number; glow?: boolean; className?: string }) {
  // unique-enough suffix so two marks on one page don't share <defs> ids
  const uid = glow ? 'g' : 'p'
  const tile = `fdy-tile-${uid}`
  const lava = `fdy-lava-${uid}`
  const heat = `fdy-heat-${uid}`
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      className={className}
      role="img"
      aria-label="Foundry"
    >
      <defs>
        <linearGradient id={tile} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#1d2233" />
          <stop offset="1" stopColor="#10131c" />
        </linearGradient>
        <linearGradient id={lava} x1="0.08" y1="0" x2="0.5" y2="1">
          <stop offset="0" stopColor="#ffc24f" />
          <stop offset="0.38" stopColor="#ff8a2e" />
          <stop offset="0.72" stopColor="#ec4a0d" />
          <stop offset="1" stopColor="#8f2009" />
        </linearGradient>
        {glow && (
          <filter id={heat} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="4.5" />
          </filter>
        )}
      </defs>
      <rect x="6" y="6" width="88" height="88" rx="26" fill={`url(#${tile})`} stroke="#6366f1" strokeWidth="2.4" />
      {glow && (
        <path
          d="M40 30 H66 M40 30 V74 M40 51 H60"
          fill="none"
          stroke={`url(#${lava})`}
          strokeWidth="9.5"
          strokeLinecap="round"
          filter={`url(#${heat})`}
          opacity="0.55"
        />
      )}
      <path
        d="M40 30 H66 M40 30 V74 M40 51 H60"
        fill="none"
        stroke={`url(#${lava})`}
        strokeWidth="9.5"
        strokeLinecap="round"
      />
    </svg>
  )
}
