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

## K-009: Name similarity is multi-dimensional, not a single score
Context: Measured across the evaluation set, no single fuzzy metric separates official from impersonation; an exact-brand name appears under official, impersonation and repackaged alike.
Options: single ratio with a threshold, weighted blend of metrics into one score, or a structured multi-field signal.
Decision: compare_name returns NameSimilarity with jaro_winkler, token_set, starts_with_brand, contains_brand and exact_skeleton. Triage reads them together; the name signal never decides a label alone.
Rationale: The name tells us how a candidate resembles the brand, not whether it is legitimate. Collapsing to one number destroys the position and skeleton information that later signals need. JaroWinkler chosen for the scalar because it is most consistent on typosquats and homoglyphs after normalization; token_set complements it for suffix/word-order cases.
Rejected and why: Single ratio - conflates mid-name mention (third-party) with leading brand (impersonation). Blended score - hides the dimensions that resolve conflicts.
Status: active

## K-010: Cheap noise filter validated against recall
Context: T0 must drop unrelated noise cheaply, but must not drop real threats.
Decision: is_noise = jaro_winkler < 0.60 and brand not contained. Verified on the bank set: 3 of 27 dropped, none of them official/impersonation/repackaged.
Rationale: A cheap filter is only safe if it provably costs no recall. The check is part of the test suite intent and re-run whenever the set changes.
Status: active

## K-011: Bounded query expansion with measured coverage
Context: Literal marketplace search misses altered names. Expansion must widen recall without exploding into thousands of noise terms.
Decision: expand() produces deduplicated queries across strategies (exact, normalized, homoglyph, turkish, leet, typosquat, spacing, suffix), each capped. For the bank profile this yields ~43 queries.
Rationale: Coverage measured on the evaluation set: without leet, 90% of impersonation/repackaged surfaced; adding a small high-confidence leet map (0,1,3,4,5,7,8,9) closed the last miss ("ornek 8ank") for only four extra queries, reaching 100%. The cost/benefit was measured, not assumed.
Rejected and why: Unbounded typo generation - thousands of terms, mostly noise no store indexes and no attacker uses. Digit substitution beyond high-confidence swaps - poor cost/benefit.
Known limit: coverage is measured against a substring model of search, not a live engine; real recall depends on store indexing.
Status: active

## K-012: Multigraph substitutions, added with a matching test case first
Context: Multi-character lookalikes ("rn"->"m", "vv"->"w") are genuine, visually strong impersonation techniques not covered by single-character maps.
Decision: Add a small bidirectional multigraph map to query expansion. Before adding the generator, a multigraph impersonation record ("Omek Bank Mobil") was added to the evaluation set so the feature could be validated, not merely asserted.
Rationale: Measured cost is tiny (0-2 variants per brand, since multigraphs occur rarely in a name) and coverage of the new attack is confirmed at 100%. Adding a feature without a case that exercises it would be an unmeasurable claim.
Rejected and why: Adding the generator without a test record - would let us claim coverage we could not demonstrate.
Status: active

## K-013: Adapter protocol with shared value-parsing
Context: Sources return different schemas (flat, nested, terse third-party). Triage must be source-agnostic.
Options: one parser per source with duplicated logic, or a shared protocol plus reused value parsers.
Decision: A SourceAdapter Protocol with one parse() per source; value-format conversions (downloads, dates, permissions) live in parsing.py and are shared. A registry maps source name to adapter; adding a source is one class.
Rationale: Field mapping is source-specific and belongs in the adapter; value formats ("1,000+", epoch, "1K") recur across sources and belong in one place. Helpers fail soft to None so one bad field never drops a record, preserving the missing-vs-zero distinction.
Rejected and why: Per-source parsers with copied conversion code - drift and duplicated bugs. A single mega-parser with if/source branches - unreadable and hard to extend.
Status: active

