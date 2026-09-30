import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, downloadFile, CATEGORY_HINT, CATEGORY_LABEL, CATEGORY_ORDER, SOURCE_LABEL, type Category, type Finding, type Source } from '../api'
import { useLocalState, usePolling } from '../hooks'
import { Counters } from '../components/Counters'
import { SourceStrip } from '../components/SourceStrip'
import { FindingsTable } from '../components/FindingsTable'
import { DetailsDrawer } from '../components/DetailsDrawer'
import { CategoryBadge, StatusPill, fmtDate } from '../ui'

const DEFAULT_TAB: Category[] = ['malicious', 'suspicious']
type Tab = 'actionable' | 'new' | Category | 'all'

const HOW_TEXT: Record<string, string> = {
  existing: 'saved profile used',
  name_only: 'name only: no official domain could be established',
  'domain+play': 'from the domain, verified by the Play publisher',
  'domain+knowledge_panel': 'from the domain, via the Google knowledge panel',
  'domain+page_title': 'from the domain, via the page title',
  domain_only: 'domain only: the brand name was guessed',
}

function howText(how: string): string {
  if (HOW_TEXT[how]) return HOW_TEXT[how]
  if (how.startsWith('re-resolved:')) return `profile resolved again: ${howText(how.slice(12))}`
  if (how.startsWith('package+')) return `from the package id; ${howText(how.slice(8))}`
  if (how.startsWith('name+')) return `from the brand name; official domain found via ${how.slice(5)}`
  return how
}

