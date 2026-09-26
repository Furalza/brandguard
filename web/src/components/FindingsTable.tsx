import { Fragment, useState } from 'react'
import { LABEL_TEXT, SOURCE_LABEL, type Brand, type Finding, type Source } from '../api'
import { plainEvidence } from '../explain'
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