## K-014: Veto trusts publisher identity, not publisher name (defense in depth)
Context: The first veto matched publisher names on normalized forms. Testing on our own set, an impersonator set its publisher name to the flattened official name ("Ornek Bank A.S" == "Örnek Bank A.Ş." after normalization) and was wrongly forced to official. The publisher name is attacker-controlled.
Options: exact-match only (loses legitimate store flattening), name match plus an independent verifier, or require the store verified flag.
Decision: Official veto requires the normalized name to match AND at least one verifier the attacker cannot cheaply forge: store-verified flag, publisher website under an official domain, or account age predating an established-brand cutoff. Name match alone does not veto; such records fall through to scoring.
Rationale: Trust belongs to identity, not to a string. The verifier set is defense in depth: any one suffices, and all are hard to fake under the threat model's phishing economics. Verified on the set: the impersonator no longer vetoes, real official records still do, repackaged still fires.
Rejected and why: Exact match only - drops legitimate Turkish-flattened publisher names (App Store case). Verified-flag only - not all legitimate publishers carry the flag on every store.
Status: active

## K-015: Scored signals return uniform results; fusion is saturating, not additive
Context: T0 must combine name similarity, account age, developer history and permission drift into one decision without any single attacker-controlled signal deciding alone.
Decision: Each signal returns a SignalResult (direction, strength, evidence). Fusion combines suspicious strengths with a saturating rule (each closes part of the remaining gap to 1) and applies conservative bands: high impersonation threshold (0.60), wide uncertain middle. Account age is graded (young/neutral/established), not binary. Permission drift is sector-aware (a courier reading SMS is routine; a bank is not).
Rationale: A bare sum lets three weak signals cross a threshold that no one signal should; saturation prevents runaway and keeps a lone signal below the impersonation line. Grading account age fixed false conflicts where a merely non-fresh account looked legitimate against a strong red flag. Sector awareness prevents cross-sector false positives.
Status: active

## K-016: unrelated vs third_party is semantic; T0 uses coarse-to-fine with a safe default
Context: Investigated on the set: no attacker-independent field separates unrelated (generic ATM directory) from third_party (bank-account aggregator). Name tokens and package ids overlap in both. The true distinction is semantic and needs T2.
Decision: T0 makes the coarse call it can prove (threat vs benign) with high confidence, then splits benign into unrelated vs third_party by objective brand relation (brand token in name or package id) at low confidence (0.65). Description text, being attacker-controlled, is never used. Fine calls can be escalated to T2.
Rationale: Forcing a semantic distinction from cheap signals would either guess or misuse attacker-controlled text. Coarse-to-fine with abstention is the honest engineering choice. Verified: zero threats labelled benign; remaining errors are benign-family confusions (low cost) or escalations.
Known limit: two unrelated records that share only the generic token "örnek" land in uncertain; recorded as a known weakness for T1/T2 rather than forced by tuning thresholds to two records.
Status: active

## K-017: Token alignment separates typosquat from single-token noise
Context: A whole-string metric (Jaro-Winkler) could not separate "Omek Bank" (a multigraph impersonation, jw 0.653) from "Örnek Oyun" (search noise sharing only the generic token "örnek", jw 0.668). They score almost identically.
Decision: Added token_alignment to NameSimilarity: the mean, over brand tokens, of each brand token's best Jaro-Winkler match among the candidate's tokens. is_noise treats a name as noise only when brand-token coverage is incomplete AND alignment is below 0.85. A typosquat stays close to every brand token; noise matches one and drops the rest.
Rationale: The distinction is structural (does the candidate preserve the whole brand token sequence, even if distorted) not global-string. Measured: typosquats align 0.90+, single-token noise 0.82. Zero threats fall to noise after the change.
Note: this makes is_noise treat ecosystem sub-brands ("Örnek Yatırım") as name-noise too; they are rescued by the publisher veto, which runs first. Recorded as an ordering dependency.
Status: active

## K-018: Impersonation requires a strong attacker-independent signal, else escalate
Context: A logistics record ("Hızlı Kargo Takip") reached score 0.768 from weak signals only (name shape, solo publisher, permission guess with no official baseline) and was labelled impersonation, though its gold label is uncertain. Raising the threshold would overfit to one record; changing the gold label to match the system would corrupt the test set.
Decision: An impersonation decision at T0 requires at least one strong attacker-independent signal: a young account, or permission drift measured against a KNOWN official baseline. A high score built only from weak or attacker-controllable signals escalates to T2 instead of being decided (reason "unbacked_high").
Rationale: This is the threat model's core rule ("every impersonation must be backed by a signal outside attacker control") applied to the escalation gate, not just the score. It generalizes: a real impersonation with a young account still fires; a merely suspicious record with weak backing defers. It fixed the false positive without touching thresholds or the gold label.
Rejected and why: Relabel to impersonation - grading the system against itself, invalid. Raise threshold - overfits to one point, risks missing real threats.
Status: active

