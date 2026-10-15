import { FELLOWS } from '../college'
import type { FellowState } from '../college'
import type { AgentName } from '../types'
import { Arch } from './Crest'

const STATUS_LABEL: Record<FellowState['status'], string> = {
  absent: 'Not summoned',
  deliberating: 'Deliberating',
  acting: 'At work',
  reported: 'Reported',
  faltered: 'Faltered',
}

export function FellowCard({ agent, state, live }: { agent: AgentName; state: FellowState; live: boolean }) {
  const f = FELLOWS[agent]
  const busy = live && (state.status === 'deliberating' || state.status === 'acting')
  return (
    <article className={`fellow status-${state.status} ${busy ? 'busy' : ''}`} aria-label={`${f.title} (${f.name})`}>
      <Arch seal={f.seal} active={state.status !== 'absent'} />
      <div className="fellow-body">
        <div className="fellow-title">{f.title}</div>
        <div className="fellow-name">{f.name} agent</div>
        <span className={`chip fellow-status s-${state.status}`}>{busy && <span className="pulse" aria-hidden="true" />}{STATUS_LABEL[state.status]}</span>

        {state.status === 'absent' ? (
          <p className="fellow-absent">{f.office}.</p>
        ) : (
          <>
            <div className="fellow-says">
              <span className="label">Says</span>
              <blockquote>{state.saying ?? <em className="muted">Has not spoken yet.</em>}</blockquote>
            </div>
            <div className="fellow-doing">
              <span className="label">Doing</span>
              <code>{state.doing ?? '—'}</code>
              {state.doingDetail && <span className="doing-detail">{state.doingDetail}</span>}
            </div>
            <div className="fellow-counts">
              <span>{state.tools} tool call{state.tools === 1 ? '' : 's'}</span>
              <span>{state.delegations} delegation{state.delegations === 1 ? '' : 's'}</span>
            </div>
          </>
        )}
      </div>
    </article>
  )
}
