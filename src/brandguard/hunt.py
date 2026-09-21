"""Unified hunt command: pick a brand and one or more sources, run, record, show.

    python -m brandguard.hunt --profile data/watchlist/ziraat.json --source crtsh
    python -m brandguard.hunt --brand "Binance" --official-domain binance.com --source crtsh,website
    python -m brandguard.hunt --profile data/watchlist/akbank.json --source play,serper

Every run is saved under results/ with an ISO UTC timestamp and appended to
results/run_log.csv, so runs are comparable across sources and over time. Use
scripts/watchlist_diff.py on two result files to see what changed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from brandguard.hunt_engine import SOURCES, record_run, run_source
from brandguard.schema import BrandProfile


def _load_profile(args) -> BrandProfile:
    if args.profile:
        return BrandProfile(**json.loads(Path(args.profile).read_text(encoding="utf-8")))
    if not args.brand:
        raise SystemExit("provide --profile or --brand")
    return BrandProfile(
        brand_name=args.brand,
        official_domains=[args.official_domain] if args.official_domain else [],
        official_publishers=[],
        known_official_apps=[],
        sector=args.sector or "unknown",
    )


def _show(result) -> None:
    print(f"\n[{result.source}] {result.brand}  {result.scanned_at}")
    print(f"  {result.candidates} candidates, {result.flagged} flagged")
    for row in result.rows[:25]:
        if "domain" in row:
            tag = "  [REVIEW]" if row["verdict"] == "lookalike" else ""
            print(f"    {row['verdict']:<12}{row.get('priority',''):<8}{row['domain']}{tag}")
        else:
            tag = "  [TAKEDOWN]" if row["label"] in ("impersonation", "repackaged") else ""
            print(f"    {row['label']:<24}{row['confidence']:<6}{row['app_id'][:50]}{tag}")
    if len(result.rows) > 25:
        print(f"    ... and {len(result.rows) - 25} more (full result in the saved JSON)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=None)
    parser.add_argument("--watchlist", type=Path, default=None,
                        help="a directory of profile JSONs; scan every one")
    parser.add_argument("--brand", default=None)
    parser.add_argument("--official-domain", default=None)
    parser.add_argument("--sector", default=None)
    parser.add_argument("--source", required=True,
                        help=f"comma-separated, one or more of: {', '.join(SOURCES)}")
    parser.add_argument("--results", type=Path, default=Path("results"))
    args = parser.parse_args()

    sources = [s.strip() for s in args.source.split(",") if s.strip()]
    for s in sources:
        if s not in SOURCES:
            raise SystemExit(f"unknown source {s!r}, expected one of {', '.join(SOURCES)}")

    # A watchlist directory scans every profile in it; otherwise a single brand.
    if args.watchlist:
        profiles = sorted(args.watchlist.glob("*.json"))
        if not profiles:
            raise SystemExit(f"no profiles in {args.watchlist}")
        brands = [BrandProfile(**json.loads(p.read_text(encoding="utf-8"))) for p in profiles]
    else:
        brands = [_load_profile(args)]

    for profile in brands:
        for source in sources:
            print(f"running {source} for {profile.brand_name} ...")
            try:
                result = run_source(profile, source)
            except Exception as exc:  # noqa: BLE001 - one source/brand failing must not stop the sweep
                print(f"  ! {source} for {profile.brand_name} failed ({type(exc).__name__}); skipping")
                continue
            path = record_run(result, args.results)
            _show(result)
            print(f"  saved: {path}")


if __name__ == "__main__":
    main()