## K-019: Icon similarity via perceptual hash, real algorithm on synthetic fixtures
Context: T1 needs visual comparison of a candidate icon against the official icon, but we have no real logo files and generating fake logos adds no engineering value.
Options: real imagehash on synthetic fixtures, a fully mocked hash interface, or full pHash with generated realistic logos.
Decision: Use the real imagehash library (local, free, no API cost) and generate synthetic test icons via scripts/make_test_icons.py (official, near-copy, recolour, unrelated). Icon similarity is a T1 signal that runs only for undecided records with an icon, and is supporting evidence, never a veto.
Rationale: The algorithm is real and verifiable at zero cost; only the data is synthetic, because real logos are expensive to source and add nothing to validation. Running pHash on every record would waste the cascade budget. An icon is attacker-controllable, so it cannot decide a label alone.
Known limit: pHash is structure-sensitive and colour-insensitive; a same-layout recolour still reads as similar (validated by the recolour fixture). Recorded and tested as documented behaviour, not hidden.
Rejected and why: Mocked hashes - would not prove the system can actually do visual comparison, near the "don't fake work" line. Generated logos - cost without validation value.
Status: active

## K-020: T1 shares the decision rule with T0; icon is supporting, not backing
Context: T1 must add richer evidence (icon similarity) to records T0 left undecided, without duplicating the label logic or letting an attacker-controllable signal decide.
Decision: Extracted the post-veto decision into _decide_from_signals, shared by T0 and T1. T1 runs only for escalated records with an icon, appends the icon signal, and re-runs the shared rule with tier=1. Icon similarity is explicitly excluded from the "strong attacker-independent" backing that K-018 requires; a copied icon plus a young account resolves to impersonation, a copied icon alone does not.
Rationale: One decision rule in one place prevents T0 and T1 from drifting apart. Spending T1 cost only on escalated records with an icon keeps the cascade economical. Treating the icon as supporting-only is consistent with the threat model: an icon is attacker-controllable.
Status: active

## K-021: T2 adjudicator behind one interface; injection-safe case summary
Context: T2 must resolve semantic cases (K-016) with an LLM without exposing the false-positive budget or the prompt to attacker control.
Decision: An Adjudicator protocol with two implementations: AnthropicAdjudicator (real API, key from environment) and RuleAdjudicator (deterministic stand-in for tests and keyless runs). The model receives only a structured CaseSummary built from facts our own code computed; attacker text is reduced to bounded booleans (claims-official, names-brand) and never quoted. The opinion re-enters fusion as a dampened signal (max strength 0.5) so it cannot cross the impersonation threshold alone. A benign leaning may settle the unrelated/third_party split; that is the language judgement T2 exists for.
Rationale: Ports-and-adapters keeps the pipeline testable everywhere and demo-safe offline. Structured facts close the injection surface: tests prove no attacker sentence survives serialization and neither injection direction flips an outcome. Dampening keeps the deterministic layer in charge of the FP budget (K-006).
Status: active

## K-022: Negation-aware official-claim detection
Context: The claims-official fact matched the word "resmi" alone, so the honest disclaimer "Resmi uygulama degildir" registered as a claim of officialness and pushed a legitimate locator toward impersonation.
Decision: The fact is affirmative-only: an official-word match is cancelled by a nearby negation (degildir/not official/unofficial).
Rationale: A disclaimer is the opposite of a claim; treating them alike manufactures false positives exactly where honest third parties are most careful.
Status: active

