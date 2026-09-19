"""Hunt for impersonating apps on third-party sites via Serper (Google search).

    python scripts/serper_hunt.py --profile data/watchlist/ziraat.json

Runs APK-hunting Google dorks for the brand, turns the results into records,
triages them through the full cascade, and lists takedown candidates first.
This looks where impersonations actually live (third-party APK sites), unlike
the Play scan which sees a well-policed store.

Requires SERPER_API_KEY (in .env or environment) and: pip install -e ".[serper,llm]"
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from brandguard.discovery.serper_source import get_serper_client, search_apks
from brandguard.schema import BrandProfile
from brandguard.triage.adjudicator import get_adjudicator
from brandguard.triage.fusion import triage_t0
from brandguard.triage.tier2 import triage_t2

_TAKEDOWN = {"impersonation", "repackaged"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--num", type=int, default=10)
    parser.add_argument("--max-queries", type=int, default=6)
    args = parser.parse_args()

    profile = BrandProfile(**json.loads(args.profile.read_text(encoding="utf-8")))
    print(f"hunting {profile.brand_name} on third-party sites via Serper ...")

    client = get_serper_client()
    records = search_apks(profile.brand_name, client=client,
                          num=args.num, max_queries=args.max_queries)
    print(f"{len(records)} candidate listings from search\n")

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
        print(f"{v.label.value:<24}{v.confidence:<6}{v.app_id[:60]}{flag}")
        for line in v.to_analyst_json()["evidence"]:
            print(f"    - {line}")


if __name__ == "__main__":
    main()
