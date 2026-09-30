import { Fragment, useState } from 'react'
import { LABEL_TEXT, SOURCE_LABEL, type Brand, type Finding, type Source } from '../api'
import { plainEvidence } from '../explain'
import { useMediaQuery } from '../hooks'
import { CategoryBadge, Confidence, Empty } from '../ui'
import { Explanation } from './Explanation'
import { ReviewBadge } from './ReviewPanel'

function sourceText(source: string): string {
  if (source.startsWith('serper:')) return source.slice(7)
  if (source.startsWith('google_play')) return 'Google Play'
  if (source === 'app_store') return 'App Store'
  if (source in SOURCE_LABEL) return SOURCE_LABEL[source as Source]
  return source
}

function tierText(f: Finding): string {
  if (f.kind === 'domain') return f.priority ? `priority ${f.priority}` : '—'
  const max = Math.max(0, ...f.tiers_used)
  return max >= 2 ? 'T2 · text reader' : max === 1 ? 'T1 · icon' : 'T0 · rules'
}

/** Strongest evidence line, in plain words, so the table alone tells the story. */
function topEvidence(f: Finding): string {
  if (!f.evidence.length) return ''
  const hint = f.evidence.find((e) => e.signal === 'affiliate_hint' || e.signal === 'developer_account')
  if (hint) return plainEvidence(hint)
  const sorted = [...f.evidence].sort((a, b) => Math.abs(b.weight) - Math.abs(a.weight))
  return plainEvidence(sorted[0])
}

