import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, SOURCE_LABEL, SOURCES, type Brand, type Depth, type Finding, type Source } from '../api'
import { usePolling } from '../hooks'
import { Counters } from '../components/Counters'
import { FindingsTable } from '../components/FindingsTable'
import { DetailsDrawer } from '../components/DetailsDrawer'
import { Field, Segmented, StatusPill, fmtDate } from '../ui'

type ListField = 'official_domains' | 'official_publishers' | 'official_package_ids' | 'known_official_apps' | 'known_affiliates'

const LIST_FIELDS: { key: ListField; label: string; hint: string }[] = [
  { key: 'official_domains', label: 'Official domains', hint: 'The trust anchor: publisher verification and domain comparison are made against these.' },
  { key: 'official_publishers', label: 'Official publishers', hint: 'A name alone is not enough; together with a verifier it fires the official veto.' },
  { key: 'official_package_ids', label: 'Official package ids', hint: 'Unique on Play; repackaging detection and the same-account rule rest on these. They are also fetched directly in every Play scan.' },
  { key: 'known_official_apps', label: 'Known official apps', hint: 'For reference.' },
  { key: 'known_affiliates', label: 'Known affiliates', hint: 'Legitimate related domains (ziraatbank.de, say); removed from the detection list.' },
]

function toLines(v: string[]) {
  return v.join('\n')
}
function fromLines(s: string) {
  return s.split('\n').map((x) => x.trim()).filter(Boolean)
}

