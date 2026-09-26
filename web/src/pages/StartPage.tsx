import { useMemo, useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, SOURCE_HINT, SOURCE_LABEL, SOURCES, type Depth, type Source } from '../api'
import { useLocalState, usePolling } from '../hooks'
import { Segmented, StatusPill, relTime } from '../ui'
import { Counters } from '../components/Counters'

const DEPTH_TEXT: Record<Depth, { title: string; body: string }> = {
  quick: { title: 'Quick', body: 'Few queries, first page only. A preview within minutes.' },
  normal: { title: 'Normal', body: 'Every APK query, more Play name variants. The daily scan.' },
  deep: { title: 'Deep', body: 'Two Google pages, 14 Play variants, 15 web queries. For priority brands.' },
}

/** Deterministic, client-side guess of what the operator typed; the server decides. */
export function guessKind(text: string): 'brand' | 'domain' | 'package' | 'url' | '' {
  const t = text.trim()
  if (!t) return ''
  if (/^(https?:\/\/|www\.)/i.test(t)) return /details\?id=|\/[a-z][a-z0-9_]*(\.[a-z0-9_]+){2,}/i.test(t) ? 'url' : 'domain'
  if (/\s/.test(t)) return 'brand'
  if (/^(com|net|org|tr|io|app|de|co)\.[a-z0-9_.]+$/i.test(t) && !/\.(com|net|org|tr|io|app|de|co)$/i.test(t)) return 'package'
  if (/^[a-z0-9-]+(\.[a-z0-9-]+)+$/i.test(t)) return 'domain'
  return 'brand'
}

type Mode = 'single' | 'multi'

function fieldStatus(value: string, expect: 'domain' | 'store'): string | null {
  const t = value.trim()
  if (!t) return null
  const kind = guessKind(t)
  if (expect === 'domain') return kind === 'domain' ? null : 'This does not look like a domain (example: papara.com)'
  return kind === 'url' || kind === 'package' ? null : 'Paste the Google Play link or the package id (com.example.app)'
}

