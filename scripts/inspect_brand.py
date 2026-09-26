"""Inspect a brand on Google Play to help build an accurate profile.

Before triaging, you need a correct brand profile: the real official publisher
name, package ids, and website as Google Play reports them. Guessing these makes
the veto wrong. This tool searches Play for a brand and prints the publisher and
package id of each hit, so you can copy the real values into a profile JSON.

    python scripts/inspect_brand.py "Ziraat Bankasi"

Then build data/profiles/<brand>.json from the values it shows, and run:

    python -m brandguard.hunt --source play --profile data/profiles/<brand>.json

Requires: pip install -e ".[live]"
"""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("brand", help="brand name to search on Google Play")
    parser.add_argument("--hits", type=int, default=10)
    parser.add_argument("--lang", default="tr")
    parser.add_argument("--country", default="tr")
    args = parser.parse_args()

    from brandguard.discovery.play_search import search  # keeps the top result (K-056)

    hits = search(args.brand, n_hits=args.hits, lang=args.lang, country=args.country)
    print(f"Top {len(hits)} results for {args.brand!r}:\n")
    print(f"{'publisher':<34}{'app id':<40}title")
    print("-" * 100)
    publishers: dict[str, int] = {}
    for h in hits:
        dev = str(h.get("developer") or "?")
        app_id = str(h.get("appId") or "?")
        title = str(h.get("title") or "?")
        publishers[dev] = publishers.get(dev, 0) + 1
        print(f"{dev[:33]:<34}{app_id[:39]:<40}{title[:30]}")

    print("\nPublishers seen (a brand's official one usually appears on its core apps):")
    for dev, count in sorted(publishers.items(), key=lambda x: -x[1]):
        print(f"  {count}x  {dev}")

    print(
        "\nBuild a profile like this (fill official_* from the real values above):\n"
        '{\n'
        f'  "brand_name": "{args.brand}",\n'
        '  "official_domains": ["<from the publisher website>"],\n'
        '  "official_publishers": ["<the exact publisher string above>"],\n'
        '  "known_official_apps": ["<official app titles>"],\n'
        '  "sector": "banking",\n'
        '  "official_package_ids": ["<official app ids above>"],\n'
        '  "official_permissions": null\n'
        '}'
    )


if __name__ == "__main__":
    main()
