import { useEffect } from 'react'
import { LABEL_TEXT, type Brand, type Finding } from '../api'
import { CategoryBadge, fmtDate } from '../ui'
import { Explanation, Fact } from './Explanation'

export function DetailsDrawer({
  finding,
  onClose,
  brand,
  onBrandUpdated,
  onReviewChanged,
}: {
  finding: Finding | null
  onClose: () => void
  brand?: Brand | null
  onBrandUpdated?: (b: Brand) => void
  onReviewChanged?: () => void
}) {
  useEffect(() => {
    if (!finding) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [finding, onClose])

  if (!finding) return null
  const f = finding
  const raw = f.extra

  return (
    <>
      <div className="backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="Finding details">
        <div className="px-5 py-4 flex items-start gap-3" style={{ borderBottom: '1px solid var(--border)' }}>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 mb-1">
              <CategoryBadge category={f.category} />
              <span className="text-xs muted">{LABEL_TEXT[f.label] ?? f.label}</span>
            </div>
            <div className="font-semibold text-[15px] leading-snug break-words">{f.name || f.key}</div>
            <div className="mono text-xs faint break-all mt-0.5">{f.key}</div>
          </div>
          <button type="button" className="btn btn-sm" onClick={onClose} title="Close (Esc)">
            Close
          </button>
        </div>

        <div className="flex-1 overflow-auto px-5 py-4 flex flex-col gap-6">
          <Explanation finding={f} brand={brand} onBrandUpdated={onBrandUpdated} onReviewChanged={onReviewChanged} />

          <section className="grid-2 text-sm">
            <Fact label="Source" value={f.source} mono />
            <Fact
              label={f.kind === 'domain' ? 'Similarity' : 'Confidence'}
              value={
                f.kind === 'domain'
                  ? `${Math.round((f.similarity ?? 0) * 100)}%`
                  : f.confidence !== null
                    ? `${Math.round(f.confidence * 100)}%`
                    : '—'
              }
            />
            <Fact
              label="First seen"
              value={
                <>
                  {fmtDate(f.first_seen_at)} {f.seen_before && <span className="faint text-xs">(also in an earlier scan)</span>}
                </>
              }
            />
            <Fact label="This scan" value={fmtDate(f.created_at)} />
            {f.kind === 'domain' && (
              <>
                <Fact label="Domain age" value={raw.domain_age_days != null ? `${String(raw.domain_age_days)} days` : 'unknown'} />
                <Fact label="Certificate age" value={raw.cert_age_days != null ? `${String(raw.cert_age_days)} days` : 'unknown'} />
              </>
            )}
          </section>

          {f.link && (
            <section>
              <a className="btn btn-sm" href={f.link} target="_blank" rel="noreferrer noopener">
                {f.kind === 'domain' ? 'Open site' : 'Open in store'} ↗
              </a>
              <span className="text-xs faint ml-2">If the site is suspicious, open it in an isolated environment.</span>
            </section>
          )}
        </div>
      </aside>
    </>
  )
}
