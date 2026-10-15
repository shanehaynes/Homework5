import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, API_BASE } from './api'
import { money, roman } from './college'
import { Approvals } from './components/Approvals'
import { Chamber } from './components/Chamber'
import { Docket } from './components/Docket'
import { Header } from './components/Header'
import { usePoll, useStoredName } from './hooks'
import type { Approval, AuditEvent, TicketDetail } from './types'

interface Toast { id: number; tone: 'ok' | 'warn' | 'err'; text: string }

export default function App() {
  const [name, setName] = useStoredName()
  const [selected, setSelected] = useState<number | null>(() => Number(new URLSearchParams(location.search).get('ticket')) || null)
  const [toasts, setToasts] = useState<Toast[]>([])

  const tickets = usePoll(api.tickets, 4000)
  const cash = usePoll(api.cash, 4000)
  const approvals = usePoll(() => api.approvals('all'), 3000)
  const runs = usePoll(api.runs, 2000)

  const job = runs.data?.find((r) => r.ticket_id === selected)
  const live = job?.status === 'running'

  const activity = usePoll<AuditEvent[]>(
    () => (selected === null ? Promise.resolve([]) : api.activity({ ticketId: selected })), live ? 1500 : 5000, [selected],
  )
  const detail = usePoll<TicketDetail | undefined>(
    () => (selected === null ? Promise.resolve(undefined) : api.ticket(selected)), live ? 2500 : 5000, [selected],
  )

  const toast = useCallback((tone: Toast['tone'], text: string) => {
    const id = Date.now() + Math.random()
    setToasts((t) => [...t, { id, tone, text }])
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 7000)
  }, [])

  const refreshAll = () => { tickets.refresh(); cash.refresh(); approvals.refresh(); runs.refresh(); activity.refresh(); detail.refresh() }

  useEffect(() => {
    if (selected === null && tickets.data?.length) setSelected(tickets.data[0].id)
  }, [tickets.data, selected])

  // When a run finishes, refresh everything so the ticket's new state (resolved or parked) shows at once.
  const lastStatus = useRef<Record<string, string>>({})
  useEffect(() => {
    for (const r of runs.data ?? []) {
      if (lastStatus.current[r.run_id] === 'running' && r.status !== 'running') {
        refreshAll()
        if (r.status === 'failed') toast('err', `Session on ticket ${roman(r.ticket_id)} failed: ${r.error}`)
        else toast('ok', `The fellows have reported on ticket ${roman(r.ticket_id)}.`)
      }
      lastStatus.current[r.run_id] = r.status
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runs.data])

  // During a live run, focus on that run. Otherwise show every session on the ticket, so the board
  // reflects all the work each fellow did across runs, plus the human actions in between.
  const events = useMemo(() => {
    const all = (activity.data ?? []).slice().reverse()
    return live && job ? all.filter((e) => e.root_run_id === job.run_id) : all
  }, [activity.data, live, job])

  const ticket = tickets.data?.find((t) => t.id === selected)

  const onRun = async () => {
    if (selected === null) return
    try {
      await api.runTicket(selected)
      toast('ok', `The fellows are convened on ticket ${roman(selected)}.`)
      runs.refresh(); activity.refresh()
    } catch (e) { toast('err', (e as Error).message) }
  }

  const onResolve = async (note: string) => {
    if (selected === null) return
    try {
      await api.resolveTicket(selected, name, note)
      toast('ok', `Boola Boola! Ticket ${roman(selected)} resolved.`)
      tickets.refresh(); detail.refresh(); activity.refresh()
    } catch (e) { toast('err', (e as Error).message) }
  }

  const onDirect = async (note: string) => {
    if (selected === null) return
    try {
      await api.directTicket(selected, name, note)
      toast('ok', `Direction recorded on ticket ${roman(selected)}. Reconvene the fellows to act on it.`)
      detail.refresh(); activity.refresh()
    } catch (e) { toast('err', (e as Error).message) }
  }

  const onDecide = async (a: Approval, decision: 'approve' | 'reject') => {
    const before = cash.data?.balance
    try {
      await api.decide(a.id, decision, name)
      if (decision === 'reject') toast('warn', `Request #${a.id} rejected.`)
      else if (a.kind === 'payment' && before !== undefined && a.amount != null) toast('ok', `Paid ${money(a.amount)}. Checking falls to ${money(before - a.amount)}.`)
      else toast('ok', `${a.kind === 'purchase' ? 'Purchase order placed' : 'Discount approved'} (#${a.id}).`)
    } catch (e) {
      toast('err', `Request #${a.id}: ${(e as Error).message}`)
    } finally { refreshAll() }
  }

  const onReset = async () => {
    try {
      const r = await api.reset()
      toast('ok', `A fresh term begins. Checking restored to ${money(r.cash[0]?.balance ?? 0)}.`)
      refreshAll()
    } catch (e) { toast('err', (e as Error).message) }
  }

  return (
    <div className="app">
      <Header cash={cash.data} name={name} onName={setName} />
      {tickets.error && (
        <div className="offline" role="alert">
          The desk cannot reach the backend at <code>{API_BASE}</code> ({tickets.error}). Start it from <code>backend/</code> with
          <code>uvicorn main:app --reload --port 8000</code>.
        </div>
      )}
      <div className="layout">
        <Docket tickets={tickets.data} selected={selected} onSelect={setSelected} runs={runs.data ?? []} onReset={onReset} />
        {ticket ? (
          <Chamber ticket={ticket} detail={detail.data} job={job} events={events} name={name} onRun={onRun} onResolve={onResolve} onDirect={onDirect} />
        ) : (
          <main className="chamber"><section className="panel"><p className="empty">Choose a matter from the docket.</p></section></main>
        )}
        <Approvals approvals={approvals.data} cash={cash.data} name={name} onDecide={onDecide} onSelectTicket={setSelected} />
      </div>
      <footer className="colophon">
        <span>Campus Customs · Chapel Street, New Haven</span>
        <span className="motto-small">Lux et Inventarium: light, and an accurate count</span>
        <span>For the Desk, for the Shop, and for Yale</span>
      </footer>
      <div className="toasts" aria-live="polite">
        {toasts.map((t) => <div key={t.id} className={`toast ${t.tone}`}>{t.text}</div>)}
      </div>
    </div>
  )
}
