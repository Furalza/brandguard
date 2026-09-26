// Plain-language explanations of a finding. Every engine evidence line is
// turned into one short sentence and sorted into a group: what pulls toward a
// threat, what pulls toward legitimacy, what decided on its own. The raw
// engine text stays available underneath, so nothing is hidden.

import { CATEGORY_HINT, LABEL_TEXT, type Evidence, type Finding } from './api'

export type Group = 'decisive' | 'plus' | 'minus' | 'reader' | 'info'

export const GROUP_TITLE: Record<Group, string> = {
  decisive: 'Decided on its own',
  plus: 'Points to a threat (+)',
  minus: 'Points to legitimacy (−)',
  reader: 'What the listing text says (read by the model)',
  info: 'Context',
}

const DECISIVE = new Set(['publisher_veto', 'package_veto', 'unauthorized_build', 'developer_account'])

export function isReaderSignal(signal: string): boolean {
  return signal.startsWith('reader_')
}

export function groupOf(e: Evidence): Group {
  if (DECISIVE.has(e.signal)) return 'decisive'
  if (isReaderSignal(e.signal)) return 'reader'
  if (e.signal === 'affiliate_hint' || e.signal === 'page_kind') return 'info'
  if (e.weight > 0.05) return 'plus'
  if (e.weight < -0.05) return 'minus'
  return 'info'
}

function num(text: string, re: RegExp): string | null {
  const m = text.match(re)
  return m ? m[1] : null
}

function quoted(text: string): string | null {
  const m = text.match(/'([^']+)'/)
  return m ? m[1] : null
}

/** One short sentence for an evidence line. Falls back to the engine text. */
export function plainEvidence(e: Evidence): string {
  const t = e.text
  switch (e.signal) {
    case 'publisher_veto': {
      let how = 'its identity was verified'
      if (t.includes('official package id')) how = 'the package id is on the official list (package ids are unique on Play)'
      else if (t.includes('publisher website on an official domain')) {
        const installs = num(t, /with ([\d,]+)\+ installs/)
        how = installs ? `its developer site is on an official domain and it has ${installs}+ installs` : 'its developer site is on an official domain'
      } else if (t.includes('predates')) how = 'the publisher account is long established'
      else if (t.includes('store-verified')) how = 'the store verified the publisher'
      return `The publisher name matches the official list and ${how}.`
    }
    case 'package_veto':
      return `An official package id under another publisher (${quoted(t.split('but publisher')[1] ?? '') ?? 'unknown'}): a repackaged build.`
    case 'unauthorized_build': {
      const markers = num(t, /\(([^)]+)\)/)
      return `The listing advertises a modified build of the brand's app (${markers ?? 'mod'}) from a publisher that is not the brand.`
    }
    case 'developer_account':
      return `Published from the same Play developer account as the verified official app '${quoted(t) ?? '?'}'; account ids cannot be shared.`
    case 'name_similarity':
      if (t.includes('does not resemble')) return 'The app name does not resemble the brand.'
      if (t.includes('visually identical')) return 'The app name looks identical to the brand name.'
      if (t.includes('begins with')) return 'The app name starts with the brand name.'
      if (t.includes('does not lead with')) return 'The app name mentions the brand but does not lead with it.'
      return `The app name resembles the brand (similarity ${num(t, /jw=([\d.]+)/) ?? '?'}).`
    case 'account_age': {
      const days = num(t, /created (\d+) days ago/)
      if (days) return `The publisher account is very new: created ${days} days ago.`
      const years = num(t, /is (\d+) years old/)
      if (years) return `The publisher account is ${years} years old; established.`
      const months = num(t, /is (\d+) months old/)
      if (months) return `The publisher account is ${months} months old.`
      return t
    }
    case 'solo_publisher':
      return 'The publisher has no other apps.'
    case 'permission_drift': {
      const list = t.split(':')[1]?.replace(/\(no official.*$/, '').trim().replace(/\.$/, '') ?? ''
      const weak = t.includes('no official permission baseline') ? ' (no official permission baseline; a weak signal)' : ''
      return `Requests sensitive permissions unexpected for this sector: ${list}${weak}.`
    }
    case 'companion_build': {
      const marker = quoted(t)
      return `A modded build of a third-party companion app (${marker ? `"${marker}"` : 'downloader, stats, tips'}); the brand is its subject, not its publisher, so this is not the brand's app being repackaged.`
    }
    case 'review_consistency':
      return 'Installs and reviews do not add up: a large install base, almost no reviews, a perfect rating (the bought-review pattern).'
    case 'adjudicator': {
      if (t.includes('adjudicator unavailable')) return 'The adjudicator (language model) was unreachable; no opinion.'
      if (t.includes('could not be parsed')) return 'The model reply could not be understood; treated as no opinion.'
      const lean = num(t, /leans (\w+):/)
      const reasoning = t.split(':').slice(1).join(':').trim()
      return `Reading of the text leans ${LABEL_TEXT[lean ?? '']?.toLowerCase() ?? lean ?? '?'}: ${reasoning}`
    }
    case 'reader_subject':
    case 'reader_claims_official':
    case 'reader_credentials':
    case 'reader_injection':
    case 'reader_quote':
    case 'reader_note':
      return t
    case 'icon_similarity':
      if (t.includes('identical')) return 'The icon is identical to the official icon.'
      if (t.includes('closely resembles')) return 'The icon closely resembles the official icon.'
      return 'The icon does not resemble the official icon.'
    case 'page_kind': {
      if (t.startsWith('Page on the brand')) return "A page on the brand's own official domain; not a store listing."
      const kind = num(t, /is a (\w+) page/)
      const kinds: Record<string, string> = { article: 'article or forum', spam: 'SEO spam', gov: 'institutional or government', developer: "a publisher's catalogue" }
      return `Not an app listing; the page is ${kinds[kind ?? ''] ?? kind}.`
    }
    case 'affiliate_hint':
      if (t.includes('matches the official publisher name')) return 'The publisher name equals the official publisher, but the identity could not be verified (installs below the bar, or the package id is not on the list).'
      if (t.includes('under an official domain')) return 'The developer site is on an official domain, but the listing is not established enough to prove the claim.'
      if (t.includes('vetted affiliate')) return 'The developer site is on a vetted affiliate domain.'
      if (t.startsWith('Publisher name')) return `The publisher name carries the brand token '${quoted(t.split(';')[0].split('token')[1] ?? '') ?? '?'}'; probably a regional or subsidiary publisher, unverified.`
      return 'The developer site carries the brand token but is not an official domain; probably a regional site, unverified.'
    case 'mirror_listing': {
      const host = num(t, /mirror site ([^,]+),/)
      return `A copy of the brand's app on the mirror site ${host ?? ''}, with no sign of modification in its title. Without a signature check nobody can say the APK is untouched; treat it as an unauthorized copy to review.`
    }
    case 'ambiguous_brand_word': {
      const n = num(t, /shared by (\d+) unrelated/)
      return `The brand word is shared by ${n ?? 'several'} unrelated products in this result set, and this listing names none of the brand's identity words (publisher, flagship title, domain); a person should confirm it is the brand's app before a takedown.`
    }
    case 'domain':
      return plainDomain(t)
    default:
      return t
  }
}

