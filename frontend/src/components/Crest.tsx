/** An original shield for the shop: Yale blue field, brass border, CC monogram over an open ledger. */
export function Crest({ size = 64 }: { size?: number }) {
  return (
    <svg className="crest" width={size} height={size * 1.15} viewBox="0 0 64 74" role="img" aria-label="Campus Customs crest">
      <path d="M4 4h56v30c0 19-13 30-28 36C17 64 4 53 4 34z" fill="var(--yale-blue)" stroke="var(--brass)" strokeWidth="2.5" />
      <path d="M8 8h48v26c0 16-11 26-24 31C19 60 8 50 8 34z" fill="none" stroke="rgba(255,255,255,.25)" strokeWidth="0.8" />
      <path d="M16 46c5-3 11-3 16 0 5-3 11-3 16 0v10c-5-3-11-3-16 0-5-3-11-3-16 0z" fill="#fff" opacity=".92" />
      <path d="M32 46v10" stroke="var(--yale-blue)" strokeWidth="1" />
      <text x="32" y="36" textAnchor="middle" fontFamily="'Cormorant Garamond', Georgia, serif" fontSize="22" fontWeight="700" fill="#fff" letterSpacing="1">
        CC
      </text>
    </svg>
  )
}

/** Pointed Gothic (lancet) arch capping each fellow's card; keeps its proportions at any card width. */
export function Arch({ seal, active }: { seal: string; active: boolean }) {
  return (
    <div className={`arch-wrap ${active ? 'active' : ''}`} aria-hidden="true">
      <svg className="arch" viewBox="0 0 120 64" preserveAspectRatio="xMidYMax meet">
        <path d="M6 64 L6 46 A 66 66 0 0 1 60 2 A 66 66 0 0 1 114 46 L114 64 Z" className="arch-fill" />
        <path d="M14 64 L14 48 A 58 58 0 0 1 60 11 A 58 58 0 0 1 106 48 L106 64" fill="none" stroke="var(--brass)" strokeWidth="1.2" opacity=".8" />
      </svg>
      <span className="seal">{seal}</span>
    </div>
  )
}
