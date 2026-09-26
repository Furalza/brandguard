"""Serper source: hunt for impersonating apps via Google search (optional).

Google Play is well policed, so real impersonations live on third-party APK
sites and direct-download pages. Serper (serper.dev) returns Google search
results as JSON; this module turns those results into ``AppRecord`` objects so
the same triage cascade can run on them.

This is fundamentally different from the Play adapter. Play returns structured
fields (appId, developer, permissions). A Google result is a raw web hit: title,
link, snippet. The adapter therefore *infers* an app record from the hit: a
package id from the URL when present, a name from the title, the host as the
source. Most signals Play provides (permissions, account age, downloads) are
absent here, so they stay ``None`` and the corresponding signals abstain. The
system is deliberately more conservative on Serper hits than on Play data.

Two kinds of pages come back from a Google search that are not app listings at
all: articles about an app ("how to download X mod apk") and SEO spam that
carries a brand name on an unrelated site (lottery, casino, referral-code
pages). ``page_kind`` recognises both from the URL alone so they are labelled
noise before triage instead of being judged as if they were listings.

Requires ``SERPER_API_KEY`` and the optional extra: ``pip install -e ".[serper]"``.
The API is a paid Google-search proxy; failures are surfaced, not hidden.
"""

from __future__ import annotations

import os
import re
from typing import Protocol
from urllib.parse import urlparse

from brandguard.schema import AppRecord, Publisher

# Third-party APK hosts where impersonations typically live. Play is excluded on
# purpose; it is scanned separately and is clean. The first four are the large
# mirrors; the rest are smaller hosts where modded builds and lookalikes appear
# earlier and are cleaned up later.
_APK_HOSTS = [
    "apkpure.com", "apkmirror.com", "apkcombo.com", "aptoide.com",
    "uptodown.com", "apkmonk.com", "apkfab.com", "apk.dog", "apkdone.com",
    "softonic.com", "apps.apple.com",
]

# A package id in a URL path, e.g. apkpure.com/foo/com.fake.bank -> com.fake.bank
_PKG_IN_URL = re.compile(r"/([a-z][a-z0-9_]+(?:\.[a-z0-9_]+){1,})")

# URL fragments that mark a page as an article, forum thread or social post
# rather than a listing. Judged on the path, so a host that also has real
# listings (aptoide /app pages next to /blog) is not thrown away wholesale.
_ARTICLE_MARKERS = (
    "/howto", "/how-to", "how-to-", "/blog", "/news", "/article", "/guide",
    "/tutorial", "/forum", "/thread", "/watch", "/wiki", "/review/", "review-of-", "-review", "/reviews/",
    "/alternatives", "alternatives-", "/tag/", "/tags/",
)
_ARTICLE_HOSTS = ("wikipedia.", "reddit.", "youtube.", "medium.", "quora.", "twitter.", "x.com",
                  "facebook.", "instagram.", "tiktok.", "linkedin.",
                  # complaint boards, review blogs and forums that rank for "<brand> apk"
                  "sikayetvar.", "eksisozluk.", "uygulamaincele.", "xdaforums.", "xda-developers.",
                  "trustpilot.", "community.", "forum.", "stackoverflow.", "github.", "mitre.org",
                  "fintables.", "scribd.", "archive.org")
# SEO spam that borrows a brand name on unrelated sites. These paths carry
# words no app listing carries.
_SPAM_MARKERS = (
    "/lottery", "/casino", "/betting", "/bet-", "/slot", "referral-code", "promo-code",
    "coupon", "/prices/", "-referral", "bonus-code",
)
_GOV_MARKERS = (".gov.", ".gov/", "gov.in", ".edu.", ".edu/")


class SerperClient(Protocol):
    """Contract for a Serper search backend (real or mock)."""

    def search(self, query: str, num: int, page: int = 1) -> list[dict]:
        """Return a list of organic results, each a dict with title, link, snippet."""
        ...


class RealSerperClient:
    """Live Serper API client. Requires SERPER_API_KEY.

    Localised to Turkey (``gl=tr``, ``hl=tr``) by default because the brands
    are Turkish and their impersonations rank on Google Turkey; a second locale
    can be passed for global APK mirrors.
    """

    def __init__(self, gl: str = "tr", hl: str = "tr") -> None:
        self.gl, self.hl = gl, hl

    def search(self, query: str, num: int, page: int = 1) -> list[dict]:
        import requests

        payload = {"q": query, "num": num, "gl": self.gl, "hl": self.hl}
        if page > 1:
            payload["page"] = page
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": os.environ["SERPER_API_KEY"], "Content-Type": "application/json"},
            json=payload,
            timeout=20,
        )
        response.raise_for_status()
        return response.json().get("organic", [])