export default function BrandPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const { data: brand, reload } = usePolling(() => api.getBrand(id), 10000, false, [id])
  const { data: scans } = usePolling(() => api.listScans({ brand_id: id, limit: 20 }), 5000, true, [id])
  const { data: latest, reload: reloadLatest } = usePolling(() => api.brandFindings(id, { limit: 500 }), 10000, false, [id])
  const [draft, setDraft] = useState<Record<ListField, string> | null>(null)
  const [sector, setSector] = useState('')
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)
  const [selected, setSelected] = useState<Finding | null>(null)

  useEffect(() => {
    if (!brand) return
    setDraft(Object.fromEntries(LIST_FIELDS.map((f) => [f.key, toLines(brand[f.key])])) as Record<ListField, string>)
    setSector(brand.sector)
    setNotes(brand.review_notes.join('\n'))
  }, [brand])

  useEffect(() => {
    if (scans?.some((s) => s.status === 'done' || s.status === 'partial')) void reloadLatest()
  }, [scans?.map((s) => s.status).join()]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!brand || !draft) return <div className="faint">Loading…</div>

  async function save(markReviewed: boolean) {
    if (!draft) return
    setSaving(true)
    try {
      const body: Partial<Brand> = { sector }
      for (const f of LIST_FIELDS) body[f.key] = fromLines(draft[f.key])
      body.review_notes = markReviewed ? [] : fromLines(notes)
      body.needs_review = markReviewed ? false : fromLines(notes).length > 0
      await api.updateBrand(id, body)
      await reload()
    } finally {
      setSaving(false)
    }
  }

  async function scanNow() {
    const scan = await api.createScan({ input: brand!.brand_name, sources: ['play', 'serper'] })
    navigate(`/scans/${scan.id}`)
  }

  const counts = latest
    ? latest.items.reduce<Record<string, number>>((acc, f) => ({ ...acc, [f.category]: (acc[f.category] ?? 0) + 1, total: (acc.total ?? 0) + 1 }), {})
    : {}
  const resolution = brand.resolution as { how?: string; evidence?: string[]; discovery?: { evidence?: string[]; method?: string }; enrichment?: { evidence?: string[] } }
  const evidence = [
    ...(resolution.evidence ?? []),
    ...(resolution.discovery?.evidence ?? []),
    ...(resolution.enrichment?.evidence ?? []),
  ]

  return (
    <div className="layout-brand">
      <section className="flex flex-col gap-4">
        <div>
          <div className="text-xs faint mb-1"><Link to="/brands">Brands</Link> / {brand.id}</div>
          <h1 className="text-xl font-semibold tracking-tight">{brand.brand_name}</h1>
          <div className="text-sm muted mt-1 flex items-center gap-2">
            {brand.needs_review ? (
              <span className="badge badge-suspicious"><span className="dot" />needs review</span>
            ) : (
              <span className="badge badge-official"><span className="dot" />ready</span>
            )}
            <span>{brand.scan_count} scan{brand.scan_count === 1 ? '' : 's'}</span>
          </div>
        </div>

        <div className="card p-4 flex flex-col gap-4">
          <Field label="Sector" hint="Permission expectations depend on it (banking, logistics, crypto, fintech…)">
            <input className="input" value={sector} onChange={(e) => setSector(e.target.value)} />
          </Field>
          {LIST_FIELDS.map((f) => (
            <Field key={f.key} label={f.label} hint={f.hint}>
              <textarea
                className="input mono"
                rows={Math.min(6, Math.max(2, draft[f.key].split('\n').length))}
                value={draft[f.key]}
                onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
                placeholder="one value per line"
              />
            </Field>
          ))}
          <Field label="Review notes" hint="What automatic resolution was unsure about. Clear them once verified.">
            <textarea className="input" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </Field>
          <div className="flex items-center gap-2">
            <button type="button" className="btn btn-primary" disabled={saving} onClick={() => void save(false)}>
              Save
            </button>
            {brand.needs_review && (
              <button type="button" className="btn" disabled={saving} onClick={() => void save(true)}>
                Save as reviewed
              </button>
            )}
            <button type="button" className="btn ml-auto" onClick={() => void scanNow()}>
              Scan now
            </button>
          </div>
        </div>

        <SchedulePanel brand={brand} onSaved={() => void reload()} />

        {evidence.length > 0 && (
          <div className="card p-4">
            <div className="label mb-2">How the profile was built</div>
            <ul className="text-xs muted flex flex-col gap-1 list-disc pl-4">
              {evidence.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section className="flex flex-col gap-4 min-w-0">
        <div className="card">
          <div className="px-4 py-3 font-medium" style={{ borderBottom: '1px solid var(--border)' }}>Scan history</div>
          {!scans?.length ? (
            <div className="px-4 py-6 text-sm faint">This brand has not been scanned yet.</div>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Sources</th>
                  <th>Status</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {scans.map((s) => (
                  <tr key={s.id} className="row" onClick={() => navigate(`/scans/${s.id}`)}>
                    <td className="text-sm">{fmtDate(s.created_at)}</td>
                    <td className="text-sm muted">{s.sources.map((x) => SOURCE_LABEL[x]).join(', ')}</td>
                    <td><StatusPill status={s.status} /></td>
                    <td><Counters counts={s.counts} compact /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card">
          <div className="px-4 py-3 flex items-center justify-between" style={{ borderBottom: '1px solid var(--border)' }}>
            <span className="font-medium">Latest findings</span>
            <Counters counts={counts} compact />
          </div>
          <div className="overflow-auto" style={{ maxHeight: 520 }}>
            {latest ? (
              <FindingsTable
                items={latest.items.filter((f) => f.category !== 'noise')}
                selectedId={selected?.id ?? null}
                onSelect={setSelected}
                brand={brand}
                onBrandUpdated={() => void reload()}
              />
            ) : (
              <div className="p-6 faint">Loading…</div>
            )}
          </div>
          <div className="px-4 py-2 text-xs faint" style={{ borderTop: '1px solid var(--border)' }}>
            The latest decision per key across all scans. Noise hidden.
          </div>
        </div>
      </section>
      <DetailsDrawer finding={selected} onClose={() => setSelected(null)} brand={brand} onBrandUpdated={() => void reload()} />
    </div>
  )
}


/** Automatic re-scans: off / daily / weekly, with the sources and depth to use. */
function SchedulePanel({ brand, onSaved }: { brand: Brand; onSaved: () => void }) {
  const [schedule, setSchedule] = useState<Brand['schedule']>(brand.schedule)
  const [sources, setSources] = useState<Source[]>(brand.schedule_sources.length ? brand.schedule_sources : ['play', 'serper'])
  const [depth, setDepth] = useState<Depth>(brand.schedule_depth || 'normal')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setSchedule(brand.schedule)
    setSources(brand.schedule_sources.length ? brand.schedule_sources : ['play', 'serper'])
    setDepth(brand.schedule_depth || 'normal')
  }, [brand.id, brand.schedule, brand.schedule_depth, brand.schedule_sources])

  const dirty =
    schedule !== brand.schedule ||
    depth !== brand.schedule_depth ||
    sources.join() !== (brand.schedule_sources.length ? brand.schedule_sources : ['play', 'serper']).join()

  async function save() {
    setBusy(true)
    setError(null)
    try {
      await api.updateBrand(brand.id, { schedule, schedule_sources: sources, schedule_depth: depth })
      onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'could not save')
    } finally {
      setBusy(false)
    }
  }

  const toggle = (s: Source) => setSources(sources.includes(s) ? sources.filter((x) => x !== s) : [...sources, s])

  return (
    <div className="card p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="label">Scheduled re-scan</div>
        {brand.schedule !== 'off' && brand.next_run_at && (
          <span className="text-xs muted">next run {fmtDate(brand.next_run_at)}</span>
        )}
      </div>
      <Segmented
        value={schedule}
        onChange={(v) => setSchedule(v as 'off' | 'daily' | 'weekly')}
        options={[
          { value: 'off', label: 'Off' },
          { value: 'daily', label: 'Daily', hint: 'Re-scan every 24 hours while the server is running' },
          { value: 'weekly', label: 'Weekly', hint: 'Re-scan every 7 days while the server is running' },
        ]}
      />
      {schedule !== 'off' && (
        <div className="flex flex-col gap-2 text-sm">
          <div className="flex flex-wrap gap-3">
            {SOURCES.map((s) => (
              <label key={s} className="inline-flex items-center gap-1.5">
                <input type="checkbox" checked={sources.includes(s)} onChange={() => toggle(s)} />
                {SOURCE_LABEL[s]}
              </label>
            ))}
          </div>
          <label className="inline-flex items-center gap-2">
            <span className="muted">Depth</span>
            <select className="input" style={{ width: 120, padding: '4px 8px' }} value={depth} onChange={(e) => setDepth(e.target.value as Depth)}>
              <option value="quick">quick</option>
              <option value="normal">normal</option>
              <option value="deep">deep</option>
            </select>
          </label>
        </div>
      )}
      <div className="flex items-center gap-3">
        <button type="button" className="btn btn-sm btn-primary" disabled={busy || !dirty || (schedule !== 'off' && sources.length === 0)} onClick={() => void save()}>
          Save schedule
        </button>
        <span className="text-xs faint">
          {schedule === 'off'
            ? 'No automatic scans. "Scan now" still works.'
            : `Runs ${schedule} while the server is up; each run is a normal scan with a "since the previous scan" comparison.`}
          {error && <span style={{ color: 'var(--malicious)' }}> {error}</span>}
        </span>
      </div>
    </div>
  )
}
