import * as React from "react"

/**
 * ForensicAI "Seal" brand mark — replaces the gradient-box <Shield/> lockup.
 * A chamfered evidence-seal hexagon + reticle + signal node, drawn monoline so
 * it reads from 16px (sidebar) to 96px (splash). The structure inherits
 * currentColor; the inner node + center dot use the --signal token.
 *
 * Replace the old header lockup, e.g. in components/header.tsx:
 *
 *   // before
 *   <div className="w-8 h-8 bg-gradient-to-br from-purple-600 to-purple-800
 *        rounded-lg flex items-center justify-center">
 *     <Shield className="w-4 h-4 text-white" />
 *   </div>
 *
 *   // after
 *   <Seal size={28} />
 *
 * For the glowing splash variant (login / loading): <Seal size={72} glow />
 */
export function Seal({
  size = 24,
  glow = false,
  className,
  strokeWidth = 1.5,
}: {
  size?: number
  glow?: boolean
  className?: string
  strokeWidth?: number
}) {
  const svg = (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className={className}
    >
      {/* outer chamfered seal */}
      <path
        d="M12 2.2 L20.1 6.9 V17.1 L12 21.8 L3.9 17.1 V6.9 Z"
        stroke="currentColor"
        strokeWidth={strokeWidth}
        strokeLinejoin="round"
        opacity={0.95}
      />
      {/* inner aperture */}
      <path
        d="M12 6.2 L16.6 8.85 V14.15 L12 16.8 L7.4 14.15 V8.85 Z"
        stroke="var(--signal)"
        strokeWidth={strokeWidth * 0.8}
        strokeLinejoin="round"
        opacity={0.5}
      />
      {/* reticle ticks */}
      <path
        d="M12 2.6 V5.2 M12 18.8 V21.4 M4.4 7.3 L6.6 8.6 M17.4 15.4 L19.6 16.7 M19.6 7.3 L17.4 8.6 M6.6 15.4 L4.4 16.7"
        stroke="currentColor"
        strokeWidth={strokeWidth * 0.7}
        strokeLinecap="round"
        opacity={0.6}
      />
      {/* signal node */}
      <circle cx="12" cy="11.5" r="1.7" fill="var(--signal)" />
    </svg>
  )

  if (glow) {
    return (
      <span style={{ display: "inline-block", filter: "drop-shadow(0 0 14px color-mix(in oklch, var(--signal) 45%, transparent))" }}>
        {svg}
      </span>
    )
  }
  return svg
}

export default Seal
