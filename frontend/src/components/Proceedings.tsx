import { useEffect, useRef, useState } from 'react'
import { FELLOWS, clock, fellowTitle, isAgent } from '../college'
import type { Entry } from '../college'

export function Proceedings({ entries, live }: { entries: Entry[]; live: boolean }) {
  const [showTools, setShowTools] = useState(true)
  const listRef = useRef<HTMLOListElement>(null)
  const shown = showTools ? entries : entries.filter((e) => e.kind !== 'do')

  useEffect(() => {
    const el = listRef.current
    if (live && el) el.scrollTop = el.scrollHeight
  }, [shown.length, live])

  return (
    <section className="panel proceedings">
      <div className="panel-head">
        <h2 className="panel-title"><span>The Proceedings</span></h2>
        <label className="toggle">
          <input type="checkbox" checked={showTools} onChange={(e) => setShowTools(e.target.checked)} /> Show tool calls
        </label>
      </div>
      {shown.length === 0 ? (
        <p className="empty">No proceedings recorded for this matter yet.</p>
      ) : (
        <ol className="feed" ref={listRef} aria-live={live ? 'polite' : 'off'}>
          {shown.map((e) => (
            <li key={e.key} className={`entry k-${e.kind}`} style={{ marginLeft: `${Math.min(e.depth, 3) * 22}px` }}>
              <span className="seal-sm" aria-hidden="true">{isAgent(e.agent) ? FELLOWS[e.agent].seal : '✒'}</span>
              <div className="entry-body">
                <div className="entry-head">
                  <b>{fellowTitle(e.agent)}</b>
                  <time>{clock(e.ts)}</time>
                </div>
                <div className={`entry-text ${e.kind === 'do' ? 'mono' : ''}`}>{e.kind === 'say' ? `“${e.text}”` : e.text}</div>
                {e.detail && <div className="entry-detail">{e.detail}</div>}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
