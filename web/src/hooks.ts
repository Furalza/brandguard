import { useCallback, useEffect, useRef, useState } from 'react'

/** Fetch once, then re-fetch every `intervalMs` while `active` is true. */
export function usePolling<T>(fetcher: () => Promise<T>, intervalMs: number, active: boolean, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  const load = useCallback(async () => {
    try {
      const value = await fetcherRef.current()
      setData(value)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    setLoading(true)
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => {
    if (!active) return
    const id = window.setInterval(() => void load(), intervalMs)
    return () => window.clearInterval(id)
  }, [active, intervalMs, load])

  return { data, error, loading, reload: load }
}

export function useLocalState<T>(key: string, initial: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = window.localStorage.getItem(key)
      return raw ? (JSON.parse(raw) as T) : initial
    } catch {
      return initial
    }
  })
  const set = (v: T) => {
    setValue(v)
    try {
      window.localStorage.setItem(key, JSON.stringify(v))
    } catch {
      /* storage may be unavailable */
    }
  }
  return [value, set]
}