export default function StartPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  // "Scan again" hands over the previous input. A structured scan's input is
  // its parts joined with " · "; each part goes back into its own field.
  const preset = useMemo(() => {
    const out = { name: params.get('name') ?? '', domain: params.get('domain') ?? '', store: params.get('store') ?? '' }
    for (const part of (params.get('input') ?? '').split(' · ').map((x) => x.trim()).filter(Boolean)) {
      const kind = guessKind(part)
      if (kind === 'domain' && !out.domain) out.domain = part
      else if ((kind === 'url' || kind === 'package') && !out.store) out.store = part
      else if (!out.name) out.name = part
    }
    return out
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const [mode, setMode] = useState<Mode>('single')
  const [name, setName] = useState(preset.name)
  const [domain, setDomain] = useState(preset.domain)
  const [store, setStore] = useState(preset.store)
  const [multiText, setMultiText] = useState('')
  const [sources, setSources] = useLocalState<Source[]>('bg.sources', ['play', 'serper'])
  const [depth, setDepth] = useLocalState<Depth>('bg.depth', 'normal')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const lines = useMemo(() => multiText.split(/\n+/).map((x) => x.trim()).filter(Boolean), [multiText])
  const domainProblem = fieldStatus(domain, 'domain')
  const storeProblem = fieldStatus(store, 'store')
  const filled = [name, domain, store].filter((v) => v.trim()).length
  const singleReady = filled > 0 && !domainProblem && !storeProblem
  const ready = sources.length > 0 && (mode === 'single' ? singleReady : lines.length > 0)

  const { data: recent } = usePolling(() => api.listScans({ limit: 8 }), 5000, true)
  const { data: health } = usePolling(() => api.health(), 30000, false)
  const serperOff = !!health && !health.serper_configured

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!ready) return
    setBusy(true)
    setError(null)
    try {
      if (mode === 'multi') {
        const batch = await api.createBatch({ inputs: lines, sources, depth })
        navigate(`/batches/${batch.id}`, { state: { errors: batch.errors } })
      } else {
        const scan = await api.createScan({
          brand_name: name.trim() || undefined,
          domain: domain.trim() || undefined,
          store: store.trim() || undefined,
          sources,
          depth,
        })
        navigate(`/scans/${scan.id}`)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setBusy(false)
    }
  }

  const toggle = (s: Source) => setSources(sources.includes(s) ? sources.filter((x) => x !== s) : [...sources, s])

  return (
    <div className="grid gap-8" style={{ gridTemplateColumns: 'minmax(0, 1fr) 360px' }}>
      <section>
        <div className="mb-4">
          <h1 className="text-xl font-semibold tracking-tight mb-1">New scan</h1>
          <p className="muted">
            BrandGuard resolves the brand's identity, searches Google Play and third-party APK sites, and puts every
            finding in a category with its reasons.
          </p>
        </div>

        <form onSubmit={submit} className="card p-5 flex flex-col gap-5">
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <Segmented
              value={mode}
              onChange={(v) => setMode(v as Mode)}
              options={[
                { value: 'single', label: 'One brand', hint: 'Scan a single brand with name, domain and Play link' },
                { value: 'multi', label: 'Several brands', hint: 'Paste a list; every line becomes its own scan' },
              ]}
            />
            <span className="text-xs faint">
              {mode === 'single' ? 'Fill any of the three fields; all three give the most exact result.' : 'One brand per line; results are followed together on one page.'}
            </span>
          </div>

          {mode === 'single' ? (
            <div>
              <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' }}>
                <label className="flex flex-col gap-1">
                  <span className="label">Brand name</span>
                  <input autoFocus className="input" placeholder="Pegasus" value={name} onChange={(e) => setName(e.target.value)} disabled={busy} />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="label">
                    Official domain <span className="normal-case tracking-normal faint">· trust anchor</span>
                  </span>
                  <input
                    className="input mono"
                    placeholder="flypgs.com"
                    value={domain}
                    onChange={(e) => setDomain(e.target.value)}
                    disabled={busy}
                    style={domainProblem ? { borderColor: 'var(--malicious)' } : undefined}
                  />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="label">
                    Google Play link <span className="normal-case tracking-normal faint">· or package id</span>
                  </span>
                  <input
                    className="input mono"
                    placeholder="https://play.google.com/store/apps/details?id=…"
                    value={store}
                    onChange={(e) => setStore(e.target.value)}
                    disabled={busy}
                    style={storeProblem ? { borderColor: 'var(--malicious)' } : undefined}
                  />
                </label>
              </div>
              <div className="mt-2 text-xs faint leading-relaxed" style={{ minHeight: 18 }}>
                {domainProblem ?? storeProblem ?? (
                  filled === 0
                    ? 'Fill at least one. The domain identifies the brand with certainty; the Play link marks its own app; the name alone is resolved from two independent sources.'
                    : filled === 3
                      ? 'All three given: the profile is built exactly as you typed it, nothing is guessed.'
                      : 'More fields, less guessing: with the domain the brand is certain; with the Play link its app is marked official.'
                )}
              </div>
            </div>
          ) : (
            <div>
              <textarea
                autoFocus
                className="input mono text-sm"
                style={{ minHeight: 160, resize: 'vertical' }}
                placeholder={'One brand per line. A line can be a name, a domain, a Play link or a package id — or all three separated by |:\nPapara\nziraatbank.com.tr\nhttps://play.google.com/store/apps/details?id=com.getir\nPegasus | flypgs.com | com.pozitron.pegasus'}
                value={multiText}
                onChange={(e) => setMultiText(e.target.value)}
                disabled={busy}
              />
              <div className="mt-2 text-xs faint" style={{ minHeight: 18 }}>
                {lines.length === 0
                  ? 'Each line becomes its own scan; they run in parallel and are followed together on one page.'
                  : `${lines.length} brand${lines.length === 1 ? '' : 's'} · each becomes its own scan, followed together on one page.`}
              </div>
            </div>
          )}

          <div>
            <div className="label mb-2">Sources</div>
            <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(4, minmax(0, 1fr))' }}>
              {SOURCES.map((s) => {
                const on = sources.includes(s)
                const disabled = serperOff && (s === 'serper' || s === 'website')
                return (
                  <label
                    key={s}
                    className={`option ${on ? 'active' : ''} ${disabled ? 'disabled' : ''}`}
                    title={disabled ? 'SERPER_API_KEY is not set' : SOURCE_HINT[s]}
                  >
                    <input type="checkbox" className="mt-1" checked={on} onChange={() => toggle(s)} disabled={disabled} />
                    <span className="flex flex-col gap-0.5 min-w-0">
                      <span className="font-medium">{SOURCE_LABEL[s]}</span>
                      <span className="text-xs muted leading-snug">{SOURCE_HINT[s]}</span>
                    </span>
                  </label>
                )
              })}
            </div>
          </div>

          <div>
            <div className="label mb-2">Depth</div>
            <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' }}>
              {(Object.keys(DEPTH_TEXT) as Depth[]).map((d) => (
                <label key={d} className={`option ${depth === d ? 'active' : ''}`}>
                  <input type="radio" className="mt-1" name="depth" checked={depth === d} onChange={() => setDepth(d)} />
                  <span className="flex flex-col gap-0.5 min-w-0">
                    <span className="font-medium">{DEPTH_TEXT[d].title}</span>
                    <span className="text-xs muted leading-snug">{DEPTH_TEXT[d].body}</span>
                  </span>
                </label>
              ))}
            </div>
          </div>

          {error && (
            <div className="text-sm px-3 py-2 rounded-md" style={{ background: 'var(--malicious-bg)', color: 'var(--malicious)', border: '1px solid var(--malicious-border)' }}>
              {error}
            </div>
          )}
          {serperOff && (
            <div className="text-xs muted">
              No Serper key configured; the APK sites and websites sources are off. Add <code>SERPER_API_KEY</code> to <code>.env</code>.
            </div>
          )}

          <div className="flex items-center justify-between gap-3 pt-1" style={{ borderTop: '1px solid var(--border)' }}>
            <span className="text-xs faint">
              {mode === 'single' ? 'A saved profile is reused; typed facts are merged into it.' : 'Lines that cannot be resolved are reported; the rest still run.'}
            </span>
            <button
              className="btn btn-primary"
              style={{ padding: '10px 22px', fontWeight: 600 }}
              disabled={busy || !ready}
              title={!ready ? (sources.length === 0 ? 'Pick at least one source' : 'Fill in the brand first') : undefined}
            >
              {busy
                ? 'Starting…'
                : mode === 'multi'
                  ? `Scan ${lines.length || ''} brand${lines.length === 1 ? '' : 's'} →`
                  : 'Start scan →'}
            </button>
          </div>
        </form>
      </section>

      <aside className="flex flex-col gap-4">
        <div className="card">
          <div className="px-4 py-3 flex items-center justify-between" style={{ borderBottom: '1px solid var(--border)' }}>
            <span className="font-medium">Recent scans</span>
            <Link to="/scans" className="text-xs">all</Link>
          </div>
          {!recent?.length ? (
            <div className="px-4 py-8 text-sm faint text-center">No scans yet.</div>
          ) : (
            <ul>
              {recent.map((s) => (
                <li key={s.id} style={{ borderBottom: '1px solid var(--border)' }}>
                  <Link to={`/scans/${s.id}`} className="block px-4 py-3 hover:bg-[var(--surface-2)] no-underline" style={{ color: 'inherit' }}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium truncate">{s.brand_name}</span>
                      <StatusPill status={s.status} />
                    </div>
                    <div className="flex items-center justify-between mt-1 text-xs faint">
                      <span className="truncate">{s.input_raw} · {s.sources.map((x) => SOURCE_LABEL[x]).join(', ')}</span>
                      <span>{relTime(s.created_at)}</span>
                    </div>
                    <div className="mt-2">
                      <Counters counts={s.counts} compact />
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="card p-4 text-xs muted leading-relaxed">
          <div className="label mb-1">How to read the results</div>
          <span style={{ color: 'var(--malicious)' }}>Malicious</span> is a takedown candidate;{' '}
          <span style={{ color: 'var(--suspicious)' }}>Suspicious</span> needs a person;{' '}
          <span style={{ color: 'var(--affiliate)' }}>Affiliate?</span> is probably the brand's own regional app — confirm and add it to the profile.
          Every row opens with the reasons, and your decisions are remembered in later scans.
        </div>
      </aside>
    </div>
  )
}
