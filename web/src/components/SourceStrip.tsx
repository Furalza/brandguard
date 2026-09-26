import { SOURCE_LABEL, type Source, type SourceRun } from '../api'
import { fmtDuration } from '../ui'

const STATUS: Record<string, { text: string; color: string }> = {
  queued: { text: 'queued', color: 'var(--text-3)' },
  running: { text: 'running', color: 'var(--running)' },
  done: { text: 'done', color: 'var(--official)' },
  failed: { text: 'failed', color: 'var(--malicious)' },
  cancelled: { text: 'cancelled', color: 'var(--text-3)' },
}

export function SourceStrip({ runs, onRetry }: { runs: SourceRun[]; onRetry?: (s: Source) => void }) {
  return (
    <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${Math.max(runs.length, 1)}, minmax(0, 1fr))` }}>
      {runs.map((r) => {
        const st = STATUS[r.status] ?? STATUS.queued
        const issues = r.warnings.length + r.errors.length
        return (
          <div key={r.source} className="card p-3 flex flex-col gap-1.5" style={{ borderLeft: `3px solid ${st.color}` }}>
            <div className="flex items-center justify-between">
              <span className="font-medium">{SOURCE_LABEL[r.source]}</span>
              <span className={`text-xs ${r.status === 'running' ? 'pulse' : ''}`} style={{ color: st.color }}>
                {st.text}
              </span>
            </div>
            {r.status === 'done' && (
              <div className="text-xs muted tnum">
                {r.candidates} candidates · {r.detected} threats{r.watch ? ` · ${r.watch} to watch` : ''} · {fmtDuration(r.duration_ms)}
              </div>
            )}
            {r.status === 'running' && <div className="text-xs faint">Querying the source…</div>}
            {r.status === 'queued' && <div className="text-xs faint">Waiting in queue</div>}
            {r.status === 'cancelled' && <div className="text-xs faint">Cancelled before it ran</div>}
            {r.status === 'failed' && (
              <div className="text-xs" style={{ color: 'var(--malicious)' }}>
                {r.error ?? 'unknown error'}
                {onRetry && (
                  <button type="button" className="ml-2 underline" onClick={() => onRetry(r.source)}>
                    retry
                  </button>
                )}
              </div>
            )}
            {issues > 0 && r.status === 'done' && (
              <details className="text-xs">
                <summary className="cursor-pointer" style={{ color: 'var(--suspicious)' }}>
                  {issues} {issues === 1 ? 'note' : 'notes'}
                </summary>
                <ul className="mt-1 pl-4 list-disc muted">
                  {[...r.warnings, ...r.errors].map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )
      })}
    </div>
  )
}
