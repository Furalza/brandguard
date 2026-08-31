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


def search_and_fetch(
    query: str,
    *,
    n_hits: int = 10,
    lang: str = "tr",
    country: str = "tr",
    fetch_details: bool = True,
) -> list[AppRecord]:
    """Search Google Play for a query and return normalized AppRecords.

    When ``fetch_details`` is true, each hit is expanded with an app() call to
    get permissions and developer fields the search result omits. That is one
    request per hit, so callers should keep query sets small and be ready for
    rate limiting.
    """
    from google_play_scraper import app, search

    hits = search(query, n_hits=n_hits, lang=lang, country=country)
    records: list[AppRecord] = []
    for hit in hits:
        if fetch_details:
            try:
                detail = app(hit["appId"], lang=lang, country=country)
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