function plainDomain(t: string): string {
  if (t.startsWith('Exact match')) return 'Exactly an official domain.'
  if (t.startsWith('Subdomain of')) return "A subdomain of an official domain (the brand's own infrastructure)."
  if (t.startsWith('Known legitimate affiliate')) return 'A vetted affiliate (allowlisted).'
  if (t.startsWith('Domain closely resembles')) return `Closely resembles an official domain but is not one (similarity ${num(t, /similarity ([\d.]+)/) ?? '?'}).`
  if (t.startsWith('Domain contains the brand')) return 'Contains the brand name but is not a close lookalike.'
  if (t.startsWith('Domain does not resemble')) return 'Does not resemble the brand.'
  if (t.startsWith('Generated')) return `A generated variant (${num(t, /Generated (\w+) variant/) ?? ''}); whether it is registered is unknown.`
  if (t.startsWith('Confirmed live')) return 'A search engine returned this domain: the site exists.'
  if (t.startsWith('Returned by a live web search')) return 'Found by a live web search.'
  if (t.startsWith('Domain registered')) return `The domain was registered ${num(t, /(\d+) days ago/) ?? '?'} days ago.`
  if (t.startsWith('Established domain')) return 'An established domain; consistent with a legitimate affiliate rather than a fresh phishing setup.'
  if (t.startsWith('Young lookalike')) return 'A young lookalike domain with a fresh certificate or a login form.'
  if (t.startsWith('Signals are mixed')) return 'Signals are mixed; a person should look at the page.'
  if (t.startsWith('Seen in CT logs')) return `Seen in certificate logs (first certificate ${t.split('first cert ')[1]?.replace(/\.$/, '') ?? '?'}).`
  return t
}

function installs(f: Finding): string | null {
  const n = f.extra.installs
  return typeof n === 'number' ? n.toLocaleString('en-US') : null
}

