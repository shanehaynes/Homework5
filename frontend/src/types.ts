export const AGENTS = ['boss', 'inventory', 'accounting', 'facilities', 'customer_service'] as const
export type AgentName = (typeof AGENTS)[number]

export interface Ticket {
  id: number
  type: string
  requester: string
  subject: string
  status: string
  state: 'open' | 'resolved'
  owner?: AgentName | null
  sku?: string | null
  size?: string | null
  qty?: number | null
  created_at: string
}

export interface AgentReport {
  status: 'done' | 'in_progress' | 'blocked' | 'needs_human' | 'failed'
  summary: string
  ticket_ids: number[]
  actions: string[]
  needs_human: string[]
  follow_ups: string[]
}

export interface RunJob {
  run_id: string
  ticket_id: number
  status: 'running' | 'done' | 'failed'
  started_at: string
  finished_at?: string | null
  report?: AgentReport | null
  error?: string | null
}

export interface AuditEvent {
  ts: string
  root_run_id: string
  run_id: string
  agent: AgentName | 'human'
  depth: number
  parent: string | null
  ticket_id: number | null
  step: number
  event: 'run_start' | 'model_response' | 'tool_call' | 'delegation' | 'run_end' | 'run_error' | 'human_action'
  data: Record<string, any>
}

export interface Approval {
  id: number
  kind: 'payment' | 'purchase' | 'discount'
  ticket_id?: number
  ref_kind?: string
  ref_id?: number
  amount?: number
  details: string
  requested_by: string
  requested_at: string
  status: 'pending' | 'approved' | 'rejected' | 'executed' | 'refused'
  decided_by?: string
  decided_at?: string
  decision_note?: string
}

export interface Cash {
  account: string
  balance: number
  shop_date: string
}

export interface TicketDetail {
  found: boolean
  ticket: Ticket & { notes?: string; lease_id?: number; invoice_id?: number }
  owner: AgentName | null
  recent_messages: { id: number; from_agent: string; to_agent: string; kind: string; body: string }[]
  approvals: { id: number; kind: string; amount?: number; status: string; requested_by: string; decided_by?: string }[]
  purchase_orders: { id: number; vendor_id: number; sku: string; size: string; qty: number; est_cost: number; eta: string; status: string }[]
  reply_drafts: { id: number; status: string; drafted_by: string; body: string }[]
  facility_issues: { id: number; issue: string; severity: string; status: string }[]
}
