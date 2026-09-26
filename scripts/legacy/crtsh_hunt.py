"""Hunt for lookalike domains in Certificate Transparency logs (crt.sh).

    python scripts/crtsh_hunt.py --profile data/watchlist/ziraat.json
    python scripts/crtsh_hunt.py --brand "Binance" --official-domain binance.com

Queries crt.sh for the brand's distinctive token, classifies every domain that
ever got a certificate against the official domain (D0 similarity), then enriches
live lookalikes with WHOIS age and certificate signals (D1) and orders them by
review priority. This looks where real impersonations surface first: the moment
they obtain TLS.

No API key needed. crt.sh can be slow; be patient. Requires ".[serper,whois]"
for the enrichment step (requests + python-whois).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from brandguard.discovery.crtsh_source import brand_token_of, search_crtsh
from brandguard.discovery.website_hunt import (
    DomainFinding,
    DomainVerdict,
    classify_domain,
    enrich_live_lookalikes,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=None)
    parser.add_argument("--brand", default=None)
    parser.add_argument("--official-domain", default=None)
    parser.add_argument("--max", type=int, default=200, help="cap domains classified")
    args = parser.parse_args()

    if args.profile:
        prof = json.loads(args.profile.read_text(encoding="utf-8"))
        brand = prof["brand_name"]
        official = prof["official_domains"]
    else:
        if not args.brand or not args.official_domain:
            raise SystemExit("provide --profile, or both --brand and --official-domain")
        brand = args.brand
        official = [args.official_domain]

    token = brand_token_of(brand)
    print(f"querying crt.sh for token {token!r} (brand: {brand}) ...")
    ct_domains = search_crtsh(token)
    print(f"{len(ct_domains)} distinct domains in CT logs\n")
    if not ct_domains:
        print("no results (crt.sh may be rate-limiting; retry shortly)")
        return

    # D0: classify each CT domain against the official domain(s).
    findings: list[DomainFinding] = []
    for ct in ct_domains[: args.max]:
        f = classify_domain(ct.domain, official, brand)
        # CT-observed domains provably exist (they have a cert), so mark live.
        findings.append(DomainFinding(
            f.domain, f.verdict, f.similarity,
            [*f.evidence, f"Seen in CT logs, first cert {ct.first_seen or 'unknown'}."],
            source_query="crt.sh", confirmed_live=True,
        ))

    # Keep the interesting ones: lookalikes and brand mentions, drop official/noise.
    interesting = [f for f in findings
                   if f.verdict in (DomainVerdict.LOOKALIKE, DomainVerdict.MENTIONS_BRAND)]
    official_hits = [f for f in findings if f.verdict == DomainVerdict.OFFICIAL]

    # D1: enrich live lookalikes with age/cert and priority.
    enriched = enrich_live_lookalikes(interesting)
    prio = {"high": 0, "medium": 1, "low": 2}
    enriched.sort(key=lambda e: (prio[e.priority], -e.finding.similarity))

    print(f"official domains seen: {len(official_hits)}")
    print(f"lookalike / mention candidates: {len(enriched)}\n")
    for e in enriched:
        f = e.finding
        tag = "  [REVIEW]" if f.verdict == DomainVerdict.LOOKALIKE else ""
        print(f"{f.verdict.value:<12}{f.similarity:<7}prio={e.priority:<8}{f.domain}{tag}")


if __name__ == "__main__":
    main()
