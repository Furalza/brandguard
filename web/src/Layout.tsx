import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { api } from './api'
import { usePolling } from './hooks'

type Theme = 'system' | 'light' | 'dark'
const THEME_KEY = 'brandguard.theme'

function readTheme(): Theme {
  try {
    const v = localStorage.getItem(THEME_KEY)
    if (v === 'light' || v === 'dark') return v
  } catch {
    /* storage unavailable */
  }
  return 'system'
}

function applyTheme(t: Theme) {
  const root = document.documentElement
  if (t === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', t)
}

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(readTheme)
  useEffect(() => {
    applyTheme(theme)
    try {
      if (theme === 'system') localStorage.removeItem(THEME_KEY)
      else localStorage.setItem(THEME_KEY, theme)
    } catch {
      /* storage unavailable */
    }
  }, [theme])
  const effectiveDark =
    theme === 'dark' || (theme === 'system' && window.matchMedia?.('(prefers-color-scheme: dark)').matches)
  const next: Theme = effectiveDark ? 'light' : 'dark'
  return (
    <button
      type="button"
      className="icon-btn"
      onClick={() => setTheme(next)}
      title={effectiveDark ? 'Switch to light theme' : 'Switch to dark theme'}
      aria-label="Toggle theme"
    >
      {effectiveDark ? (
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </svg>
      ) : (
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
        </svg>
      )}
    </button>
  )
}

function PublicLink({ url }: { url: string }) {
  const [copied, setCopied] = useState(false)
  const short = url.replace(/^https?:\/\//, '')
  async function copy() {
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      window.prompt('Copy the public link:', url)
    }
  }
  return (
    <button
      type="button"
      className="btn btn-sm"
      onClick={() => void copy()}
      title="The console's current public address (Cloudflare quick tunnel). Click to copy. It changes when the tunnel restarts."
      style={{ color: 'var(--official)', borderColor: 'var(--official-border)', background: 'var(--official-bg)' }}
    >
      <span className="dot" />
      <span className="mono" style={{ fontSize: 12 }}>{short}</span>
      <span className="faint">{copied ? 'copied' : 'copy'}</span>
    </button>
  )
}

function HealthChip({ label, ok, text, title, className = '' }: { label: string; ok: boolean; text: string; title: string; className?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs ${className}`}
      style={{ border: '1px solid var(--border)', background: 'var(--surface-2)' }}
      title={title}
    >
      <span className="dot" style={{ color: ok ? 'var(--official)' : 'var(--text-3)' }} />
      <span className="faint">{label}</span>
      <span className="muted">{text}</span>
    </span>
  )
}

export default function Layout() {
  const { data: health } = usePolling(() => api.health(), 15000, true)
  const link = ({ isActive }: { isActive: boolean }) =>
    `px-3 py-1.5 rounded-md text-sm ${isActive ? 'font-semibold' : 'muted hover:text-[var(--text)]'}`
  return (
    <div className="min-h-screen flex flex-col">
      <header
        className="sticky top-0 z-20"
        style={{ background: 'var(--surface)', borderBottom: '1px solid var(--border)' }}
      >
        <div className="header-inner mx-auto max-w-[1400px] px-5 flex items-center gap-6" style={{ height: 52 }}>
          <NavLink to="/" className="brand-word flex items-center gap-2 font-semibold tracking-tight text-[15px] whitespace-nowrap">
            <span
              aria-hidden
              className="inline-block w-4 h-4 rounded-sm"
              style={{ background: 'var(--accent)' }}
            />
            BrandGuard
          </NavLink>
          <nav className="header-nav flex items-center gap-1">
            <NavLink to="/" end className={link}>
              New scan
            </NavLink>
            <NavLink to="/scans" className={link}>
              Scans
            </NavLink>
            <NavLink to="/brands" className={link}>
              Brands
            </NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-2">
            {health && (
              <>
                {health.inflight > 0 && (
                  <span className="badge badge-running pulse" title="Scans currently running">
                    <span className="dot" />
                    {health.inflight} running
                  </span>
                )}
                <HealthChip
                  className="hide-sm"
                  label="Reader"
                  ok={health.adjudicator !== 'rules'}
                  text={health.adjudicator === 'rules' ? 'rules only' : health.adjudicator_model ?? health.adjudicator}
                  title={
                    health.adjudicator === 'rules'
                      ? 'No LLM key is configured: undecided listings are settled by rules alone, and listing text is not read.'
                      : `Undecided listings are read by ${health.adjudicator} (${health.adjudicator_model}); the model answers questions about the text, the rules decide.`
                  }
                />
                <HealthChip
                  className="hide-sm"
                  label="APK sites"
                  ok={health.serper_configured}
                  text={health.serper_configured ? 'on' : 'off'}
                  title="Web search for APK mirror sites (Serper key). Off means only Google Play is scanned."
                />
                <span className="text-xs faint ml-1 hide-sm" title="Build version">
                  v{health.version}
                </span>
              </>
            )}
            {health?.public_url && <PublicLink url={health.public_url} />}
            <ThemeToggle />
          </div>
        </div>
      </header>
      <main className="page mx-auto w-full max-w-[1400px] px-5 py-6 flex-1">
        <Outlet />
      </main>
    </div>
  )
}