/** Two or three sentences: what the category means and why this row got it. */
export function summary(f: Finding): string {
  const pub = typeof f.extra.publisher === 'string' && f.extra.publisher ? f.extra.publisher : null
  const inst = installs(f)
  const facts = pub ? ` Publisher: ${pub}${inst ? `, ${inst} installs` : ''}.` : ''
  if (f.kind === 'domain') {
    const base = CATEGORY_HINT[f.category]
    if (f.category === 'suspicious' && f.confirmed_live === false)
      return `${base} This name is a variant we generated; its registration was not confirmed, so it is a watch item.`
    return base
  }
  switch (f.category) {
    case 'official':
      if (f.reason === 'same_developer_account') return `Official. Published from the same Play developer account as a verified official app; small or regional, it is still the brand's own.${facts}`
      return `Official. The publisher name matches the official list and its identity was confirmed by evidence an attacker cannot forge.${facts}`
    case 'malicious':
      if (f.label === 'repackaged') {
        if (f.evidence.some((e) => e.signal === 'unauthorized_build'))
          return `Takedown candidate. The listing advertises a modified ("mod", "cracked", "premium unlocked") build of the brand's app from a publisher that is not the brand: the real product, altered and redistributed.${facts}`
        return `Takedown candidate. An official package id sits under a publisher that is not the brand: the app was taken and repackaged.${facts}`
      }
      if (f.reason === 'veto') return `Takedown candidate. A hard rule fired.${facts}`
      return `Takedown candidate. The suspicion score crossed the threshold and was backed by evidence outside the attacker's control (account age or permission drift).${facts}`
    case 'suspicious':
      if (f.reason === 'mirror_unverified')
        return `Unverified copy. A mirror site lists what looks like the brand's own app, unmodified. It is not an impersonation, but nobody can confirm the APK is the original without a signature check.${facts}`
      return `Grey zone. The system deliberately did not decide: the pluses and minuses below balance each other, or there was no independent evidence to carry a decision. A person should look.${facts}`
    case 'affiliate':
      return `${CATEGORY_HINT.affiliate}${facts}`
    case 'related':
      if (f.evidence.some((e) => e.signal === 'companion_build'))
        return `Related, not a takedown: a modified build of a third-party app that uses the brand as its subject (a downloader, a stats widget, a guide). The brand's own product is not what was repackaged.${facts}`
      return `Related to the brand, no threat signal: the name or package mentions the brand; permissions and publisher are ordinary. Probably an independent tool or content.${facts}`
    case 'noise':
      if (f.reason.startsWith('non_listing')) return 'Not an app listing: the search engine returned an article, a forum thread or a spam page.'
      return `No link to the brand found: neither the name nor the package mentions it. Search noise.${facts}`
    default:
      return LABEL_TEXT[f.label] ?? f.label
  }
}

/** The decision path as numbered plain steps. */
export function decisionSteps(f: Finding): string[] {
  if (f.kind === 'domain') {
    const steps = [`Domain rules: ${LABEL_TEXT[f.label] ?? f.label}`]
    if (f.confirmed_live === false) steps.push('Generated name; registration unknown (watch item)')
    if (f.confirmed_live) steps.push('A source actually returned this domain')
    if (f.priority) steps.push(`WHOIS/SSL priority: ${f.priority}`)
    return steps
  }
  const steps: string[] = []
  const tiers = f.tiers_used.length ? f.tiers_used : [0]
  const score = f.score !== null ? f.score.toFixed(2) : null
  if (f.reason.startsWith('non_listing')) return ['The page is not a listing; the engine was not run']
  if (f.reason === 'veto') return ['A hard rule (veto) fired; no scoring was needed']
  if (f.reason === 'same_developer_account')
    return [
      'Identity could not be verified on its own (below the install bar, or no package id on file)',
      'A verified official app in the same scan shares its developer account',
      'Marked official',
    ]
  steps.push(`Rules scored the signals: ${score ?? '—'} (below 0.25 benign, 0.35–0.60 grey zone, above 0.60 impersonation)`)
  if (tiers.includes(1)) steps.push('Icon similarity added')
  if (tiers.includes(2)) steps.push('Adjudicator (language model) opinion added')
  const why: Record<string, string> = {
    benign: 'No suspicion; treated as benign',
    scored: 'Threshold crossed with independent backing; decided',
    conflict: 'Signals conflicted; the listing text was read',
    grey_zone: 'Score stayed in the grey zone; the listing text was read',
    thin_evidence: 'Only one signal; the listing text was read',
    unbacked_high: 'High score but no attacker-independent evidence; not called an impersonation',
    adjudicated_benign: 'The reading of the listing text closed it as benign',
    final_uncertain: 'Still uncertain after reading the listing; left to an analyst',
  }
  if (f.reason === 'mirror_unverified')
    return ['The listing is on a known mirror site and names the brand\'s app without a "mod" marker', 'Signature comparison is not available, so the copy cannot be verified', 'Left uncertain: an unauthorized copy to review, not an impersonation']
  if (f.reason === 'ambiguous_brand_word')
    return ['The build veto fired (a "mod" of an app carrying the brand word)', 'The brand word is shared by several unrelated products in this result set and the listing names no identity word of the brand', 'Left uncertain for a person to confirm']
  if (f.reason === 'scored' && f.label === 'uncertain') steps.push('Score reached neither the benign nor the impersonation threshold; uncertain')
  else steps.push(why[f.reason] ?? f.reason)
  if (f.category === 'affiliate') steps.push('Publisher identity points at the brand; set aside as "possible affiliate"')
  if (f.category === 'related' && f.label === 'third_party_legitimate') steps.push('Counted as "related", not "noise", because the name or package mentions the brand')
  return steps
}
