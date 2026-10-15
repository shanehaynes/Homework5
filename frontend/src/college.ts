// The Yale layer: fellows' titles, Roman numerals, Latin dates, and the plain-English reading of audit events.
import type { AgentName, AgentReport, AuditEvent } from './types'
import { AGENTS } from './types'

export const FELLOWS: Record<AgentName, { name: string; title: string; seal: string; office: string }> = {
  boss: { name: 'Boss', title: 'Head of College', seal: 'B', office: 'Orchestrates the fellows; decides from their reports' },
  inventory: { name: 'Inventory', title: 'Keeper of the Stores', seal: 'I', office: 'Stock, restock, and demand' },
  accounting: { name: 'Accounting', title: 'The Bursar', seal: 'A', office: 'Cash, invoices, and approvals' },
  facilities: { name: 'Facilities', title: 'Superintendent of Grounds', seal: 'F', office: 'Lease, rent, and upkeep' },
  customer_service: { name: 'Customer Service', title: 'Dean of Patrons', seal: 'C', office: 'Catalog, quotes, and replies' },
}

export const isAgent = (a: string): a is AgentName => (AGENTS as readonly string[]).includes(a)
export const fellowTitle = (a: string) => (isAgent(a) ? FELLOWS[a].title : a === 'human' ? 'The Desk' : a)

export function roman(n: number): string {
  const table: [number, string][] = [[1000, 'M'], [900, 'CM'], [500, 'D'], [400, 'CD'], [100, 'C'], [90, 'XC'],
    [50, 'L'], [40, 'XL'], [10, 'X'], [9, 'IX'], [5, 'V'], [4, 'IV'], [1, 'I']]
  let out = ''
  for (const [v, s] of table) while (n >= v) { out += s; n -= v }
  return out
}

const MENSES = ['Ianuarii', 'Februarii', 'Martii', 'Aprilis', 'Maii', 'Iunii', 'Iulii', 'Augusti', 'Septembris',
  'Octobris', 'Novembris', 'Decembris']
export function latinDate(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return `Die ${roman(d)} ${MENSES[m - 1]} ${roman(y)}`
}

export const money = (n: number) => n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
export const clock = (ts: string) => new Date(ts).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', second: '2-digit' })
export const humanize = (s: string) => s.replace(/_/g, ' ')

const KEY_FIELDS = ['status', 'on_hand', 'shortfall', 'on_order', 'will_ship', 'eta', 'eta_if_approved_today', 'est_cost',
  'approval_id', 'po_id', 'draft_id', 'amount', 'balance_after', 'projected_balance', 'owner', 'margin_pct', 'total']

/** One short line describing what a tool returned. */
export function digest(result: unknown): string {
  if (result == null) return ''
  if (typeof result === 'string') {
    try { return digest(JSON.parse(result)) } catch { return result.length > 120 ? `${result.slice(0, 120)}…` : result }
  }
  if (Array.isArray(result)) return `${result.length} record${result.length === 1 ? '' : 's'}`
  const r = result as Record<string, unknown>
  if (r.ok === false) return `refused: ${String(r.error ?? r.status)}`
  if (r.found === false) return 'not found'
  const parts = KEY_FIELDS.filter((k) => k in r).slice(0, 5).map((k) => `${humanize(k)} ${fmt(r[k])}`)
  return parts.length ? parts.join(' · ') : `${Object.keys(r).length} fields`
}
const fmt = (v: unknown) => (typeof v === 'boolean' ? (v ? 'yes' : 'no') : typeof v === 'number' ? String(v) : String(v))

export type EntryKind = 'start' | 'say' | 'do' | 'delegate' | 'report' | 'error' | 'human'
export interface Entry { key: string; ts: string; agent: string; depth: number; kind: EntryKind; text: string; detail?: string }