def build_apk_queries(brand_name: str, hosts: list[str] | None = None,
                      context: str | None = None) -> list[str]:
    """Google dorks that surface third-party APK listings of a brand.

    Excludes the official Play store, which is scanned separately. Targets the
    common APK hosts plus broad 'apk download' catch-alls in Turkish and English.
    ``context`` (a word from the brand's own app title or publisher, e.g.
    "ucak" for the airline Pegasus) is added to the host and catch-all dorks
    when the brand word is known to be shared with unrelated products, so the
    budget is not spent on horses and phones; the mod dork stays bare, because
    a modded build is titled with the bare word (K-076).
    """
    hosts = _APK_HOSTS if hosts is None else hosts
    ctx = f" {context}" if context else ""
    queries = [f'"{brand_name}"{ctx} apk -site:play.google.com',
               # second, so a small budget (quick depth) still spends one query
               # on what takedowns are made of
               f'"{brand_name}" apk download mod -site:play.google.com']
    queries += [f'"{brand_name}"{ctx} apk site:{host}' for host in hosts]
    queries.append(f'"{brand_name}"{ctx} mobil apk indir -site:play.google.com')
    return queries


def _extract_package_id(link: str) -> str | None:
    """Pull a package id out of a URL path when one is present."""
    path = urlparse(link).path.lower()
    match = _PKG_IN_URL.search(path)
    if not match:
        return None
    candidate = match.group(1)
    # Two-segment matches are common file names (index.html, app.apk); a real
    # package id has at least three segments or an obvious reverse-domain head.
    if candidate.count(".") == 1 and not candidate.startswith(("com.", "net.", "org.", "tr.")):
        return None
    return candidate


def _host(link: str) -> str:
    return urlparse(link).netloc.lower().removeprefix("www.")


def page_kind(link: str) -> str:
    """Classify a search hit's URL: "listing", "article", "spam" or "gov".

    Anything but "listing" is not an app and must not be triaged as one. The
    check is deliberately URL-only: fetching the page would be slower and would
    mean connecting to sites we suspect.
    """
    low = link.lower()
    host = _host(link)
    if any(m in host for m in _ARTICLE_HOSTS):
        return "article"
    if any(m in low for m in _GOV_MARKERS):
        return "gov"
    if any(m in low for m in _SPAM_MARKERS):
        return "spam"
    if any(m in low for m in _ARTICLE_MARKERS):
        return "article"
    if "/developer/" in low or "/developers/" in low:
        # a seller's catalogue page (App Store, apkpure, apkmirror), not an app
        return "developer"
    return "listing"


def _result_to_record(hit: dict) -> AppRecord | None:
    """Turn one Google organic result into an AppRecord, or None if unusable.

    The publisher and most metadata are unknown from a search hit, so they stay
    None. app_id is the package id when the URL exposes one, otherwise the link
    itself (so the analyst can still open and inspect it). The page kind is
    kept in ``raw`` so the engine can label non-listings as noise.
    """
    link = hit.get("link") or ""
    if not link:
        return None
    title = (hit.get("title") or "").strip()
    package_id = _extract_package_id(link)
    return AppRecord(
        app_id=package_id or link,
        source=f"serper:{_host(link)}",
        name=title,
        publisher=Publisher(name=""),  # unknown from a search hit
        description=hit.get("snippet"),
        icon_url=None,
        raw={**hit, "page_kind": page_kind(link)},
    )


def search_apks(
    brand_name: str,
    *,
    client: SerperClient | None = None,
    num: int = 10,
    max_queries: int | None = 6,
    pages: int = 1,
    hosts: list[str] | None = None,
    errors: list[str] | None = None,
    extra_terms: list[str] | None = None,
    context: str | None = None,
) -> list[AppRecord]:
    """Run APK-hunting dorks for a brand and return normalized AppRecords.

    Deduplicated by app_id. One search per query and page, so ``max_queries``
    and ``pages`` are the cost dials; ``max_queries=None`` runs every dork.
    Query failures are appended to ``errors`` (when given) and printed, never
    raised: one throttled query must not lose the others.
    """
    client = client or RealSerperClient()
    seen: set[str] = set()
    records: list[AppRecord] = []
    queries = build_apk_queries(brand_name, hosts, context=context)
    if max_queries is not None:
        queries = queries[:max_queries]
    # Precise identity terms (publisher, flagship title) get one catch-all dork
    # each, on top of the budget: they are what finds a dictionary-word brand.
    for term in extra_terms or []:
        queries.append(f'"{term}" apk -site:play.google.com')
    for query in queries:
        for page in range(1, max(1, pages) + 1):
            try:
                hits = client.search(query, num=num, page=page) if page > 1 else client.search(query, num=num)
            except Exception as exc:  # noqa: BLE001 - surface search failures per query
                message = f"serper query {query!r} page {page} skipped ({type(exc).__name__})"
                print(f"    . {message}")
                if errors is not None:
                    errors.append(message)
                break
            if not hits:
                break
            for hit in hits:
                record = _result_to_record(hit)
                if record is None or record.app_id in seen:
                    continue
                seen.add(record.app_id)
                records.append(record)
    return records


def _load_dotenv_once() -> None:
    """Consult the repo-root .env for SERPER_API_KEY (gaps only)."""
    from brandguard.config import load_dotenv

    load_dotenv()


def get_serper_client() -> SerperClient:
    """Return the real client when a key is configured; raise otherwise."""
    _load_dotenv_once()
    if not os.environ.get("SERPER_API_KEY"):
        raise RuntimeError(
            "SERPER_API_KEY is not set. Add it to .env or the environment, "
            'and install the extra: pip install -e ".[serper]"'
        )
    return RealSerperClient()
