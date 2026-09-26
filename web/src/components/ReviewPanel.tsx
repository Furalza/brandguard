import { useEffect, useState } from 'react'
import { api, REVIEW_HINT, REVIEW_LABEL, type Finding, type Review, type ReviewStatus } from '../api'
import { fmtDate } from '../ui'

const ORDER: ReviewStatus[] = ['confirmed', 'takedown_sent', 'false_positive', 'resolved']

export function reviewTone(status: ReviewStatus): string {
  if (status === 'confirmed') return 'var(--malicious)'
  if (status === 'takedown_sent') return 'var(--suspicious)'
  if (status === 'resolved') return 'var(--official)'
  return 'var(--text-3)'
}

/** Small mark for table rows. */
export function ReviewBadge({ review }: { review: Review | null }) {
  if (!review) return null
  return (
    <span
      className="badge"
      style={{ color: reviewTone(review.status), borderColor: 'currentColor', background: 'transparent', fontWeight: 500 }}
      title={review.note ? `${REVIEW_LABEL[review.status]} — ${review.note}` : REVIEW_LABEL[review.status]}
    >
      {REVIEW_LABEL[review.status]}
    </span>
  )
}

/** The analyst's decision on a finding; persists per brand + key across scans. */
export function ReviewPanel({
  finding,
  brandId,
  onChanged,
}: {
  finding: Finding
  brandId: string
  onChanged?: (review: Review | null) => void
}) {
  const [review, setReview] = useState<Review | null>(finding.review)
  const [note, setNote] = useState(finding.review?.note ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setReview(finding.review)
    setNote(finding.review?.note ?? '')
    setError(null)
  }, [finding.id, finding.review])

  async function save(status: ReviewStatus) {
    setBusy(true)
    setError(null)
    try {
      const r = await api.setReview(brandId, finding.key, { status, note })
      setReview(r)
      onChanged?.(r)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'could not save')
    } finally {
      setBusy(false)
    }
  }

  async function clear() {
    setBusy(true)
    setError(null)
    try {
      await api.clearReview(brandId, finding.key)
      setReview(null)
      setNote('')
      onChanged?.(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'could not clear')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <div className="label mb-2">Analyst decision</div>
      <div className="flex flex-wrap gap-2 mb-2">
        {ORDER.map((s) => {
          const active = review?.status === s
          return (
            <button
              key={s}
              type="button"
              className="btn btn-sm"
              disabled={busy}
              onClick={() => void save(s)}
              title={REVIEW_HINT[s]}
              style={active ? { borderColor: reviewTone(s), color: reviewTone(s), fontWeight: 600 } : undefined}
            >
              {active ? '● ' : ''}
              {REVIEW_LABEL[s]}
            </button>
          )
        })}
        {review && (
          <button type="button" className="btn btn-sm" disabled={busy} onClick={() => void clear()} title="Remove the decision">
            Clear
          </button>
        )}
      </div>
      <input
        className="input text-sm"
        placeholder="Note (optional): why, ticket id, who handles it…"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        onBlur={() => {
          if (review && note !== review.note) void save(review.status)
        }}
        disabled={busy}
      />
      <div className="text-xs faint mt-1.5 leading-relaxed">
        {review ? (
          <>
            {REVIEW_HINT[review.status]} Decided {fmtDate(review.updated_at)}. The decision follows this{' '}
            {finding.kind === 'domain' ? 'domain' : 'package'} in every later scan of the brand.
          </>
        ) : (
          'No decision yet. A decision is kept per brand and key, so the same listing is not reviewed twice.'
        )}
        {error && <span style={{ color: 'var(--malicious)' }}> {error}</span>}
      </div>
    </section>
  )
}
