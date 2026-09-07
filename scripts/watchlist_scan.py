"""Watchlist runner: scan several brands and record timestamped results.

Runs the full cascade for every brand profile in a watchlist directory against a
named platform (currently Google Play), writes one timestamped result file per
brand, and appends a one-line summary to a run log. This turns the system from a
one-off script into something you can run on a schedule and track over time:
when did we scan, what did we find, what changed since last time.

    python scripts/watchlist_scan.py
    python scripts/watchlist_scan.py --watchlist data/watchlist --platform google_play

Results layout:
    results/<UTC timestamp>__<brand>__<platform>.json   (git-ignored, raw)
    results/run_log.csv                                 (committed, summary only)

The raw results are git-ignored because they contain real publisher data and
grow over time; the run log is a non-sensitive summary safe to commit. See the
README in results/ and K-033.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from brandguard.discovery.live_google_play import search_and_fetch
from brandguard.discovery.query_expansion import expand
from brandguard.schema import AppRecord, BrandProfile
from brandguard.triage.adjudicator import get_adjudicator
from brandguard.triage.fusion import triage_t0
from brandguard.triage.tier2 import triage_t2

_TAKEDOWN = {"impersonation", "repackaged"}


def _gather(profile: BrandProfile, max_queries: int, hits: int) -> list[AppRecord]:
    queries = [q.term for q in expand(profile.brand_name)][:max_queries]
    seen: set[str] = set()
    records: list[AppRecord] = []
    for term in queries:
        try:
            found = search_and_fetch(term, n_hits=hits)
        except Exception as exc:  # noqa: BLE001 - scraping an unofficial interface
            print(f"    . query {term!r} skipped ({type(exc).__name__})")
            continue
        for record in found:
            if not record.app_id or record.app_id in seen:
                continue
            seen.add(record.app_id)
            records.append(record)
    return records


def scan_brand(
    profile: BrandProfile,
    platform: str,
    max_queries: int,
    hits: int,
) -> dict:
    """Scan one brand and return a structured, timestamped result."""
    adjudicator = get_adjudicator()
    started = datetime.now(tz=UTC)
    records = _gather(profile, max_queries, hits)

    verdicts = []
    for record in records:
        decision = triage_t0(record, profile)
        if decision.escalate or decision.verdict.label.value == "uncertain":
            decision = triage_t2(record, profile, decision, adjudicator)
        verdicts.append(decision.verdict)

    takedown = [v for v in verdicts if v.label.value in _TAKEDOWN]
    return {
        "brand": profile.brand_name,
        "platform": platform,
        "scanned_at": started.isoformat(),
        "adjudicator": type(adjudicator).__name__,
        "candidates": len(verdicts),
        "takedown_candidates": len(takedown),
        "verdicts": [v.to_analyst_json() for v in verdicts],
    }


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watchlist", type=Path, default=Path("data/watchlist"))
    parser.add_argument("--platform", default="google_play")
    parser.add_argument("--results", type=Path, default=Path("results"))
    parser.add_argument("--max-queries", type=int, default=4)
    parser.add_argument("--hits", type=int, default=5)
    args = parser.parse_args()

    profiles = sorted(args.watchlist.glob("*.json"))
    if not profiles:
        raise SystemExit(f"no profiles in {args.watchlist}")

    args.results.mkdir(parents=True, exist_ok=True)
    log_path = args.results / "run_log.csv"
    new_log = not log_path.exists()

    with log_path.open("a", newline="", encoding="utf-8") as log_file:
        writer = csv.writer(log_file)
        if new_log:
            writer.writerow(
                ["scanned_at", "brand", "platform", "candidates",
                 "takedown_candidates", "adjudicator", "result_file"]
            )

        for profile_path in profiles:
            profile = BrandProfile(**json.loads(profile_path.read_text(encoding="utf-8")))
            print(f"scanning {profile.brand_name} on {args.platform} ...")
            result = scan_brand(profile, args.platform, args.max_queries, args.hits)

            stamp = result["scanned_at"].replace(":", "-").replace("+00-00", "Z")
            fname = f"{stamp}__{_slug(profile.brand_name)}__{args.platform}.json"
            out = args.results / fname
            out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

            writer.writerow([
                result["scanned_at"], result["brand"], result["platform"],
                result["candidates"], result["takedown_candidates"],
                result["adjudicator"], fname,
            ])
            print(f"    {result['candidates']} candidates, "
                  f"{result['takedown_candidates']} takedown -> {fname}")

    print(f"\nrun log: {log_path}")


if __name__ == "__main__":
    main()
