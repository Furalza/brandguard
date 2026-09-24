# BrandGuard: Technical Documentation

Detection of brand impersonation across app marketplaces and, as a second track,
lookalike websites. Given a brand profile, the system builds a candidate pool,
triages each candidate through a cost-aware cascade, and returns a label with a
calibrated confidence and auditable evidence an analyst can act on.

## Problem framing

The task is not "build a classifier" but "produce defensible input for a takedown
decision". Three consequences shaped every design choice:

- Output must be auditable. Evidence is concrete facts ("account created 16 days
  ago", "requests SMS"), never "the model was suspicious".
- False positives are the expensive error. A wrong takedown harms a legitimate
  publisher, so the system is precision-first and treats `uncertain` as a valid
  answer rather than forcing a call.
- Input is untrusted. App names, descriptions and reviews are attacker-controlled,
  so no zero-cost signal decides a label on its own.

## Architecture

```
Brand profile
   |
   v
Discovery      query expansion (homoglyph, typosquat, leet, multigraph, Turkish)
               per-source adapters normalise to a shared AppRecord
   |
   v
Triage cascade                                        cost per record
   T0   veto + string/metadata signals + fusion       milliseconds
   T1   perceptual-hash icon similarity                only if undecided
   T2   LLM adjudicator (injection-safe summary)       only if still undecided
   |
   v
Verdict   { app_id, source, label, confidence, evidence[] }
```

Labels: `official`, `impersonation`, `repackaged`, `third_party_legitimate`,
`unrelated`, `uncertain`.

### Discovery

Marketplace search matches literally, so searching the brand name alone misses
altered names. Query expansion generates search seeds across the transformations
attackers use, and coverage is measured against the evaluation set rather than
assumed. Each source has an adapter that maps its own schema onto `AppRecord`;
triage never sees source-specific data, so adding a source is one class. A
missing field stays `None` and its signal abstains, kept strictly distinct from
an observed zero.

Four discovery sources sit behind the same adapter interface: mock marketplaces
(for the evaluation set), live Google Play (a scraper), Serper (Google search)
for third-party APK sites, and Certificate Transparency logs (crt.sh) for the
domain track. Google Play is well policed and usually clean; the deeper sources
are where real impersonations surface, and crt.sh shows a phishing domain the
moment it obtains a certificate, before it is indexed or reported.

The Play scraper (google-play-scraper 1.2.7, the latest release) returns the
featured top search result without its package id, and that result is usually
the brand's own main app. `discovery/play_search.py` replaces only that field's
lookup and recovers the id from the structure the library already uses for the
other results; every Play search goes through it (K-056). Before the fix the
hunt missed the most relevant listing of every Play query.

### Brand registry

Brands are listed in `data/brands.csv`, one row each; a row can be just the
brand name. `python -m brandguard.registry sync --enrich` turns the rows into
the profiles the hunt reads, in `data/watchlist/` (K-053, K-054):

- Official domain, when not given: accepted only when two independent sources
  agree, Google (knowledge panel, or a top result about the brand) and the
  developer site of the brand's established Play app. A single source counts
  only in forms an impersonator cannot produce (Google's knowledge panel alone,
  or a Play app with 1M+ installs carrying the full brand name) and is flagged
  for review. Otherwise the brand is skipped and reported; no domain is guessed,
  because the veto trusts it.
- Official publishers, package ids and app titles: taken from Play only for a
  publisher whose claimed website or e-mail is under an official domain AND who
  has an app with 100k+ installs (K-055). All its apps then count, including
  small ones. Anything weaker is a `review` line with the reason.
- CSV values always win and lookups only add. Lookups are cached in the profile
  with their evidence and repeated only on `--refresh` or when the official
  domains change.
- Safety: only profiles the registry generated are ever changed or removed; a
  hand-written profile is never touched and a brand it covers is not scanned
  twice. Any validation error aborts the sync before a write. An online source
  failing three times in a row stops lookups for that run instead of hammering it.

### Triage cascade

The cascade spends effort only where it can change an outcome. Most records are
decided at T0; only conflicting or grey-zone cases reach the expensive tiers.

- Veto: trust is placed in publisher identity, not the publisher name (a name is
  attacker-controlled). An official verdict requires a name match plus an
  independent verifier an impersonator cannot type in: a store-verified flag, an
  established account, an official package id on Google Play (package ids are
  unique there), or a website on an official domain on a listing with 100k+
  installs. The website field is self-declared, so on its own it is only a
  claim: a copied name plus a typed-in domain on a fresh listing was reproduced
  as passing the old veto and no longer does (K-055). A matching name alone does
  not veto.
- Scored signals: name similarity (multi-dimensional, not a single ratio),
  account age (graded), developer history, permission drift (sector-aware, since
  a courier reading SMS is routine but a bank is not), and review consistency
  (keyed on an inconsistency an attacker cannot cheaply fake, never on review
  text). Signals combine with a saturating rule so no single weak signal crosses
  a threshold.
- An impersonation verdict requires at least one strong attacker-independent
  signal; a high score built only from weak or attacker-controllable signals
  escalates instead of being decided.
- T2 receives a structured, injection-safe summary, never raw attacker text. Its
  opinion re-enters as one dampened signal; the deterministic layer keeps the
  final decision and the false-positive budget.

## Website impersonation (second track)

Phishing more often lives on lookalike domains than on fake apps. A parallel
domain cascade mirrors the app one:

```
Official domain
   |
   v
Domain discovery   generate lookalike variants (typosquat, leet, lure-word, alt-TLD)
                   plus Serper searches for the brand off its official domain
   |
   v
Domain cascade                                     cost per domain
   D0   string similarity + brand-token check        no network
   D1   WHOIS age + TLS certificate                  only for live lookalikes
   D2   LLM adjudicator (structured facts only)       only if still ambiguous
   |
   v
DomainFinding  { verdict, similarity, priority, confirmed_live, evidence[] }
```

Verdicts are `official`, `lookalike`, `mentions`, `unrelated`, kept separate from
the app labels because a string-compared domain proves less than an app record.
D0 also reads a domain structurally (via `domain_anatomy`): a brand-prefixed name
paired with a credential-bait word (`paypal-login`) is a lookalike even when its
string distance is large, while a brand plus a neutral word (`paypalobjects`) is
only a mention. D1 orders the analyst queue by registration age (a fresh lookalike
is high; a years-old subsidiary is low); the certificate issuer is a weak nudge,
never a decision, since an attacker can also buy one.

Two distinctions keep the output honest. `confirmed_live` separates a domain a
source actually returned from a generated variant whose registration is unknown,
so results split into **detected** (real, found threats) and **watch** (generated
names to monitor). And `known_affiliates` in the profile allowlists a brand's own
vetted entities (`ziraatbank.de`, `ziraatkatilim.com.tr`) so they are treated as
official and leave the detected queue; the allowlist never shields a genuine
phishing shape. Page-content analysis (rendering the page, comparing the login
form) is defined as an extension point but not implemented.

## Operations

A single command, `python -m brandguard.hunt`, runs any set of sources
(`play,serper,website,crtsh`) for one brand or a whole watchlist directory. Each
run is written to `results/` as a timestamped JSON and summarised in a single
append-only `results/run_log.csv`, so a brand's exposure is comparable across
runs and sources over time (per-run JSON is the detail; the log is the ledger).
A source that throttles or fails for one brand is skipped and the sweep
continues, so a portfolio scan completes even when one live source is rate-
limited. crt.sh, which throttles often, is fetched with bounded exponential
backoff so a transient throttle is not mistaken for "no lookalikes".

## Evaluation

There is no external ground truth, so the evaluation set is part of the solution:
45 hand-labelled development records across 11 difficulty layers (the hardest and
largest being brand ecosystem apps and legitimate third-party tools), plus an
8-record locked holdout evaluated once.

On the development set, with the deterministic adjudicator (measured 2026-09-24):

- Takedown false-positive rate: 0% (0 of 18 takedowns; constraint: under 5%)
- Missed threats (a real threat labelled benign): 0% (0 of 20)
- Impersonation precision 1.0, recall 0.88 (15 of 17; the two misses defer to
  `uncertain`, never to a benign label)
- Most records are decided at T0; `scripts/evaluate.py` prints the exact share

Earlier decision-log entries report recall 0.94 on 44 records; the record added
since then defers to `uncertain`. The locked holdout of unseen records, evaluated
once, gave 6/8 exact, 0% takedown FP and 0% missed threats. Confidence was
calibrated against the set: an early over-statement on benign labels was
measured and corrected. Every change to the veto since is checked by running the
evaluation before and after; K-055 and its refinement left every label unchanged.

The system was also run against live Google Play through an optional source.
Real data surfaced issues the mock never showed, including a false positive where
a real bank's official app was flagged for takedown; each was diagnosed and
fixed (K-029 to K-032). Later, checking live output against an independent
source (AppBrain) found the self-declared-website hole (K-055) and the dropped
top search result (K-056). After K-056 the brand's main app is the first,
official-labelled result for 18 of 19 watchlist brands; the exception has no
current app on Play.

## Setup and use

```
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev,icons]"      # extras: llm, live (Google Play), serper (search), whois (domain age)

python run.py --profile data/profiles/ornek_bank.json \
              --records data/testset/ornek_bank.json --pretty

python scripts/evaluate.py         # metrics
pytest                             # 237 tests

python -m brandguard.registry sync --enrich        # brands.csv -> data/watchlist
python -m brandguard.hunt --watchlist data/watchlist --source play,serper
```

The LLM tier is optional. With an `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` (env
or `.env`) it uses the real model; otherwise it falls back to a deterministic
rule adjudicator, so every command works offline.

## Known limits

- `unrelated` versus `third_party_legitimate` is a semantic distinction the cheap
  tiers cannot make reliably; both are benign (no takedown), so the confusion
  carries no takedown cost, and it is deferred to T2.
- Live Google Play does not expose publisher account age or verification, so the
  strongest attacker-independent signals are absent there and the system is more
  conservative on live data.
- A genuine official app under 100k installs whose package id is not yet in the
  profile is not vetoed on Play; it falls through to scoring and ends at worst
  `uncertain`, never a takedown. Adding its package to the CSV fixes it.
- Registry lookups see only the top Play results for the brand name, so an
  official app that does not rank for it must be added in the CSV. A source that
  reports no install figure still accepts a claimed website on its own.
- The Play source depends on an unofficial scraper. The top-result fix (K-056)
  relies on Play's current data shape; `python scripts/inspect_brand.py "<brand>"`
  is the quick live check (the main app should be the first line).
- Real impersonations largely live off Google Play, which is well policed. The
  Serper and crt.sh sources cover third-party apps and certificate logs; further
  stores are one adapter each.
- The website track triages domains by similarity, structure, registration age
  and certificate; page-content analysis (rendering the page, comparing the login
  form and logo) is an extension point, not yet implemented.
- On well-policed brands the system is correctly quiet; genuine lookalikes show
  up most on heavily targeted global brands via crt.sh. A generated variant is a
  watch-list entry, not a detection, until a source confirms it exists.

## Repository

```
src/brandguard/
  schema.py            shared normalised data model
  discovery/           normalisation, similarity, query expansion, adapters,
                       live Google Play (play_search), Serper, crt.sh,
                       website + domain cascade
  triage/              signals, veto, fusion, T1 (icon), T2 (adjudicator)
  eval/                dataset loader, metrics, red-team generator
  hunt_engine.py       unified engine over all sources, timestamped recording
  hunt.py              unified CLI (python -m brandguard.hunt)
  registry.py          brand CSV -> watchlist profiles, with verified online lookup
scripts/               evaluation, per-source runners, watchlist scan/diff,
                       brand inspector, fixtures
data/                  brands.csv, watchlist profiles, labelled test sets, mock marketplaces
run.py                 end-to-end CLI
KARARLAR.md            decision log, abandoned experiments, known weaknesses, next steps
```

`KARARLAR.md` holds the rationale for every non-obvious decision, the experiments
that were tried and dropped, the known weaknesses, and what a further month would
change. The threat model behind each signal weight is in `docs/THREAT_MODEL.md`;
the registry's CSV format and rules are in `docs/BRAND_REGISTRY.md`.
