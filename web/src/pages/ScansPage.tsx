import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError, SOURCE_LABEL } from '../api'
import { useMediaQuery, usePolling } from '../hooks'
import { Counters } from '../components/Counters'
import { Empty, Segmented, StatusPill, fmtDate } from '../ui'

const PAGE_SIZE = 50
const VIEWS = ['all', 'active', 'attention', 'batches'] as const
type View = (typeof VIEWS)[number]

/** Page numbers to show: first, last, and a window around the current one. */
function pageNumbers(current: number, last: number): (number | '…')[] {
  if (last <= 7) return Array.from({ length: last }, (_, i) => i + 1)
  const set = new Set<number>([1, last, current - 1, current, current + 1])
  const out: (number | '…')[] = []
  let prev = 0
  for (const n of [...set].filter((n) => n >= 1 && n <= last).sort((a, b) => a - b)) {
    if (n - prev > 1) out.push('…')
    out.push(n)
    prev = n
  }
  return out
}

export default function ScansPage() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const view = (VIEWS as readonly string[]).includes(params.get('view') ?? '') ? (params.get('view') as View) : 'all'
  const page = Math.max(1, Number(params.get('page') ?? '1') || 1)
  const q = params.get('q') ?? ''
  const [draft, setDraft] = useState(q)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Debounce the search box into the URL so the back button and reloads keep it.
  useEffect(() => {
    const t = window.setTimeout(() => {
      if (draft !== q) update({ q: draft, page: '1' })
    }, 300)
    return () => window.clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft])

  function update(next: Record<string, string>) {
    const p = new URLSearchParams(params)
    Object.entries(next).forEach(([k, v]) => (v && v !== 'all' && v !== '1' ? p.set(k, v) : p.delete(k)))
    setParams(p, { replace: true })
  }

  const { data, reload } = usePolling(
    () => api.searchScans({ q, view, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE }),
    5000,
    true,
    [q, view, page],
  )

  async function cancel(id: string) {
    if (!window.confirm('Cancel this scan? Results already collected are kept.')) return
    await api.cancelScan(id)
    await reload()
  }

  async function remove(id: string, name: string) {
    if (!window.confirm(`Delete this scan of "${name}"? Its findings go with it; the brand and your reviews stay.`)) return
    setBusy(id)
    setError(null)
    try {
      await api.deleteScan(id)
      await reload()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'delete failed')
    } finally {
      setBusy(null)
    }
  }

  const phone = useMediaQuery('(max-width: 640px)')
  const total = data?.total ?? 0
  const last = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const rows = data?.items ?? []
  const from = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1
  const to = Math.min(total, page * PAGE_SIZE)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <h1 className="text-xl font-semibold tracking-tight">Scans</h1>
        <Link to="/" className="btn btn-primary">
          + New scan
        </Link>
      </div>
      <div className="flex items-center gap-3 flex-wrap">
        <Segmented
          value={view}
          onChange={(v) => update({ view: v, page: '1' })}
          options={[
            { value: 'all', label: 'All' },
            { value: 'active', label: 'Running', hint: 'Queued or running scans' },
            { value: 'attention', label: 'Needs attention', hint: 'Scans with malicious or suspicious findings' },
            { value: 'batches', label: 'In a batch' },
          ]}
        />
        <input
          className="input"
          style={{ maxWidth: 280 }}
          placeholder="Filter by brand or input…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        {data && (
          <span className="text-xs faint ml-auto tnum">
            {total === 0 ? 'no scans' : `${from}–${to} of ${total}`}
          </span>
        )}
      </div>
      {error && (
        <div
          className="text-sm px-4 py-2 rounded-md"
          style={{ background: 'var(--malicious-bg)', border: '1px solid var(--malicious-border)', color: 'var(--malicious)' }}
        >
          {error}
        </div>
      )}
      <div className="card overflow-hidden table-wrap">
        {!data ? (
          <div className="p-6 faint">Loading…</div>
        ) : total === 0 && !q && view === 'all' ? (
          <Empty title="No scans yet" body="Start by entering a brand name, its domain or its Google Play link." />
        ) : rows.length === 0 ? (
          <Empty title="Nothing matches this filter" body="Pick another filter or clear the search box." />
        ) : phone ? (
          <ul className="flex flex-col">
            {rows.map((s) => {
              const live = s.status === 'queued' || s.status === 'running'
              return (
                <li key={s.id} className="px-3 py-3" style={{ borderBottom: '1px solid var(--border)' }}>
                  <div className="flex items-start justify-between gap-2">
                    <Link to={`/scans/${s.id}`} className="font-medium" style={{ color: 'inherit' }}>
                      {s.brand_name}
                    </Link>
                    <StatusPill status={s.status} />
                  </div>
                  <div className="text-xs faint mono mt-0.5" style={{ overflowWrap: 'anywhere' }}>
                    {s.input_raw}
                  </div>
                  <div className="text-xs faint mt-1">
                    {s.sources.map((x) => SOURCE_LABEL[x]).join(', ')} · {s.depth} · {fmtDate(s.created_at)}
                    {s.trigger === 'schedule' ? ' · scheduled' : ''}
                    {s.batch_id ? (
                      <>
                        {' · '}
                        <Link to={`/batches/${s.batch_id}`}>batch {s.batch_id.slice(0, 8)}</Link>
                      </>
                    ) : null}
                  </div>
                  <div className="mt-2">
                    <Counters counts={s.counts} compact />
                  </div>
                  <div className="flex items-center gap-2 mt-2">
                    <Link to={`/scans/${s.id}`} className="btn btn-sm">
                      Open →
                    </Link>
                    {live ? (
                      <button type="button" className="btn btn-sm btn-danger" onClick={() => void cancel(s.id)}>
                        Cancel
                      </button>
                    ) : (
                      <button type="button" className="btn btn-sm btn-ghost" disabled={busy === s.id} onClick={() => void remove(s.id, s.brand_name)}>
                        Delete
                      </button>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Brand</th>
                <th>Input</th>
                <th>Sources</th>
                <th>Depth</th>
                <th>Status</th>
                <th>Result</th>
                <th>Time</th>
                <th>Batch</th>
                <th style={{ width: 220 }} />
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => {
                const live = s.status === 'queued' || s.status === 'running'
                return (
                  <tr key={s.id} className="row" onClick={() => navigate(`/scans/${s.id}`)}>
                    <td className="font-medium">
                      <Link to={`/scans/${s.id}`} style={{ color: 'inherit' }}>
                        {s.brand_name}
                      </Link>
                    </td>
                    <td className="mono text-xs muted" style={{ maxWidth: 360, overflowWrap: 'anywhere' }}>
                      {s.input_raw}
                      {s.trigger === 'schedule' && (
                        <span className="ml-2 badge badge-noise" style={{ fontWeight: 500 }} title="Started by the brand's schedule">
                          scheduled
                        </span>
                      )}
                    </td>
                    <td className="text-sm muted">{s.sources.map((x) => SOURCE_LABEL[x]).join(', ')}</td>
                    <td className="text-sm muted">{s.depth}</td>
                    <td>
                      <StatusPill status={s.status} />
                    </td>
                    <td>
                      <Counters counts={s.counts} compact />
                    </td>
                    <td className="text-xs faint">{fmtDate(s.created_at)}</td>
                    <td className="text-xs" onClick={(e) => e.stopPropagation()}>
                      {s.batch_id ? (
                        <Link to={`/batches/${s.batch_id}`} title="Open the batch this scan belongs to">
                          {s.batch_id.slice(0, 8)}
                        </Link>
                      ) : (
                        <span className="faint">—</span>
                      )}
                    </td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center gap-1.5 justify-end">
                        {live ? (
                          <button type="button" className="btn btn-sm btn-danger" onClick={() => void cancel(s.id)}>
                            Cancel
                          </button>
                        ) : (
                          <button
                            type="button"
                            className="btn btn-sm btn-ghost"
                            disabled={busy === s.id}
                            onClick={() => void remove(s.id, s.brand_name)}
                            title="Delete this scan and its findings (the brand stays)"
                          >
                            Delete
                          </button>
                        )}
                        <Link to={`/scans/${s.id}`} className="btn btn-sm">
                          Open →
                        </Link>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
        {last > 1 && (
          <div className="flex items-center justify-between gap-3 px-4 py-2" style={{ borderTop: '1px solid var(--border)' }}>
            <button type="button" className="btn btn-sm" disabled={page <= 1} onClick={() => update({ page: String(page - 1) })}>
              ← Previous
            </button>
            <div className="flex items-center gap-1">
              {pageNumbers(page, last).map((n, i) =>
                n === '…' ? (
                  <span key={`gap-${i}`} className="faint px-1">
                    …
                  </span>
                ) : (
                  <button
                    key={n}
                    type="button"
                    className={`btn btn-sm ${n === page ? 'btn-primary' : 'btn-ghost'}`}
                    onClick={() => update({ page: String(n) })}
                    aria-current={n === page ? 'page' : undefined}
                  >
                    {n}
                  </button>
                ),
              )}
            </div>
            <button type="button" className="btn btn-sm" disabled={page >= last} onClick={() => update({ page: String(page + 1) })}>
              Next →
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
