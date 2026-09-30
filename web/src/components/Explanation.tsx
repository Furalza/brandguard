import { useState } from 'react'
import { api, type Brand, type Evidence, type Finding } from '../api'
import { decisionSteps, GROUP_TITLE, groupOf, plainEvidence, summary, type Group } from '../explain'
import { ReviewPanel } from './ReviewPanel'

const GROUP_ORDER: Group[] = ['decisive', 'plus', 'minus', 'reader', 'info']

function glyph(g: Group): { glyph: string; color: string } {
  if (g === 'decisive') return { glyph: '■', color: 'var(--accent)' }
  if (g === 'plus') return { glyph: '▲', color: 'var(--malicious)' }
  if (g === 'minus') return { glyph: '▼', color: 'var(--official)' }
  if (g === 'reader') return { glyph: '❝', color: 'var(--affiliate)' }
  return { glyph: '•', color: 'var(--text-3)' }
}

function weightText(e: Evidence): string {
  if (Math.abs(e.weight) < 0.05) return ''
  return (e.weight > 0 ? '+' : '−') + Math.abs(e.weight).toFixed(2)
}

function EvidenceGroup({ group, items, showRaw }: { group: Group; items: Evidence[]; showRaw: boolean }) {
  if (!items.length) return null
  const g = glyph(group)
  return (
    <div>
      <div className="text-xs font-semibold mb-1.5 flex items-center gap-2" style={{ color: g.color }}>
        <span>{g.glyph}</span>
        {GROUP_TITLE[group]}
        <span className="faint font-normal tnum">{items.length}</span>
      </div>
      <ul className="flex flex-col gap-1.5 pl-5">
        {items.map((e, i) => (
          <li key={i} className="text-sm leading-snug">
            <div className="flex gap-2">
              <span className="flex-1">{plainEvidence(e)}</span>
              {weightText(e) && (
                <span className="tnum text-xs shrink-0" style={{ color: g.color }}>
                  {weightText(e)}
                </span>
              )}
            </div>
            {showRaw && (
              <div className="text-xs faint mt-0.5 break-words">
                {e.text}
                {e.signal && <span className="mono ml-1">· {e.signal}{e.tier ? ` · T${e.tier}` : ''}</span>}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

export function Fact({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  if (value === null || value === undefined || value === '') return null
  return (
    <div className="min-w-0">
      <div className="label">{label}</div>
      <div className={`mt-0.5 break-words ${mono ? 'mono text-xs' : ''}`}>{value}</div>
    </div>
  )
}

/** For a possible affiliate: one click records the package id (and publisher)
 *  on the brand profile, so the next scan verifies it as official. */
export function AddToProfile({ finding, brand, onUpdated }: { finding: Finding; brand: Brand; onUpdated?: (b: Brand) => void }) {
  const [state, setState] = useState<'idle' | 'busy' | 'done' | 'error'>(
    brand.official_package_ids.includes(finding.key) ? 'done' : 'idle',
  )
  const publisher = typeof finding.extra.publisher === 'string' ? finding.extra.publisher : ''
  async function add() {
    setState('busy')
    try {
      const ids = brand.official_package_ids.includes(finding.key) ? brand.official_package_ids : [...brand.official_package_ids, finding.key]
      const pubs = publisher && !brand.official_publishers.includes(publisher) ? [...brand.official_publishers, publisher] : brand.official_publishers
      const updated = await api.updateBrand(brand.id, { official_package_ids: ids, official_publishers: pubs })
      onUpdated?.(updated)
      setState('done')
    } catch {
      setState('error')
    }
  }
  if (state === 'done')
    return <span className="text-xs" style={{ color: 'var(--official)' }}>Added to the profile; the next scan verifies it as official.</span>
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <button type="button" className="btn btn-sm" disabled={state === 'busy'} onClick={() => void add()}>
        This is the brand's app: add to profile
      </button>
      <span className="text-xs faint">
        Writes the package id{publisher ? ' and publisher name' : ''} to the official lists.
        {state === 'error' && <span style={{ color: 'var(--malicious)' }}> Could not save.</span>}
      </span>
    </div>
  )
}

/** The full "why" of a finding: summary, facts, grouped evidence, decision path.
 *  Shared by the details drawer and the inline row expansion in the table. */
export function Explanation({
  finding: f,
  brand,
  onBrandUpdated,
  onReviewChanged,
  compact = false,
}: {
  finding: Finding
  brand?: Brand | null
  onBrandUpdated?: (b: Brand) => void
  onReviewChanged?: () => void
  compact?: boolean
}) {
  const [showRaw, setShowRaw] = useState(false)
  const raw = f.extra
  const grouped: Record<Group, Evidence[]> = { decisive: [], plus: [], minus: [], reader: [], info: [] }
  const excerpt = typeof raw.description_excerpt === 'string' && raw.description_excerpt ? raw.description_excerpt : null
  for (const e of f.evidence) grouped[groupOf(e)].push(e)
  const plus = grouped.plus.length
  const minus = grouped.minus.length
  const installs = typeof raw.installs === 'number' ? raw.installs.toLocaleString('en-US') : null
  const website = typeof raw.website === 'string' && raw.website ? raw.website : null
  const gap = compact ? 'gap-4' : 'gap-6'

  return (
    <div className={`flex flex-col ${gap}`}>
      <section>
        <div className="label mb-2">In short</div>
        <p className="text-sm leading-relaxed">{summary(f)}</p>
      </section>

      {f.kind === 'app' && (raw.publisher || website || installs) && (
        <section className={`text-sm ${compact ? 'grid-4' : 'grid-2'}`}>
          <Fact label="Publisher" value={typeof raw.publisher === 'string' && raw.publisher ? raw.publisher : null} />
          <Fact label="Installs" value={installs ? `${installs}+` : null} />
          <Fact
            label="Developer site"
            value={website ? <a href={website} target="_blank" rel="noreferrer noopener">{website.replace(/^https?:\/\//, '')}</a> : null}
            mono
          />
          <Fact label="Released / updated" value={raw.released || raw.updated ? `${String(raw.released ?? '—')} / ${String(raw.updated ?? '—')}` : null} mono />
        </section>
      )}

      <section>
        <div className="flex items-center justify-between mb-2">
          <div className="label">
            Why this decision?
            {f.kind === 'app' && f.evidence.length > 0 && (
              <span className="ml-2 normal-case tracking-normal tnum">
                <span style={{ color: 'var(--malicious)' }}>{plus} for</span> · <span style={{ color: 'var(--official)' }}>{minus} against</span>
              </span>
            )}
          </div>
          <button type="button" className="text-xs faint" onClick={() => setShowRaw((v) => !v)}>
            {showRaw ? 'Hide engine text' : 'Show engine text'}
          </button>
        </div>
        {f.evidence.length === 0 ? (
          <div className="text-sm faint">No evidence lines.</div>
        ) : (
          <div className="flex flex-col gap-4">
            {GROUP_ORDER.map((g) => (
              <EvidenceGroup key={g} group={g} items={grouped[g]} showRaw={showRaw} />
            ))}
          </div>
        )}
      </section>

      {excerpt && (
        <section>
          <details>
            <summary className="label cursor-pointer" style={{ listStyle: 'none' }}>
              <span className="faint">▸</span> Listing text (as published, untrusted)
            </summary>
            <p
              className="text-sm mt-2 px-3 py-2 rounded-md leading-relaxed"
              style={{ background: 'var(--surface-2)', border: '1px dashed var(--border-strong)', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}
            >
              {excerpt}
            </p>
          </details>
        </section>
      )}

      <section>
        <div className="label mb-2">Decision path</div>
        <ol className="flex flex-col gap-1 text-sm">
          {decisionSteps(f).map((s, i) => (
            <li key={i} className="flex gap-2">
              <span className="faint tnum w-4 shrink-0">{i + 1}.</span>
              <span>{s}</span>
            </li>
          ))}
        </ol>
        {f.category === 'suspicious' && f.kind === 'app' && (
          <p className="text-xs muted mt-2 leading-relaxed">
            Rule: without evidence outside the attacker's control (account age, drift from the official permission
            list) the system never calls an app an impersonation; a wrong takedown request costs more than a missed one.
          </p>
        )}
        {f.category === 'affiliate' && (
          <div className="mt-3 flex flex-col gap-2">
            <p className="text-xs muted leading-relaxed">
              If this is the brand's own app, add its package id to the brand profile; the next scan verifies it as
              official. Otherwise leave it as related.
            </p>
            {brand && f.kind === 'app' && <AddToProfile finding={f} brand={brand} onUpdated={onBrandUpdated} />}
          </div>
        )}
      </section>

      {brand && <ReviewPanel finding={f} brandId={brand.id} onChanged={() => onReviewChanged?.()} />}
    </div>
  )
}