export default function ScanPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('actionable')
  const [source, setSource] = useState<string>('')
  const [query, setQuery] = useState('')
  const [hideMirrors, setHideMirrors] = useLocalState<boolean>('bg.hideMirrors', false)
  const [selected, setSelected] = useState<Finding | null>(null)
  const [exporting, setExporting] = useState<'idle' | 'busy' | 'error'>('idle')

  async function exportJson() {
    setExporting('busy')
    try {
      await downloadFile(`/api/scans/${id}/export`, `brandguard_scan_${id.slice(0, 8)}.json`)
      setExporting('idle')
    } catch {
      setExporting('error')
    }
  }

  const { data: scan, error, reload } = usePolling(() => api.getScan(id), 2500, true, [id])
  const live = !scan || scan.status === 'queued' || scan.status === 'running'

  const category = useMemo(() => {
    if (tab === 'all' || tab === 'new') return undefined
    if (tab === 'actionable') return DEFAULT_TAB.join(',')
    return tab
  }, [tab])

  const { data: page, reload: reloadItems } = usePolling(
    () =>
      api.listItems(id, {
        category,
        source: source || undefined,
        q: query || undefined,
        new_only: tab === 'new',
        open_only: tab === 'actionable',
        limit: 500,
      }),
    2500,
    live,
    [id, category, source, query, tab],
  )

  // What changed since the previous scan of this brand (same sources).
  const { data: diff } = usePolling(() => api.scanDiff(id), 60000, false, [id, scan?.status])
  const [showDiff, setShowDiff] = useState(false)

  const onReviewChanged = useCallback(() => {
    void reload()
    void reloadItems()
  }, [reload, reloadItems])

  // When the scan finishes, refresh the table one last time.
  useEffect(() => {
    if (scan && !live) void reloadItems()
  }, [scan?.status]) // eslint-disable-line react-hooks/exhaustive-deps

  const retry = useCallback(
    async (s?: Source) => {
      await api.retryScan(id, s)
      await reload()
    },
    [id, reload],
  )

  const close = useCallback(() => setSelected(null), [])

  if (error && !scan) {
    return (
      <div className="card p-6">
        <div className="font-medium">Scan not found</div>
        <div className="muted text-sm mt-1">{error}</div>
        <Link to="/" className="btn btn-sm mt-4">New scan</Link>
      </div>
    )
  }
  if (!scan) return <div className="faint">Loading…</div>

  const counts = scan.counts ?? {}
  const mirrorCount = page ? page.items.filter((f) => f.reason === 'mirror_unverified').length : 0
  const visibleItems = page ? (hideMirrors ? page.items.filter((f) => f.reason !== 'mirror_unverified') : page.items) : []
  const actionable = counts.needs_action ?? (counts.malicious ?? 0) + (counts.suspicious ?? 0)
  const newCount = diff && diff.against_id ? diff.new.length : null
  const failed = scan.source_runs.filter((r) => r.status === 'failed')

  return (
    <div className="flex flex-col gap-5">
      <div className="page-head flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="text-xs faint mb-1">
            <Link to="/scans">Scans</Link> / {scan.id.slice(0, 8)}
          </div>
          <h1 className="text-xl font-semibold tracking-tight flex items-center gap-3">
            <Link to={`/brands/${scan.brand.id}`} style={{ color: 'inherit' }}>
              {scan.brand.brand_name}
            </Link>
            <StatusPill status={scan.status} />
          </h1>
          <div className="text-sm muted mt-1">
            Input <span className="mono">{scan.input_raw}</span> · {howText(scan.resolved_how)} · depth {scan.depth} ·{' '}
            {fmtDate(scan.created_at)}
          </div>
        </div>
        <div className="actions flex items-center gap-2 shrink-0">
          {failed.length > 0 && !live && (
            <button type="button" className="btn btn-sm" onClick={() => void retry()}>
              Retry failed sources
            </button>
          )}
          {live && (
            <button
              type="button"
              className="btn btn-sm btn-danger"
              onClick={() => {
                if (window.confirm('Cancel this scan? Sources still queued will not run; results already collected are kept.'))
                  void api.cancelScan(id).then(() => reload())
              }}
              title="Stop this scan. Results already collected are kept."
            >
              Cancel scan
            </button>
          )}
          {!live && (
            <button
              type="button"
              className={`btn btn-sm ${exporting === 'error' ? 'btn-danger' : ''}`}
              disabled={exporting === 'busy'}
              onClick={() => void exportJson()}
              title="Download the whole scan as one JSON file"
            >
              {exporting === 'busy' ? 'Exporting…' : exporting === 'error' ? 'Export failed, retry' : 'Export JSON'}
            </button>
          )}
          {!live && (
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              onClick={() => {
                if (window.confirm('Delete this scan and its findings? The brand and your reviews stay.'))
                  void api.deleteScan(id).then(() => navigate('/scans'))
              }}
              title="Delete this scan (the brand stays)"
            >
              Delete
            </button>
          )}
          <Link
            to={`/?input=${encodeURIComponent(scan.input_raw)}`}
            className="btn btn-sm btn-primary"
            title="Run this brand again with the same input"
          >
            Scan again
          </Link>
        </div>
      </div>

      {scan.brand.needs_review && (
        <div className="text-sm px-4 py-3 rounded-md flex items-start gap-3" style={{ background: 'var(--suspicious-bg)', border: '1px solid var(--suspicious-border)', color: 'var(--suspicious)' }}>
          <span className="font-semibold shrink-0">Profile needs review</span>
          <span style={{ color: 'var(--text)' }}>
            {scan.brand.review_notes[0]}
            {scan.brand.review_notes.length > 1 && ` (+${scan.brand.review_notes.length - 1})`}{' '}
            <Link to={`/brands/${scan.brand.id}`}>edit the profile</Link>
          </span>
        </div>
      )}

      <SourceStrip runs={scan.source_runs} onRetry={(s) => void retry(s)} />

      {!live && diff && diff.against_id && (
        <div className="card px-4 py-3 text-sm">
          <div className="flex items-center gap-4 flex-wrap">
            <span className="font-medium">Since the previous scan</span>
            <span style={{ color: diff.new.length ? 'var(--malicious)' : 'var(--text-2)' }}>
              {diff.new.length} new
            </span>
            <span className="muted">{diff.gone.length} gone</span>
            <span className="muted">{diff.changed.length} changed category</span>
            <span className="faint">{diff.unchanged} unchanged</span>
            <Link to={`/scans/${diff.against_id}`} className="text-xs ml-auto">previous scan →</Link>
            {(diff.gone.length > 0 || diff.changed.length > 0) && (
              <button type="button" className="text-xs faint" onClick={() => setShowDiff((v) => !v)}>
                {showDiff ? 'hide details' : 'show details'}
              </button>
            )}
          </div>
          {showDiff && (
            <div className="mt-3 grid-2 text-xs">
              <div>
                <div className="label mb-1">Gone (was in the previous scan)</div>
                {diff.gone.length === 0 ? (
                  <div className="faint">—</div>
                ) : (
                  <ul className="flex flex-col gap-1">
                    {diff.gone.map((f) => (
                      <li key={f.id} className="flex items-center gap-2">
                        <CategoryBadge category={f.category} />
                        <span className="truncate">{f.name || f.key}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div>
                <div className="label mb-1">Changed category</div>
                {diff.changed.length === 0 ? (
                  <div className="faint">—</div>
                ) : (
                  <ul className="flex flex-col gap-1">
                    {diff.changed.map((f) => (
                      <li key={f.id} className="flex items-center gap-2">
                        <span className="faint">{CATEGORY_LABEL[f.previous_category ?? 'noise']}</span>
                        <span className="faint">→</span>
                        <CategoryBadge category={f.category} />
                        <span className="truncate">{f.name || f.key}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      <Counters counts={counts} active={tab === 'actionable' || tab === 'new' ? undefined : tab} onSelect={(c) => setTab(c)} />

      <div className="card">
        <div className="toolbar px-3 pt-1" style={{ borderBottom: '1px solid var(--border)' }}>
          <div className="tabs flex-1" style={{ borderBottom: 0 }}>
            <button type="button" className={`tab ${tab === 'actionable' ? 'active' : ''}`} onClick={() => setTab('actionable')}>
              Needs action <span className="faint tnum ml-1">{actionable}</span>
            </button>
            {newCount !== null && (
              <button type="button" className={`tab ${tab === 'new' ? 'active' : ''}`} onClick={() => setTab('new')} title="Keys first seen in this scan">
                New <span className="faint tnum ml-1">{newCount}</span>
              </button>
            )}
            {CATEGORY_ORDER.map((c) => (
              <button key={c} type="button" className={`tab ${tab === c ? 'active' : ''}`} onClick={() => setTab(c)} title={CATEGORY_HINT[c]}>
                {CATEGORY_LABEL[c]} <span className="faint tnum ml-1">{counts[c] ?? 0}</span>
              </button>
            ))}
            <button type="button" className={`tab ${tab === 'all' ? 'active' : ''}`} onClick={() => setTab('all')}>
              All <span className="faint tnum ml-1">{counts.total ?? 0}</span>
            </button>
          </div>
          <select className="input text-sm" style={{ width: 170, padding: '5px 8px' }} value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="">All sources</option>
            {scan.sources.map((s) => (
              <option key={s} value={s === 'play' ? 'google_play' : s}>
                {SOURCE_LABEL[s]}
              </option>
            ))}
          </select>
          <input className="input text-sm" style={{ width: 220, padding: '5px 8px' }} placeholder="Search (name, package, domain)" value={query} onChange={(e) => setQuery(e.target.value)} />
          {mirrorCount > 0 && (
            <label
              className="inline-flex items-center gap-1.5 text-xs muted whitespace-nowrap cursor-pointer"
              title="Copies of the brand's own app on APK mirror sites (apkpure, uptodown, apkmirror...). Unauthorized distribution, not impersonation; hide them to focus on the rest."
            >
              <input type="checkbox" checked={hideMirrors} onChange={(e) => setHideMirrors(e.target.checked)} />
              Hide mirror copies <span className="faint tnum">{mirrorCount}</span>
            </label>
          )}
        </div>
        <div className="overflow-auto findings-scroll" style={{ maxHeight: 'calc(100vh - 380px)', minHeight: 200 }}>
          {page ? (
            <FindingsTable
              items={visibleItems}
              selectedId={selected?.id ?? null}
              onSelect={setSelected}
              scanning={live}
              brand={scan.brand}
              onBrandUpdated={() => void reload()}
              onReviewChanged={onReviewChanged}
            />
          ) : (
            <div className="p-6 faint">Loading…</div>
          )}
        </div>
        <div className="px-4 py-2 text-xs faint flex items-center justify-between" style={{ borderTop: '1px solid var(--border)' }}>
          <span>{page ? `${visibleItems.length} / ${page.total} findings${hideMirrors && mirrorCount ? ` (${mirrorCount} mirror copies hidden)` : ''}` : ''}{live ? ' · scan in progress' : ''}</span>
          <span className="hide-sm">
            Click a row or press <span className="kbd">Enter</span> for details · <span className="kbd">▾</span> or <span className="kbd">Space</span> shows why · <span className="kbd">Esc</span> closes
          </span>
        </div>
      </div>

      <DetailsDrawer finding={selected} onClose={close} brand={scan.brand} onBrandUpdated={() => void reload()} onReviewChanged={onReviewChanged} />
    </div>
  )
}