export function FindingsTable({
  items,
  selectedId,
  onSelect,
  scanning = false,
  brand,
  onBrandUpdated,
  onReviewChanged,
}: {
  items: Finding[]
  selectedId: string | null
  onSelect: (f: Finding) => void
  scanning?: boolean
  brand?: Brand | null
  onBrandUpdated?: (b: Brand) => void
  onReviewChanged?: () => void
}) {
  const [open, setOpen] = useState<string | null>(null)
  const phone = useMediaQuery('(max-width: 640px)')

  if (!items.length) {
    if (scanning)
      return (
        <Empty
          title={
            <span className="inline-flex items-center gap-2 running">
              <span className="dot pulse" /> Scanning…
            </span>
          }
          body="Findings appear here as each source finishes. Nothing has been ruled out yet."
        />
      )
    return <Empty title="No findings in this filter" body="Pick another category, or the scan found nothing here." />
  }

  const toggle = (f: Finding) => setOpen(open === f.id ? null : f.id)

  if (phone) {
    // One card per finding: the table's seven columns do not fit a phone,
    // and the explanation must open at full width under its row.
    return (
      <ul className="flex flex-col">
        {items.map((f) => {
          const expanded = open === f.id
          return (
            <li key={f.id} className="px-3 py-3" style={{ borderBottom: '1px solid var(--border)' }}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-medium" style={{ overflowWrap: 'anywhere' }}>{f.name || f.key}</div>
                  <div className="text-xs faint mono" style={{ overflowWrap: 'anywhere' }}>
                    {f.kind === 'app' && f.name ? f.key : LABEL_TEXT[f.label] ?? f.label}
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1 shrink-0">
                  <CategoryBadge category={f.category} />
                  <ReviewBadge review={f.review} />
                </div>
              </div>
              <div className="text-xs muted mt-1.5 leading-snug">{topEvidence(f)}</div>
              <div className="flex items-center justify-between gap-2 mt-2 text-xs faint">
                <span className="truncate">
                  {sourceText(f.source)} · {tierText(f)} · {f.seen_before ? 'seen earlier' : 'new'}
                </span>
                {f.kind === 'domain' ? (
                  <span className="tnum shrink-0">similarity {Math.round((f.similarity ?? 0) * 100)}%</span>
                ) : (
                  <Confidence value={f.confidence} />
                )}
              </div>
              <div className="flex items-center gap-2 mt-2">
                <button type="button" className="btn btn-sm" aria-expanded={expanded} onClick={() => toggle(f)}>
                  {expanded ? 'Hide why' : 'Why?'}
                </button>
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => onSelect(f)}>
                  Details
                </button>
              </div>
              {expanded && (
                <div className="mt-3 pt-3" style={{ borderTop: '1px dashed var(--border-strong)' }}>
                  <Explanation finding={f} brand={brand} onBrandUpdated={onBrandUpdated} onReviewChanged={onReviewChanged} compact />
                </div>
              )}
            </li>
          )
        })}
      </ul>
    )
  }

  return (
    <table className="table" style={{ minWidth: 900 }}>
      <thead>
        <tr>
          <th style={{ width: 130 }}>Category</th>
          <th>Finding</th>
          <th style={{ width: 150 }}>Source</th>
          <th style={{ width: 120 }}>Confidence</th>
          <th style={{ width: 120 }}>Decided by</th>
          <th style={{ width: 90, whiteSpace: 'nowrap' }}>First seen</th>
          <th style={{ width: 150 }} aria-label="Actions" />
        </tr>
      </thead>
      <tbody>
        {items.map((f) => {
          const expanded = open === f.id
          return (
            <Fragment key={f.id}>
              <tr
                className={`row ${selectedId === f.id ? 'selected' : ''}`}
                onClick={() => onSelect(f)}
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') onSelect(f)
                  if (e.key === ' ') {
                    e.preventDefault()
                    toggle(f)
                  }
                }}
              >
                <td>
                  <div className="flex flex-col gap-1 items-start">
                    <CategoryBadge category={f.category} />
                    <ReviewBadge review={f.review} />
                  </div>
                </td>
                <td>
                  <div className="font-medium truncate" style={{ maxWidth: 420 }}>
                    {f.name || f.key}
                  </div>
                  <div className="text-xs faint truncate mono" style={{ maxWidth: 420 }}>
                    {f.kind === 'app' && f.name ? f.key : LABEL_TEXT[f.label] ?? f.label}
                    {f.kind === 'app' && f.name ? ` · ${LABEL_TEXT[f.label] ?? f.label}` : ''}
                  </div>
                  <div className="text-xs muted truncate mt-0.5" style={{ maxWidth: 520 }}>
                    {topEvidence(f)}
                  </div>
                </td>
                <td className="text-sm muted">{sourceText(f.source)}</td>
                <td>
                  {f.kind === 'domain' ? (
                    <span className="text-xs muted tnum">similarity {Math.round((f.similarity ?? 0) * 100)}%</span>
                  ) : (
                    <Confidence value={f.confidence} />
                  )}
                </td>
                <td className="text-xs muted">{tierText(f)}</td>
                <td className="text-xs faint">{f.seen_before ? 'earlier' : 'new'}</td>
                <td onClick={(e) => e.stopPropagation()}>
                  <div className="flex items-center gap-1 justify-end">
                    <button
                      type="button"
                      className="btn-link"
                      aria-expanded={expanded}
                      title={expanded ? 'Hide the explanation' : 'Show why BrandGuard decided this'}
                      onClick={() => toggle(f)}
                    >
                      {expanded ? 'Hide' : 'Why?'}
                      <span className={`chevron-icon ${expanded ? 'open' : ''}`}>▾</span>
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm btn-ghost"
                      title="Open full details in the side panel"
                      onClick={() => onSelect(f)}
                    >
                      Details
                    </button>
                  </div>
                </td>
              </tr>
              {expanded && (
                <tr className="expand">
                  <td colSpan={7}>
                    <div className="px-2 py-3" style={{ maxWidth: 980 }}>
                      <Explanation finding={f} brand={brand} onBrandUpdated={onBrandUpdated} onReviewChanged={onReviewChanged} compact />
                    </div>
                  </td>
                </tr>
              )}
            </Fragment>
          )
        })}
      </tbody>
    </table>
  )
}
