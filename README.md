# BrandGuard

Detects brand impersonation across app marketplaces and, as a second track,
lookalike websites. Takes a brand profile, expands the search space to catch
altered names and domains, and triages candidates through a cost-aware cascade
into labelled, evidence-backed verdicts an analyst can act on.

## What it does

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
returned, and D1 orders the analyst queue by registration age.

Design rationale for every non-obvious choice is in `KARARLAR.md` (decision
log). The threat model that justifies each signal weight is in
`docs/THREAT_MODEL.md`.

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

Other entry points:

```bash
python scripts/scrape_and_triage.py --brand "..." --sector banking   # live Google Play
python scripts/serper_hunt.py --profile data/watchlist/<brand>.json    # third-party apps
python scripts/website_hunt.py --profile data/watchlist/<brand>.json   # lookalike domains
python scripts/watchlist_scan.py --watchlist data/watchlist            # scan many brands, log results
```

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

On the 44-record development set (deterministic adjudicator):

- Takedown false-positive rate: **0%** (brief constraint: under 5%)
- Missed threats (a real impersonation labelled benign): **0%**
- Impersonation precision **1.0**, recall **0.94**
- **84%** of records decided at T0 (the cheap tier)

A locked holdout of unseen records, evaluated once, reproduced these figures
(6/8 exact, 0% takedown FP, 0% missed threats); the two misses are the known
`unrelated`/`third_party` confusion, which carries no takedown cost. Details and
known weaknesses are in `KARARLAR.md`. 

The system also runs against live sources: Google Play
(`scripts/scrape_and_triage.py`), third-party APK sites via Serper
(`scripts/serper_hunt.py`), and lookalike websites (`scripts/website_hunt.py`).
Testing on real data surfaced and fixed issues the mock never showed (schema
inconsistency, and false positives where a real bank's official app or an
official package with no publisher were flagged for takedown), recorded across
K-029 to K-040.

## Tests

```bash
pytest        # 132 tests
ruff check .
```

## Layout

```
src/brandguard/
  schema.py            normalized data model shared by every stage
  discovery/           normalization, name/domain similarity, query expansion,
                       adapters, live Google Play, Serper, website + domain cascade
  triage/              signals, veto, fusion, T1 (icon), T2 (adjudicator)
  eval/                dataset loader, metrics, red-team generator
scripts/               evaluation, live triage, watchlist scan, website hunt,
                       brand inspector, fixtures
data/                  brand profiles, labelled test sets, mock marketplaces
docs/                  threat model, evaluation-set design, plan
run.py                 end-to-end CLI
KARARLAR.md            decision log, abandoned experiments, known weaknesses
```
