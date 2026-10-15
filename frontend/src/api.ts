import type { Approval, AuditEvent, Cash, RunJob, Ticket, TicketDetail } from './types'

export const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

export class ApiError extends Error {
  readonly status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      const detail = body.detail
      message = typeof detail === 'string' ? detail : detail?.error ?? JSON.stringify(detail)
    } catch {
      /* keep the status text */
    }
    throw new ApiError(res.status, message)
  }
  return res.json() as Promise<T>
}

const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const api = {
  tickets: () => request<Ticket[]>('/tickets'),
  ticket: (id: number) => request<TicketDetail>(`/tickets/${id}`),
  runTicket: (id: number) => post<RunJob>(`/tickets/${id}/run`),
  resolveTicket: (id: number, decided_by: string, note: string) =>
    post<{ ok: boolean }>(`/tickets/${id}/resolve`, { decided_by, note }),
  directTicket: (id: number, decided_by: string, note: string) =>
    post<{ ok: boolean }>(`/tickets/${id}/direct`, { decided_by, note }),
  runs: () => request<RunJob[]>('/runs'),
  activity: (params: { ticketId?: number; runId?: string; limit?: number }) => {
    const q = new URLSearchParams({ limit: String(params.limit ?? 500) })
    if (params.ticketId !== undefined) q.set('ticket_id', String(params.ticketId))
    if (params.runId) q.set('run_id', params.runId)
    return request<AuditEvent[]>(`/activity?${q}`)
  },
  approvals: (status = 'all') => request<Approval[]>(`/approvals?status=${status}`),
  decide: (id: number, decision: 'approve' | 'reject', decided_by: string, note = '') =>
    post<Record<string, unknown>>(`/approvals/${id}/${decision}`, { decided_by, note }),
  cash: () => request<Cash>('/cash'),
  reset: () => post<{ ok: boolean; cash: { name: string; balance: number }[] }>('/reset'),
}
