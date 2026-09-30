import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError, type Brand } from '../api'
import { usePolling } from '../hooks'
import { Empty, relTime } from '../ui'

const FROM_TEXT: Record<string, string> = {
  csv: 'from CSV registry',
  watchlist: 'hand-written profile',
  manual: 'edited by hand',
  auto: 'resolved automatically',
}

export default function BrandsPage() {
  const navigate = useNavigate()
  const { data, reload } = usePolling(() => api.listBrands(), 10000, true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function remove(b: Brand) {
    const ok = window.confirm(
      `Delete "${b.brand_name}" and its ${b.scan_count} scan${b.scan_count === 1 ? '' : 's'}? This cannot be undone.`,
    )
    if (!ok) return
    setBusy(b.id)
    setError(null)
    try {
      await api.deleteBrand(b.id)
      await reload()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'delete failed')
    } finally {
      setBusy(null)
    }
  }

  async function scanNow(b: Brand) {
    setBusy(b.id)
    setError(null)
    try {
      const scan = await api.createScan({
        input: b.official_domains[0] ?? b.brand_name,
        sources: b.schedule_sources.length ? b.schedule_sources : undefined,
        depth: b.schedule_depth,
      })
      navigate(`/scans/${scan.id}`)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'could not start the scan')
      setBusy(null)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-4">
        <div style={{ maxWidth: 820 }}>
          <h1 className="text-xl font-semibold tracking-tight">Brands</h1>
          <p className="muted text-sm mt-1">
            The official identities scans are compared against. Automatically resolved profiles stay flagged until
            someone reviews them. A mistyped brand can be deleted here together with its scans.
          </p>
        </div>
        <Link to="/" className="btn btn-primary shrink-0">
          + New scan
        </Link>
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
        ) : data.length === 0 ? (
          <Empty title="No brands yet" body="A brand appears here once you start a scan." />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Brand</th>
                <th>Official domains</th>
                <th>Publishers</th>
                <th>Packages</th>
                <th>Origin</th>
                <th>Status</th>
                <th>Re-scan</th>
                <th>Last scan</th>
                <th style={{ width: 190 }} />
              </tr>
            </thead>
            <tbody>
              {data.map((b) => (
                <tr key={b.id} className="row" onClick={() => navigate(`/brands/${b.id}`)}>
                  <td className="font-medium">
                    <Link to={`/brands/${b.id}`} style={{ color: 'inherit' }}>
                      {b.brand_name}
                    </Link>
                    <div className="text-xs faint">{b.sector}</div>
                  </td>
                  <td className="mono text-xs">{b.official_domains.join(', ') || <span className="faint">—</span>}</td>
                  <td className="text-sm muted truncate" style={{ maxWidth: 220 }}>
                    {b.official_publishers.join(', ') || '—'}
                  </td>
                  <td className="text-sm muted tnum">{b.official_package_ids.length}</td>
                  <td className="text-xs muted">{FROM_TEXT[b.resolved_from] ?? b.resolved_from}</td>
                  <td>
                    {b.needs_review ? (
                      <span className="badge badge-suspicious">
                        <span className="dot" />
                        needs review
                      </span>
                    ) : (
                      <span className="badge badge-official">
                        <span className="dot" />
                        ready
                      </span>
                    )}
                  </td>
                  <td className="text-xs muted">
                    {b.schedule === 'off' ? (
                      <span className="faint">off</span>
                    ) : (
                      <span title={b.next_run_at ? `Next run ${relTime(b.next_run_at).replace('ago', 'from now')}` : ''}>
                        {b.schedule}
                      </span>
                    )}
                  </td>
                  <td className="text-xs faint">
                    {b.last_scan_at
                      ? `${relTime(b.last_scan_at)} · ${b.scan_count} scan${b.scan_count === 1 ? '' : 's'}`
                      : '—'}
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center gap-1.5 justify-end">
                      <button
                        type="button"
                        className="btn btn-sm"
                        disabled={busy === b.id}
                        onClick={() => void scanNow(b)}
                        title="Start a new scan for this brand with its saved profile"
                      >
                        Scan now
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm btn-danger"
                        disabled={busy === b.id}
                        onClick={() => void remove(b)}
                        title="Delete this brand and all of its scans"
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
