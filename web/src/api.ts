// Typed client for the BrandGuard API. Shapes mirror brandguard/api/schemas.py.

export type Category = 'malicious' | 'suspicious' | 'official' | 'affiliate' | 'related' | 'noise'
export type ScanStatus = 'queued' | 'running' | 'done' | 'partial' | 'failed' | 'cancelled'
export type SourceStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled'
export type Depth = 'quick' | 'normal' | 'deep'

export const SOURCES = ['play', 'serper', 'website', 'crtsh'] as const
export type Source = (typeof SOURCES)[number]

export const SOURCE_LABEL: Record<Source, string> = {
  play: 'Google Play',
  serper: 'APK sites',
  website: 'Websites',
  crtsh: 'Certificate logs',
}
export const SOURCE_HINT: Record<Source, string> = {
  play: 'Play search over name variants, with listing details',
  serper: 'Google dorks across third-party APK sites',
  website: 'Lookalike domains: generated variants and search',
  crtsh: 'Domains naming the brand in Certificate Transparency logs',
}

export interface SourceRun {
  source: Source
  status: SourceStatus
  error: string | null
  errors: string[]
  warnings: string[]
  candidates: number
  detected: number
  watch: number
  requests: number
  duration_ms: number
  started_at: string | null
  finished_at: string | null
}

export interface Brand {
  id: string
  brand_name: string
  sector: string
  official_domains: string[]
  official_publishers: string[]
  official_package_ids: string[]
  known_official_apps: string[]
  known_affiliates: string[]
  resolved_from: string
  needs_review: boolean
  review_notes: string[]
  resolution: Record<string, unknown>
  last_scan_at: string | null
  scan_count: number
  schedule: 'off' | 'daily' | 'weekly'
  schedule_sources: Source[]
  schedule_depth: Depth
  next_run_at: string | null
}

export interface Counts {
  total?: number
  malicious?: number
  suspicious?: number
  official?: number
  affiliate?: number
  related?: number
  noise?: number
  needs_action?: number
}

export interface Scan {
  id: string
  brand: Brand
  input_raw: string
  input_type: string
  resolved_how: string
  sources: Source[]
  depth: Depth
  tuning: Record<string, unknown>
  status: ScanStatus
  error: string | null
  counts: Counts
  created_at: string
  started_at: string | null
  finished_at: string | null
  source_runs: SourceRun[]
}

export interface ScanListItem {
  id: string
  brand_id: string
  brand_name: string
  input_raw: string
  input_type: string
  sources: Source[]
  depth: Depth
  status: ScanStatus
  counts: Counts
  created_at: string
  finished_at: string | null
  batch_id?: string | null
  trigger?: 'manual' | 'schedule'
}

export interface ScanPage {
  items: ScanListItem[]
  total: number
  limit: number
  offset: number
}

export interface Batch {
  id: string
  created_at: string
  status: 'running' | 'done'
  scans: ScanListItem[]
  errors: { input: string; error: string }[]
  totals: Counts
}

export interface Evidence {
  signal: string
  text: string
  weight: number
  tier: number
}

export interface Finding {
  id: string
  scan_id: string
  kind: 'app' | 'domain'
  key: string
  name: string
  source: string
  label: string
  category: Category
  confidence: number | null
  score: number | null
  similarity: number | null
  tiers_used: number[]
  reason: string
  priority: string | null
  confirmed_live: boolean | null
  evidence: Evidence[]
  extra: Record<string, unknown>
  first_seen_at: string
  created_at: string
  seen_before: boolean
  link: string | null
  review: Review | null
  previous_category?: Category | null
}

export type ReviewStatus = 'false_positive' | 'confirmed' | 'takedown_sent' | 'resolved'
export interface Review {
  key: string
  status: ReviewStatus
  note: string
  updated_at: string
}
export const REVIEW_LABEL: Record<ReviewStatus, string> = {
  false_positive: 'False positive',
  confirmed: 'Confirmed threat',
  takedown_sent: 'Takedown sent',
  resolved: 'Resolved',
}
export const REVIEW_HINT: Record<ReviewStatus, string> = {
  false_positive: 'Not a threat to this brand. Leaves the action queue; still shown with this mark in later scans.',
  confirmed: 'A real threat, action still to be taken. Stays in the queue.',
  takedown_sent: 'A takedown request was filed. Leaves the queue; comes back only if the listing changes.',
  resolved: 'The listing is gone or the issue is closed.',
}

