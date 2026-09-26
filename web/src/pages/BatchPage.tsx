import { useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, downloadFile, SOURCE_LABEL } from '../api'
import { usePolling } from '../hooks'
import { Counters } from '../components/Counters'
import { Empty, StatusPill, fmtDate } from '../ui'

export default function BatchPage() {
  const { id = '' } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const { data: batch, error } = usePolling(() => api.getBatch(id), 3000, true, [id])
  // Inputs that could not be scanned are known only at creation; the start
  // page hands them over so they are shown once, next to the batch.
  const initialErrors = ((location.state as { errors?: { input: string; error: string }[] } | null)?.errors) ?? []
  const [exporting, setExporting] = useState<string | null>(null)   // 'all' | scan id
  const [exportError, setExportError] = useState<string | null>(null)

  async function download(path: string, key: string, fallback: string) {
    setExporting(key)
    setExportError(null)
    try {
      await downloadFile(path, fallback)
    } catch {
      setExportError(key)
    } finally {
      setExporting(null)
    }
  }

  if (error && !batch) {
    return (
      <div className="card p-6">
        <div className="font-medium">Batch not found</div>
        <div className="muted text-sm mt-1">{error}</div>
        <Link to="/" className="btn btn-sm mt-4">New scan</Link>
      </div>
    )
  }
  if (!batch) return <div className="faint">Loading…</div>

  const done = batch.scans.filter((s) => s.status !== 'queued' && s.status !== 'running').length
  const live = batch.status === 'running'
  const errors = batch.errors.length ? batch.errors : initialErrors

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-xs faint mb-1">
            <Link to="/scans">Scans</Link> / batch {batch.id.slice(0, 8)}
          </div>
          <h1 className="text-xl font-semibold tracking-tight flex items-center gap-3">
            {batch.scans.length} brand{batch.scans.length === 1 ? '' : 's'}
            <StatusPill status={live ? 'running' : 'done'} />
          </h1>
          <div className="text-sm muted mt-1">
            {done} / {batch.scans.length} finished · started {fmtDate(batch.created_at)}
            {live && <span className="running pulse ml-2">scanning…</span>}
          </div>
          <div className={`progress mt-2 ${live ? '' : 'done'}`} style={{ maxWidth: 360 }} aria-hidden>
            <span style={{ width: `${batch.scans.length ? Math.round((done / batch.scans.length) * 100) : 0}%` }} />
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {live && (
            <button
              type="button"
              className="btn btn-sm btn-danger"
              onClick={() => {
                if (window.confirm('Cancel the remaining scans of this batch? Finished ones are kept.')) void api.cancelBatch(batch.id)
              }}
            >
              Cancel remaining
            </button>
          )}
          {!live && (
            <button
              type="button"
              className="btn btn-sm"
              disabled={exporting === 'all'}
              onClick={() => void download(`/api/batches/${batch.id}/export`, 'all', `brandguard_batch_${batch.id.slice(0, 8)}.zip`)}
              title="One ZIP: a JSON file per brand plus summary.json"
              style={exportError === 'all' ? { color: 'var(--malicious)' } : undefined}
            >
              {exporting === 'all' ? 'Exporting…' : exportError === 'all' ? 'Export failed, retry' : 'Export all (ZIP)'}
            </button>
          )}
          <Link to="/" className="btn btn-sm btn-primary">+ New scan</Link>
        </div>
      </div>

      {errors.length > 0 && (
        <div className="text-sm px-4 py-3 rounded-md" style={{ background: 'var(--suspicious-bg)', border: '1px solid var(--suspicious-border)' }}>
          <div className="font-semibold mb-1" style={{ color: 'var(--suspicious)' }}>
            {errors.length} input{errors.length === 1 ? '' : 's'} not scanned
          </div>
          <ul className="flex flex-col gap-0.5">
            {errors.map((e, i) => (
              <li key={i}>
                <span className="mono">{e.input}</span> <span className="muted">— {e.error}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <Counters counts={batch.totals} />

      <div className="card overflow-hidden">
        {batch.scans.length === 0 ? (
          <Empty title="No scans in this batch" />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Brand</th>
                <th>Input</th>
                <th>Sources</th>
                <th>Status</th>
                <th>Result</th>
                <th style={{ width: 210 }} />
              </tr>
            </thead>
            <tbody>
              {batch.scans.map((s) => (
                <tr key={s.id} className="row" onClick={() => navigate(`/scans/${s.id}`)}>
                  <td className="font-medium">
                    <Link to={`/scans/${s.id}`} style={{ color: 'inherit' }}>{s.brand_name}</Link>
                  </td>
                  <td className="mono text-xs muted">{s.input_raw}</td>
                  <td className="text-sm muted">{s.sources.map((x) => SOURCE_LABEL[x]).join(', ')}</td>
                  <td><StatusPill status={s.status} /></td>
                  <td><Counters counts={s.counts} compact /></td>
                  <td className="whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center gap-1.5 justify-end">
                      {s.status !== 'queued' && s.status !== 'running' && (
                        <button
                          type="button"
                          className={`btn btn-sm ${exportError === s.id ? 'btn-danger' : ''}`}
                          disabled={exporting === s.id}
                          onClick={() => void download(`/api/scans/${s.id}/export`, s.id, `brandguard_${s.brand_id}.json`)}
                          title="Download this brand's scan as JSON"
                        >
                          {exporting === s.id ? 'Exporting…' : exportError === s.id ? 'Failed, retry' : 'Export JSON'}
                        </button>
                      )}
                      <Link to={`/scans/${s.id}`} className="btn btn-sm btn-ghost">
                        Open →
                      </Link>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="px-4 py-2 text-xs faint" style={{ borderTop: '1px solid var(--border)' }}>
          Totals add up the categories of every scan in the batch. Sources run in parallel across brands, with one Play
          search at a time to stay under the store's rate limit.
        </div>
      </div>
    </div>
  )
}
