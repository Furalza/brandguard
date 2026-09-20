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

Three discovery sources sit behind the same adapter interface: mock marketplaces
(for the evaluation set), live Google Play (optional, via a scraper), and Serper
(Google search) for third-party APK sites where real impersonations live. Google
Play is well policed and usually clean; the third-party search is where fake apps
actually surface.

### Triage cascade

The cascade spends effort only where it can change an outcome. Most records are
decided at T0; only conflicting or grey-zone cases reach the expensive tiers.

- Veto: trust is placed in publisher identity, not the publisher name (a name is
  attacker-controlled). An official verdict requires a name match plus an
  independent verifier (verified flag, website on an official domain, or an
  established account). A matching name alone does not veto.
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
`confirmed_live` separates a domain a search actually returned from a generated
name whose registration is unknown, so the system never claims to have "found" a
site it only constructed. D1 orders the analyst queue by registration age (a
fresh lookalike is high priority; a years-old subsidiary is low); the certificate
issuer is a weak nudge, never a decision, since an attacker can also buy one. On
a live run for a real bank the system correctly pushed legitimate subsidiaries
(ziraatbank.de, ziraatkatilim.com.tr) to low priority. Page-content analysis is
defined as an extension point but not implemented.

## Evaluation

There is no external ground truth, so the evaluation set is part of the solution:
44 hand-labelled development records across 11 difficulty layers (the hardest and
largest being brand ecosystem apps and legitimate third-party tools), plus an
8-record locked holdout evaluated once.

On the development set, with the deterministic adjudicator:

- Takedown false-positive rate: 0% (constraint: under 5%)
- Missed threats (a real impersonation labelled benign): 0%
- Impersonation precision 1.0, recall 0.94
- 84% of records decided at T0

The locked holdout of unseen records reproduced these figures (6/8 exact, 0%
takedown FP, 0% missed threats). Confidence was calibrated against the set: an
early over-statement on benign labels was measured and corrected.

The system was also run against live Google Play through an optional source.
Real data surfaced issues the mock never showed, including a false positive where
a real bank's official app was flagged for takedown; each was diagnosed and
fixed. This is documented in the decision log (K-029 to K-032).

## Setup and use

```
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev,icons]"      # extras: llm, live (Google Play), serper (search), whois (domain age)

python run.py --profile data/profiles/ornek_bank.json \
              --records data/testset/ornek_bank.json --pretty

python scripts/evaluate.py         # metrics
pytest                             # 132 tests
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
- Real impersonations largely live on third-party stores rather than Google Play,
  which is well policed. A Serper (Google search) source covers third-party APK
  sites; further stores are one adapter each.
- The website track triages domains by similarity, registration age and
  certificate; page-content analysis (rendering the page, comparing the login
  form and logo) is an extension point, not yet implemented.

## Repository

```
src/brandguard/
  schema.py            shared normalised data model
  discovery/           normalisation, name/domain similarity, query expansion,
                       adapters, live Google Play, Serper, website + domain cascade
  triage/              signals, veto, fusion, T1 (icon), T2 (adjudicator)
  eval/                dataset loader, metrics, red-team generator
scripts/               evaluation, live triage, watchlist scan, website hunt,
                       brand inspector, fixtures
data/                  brand profiles, labelled test sets, mock marketplaces
run.py                 end-to-end CLI
KARARLAR.md            decision log, abandoned experiments, known weaknesses, next steps
```

`KARARLAR.md` holds the rationale for every non-obvious decision, the experiments
that were tried and dropped, the known weaknesses, and what a further month would
change. The threat model behind each signal weight is in `docs/THREAT_MODEL.md`.
