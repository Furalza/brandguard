"""Replay exported scans through T2 with and without the text reader (K-078).

Usage:
    python scripts/replay_t2.py exports/*.json            # or a batch .zip
    python scripts/replay_t2.py exports/*.json --only-changed
    python scripts/replay_t2.py exports/*.json --dry-run  # prompts only, no API calls

Every finding of an export carries enough of the listing (facts.description_
excerpt, permissions, account_created, other_app_count, installs) to rebuild
the record. The script runs the app cascade twice over those records, once
with the deterministic RuleAdjudicator and once with the configured model
reader, and prints where the category changed and what the reader said.
Readings are cached, so re-running costs nothing after the first pass.

Findings exported before v3.5 have no description excerpt; they are replayed
with an empty description and flagged as such.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from brandguard.hunt_engine import _triage_records  # noqa: E402
from brandguard.schema import AppRecord, BrandProfile, Publisher  # noqa: E402
from brandguard.triage.adjudicator import RuleAdjudicator, describe_adjudicator, get_adjudicator  # noqa: E402


def _date(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def load_exports(paths: list[str]) -> list[dict]:
    docs: list[dict] = []
    for p in paths:
        path = Path(p)
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as zf:
                for name in zf.namelist():
                    if name.endswith(".json") and name != "summary.json":
                        docs.append(json.load(io.TextIOWrapper(zf.open(name), encoding="utf-8")))
        else:
            docs.append(json.loads(path.read_text(encoding="utf-8")))
    return docs


def rebuild(doc: dict) -> tuple[BrandProfile, list[AppRecord], list[dict], int]:
    b = doc["brand"]
    profile = BrandProfile(
        brand_name=b["brand_name"], official_domains=b.get("official_domains", []),
        official_publishers=b.get("official_publishers", []), known_official_apps=b.get("known_official_apps", []),
        sector=b.get("sector", "unknown"), official_package_ids=b.get("official_package_ids", []),
        known_affiliates=b.get("known_affiliates", []),
    )
    records, originals, missing = [], [], 0
    for f in doc["findings"]:
        if f.get("kind") != "app":
            continue
        x = f.get("extra") or {}
        if "description_excerpt" not in x:
            missing += 1
        records.append(AppRecord(
            app_id=f["key"], source=f["source"], name=f.get("name") or "",
            publisher=Publisher(name=x.get("publisher") or "", website=x.get("website"),
                                account_id=x.get("account_id"), account_created=_date(x.get("account_created")),
                                other_app_count=x.get("other_app_count"), verified=x.get("verified")),
            description=x.get("description_excerpt") or None,
            permissions=list(x.get("permissions") or []), downloads=x.get("installs"),
            published=_date(x.get("released")), last_updated=_date(x.get("updated")),
            raw={"page_kind": x.get("page_kind") or "listing", "bundle_id": x.get("bundle_id")},
        ))
        originals.append(f)
    return profile, records, originals, missing


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("exports", nargs="+")
    ap.add_argument("--only-changed", action="store_true", help="print only rows whose category changed")
    ap.add_argument("--dry-run", action="store_true", help="rebuild and run rules only; no model calls")
    args = ap.parse_args()

    provider, model = describe_adjudicator()
    if provider == "rules" and not args.dry_run:
        print("No ANTHROPIC_API_KEY / OPENAI_API_KEY configured; nothing to compare. Use --dry-run to check the rebuild.")
        return 2
    reader = None if args.dry_run else get_adjudicator()
    print(f"reader: {provider} {model or ''}".rstrip())

    totals = Counter()
    for doc in load_exports(args.exports):
        profile, records, originals, missing = rebuild(doc)
        if not records:
            continue
        rules_rows, _ = _triage_records(records, profile, RuleAdjudicator())
        model_rows = rules_rows if reader is None else _triage_records(records, profile, reader)[0]
        header = f"== {profile.brand_name}  ({len(records)} app findings"
        if missing:
            header += f", {missing} without listing text (exported before v3.5)"
        print(header + ")")
        for orig, rr, mr in zip(originals, rules_rows, model_rows, strict=True):
            changed = rr["category"] != mr["category"]
            totals["rows"] += 1
            totals["changed"] += changed
            if args.only_changed and not changed:
                continue
            mark = "*" if changed else " "
            print(f" {mark} {rr['category']:>10} -> {mr['category']:<10} {orig.get('name') or orig['key']}")
            for e in mr.get("evidence_detail", []):
                if str(e.get("signal", "")).startswith("reader_") or e.get("signal") == "adjudicator":
                    print(f"        - {e['text']}")
        stats = getattr(reader, "stats", None)
        if stats:
            print(f"   reader stats: {stats}")
            for k, v in stats.items():
                totals[f"t2_{k}"] += v
            for k in stats:
                stats[k] = 0
    print()
    print(f"rows: {totals['rows']}, category changed by the reader: {totals['changed']}")
    if reader is not None:
        print(f"model calls: {totals['t2_calls']}, cache hits: {totals['t2_cache_hits']}, "
              f"failures: {totals['t2_failures']}, injections reported: {totals['t2_injections']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
