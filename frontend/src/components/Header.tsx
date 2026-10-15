import { useEffect, useRef, useState } from 'react'
import { latinDate, money } from '../college'
import type { Cash } from '../types'
import { Crest } from './Crest'

interface Props {
  cash?: Cash
  name: string
  onName: (n: string) => void
}

export function Header({ cash, name, onName }: Props) {
  const prev = useRef<number | undefined>(undefined)
  const [delta, setDelta] = useState<number | null>(null)

  useEffect(() => {
    if (!cash) return
    if (prev.current !== undefined && cash.balance !== prev.current) {
      setDelta(cash.balance - prev.current)
      const t = window.setTimeout(() => setDelta(null), 6000)
      prev.current = cash.balance
      return () => window.clearTimeout(t)
    }
    prev.current = cash.balance
  }, [cash])

  return (
    <header className="masthead">
      <div className="masthead-inner">
        <div className="brand">
          <Crest size={58} />
          <div>
            <div className="eyebrow">Office of the Desk · Est. MMXXVI</div>
            <h1>Campus Customs</h1>
            <div className="motto"><span>Lux et Inventarium</span></div>
          </div>
        </div>

        <div className="masthead-meta">
          <div className="meta-block">
            <span className="label">Shop date</span>
            <b>{cash?.shop_date ?? '—'}</b>
            <i>{cash ? latinDate(cash.shop_date) : ''}</i>
          </div>
          <label className="meta-block signer">
            <span className="label">Signed by</span>
            <input value={name} onChange={(e) => onName(e.target.value)} placeholder="Your name, for approvals" aria-label="Your name, used to sign approvals" />
          </label>
          <div className={`meta-block ledger ${delta !== null ? (delta < 0 ? 'fell' : 'rose') : ''}`} aria-live="polite">
            <span className="label">The Bursar's Ledger · Checking</span>
            <b className="balance">{cash ? money(cash.balance) : '—'}</b>
            {delta !== null && <i className="delta">{delta < 0 ? '−' : '+'}{money(Math.abs(delta))} just now</i>}
          </div>
        </div>
      </div>
      <div className="tracery" aria-hidden="true" />
    </header>
  )
}
