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

## K-027: Generalization demo on an unseen sector (crypto)
Context: The system should not be memorizing the banking and logistics cases it was built against; generalization needs to be demonstrated, not asserted.
Decision: Added a crypto brand profile and seven records (in no training or eval set) under data/demo, plus a test locking the safety-critical invariants. Adding the sector required one line in _SECTOR_EXPECTED; everything else is sector-agnostic.
Rationale: Crypto is a high-value phishing target, so it is a realistic stress test (airdrop scam, seed-phrase lure). The run shows the cascade applying crypto permission expectations (SMS is a red flag for a wallet), catching a homoglyph and a repackaged mirror, and protecting a legitimate price tracker and a themed game from takedown, all on unseen input. The test asserts invariants (no threat labelled benign, no legitimate tool flagged) rather than exact labels, since some records sit on the benign-family boundary only T2 fully resolves.
Status: active

## K-028: Optional live Google Play source behind the adapter interface
Context: Test data so far is hand-built. The question "can this run on real data" deserves a concrete answer, and the adapter interface (K-013) was designed exactly so the source could be swapped without touching triage.
Decision: Added src/brandguard/discovery/live_google_play.py (real scraper results -> AppRecord) and scripts/scrape_and_triage.py (expand queries, scrape, dedupe, triage, list takedown candidates), as an optional ".[live]" dependency. Triage is unchanged; only the source differs.
Rationale: This proves the mock-to-live path is real, not hypothetical. Live data omits fields our signals would like (publisher account age, verification); those stay None and the signals abstain, which is the missing-vs-zero discipline from schema.py earning its keep on real input. The scraper is unofficial and may be rate-limited or blocked; failures are surfaced per query, not hidden, and the mapping is unit-tested offline while the network call is exercised manually.
Known limit: without account-age and verification, the strongest attacker-independent signals are weaker on live Play data than on a source that exposes them; recorded as a reason the veto and impersonation gates are more conservative there.
Status: active

## K-029: Live-data hardening (real Play crashed the first adapter)
Context: Running scrape_and_triage.py against real Google Play surfaced two failures the mock data never showed: some queries died with ValidationError/TypeError because real listings return string ratings, float versions, non-string ids, and malformed emails, and a single bad listing was dropping its entire query's results.
Decision: Per-record isolation in the adapter (one unmappable listing is skipped, not the whole batch) plus defensive coercion in _detail_to_record (unexpected types become None rather than crashing the schema). Added tests reproducing the real-data quirks offline.
Rationale: Real data is inconsistent in ways hand-built mocks are not; the adapter is the boundary where that inconsistency must be absorbed so triage never sees a malformed record. Losing one listing is acceptable; losing a query or crashing is not. This is the adapter interface (K-013) doing its job under real conditions.
Observed on live data: no impersonation labels for the synthetic "Örnek Bank" (no real impersonator exists, and the scraper omits account age and verification, so the strongest attacker-independent signals are absent and the system stays conservative, consistent with K-028). Real brands ("Ziraat Mobil") map and triage correctly.
Status: active

## K-030: Live-run polish from real output (query-skip message, empty-id filter)
Context: A real "Ziraat" run showed two rough edges: a query still failed with a bare "TypeError" (Google Play raising from inside the scraper on an exotic homoglyph variant), and one listing reached the output with an empty app_id.
Decision: The query-level handler now prints a human-readable skip line explaining that Play returned an unexpected response, instead of a bare exception name; and records with no app_id are dropped before triage, since an analyst cannot act on an unidentifiable listing.
Rationale: The scraper failure is inherent to an unofficial interface and is already isolated per query (the run continues with the other queries), so the fix is clarity, not suppression. An empty-id record is not actionable output. Both changes came from reading real output, not from the mocks, which is why they surfaced only after the live run.
Status: active

## K-031: Review signal via consistency, not content (closing the one deliberate gap)
Context: The brief lists user reviews among the available signals; we had deliberately skipped them because review text and counts are attacker-controllable (reviews can be bought). This closes that gap without opening an injection surface.
Decision: Added review_consistency_signal. It never reads review text and does not trust the raw count. It fires only on a pattern an attacker cannot cheaply fake: a large claimed install base (>=100k) with a review ratio under 0.01% and a near-perfect rating (>=4.8), which is how bought-review inflation looks against organic behaviour. Weight is 0.25 (cannot decide a label alone) and it abstains whenever downloads or reviews are missing. A test impersonation record exercising the pattern was added first (K-012 discipline).
Rationale: The honest way to use an attacker-controlled signal is to key on the inconsistency the attacker leaves behind, not on the content they author. Verified: fires on the inflated pattern, abstains on legitimate large apps, small apps, missing data, and merely-few-reviews-without-perfect-rating. Metrics unchanged (FP 0%, recall 0.938); it adds coverage without disturbing existing decisions.
Rejected and why: reading review text/sentiment - attacker-authored, injection surface; trusting raw review count - trivially inflated; sudden-spike detection - needs review timestamps neither the mock nor the scraper provides.
Status: active
## K-032: Package veto must not fire when the publisher name is itself official
Context: On live Ziraat data, an official app (official package id com.bankkart.mobil, publisher "T.C. Ziraat Bankası A.Ş.") was wrongly labelled repackaged and flagged for takedown. Its publisher had no website on an official domain, so the publisher veto did not fire for lack of a verifier (K-014), and the package veto then concluded "official package, non-official publisher" even though the publisher name matched the official list.
Decision: check_package_veto now returns None when the normalized publisher name matches the official publishers, regardless of verifier. Repackaged is specifically an official package under a DIFFERENT publisher; a matching name means unverified identity, not a foreign repackager.
Rationale: This was a real false positive against a legitimate app, the exact error the 5% constraint targets. Verified: Bankkart no longer flagged (falls through to triage), while a genuine repackaged (official package, foreign publisher like "ModApps") still fires. Surfaced only on live data, where publishers often lack an on-domain website, which the mock always had.
Status: active

## K-033: Watchlist scanning with timestamped, tracked results
Context: Beyond one-off runs, a real DRP system scans many brands regularly and tracks change over time. We wanted the same: several major banks, timestamped results, the platform recorded, and run-to-run comparison.
Decision: scripts/watchlist_scan.py scans every profile in data/watchlist against a named platform (google_play), writes one timestamped JSON per brand (results/<UTC>__<brand>__<platform>.json), and appends a summary row to results/run_log.csv. scripts/watchlist_diff.py compares two scans (new, gone, changed verdicts). GitHub policy: raw result JSON is git-ignored (real publisher data, grows over time), only run_log.csv (non-sensitive summary) and a hand-picked demo run under docs/sample_runs are committed.
Rationale: The timestamp answers "when did we look", the platform field answers "where", and the diff answers "what changed". Committing the summary but not the raw data shows a real scanning history without exposing real publisher data or bloating the repo. Live data is fetched via the google-play-scraper source (K-028), so each scan is a snapshot of that moment, which is exactly why timestamping matters.
Known limit: Google Play is well policed, so scans of real banks are mostly official/third_party; the value is demonstrating live, multi-brand, timestamped, trackable scanning, not that a takedown target will always appear.
Status: active

## K-034: Serper source for third-party app hunting via Google search
Context: Google Play is well policed, so real impersonations live on third-party APK sites, not Play. The CTO suggested driving discovery through Google search (Serper).
Decision: Added a Serper source (src/brandguard/discovery/serper_source.py) that runs APK-hunting Google dorks (excluding Play), turns each organic result into an AppRecord by inferring a package id from the URL and a name from the title, and feeds them through the existing cascade. Behind a SerperClient protocol with a mock for tests; optional ".[serper]" extra; SERPER_API_KEY read from .env.
Rationale: This looks where impersonations actually live. A search hit is far poorer than a Play listing (no publisher, permissions, age), so those stay None and the system is deliberately more conservative. The adapter interface (K-013) made this a new source with zero change to triage. A live Ziraat run returned 36 candidates across Aptoide, APKMirror, Uptodown and others, all correctly triaged as third_party or unrelated except one bug (K-035).
Status: active

## K-035: Empty publisher is unknown identity, not a foreign repackager
Context: On live Serper data, an official Ziraat package (com.ziraat.basakdijital) was flagged repackaged and takedown, because a Google search hit carries no publisher, so the package veto read the empty publisher as "not the official one". A false positive against a real official app, the exact error the 5% cap targets.
Decision: check_package_veto returns None when the normalized publisher name is empty OR matches the official list. Empty means unknown identity; unknown is at most uncertain, never a takedown. This extends K-032 (matching-but-unverified name) to the empty case.
Rationale: An absent identity cannot justify a takedown. Verified across four scenarios: empty publisher no longer flagged; a genuine repackaged (official package, real foreign publisher like "ModApps") still fires; official name without verifier stays unflagged; official name with a domain verifier is official. Surfaced only on live search data, where hits have no publisher, which the mocks and Play always had.
Status: active

## K-036: Website-impersonation discovery, phase 2a (domain similarity only)
Context: Phishing sites live on lookalike domains, often a bigger problem than fake apps. The CTO's Serper direction supports this, and the goal was to cover every avenue.
Decision: Added domain_variants.py (generate typosquat/leet/lure-word/alt-TLD variants of the official domain) and website_hunt.py (classify a domain against the official ones by similarity: official, lookalike, mentions, unrelated; discover via generated variants plus Serper searches off the official domain). DomainFinding carries confirmed_live to separate a domain a search actually returned from a generated name whose registration is unknown. WHOIS/SSL/page-content are defined as an extension point (WebsiteSignal) but NOT implemented; this phase uses only domain similarity.
Rationale: Discovery is broad (a missing variant is a domain we could never flag) but triage is honest about its one signal: a string-only comparison flags a lookalike for review, it does not assert phishing. A lookalike requires both high similarity AND the distinctive brand token, so a rival bank sharing "bank" is not flagged, while a leet-distorted brand prefix (z1raatbank) still is. confirmed_live prevents overclaiming.
Rejected and why: Implementing WHOIS/SSL/content now - each is a separate integration, a project-sized extension that would pull effort off the core. Flagging every generated variant as a hit - dishonest, registration is unknown.
Status: active

