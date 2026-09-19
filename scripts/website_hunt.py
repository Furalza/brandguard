"""Hunt for impersonating websites of a brand (Phase 2a).

    python scripts/website_hunt.py --profile data/watchlist/ziraat.json

Generates lookalike domain variants of the brand's official domain, searches
the web for the brand used off its official domain, and classifies each by
domain similarity. Lookalikes and confirmed-live hits are shown first.

Requires SERPER_API_KEY and: pip install -e ".[serper]"
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from brandguard.discovery.serper_source import get_serper_client
from brandguard.discovery.website_hunt import DomainVerdict, hunt_websites
from brandguard.schema import BrandProfile

_ORDER = {DomainVerdict.LOOKALIKE: 0, DomainVerdict.MENTIONS_BRAND: 1,
          DomainVerdict.OFFICIAL: 2, DomainVerdict.UNRELATED: 3}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--num", type=int, default=10)
    parser.add_argument("--max-queries", type=int, default=3)
    args = parser.parse_args()

    profile = BrandProfile(**json.loads(args.profile.read_text(encoding="utf-8")))
    if not profile.official_domains:
        raise SystemExit("profile has no official_domains to compare against")

    print(f"hunting impersonating websites for {profile.brand_name} ...")
    client = get_serper_client()
    findings = hunt_websites(profile.brand_name, profile.official_domains,
                             client=client, num=args.num, max_queries=args.max_queries)

    findings.sort(key=lambda f: (_ORDER.get(f.verdict, 9), -f.similarity, not f.confirmed_live))
    print(f"{len(findings)} candidate domains\n")
    for f in findings:
        live = "LIVE" if f.confirmed_live else "generated"
        flag = "  [REVIEW]" if f.verdict == DomainVerdict.LOOKALIKE and f.confirmed_live else ""
        print(f"{f.verdict.value:<12}{f.similarity:<7}{live:<11}{f.domain}{flag}")
        for line in f.evidence:
            print(f"    - {line}")


if __name__ == "__main__":
    main()
