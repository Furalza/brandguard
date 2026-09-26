import type { ReactNode } from 'react'
import { CATEGORY_LABEL, type Category } from './api'

export function CategoryBadge({ category, className = '' }: { category: Category; className?: string }) {
  return (
    <span className={`badge badge-${category} ${className}`}>
      <span className="dot" />
      {CATEGORY_LABEL[category]}
    </span>
  )
}

export function Confidence({ value }: { value: number | null }) {
  if (value === null || value === undefined) return <span className="faint">—</span>
  const pct = Math.round(value * 100)
  return (
    <span className="inline-flex items-center gap-2 tnum">
      <span
        aria-hidden
        className="inline-block h-1.5 w-14 rounded-full overflow-hidden"
        style={{ background: 'var(--border)' }}
      >
        <span className="block h-full" style={{ width: `${pct}%`, background: 'var(--text-2)' }} />
      </span>
      <span className="text-xs muted">{pct}%</span>
    </span>
  )
}

export function StatusPill({ status }: { status: string }) {
  const map: Record<string, { text: string; cls: string }> = {
    queued: { text: 'Queued', cls: 'badge-noise' },
    running: { text: 'Running', cls: 'badge-running pulse' },
    done: { text: 'Done', cls: 'badge-official' },
    partial: { text: 'Partial', cls: 'badge-suspicious' },
    failed: { text: 'Failed', cls: 'badge-malicious' },
    cancelled: { text: 'Cancelled', cls: 'badge-noise' },
  }
  const m = map[status] ?? { text: status, cls: 'badge-noise' }
  return (
    <span className={`badge ${m.cls}`}>
      <span className="dot" />
      {m.text}
    </span>
  )
}

export function Segmented({
  value,
  onChange,
  options,
  className = '',
}: {
  value: string
  onChange: (v: string) => void
  options: { value: string; label: string; hint?: string }[]
  className?: string
}) {
  return (
    <div role="tablist" className={`segmented ${className}`}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="tab"
          aria-selected={o.value === value}
          className={`segmented-item ${o.value === value ? 'active' : ''}`}
          onClick={() => onChange(o.value)}
          title={o.hint}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="label">{label}</span>
      <div>{children}</div>
      {hint && <span className="text-xs faint">{hint}</span>}
    </div>
  )
}

export function Empty({ title, body }: { title: ReactNode; body?: string }) {
  return (
    <div className="py-14 text-center">
      <div className="font-medium">{title}</div>
      {body && <div className="muted mt-1 text-sm">{body}</div>}
    </div>
  )
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })
}

export function fmtDuration(ms: number): string {
  if (!ms) return '—'
  if (ms < 1000) return `${ms} ms`
  const s = ms / 1000
  if (s < 90) return `${s.toFixed(1)} s`
  return `${Math.round(s / 60)} min`
}

export function relTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`
  if (diff < 86400) return `${Math.round(diff / 3600)} h ago`
  return `${Math.round(diff / 86400)} d ago`
}
