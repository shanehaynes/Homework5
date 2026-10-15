import { useState } from 'react'
import { fellowTitle, humanize, roman } from '../college'
import type { RunJob, Ticket } from '../types'

interface Props {
  tickets?: Ticket[]
  selected: number | null
  onSelect: (id: number) => void
  runs: RunJob[]
  onReset: () => Promise<void>
}

export function Docket({ tickets, selected, onSelect, runs, onReset }: Props) {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const running = new Set(runs.filter((r) => r.status === 'running').map((r) => r.ticket_id))

  return (
    <aside className="panel docket">
      <h2 className="panel-title"><span>The Docket</span></h2>
      <p className="panel-sub">Matters before the desk. Choose one to convene the fellows.</p>

      <ol className="ticket-list">
        {(tickets ?? []).map((t) => (
          <li key={t.id}>
            <button className={`ticket-card ${selected === t.id ? 'selected' : ''} ${t.state}`} onClick={() => onSelect(t.id)} aria-pressed={selected === t.id}>
              <div className="ticket-no">
                <span className="roman">{roman(t.id)}</span>
                <span className="arabic">No. {t.id}</span>
              </div>
              <div className="ticket-body">
                <div className="ticket-subject">{t.subject}</div>
                <div className="ticket-requester">{t.requester}</div>
                <div className="ticket-tags">
                  <span className={`chip state-${t.state}`}>{t.state === 'resolved' ? 'Resolved' : 'Open'}</span>
                  {running.has(t.id) && <span className="chip running">In session</span>}
                </div>
                {t.state === 'open' && t.status !== 'open' && <div className="ticket-status">{humanize(t.status)}</div>}
                <div className="ticket-owner">{t.owner ? `In the care of ${fellowTitle(t.owner)}` : 'Unassigned'}</div>
              </div>
            </button>
          </li>
        ))}
        {!tickets && <li className="empty">Calling the roll…</li>}
      </ol>

      <div className="fresh-term">
        {!confirming ? (
          <button className="btn ghost" onClick={() => setConfirming(true)} disabled={running.size > 0}>
            Begin a Fresh Term
          </button>
        ) : (
          <div className="confirm-box" role="alertdialog" aria-label="Confirm reset">
            <p>
              Restore the shop to its original books? Cash returns to <b>$3,400</b>, invoice 501 and the rent become unpaid
              again, and every ticket reopens. The audit trail is kept.
            </p>
            <div className="row">
              <button className="btn danger" disabled={busy} onClick={async () => { setBusy(true); await onReset(); setBusy(false); setConfirming(false) }}>
                {busy ? 'Restoring…' : 'Restore original books'}
              </button>
              <button className="btn ghost" onClick={() => setConfirming(false)}>Cancel</button>
            </div>
          </div>
        )}
      </div>
    </aside>
  )
}
