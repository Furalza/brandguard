"""Unified hunting engine.

One interface over every discovery source (mock, live Google Play, Serper,
website domains, Certificate Transparency), each producing a timestamped,
recorded run that can be compared over time. This is the operational layer a
real DRP platform exposes: pick a brand and a source, get a saved, auditable
result, and track how a brand's exposure changes between runs.

A source is a callable that takes a BrandProfile and returns a list of Verdict
(for app sources) or is adapted into one (for domain sources, whose findings are
mapped onto the same recorded shape). Recording is uniform: one JSON per run
under results/, one summary row in results/run_log.csv, both keyed by an ISO
UTC timestamp, the brand and the source, so runs are comparable across sources
and over time.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from brandguard.schema import BrandProfile

# A source name maps to a runner that produces recorded rows for a brand.
SOURCES = ("play", "serper", "website", "crtsh")

_TAKEDOWN = {"impersonation", "repackaged"}
_HIGH_DOMAIN = {"lookalike"}


@dataclass(frozen=True)
class RunResult:
    """The uniform, recordable result of one hunt run."""

    brand: str
    source: str
    scanned_at: str
    candidates: int
    flagged: int          # takedown candidates (apps) or lookalikes (domains)
    rows: list[dict]      # analyst-facing records, source-specific but JSON-safe


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")


# ---- Source runners -------------------------------------------------------
# Each returns (rows, flagged_count). They are thin wrappers over the discovery
# modules, so the engine stays agnostic to how each source works.


def _run_play(profile: BrandProfile, *, max_queries: int, hits: int, adjudicator) -> tuple[list[dict], int]:
    from brandguard.discovery.live_google_play import search_and_fetch
    from brandguard.discovery.query_expansion import expand
    from brandguard.triage.fusion import triage_t0
    from brandguard.triage.tier2 import triage_t2

    seen: set[str] = set()
    records = []
    for q in [x.term for x in expand(profile.brand_name)][:max_queries]:
        try:
            found = search_and_fetch(q, n_hits=hits)
        except Exception as exc:  # noqa: BLE001
            print(f"    . play query {q!r} skipped ({type(exc).__name__})")
            continue
        for r in found:
            if r.app_id and r.app_id not in seen:
                seen.add(r.app_id)
                records.append(r)

    rows, flagged = [], 0
    for r in records:
        d = triage_t0(r, profile)
        if d.escalate or d.verdict.label.value == "uncertain":
            d = triage_t2(r, profile, d, adjudicator)
        rows.append(d.verdict.to_analyst_json())
        if d.verdict.label.value in _TAKEDOWN:
            flagged += 1
    return rows, flagged


def _run_serper(profile: BrandProfile, *, num: int, max_queries: int, adjudicator) -> tuple[list[dict], int]:
    from brandguard.discovery.serper_source import get_serper_client, search_apks
    from brandguard.triage.fusion import triage_t0
    from brandguard.triage.tier2 import triage_t2

    client = get_serper_client()
    records = search_apks(profile.brand_name, client=client, num=num, max_queries=max_queries)
    rows, flagged = [], 0
    for r in records:
        d = triage_t0(r, profile)
        if d.escalate or d.verdict.label.value == "uncertain":
            d = triage_t2(r, profile, d, adjudicator)
        rows.append(d.verdict.to_analyst_json())
        if d.verdict.label.value in _TAKEDOWN:
            flagged += 1
    return rows, flagged


def _domain_rows(enriched) -> tuple[list[dict], int]:
    rows, flagged = [], 0
    for e in enriched:
        f = e.finding
        rows.append({
            "domain": f.domain,
            "verdict": f.verdict.value,
            "similarity": f.similarity,
            "priority": e.priority,
            "confirmed_live": f.confirmed_live,
            "evidence": e.evidence,
        })
        if f.verdict.value in _HIGH_DOMAIN:
            flagged += 1
    return rows, flagged


def _run_website(profile: BrandProfile, *, num: int, max_queries: int) -> tuple[list[dict], int]:
    from brandguard.discovery.serper_source import get_serper_client
    from brandguard.discovery.website_hunt import enrich_live_lookalikes, hunt_websites

    client = get_serper_client()
    findings = hunt_websites(profile.brand_name, profile.official_domains,
                             client=client, num=num, max_queries=max_queries)
    return _domain_rows(enrich_live_lookalikes(findings))


def _run_crtsh(profile: BrandProfile, *, cap: int) -> tuple[list[dict], int]:
    from brandguard.discovery.crtsh_source import brand_token_of, search_crtsh
    from brandguard.discovery.website_hunt import (
        DomainFinding,
        DomainVerdict,
        classify_domain,
        enrich_live_lookalikes,
    )

    token = brand_token_of(profile.brand_name)
    ct = search_crtsh(token)
    findings = []
    for c in ct[:cap]:
        f = classify_domain(c.domain, profile.official_domains, profile.brand_name)
        findings.append(DomainFinding(
            f.domain, f.verdict, f.similarity,
            [*f.evidence, f"Seen in CT logs, first cert {c.first_seen or 'unknown'}."],
            source_query="crt.sh", confirmed_live=True,
        ))
    interesting = [f for f in findings
                   if f.verdict in (DomainVerdict.LOOKALIKE, DomainVerdict.MENTIONS_BRAND)]
    return _domain_rows(enrich_live_lookalikes(interesting))


# ---- Engine ---------------------------------------------------------------


def run_source(profile: BrandProfile, source: str, **kw) -> RunResult:
    """Run one source for a brand and return a uniform RunResult (unrecorded)."""
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}, expected one of {SOURCES}")

    started = _now_iso()
    if source == "play":
        from brandguard.triage.adjudicator import get_adjudicator
        rows, flagged = _run_play(profile, max_queries=kw.get("max_queries", 4),
                                  hits=kw.get("hits", 5), adjudicator=get_adjudicator())
    elif source == "serper":
        from brandguard.triage.adjudicator import get_adjudicator
        rows, flagged = _run_serper(profile, num=kw.get("num", 10),
                                    max_queries=kw.get("max_queries", 6),
                                    adjudicator=get_adjudicator())
    elif source == "website":
        rows, flagged = _run_website(profile, num=kw.get("num", 10),
                                     max_queries=kw.get("max_queries", 4))
    else:  # crtsh
        rows, flagged = _run_crtsh(profile, cap=kw.get("cap", 200))

    return RunResult(
        brand=profile.brand_name, source=source, scanned_at=started,
        candidates=len(rows), flagged=flagged, rows=rows,
    )


def record_run(result: RunResult, results_dir: Path = Path("results")) -> Path:
    """Write a timestamped JSON for the run and append a summary row to the log.

    Returns the path of the per-run JSON. The raw JSON is git-ignored; the log
    is a non-sensitive summary safe to commit. Same convention as the watchlist.
    """
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = result.scanned_at.replace(":", "-").replace("+00-00", "Z")
    fname = f"{stamp}__{_slug(result.brand)}__{result.source}.json"
    out = results_dir / fname
    out.write_text(
        json.dumps(result.__dict__, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    log = results_dir / "run_log.csv"
    new = not log.exists()
    with log.open("a", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["scanned_at", "brand", "source", "candidates", "flagged", "result_file"])
        w.writerow([result.scanned_at, result.brand, result.source,
                    result.candidates, result.flagged, fname])
    return out