## K-037: Domain verdicts are separate from app labels
Context: A domain compared only by string is not the same object as an app with publisher, permissions and age.
Decision: website_hunt uses its own DomainVerdict (official/lookalike/mentions/unrelated), not the app Label.
Rationale: Using the app label would overclaim certainty the domain signals do not support. Separate vocabularies keep each pipeline honest about what its evidence proves.
Status: active

## K-038: Domain cascade D1 (WHOIS age + SSL), soft-failing, live lookalikes only
Context: Phase 2a flagged lookalike domains by string similarity alone. The strongest attacker-independent website signal is registration age (a phishing domain is days old), mirroring account age on apps.
Decision: Added domain_signals.py (whois_age via python-whois, cert_age via stdlib ssl) and enrich_live_lookalikes in website_hunt.py. D1 runs ONLY on live lookalikes (confirmed_live and verdict lookalike), assigns a review priority (young domain high, established low, unknown medium), and both signals fail soft to None on any WHOIS/TLS error. Optional ".[whois]" extra; SSL uses the standard library.
Rationale: Registration age is the domain equivalent of account age and orders the analyst queue so young lookalikes surface first. Running D1 only on live lookalikes keeps the network cost on the few domains where it matters, the same cascade economics as the app tiers. Soft failure is essential: WHOIS is inconsistent across TLDs (especially .com.tr) and rate-limited, so an unavailable signal is absent, never guessed.
Rejected and why: Running WHOIS/SSL on every candidate - wasteful, most are generated names with no registration. A paid WHOIS API - unnecessary for age alone, which the free library usually provides.
Status: active

## K-039: Domain cascade D2 (AI adjudicator), minimal, injection-safe
Context: Some live lookalikes remain ambiguous after D1 (young or unknown age). A language model can judge these, but only carefully.
Decision: Added domain_adjudicator.py: a DomainAdjudicator protocol with a deterministic RuleDomainAdjudicator default and an LLM-backed path reusing the app-side provider selection. The model receives only a structured DomainCase (similarity, ages, issuer, booleans), never a raw page; fetching the live page is optional and off by default, since connecting to a suspected phishing site is sensitive. D2 runs only on the few D1 could not settle.
Rationale: This is the domain mirror of app T2 (K-021): ports-and-adapters, deterministic fallback so it runs without a key, structured-only input to close the injection surface, and advisory output rather than automated takedown. AI is used last and least, the cheap-first expensive-rarely cascade principle applied to domains.
Rejected and why: Sending the raw page to the model - injection surface and a security risk on a phishing site. Auto-fetching every page - risky and slow; kept optional and off by default.
Status: active

## K-040: Certificate issuer as a weak priority nudge, age still dominates
Context: On the real Ziraat run, two legitimate subsidiary domains (ziraatbank.az, ziraatbank.de) sat at medium priority because WHOIS was unavailable for those TLDs, even though each had an old certificate from a paid CA (DigiCert). The analyst queue could be sharper.
Decision: cert_age now records whether the issuer is a free CA (Let's Encrypt/ZeroSSL, the phisher's usual choice) or a paid/organization CA. enrich_live_lookalikes uses this only as a weak nudge: an old paid-CA certificate with unknown domain age lowers priority to low; a young domain or a fresh/free certificate raises it to high. Registration age still dominates when known.
Rationale: This moved the two legitimate subsidiaries from medium to low (out of the urgent queue) while a simulated fresh-domain, free-cert phishing case correctly rises to high. The certificate is deliberately a weak signal, never a decision: an attacker can buy a paid certificate too, so a young domain still overrides a good certificate. Consistent with the threat model, no attacker-obtainable signal decides alone.
Rejected and why: Treating a paid CA as proof of legitimacy - an attacker can obtain one; it only nudges when the stronger age signal is missing.
Status: active