## K-023: Benign settle is blocked by sensitive permissions; two kinds of uncertainty
Context: Live run with the OpenAI adjudicator settled the apkmirror mirror record (gold: uncertain, READ_CONTACTS, no publisher data) as third_party on a benign leaning. Had it been a real repack, a threat would have been labelled benign.
Decision: T2's benign-settle authority applies only to semantic ambiguity. A record requesting sensitive permissions is never settled benign on the adjudicator's word; it ends uncertain. Separately, a configured API key with a missing SDK now fails loudly with an install hint instead of silently falling back to the rule adjudicator.
Rationale: Two kinds of uncertainty must not be conflated: semantic ambiguity (evidence exists, interpretation needed) is what a language model resolves; absence of evidence (no signature, no publisher data) is not, because reasoning cannot fill a missing fact. A concrete risk marker (sensitive permission) outweighs a language judgement. Validated: legitimate settles (API Sample, locator) carry no sensitive permissions and still settle; the mirror stays uncertain. Silent fallback was rejected because the operator would believe the model is in use while it is not.
Rejected and why: Trusting the model's benign call unconditionally - lets a language opinion cancel a concrete risk marker.
Status: active

## K-024: Official evaluation uses the deterministic adjudicator; confidences recalibrated from measurement
Context: Metrics must be reproducible, and the first calibration table caught the system overstating confidence: the 0.6-0.8 bin claimed 0.65 and achieved 0.33.
Decision: scripts/evaluate.py runs the cascade with RuleAdjudicator so numbers are identical run to run; the live model is validated separately with run_cascade.py. Benign-split confidences were lowered to what measurement supports (0.5 for the T0 split, 0.55 for adjudicated settles), moving those decisions into a bin where stated 0.509 matches actual 0.455.
Rationale: An LLM is non-deterministic; metrics computed through it are snapshots, not measurements. A confidence number is a promise to the analyst about how often the system is right; the calibration table showed the promise was broken for the benign split, and the honest fix is to state the uncertainty we actually have, not to invent precision.
Known limits recorded with the numbers: the unrelated class collapses into third_party (benign-family confusion, zero takedown cost, K-016); T1 shows zero usage in evaluation because test records carry no icon files.
Status: active

## K-025: Balanced logistics set; locked holdout run once
Context: The logistics set had no adversarial layers (9 records, no L3-L7/L11); and the brief requires a held-out check on unseen records.
Decision: Added L3-L7 and L11 adversarial logistics records (red-team style, homoglyph verified) bringing it to 16, all layers represented. Wrote an 8-record locked holdout for the bank brand, biased to the hard layers, kept git-ignored and never consulted during development, then evaluated exactly once.
Results (locked holdout, single run): 6/8 exact, takedown FP 0/2 = 0.0%, missed threats 0/2 = 0.0%. The two misses are both the unrelated<->third_party benign-family confusion (zero takedown cost), independently reproducing the known weakness from the development set. Development set (44 records): takedown FP 0%, missed threats 0%, impersonation precision 1.0 recall 0.938, cost 84% decided at T0.
Rationale: The holdout confirms the system generalizes (same behaviour on unseen records) and that its one real weakness is the cheap-tier semantic split, exactly where it was predicted. The single missed-in-recall impersonation ("Puan Kazan", 7-month account, no strong independent signal) defers to uncertain rather than forcing a call; that is K-018 working, not a failure.
Status: active
## K-026: Leading typosquats recognized as starting with the brand (evidence correctness)
Context: A live run showed "Örnek Bankk Mobil" described in its evidence as "mentions the brand but does not lead with it", although it clearly leads with a typosquatted brand. The verdict was still impersonation (other signals carried it), but the analyst-facing evidence was wrong and the name signal contributed as neutral instead of suspicious.
Decision: starts_with_brand matches the leading tokens against the brand tokens with a high fuzzy threshold (Jaro-Winkler >= 0.85) when they are not identical, so a distorted brand prefix counts as leading. Exact match stays the cheap common path.
Rationale: The output exists to give an analyst correct facts; a misleading evidence line is a real defect even when the label is right. Verified: the fix corrects the evidence with zero change to the metric dashboard (FP 0%, recall 0.938, 84% at T0) and no regression on mid-name mentions or ecosystem sub-brands.
Status: active

---

# Tried and Abandoned

