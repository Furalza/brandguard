# BrandGuard

Detects brand impersonation across app marketplaces and, as a second track,
lookalike websites. Takes a brand profile, expands the search space to catch
altered names and domains, and triages candidates through a cost-aware cascade
into labelled, evidence-backed verdicts an analyst can act on.

## What it does

Brands to protect are listed in one CSV; a row can be just the brand name. The
registry turns each row into a brand profile, looking up the official domain,
publishers and apps online with proof (see [Brand registry](#brand-registry)).
Given a brand profile:

```json
{
  "brand_name": "Örnek Bank",
  "official_domains": ["ornekbank.com.tr"],
  "official_publishers": ["Örnek Bank A.Ş."],
  "known_official_apps": ["Örnek Bank Mobil", "Örnek Bank Kurumsal"],
  "sector": "banking"
}
```

it produces one verdict per candidate listing:

```json
{
  "app_id": "com.ornekbank.mobil2026",
  "source": "apkpure",
  "label": "impersonation",
  "confidence": 0.95,
  "evidence": [
    "App name 'Örnek Bank Mobil' begins with the brand name.",
    "Publisher account was created 16 days ago.",
    "Publisher has no other apps.",
    "Requests sensitive permissions not expected for a banking app: READ_SMS, RECEIVE_SMS, SYSTEM_ALERT_WINDOW."
  ]
}
```

Every evidence line is auditable: an analyst decides on facts, not on "the model
was suspicious".

## Architecture

```
Brand profile
    |
    v
Discovery
    query expansion  (homoglyphs, typosquats, leet, multigraph, Turkish, suffixes)
    source adapters  (per-marketplace schema -> normalized AppRecord)
    |
    v
Triage cascade                                   cost per record
    T0  veto + string/metadata signals + fusion     ~milliseconds
    T1  perceptual-hash icon similarity             ~tens of ms, only if undecided
    T2  LLM adjudicator (injection-safe summary)    ~seconds, only if still undecided
    |
    v
Verdict  { label, confidence, evidence[] }
```

The six labels are `official`, `impersonation`, `repackaged`,
`third_party_legitimate`, `unrelated`, `uncertain`. `uncertain` is a real
answer: the system defers rather than force a costly wrong call.

A parallel track hunts lookalike websites, where phishing more often lives:

```
Official domain
    |
    v
Domain discovery  generated lookalikes (typosquat, leet, lure-word, alt-TLD)
                  + Serper (Google search) for the brand off its official domain
    |
    v
Domain cascade
    D0  string similarity + brand-token check     no network
    D1  WHOIS age + TLS certificate               only for live lookalikes
    D2  LLM adjudicator (structured facts only)   only if still ambiguous
```

Domain verdicts (`lookalike`, `mentions`, `unrelated`) are separate from app
labels; a generated variant is distinguished from a domain a search actually
returned (`confirmed_live`), and D1 orders the analyst queue by registration age.

Findings split into **detected** (lookalikes a source actually found: real
threats to action) and **watch** (generated lookalike names to monitor, not yet
confirmed to exist), so a run reports "1 detected, 45 to watch" rather than an
inflated single count. A profile's `known_affiliates` allowlists vetted
legitimate entities (a brand's own subsidiaries such as `ziraatbank.de`) so they
leave the detected queue; the allowlist never shields a real phishing shape.

Design rationale for every non-obvious choice is in `KARARLAR.md` (decision
log). The threat model that justifies each signal weight is in
`docs/THREAT_MODEL.md`.

### Identity rules

An `official` verdict rests on publisher identity, never on a name, and only on
evidence an impersonator cannot type in (K-014, K-055):

- a store-verified publisher, or an account that predates the brand-age cutoff;
- an official package id on Google Play, where package ids are unique;
- a developer website on an official domain, but only on a listing with 100k+
  installs: the website field is self-declared, organic reach is not.

A copied official name plus a typed-in official domain on a fresh listing does
not pass; this was reproduced as a failing test before the rule was tightened.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev,icons]"      # extras: llm, live (Google Play), serper (search), whois (domain age)
```

## Usage

Run the cascade over a set of candidate records:

```bash
python run.py --profile data/profiles/ornek_bank.json \
              --records data/testset/ornek_bank.json
```

Options: `--pretty` for a table with evidence, `--only impersonation` to filter,
`--official-icon path.png` to enable icon comparison.

### Brand registry

`data/brands.csv` lists every brand; the registry keeps `data/watchlist/` in
sync with it. Details in `docs/BRAND_REGISTRY.md`.

```bash
python -m brandguard.registry check           # validate, show the plan, write nothing
python -m brandguard.registry sync --enrich   # create/update/remove profiles, look up missing data
```

- A row can be just `brand_name`. The official domain is accepted only when two
  independent sources agree (Google's knowledge panel or a top result, and the
  developer site of the brand's established Play app); otherwise the brand is
  skipped and reported, never guessed.
- Official publishers and apps are taken from Google Play only when the claimed
  domain is backed by an app with 100k+ installs; anything weaker goes to a
  `review` line for the analyst, never into the profile.
- Anything typed into the CSV wins over what is looked up. Lookups are cached in
  the profile; `--refresh` re-checks them.
- Only generated profiles are ever changed or removed; a hand-written profile is
  never touched, and a CSV with errors writes nothing.

### Live hunting

A single command runs every discovery source and records each run:

```bash
python -m brandguard.hunt --profile data/watchlist/ziraat.json --source crtsh
python -m brandguard.hunt --brand "Binance" --official-domain binance.com --source crtsh,website
python -m brandguard.hunt --watchlist data/watchlist --source play,serper,website
```

Sources: `play` (live Google Play), `serper` (third-party APK sites via Google
search), `website` (lookalike domains), `crtsh` (Certificate Transparency logs,
the deepest source: a phishing domain appears there the moment it gets a
certificate). Every run is saved to `results/<UTC>__<brand>__<source>.json` and
appended to `results/run_log.csv`, so runs are comparable over time; compare two
with `scripts/watchlist_diff.py`. A throttled source for one brand is skipped and
the sweep continues.

The LLM tier (T2) is optional. With `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` in
the environment or a `.env` file, it uses the real model; without one it falls
back to a deterministic rule adjudicator, so the command works everywhere. Copy
`.env.example` to `.env` to configure a key.

## Evaluation

The evaluation set is hand-built and labelled; there is no external ground
truth. Run the metrics:

```bash
python scripts/evaluate.py
```

On the 45-record development set (deterministic adjudicator, measured 2026-09-24):

- Takedown false-positive rate: **0%** (0 of 18 takedowns; brief constraint: under 5%)
- Missed threats (a real threat labelled benign): **0%** (0 of 20)
- Impersonation precision **1.0**, recall **0.88** (15 of 17; the other two
  defer to `uncertain`, never to a benign label)
- Most records are decided at T0, the cheap tier; `evaluate.py` prints the share

Earlier entries in `KARARLAR.md` report recall 0.94 on 44 records; a record
added to the set since then defers to `uncertain` (see Known Weaknesses there).
A locked holdout of unseen records, evaluated once, gave 6/8 exact, 0% takedown
FP and 0% missed threats; the two misses are the known `unrelated`/`third_party`
confusion, which carries no takedown cost.

The system also runs against live sources through the unified hunt command:
Google Play, third-party APK sites (Serper), lookalike websites, and Certificate
Transparency logs (crt.sh). Testing on real data surfaced and fixed issues the
mock never showed (schema inconsistency; false positives where a real bank's
official app, an official package with no publisher, or the brand's own
subdomains were flagged), recorded across K-029 to K-049. Checking live output
against an independent source found two more: a self-declared developer website
was accepted as proof of identity (K-055), and the Play scraper dropped the
package id of the top search result, so every brand's main app was missing from
the hunt (K-056). After the fix the main app is the first, official-labelled
result for 18 of 19 watchlist brands. On real Turkish banks
the system is correctly quiet (their active impersonations are rare and quickly
removed); on heavily targeted global brands the crt.sh source surfaces genuine
lookalikes (e.g. dozens for Binance). The system is brand-agnostic: banks were
only the test data, and non-bank brands (Trendyol, Netflix, Getir) run through
the same pipeline.

## Tests

```bash
pytest        # 237 tests
ruff check .
```

## Layout

```
src/brandguard/
  schema.py            normalized data model shared by every stage
  discovery/           normalization, name/domain similarity, query expansion,
                       adapters, live Google Play (play_search), Serper, crt.sh,
                       website + domain cascade (anatomy, WHOIS/SSL signals)
  triage/              signals, veto, fusion, T1 (icon), T2 (adjudicator)
  eval/                dataset loader, metrics, red-team generator
  hunt_engine.py       unified engine over all sources, timestamped recording
  hunt.py              unified CLI (python -m brandguard.hunt)
  registry.py          brand CSV -> watchlist profiles (python -m brandguard.registry)
scripts/               evaluation, per-source runners, watchlist scan/diff,
                       brand inspector, fixtures
data/                  brands.csv, watchlist profiles, labelled test sets, mock marketplaces
docs/                  threat model, evaluation-set design, brand registry, plan
run.py                 end-to-end CLI
KARARLAR.md            decision log, abandoned experiments, known weaknesses
```
