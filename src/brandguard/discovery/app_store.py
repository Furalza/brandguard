"""Apple App Store enrichment through the public iTunes Lookup API (K-079).

Google search hits on apps.apple.com are store listings, not mirrors: Apple
runs the store, sets the seller name from the developer account and keeps
one bundle id per app. But a search snippet carries none of that, so until
now an App Store page of the brand's own iOS app was triaged as an
unverifiable copy and landed in "suspicious" (found live on TikTok: four
App Store pages of TikTok's own apps).

The Lookup API needs no key: ``https://itunes.apple.com/lookup?id=<id>``
returns the seller, the seller's website, the bundle id, the description
and the release date. With those the ordinary publisher veto applies: the
seller on the official list plus a website on an official domain is the
brand's own listing; a different seller is judged like any other publisher.

This is the first step of an App Store source. Search across the store
(the same API takes ``term=``) is the next one; enrichment of hits we
already have costs nothing and removes a whole class of false suspicion.
"""

from __future__ import annotations

import re
import time
from datetime import date
from typing import Protocol
from urllib.parse import urlparse

from brandguard.schema import AppRecord, Publisher

SOURCE = "app_store"
# App pages only: a /developer/ page is a seller's catalogue, not a listing.
_STORE_URL = re.compile(r"apps\.apple\.com/(?:([a-z]{2})/)?app/(?:[^/]+/)?id(\d+)", re.IGNORECASE)
_MAX_LOOKUPS = 30          # per run; Apple throttles around 20 requests a minute
_PACE_S = 0.35
_TIMEOUT_S = 10.0


class LookupClient(Protocol):
    def lookup(self, store_id: str, country: str) -> dict | None: ...


class ItunesLookupClient:
    """The real client. ``requests`` is imported lazily like the other sources."""

    def lookup(self, store_id: str, country: str) -> dict | None:
        import requests

        response = requests.get(
            "https://itunes.apple.com/lookup",
            params={"id": store_id, "country": country},
            timeout=_TIMEOUT_S,
            headers={"User-Agent": "brandguard/1.0"},
        )
        response.raise_for_status()
        results = (response.json() or {}).get("results") or []
        return results[0] if results else None


def parse_store_url(link: str) -> tuple[str, str] | None:
    """(store_id, country) from an apps.apple.com URL, or None."""
    m = _STORE_URL.search(link or "")
    if not m:
        return None
    return m.group(2), (m.group(1) or "us").lower()


def _date(value: object) -> date | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def record_from_lookup(link: str, data: dict) -> AppRecord:
    """An AppRecord for one App Store listing, keyed by its canonical URL.

    The URL stays the app id so the analyst's link works and the search hit
    dedupes against it; the bundle id (unique per app on the store) travels
    in ``raw`` for the package check.
    """
    seller = (data.get("sellerName") or data.get("artistName") or "").strip()
    return AppRecord(
        app_id=link,
        source=SOURCE,
        name=(data.get("trackName") or data.get("trackCensoredName") or "").strip()
        or f"App Store listing id{data.get('trackId') or ''}",
        # artistId is Apple's developer-account id: unique per account like
        # Play's developerId, so the same-account rule (K-062) applies.
        publisher=Publisher(name=seller, website=data.get("sellerUrl") or None,
                            account_id=f"apple:{data['artistId']}" if data.get("artistId") else None),
        description=data.get("description"),
        icon_url=data.get("artworkUrl512") or data.get("artworkUrl100"),
        rating=data.get("averageUserRating"),
        review_count=data.get("userRatingCount"),
        published=_date(data.get("releaseDate")),
        last_updated=_date(data.get("currentVersionReleaseDate")),
        version=data.get("version"),
        raw={
            "page_kind": "listing",
            "bundle_id": data.get("bundleId"),
            "track_id": data.get("trackId"),
            "artist_name": data.get("artistName"),
            "seller_name": data.get("sellerName"),
            "genres": data.get("genres"),
        },
    )


def enrich_app_store(records: list[AppRecord], *, client: LookupClient | None = None,
                     errors: list[str] | None = None) -> tuple[list[AppRecord], int]:
    """Replace apps.apple.com search hits with looked-up listings.

    Returns the new record list and the number of lookups made. A failed or
    empty lookup keeps the search hit as it was. Order is preserved.
    """
    client = client or ItunesLookupClient()
    out: list[AppRecord] = []
    lookups = 0
    seen: dict[str, AppRecord] = {}
    for r in records:
        parsed = parse_store_url(r.app_id) if "://" in r.app_id else None
        if parsed is None or lookups >= _MAX_LOOKUPS:
            out.append(r)
            continue
        store_id, country = parsed
        if store_id in seen:
            continue  # the same app under two country paths: one listing
        try:
            if lookups:
                time.sleep(_PACE_S)
            lookups += 1
            data = client.lookup(store_id, country)
            if data is None and country != "us":
                lookups += 1
                data = client.lookup(store_id, "us")
        except Exception as exc:  # noqa: BLE001 - one failed lookup must not lose the run
            if errors is not None:
                errors.append(f"App Store lookup for id{store_id} skipped ({type(exc).__name__})")
            out.append(r)
            continue
        if not data or data.get("wrapperType") not in (None, "software"):
            out.append(r)
            continue
        canonical = f"https://apps.apple.com/{country}/app/id{store_id}"
        enriched = record_from_lookup(canonical, data)
        seen[store_id] = enriched
        out.append(enriched)
    return out, lookups


def host_of(link: str) -> str:
    return urlparse(link).netloc.lower().removeprefix("www.")
