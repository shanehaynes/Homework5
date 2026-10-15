import { FELLOWS, humanize } from '../college'
import type { FellowState } from '../college'
import type { AgentName } from '../types'
import { AGENTS } from '../types'

/** Short summary of what each fellow did on this ticket, from their filed reports. */
export function Minutes({ states }: { states: Record<AgentName, FellowState> }) {
  const reporting = AGENTS.filter((a) => states[a].reports.length > 0)
  if (reporting.length === 0) return null
  return (
    <section className="panel minutes">
      <h2 className="panel-title"><span>Minutes of the Meeting</span></h2>
      <div className="minutes-grid">
        {reporting.map((a) => {
          const r = states[a].reports[states[a].reports.length - 1]
          return (
            <div key={a} className="minute">
              <div className="minute-head">
                <b>{FELLOWS[a].title}</b>
                <span className={`chip report-${r.status}`}>{humanize(r.status)}</span>
              </div>
              <p>{r.summary}</p>
              {r.actions.length > 0 && (
                <ul className="actions">{r.actions.map((x, i) => <li key={i}>{x}</li>)}</ul>
              )}
              {r.needs_human.length > 0 && (
                <div className="needs-human">
                  <span className="label">Requires the Desk</span>
                  <ul>{r.needs_human.map((x, i) => <li key={i}>{x}</li>)}</ul>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}
