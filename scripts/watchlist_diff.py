"""Compare two watchlist result files for the same brand and platform.

Shows what changed between two scans: new listings, disappeared listings, and
verdicts that changed label. This is the point of keeping timestamped results:
tracking a brand's marketplace footprint over time.

    python scripts/watchlist_diff.py results/<older>.json results/<newer>.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _index(result: dict) -> dict[str, dict]:
    return {v["app_id"]: v for v in result["verdicts"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old", type=Path)
    parser.add_argument("new", type=Path)
    args = parser.parse_args()

    old = json.loads(args.old.read_text(encoding="utf-8"))
    new = json.loads(args.new.read_text(encoding="utf-8"))
    old_v, new_v = _index(old), _index(new)

    print(f"{old['brand']} on {old['platform']}")
    print(f"  {old['scanned_at']}  ->  {new['scanned_at']}\n")

    appeared = [a for a in new_v if a not in old_v]
    disappeared = [a for a in old_v if a not in new_v]
    changed = [
        a for a in new_v if a in old_v and old_v[a]["label"] != new_v[a]["label"]
    ]

    if appeared:
        print("NEW listings:")
        for a in appeared:
            print(f"  + [{new_v[a]['label']}] {a}")
    if disappeared:
        print("GONE listings:")
        for a in disappeared:
            print(f"  - [{old_v[a]['label']}] {a}")
    if changed:
        print("CHANGED verdicts:")
        for a in changed:
            print(f"  ~ {a}: {old_v[a]['label']} -> {new_v[a]['label']}")
    if not (appeared or disappeared or changed):
        print("no change between the two scans")


if __name__ == "__main__":
    main()
