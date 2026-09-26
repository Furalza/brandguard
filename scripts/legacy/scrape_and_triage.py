"""Scrape live Google Play for a brand and triage the results.

    python scripts/scrape_and_triage.py --profile data/profiles/ornek_bank.json
    python scripts/scrape_and_triage.py --brand "Garanti BBVA" --sector banking

Give it a brand profile, or just a brand name and sector. It expands the brand
into search queries (homoglyphs, typosquats, ...), scrapes Google Play for each,
deduplicates by app id, runs the full cascade, and prints the verdicts, with
takedown candidates first.

This talks to a live, unofficial interface. It may be slow, rate-limited, or
blocked; that is a property of scraping Google Play, not of the triage system.
Requires: pip install -e ".[live,llm]"
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from brandguard.discovery.live_google_play import search_and_fetch
from brandguard.discovery.query_expansion import expand
from brandguard.schema import AppRecord, BrandProfile
from brandguard.triage.adjudicator import get_adjudicator
from brandguard.triage.fusion import triage_t0
from brandguard.triage.tier2 import triage_t2

_TAKEDOWN = {"impersonation", "repackaged"}


def _load_profile(args) -> BrandProfile:
    if args.profile:
        return BrandProfile(**json.loads(Path(args.profile).read_text(encoding="utf-8")))
    if not args.brand:
        raise SystemExit("provide --profile or --brand")
    return BrandProfile(
        brand_name=args.brand,
        official_domains=[],
        official_publishers=[],
        known_official_apps=[],
        sector=args.sector or "unknown",
    )


def gather(profile: BrandProfile, max_queries: int, hits: int) -> list[AppRecord]:
    """Expand the brand into queries and scrape each, deduplicated by app id."""
    queries = [q.term for q in expand(profile.brand_name)][:max_queries]
    seen: set[str] = set()
    records: list[AppRecord] = []
    for term in queries:
        try:
            found = search_and_fetch(term, n_hits=hits)
        except Exception as exc:  # noqa: BLE001 - surface scraping failures
            # Failures here are Google Play returning an unexpected response for
            # a query (often the more exotic homoglyph variants); the scraper
            # raises from inside its own parsing. This is a property of scraping
            # an unofficial interface, not a defect in triage. Skip the query and
            # keep going so one bad query never sinks the run.
            print(f"  . query {term!r} skipped ({type(exc).__name__}: Play returned an unexpected response)")
            continue
        for record in found:
            # A record with no app id cannot be actioned by an analyst; drop it.
            if not record.app_id or record.app_id in seen:
                continue
            seen.add(record.app_id)
            records.append(record)
        print(f"  query {term!r}: {len(found)} hits, {len(records)} unique so far")
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=None)
    parser.add_argument("--brand", default=None)
    parser.add_argument("--sector", default=None)
    parser.add_argument("--max-queries", type=int, default=5, help="cap scraping cost")
    parser.add_argument("--hits", type=int, default=5, help="results per query")
    args = parser.parse_args()

    profile = _load_profile(args)
    print(f"brand: {profile.brand_name}  sector: {profile.sector}")
    print("gathering from Google Play (live)...")
    records = gather(profile, args.max_queries, args.hits)
    print(f"\n{len(records)} unique candidate listings\n")

    adjudicator = get_adjudicator()
    verdicts = []
    for record in records:
        decision = triage_t0(record, profile)
        if decision.escalate or decision.verdict.label.value == "uncertain":
            decision = triage_t2(record, profile, decision, adjudicator)
        verdicts.append(decision.verdict)

    verdicts.sort(key=lambda v: (v.label.value not in _TAKEDOWN, -v.confidence))
    for v in verdicts:
        flag = "  [TAKEDOWN CANDIDATE]" if v.label.value in _TAKEDOWN else ""
        print(f"{v.label.value:<24}{v.confidence:<6}{v.app_id}{flag}")
        for line in v.to_analyst_json()["evidence"]:
            print(f"    - {line}")


if __name__ == "__main__":
    main()
