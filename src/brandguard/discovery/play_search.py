"""Google Play search that keeps the top result's package id (K-056).

google-play-scraper 1.2.7 reads the package id of the featured top search
result from a fixed position (``SearchResultOnTop["appId"]`` at [11, 0, 0]).
Google moved it, so the top result - usually the brand's own main app - comes
back with ``appId: None`` and every caller that needs an id silently drops it.
Seen live: search("Papara") returned None first, and com.mobillium.papara was
missing from both the registry enrichment and the Play hunt.

The fix is the smallest possible change to the library: only the top result's
appId rule is replaced. It tries the old position first, then scans the top
card for package ids in the shape the library itself relies on for the regular
results (``["com.x.y", 7]``) or in "details?id=" links, and takes the id that
occurs most often; the featured app's id repeats across its card, a similar
app mentioned in it does not. When nothing qualifies the id stays None, which
is exactly the previous behaviour. Everything else is the unmodified library.

Use ``search`` from this module wherever google_play_scraper.search was used.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

_PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$")
_DETAILS_LINK = re.compile(r"details\?id=([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+)")
_ID_MARKER = 7  # the library reads regular results' ids from ["<package>", 7]
_MAX_NODES = 100_000


def find_app_id(node: Any) -> str | None:
    """Return the package id that occurs most often in a Play data structure."""
    counts: Counter[str] = Counter()
    first_seen: dict[str, int] = {}

    def note(app_id: str) -> None:
        counts[app_id] += 1
        first_seen.setdefault(app_id, len(first_seen))

    stack = [node]
    visited = 0
    while stack and visited < _MAX_NODES:
        current = stack.pop()
        visited += 1
        if isinstance(current, list):
            head = current[0] if current else None
            if (len(current) >= 2 and isinstance(head, str) and current[1] == _ID_MARKER
                    and not isinstance(current[1], bool) and _PACKAGE.match(head)):
                note(head)
            stack.extend(reversed(current))
        elif isinstance(current, dict):
            stack.extend(current.values())
        elif isinstance(current, str) and "details?id=" in current:
            for app_id in _DETAILS_LINK.findall(current):
                note(app_id)
    if not counts:
        return None
    return max(counts, key=lambda app_id: (counts[app_id], -first_seen[app_id]))


def _top_result_app_id(top_result: Any) -> str | None:
    try:
        legacy = top_result[11][0][0]
    except (IndexError, KeyError, TypeError):
        legacy = None
    if isinstance(legacy, str) and _PACKAGE.match(legacy):
        return legacy
    return find_app_id(top_result)


def _install() -> None:
    from google_play_scraper.constants.element import ElementSpec, ElementSpecs

    class _TopResultAppId(ElementSpec):
        def __init__(self) -> None:
            super().__init__(None, [11, 0, 0])

        def extract_content(self, source: Any) -> str | None:
            return _top_result_app_id(source)

    if not isinstance(ElementSpecs.SearchResultOnTop.get("appId"), _TopResultAppId):
        ElementSpecs.SearchResultOnTop["appId"] = _TopResultAppId()


def search(query: str, n_hits: int = 30, lang: str = "en", country: str = "us") -> list[dict]:
    """google_play_scraper.search with the top result's appId recovered, deduplicated."""
    from google_play_scraper import search as library_search

    _install()
    results = library_search(query, n_hits=n_hits, lang=lang, country=country)
    seen: set[str] = set()
    unique: list[dict] = []
    for hit in results:
        app_id = hit.get("appId")
        if app_id and app_id in seen:
            continue
        if app_id:
            seen.add(app_id)
        unique.append(hit)
    return unique
