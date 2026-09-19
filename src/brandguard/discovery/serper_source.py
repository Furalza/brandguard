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
# purpose; it is scanned separately and is clean.
_APK_HOSTS = ["apkpure.com", "apkmirror.com", "apkcombo.com", "aptoide.com"]

# A package id in a URL path, e.g. apkpure.com/foo/com.fake.bank -> com.fake.bank
_PKG_IN_URL = re.compile(r"/([a-z][a-z0-9_]+(?:\.[a-z0-9_]+){2,})")


class SerperClient(Protocol):
    """Contract for a Serper search backend (real or mock)."""

    def search(self, query: str, num: int) -> list[dict]:
        """Return a list of organic results, each a dict with title, link, snippet."""
        ...


class RealSerperClient:
    """Live Serper API client. Requires SERPER_API_KEY."""

    def search(self, query: str, num: int) -> list[dict]:
        import requests

        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": os.environ["SERPER_API_KEY"], "Content-Type": "application/json"},
            json={"q": query, "num": num},
            timeout=20,
        )
        response.raise_for_status()
        return response.json().get("organic", [])


def build_apk_queries(brand_name: str) -> list[str]:
    """Google dorks that surface third-party APK listings of a brand.

    Excludes the official Play store, which is scanned separately. Targets the
    common APK hosts plus a broad 'apk download' catch-all.
    """
    queries = [f'"{brand_name}" apk -site:play.google.com']
    queries += [f'"{brand_name}" apk site:{host}' for host in _APK_HOSTS]
    queries.append(f'"{brand_name}" mobil apk indir -site:play.google.com')
    return queries


def _extract_package_id(link: str) -> str | None:
    """Pull a package id out of a URL path when one is present."""
    path = urlparse(link).path.lower()
    match = _PKG_IN_URL.search(path)
    return match.group(1) if match else None


def _host(link: str) -> str:
    return urlparse(link).netloc.lower().removeprefix("www.")


def _result_to_record(hit: dict) -> AppRecord | None:
    """Turn one Google organic result into an AppRecord, or None if unusable.

    The publisher and most metadata are unknown from a search hit, so they stay
    None. app_id is the package id when the URL exposes one, otherwise the link
    itself (so the analyst can still open and inspect it).
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
        raw=hit,
    )


def search_apks(
    brand_name: str,
    *,
    client: SerperClient | None = None,
    num: int = 10,
    max_queries: int = 6,
) -> list[AppRecord]:
    """Run APK-hunting dorks for a brand and return normalized AppRecords.

    Deduplicated by app_id. One search per query, so keep max_queries small.
    """
    client = client or RealSerperClient()
    seen: set[str] = set()
    records: list[AppRecord] = []
    for query in build_apk_queries(brand_name)[:max_queries]:
        try:
            hits = client.search(query, num=num)
        except Exception as exc:  # noqa: BLE001 - surface search failures per query
            print(f"    . serper query {query!r} skipped ({type(exc).__name__})")
            continue
        for hit in hits:
            record = _result_to_record(hit)
            if record is None or record.app_id in seen:
                continue
            seen.add(record.app_id)
            records.append(record)
    return records


def _load_dotenv_once() -> None:
    """Populate os.environ from a .env at the repo root if present (gaps only).

    Mirrors the adjudicator's loader so Serper works from .env exactly like the
    LLM keys do. Real environment variables always win.
    """
    from pathlib import Path

    env_path = Path(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def get_serper_client() -> SerperClient:
    """Return the real client when a key is configured; raise otherwise."""
    _load_dotenv_once()
    if not os.environ.get("SERPER_API_KEY"):
        raise RuntimeError(
            "SERPER_API_KEY is not set. Add it to .env or the environment, "
            'and install the extra: pip install -e ".[serper]"'
        )
    return RealSerperClient()
