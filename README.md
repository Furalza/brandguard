# BrandGuard

Detects apps that impersonate a brand across official and third-party app marketplaces.
Takes a brand profile as input and produces a list of candidate listings, each with a label,
a calibrated confidence score and auditable evidence for an analyst.

## Architecture

```
Brand profile
    |
    v
Discovery
    query expansion (typos, homoglyphs, semantic variants)
    per-source adapters -> normalized AppRecord
    |
    v
Triage cascade
    T0  cheap rules: veto signals, name and publisher similarity, metadata
    T1  icon hashing, permission drift
    T2  LLM adjudicator, only for grey-zone or conflicting records
    |
    v
Analyst output  { label, confidence, evidence[] }
```

## Documents

- `docs/THREAT_MODEL.md` - why each signal carries the weight it does
- `docs/PLAN.md` - work plan and what gets cut first under time pressure
- `KARARLAR.md` - decision log, abandoned experiments, known weaknesses

## Setup

_To be completed._