| Tried | Observed | Why dropped / what replaced it | Branch | Phase |
| Word-match official-claim detection | 'Resmi uygulama degildir' (a disclaimer) counted as claiming official | Negation-aware detection (K-022) | feat/tier2 | Triage |
|---|---|---|---|---|
| _(empty)_ | | | |
| | Name-only unrelated detection | Marked ecosystem and typosquats as noise | Replaced with objective brand relation + token alignment (K-016, K-017) | feat/triage-fusion | Triage |
| | Binary account age (young/old) | A 6-month account read as legitimate, forcing real impersonations to uncertain | Made it graded young/neutral/established (K-015) | feat/triage-fusion | Triage |
| | Single Jaro-Winkler for noise detection | Could not separate 'Omek Bank' (threat) from 'Örnek Oyun' (noise), near-equal scores | Added token_alignment (K-017) | feat/triage-fusion | Triage |
| Normalized publisher-name veto (no verifier) | An impersonator spoofed the flattened official name and was forced to official | Replaced with identity-verifier veto (K-014) | feat/triage-t0 | Triage |
| confusable_homoglyphs library | Maps a char to all its look-alikes (one-to-many), not to a canonical target | Replaced with a curated confusables map for normalization | (no branch, removed before commit) | Discovery | |

---

# Known Weaknesses

- T0 lands two unrelated records sharing only the generic token "örnek" in uncertain instead of unrelated. Low cost (no threat missed); deferred to T1/T2.
- T0 confuses unrelated with third_party in the benign family (semantic distinction); intended to be resolved by T2.
- unrelated vs third_party: the cheap tiers cannot separate these (semantic, K-016); measured as unrelated precision/recall 0.0 on the dev set, both benign-family, zero takedown cost. Deferred to T2/a future classifier.
- One logistics impersonation ("Puan Kazan") defers to uncertain instead of impersonation: a 7-month account with no strong attacker-independent signal; correct per K-018, recall cost accepted for precision.
- T1 (icon) shows zero usage in offline evaluation because test records carry no icon files; validated separately with synthetic icons.
- Live LLM (OpenAI) agreement 23/28 on the bank set; all disagreements benign-family.

---

# With One More Month

_(written before submission)_

The single most valuable month would go to the one measured weakness, not to new
features.

1. **A learned classifier for the unrelated/third_party split.** This is the only
   error the evaluation shows (unrelated precision/recall 0.0 on the dev set,
   reproduced on the holdout). It is semantic and the cheap tiers provably cannot
   make it (K-016). I would label a few hundred real listings, train a small
   text classifier on the description and name, and use it as a T1 signal so T2
   is reserved for genuinely hard cases. This is bounded, measurable work with a
   clear success metric.

2. **Signature and certificate checks for repackaged detection.** Today the
   package-id veto and the mirror ambiguity (the L10 case that stays uncertain)
   both really want APK signature comparison. With signatures, "official app from
   an unofficial publisher" becomes a certainty rather than an inference, and the
   uncertain mirror resolves. This closes the largest genuine information gap.

3. **Real discovery against one live source, rate-limited.** The query expander's
   coverage is measured against a substring model of search, not a live index
   (K-011 known limit). Wiring one real marketplace behind the existing adapter
   interface would replace an assumption with a measurement, and would surface
   the discovery blind spots (e.g. the "HK Esnaf" abbreviation case) that the
   mock cannot.

4. **Calibration on more data.** Confidence is calibrated against tens of
   records; the high-confidence bin is trustworthy but the middle bins are thin.
   More labelled data would let me fit and validate a proper calibration curve
   instead of the honest-but-coarse table used now.

5. **Cost and latency instrumentation in production shape.** The cascade's cost
   claim (84% decided at T0) is measured offline. In production I would add
   per-tier timing and a cache keyed by app_id+version so a record is never sent
   to T2 twice, and report real cost per thousand records.

What I would NOT spend the month on: more marketplace adapters (the interface
already makes them cheap), more query-expansion strategies (coverage is already
100% on the set; the bottleneck is discovery against a real index, not more
transforms), or a larger LLM (the adjudicator is not the accuracy bottleneck;
the deterministic layer and the missing signature data are).