## K-041: Certificate Transparency (crt.sh) as the deepest lookalike source
Context: Play, Serper and generated variants had not surfaced a confirmed real impersonation, because those sources are shallow (a well-policed store, the first page of search). Proof that the system catches a genuine lookalike was missing.
Decision: Added crtsh_source.py (query crt.sh for the brand's distinctive token, return every domain that ever obtained a certificate containing it) and scripts/crtsh_hunt.py (classify those domains through the existing domain cascade: D0 similarity, then D1 whois/ssl priority). No API key, no cost; fails soft to an empty list on any error. CT-observed domains are marked confirmed_live, since a certificate proves the domain exists.
Rationale: A phishing domain appears in CT logs the moment it obtains TLS, before it ranks in a search engine or gets reported, so CT is the richest free source of real lookalikes. It plugs into the domain cascade as a discovery source with no change to classification. Payment and crypto brands are the most productive queries, being impersonated most and cleaned up least.
Rejected and why: Relying on search alone - too shallow, returns the clean first page. Paid threat-intel feeds - unnecessary when CT is free and deeper.
Status: active

## K-042: Unified hunt engine with timestamped, comparable runs across all sources
Context: Four discovery sources (Play, Serper, website, crt.sh) had each grown its own script printing to the screen. That is not how a DRP platform operates: it needs one interface, and every run recorded and comparable over time. The watchlist already did this for Play; the other sources did not.
Decision: Added hunt_engine.py (one run_source over all sources returning a uniform RunResult, plus record_run writing a timestamped JSON per run and a shared results/run_log.csv) and hunt.py (python -m brandguard.hunt --brand X --source crtsh,website). Every run is keyed by ISO UTC timestamp, brand and source, so runs compare across sources and over time; the existing diff tool works on any two result files. Raw JSON is git-ignored, the summary log is committed, same convention as the watchlist (K-033).
Rationale: A single operational entry point is the expert-grade shape, not four divergent scripts. Recording every run with a timestamp is what makes exposure trackable ("this lookalike was not here last week"). The per-source runners are thin wrappers over the discovery modules, so the engine stays agnostic and each source keeps its own logic.
Rejected and why: Patching record-keeping into each of the four scripts - divergent code, four places to maintain. Leaving runs unrecorded - no way to compare over time, which is the point of monitoring.
Status: active

## K-043: crt.sh retry with exponential backoff, distinguishing throttling from empty
Context: On a live run, crt.sh returned nothing for both Binance and PayPal at once, which the old code reported as "0 candidates", the same as "no lookalikes exist". crt.sh is a free service that frequently rate-limits or returns an empty body under load, so a single shot conflates "temporarily throttled" with "genuinely empty".
Decision: search_crtsh now separates retryable conditions (HTTP 429, timeout, empty or garbled body) from a definite answer (data, or a real non-OK status), and retries the retryable ones with exponential backoff (2s, 4s, 8s, three attempts). A definite empty or a real error returns an empty list without pointless retries.
Rationale: This is standard resilience for a flaky third-party service and stops a transient throttle from looking like a clean result. Verified with mocked responses: recovers after two 429s, soft-empties after repeated empty bodies without hanging, does not retry on immediate success, and does not retry a real 503. Backoff is bounded so a run never stalls indefinitely.
Rejected and why: Retrying forever - could hang a run. Treating every non-200 as retryable - wastes time on real errors that will not change.
Status: active

## K-044: Exclude a brand's own subdomains and non-domain strings from lookalikes
Context: A live crt.sh run for PayPal returned 194 candidates, but almost all were PayPal's own infrastructure subdomains (api.paypal.com, stage.paypal.com, sandbox.paypal.com), and one "lookalike" was the certificate organization string "paypal, inc." rather than a domain. Real impersonations were buried under the brand's own hostnames.
Decision: classify_domain now, before similarity, (1) rejects strings that are not valid hostnames (a regex for label.label.tld), so org names like "paypal, inc." become unrelated, and (2) marks any subdomain of an official domain (host == official or endswith "." + official) as official, since api.paypal.com is the brand's own infrastructure, not an impersonation.
Rationale: CT logs are dominated by a brand's own subdomains and occasionally carry non-domain fields; without these filters the lookalike queue is buried in noise. A subdomain of the official domain is definitionally the brand's own, so it cannot be an impersonation. Verified: PayPal's own subdomains become official, "paypal, inc." becomes unrelated, and real phishing shapes (paypal-login.info, paypa1.com) remain lookalike.
Rejected and why: Keeping subdomains as mentions - still clutters the review queue with the brand's own hosts. Trusting the crt.sh name field as always a domain - it is not.
Status: active

## K-045: Structural domain anatomy, so brand+lure domains are caught and brand+neutral are not
Context: A live crt.sh run for PayPal, after removing the brand's own subdomains, left 13 "paypal-something" domains all classified as low-priority mentions. But paypal-login.info is a classic phishing shape while paypalobjects.com is PayPal's real CDN; pure string similarity cannot tell them apart, and both merely "contain paypal".
Decision: Added domain_anatomy.py, which reads a domain's structure relative to the brand token: is the brand at the start, is it paired with a credential-bait word (login/secure/verify/wallet/..., plus Turkish equivalents), is the TLD cheap/abuse-prone (.info/.xyz/.top/...). classify_domain now calls a domain a lookalike when it is either a true typosquat (single-word label within 3 chars of an official label, e.g. paypa1, ziraatbank.com) OR a phishing shape (brand-prefixed AND carrying a lure word). A brand plus a neutral word (paypal-social, paypalobjects) stays a mention.
Rationale: This is how real DRP triage separates the class string distance misses. The lure lexicon is intent-based, so legitimate brand-product and brand-region domains are not promoted, while brand-login style domains are. Verified on the real PayPal set (paypal--login.info to lookalike, paypalobjects.com to mention) with no regression on Ziraat (z1raatbank, ziraatbank.com still lookalike; garantibbva still unrelated). Typosquat length is measured against the official domain label, not the bare token, so the full-name label (ziraatbank) is handled correctly.
Rejected and why: A flat lure-word list without the brand-prefix and TLD structure - would flag login-portal.com that has nothing to do with the brand. Pure string similarity - cannot separate paypal-login from paypalobjects.
Status: active

## K-046: Strip cosmetic host prefixes (www., m.) before structural analysis
Context: After adding domain anatomy (K-045), a live crt.sh run still left www.paypal--login.info as a low mention instead of a lookalike. crt.sh returns hosts with a leading www. (and sometimes m.), which made the first label "www" rather than the brand, so the brand-at-start check failed and the phishing shape was missed. The unit tests had used bare hosts, so this only showed on real data.
Decision: _label_of now strips cosmetic prefixes (www., m., mobile., web.) before any classification, so anatomy and similarity see the registrable host. A www test on the real string was added.
Rationale: These prefixes are not part of the registrable name and must not change the verdict; www.paypal-login.info is the same threat as paypal-login.info. Verified: the real www.paypal--login.info is now a lookalike, the other twelve paypal-* hosts stay mentions, and there is no regression on Ziraat (z1raatbank, www.ziraatbank.com still lookalike; garantibbva unrelated; www.api.paypal.com still official as an own subdomain).
Rejected and why: Stripping only in one code path - the fix belongs in the single host-normalization point so every downstream check benefits.
Status: active

## K-047: Watchlist sweep in the unified hunt, with per-run failure isolation
Context: Recording each run (K-042) worked for one brand and one source at a time. Operating a portfolio means scanning many brands across several sources in one pass, and a single throttled source (crt.sh rate limit) must not abort the whole sweep.
Decision: hunt.py gained --watchlist DIR, which scans every profile in the directory across every requested source (e.g. --source play,serper,website). Each brand-source run is isolated: if one raises, it is logged as skipped and the sweep continues; successful runs are recorded as usual with their timestamp.
Rationale: This is the portfolio-scan shape a DRP platform runs on a schedule. Failure isolation is essential because live sources throttle independently, so 23 of 24 runs still complete and get recorded when one is throttled. Verified with a mocked sweep: a failing source is skipped for every brand while the working source is recorded for all.
Rejected and why: Aborting the sweep on the first failure - one flaky source would waste the whole run. Running sources serially in separate commands - loses the single operational entry point and the uniform record.
Status: active

## K-048: Separate detected threats from generated watch-list names
Context: The website/crt.sh sources report lookalikes, but many are generated variants (akbbank, aakbank) we produced, not domains a source actually found. Counting these as "flagged" inflated the number and blurred "we found this threat" with "an attacker could register this name". A sweep showing "47 flagged" for a brand was misleading.
Decision: Split the flagged count into detected (lookalikes a source actually returned, confirmed_live: real threats an analyst should action) and watch (generated lookalike names, not yet confirmed to exist: an early-warning monitor list). RunResult carries both; the run log has detected and watch columns; the CLI prints "N detected, M to watch". App sources report detected only (no generated notion).
Rationale: Generated variants are valuable as proactive monitoring, a name registered tomorrow is already on the list, but they are not detections and must not be reported as threats. Confirmed-live lookalikes are the real signal. Keeping them in separate columns is honest and matches how an analyst triages: action the detected, monitor the watch. Verified: a live lookalike counts as detected, a generated one as watch, a mention as neither.
Rejected and why: Dropping generated variants entirely - loses early warning before a domain is indexed or certificated. Counting both as one "flagged" number - overstates detections and is the thing that looked inflated in the sweep.
Status: active

## K-049: Known-affiliate allowlist so vetted brand entities leave the detected queue
Context: A live website sweep for Ziraat surfaced ziraatbank.de and ziraatkatilim.com.tr as detected lookalikes. They resemble the official domain and are not on the official-domains list, so the system flagged them, but they are the brand's own legitimate subsidiaries, not impersonations. Reporting them as detections every run is noise an analyst would clear once and never want to see again.
Decision: BrandProfile gained known_affiliates (a list of vetted legitimate domains). classify_domain, after the official and own-subdomain checks, treats a candidate that matches or is a subdomain of a known affiliate as official with the evidence "Known legitimate affiliate (allowlisted)". The parameter is optional and threaded through hunt_websites and the engine, so existing calls are unchanged.
Rationale: This is the allowlist a real DRP tool builds as analysts clear findings: a vetted entity should not re-enter the detected queue. Crucially the allowlist only shields exact affiliates and their subdomains; a real phishing shape (ziraatbank-giris.com) is still a lookalike, and a rival (garantibbva) is still unrelated. Verified both ways. The honest consequence is that bank "detected" counts drop toward zero once affiliates are listed, which is correct: those were never impersonations.
Rejected and why: Hard-coding affiliate patterns in code - every brand differs; it belongs in the profile. Widening the official-domains list to include affiliates - conflates "our domain" with "a related but separate legal entity", which matters for veto semantics elsewhere.
Status: active

## K-050: Broaden website dorks so Serper finds phishing pages without crt.sh
Context: crt.sh throttles heavily, and the primary intent is Google-dork discovery via Serper. The website source had only three dorks (brand + giris/mobil giris/hesap), too narrow to surface many phishing pages.
Decision: build_website_queries now emits ~15 dorks: the brand paired with a Turkish+English credential-bait lexicon (giris, guvenli giris, hesap dogrulama, login, verify account, wallet, ...), plus URL-targeted dorks (inurl:login, intitle+inurl), all excluding the official domains. Serper runs these; crt.sh is not touched.
Rationale: Google-dork discovery is the intended primary path and does not rate-limit like crt.sh. Widening the lure lexicon and adding inurl/intitle targets the pages phishing actually uses (a brand name plus a login path off the official site). Cost scales with dork count, so --max-queries bounds it.
Rejected and why: Relying on crt.sh as the main domain source - it throttles too often for routine use; crt.sh stays as the deepest supplementary source, Serper dorks are the workhorse.
Status: active

## K-051: Expose per-source tuning (max-queries, num, cap) on the hunt CLI
Context: The engine's runners already accepted max_queries, num and cap, but the unified CLI did not pass them through, so a user could not bound Serper cost or crt.sh volume from the command line (--max-queries errored as unrecognized).
Decision: hunt.py now accepts optional --max-queries, --num and --cap and forwards only the ones provided into run_source, leaving the engine defaults in place otherwise.
Rationale: Cost control belongs at the operator's fingertips: the broadened website dorks (K-050) make query count matter, so bounding it from the CLI is necessary. Forwarding only provided values keeps existing behaviour unchanged when the flags are absent.
Status: active

## K-052: Unauthorized-build veto catches modded/cracked apps, spares legit mirrors
Context: On the app side, Serper surfaces third-party listings like "Spotify Premium Mod" and "cracked" builds, but the system labelled them third_party because the publisher field was empty or a mirror. These are real fake apps: unauthorized, modified redistributions of the official app, i.e. repackaged by definition. The hard part is not catching them but not flagging legitimate mirrors (APKMirror carrying the real "spotify-ab" build).
Decision: Added check_unauthorized_build_veto in veto.py, following the package-veto pattern. It fires repackaged when the app NAME or PACKAGE id (never the description) carries a strong build marker (mod, cracked, hacked, patched, nulled, ...) or an explicit unlock phrase (premium unlocked, mega mod, ...), AND the publisher is not official. Strong markers match as whole words so "mod" does not fire on "model"; weak product words (premium, pro, plus) never fire alone, only inside an unlock phrase. Added to the veto chain after publisher and package vetoes.
Rationale: A modded/cracked build is a repackaged app, so the repackaged label is correct. The publisher guard is what keeps legit mirrors safe: an official publisher's build is never flagged however a mirror labels it. Reading markers from name/package only avoids the innocent "no mods needed" description case. Verified: mod/cracked/unlocked builds from non-official publishers become repackaged; official-publisher builds, "premium" alone, and "model" stay untouched. A later refinement (from a live Spotify run) ignores markers when the app_id is a URL rather than a dotted package: a link path like /howto/how-to-download-spotify-mod-apk is an article title, and a marker in a host or path is not evidence the app itself is a modded build, so only the app name and a real package id are scanned. A further refinement (from live Minecraft and WhatsApp runs) skips URLs that are clearly not app listings at all: how-to guides, blog/news/forum posts and government pages ('/howto/', 'how-to-download-minecraft-mod', a gov.in download page) are articles, not repackaged builds, so a non-app-page guard drops them while genuine mod apps on APK sites (aptoide /app pages, mod-site domains) are still flagged.
Rejected and why: A scored signal in fusion - fusion maps scores to impersonation, not repackaged, so a veto with a forced repackaged label is the right shape, consistent with the existing package veto. Reading the description for markers - "mod" appears innocently there; name and package are the reliable place.
Status: active

## K-053: Brand registry - one CSV as the source of truth for the watchlist
Context: The watchlist sweep (K-047) scans every profile in data/watchlist, but each profile was a hand-written JSON. That works for three banks and not for a portfolio of hundreds: writing, reviewing and removing a thousand JSON files by hand is slow and error-prone, and the official publisher/package fields that drive the veto (K-014) were being guessed or copied manually from inspect_brand.py.
Options: (a) keep hand-written JSONs, (b) a one-shot CSV-to-JSON converter, (c) a registry that keeps the watchlist in sync with a CSV, with ownership rules and optional verified enrichment.
Decision: src/brandguard/registry.py with `python -m brandguard.registry check|sync [--enrich]`. data/brands.csv holds one row per brand (only brand_name and official_domains required; list cells use "|"). `check` validates and prints the plan without writing; `sync` creates, updates and removes profiles to match. Generated profiles carry a `_registry` block; only those are ever changed or removed, a hand-maintained profile (no block) is never touched, and a row already covered by one (same id or shared official domain) is skipped so no brand is scanned twice. Any validation error aborts the whole sync before a write; a CSV with no active brands refuses to prune. Writes are atomic and idempotent (unchanged content is not rewritten). `--enrich` fills official publishers, package ids and app titles from Google Play, accepting a publisher only when its developer website or e-mail is under an official domain; name-only lookalike publishers are listed for review and never written. Enrichment is cached in the profile and re-queried only on --refresh or when the official domains change; three consecutive failures stop enrichment for the run.
Rationale: The CSV is the smallest representation a person can maintain (Excel, one line per brand, "active=no" to pause), and a sync with explicit ownership is what makes it safe to run on a schedule: a typo, a truncated file or a hand-tuned profile cannot cost coverage. Enrichment applies the same identity rule as the publisher veto (trust the domain, not the name), so automating profile building does not reopen the spoofed-publisher hole K-014 closed. Incremental caching and the circuit breaker keep a thousand-brand run cheap and polite to an unofficial interface. Real-world input is handled explicitly: Turkish-locale Excel writes ";" and cp1254, both are read; pasted URLs are reduced to hosts; unknown columns fail loudly to catch typos; a sector with no permission baseline in triage is reported, because permission drift silently abstains there.
Rejected and why: (a) does not scale and invites drift between profiles. (b) a one-shot converter cannot remove brands or protect hand-tuned profiles, so the second run is where it breaks. Writing enrichment by top publisher frequency (what inspect_brand.py suggests to a human) - the most frequent publisher on a search page is not proof of identity and would let an impersonator become "official". Storing a manifest outside the profiles - the in-file marker keeps each profile self-describing and survives copying.
Verified: 33 unit tests (validation with line numbers, cp1254 and ";" input, idempotency, pruning only managed files, manual profiles untouched, no double scan, all-or-nothing on errors, domain-verified enrichment accepting website and e-mail proof and rejecting a name-only lookalike, cache reuse, stale-proof drop, circuit breaker). End to end on a 13-brand CSV next to a hand-written ziraat.json: 12 created, re-run 12 unchanged, deleting a row and deactivating another removed exactly those two profiles.
Known limit: enrichment sees only the top Play search results for the brand name, so an official app that does not rank for it is not added (add it in the CSV); a publisher whose store listing has neither a website nor an e-mail under an official domain is never auto-accepted, which is deliberate, and subsidiaries on their own domains (e.g. a participation bank) count only when that domain is listed.
Status: active

## K-054: Brand-name-only rows - official domain discovered from two independent sources
Context: K-053 still required official_domains in every CSV row, and a plain sync never went online, so profiles held only what was typed. The goal is a list where an operator types a brand name and nothing else. The official domain is the trust anchor of the whole profile (the veto and enrichment verify identity against it), so finding it automatically must not let an impersonator plant its own site as "official".
Options: (a) keep the domain mandatory, (b) take the developer website of the top Play hit, (c) take Google's first result, (d) require agreement between independent sources, with narrow single-source fallbacks.
Decision: official_domains is optional. For a row without it, `sync --enrich` runs one Serper search and one Play search (shared with enrichment) and accepts, strongest first: a Google candidate (knowledge panel website, or a top-5 result about the brand) that matches the developer site of the brand's Play app ("google+play"); Google's knowledge panel alone; or the developer site of a Play app with 1M+ installs whose title or developer carries the full brand name. The two single-source forms are flagged for review, printed once when first found. Social networks, stores, encyclopedias and free mail hosts never count as a brand site. When nothing qualifies the row is skipped with a reason and no profile is written. The proof is stored under _registry.discovery and cached; a domain typed into the CSV always wins and replaces it. Online lookups share one rate limit and one circuit breaker, and a brand resolved earlier keeps its profile when a later lookup fails.
Rationale: The top Play hit (b) and the top web result (c) are each something an attacker can influence; two independent sources agreeing is not. The single-source fallbacks keep only what the threat model says an attacker cannot cheaply produce: Google's curated knowledge panel, and organic install volume ("Cannot do: produce organic download volume"). Requiring the full brand name for the Play-only rule stops a popular generic app ("Kredi Hesaplama" for "Yapi Kredi") from qualifying on one shared word. Skipping instead of guessing keeps the failure mode "brand not yet covered, reported", never "impersonator trusted".
Rejected and why: (a) defeats the purpose at scale. (b)/(c) alone - a single attacker-influenced source would become the veto's trust anchor. Inferring the sector from the Play category - FINANCE covers both banks and exchanges, whose permission baselines differ; the sector stays optional and unknown sectors make permission drift abstain, which is safe.
Verified: 44 unit tests, 11 new: agreement across sources, both single-source rules with review, a 900-install lookalike with its own site rejected even when Google names the real one, social/mail hosts ignored, a generic 5M-install app not accepted for a two-word brand, brand-name-only row to a full profile with one shared Play search, cache reuse (one Serper call across runs), CSV domain overriding discovery, unresolved brands skipped, a resolved profile kept when a later lookup fails. End to end through the CLI with fake Play/Google clients: a three-name CSV produced two complete profiles (domain, publisher, package id, app title), rejected a lookalike publisher, and skipped the unknown brand; the second run made no discovery calls for the resolved brands.
Known limit: an unresolved brand is looked up again on every --enrich run (one Serper query each) until its domain is typed into the CSV; the sector is not inferred.
Status: active

## K-055: A claimed developer website is not proof of identity (revisits K-014)
Context: Reading a live enrichment result (Binance) showed that the evidence rested on Play's developer website and e-mail. Those fields are typed in by the developer; Play does not require them to be proven. K-014 listed "publisher website on an official domain" among verifiers "the attacker cannot cheaply forge", and K-053/K-054 reused that premise. It is false on Play: an impersonator can copy the official publisher name and type the brand's domain. Reproduced as a failing test before the fix: a 500-install listing named "Binance Inc." with website binance.com received an official veto from check_publisher_veto. With automated enrichment the same claim would also have written the impersonator into official_publishers across the portfolio.
Options: (a) drop the website verifier, (b) keep it and accept the risk, (c) keep it only when the listing also carries a signal the attacker cannot produce.
Decision: (c), applied in three places with one threshold (100,000 installs, the organic reach an impersonator cannot manufacture, THREAT_MODEL.md "Cannot do"). Veto: _website_verifier accepts the claimed website only on a listing with >= 100k installs, or on an official package id on Google Play, where package ids are unique; other verifiers (store verified flag, account age) are unchanged. Enrichment: a publisher whose website/e-mail claims an official domain is accepted only when one of its apps in the results has >= 100k installs; its smaller apps then count as official too. Claims without an established app go to review with the reason, never into the profile. Domain discovery: agreement between an organic Google result and a Play developer site counts only when that Play app is established; agreement with the knowledge panel is unaffected, because the panel is not attacker-controlled. --min-installs makes the enrichment threshold tunable; an analyst can always confirm a small genuine publisher by typing it into the CSV.
Rationale: Identity must rest on something the attacker cannot type. Install volume and Play's unique package ids are such signals; the website field is not. Requiring the claim AND reach keeps genuine brands working (their core apps are far past the threshold, and a new small app inherits trust from its publisher's established one) while a fresh impersonator listing fails regardless of how well it copies the name and domain. A rejected claim does not become a takedown: K-032 still treats a matching official name as unverified identity, and without a strong attacker-independent signal K-018 escalates instead of labelling impersonation.
Rejected and why: (a) loses the only identity signal many genuine live listings carry (Play exposes no verified flag or account age), pushing official apps to uncertain. (b) the failing test shows the hole is real, and automation would spread it to every brand. A per-brand install threshold - no principled value per brand; one global threshold tied to the threat model is explainable and tunable.
Verified: the attack test failed on the old veto and passes on the new one. 8 veto tests (fresh impostor not official; established official listing official; small official app official via its Play package id; the same package id on a third-party store not accepted; sources without install data keep the earlier rule; other verifiers unchanged; a rejected claim does not become a repackaged takedown) and 7 registry tests (impostor typing the official website and e-mail rejected with a review reason while the genuine publisher stays, small app of an established publisher kept, missing install data not trusted, threshold tunable, analyst override through the CSV, organic+Play agreement refused for a small app, knowledge-panel agreement unaffected). Registry suite 51 tests.
Refinement (same day, from the live Ziraat hunt): Bankkart Mobil (com.bankkart.mobil, on Ziraat's official package list, publisher "T.C. Ziraat Bankasi A.S.") was labelled unrelated, because its listing declares its own card-brand website rather than ziraatbank.com.tr, so no verifier fired, and K-032 correctly kept it from becoming repackaged. An official package id on Google Play is now a verifier on its own: Play enforces unique package ids, so such a listing is the brand's app whatever website it declares. The same id on a third-party store still proves nothing (that is what repackaging is), and the package list itself only holds ids from the analyst or from K-055-verified publishers. Tested with the Bankkart case and its third-party mirror.
Known limit: a source that reports no install figure keeps the earlier website rule, since the claim cannot be checked there; live Play always reports installs. A genuine official app under 100k installs that is not yet in official_package_ids is no longer vetoed on Play; it falls through to scoring, where live data cannot reach an impersonation verdict without a strong attacker-independent signal (K-018), so the cost is an uncertain label, not a takedown. Adding it to the CSV restores the veto.
Status: active

## K-056: Recover the featured top search result that google-play-scraper drops
Context: Verifying the registry's enrichment against the web (AppBrain) showed that nearly every brand's main app was missing: com.binance.dev, com.mobillium.papara, com.paribu.app, com.btcturk.pro, com.enparabank.retail, com.yurticikargo.android, com.araskargo.mobileapp. A live check confirmed the cause: search("Papara", lang="tr", country="tr") returned None as the first appId. google-play-scraper 1.2.7 (the latest release) reads the featured top result's package id from a fixed position ([11, 0, 0]) that Google has moved, so the top result - usually the brand's own main app - arrives without an id. Every caller then drops it: the registry skips hits without an id, and live_google_play.search_and_fetch calls app(None), falls back to the bare hit and yields a record with an empty app_id that is filtered out. The empty-id record noted in K-030 was this. The hunt had therefore been missing the single most relevant listing of every Play query, and the registry could not see the apps its install-volume rule (K-055) depends on.
Options: (a) wait for an upstream fix, (b) find Play ids through Google search (Serper, site:play.google.com), (c) reimplement the library's search, (d) replace only the top result's appId rule.
Decision: (d). src/brandguard/discovery/play_search.py replaces SearchResultOnTop["appId"] with a rule that tries the old position, then scans the top card for package ids in the shape the library itself uses for regular results (["<package>", 7]) or in "details?id=" links, and returns the id that occurs most often (the featured app's id repeats across its card; a similar app shown on it does not). Nothing recognisable leaves None, the previous behaviour. Its search() is a drop-in for google_play_scraper.search (same signature) and removes duplicate ids. The registry, live_google_play.search_and_fetch and scripts/inspect_brand.py now import search from it.
Rationale: The smallest change that fixes the defect where it originates, with no extra requests and no API cost; every other field and the rest of the library stay untouched, so a future upstream fix makes the rule a no-op. Keying on the structure the library already trusts is more stable than a new fixed index. Majority voting guards against picking a neighbouring app's id from the same card.
Rejected and why: (a) no fix is released and the hunt is blind to main apps meanwhile. (b) adds a paid query per Play search and depends on Google ranking; kept in reserve as a fallback if Play's structure changes again. (c) a fork of the library's parsing to maintain.
Verified: the test reproduces the live bug through the library's real parsing code on a Play-shaped page (top result title "Papara", appId None) and shows the wrapper returning com.mobillium.papara with its developer; majority vote beats a similar app on the card; a details link alone is enough; unrecognisable data keeps None; duplicates removed. End to end, search_and_fetch on the same page now yields the main app as a record with publisher, website and 10,000,000 installs, where before it was dropped. Registry suite and evaluation unchanged (the evaluation set does not use live search). Live, same day: scripts/inspect_brand.py "Papara" lists com.mobillium.papara first (it was None). Re-running the Play hunt over the 19-brand watchlist, the brand's main app went from absent in every brand to the first, official-labelled result in 18 of 19 (com.binance.dev, com.mobillium.papara, com.paribu.app, com.btcturk.pro, com.enparabank.retail, com.pozitron.iscep, com.ziraat.ziraatmobil, ...); the exception, MNG Kargo, has no current app on Play. With the main apps visible, registry enrichment accepted PARIBU and the BtcTurk publisher through their 5M+ apps, clearing both K-055 review lines without any manual input.
Known limit: the recovery relies on Play still embedding the id as ["<package>", 7] or a details link in the top card; if both change, the top result's id is None again and the old behaviour returns, which the test would not catch because it uses a fixed page. `python scripts/inspect_brand.py "Papara"` is the quick live check: the main app should be the first line.
Status: active

## K-057: Operator categories are a product layer over the engine labels
Context: The CTO's brief for the product was three answers per candidate (official, malicious, suspicious) and an interface anyone can use. The engine deliberately keeps six labels (K-016) and separate domain verdicts (K-037), because those distinctions are what the evidence supports.
Options: (a) collapse the engine labels to three, (b) show six labels in the UI, (c) a mapping layer.
Decision: (c) `brandguard/product/category.py` maps engine labels and domain verdicts to five operator categories (official, malicious, suspicious, related, noise) in one function; the engine label is stored next to the category on every finding and shown in the details view. Domain findings map by liveness and D1 priority: a live, high-priority lookalike is malicious; other lookalikes and generated watch names are suspicious.
Rationale: The product vocabulary can change per customer (show related or not) without touching a decision rule or a test. Nothing is lost: an analyst who opens a row sees the fine label and the evidence.
Rejected and why: (a) destroys measured distinctions and the evaluation; (b) makes the operator learn the engine.
Status: active

## K-058: Hardening fixes found by reading the code, each locked by a test
Context: Before adding a product shell, the known-weakness list was walked through and every defect that could fail silently in a running service was fixed.
Decision: (1) `normalize` folds Turkish characters before lowercasing, so "İş Bankası" no longer splits into "i s bankasi" (Python lowercases the dotted İ to i + combining dot). (2) `parse_downloads` understands both thousands conventions ("1.000+" and "1,000+", decimal "1,5M" and "2.5M"). (3) Model output in both LLM adjudicators goes through one guarded parser: prose, fences, truncation or an API error become a weak uncertain leaning, never an exception; calls have a 30 s timeout and one retry; `triage_t2` records an unreachable adjudicator in the evidence instead of aborting the scan. (4) The conflict list handed to T2 names signals and directions, not their evidence text, closing the path by which a raw app name reached the model. (5) `.env` is resolved from the repo root (`brandguard/config.py`), not the working directory. (6) The one-source scripts moved to `scripts/legacy/`, which also ends the two-format `run_log.csv`.
Rationale: A product runs unattended; a crash on a malformed model reply or a key not found because the process started in another folder is a silent outage. Each fix has a test in `tests/test_hardening.py`. Evaluation metrics unchanged before and after.
Status: active

## K-059: Product API and database; sources run in isolation, a scan can be partial
Context: The console needs persistence, background execution and an audit trail; the CLI wrote one JSON per run and a CSV log.
Decision: FastAPI + SQLAlchemy + SQLite (WAL) under `brandguard/api/`. Tables: brands, scans, scan_sources, findings. One job per (scan, source) on a small thread pool with per-source concurrency limits (Play 1, Serper 2, crt.sh 1). A failing source records its error on its own row; the scan ends `done`, `partial` or `failed` and failed sources can be retried alone. Findings keep `first_seen_at` per brand and key across scans. Depth presets (quick / normal / deep) set the runner dials; explicit tuning overrides them. Datetimes are serialised as UTC. Startup imports `data/watchlist/*.json`; a profile edited in the console (`resolved_from=manual`) is never overwritten by an import.
Rationale: The K-047 isolation rule carried into the product, with the failure visible instead of printed. SQLite needs no setup and the URL is the only thing to change for Postgres. `first_seen_at` costs nothing now and is what notifications and "what changed" will need.
Rejected and why: Celery/Redis: more moving parts than the workload justifies today. Keeping JSON files as the store: no queries, no first-seen, no editing.
Status: active

## K-060: Input resolution: a typed domain is the trust anchor
Context: The CTO wants to type a domain (or a package id, or a store URL) and get the related apps. K-054 resolved a brand name to a domain through two independent sources; the reverse direction was missing.
Decision: `brandguard/product/resolve.py` detects the input type without asking and resolves it: a domain is trusted as given and only the brand name and Play publisher are looked up (the most-installed Play app whose developer site or e-mail sits under the domain, then Google's knowledge panel, then the site's own title, then the domain label with a review note); a package id is resolved through its Play listing's developer site into the domain path, and a listing below the K-055 install threshold is scanned but not assumed official; a name follows K-054 unchanged. Every unverified step becomes a review note on the brand, shown in the console, never written into the profile. A resolved profile that matches an existing brand merges into it.
Rationale: The operator typing a domain is a stronger source than any search result, so requiring two-source agreement there would only add cost. The Play-publisher rule reuses `enrich_from_listings`, so the K-055 install threshold applies to domain inputs too.
Rejected and why: Guessing the brand name from the domain label alone without saying so — it is the fallback, but it is flagged.
Status: active

## K-061: Discovery widening and reliability for unattended runs
Context: "More APK sites, more Google pages, no mocks, must be trustworthy."
Decision: Serper: eleven APK hosts, a modded-build dork, `gl=tr,hl=tr`, pagination (`pages`), per-query errors collected on the run instead of printed; non-listing pages (articles, forums, SEO spam, government pages) are recognised from the URL and labelled noise with the reason, before triage. Play: the query budget is spread over strategies in priority order (exact, normalized, suffix, typosquat, ...) instead of the first N of the block-ordered list, detail pages are cached for a day and never fetched twice in a scan, searches are paced; a run that returns none of the brand's official package ids carries a warning (the K-056 alarm). Website hunt: a generated variant that a search returns is promoted to live and enriched; the generator's lure words match the classifier's. Every runner reports request counts and duration, so the cost report has real numbers.
Rationale: Each item either widens what is seen or turns a silent degradation into a visible one. Evaluation metrics unchanged.
Known limit: the noise filter and the K-056 alarm are URL and package-id heuristics; they detect, they do not fix. Live measurement on the ten-brand set is the next step (see PLAN v2, Faz 4 ölçüm).
Status: active

## K-062: The store's developer account id is an identity verifier
Context: First live scan of a bank (Sept 2026). The flagship app was official via the package-id veto; the same publisher's card app, its small "easy" variant and a merchant app (10k-40k installs, not on the package-id list) fell to `third_party_legitimate` and were shown as "related", next to unrelated ATM directories. The operator could not tell the brand's own apps from noise.
Decision: `Publisher.account_id` carries Google Play's `developerId` (present on detail pages only). After the cascade has run over a batch, a record that shares the account id of a listing the veto already verified as official is promoted to official (confidence 0.95, reason `same_developer_account`, an extra evidence line naming the anchor app). Records with no account id are never touched, so evaluation data and other stores are unaffected (metrics unchanged).
Rationale: The account id is the one publisher field an impostor cannot type in: only the account's owner can publish under it. The rule inherits its safety from the veto that verified the anchor; it adds no new trust source. It is a batch rule (it needs the anchor in the same scan), which is why it lives in the hunt engine's second pass and not in the per-record veto.
Known limit: an anchor must be present in the scan; a scan that misses the flagship (K-056 alarm) promotes nothing. A verified account that is later compromised would promote its new uploads too; the package-id list remains the operator's override.
Status: active

## K-063: "Possible affiliate" is a product category, not an engine label
Context: Same scan. "Isbank AG" (the German subsidiary, its own developer account, its own domain) is not an impersonation and not the profile's publisher; the engine correctly says `third_party_legitimate`. Shown as "related" it is indistinguishable from a comparison-site app, and the operator asked for a fourth bucket: "probably a foreign/affiliate version".
Decision: `product.affiliate.possible_affiliate()` attaches a hint to a *benign* record (third_party or unrelated) whose publisher identity points at the brand: official publisher name without a verifier, developer site under an official or vetted-affiliate domain, or a brand token in the publisher name or the developer site's own label. Records with the hint are shown as category `affiliate` ("Affiliate?"). Threat and uncertain labels are never softened by the hint. The details view offers one click to write the package id and publisher to the profile, after which the next scan verifies it through the veto.
Rationale: Everything the hint uses is typed by the publisher, so it cannot decide anything; it only tells the operator where to look. Keeping it out of the label keeps the evaluation set and the takedown metrics untouched and keeps the trust rules (K-014, K-054, K-055) intact: the way to make an affiliate official is still the profile, now one click away.
Known limit: brand tokens are the distinctive words of the name plus official-domain labels; a brand whose name is entirely generic ("Bank") and whose domain label is short gets no hints.
Status: active

## K-064: A Play "no results" page is an empty result, not a failed query
Context: Typo variants ("tturkiye is bankasi") made google-play-scraper raise TypeError (it guards only IndexError while reading the featured result from a fixed path, and the node is None on a no-result page). Each such query showed as an error on the run.
Decision: The K-056 wrapper catches that TypeError and returns an empty list; other exceptions still propagate and are recorded per query (K-030). The APK-site runner's request accounting no longer multiplies an unbounded (`None`) query budget, which had failed the whole source at normal and deep depth.
Rationale: A no-result page is a legitimate outcome of a typo query; reporting it as an error hid the real failures among a dozen false ones.
Status: active

## K-065: A modded build is this brand's takedown only when it is this brand's app
Context: Live scans of Spotify, Duolingo and TikTok. The APK-site source returns whatever a "brand mod apk" dork matches; the unauthorized-build veto then labelled every page with "MOD" in its title as repackaged, including Amazon Music, Shazam and Pandora mods, store index pages ("Android Apps & MOD APKs - Page 2") and the store's own front page. Precision on the malicious tab was roughly one in three, and the operator rightly asked why Amazon was on Spotify's list.
Decision: The veto fires only when the listing relates to the brand: its name, package, URL or publisher names the brand (its distinctive words, its compact name, an official-domain label or a known app name: `registry.identity_tokens`), or the package id is an official one. Otherwise the record falls through to the scored signals, which read a foreign name as unrelated. The Spotify-profile tests that expected "Netflix Cracked" to be repackaged were changed to assert the opposite; on a Netflix profile it still is.
Rationale: Repackaging is by definition a modification of *this* brand's product. A modded Amazon Music app is real and objectionable, but it is Amazon's takedown, not Spotify's; listing it costs analyst time and trust. Identity tokens (not just the name's words) matter because a bank whose name is entirely generic ("Turkiye Is Bankasi") is recognised through "iscep" and "isbank". Evaluation metrics unchanged.
Known limit: a mod that names the product only by an abbreviation the profile does not know ("MCPE" for Minecraft) is missed until the abbreviation is added as a known app name.
Status: active

## K-066: Official package ids are fetched directly; a platform's own domain is not excluded for that platform
Context: (a) TikTok, entered as its Play store URL, resolved to a name-only profile and its own listing was not official: `tiktok.com` sits on the list of hosts that are never a brand's site (social networks, stores, mail providers), which is right for every brand except TikTok. (b) The account rule (K-062) needs the verified flagship in the same scan, and Play search does not always return it (K-056).
Decision: (a) `_is_brand_site(host, brand)` accepts an excluded host when the brand's compact name is that host's label; the package path passes the listing's title and developer as the brand hint. (b) The Play runner fetches every official package id's detail page first (cached, one request each) and adds those records before searching; the K-056 alarm now looks only at what search itself returned, so the direct fetch cannot mask a broken scraper.
Rationale: (a) The exclusion list protects against a listing that names a platform as its "website"; the platform itself typing its own domain is the one case where that claim is trivially true. (b) A scan's official rows should not depend on search ranking; fetching the anchors is one request per official app and makes the account rule deterministic.
Status: active

## K-067: A name-only automatic profile is resolved again on its next scan
Context: TikTok still had no official app after K-066: the scan said "saved profile used". The first, failed resolution had stored a name-only automatic profile, and every later scan reused it without a network call, so the resolver fix never ran.
Decision: A brand row with `resolved_from="auto"` and no official domain is stale. On its next scan the resolver runs again; if it now finds a domain the row is upgraded in place (domain, publishers, package ids, sector, audit trail, fresh review notes) and the scan records `re-resolved:<how>`. If it still finds nothing, the row is kept and nothing is repeated. Rows an operator edited (`manual`) or that already have a domain are never re-resolved.
Rationale: Reusing a profile saves network and keeps operator edits authoritative; both reasons vanish for a row that holds nothing but a name. Retrying only the stale rows keeps the cost bounded to one resolution per scan of such a brand.
Status: active

## K-068: A modded companion app is related, not a takedown
Context: Thirteen exported live scans (Instagram, Facebook, TikTok, Spotify, CapCut, ...). After K-065, most of what remained on the malicious tab that was not a mod of the brand's product was a mod of a *companion* app: "Video Downloader for Instagram (MOD)", "Stats for Spotify (MOD)", "Tips for CapCut (MOD)", "DJ TikTok Viral (MOD)". They name the brand, so the relation guard passes, but the brand is their subject, not their publisher: nothing of the brand's was repackaged. Replayed over the exports, the malicious rows fell from 163 to 72 with K-065 and K-068 together, and every remaining row names the brand's own product.
Decision: The build veto stays silent when the normalized name marks a companion app: the brand as the object of a preposition ("for instagram", "para spotify"), a "download <brand> video" phrase, or a companion noun (downloader, stats, tips, guide, tutorial, wallpaper, widget, template, followers, ringtone, ...). A neutral `companion_build` signal records the reason, so the analyst reads "modded build of a third-party companion app" on a related row rather than wondering why "(MOD)" is not malicious. The preposition rule uses brand and domain tokens only: "Spotify for Artists" is the brand's own app, and "artists" must never count as a brand word. An official package id always overrides.
Rationale: Repackaging is the brand's product, modified. A companion app is somebody else's product; its mod is that publisher's takedown. Keeping it visible as related preserves the trademark-use signal for whoever wants it, without spending analyst time on it as a threat.
Known limit: word lists. A companion app named without any of the markers ("Insta Saver Pro (MOD)") still reads as a mod of the brand when "insta" matches a brand token; the lists grow from live data.
Status: active

## K-069: Store and platform URLs are inputs about a brand, never the brand
Context: A Play *developer* URL (`/store/apps/developer?id=TikTok+Pte.+Ltd.`) was typed; input detection saw a domain (play.google.com), resolution took it as the brand's site, and the scan produced a brand "Google LLC" with 28 official Google apps. Separately, complaint boards (sikayetvar.com) and forums (xdaforums) ranked for "<brand> apk" and were triaged as listings.
Decision: A Play developer URL is a brand-name input (the developer name); a Play URL that names neither an app nor a developer is refused with a message. A typed domain on the platform list (stores, mail providers, hosting platforms, encyclopedias, complaint boards) is refused as a brand domain with a message naming the alternatives; typed social-network domains are accepted, because "facebook.com" typed means the brand Facebook (the listing-claim exclusion of K-066 is a different list). Complaint boards, review blogs and forums are article hosts for the page-kind filter.
Rationale: The K-060 trust in a typed domain assumes the domain can belong to a brand. A store cannot; accepting it does not just fail, it produces a confidently wrong profile.
Status: active

## K-070: An app's own name is not a mention of the brand
Context: Scan of the airline Pegasus. "Pegasus Plus" (BJain Publishers, a children's-book companion app, 1k installs) ended suspicious: its name starts with the brand word, and its description "PegasusPlus is the official companion app for parents using books from BJain Publishers" set both `description_names_brand` and `description_claims_official`, so the adjudicator read "unverified publisher claiming to be official". The claim was about BJain, and the only "Pegasus" in the text was the app's own name. A brand whose name is a dictionary word shares it with many unrelated companies.
Decision: Before the description facts are computed, the app's own name is removed from the description when that name merely contains the brand word (an app named exactly like the brand keeps its mentions). `description_claims_official` is then true only for an official word within 80 normalized characters of a remaining brand mention, on top of the K-022 negation rule. The rule adjudicator gains a namesake rule: a brand-leading name whose description never refers to the brand, with no youth, no sensitive permissions and no official claim, leans third-party; the model prompt states the same. Pegasus Plus now ends related.
Rationale: An imitation talks about the brand; a namesake talks about itself. Word-level facts could not tell the two apart because the app's name is in its own description by construction. The stripped facts stay injection-safe (still booleans) and the evaluation set, whose impersonations name the brand in their prose, is unchanged.
Known limit: an impersonator whose app is named "Brand Plus" and whose description avoids the brand word entirely also reads as a namesake at T2; T0's attacker-independent signals (account age, permissions) still carry such a case when they are present.
Status: active

## K-071: A dictionary-word brand is found by its identity words and doubted by its bare word
Context: Pegasus, scanned by name and then by its Play URL, gave the same result: the URL only identifies the profile (already correct: flypgs.com, Pegasus Airlines, com.pozitron.pegasus); discovery still searches the bare word "pegasus", which belongs to horses, an Asus phone model, a book publisher, a VPN and a spyware. Eighteen "malicious" rows were "X (MOD) for Asus Pegasus 5000" device pages and games named Pegasus.
Decision: Three parts. (1) The companion rule (K-068) accepts the brand word within three words after the preposition ("for asus pegasus 5000"). (2) Discovery adds identity terms to the queries: the official publisher name and the flagship app's title ("Pegasus Airlines", "Pegasus - En Uygun Ucak Bileti") get one Play search and one catch-all APK dork each, on top of the budget. (3) After triage, when the brand's strongest identity is not its bare word (the domain label differs from the name) and the result set shows the word is shared by at least four unrelated products, a repackaged verdict that rests on the build veto and names none of the identity words (publisher, flagship title, domain label) becomes uncertain with the count on record. Brands whose domain is their name (spotify.com, tiktok.com, akbank.com) are never touched by (3). Replayed: Pegasus malicious 18 -> 0, three left uncertain; every other export unchanged.
Rationale: The store URL cannot narrow a name search; what narrows it is the identity the profile already holds. Part (3) is deliberately conservative: it only moves takedowns to review, only for brands the data itself shows to be ambiguous, and never when the listing carries an identity word. A person confirming "Little Pegasus (MOD)" is cheaper than a wrong takedown letter to a game studio.
Known limit: the ambiguity count is per source run; a scan whose APK results happen to contain few namesakes keeps the veto. The stop-word list for counting products grows from live data.
Status: active

## K-072: Second live round, sixteen brands: sector words, legal suffixes, the brand's own pages
Context: Sixteen exports on the v2.6 engine. Takedown precision was right for every brand (every malicious row named the brand's own product; Netflix showed 19 official apps through the account rule). Three residual classes: (a) "kredi" made every Turkish loan app a possible affiliate of Yapi Kredi and "telekom" every European carrier an affiliate of Turk Telekom; (b) profiles built from a store publisher were named "WhatsApp LLC", "BIM Birlesik Magazalar A.S.", "Google LLC", which also broke the K-071 off-switch ("whatsappllc" is not the domain label "whatsapp", so a real WhatsApp mod was softened); (c) pages on the brand's own site (binance.com/download) were triaged as listings and came out suspicious because their text "claims to be official"; a stale "Google LLC" row let `play.google.com` bypass the K-069 refusal.
Decision: (a) Industry words join the generic-token list (kredi, yapi, finans, sigorta, yatirim, telekom, market, magaza, hizmetleri, iletisim, teknoloji, ...) together with legal abbreviations. (b) `clean_brand_name` strips legal suffixes from a publisher name used as a brand name; the K-071 switch is off when any of the brand's own words is an official-domain label. (c) A search hit whose URL is under an official domain is noise with the reason on record ("non_listing_official_site"); the platform-domain refusal runs before the saved-brand lookup. Play's no-result KeyError is treated like its TypeError (K-064); fintables, scribd and archive.org are article hosts.
Rationale: Each is a one-line rule that the data forced; none touches the trust rules. Evaluation unchanged.
Status: active

## K-073: The console is a workbench, not a one-shot scanner: reviews, diffs, schedules
Context: With takedown precision settled (K-065..K-072), the remaining cost was human: every scan re-listed Ziraat's nine affiliates and every known false positive; "what changed since last week" had to be read off two exports; nothing ran unless someone typed the brand.
Decision: Three small, independent pieces that share one idea, the finding *key* (package id or domain) is the identity that persists across scans.
(1) **Reviews.** An analyst marks a key of a brand as false positive, confirmed, takedown sent or resolved, with a note (`reviews` table, unique per brand+key; `PUT/DELETE /api/brands/{id}/reviews/{key}`). The decision is attached to every finding with that key in every scan, past and future. "Needs action" is malicious + suspicious minus settled keys (false positive, resolved, takedown sent); confirmed stays in the queue because the takedown is still to do. The engine's label and category are never changed by a review; the mark sits beside them.
(2) **Diff.** `GET /api/scans/{id}/diff` compares a scan with the brand's previous finished scan that used the same sources (or with `?against=`): keys that appeared, disappeared, or changed category. The scan page shows the line "since the previous scan: N new, M gone, K changed" and a "New" tab (`items?new_only`, first_seen == created).
(3) **Schedules.** A brand carries schedule off/daily/weekly with its sources and depth; a scheduler thread ticks every minute and starts due scans as ordinary scans marked `trigger=schedule`, submitting them only after the transaction committed. The first run is one interval after enabling ("Scan now" covers the immediate case). Schedule edits do not mark the profile as manually edited.
Rationale: Keys, not finding rows, carry state because rows are per scan by design (K-059) and the operator's decisions are about the thing, not about one observation of it. Reviews never touch the engine so the evaluation stays meaningful and a wrong review is reversible with one click. The diff is computed, not stored, so it needs no migration and is always consistent with the rows. The scheduler is a thread, not a separate process, because the worker already is; a restart loses at most one tick.
Known limit: a schedule runs only while the server is up (a cron-like external trigger is the production shape); notification of new findings is deliberately still out of scope, the diff endpoint is what a notifier would read.
Status: active

## K-074: A brand-named publisher left uncertain by words alone is a possible affiliate
Context: Third live round, twenty brands. "BtcTurk | Hisse" (publisher BTCTURK YATIRIM MENKUL DEGERLER) and "Türk Hava Yolları Uçak Bileti" (publisher Turkish Airlines, before the profile knew it) ended suspicious: their descriptions "claim to be official", and the affiliate hint (K-063) only decorated benign labels.
Decision: The hint also applies to an *uncertain* verdict when two things hold: the publisher name equals the official publisher or carries a brand identity token, and no attacker-independent signal accuses the record (account age, permission drift, solo publisher, review pattern, build marker, package veto). Such a record is shown as a possible affiliate, still a review item, not as a suspected impersonation. Three-letter brands (QNB, n11) now have their own word as an identity token, matched as a whole word only.
Rationale: The only suspicion in these cases is text the publisher wrote, read by a language model; the publisher naming the brand in its own store identity is a stronger hint of kinship than of fraud, and an impostor who does that still trips the independent signals when they are present. The review is the same either way; the bucket says where to look first.
Status: active

## K-075: The Play run measures how shared the brand word is, and tells the APK-site run
Context: "Wise" (wise.com): eight "malicious" rows were mods of Wise PDF, Wise Timetable, Doctor Wise, Chat Wise. K-071's ambiguity switch was off because the domain label is the brand word, which is right for Spotify and wrong for a dictionary word. Also: "turkishairlines.com" resolved to a name-only profile because Play does not answer the fused label; catalog apps ("Aktüel Ürünler - A101 Bim Şok (MOD)") were A101 takedowns; every mirror listing of an official app read "claims to be official".
Decision: (1) The Play run counts *namesake* publishers: not the brand, not carrying a brand token in their name (a subsidiary and a namesake look alike; counting subsidiaries softened Garanti's own mods in the replay), leading their app name with the brand word, whose description does not name the brand once the app's own name is set aside (companions lead too: "Binance Ninja"). The count travels as `RunResult.measurements` into the scan and the APK-site run of the same scan waits for Play (up to 20 minutes) and reads it into `BrandProfile.brand_word_shared_by`; three or more turns K-071 on regardless of the domain. (2) Domain resolution retries Play with the site's title when the label finds nothing. (3) katalog/catalog/brosur/aktuel are companion words. (4) An uncertain listing on a known mirror host that names the brand's app without a build marker gets a `mirror_listing` evidence line and reason `mirror_unverified`; the adjudicator's "claims official" line is dropped. It stays suspicious: unverifiable without a signature, but the analyst reads what it is.
Rationale: Store publisher names and descriptions are the attacker-independent evidence the serper rows lack; measuring on Play and handing the number over keeps the engine's rule deterministic and explainable ("shared by 4 other publishers on Google Play"). The wait costs a minute per scan and cannot deadlock: Play jobs never wait on anything.
Known limit: a dictionary-word brand whose namesakes all carry the word in their publisher names (Wise Vets, Wise Finwealth) still reads as unambiguous; without world knowledge or a signature, "Wise PDF (MOD)" cannot be told from "Wise Payments (MOD)" by rules. The mirror rule trusts the host list.
Status: active

## K-076: For a shared brand word, discovery queries are anchored with an identity word
Context: The operator's observation after the third round: "searching by the publisher or the domain is better than by the brand name". True for identity (K-060: the typed domain is the anchor) and half true for discovery: impostors and their victims type the bare word, so the bare word must stay in the queries; but for a word Play has shown to be shared (K-075), the host dorks spent the whole budget on horses, phones and PDF readers.
Decision: When `brand_word_shared_by` is three or more, the catch-all and per-host APK dorks carry one of the brand's own identity words ("pegasus ucak apk site:apkpure.com"); the mod dork stays bare, because a modded build of the brand's app is titled with the bare word, and it moves to second place so the smallest budget still runs it. The Play run already searches the publisher name and the flagship title (K-071). Unambiguous brands keep the bare queries.
Rationale: The identity word is the profile's, not the attacker's; it narrows recall only where recall was mostly noise. Keeping the mod dork bare protects the one query that finds takedowns.
Status: active

## K-077: The scan input is three typed facts, and an official package id on Play is identity on its own
Context: The operator's conclusion after three live rounds: "searching by the domain or the publisher is much better than by the brand name" (K-060, K-076). The console still asked for one free-text box and guessed its type, so the domain and the Play link, the two facts that remove all guessing, were typed only sometimes. When an operator did type a Play link together with a domain, the profile carried the package id but not yet the publisher's exact store name (the Play fetch can fail, and a CSV legal name is not the Play trading name), and the package veto then read the brand's own listing as "official package under a foreign publisher": a takedown against the customer.
Decision: The single-scan form has three labelled fields: brand name, official domain (the trust anchor), Google Play link or package id. Any one is enough; all three build the profile exactly as typed, with no guessing (`resolve_structured`; batch lines accept `Name | domain | link`). Typed facts are merged into an existing brand and make it operator-edited. A typed name removes the "guessed from the domain label" review note. In triage, an official package id on a store that enforces unique package ids (Google Play) is by itself the official identity: the publisher veto fires without a name match and its text asks to add the unfamiliar publisher name to the profile; the package veto can no longer fire on Play for an official id (it still does on mirrors, where any id can be carried).
Rationale: Nobody but the owner can publish under a package id on Play (already the K-032/K-055 verifier). Treating an unknown publisher name as a foreign one made the missing fact (the name) worse than a wrong one. The three fields turn the operator's best knowledge into the profile at the moment of scanning instead of after a review round.
Status: active

## K-078: The model reads the listing text and answers questions; the code keeps the decision
Context: The operator's verdict after three live rounds: "the LLM does not add much clarity". Correct, and structural: the adjudicator received eleven booleans and enums (K-014's injection rule kept attacker text away from the model entirely) and re-derived from them the decision the rules had already made from the same features. Meanwhile the one error class that survived three rounds of rules, the namesake/companion/affiliate split (Wise, Pegasus, Vodafone Greece, Binance Ninja, K-016), is precisely a reading problem: what is this description about? Records whose score fell just under the grey band were labelled uncertain by T0 without ever reaching T2 at all.
Decision: T2 becomes a text reader (`triage/reader.py`). The model sees name, publisher, website host and a description excerpt capped at 1200 characters, cleaned of control characters and angle brackets, inside a data block delimited by a per-call random tag and declared untrusted. It answers fixed questions with enum answers (subject: brand_service / companion / namesake / unrelated / unclear; claims_official; asks_credentials; names_brand; embedded_instructions; language), one quote that must occur verbatim in the excerpt, and one capped note stripped of URLs and dropped if it reads as an instruction. `derive_leaning` turns answers plus hard facts (publisher on the official list, verified, permissions, account age, name relation) into the leaning; the model never emits a label. The opinion re-enters fusion dampened exactly as before: it can settle a benign case (adjudicated_benign) but not provide the independent backing a takedown needs, so a phishing text from an established publisher stays suspicious for a person. A reply reporting embedded instructions collapses every other answer to unclear and leans impersonation at 0.35 (an honest listing does not address the reader); a self-contradictory reply is downgraded. Uncertain records T0 did not escalate now reach T2 too. Readings are cached by a hash of model, prompt version and case. Findings carry a 600-character excerpt plus permissions, account age and app count so exports replay (`scripts/replay_t2.py`). The console shows the reader's lines and the excerpt, marked untrusted. Brand resolution stays deterministic: the official-domain anchor is the one place a confident wrong model answer would poison every later decision, and the three-field form (K-077) already lets the operator supply it.
Rationale: The rules cannot read; the model cannot be trusted with the decision. Splitting the work along that line gives the model the only thing it is better at (language) and keeps every property the threat model demands: no veto, no label, no independent backing, bounded and validated output, and an explicit signal when the text tries to talk to the reader.
Status: active

## K-079: Mirror copies of the brand's app bypass the reader; App Store hits are looked up
Context: The first live run of the text reader (TikTok, gpt-4o-mini, 59 readings) showed three things. (1) 44 mirror pages of TikTok's own apps ("TikTok Lite APK for Android Download" on apkpure, "TikTok 46.2.3 by TikTok Pte. Ltd." on apkmirror) were read as namesakes ("a different product that shares the name") and filed as noise; the rule adjudicator had been doing the same before, so unauthorized copies of the brand's app had been invisible for weeks. (2) Four App Store pages of TikTok's own iOS apps sat in "suspicious" as unverifiable mirror copies, because a search snippet carries no seller. (3) The model reported install instructions for users ("simply download the APK, then open the file") as instructions aimed at the reader, four times.
Decision: (1) A hit on a mirror host whose title names the brand identity (brand word, official app title, domain label) and carries no build marker is a mirror listing: it is decided before T2 as uncertain with the mirror explanation, at confidence 0.25 so it sorts under the genuinely undecided rows, and is never read or settled benign. The reader gained a "brand_app" subject for the same situation elsewhere; a "namesake" answer that admits the text talks about the brand, or whose title carries an official app title, is corrected in code. (2) apps.apple.com is a store, not a mirror: hits are resolved through the keyless iTunes Lookup API (seller, seller website, bundle id, description) and judged like any listing; the App Store joins Google Play as a unique-id store, so an official bundle id proves identity. This is the first piece of the App Store source. (3) A reported injection is believed only when the text contains reader-directed language (ignore previous instructions, you are the analyst, mark this as, Turkish equivalents); otherwise the report is dropped and the other answers stand.
Rationale: The reader is for language questions; whether a mirror's APK is untouched is not one, so no reading can settle it and the honest label is fixed in advance. Apple's metadata is one cheap request away and turns a guess into a verified listing. An injection detector that fires on how-to text would push ordinary mirrors toward impersonation, which is the false-positive direction the threat model forbids.
Status: active

## K-080: Three-brand live round after the reader: publisher names without legal tails, mirror copies decided once, companion names are not affiliates
Context: Spotify, Getir and TikTok with three typed fields each (v3.6). The reader's cost fell as intended (TikTok 59 readings to 3) and the App Store lookup verified six of TikTok's iOS apps. What remained: (1) "Spotify: Music and Podcasts" on the App Store, seller "Spotify", website spotify.com, read as a possible impersonation because the profile knows "Spotify AB"; (2) "Download Spotify 9.1.84 | Uptodown" filed as related while "Spotify for Android - Uptodown" was a mirror copy, the same page class split by whether T0 happened to find it benign; (3) "Getir Parca" (auto parts) and "Spotify Songs Downloader" called mirror copies because their titles carry the brand word; (4) "Notify for Spotify" by an individual read as an affiliate because its website carries the word; (5) App Store developer pages looked up as apps; (6) a duplicate mirror line; (7) the model calling getirfinans "unrelated" while admitting the text is about Getir.
Decision: Publisher names match with or without a legal suffix (AB, Pte. Ltd., A.S., Inc...), and a website under an official domain counts as identity for the reader's leaning (the veto still needs its verifier). Mirror detection runs after T0 for every non-veto outcome and requires an empty title residue (title words that are neither the brand's own words nor mirror noise: download verbs in six languages, platform words, store names, product-category words) and no companion word; titles with a residue go to the reader, and a reader answer of "brand_app" on a non-store source becomes the same mirror_unverified outcome. Companion-shaped names are never affiliates. Only /app/ URLs are looked up on the App Store. An "unrelated" answer that names the brand is downgraded like a namesake. The console gains "Hide mirror copies" so the analyst can look past unauthorized distribution to the rest.
Rationale: Each of these was a place where two identical situations got two answers depending on an accident (a legal tail, T0's score, a shared verb). A product is judged on consistency more than on any one label; the fixes make one class of page get one answer, and keep the model where it belongs, behind the code.
Status: active

## K-081: A shared brand word is measured by reading, and everything that rests on the bare word is read too
Context: Wise, the dictionary-word brand we had declared a known limit, with three typed fields. Eight "malicious" rows, every one a mod of a namesake ("Doctor Wise", "Wise PDF", "Wise Timetable"); ten "Affiliate?" rows that were all namesakes (Wise Vets, Wise Finwealth, Wise&Rise...); bare-word mirror pages ("Wise APK for Android Download") called copies of the brand's app when apkpure lists a dozen Wise apps. The K-075 measure had said the word was not shared (0) because it excludes publishers that carry the word, and for a dictionary word every namesake does. Meanwhile the reader had read those very listings and said, correctly, "namesake, brand not named". Separately, Trendyol never ran: its package id is literally "trendyol.com", which the store field read as a domain, and the batch's error line was gone after a reload because errors lived only in the creation response.
Decision: The Play run counts, after triage, the non-official publishers whose brand-leading app the reader found to be about something else, and the larger of the two measures becomes brand_word_shared_by. When the word is shared: a mod that names none of the brand's other identity words is read before it is left for review (a namesake's mod is noise; a text describing the brand's own app restores the takedown); a bare-word mirror page is a copy only when its title carries one of the brand's own app titles or its URL an official package id, otherwise the reader decides. A reader answer of "brand not named" suppresses the affiliate hint and any credential claim. Official apps' English titles are fetched once per scan and handed to the APK-site run, since mirrors and the App Store use them. A store field that looks like a domain is checked on Play as a package id; batch errors are stored with the batch.
Rationale: The name-only measure could not tell a subsidiary from a namesake, so it stayed silent and the veto fired on the word. The reader can tell, from the one thing a namesake cannot fake: a description that never mentions the brand. Using that reading as a measurement keeps the model where K-078 put it (it answers a question about text) while removing the last class of false takedowns we knew about.
Status: active

---

# Tried and Abandoned

| Tried | Observed | Why dropped / what replaced it | Branch | Phase |
| CSV run log in plain utf-8 | Turkish bank names looked garbled in some Windows viewers | Switched to utf-8-sig (BOM) so Excel and PowerShell read it correctly | feat/watchlist | Watchlist |
| Package veto keyed only on 'publisher veto did not fire' | On live data an official app with an unverified official publisher was flagged repackaged | Also skip when publisher name matches official list (K-032) | fix/package-veto-official-name | Triage |
| First live adapter (strict field access) | Real Play returned types our schema rejected; one bad listing dropped a whole query | Per-record isolation + defensive coercion (K-029) | feat/live-source | Discovery |
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
- Bank affiliates surface as detected until allowlisted. On live website/crt.sh runs, a brand's own foreign subsidiaries and sister entities (garantibbva.ro, garantibank.ro, vakifbank.de, vakifyatirim.com.tr) are close enough to the official domain to be lookalikes but are legitimate. They are cleared per brand via known_affiliates (K-049); the Ziraat profile is done, the other bank profiles still need their affiliate lists filled in. Until then those entries show as detected, not as real phishing. No Turkish bank surfaced a genuine active impersonation on either source; the banks are well policed and quickly clean up, so a clean result there is correct, and the genuine detections are on heavily targeted global brands (Binance 13 lookalikes on crt.sh; GTA/Netflix/Spotify modded builds on Serper).
- App-side mod/cracked detection keys on the app name and package id, not page content. A search hit that is actually an article or a government download page ("how-to-download-...-mod", a gov.in page) is excluded by a non-app-page URL guard rather than by inspecting the page. Fetching each page to confirm a download button or a login form is the more precise but more expensive and riskier route (connecting to a suspected phishing/mod site), left as an extension point.
- Store developer websites and e-mails are self-declared. Since K-055 they identify a publisher only together with 100k+ installs or an official package id on Play; a source that reports no install figure still accepts the website alone, because there is nothing to check the claim against there.
- Evaluation drift since the K-025/K-026/K-031 figures: on 2026-09-24 the development set has 45 records and impersonation recall is 0.882 (15 of 17), not the 0.938 (15 of 16) recorded then; one impersonation record added to the set since defers to uncertain, as does "Puan Kazan" (K-025). Takedown FP and missed threats are still 0%, and K-055/K-056 left every label unchanged (measured before and after). Which record changed and why is not yet traced; the older entries keep their original numbers as a record of that day.
- Registry review lines can name a neighbouring brand's app when a publisher's legal name contains the brand's words: "Aras Kargo Yurt Ici Ve Yurt Disi Tasimacilik A.S." is listed under Yurtici Kargo. Review lines are never written into a profile, so this is noise for the analyst, not a wrong verdict.
- Unauthorized-build veto on live Serper data (2026-09-24, 19-brand sweep): three takedown candidates, all on apk.dog (papara.apk.dog, btcturk-bitcoin-al-sat.apk.dog, a Trendyol seller-panel page), labelled repackaged 0.95 because the page title carries "(MOD)"; no bank and no official mirror was flagged. apk.dog titles every page "(MOD) APK", even unrelated ones, so the marker proves the site advertises a modified build, not that the file is modified; only an APK signature comparison would (With One More Month, item 2). The 0.95 confidence of this veto has never been calibrated on live data, since the evaluation set is mock data.
- The unauthorized-build evidence line says "from a non-official publisher" even when the source gives no publisher at all (every Serper hit); "unknown publisher" is the accurate wording (the K-026 principle: evidence must state facts). It also omits the matched title, which the analyst needs to check the call.
- SEO spam on unrelated sites that uses a brand name (easemytrip.com/lottery/..., easemytrip.com/casino/..., asqa.gov.af/prices/...-referral-codes) comes back from Serper as third_party_legitimate. No takedown risk, but the label is wrong: these are not app listings. The K-052 non-app-page guard could also drop lottery, casino and referral-code paths; the website track is the right place to judge them as pages.

---

# With One More Month


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

3. **Real discovery against one live source, rate-limited.** (Since done: live
   Google Play, Serper and crt.sh sources, K-028 to K-056.) The query expander's
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

