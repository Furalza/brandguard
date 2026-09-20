"""Certificate Transparency (crt.sh) source for lookalike-domain discovery.

Every TLS certificate is published to public CT logs. crt.sh lets us query them,
so searching a brand name returns every domain that ever obtained a certificate
containing that string, including impersonating domains an attacker registered
and gave TLS. This is far deeper than a web search: a phishing domain surfaces
here the moment it gets a certificate, before it ranks in Google or gets
reported. It is the richest free source of real lookalikes.

No API key, no cost. crt.sh can be slow or rate-limit; failures are surfaced,
not hidden. Results feed the existing domain cascade (D0 similarity, D1 whois/
ssl, D2 adjudicator), so this module only discovers, it does not classify.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class CtDomain:
    """A domain observed in a certificate transparency log."""

    domain: str
    first_seen: str | None


def _clean(name: str) -> str:
    """Normalize a CT name entry to a bare hostname."""
    name = name.strip().lower().lstrip("*.")
    return name.split("\n")[0].strip()


def _fetch_crtsh(brand_token: str, timeout: float) -> list[dict] | None:
    """One crt.sh request. Returns parsed rows, [] for a definite empty result,
    or None to signal a retryable condition (rate limit, timeout, bad body)."""
    import requests

    url = f"https://crt.sh/?q=%25{brand_token}%25&output=json"
    try:
        response = requests.get(url, timeout=timeout, headers={"User-Agent": "brandguard/1.0"})
    except requests.RequestException:
        return None  # network hiccup: retryable
    if response.status_code == 429:
        return None  # rate limited: retryable
    if response.status_code != 200:
        return []     # a real non-OK status: treat as empty, not retryable
    body = response.text.strip()
    if not body:
        return None   # crt.sh often returns an empty body under load: retryable
    try:
        return response.json()
    except (json.JSONDecodeError, ValueError):
        return None   # partial/garbled body under load: retryable


def search_crtsh(
    brand_token: str,
    *,
    timeout: float = 30.0,
    retries: int = 3,
    base_delay: float = 2.0,
) -> list[CtDomain]:
    """Return distinct domains from crt.sh whose certificate names contain the token.

    ``brand_token`` should be the distinctive part of the brand (e.g. "ziraat",
    "binance"), not the full domain, so lookalikes on other TLDs and with extra
    words are caught.

    crt.sh is a free service that frequently rate-limits or returns an empty body
    under load. Retryable conditions (429, timeout, empty/garbled body) are
    retried with exponential backoff (base_delay, x2 each time); a definite empty
    result or a real error status is returned as an empty list. This keeps the
    common "temporarily throttled" case from looking like "no lookalikes exist".
    """
    import time

    rows: list[dict] | None = None
    for attempt in range(retries + 1):
        rows = _fetch_crtsh(brand_token, timeout)
        if rows is not None:
            break                       # got a definite answer (data or real empty)
        if attempt < retries:
            time.sleep(base_delay * (2 ** attempt))   # 2s, 4s, 8s
    if not rows:                        # None after all retries, or genuinely empty
        return []

    seen: set[str] = set()
    out: list[CtDomain] = []
    for row in rows:
        for field in ("common_name", "name_value"):
            value = row.get(field) or ""
            for entry in value.split("\n"):
                host = _clean(entry)
                if host and "." in host and host not in seen:
                    seen.add(host)
                    out.append(CtDomain(domain=host, first_seen=row.get("not_before")))
    return out


def brand_token_of(brand_name: str) -> str:
    """Pick the distinctive token to query crt.sh with.

    Uses the longest normalized token of the brand name, since that is usually
    the distinctive part (e.g. "ziraat" from "Ziraat Bankasi", not "bankasi").
    """
    from brandguard.discovery.normalize import tokens

    parts = tokens(brand_name)
    generic = {"bank", "bankasi", "banka", "mobil", "app", "kargo", "market", "pay"}
    distinctive = [p for p in parts if p not in generic]
    pool = distinctive or parts
    return max(pool, key=len) if pool else ""
