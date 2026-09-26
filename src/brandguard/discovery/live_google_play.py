"""Live Google Play source (optional).

Turns real Google Play search and detail results into ``AppRecord`` objects so
the same triage cascade that runs on mock data can run on live listings. This is
the bridge the mock adapters were designed to be swapped for: triage does not
change, only the source.

Reality of live data: the public scraper does not expose everything our signals
would like. Publisher account age and verification are not available, so those
fields stay ``None`` and the corresponding signals abstain rather than guess.
This is exactly the missing-vs-zero discipline from schema.py, now earning its
keep on real input.

Requires the optional dependency: ``pip install -e ".[live]"``. The scraper is a
best-effort, unofficial interface; Google may rate-limit or block it, and the
result shape can change. Failures are surfaced, not hidden.
"""

from __future__ import annotations

import threading
import time

from brandguard.discovery.parsing import parse_date, parse_downloads, split_permissions
from brandguard.schema import AppRecord, Publisher


def _detail_to_record(detail: dict) -> AppRecord:
    """Map one google-play-scraper app() result onto an AppRecord.

    Real Play data is inconsistent: numeric fields arrive as strings or None,
    emails are sometimes absent, ids are occasionally non-string. Everything is
    coerced defensively so a live listing maps or is skipped by the caller, never
    corrupts the record.
    """
    app_id = str(detail.get("appId") or detail.get("appid") or "").strip()
    email = detail.get("developerEmail") or ""
    email_domain = email.split("@")[-1] if "@" in email else None
    rating = detail.get("score")
    if not isinstance(rating, (int, float)):
        rating = None
    review_count = detail.get("ratings")
    if not isinstance(review_count, int):
        review_count = None
    # Only the detail payload carries developerId; a search hit does not (K-062).
    developer_id = detail.get("developerId")
    account_id = str(developer_id).strip() if developer_id not in (None, "") else None

    return AppRecord(
        app_id=app_id,
        source="google_play_live",
        name=str(detail.get("title") or ""),
        publisher=Publisher(
            name=str(detail.get("developer") or ""),
            account_created=None,
            other_app_count=None,
            website=detail.get("developerWebsite"),
            email_domain=email_domain,
            verified=None,
            account_id=account_id,
        ),
        description=detail.get("description"),
        icon_url=detail.get("icon"),
        permissions=split_permissions(detail.get("permissions")),
        downloads=parse_downloads(detail.get("installs") or detail.get("realInstalls")),
        rating=rating,
        review_count=review_count,
        published=parse_date(detail.get("released")),
        last_updated=parse_date(detail.get("updated")),
        version=detail.get("version") if isinstance(detail.get("version"), str) else None,
        raw=detail,
    )


# Detail pages rarely change within a day, and the same app comes back for
# several of a brand's query variants. A small in-process cache keyed by
# (app_id, lang, country) removes those repeat requests, which is where most
# of the Play load (and rate-limit risk) comes from.
_DETAIL_TTL_S = 24 * 3600
_detail_cache: dict[tuple[str, str, str], tuple[float, dict]] = {}
_cache_lock = threading.Lock()

# Polite pacing between consecutive search requests to an unofficial interface.
_MIN_GAP_S = 0.6
_last_search = 0.0
_pace_lock = threading.Lock()


def _paced() -> None:
    global _last_search
    with _pace_lock:
        wait = _MIN_GAP_S - (time.monotonic() - _last_search)
        if wait > 0:
            time.sleep(wait)
        _last_search = time.monotonic()


def cached_detail(app_id: str, lang: str, country: str, fetch) -> dict:
    key = (app_id, lang, country)
    now = time.monotonic()
    with _cache_lock:
        hit = _detail_cache.get(key)
        if hit and now - hit[0] < _DETAIL_TTL_S:
            return hit[1]
    detail = fetch(app_id, lang=lang, country=country)
    with _cache_lock:
        _detail_cache[key] = (now, detail)
    return detail


def clear_detail_cache() -> None:
    with _cache_lock:
        _detail_cache.clear()


def search_and_fetch(
    query: str,
    *,
    n_hits: int = 10,
    lang: str = "tr",
    country: str = "tr",
    fetch_details: bool = True,
    skip_ids: set[str] | None = None,
    seen_out: set[str] | None = None,
) -> list[AppRecord]:
    """Search Google Play for a query and return normalized AppRecords.

    When ``fetch_details`` is true, each hit is expanded with an app() call to
    get permissions and developer fields the search result omits. Details are
    cached for a day and ids in ``skip_ids`` are not fetched again, so a brand
    whose app ranks for ten query variants costs one detail request, not ten.
    """
    from google_play_scraper import app

    # The library's own search drops the featured top result's package id, which
    # is usually the brand's main app; this wrapper recovers it (K-056).
    from brandguard.discovery.play_search import search

    _paced()
    hits = search(query, n_hits=n_hits, lang=lang, country=country)
    records: list[AppRecord] = []
    for hit in hits:
        app_id = hit.get("appId")
        if not app_id:
            continue  # the featured-result rule failed again; nothing to fetch (K-056)
        if seen_out is not None:
            seen_out.add(app_id)  # every id search returned, fetched or not
        if skip_ids is not None and app_id in skip_ids:
            continue  # already collected by an earlier query of this scan
        if fetch_details:
            try:
                detail = cached_detail(app_id, lang, country, app)
            except Exception:  # noqa: BLE001 - scraper detail fetch is best-effort
                detail = hit  # fall back to the search-result fields
        else:
            detail = hit
        try:
            records.append(_detail_to_record(detail))
        except Exception:  # noqa: BLE001,S112 - one malformed listing must not drop the batch
            # Real Play data occasionally returns shapes we cannot map; skip that
            # single listing rather than losing the whole query's results.
            continue
    return records
