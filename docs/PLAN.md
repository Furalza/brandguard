# Work Plan

Phases, not days. Commit history carries the timeline.

| Phase | Focus | Deliverable | Cut order under pressure |
|---|---|---|---|
| 0 | Foundation | repo, threat model, initial decisions | n/a |
| 1 | Schema and evaluation set | `AppRecord`, 2 brand profiles, 60-80 labelled records, locked holdout | never |
| 2 | Discovery | variant generator, mock adapters, normalization | live requests first |
| 3 | Triage T0 | veto rules, string and metadata signals, evidence generation | never |
| 4 | Triage T1 and T2 | icon hashing, permission drift, LLM adjudicator, injection tests | LLM first, then CLIP |
| 5 | Evaluation | confusion matrix, calibration, cost report, error analysis | never |
| 6 | Packaging | README, CLI, complete KARARLAR.md, demo rehearsal | n/a |

A method is dropped only for one of three reasons: measurably worse results,
budget overrun, or exposure to attacker-controlled input. "Ran out of time"
is recorded honestly as deferred.

## Git workflow

- Trunk-based: `main` always runs. Short-lived branches `feat/*`, `exp/*`, `docs/*`.
- Abandoned experiments keep their `exp/*` branch and are recorded in `KARARLAR.md`.
- Conventional Commits. Tags at milestones: `v0.1-schema`, `v0.2-discovery`, and so on.
