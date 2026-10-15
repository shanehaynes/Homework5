import { useState } from 'react'
import { fellowTitle, humanize, money, roman } from '../college'
import type { Approval, Cash } from '../types'

const KIND_LABEL: Record<Approval['kind'], string> = { payment: 'Payment', purchase: 'Purchase order', discount: 'Discount' }

interface Props {
  approvals?: Approval[]
  cash?: Cash
  name: string
  onDecide: (a: Approval, decision: 'approve' | 'reject') => Promise<void>
  onSelectTicket: (id: number) => void
}

export function Approvals({ approvals, cash, name, onDecide, onSelectTicket }: Props) {
  const pending = (approvals ?? []).filter((a) => a.status === 'pending')
  const decided = (approvals ?? []).filter((a) => a.status !== 'pending').slice(-6).reverse()

  return (
    <aside className="panel assent">
      <h2 className="panel-title"><span>Awaiting Assent</span></h2>
      <p className="panel-sub">Payments and purchases move only on a human's signature.</p>
      {!name.trim() && pending.length > 0 && <p className="notice">Enter your name under “Signed by” to approve or reject.</p>}

      {pending.length === 0 ? (
        <p className="empty">Nothing awaits your assent.</p>
      ) : (
        <ul className="approval-list">
          {pending.map((a) => <ApprovalCard key={a.id} a={a} cash={cash} name={name} onDecide={onDecide} onSelectTicket={onSelectTicket} />)}
        </ul>
      )}

      {decided.length > 0 && (
        <>
          <h3 className="sub-title">Acta · recent decisions</h3>
          <ul className="acta">
            {decided.map((a) => (
              <li key={a.id}>
                <span>{KIND_LABEL[a.kind]} #{a.id}{a.amount != null ? ` · ${money(a.amount)}` : ''}</span>
                <span className={`chip decided-${a.status}`}>{humanize(a.status)}</span>
                {a.decided_by && <i>by {a.decided_by}</i>}
              </li>
            ))}
          </ul>
        </>
      )}
    </aside>
  )
}

function ApprovalCard({ a, cash, name, onDecide, onSelectTicket }: { a: Approval } & Omit<Props, 'approvals'>) {
  const [confirm, setConfirm] = useState<'approve' | 'reject' | null>(null)
  const [busy, setBusy] = useState(false)
  const moves = a.kind === 'payment'
  const after = moves && cash && a.amount != null ? cash.balance - a.amount : null
  const short = after !== null && after < 0
  const signed = name.trim().length > 0

  const go = async (d: 'approve' | 'reject') => {
    setBusy(true)
    try { await onDecide(a, d) } finally { setBusy(false); setConfirm(null) }
  }

  return (
    <li className={`approval kind-${a.kind}`}>
      <div className="approval-head">
        <span className="kind">{KIND_LABEL[a.kind]}</span>
        <span className="approval-id">#{a.id}</span>
      </div>
      {a.amount != null && <div className="approval-amount">{a.kind === 'discount' ? `${money(a.amount)} off list` : money(a.amount)}</div>}
      <p className="approval-details">{a.details}</p>
      <div className="approval-meta">
        Requested by {fellowTitle(a.requested_by)}
        {a.ticket_id && <> · <button className="link" onClick={() => onSelectTicket(a.ticket_id!)}>Ticket {roman(a.ticket_id)} ({a.ticket_id})</button></>}
      </div>
      {after !== null && (
        <div className={`after ${short ? 'short' : ''}`}>
          Checking after payment: <b>{money(after)}</b>{short && ' · insufficient cash; the Bursar will refuse it'}
        </div>
      )}
      {a.kind === 'purchase' && <div className="after">Commits spend; the vendor bills on delivery. Cash is not debited today.</div>}

      {confirm === null ? (
        <div className="row">
          <button className="btn primary" disabled={!signed || busy} onClick={() => setConfirm('approve')}>Approve</button>
          <button className="btn ghost" disabled={!signed || busy} onClick={() => setConfirm('reject')}>Reject</button>
        </div>
      ) : (
        <div className="confirm-box">
          <p>
            {confirm === 'approve'
              ? moves ? `Pay ${money(a.amount ?? 0)} now, signed ${name}? This cannot be undone.` : `Approve this ${KIND_LABEL[a.kind].toLowerCase()}, signed ${name}?`
              : `Reject this request, signed ${name}?`}
          </p>
          <div className="row">
            <button className={`btn ${confirm === 'approve' ? 'primary' : 'danger'}`} disabled={busy} onClick={() => go(confirm)}>
              {busy ? 'Recording…' : confirm === 'approve' ? 'Confirm' : 'Confirm rejection'}
            </button>
            <button className="btn ghost" disabled={busy} onClick={() => setConfirm(null)}>Back</button>
          </div>
        </div>
      )}
    </li>
  )
}
