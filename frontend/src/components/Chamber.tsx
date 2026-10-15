import { useState } from 'react'
import { FELLOWS, fellowTitle, fellowStates, humanize, money, proceedings, roman } from '../college'
import type { AuditEvent, RunJob, Ticket, TicketDetail } from '../types'
import { AGENTS } from '../types'
import { FellowCard } from './FellowCard'
import { Minutes } from './Minutes'
import { Proceedings } from './Proceedings'

interface Props {
  ticket: Ticket
  detail?: TicketDetail
  job?: RunJob
  events: AuditEvent[]
  name: string
  onRun: () => Promise<void>
  onResolve: (note: string) => Promise<void>
  onDirect: (note: string) => Promise<void>
}

export function Chamber({ ticket, detail, job, events, name, onRun, onResolve, onDirect }: Props) {
  const [starting, setStarting] = useState(false)
  const live = job?.status === 'running'
  const states = fellowStates(events)
  const entries = proceedings(events)
  const finished = job && job.status !== 'running'

  return (
    <main className="chamber">
      <section className="panel matter">
        <div className="matter-head">
          <div className="matter-no">
            <span className="roman big">{roman(ticket.id)}</span>
            <span className="arabic">Ticket No. {ticket.id}</span>
          </div>
          <div className="matter-title">
            <div className="eyebrow">{humanize(ticket.type)}</div>
            <h2>{ticket.subject}</h2>
            <div className="matter-sub">
              From <b>{ticket.requester}</b>
              {ticket.sku && <> · {ticket.qty} × <code>{ticket.sku}</code> size {ticket.size}</>}
            </div>
          </div>
          <div className="matter-state">
            <span className={`chip big state-${ticket.state}`}>{ticket.state === 'resolved' ? 'Resolved' : 'Open'}</span>
            <span className="status-line">{humanize(ticket.status)}{ticket.owner ? ` · ${fellowTitle(ticket.owner)}` : ''}</span>
          </div>
        </div>

        <div className="matter-actions">
          <button
            className="btn primary convene"
            disabled={live || starting || ticket.state === 'resolved'}
            onClick={async () => { setStarting(true); try { await onRun() } finally { setStarting(false) } }}
            title={ticket.state === 'resolved' ? 'This matter is already resolved' : 'Start the agent team on this ticket'}
          >
            {live ? 'The fellows are in session…' : starting ? 'Convening…' : events.length ? 'Reconvene the Fellows' : 'Convene the Fellows'}
          </button>
          <span className="hint">The Head of College reads the ticket first and summons only the fellows it needs.</span>
        </div>

        {finished && <Verdict job={job} ticket={ticket} name={name} onResolve={onResolve} />}
        {ticket.state === 'open' && !live && <Direction name={name} onDirect={onDirect} />}
      </section>

      <section className="fellows" aria-label="The fellows">
        {AGENTS.map((a) => <FellowCard key={a} agent={a} state={states[a]} live={!!live} />)}
      </section>

      <Minutes states={states} />

      <div className="chamber-lower">
        <Proceedings entries={entries} live={!!live} />
        <Record detail={detail} />
      </div>
    </main>
  )
}

function Verdict({ job, ticket, name, onResolve }: { job: RunJob; ticket: Ticket; name: string; onResolve: (note: string) => Promise<void> }) {
  const [note, setNote] = useState(job.report?.summary ?? '')
  const [busy, setBusy] = useState(false)
  if (job.status === 'failed') {
    return <div className="verdict failed" role="status"><b>The session failed.</b> {job.error}</div>
  }
  if (ticket.state === 'resolved') {
    return (
      <div className="verdict resolved" role="status">
        <span className="boola">Boola Boola!</span> Ticket {roman(ticket.id)} is resolved. {job.report?.summary}
      </div>
    )
  }
  return (
    <div className="verdict parked" role="status">
      <div>
        <b>The session has ended; the matter is parked: {humanize(ticket.status)}.</b> {job.report?.summary}
      </div>
      {job.report?.needs_human?.length ? <ul className="needs">{job.report.needs_human.map((x, i) => <li key={i}>{x}</li>)}</ul> : null}
      <div className="resolve-row">
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Resolution note" aria-label="Resolution note" />
        <button className="btn secondary" disabled={!name.trim() || !note.trim() || busy}
          onClick={async () => { setBusy(true); try { await onResolve(note) } finally { setBusy(false) } }}>
          Mark resolved
        </button>
      </div>
      {!name.trim() && <span className="hint">Sign your name in the masthead to resolve.</span>}
    </div>
  )
}

function Direction({ name, onDirect }: { name: string; onDirect: (note: string) => Promise<void> }) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  return (
    <div className="direction">
      <span className="label">Direction from the Desk</span>
      <div className="resolve-row">
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="A decision or instruction for the fellows; they act on it when reconvened" aria-label="Direction for the agent team" />
        <button className="btn ghost" disabled={!name.trim() || !note.trim() || busy}
          onClick={async () => { setBusy(true); try { await onDirect(note); setNote('') } finally { setBusy(false) } }}>
          Send direction
        </button>
      </div>
    </div>
  )
}

function Record({ detail }: { detail?: TicketDetail }) {
  if (!detail) return <section className="panel record"><p className="empty">Opening the file…</p></section>
  const notes = (detail.ticket.notes ?? '').split('\n').filter(Boolean)
  const draft = detail.reply_drafts[0]
  return (
    <section className="panel record">
      <h2 className="panel-title"><span>The Record</span></h2>
      <h3 className="sub-title">Ticket notes</h3>
      <ol className="notes">{notes.map((n, i) => <li key={i}>{n}</li>)}</ol>

      {detail.purchase_orders.length > 0 && (
        <>
          <h3 className="sub-title">Purchase orders</h3>
          <ul className="plain">
            {detail.purchase_orders.map((p) => (
              <li key={p.id}>PO {p.id}: {p.qty} × <code>{p.sku}</code> {p.size} · {money(p.est_cost)} · ETA {p.eta} · <i>{humanize(p.status)}</i></li>
            ))}
          </ul>
        </>
      )}

      {draft && (
        <>
          <h3 className="sub-title">Letter to the patron · {draft.status === 'draft' ? 'draft, not sent' : humanize(draft.status)}</h3>
          <div className="letter">
            <div className="letter-crest">Campus Customs · Chapel Street · New Haven</div>
            <p>{draft.body}</p>
            <div className="letter-foot">Drafted by {fellowTitle(draft.drafted_by)} ({FELLOWS.customer_service.name}). A human must send it.</div>
          </div>
        </>
      )}
    </section>
  )
}
