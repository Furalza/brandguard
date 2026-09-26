import { CATEGORY_HINT, CATEGORY_LABEL, CATEGORY_ORDER, type Category, type Counts } from '../api'

/** The numbers an operator reads first. Compact form for lists. */
export function Counters({
  counts,
  compact = false,
  active,
  onSelect,
}: {
  counts: Counts
  compact?: boolean
  active?: Category | 'all'
  onSelect?: (c: Category | 'all') => void
}) {
  const shown: Category[] = compact ? ['malicious', 'suspicious', 'official'] : CATEGORY_ORDER
  if (compact) {
    return (
      <div className="flex items-center gap-3 text-xs tnum">
        {shown.map((c) => (
          <span key={c} className="inline-flex items-center gap-1" style={{ color: (counts[c] ?? 0) > 0 ? `var(--${c})` : 'var(--text-3)' }}>
            <span className="dot" />
            {counts[c] ?? 0} {CATEGORY_LABEL[c]}
          </span>
        ))}
      </div>
    )
  }
  return (
    <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${shown.length + 1}, minmax(0, 1fr))` }}>
      <button
        type="button"
        onClick={() => onSelect?.('all')}
        className="card p-3 text-left"
        style={{ borderColor: active === 'all' ? 'var(--accent)' : undefined }}
      >
        <div className="label">Total</div>
        <div className="text-2xl font-semibold tnum mt-1">{counts.total ?? 0}</div>
      </button>
      {shown.map((c) => {
        const n = counts[c] ?? 0
        return (
          <button
            key={c}
            type="button"
            onClick={() => onSelect?.(c)}
            className="card p-3 text-left"
            style={{ borderColor: active === c ? `var(--${c})` : undefined }}
            title={CATEGORY_HINT[c]}
          >
            <div className="label flex items-center gap-1.5" lang="en" style={{ color: `var(--${c})` }}>
              <span className="dot" /> {CATEGORY_LABEL[c]}
            </div>
            <div className="text-2xl font-semibold tnum mt-1" style={{ color: n > 0 ? `var(--${c})` : 'var(--text-3)' }}>
              {n}
            </div>
          </button>
        )
      })}
    </div>
  )
}