export interface Diff {
  brand_id: string
  scan_id: string
  against_id: string | null
  new: Finding[]
  gone: Finding[]
  changed: Finding[]
  unchanged: number
}

export interface FindingPage {
  items: Finding[]
  total: number
  limit: number
  offset: number
}

export interface Health {
  status: string
  adjudicator: string
  adjudicator_model?: string | null
  public_url?: string | null
  serper_configured: boolean
  play_available: boolean
  sources: Source[]
  depths: Depth[]
  inflight: number
  version: string
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as T
}

/** Fetch a file endpoint and hand it to the browser as a download.
 *  Explicit fetch instead of <a download>: over a flaky tunnel the browser
 *  otherwise saves an empty "export.txt" from the error response. Throws on failure. */
export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const res = await fetch(path)
  if (!res.ok) throw new ApiError(res.status, res.statusText)
  const blob = await res.blob()
  const cd = res.headers.get('content-disposition') ?? ''
  const name = /filename="([^"]+)"/.exec(cd)?.[1] ?? fallbackName
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export const api = {
  health: () => request<Health>('/api/health'),
  createScan: (body: {
    input?: string
    brand_name?: string
    domain?: string
    store?: string
    sources?: Source[]
    depth?: Depth
    tuning?: Record<string, unknown>
  }) =>
    request<Scan>('/api/scans', { method: 'POST', body: JSON.stringify(body) }),
  getScan: (id: string) => request<Scan>(`/api/scans/${id}`),
  createBatch: (body: { inputs: string[]; sources?: Source[]; depth?: Depth }) =>
    request<Batch>('/api/scans/batch', { method: 'POST', body: JSON.stringify(body) }),
  getBatch: (id: string) => request<Batch>(`/api/batches/${id}`),
  scanDiff: (id: string) => request<Diff>(`/api/scans/${id}/diff`),
  setReview: (brandId: string, key: string, body: { status: ReviewStatus; note?: string }) =>
    request<Review>(`/api/brands/${brandId}/reviews/${encodeURIComponent(key)}`, { method: 'PUT', body: JSON.stringify(body) }),
  clearReview: async (brandId: string, key: string) => {
    const res = await fetch(`/api/brands/${brandId}/reviews/${encodeURIComponent(key)}`, { method: 'DELETE' })
    if (!res.ok && res.status !== 404) throw new ApiError(res.status, res.statusText)
  },
  cancelScan: (id: string) => request<Scan>(`/api/scans/${id}/cancel`, { method: 'POST' }),
  cancelBatch: (id: string) => request<Batch>(`/api/batches/${id}/cancel`, { method: 'POST' }),
  listScans: (params: { brand_id?: string; limit?: number } = {}) => {
    const q = new URLSearchParams()
    if (params.brand_id) q.set('brand_id', params.brand_id)
    if (params.limit) q.set('limit', String(params.limit))
    return request<ScanListItem[]>(`/api/scans?${q}`)
  },
  searchScans: (params: { q?: string; view?: string; limit?: number; offset?: number } = {}) => {
    const q = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== '' && v !== null) q.set(k, String(v))
    })
    return request<ScanPage>(`/api/scans/search?${q}`)
  },
  deleteScan: async (id: string) => {
    const res = await fetch(`/api/scans/${id}`, { method: 'DELETE' })
    if (!res.ok) {
      let detail = res.statusText
      try {
        const body = await res.json()
        detail = typeof body.detail === 'string' ? body.detail : detail
      } catch {
        /* keep statusText */
      }
      throw new ApiError(res.status, detail)
    }
  },
  retryScan: (id: string, source?: Source) =>
    request<Scan>(`/api/scans/${id}/retry${source ? `?source=${source}` : ''}`, { method: 'POST' }),
  listItems: (scanId: string, params: { category?: string; source?: string; kind?: string; q?: string; new_only?: boolean; open_only?: boolean; limit?: number; offset?: number } = {}) => {
    const q = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== '' && v !== null && v !== false) q.set(k, String(v))
    })
    return request<FindingPage>(`/api/scans/${scanId}/items?${q}`)
  },
  getItem: (id: string) => request<Finding>(`/api/items/${id}`),
  listBrands: () => request<Brand[]>('/api/brands'),
  getBrand: (id: string) => request<Brand>(`/api/brands/${id}`),
  updateBrand: (id: string, body: Partial<Brand> & { official_permissions?: string[] | null; schedule?: string; schedule_sources?: string[]; schedule_depth?: string }) =>
    request<Brand>(`/api/brands/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteBrand: async (id: string) => {
    const res = await fetch(`/api/brands/${id}`, { method: 'DELETE' })
    if (!res.ok) {
      let detail = res.statusText
      try {
        const body = await res.json()
        detail = typeof body.detail === 'string' ? body.detail : detail
      } catch {
        /* keep statusText */
      }
      throw new ApiError(res.status, detail)
    }
  },
  brandFindings: (id: string, params: { category?: string; limit?: number } = {}) => {
    const q = new URLSearchParams()
    if (params.category) q.set('category', params.category)
    if (params.limit) q.set('limit', String(params.limit))
    return request<FindingPage>(`/api/brands/${id}/findings?${q}`)
  },
}

export const CATEGORY_LABEL: Record<Category, string> = {
  malicious: 'Malicious',
  suspicious: 'Suspicious',
  official: 'Official',
  affiliate: 'Affiliate?',
  related: 'Related',
  noise: 'Noise',
}
export const CATEGORY_ORDER: Category[] = ['malicious', 'suspicious', 'official', 'affiliate', 'related', 'noise']

// One line per category for the operator; shown in the drawer and as tab tooltips.
export const CATEGORY_HINT: Record<Category, string> = {
  malicious: 'Takedown candidate: an impersonation or a repackaged build of the brand\'s app.',
  suspicious: 'The engine could not decide; a person should look.',
  official: 'The brand\'s own listing; its identity was verified.',
  affiliate: 'Looks benign and its publisher identity points at the brand: probably the brand\'s own regional or secondary app. Unverified; confirm and add it to the profile.',
  related: 'Mentions the brand with no threat signal (news, comparison, an independent tool).',
  noise: 'Search noise; hidden by default.',
}

export const LABEL_TEXT: Record<string, string> = {
  impersonation: 'Impersonation',
  repackaged: 'Repackaged',
  official: 'Official',
  third_party_legitimate: 'Legitimate third party',
  unrelated: 'Unrelated',
  uncertain: 'Uncertain',
  lookalike: 'Lookalike domain',
  mentions: 'Mentions the brand',
}

export const REASON_TEXT: Record<string, string> = {
  veto: 'A hard rule (veto) decided',
  benign: 'No suspicion; benign',
  scored: 'The signal score crossed the threshold with independent backing',
  conflict: 'Signals conflicted; the listing text was read',
  grey_zone: 'Score in the grey zone; the listing text was read',
  thin_evidence: 'Only one signal; the listing text was read',
  unbacked_high: 'High score but no attacker-independent evidence',
  adjudicated_benign: 'The reading of the listing text closed it as benign',
  final_uncertain: 'Still uncertain after reading the listing; left to an analyst',
  non_listing_article: 'Not an app listing: article or forum page',
  non_listing_spam: 'Not an app listing: SEO spam page',
  non_listing_gov: 'Not an app listing: institutional or government page',
  non_listing_official_site: "Not an app listing: a page on the brand's own domain",
  same_developer_account: 'Same Play developer account as a verified official app',
  ambiguous_brand_word: 'Brand word shared by unrelated products; mod names no brand identity word',
  mirror_unverified: 'Copy of the official app on a mirror site; cannot be verified without a signature',
}
