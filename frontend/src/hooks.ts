import { useEffect, useRef, useState } from 'react'

/** Fetch now, then every `intervalMs`. Returns data, error, and a manual refresh. */
export function usePoll<T>(fetcher: () => Promise<T>, intervalMs: number, deps: unknown[] = []) {
  const [data, setData] = useState<T | undefined>(undefined)
  const [error, setError] = useState<string | undefined>(undefined)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let alive = true
    const load = () =>
      fetcherRef.current().then(
        (d) => { if (alive) { setData(d); setError(undefined) } },
        (e: Error) => { if (alive) setError(e.message) },
      )
    load()
    const id = window.setInterval(load, intervalMs)
    return () => { alive = false; window.clearInterval(id) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, tick, ...deps])

  return { data, error, refresh: () => setTick((t) => t + 1), setData }
}

export function useStoredName() {
  const [name, setName] = useState(() => localStorage.getItem('cc.desk.name') ?? '')
  useEffect(() => { localStorage.setItem('cc.desk.name', name) }, [name])
  return [name, setName] as const
}