/** Turn audit events (chronological) into readable proceedings. */
export function proceedings(events: AuditEvent[]): Entry[] {
  const out: Entry[] = []
  for (const e of events) {
    const base = { ts: e.ts, agent: e.agent, depth: e.depth }
    const key = `${e.run_id}-${e.step}`
    const d = e.data
    switch (e.event) {
      case 'run_start':
        out.push({ ...base, key, kind: 'start', text: e.depth === 0 ? `Takes up the matter · session ${e.root_run_id}` : `Receives a charge from ${fellowTitle(e.parent ?? '')}`, detail: String(d.prompt ?? '') })
        break
      case 'model_response': {
        // Tool calls appear once, as their own tool_call entries with results.
        if (d.text) out.push({ ...base, key: `${key}s`, kind: 'say', text: String(d.text) })
        break
      }
      case 'tool_call':
        out.push({ ...base, key, kind: 'do', text: String(d.tool), detail: digest(d.result) })
        break
      case 'delegation':
        out.push({
          ...base, key, kind: 'delegate',
          text: d.ok === false ? `Delegation to ${fellowTitle(String(d.to))} refused` : `${d.cached ? 'Reuses the answer of' : 'Delegates to'} ${fellowTitle(String(d.to))}`,
          detail: d.ok === false ? String(d.error) : String(d.task ?? ''),
        })
        break
      case 'run_end': {
        const report = d.report as AgentReport
        out.push({ ...base, key, kind: 'report', text: `Reports: ${humanize(report.status)}`, detail: report.summary })
        break
      }
      case 'run_error':
        out.push({ ...base, key, kind: 'error', text: 'Falters', detail: String(d.error) })
        break
      case 'human_action':
        out.push({ ...base, key, kind: 'human', text: `${String(d.decided_by ?? 'The Desk')}: ${humanize(String(d.action))}`, detail: d.result ? digest(d.result) : undefined })
        break
    }
  }
  return out
}

export type FellowStatus = 'absent' | 'deliberating' | 'acting' | 'reported' | 'faltered'
export interface FellowState { status: FellowStatus; saying?: string; doing?: string; doingDetail?: string; tools: number; delegations: number; reports: AgentReport[] }

/** What each fellow is saying and doing, derived from one run's events (chronological). */
export function fellowStates(events: AuditEvent[]): Record<AgentName, FellowState> {
  const s = Object.fromEntries(AGENTS.map((a) => [a, { status: 'absent', tools: 0, delegations: 0, reports: [] } as FellowState])) as Record<AgentName, FellowState>
  for (const e of events) {
    if (!isAgent(e.agent)) continue
    const f = s[e.agent]
    const d = e.data
    switch (e.event) {
      case 'run_start': f.status = 'deliberating'; f.doing = 'Reading the charge'; f.doingDetail = undefined; break
      case 'model_response': {
        if (d.text) f.saying = String(d.text)
        const calls = ((d.tool_calls ?? []) as { tool: string }[]).filter((c) => c.tool !== 'final_result')
        if (calls.length) { f.status = 'acting'; f.doing = calls.map((c) => c.tool).join(', '); f.doingDetail = undefined }
        break
      }
      case 'tool_call': f.tools += 1; f.doing = String(d.tool); f.doingDetail = digest(d.result); break
      case 'delegation':
        if (d.ok !== false) f.delegations += 1
        f.status = 'acting'
        f.doing = d.ok === false ? `Delegation to ${fellowTitle(String(d.to))} refused` : `Awaiting ${fellowTitle(String(d.to))}`
        f.doingDetail = d.ok === false ? String(d.error) : String(d.task ?? '')
        break
      case 'run_end': {
        const r = d.report as AgentReport
        f.status = 'reported'; f.reports.push(r); f.saying = r.summary; f.doing = 'Report filed'; f.doingDetail = undefined
        break
      }
      case 'run_error': f.status = 'faltered'; f.doing = 'Run failed'; f.doingDetail = String(d.error); break
    }
  }
  return s
}
