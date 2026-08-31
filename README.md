# BrandGuard

Detects apps that impersonate a brand across app marketplaces. Takes a brand
profile, expands the search space to catch altered names, and triages candidate
listings through a cost-aware cascade into labelled, evidence-backed verdicts an
analyst can act on.

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

Design rationale for every non-obvious choice is in `KARARLAR.md` (decision
log). The threat model that justifies each signal weight is in
`docs/THREAT_MODEL.md`.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev,icons]"      # add ,llm for the real LLM adjudicator
```

## Usage

Run the cascade over a set of candidate records:

```bash
python run.py --profile data/profiles/ornek_bank.json \
              --records data/testset/ornek_bank.json
```

Options: `--pretty` for a table with evidence, `--only impersonation` to filter,
`--official-icon path.png` to enable icon comparison.

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

## Tests

```bash
pytest        # 92 tests
ruff check .
```

## Layout

```
src/brandguard/
  schema.py            normalized data model shared by every stage
  discovery/           normalization, name similarity, query expansion, adapters
  triage/              signals, veto, fusion, T1 (icon), T2 (adjudicator)
  eval/                dataset loader, metrics
scripts/               red-team generator, live runner, evaluation, icon fixtures
data/                  brand profiles, labelled test sets, mock marketplaces
docs/                  threat model, evaluation-set design, plan
run.py                 end-to-end CLI
KARARLAR.md            decision log, abandoned experiments, known weaknesses
```
