"""Source adapters.

Each marketplace returns its own schema. An adapter's only job is to map that
schema onto the shared ``AppRecord``; all scoring downstream is source-agnostic.
Adapters implement a common protocol so a new source is one class, not a change
to the pipeline. Value-format conversions live in ``parsing`` and are reused, so
an adapter contains field mapping and nothing else.

The three adapters here use deliberately different shapes (flat, nested,
minimal third-party) to exercise the normalization layer the way real sources
would.
"""

from __future__ import annotations

from typing import Protocol

from brandguard.discovery.parsing import parse_date, parse_downloads, split_permissions
from brandguard.schema import AppRecord, Publisher


class SourceAdapter(Protocol):
    """Contract every adapter satisfies."""

    source: str

    def parse(self, raw: dict) -> AppRecord:
        """Convert one raw source record into an ``AppRecord``."""
        ...


class GooglePlayLikeAdapter:
    """A flat schema close to Google Play's public shape."""

    source = "google_play"

    def parse(self, raw: dict) -> AppRecord:
        return AppRecord(
            app_id=raw["appId"],
            source=self.source,
            name=raw["title"],
            publisher=Publisher(
                name=raw["developer"],
                account_created=parse_date(raw.get("developerSince")),
                other_app_count=raw.get("developerAppCount"),
                website=raw.get("developerWebsite"),
                verified=raw.get("developerVerified"),
            ),
            description=raw.get("description"),
            icon_url=raw.get("icon"),
            permissions=split_permissions(raw.get("permissions")),
            downloads=parse_downloads(raw.get("installs")),
            rating=raw.get("score"),
            review_count=raw.get("ratings"),
            published=parse_date(raw.get("released")),
            last_updated=parse_date(raw.get("updated")),
            version=raw.get("version"),
            raw=raw,
        )


class NestedStoreAdapter:
    """A store that nests publisher and metrics under sub-objects."""

    source = "nested_store"

    def parse(self, raw: dict) -> AppRecord:
        dev = raw.get("publisher", {})
        metrics = raw.get("metrics", {})
        meta = raw.get("meta", {})
        return AppRecord(
            app_id=raw["package"],
            source=self.source,
            name=raw["label"],
            publisher=Publisher(
                name=dev.get("displayName", ""),
                account_created=parse_date(dev.get("joinedEpoch")),
                other_app_count=dev.get("appCount"),
                website=dev.get("url"),
                verified=dev.get("isVerified"),
            ),
            description=raw.get("summary"),
            icon_url=meta.get("iconUrl"),
            permissions=split_permissions(meta.get("perms")),
            downloads=parse_downloads(metrics.get("downloadText")),
            rating=metrics.get("stars"),
            review_count=metrics.get("reviewTotal"),
            published=parse_date(meta.get("firstSeen")),
            last_updated=parse_date(meta.get("lastSeen")),
            version=meta.get("versionName"),
            raw=raw,
        )


class ThirdPartyApkAdapter:
    """A minimal third-party APK site with terse, differently named fields."""

    source = "thirdparty_apk"

    def parse(self, raw: dict) -> AppRecord:
        return AppRecord(
            app_id=raw["pkg"],
            source=self.source,
            name=raw["name"],
            publisher=Publisher(name=raw.get("uploader", "")),
            description=raw.get("desc"),
            icon_url=raw.get("img"),
            permissions=split_permissions(raw.get("perm")),
            downloads=parse_downloads(raw.get("dl")),
            published=parse_date(raw.get("date")),
            last_updated=parse_date(raw.get("date")),
            version=raw.get("ver"),
            raw=raw,
        )


_REGISTRY: dict[str, SourceAdapter] = {
    a.source: a
    for a in (GooglePlayLikeAdapter(), NestedStoreAdapter(), ThirdPartyApkAdapter())
}


def get_adapter(source: str) -> SourceAdapter:
    """Return the adapter registered for a source name."""
    try:
        return _REGISTRY[source]
    except KeyError:
        raise ValueError(f"no adapter for source {source!r}") from None


def normalize_records(source: str, raw_records: list[dict]) -> list[AppRecord]:
    """Convert a batch of raw records from one source into ``AppRecord`` objects."""
    adapter = get_adapter(source)
    return [adapter.parse(raw) for raw in raw_records]
