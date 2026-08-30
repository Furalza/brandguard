# KARARLAR.md - Decision Log

Every decision uses the format below. Reverted decisions are never deleted;
their status changes. This file matters as much as the code.

```
## K-NNN: Title
Context: why was a decision needed?
Options: alternatives considered
Decision:
Rationale:
Rejected and why:
Status: active | reverted | deferred
```

---

## K-001: Language and ecosystem - Python
Context: Fast prototyping; mature libraries for string, image and ML work.
Options: Python, Java/Spring, TypeScript/Node
Decision: Python 3.11+, pydantic (schema), rapidfuzz (string similarity), imagehash (icons), pytest.
Rationale: The domain libraries (unicode confusables, perceptual hashing, fuzzy matching) are most mature here. The same work in Java is roughly twice the code.
Rejected and why: Java - better at scale, expensive for a prototype. Noted for the production discussion: the cheap tier is portable to Go/Java.
Status: active

## K-002: Threat model before code
Context: Signal weights must not be arbitrary.
Decision: `docs/THREAT_MODEL.md` is the reference for every weight. A weight change requires a threat model update first.
Rationale: In the demo, "why is the icon weight low?" must be answered with "zero cost for the attacker", not "it worked better".
Status: active

## K-003: Cascade architecture
Context: Thousands of records, recurring runs, cost constraint.
Options: (a) one model on every record, (b) single rule-based layer, (c) cascade
Decision: Three tiers:
  T0 cheap: veto rules, string similarity, metadata (milliseconds, no external cost)
  T1 medium: perceptual icon hash, permission drift
  T2 expensive: LLM adjudicator, only for records still uncertain or conflicting after T0-T1
Rationale: Most candidates are `unrelated` or clearly `official`; they finish at T0. Target: 5-15% of records reach T2. The actual share is reported by evaluation.
Rejected and why: (a) works but is not producible - the exact trap the brief warns about. (b) blind to conflicting signals.
Status: active

## K-004: Git workflow
Decision: Trunk-based. `main` always runs; short-lived `feat/*`, `exp/*`, `docs/*` branches; Conventional Commits; tags at milestones (`v0.1-schema`, `v0.2-discovery`, ...).
Rationale: Long-lived method branches diverge and cause merge pain. Abandoned experiments keep their branch as evidence and are recorded below.
Status: active

## K-005: Evaluation set before the system
Context: No labelled data is provided. Without measurement there is no way to know whether a change helps.
Decision: Build a 60-80 record, hand-labelled evaluation set with written rationale per record before writing triage code. Layers: easy impersonation, homoglyph, brand ecosystem apps, legitimate third-party tools, repackaged, noise, genuinely ambiguous. A separate 15-20 record holdout stays locked (git-ignored) until final measurement.
Rationale: An easy set measures nothing; the brief says so explicitly. The locked holdout is the rehearsal for the unseen records in the demo.
Status: active

## K-006: Grey-zone routing has two triggers
Context: "Ask the LLM when the score is in between" is correct but incomplete.
Decision: A record is sent to T2 if (a) its score falls in the grey band, or (b) high-trust signals conflict (for example name similarity 0.9 but publisher is established). T2 receives the list of conflicting signals, not just a number. T2 output re-enters scoring as one more signal; the deterministic layer makes the final call.
Rationale: Two records can share a score for very different reasons; the LLM adds value by weighing the conflict, not by reading a number. LLM confidence values are not calibrated, so the false positive target cannot be delegated to it, and determinism keeps results reproducible.
Rejected and why: LLM as final decider - uncalibrated, non-reproducible, larger injection surface.
Status: active

## K-007: Icon combination rule and red-team LLM
Decision: Icon similarity alone stays low weight. The combination icon match + young account + unknown publisher is treated as a strong signal in T0. An LLM acting as attacker generates adversarial name variants; the share caught by the query expander is reported as a coverage metric.
Rationale: A single attacker-controlled signal is cheap to fake, a combination with account age is not. Red-teaming is the cheapest way to avoid limiting the evaluation set to our own blind spots.
Status: active

## K-008: Confusable folding via a curated map, not confusable_homoglyphs
Context: Homoglyph attacks (Cyrillic/Greek letters that look Latin) must fold to a canonical form for both attack detection and legitimate-variant matching.
Options: confusable_homoglyphs library, unicodedata NFKC/NFKD, a curated map derived from Unicode UTS #39.
Decision: A curated map of the confusables actually used against Latin/Turkish brand names, plus NFKC and Turkish flattening, in src/brandguard/discovery/normalize.py.
Rationale: The library answers "what could this be confused with" (detection, one-to-many, noisy) but we need the reverse, "fold this to its Latin target" (normalization, many-to-one). NFKC alone does not touch Cyrillic or Greek letters because they are valid distinct letters, not compatibility forms. A curated map is small, fully under our control, adds no dependency, and can be swapped for the full Unicode table without changing callers.
Rejected and why: confusable_homoglyphs - wrong direction and noisy output. Pure NFKC - does not fold Cyrillic/Greek at all (verified).
Status: active

---

# Tried and Abandoned

| Tried | Observed | Why dropped / what replaced it | Branch | Phase |
|---|---|---|---|---|
| _(empty)_ | | | |
| confusable_homoglyphs library | Maps a char to all its look-alikes (one-to-many), not to a canonical target | Replaced with a curated confusables map for normalization | (no branch, removed before commit) | Discovery | |

---

# Known Weaknesses

_(filled after evaluation; every misclassified record is listed here)_

---

# With One More Month

_(written before submission)_
