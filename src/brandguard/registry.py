"""Brand registry: one CSV file is the source of truth for the watchlist.

Scanning many brands needs one place to list them. Hand-writing a profile JSON
per brand does not scale past a handful, so the registry keeps brands as rows in
a CSV (editable in Excel) and generates the profile JSONs the hunt sweep reads:

    data/brands.csv  --check-->  validated rows  --sync-->  data/watchlist/<id>.json
                                                  (--enrich: official apps from Google Play)

    python -m brandguard.registry check
    python -m brandguard.registry sync
    python -m brandguard.registry sync --enrich
    python -m brandguard.hunt --watchlist data/watchlist --source play,serper

CSV columns (only brand_name and official_domains are required; list cells use
"|" between values, so the file works with both "," and ";" delimiters):

    id                    profile file name; defaults to a slug of brand_name
    brand_name            e.g. Ziraat Bankasi
    official_domains      ziraatbank.com.tr|ziraat.com.tr
    sector                banking, logistics, crypto ... (default: unknown)
    official_publishers   exact publisher strings as the store shows them
    official_package_ids  tr.com.ziraat.ziraatmobil|...
    known_official_apps   official app titles
    known_affiliates      vetted legitimate related domains (K-049)
    active                yes/no; "no" takes the brand out of the sweep without deleting the row
    notes                 free text for humans, ignored

Ownership rules (the safety model of sync):
  * A profile written by the registry carries a "_registry" block. Only those
    files are ever updated or removed by sync.
  * A profile without that block is hand-maintained and is never touched. If a
    CSV row points at the same file, or at a brand a hand-maintained profile
    already covers (shared official domain), the row is skipped so the sweep
    never scans a brand twice.
  * Any validation error aborts the whole sync before a single file is written,
    so a typo can never prune half the watchlist.

Enrichment (--enrich) fills official publishers, package ids and app titles
from Google Play, but only for publishers whose developer website or e-mail is
under one of the brand's official domains. A publisher name that merely looks
right is reported for review, never written: the name is attacker-controlled,
the domain proof is not (the same rule as the publisher veto, K-014).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import time
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Protocol

from brandguard.schema import BrandProfile

MANAGED_KEY = "_registry"
MANAGER = "brandguard.registry"
LIST_SEP = "|"

REQUIRED_COLUMNS = ("brand_name", "official_domains")
LIST_COLUMNS = (
    "official_domains",
    "official_publishers",
    "official_package_ids",
    "known_official_apps",
    "known_affiliates",
)
KNOWN_COLUMNS = frozenset(
    {"id", "brand_name", "sector", "active", "notes", *LIST_COLUMNS}
)

_TRUE = {"", "1", "yes", "y", "true", "evet", "e", "on"}
_FALSE = {"0", "no", "n", "false", "hayir", "h", "off"}

_TURKISH_FOLD = str.maketrans({
    "\u0131": "i", "\u0130": "i", "\u015f": "s", "\u015e": "s", "\u011f": "g",
    "\u011e": "g", "\u00fc": "u", "\u00dc": "u", "\u00f6": "o", "\u00d6": "o",
    "\u00e7": "c", "\u00c7": "c",
})
_SECTOR_ALIASES = {
    "bank": "banking", "bankacilik": "banking", "banka": "banking",
    "kargo": "logistics", "lojistik": "logistics", "courier": "logistics",
    "kripto": "crypto", "cryptocurrency": "crypto", "exchange": "crypto",
}


def _sectors_with_baseline() -> set[str] | None:
    """Sectors triage has a permission baseline for, or None if triage is not importable."""
    try:
        from brandguard.triage.scored_signals import _SECTOR_EXPECTED
    except ImportError:
        return None
    return set(_SECTOR_EXPECTED)


_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_HOST_RE = re.compile(
    r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$"
)
_PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    """Turn a brand name into a stable ASCII file id with Turkish letters folded."""
    folded = unicodedata.normalize("NFKD", text.translate(_TURKISH_FOLD))
    ascii_only = "".join(c for c in folded if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_only.lower()).strip("_")
    return slug[:64]


def normalize_domain(value: str) -> str:
    """Reduce a pasted URL or host to a bare lower-case host.

    "https://www.ZiraatBank.com.tr/tr/bireysel" -> "ziraatbank.com.tr". People
    paste URLs from a browser; the profile must hold the registrable host.
    """
    host = value.strip().lower()
    host = re.sub(r"^[a-z][a-z0-9+.-]*://", "", host)
    host = re.split(r"[/?#]", host, maxsplit=1)[0]
    host = host.split("@")[-1].split(":")[0].rstrip(".")
    host = host.removeprefix("www.")
    return host


def host_under(host: str, domains: Iterable[str]) -> bool:
    """True when host equals one of the domains or is a subdomain of it."""
    host = normalize_domain(host)
    return any(host == d or host.endswith("." + d) for d in domains if d)


def _split(cell: str | None) -> list[str]:
    if not cell:
        return []
    return [part.strip() for part in cell.split(LIST_SEP) if part.strip()]


def _dedupe(values: Iterable[str], *, key: Callable[[str], str] = str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        k = key(value)
        if k not in seen:
            seen.add(k)
            out.append(value)
    return out


# ---------------------------------------------------------------------------
# Reading and validating the CSV
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BrandEntry:
    """One validated CSV row."""

    id: str
    brand_name: str
    official_domains: tuple[str, ...]
    sector: str = "unknown"
    official_publishers: tuple[str, ...] = ()
    official_package_ids: tuple[str, ...] = ()
    known_official_apps: tuple[str, ...] = ()
    known_affiliates: tuple[str, ...] = ()
    active: bool = True
    line: int = 0


@dataclass
class Registry:
    entries: list[BrandEntry]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source: str = ""

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def active(self) -> list[BrandEntry]:
        return [e for e in self.entries if e.active]


def _decode(raw: bytes, warnings: list[str]) -> str:
    """Excel on a Turkish Windows saves "CSV" as cp1254 unless "CSV UTF-8" is chosen."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        warnings.append(
            "file is not UTF-8; read it as Windows-1254 (Turkish Excel). "
            "Saving as 'CSV UTF-8' avoids this."
        )
        return raw.decode("cp1254")


def _delimiter(text: str) -> str:
    """Turkish-locale Excel writes ';', everything else ','. Decide from the header."""
    header = text.splitlines()[0] if text else ""
    counts = {d: header.count(d) for d in (",", ";", "\t")}
    best = max(counts, key=counts.get)
    return best if counts[best] else ","


def _parse_row(row: dict[str, str], line: int, errors: list[str]) -> BrandEntry | None:
    def err(msg: str) -> None:
        errors.append(f"line {line}: {msg}")

    brand = (row.get("brand_name") or "").strip()
    if not brand:
        err("brand_name is empty")
        return None
    where = f"{brand!r}"

    raw_domains = _split(row.get("official_domains"))
    domains = _dedupe(normalize_domain(d) for d in raw_domains)
    if not domains:
        err(f"{where}: official_domains is empty (at least one is required)")
    for d in domains:
        if not _HOST_RE.match(d):
            err(f"{where}: {d!r} is not a valid domain")

    affiliates = _dedupe(normalize_domain(d) for d in _split(row.get("known_affiliates")))
    for d in affiliates:
        if not _HOST_RE.match(d):
            err(f"{where}: known_affiliates {d!r} is not a valid domain")
        elif d in domains:
            err(f"{where}: {d!r} is listed both as official and as affiliate")

    packages = _dedupe(_split(row.get("official_package_ids")))
    for p in packages:
        if not _PACKAGE_RE.match(p):
            err(f"{where}: {p!r} is not a valid package id (expected e.g. com.brand.app)")

    entry_id = (row.get("id") or "").strip().lower() or slugify(brand)
    if not _ID_RE.match(entry_id):
        err(f"{where}: id {entry_id!r} must be lower-case letters, digits, '_' or '-'")

    active_cell = (row.get("active") or "").strip().lower().translate(_TURKISH_FOLD)
    if active_cell in _TRUE:
        active = True
    elif active_cell in _FALSE:
        active = False
    else:
        err(f"{where}: active must be yes/no, got {row.get('active')!r}")
        active = True

    sector_cell = (row.get("sector") or "").strip().lower().translate(_TURKISH_FOLD)
    sector = _SECTOR_ALIASES.get(sector_cell, sector_cell) or "unknown"

    return BrandEntry(
        id=entry_id,
        brand_name=brand,
        official_domains=tuple(domains),
        sector=sector,
        official_publishers=tuple(_dedupe(_split(row.get("official_publishers")))),
        official_package_ids=tuple(packages),
        known_official_apps=tuple(_dedupe(_split(row.get("known_official_apps")))),
        known_affiliates=tuple(affiliates),
        active=active,
        line=line,
    )


def parse_registry(
    text: str, *, source: str = "<csv>", warnings: list[str] | None = None
) -> Registry:
    """Parse CSV text into a Registry. Never raises on bad data; errors are collected."""
    reg = Registry(entries=[], warnings=list(warnings or []), source=source)
    if not text.strip():
        reg.errors.append("file is empty")
        return reg

    reader = csv.DictReader(io.StringIO(text), delimiter=_delimiter(text))
    header = [(h or "").strip().lower() for h in (reader.fieldnames or [])]
    reader.fieldnames = header

    unknown = [h for h in header if h and h not in KNOWN_COLUMNS]
    if unknown:
        reg.errors.append(
            f"unknown column(s) {unknown}; allowed: {sorted(KNOWN_COLUMNS)}"
        )
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        reg.errors.append(f"missing required column(s) {missing}")
    if reg.errors:
        return reg

    by_id: dict[str, BrandEntry] = {}
    by_domain: dict[str, BrandEntry] = {}
    for row in reader:
        line = reader.line_num
        if None in row:  # more cells than header columns
            reg.errors.append(
                f"line {line}: more cells than columns (unquoted delimiter in a value?)"
            )
            continue
        if not any((v or "").strip() for v in row.values()):
            continue  # blank line
        if (row.get("brand_name") or "").lstrip().startswith("#"):
            continue  # commented-out row
        entry = _parse_row(row, line, reg.errors)
        if entry is None:
            continue
        if entry.id in by_id:
            reg.errors.append(
                f"line {line}: id {entry.id!r} already used on line {by_id[entry.id].line}; "
                "set a distinct id column"
            )
            continue
        by_id[entry.id] = entry
        for d in entry.official_domains:
            other = by_domain.get(d)
            if other is not None:
                reg.warnings.append(
                    f"line {line}: {entry.brand_name!r} shares official domain {d!r} "
                    f"with {other.brand_name!r} (line {other.line})"
                )
            else:
                by_domain[d] = entry
        reg.entries.append(entry)

    known = _sectors_with_baseline()
    if known is not None:
        for sector in sorted({e.sector for e in reg.entries if e.active} - known):
            names = ", ".join(e.brand_name for e in reg.active if e.sector == sector)
            reg.warnings.append(
                f"sector {sector!r} has no permission baseline in triage "
                f"(known: {', '.join(sorted(known))}); permission drift will abstain for: {names}"
            )
    return reg


def load_registry(path: Path) -> Registry:
    warnings: list[str] = []
    text = _decode(path.read_bytes(), warnings)
    return parse_registry(text, source=path.name, warnings=warnings)


# ---------------------------------------------------------------------------
# Google Play enrichment (domain-verified)
# ---------------------------------------------------------------------------

class PlayClient(Protocol):
    """The two calls enrichment needs. The real one wraps google-play-scraper."""

    def search(self, query: str, n_hits: int) -> list[dict]: ...

    def details(self, app_id: str) -> dict: ...


class GooglePlayClient:
    def __init__(self, lang: str = "tr", country: str = "tr") -> None:
        try:
            from google_play_scraper import app, search
        except ImportError as exc:  # pragma: no cover - depends on the optional extra
            raise SystemExit('--enrich needs the live extra: pip install -e ".[live]"') from exc
        self._app, self._search = app, search
        self.lang, self.country = lang, country

    def search(self, query: str, n_hits: int) -> list[dict]:
        return self._search(query, n_hits=n_hits, lang=self.lang, country=self.country)

    def details(self, app_id: str) -> dict:
        return self._app(app_id, lang=self.lang, country=self.country)


@dataclass
class Enrichment:
    domains: list[str]
    publishers: list[str] = field(default_factory=list)
    package_ids: list[str] = field(default_factory=list)
    apps: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    needs_review: list[str] = field(default_factory=list)
    checked_at: str = ""

    def to_json(self) -> dict:
        return {
            "source": "google_play",
            "checked_at": self.checked_at,
            "domains": self.domains,
            "publishers": self.publishers,
            "package_ids": self.package_ids,
            "apps": self.apps,
            "evidence": self.evidence,
        }

    @classmethod
    def from_json(cls, data: dict) -> Enrichment:
        return cls(
            domains=list(data.get("domains", [])),
            publishers=list(data.get("publishers", [])),
            package_ids=list(data.get("package_ids", [])),
            apps=list(data.get("apps", [])),
            evidence=list(data.get("evidence", [])),
            checked_at=str(data.get("checked_at", "")),
        )


def _email_domain(email: object) -> str:
    return email.split("@")[-1].strip().lower() if isinstance(email, str) and "@" in email else ""


def enrich_from_play(entry: BrandEntry, client: PlayClient, *, hits: int = 15) -> Enrichment:
    """Find the brand's official Play apps, accepting only domain-verified publishers.

    A publisher is accepted when its developer website or e-mail is under an
    official domain. Every app by an accepted publisher in the results is then
    official. Publishers that only resemble the brand by name are returned in
    needs_review and are not written into the profile.
    """
    result = Enrichment(
        domains=list(entry.official_domains),
        checked_at=datetime.now(tz=UTC).date().isoformat(),
    )
    listings: list[dict] = []
    for hit in client.search(entry.brand_name, hits):
        app_id = str(hit.get("appId") or "").strip()
        if not app_id:
            continue
        try:
            detail = client.details(app_id) or {}
        except Exception:  # noqa: BLE001 - one failed detail must not lose the brand
            detail = {}
        listings.append({**hit, **detail, "appId": app_id})

    verified: dict[str, str] = {}
    for item in listings:
        publisher = str(item.get("developer") or "").strip()
        if not publisher or publisher in verified:
            continue
        website = str(item.get("developerWebsite") or "")
        email_dom = _email_domain(item.get("developerEmail"))
        if website and host_under(website, entry.official_domains):
            verified[publisher] = f"developer website {normalize_domain(website)}"
        elif email_dom and host_under(email_dom, entry.official_domains):
            verified[publisher] = f"developer e-mail domain {email_dom}"

    brand_key = slugify(entry.brand_name).split("_")[0]
    for item in listings:
        publisher = str(item.get("developer") or "").strip()
        app_id = item["appId"]
        title = str(item.get("title") or "").strip()
        if publisher in verified:
            result.package_ids.append(app_id)
            if title:
                result.apps.append(title)
            result.evidence.append(f"{app_id}: {publisher!r} verified by {verified[publisher]}")
        elif publisher and brand_key and brand_key in slugify(publisher):
            result.needs_review.append(
                f"{app_id}: publisher {publisher!r} resembles the brand but has no "
                "website/e-mail under an official domain"
            )

    result.publishers = list(verified)
    result.package_ids = _dedupe(result.package_ids)
    result.apps = _dedupe(result.apps)
    result.needs_review = _dedupe(result.needs_review)
    return result


# ---------------------------------------------------------------------------
# Planning and applying a sync
# ---------------------------------------------------------------------------

class Action(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    UNCHANGED = "unchanged"
    REMOVE = "remove"
    SKIP_MANUAL = "skip-manual"
    SKIP_COVERED = "skip-covered"


@dataclass
class Change:
    action: Action
    path: Path
    brand: str
    reason: str = ""
    content: str | None = None


@dataclass
class SyncReport:
    changes: list[Change] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    review: list[str] = field(default_factory=list)
    applied: bool = False

    def count(self, action: Action) -> int:
        return sum(1 for c in self.changes if c.action is action)


def is_managed(data: dict) -> bool:
    block = data.get(MANAGED_KEY)
    return isinstance(block, dict) and block.get("managed_by") == MANAGER


def build_profile(entry: BrandEntry, enrichment: Enrichment | None, source: str) -> dict:
    """Assemble the profile dict. CSV values come first, enrichment only adds."""
    enr = enrichment or Enrichment(domains=[])
    profile = {
        "brand_name": entry.brand_name,
        "official_domains": list(entry.official_domains),
        "official_publishers": _dedupe([*entry.official_publishers, *enr.publishers]),
        "known_official_apps": _dedupe([*entry.known_official_apps, *enr.apps]),
        "sector": entry.sector,
        "official_package_ids": _dedupe([*entry.official_package_ids, *enr.package_ids]),
        "official_permissions": None,
        "known_affiliates": list(entry.known_affiliates),
    }
    BrandProfile(**profile)  # the hunt must be able to load what we write
    block: dict = {"managed_by": MANAGER, "source": source}
    if enrichment is not None:
        block["enrichment"] = enrichment.to_json()
    profile[MANAGED_KEY] = block
    return profile


def _dump(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _read_profiles(directory: Path, warnings: list[str]) -> dict[Path, dict]:
    found: dict[Path, dict] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            warnings.append(f"{path.name}: unreadable ({type(exc).__name__}); left untouched")
            continue
        if isinstance(data, dict):
            found[path] = data
    return found


def plan_sync(
    registry: Registry,
    watchlist: Path,
    *,
    enricher: Callable[[BrandEntry], Enrichment] | None = None,
    refresh: bool = False,
    prune: bool = True,
    delay: float = 0.0,
    max_failures: int = 3,
    progress: Callable[[BrandEntry], None] | None = None,
) -> SyncReport:
    """Work out every file change without writing anything.

    Enrichment is incremental: a brand already enriched against its current
    official domains is not queried again unless ``refresh`` is set, so a sweep
    over a large CSV only pays for new or changed brands. After
    ``max_failures`` consecutive enrichment failures the source is treated as
    down for the rest of the run.
    """
    report = SyncReport(errors=list(registry.errors), warnings=list(registry.warnings))
    if not registry.ok:
        return report

    existing = _read_profiles(watchlist, report.warnings)
    manual = {p: d for p, d in existing.items() if not is_managed(d)}
    manual_domains: dict[str, Path] = {}
    for path, data in manual.items():
        for d in data.get("official_domains") or []:
            manual_domains.setdefault(normalize_domain(str(d)), path)

    keep: set[Path] = set()
    first_call = True
    failures = 0
    for entry in registry.active:
        path = watchlist / f"{entry.id}.json"
        if path in manual:
            report.changes.append(Change(
                Action.SKIP_MANUAL, path, entry.brand_name,
                "hand-maintained profile with this id exists; it takes priority",
            ))
            continue
        covered = next(
            (manual_domains[d] for d in entry.official_domains if d in manual_domains), None
        )
        if covered is not None:
            report.changes.append(Change(
                Action.SKIP_COVERED, path, entry.brand_name,
                f"already covered by hand-maintained {covered.name}",
            ))
            continue

        current = existing.get(path)
        enrichment = None
        if current is not None:
            old = current.get(MANAGED_KEY, {}).get("enrichment")
            if old:
                enrichment = Enrichment.from_json(old)
                if enrichment.domains != list(entry.official_domains):
                    enrichment = None  # official domains changed: proof is stale
                    report.warnings.append(
                        f"{entry.brand_name}: official domains changed, previous enrichment dropped"
                    )
        if enricher is not None and (enrichment is None or refresh):
            if delay and not first_call:
                time.sleep(delay)
            first_call = False
            if progress is not None:
                progress(entry)
            try:
                enrichment = enricher(entry)
                failures = 0
                report.review.extend(f"{entry.brand_name}: {r}" for r in enrichment.needs_review)
                if not enrichment.publishers:
                    report.warnings.append(
                        f"{entry.brand_name}: Play enrichment found no domain-verified publisher"
                    )
            except Exception as exc:  # noqa: BLE001 - one brand failing must not stop the sync
                failures += 1
                kept = "previous enrichment kept" if enrichment else "profile written from CSV only"
                report.warnings.append(
                    f"{entry.brand_name}: enrichment failed ({type(exc).__name__}); {kept}"
                )
                if failures >= max_failures:
                    enricher = None  # source is down: stop hammering it, finish from the CSV
                    report.warnings.append(
                        f"enrichment stopped after {failures} consecutive failures "
                        "(Play unreachable or rate-limited?); remaining brands use the CSV only. "
                        "Re-run later; already enriched brands are not queried again."
                    )

        content = _dump(build_profile(entry, enrichment, registry.source))
        keep.add(path)
        if current is None:
            report.changes.append(Change(Action.CREATE, path, entry.brand_name, content=content))
        elif path.read_text(encoding="utf-8-sig") == content:
            report.changes.append(Change(Action.UNCHANGED, path, entry.brand_name))
        else:
            report.changes.append(Change(Action.UPDATE, path, entry.brand_name, content=content))

    if prune:
        inactive = {f"{e.id}.json" for e in registry.entries if not e.active}
        for path, data in existing.items():
            if path in keep or path in manual:
                continue
            reason = "deactivated in the CSV" if path.name in inactive else "no longer in the CSV"
            report.changes.append(Change(
                Action.REMOVE, path, str(data.get("brand_name", path.stem)), reason,
            ))

    removing = report.count(Action.REMOVE)
    if removing and not registry.active:
        report.errors.append(
            f"refusing to remove {removing} profile(s): the CSV has no active brands "
            "(truncated or wrong file?)"
        )
    return report


def apply_sync(report: SyncReport, watchlist: Path) -> None:
    """Write the planned changes. Each file is written atomically."""
    if report.errors:
        return
    watchlist.mkdir(parents=True, exist_ok=True)
    for change in report.changes:
        if change.action in (Action.CREATE, Action.UPDATE) and change.content is not None:
            tmp = change.path.with_suffix(".json.tmp")
            tmp.write_text(change.content, encoding="utf-8", newline="\n")
            tmp.replace(change.path)
        elif change.action is Action.REMOVE:
            change.path.unlink(missing_ok=True)
    report.applied = True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_SYMBOL = {
    Action.CREATE: "+", Action.UPDATE: "~", Action.REMOVE: "-",
    Action.SKIP_MANUAL: "!", Action.SKIP_COVERED: "!", Action.UNCHANGED: "=",
}


def _print_report(report: SyncReport, *, dry_run: bool, verbose: bool) -> None:
    for e in report.errors:
        print(f"ERROR   {e}")
    for w in report.warnings:
        print(f"warning {w}")
    for c in report.changes:
        if c.action is Action.UNCHANGED and not verbose:
            continue
        note = f"  ({c.reason})" if c.reason else ""
        print(f"  {_SYMBOL[c.action]} {c.action.value:<13}{c.path.name:<34}{c.brand}{note}")
    for r in report.review:
        print(f"review  {r}")

    counts = ", ".join(
        f"{report.count(a)} {a.value}" for a in Action if report.count(a)
    ) or "nothing to do"
    if report.errors:
        print(f"\n{len(report.errors)} error(s); nothing was written. Fix the CSV and re-run.")
    elif dry_run:
        print(f"\ncheck: {counts}. Nothing written; run 'sync' to apply.")
    else:
        print(f"\nsynced: {counts}.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m brandguard.registry",
        description="Keep data/watchlist in sync with a brand CSV.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("check", "validate the CSV and show what sync would change (writes nothing)"),
        ("sync", "write, update and remove generated profiles to match the CSV"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--csv", type=Path, default=Path("data/brands.csv"))
        p.add_argument("--watchlist", type=Path, default=Path("data/watchlist"))
        p.add_argument("--no-prune", action="store_true",
                       help="never remove generated profiles missing from the CSV")
        p.add_argument("--enrich", action="store_true",
                       help="fill official publishers/apps from Google Play (domain-verified)")
        p.add_argument("--refresh", action="store_true",
                       help="with --enrich, re-query brands that were already enriched")
        p.add_argument("--hits", type=int, default=15, help="Play results per brand for --enrich")
        p.add_argument("--delay", type=float, default=2.0,
                       help="seconds between Play lookups (rate-limit courtesy)")
        p.add_argument("--only", default=None,
                       help="comma-separated ids to process (others are left as they are)")
        p.add_argument("-v", "--verbose", action="store_true", help="also list unchanged profiles")
    args = parser.parse_args(argv)

    if not args.csv.exists():
        print(f"ERROR   {args.csv} not found")
        return 2
    registry = load_registry(args.csv)
    prune = not args.no_prune
    if args.only:
        wanted = {s.strip().lower() for s in args.only.split(",") if s.strip()}
        unknown = wanted - {e.id for e in registry.entries}
        if unknown:
            registry.errors.append(f"--only: unknown id(s) {sorted(unknown)}")
        registry.entries = [e for e in registry.entries if e.id in wanted]
        prune = False  # a partial run must not remove the brands it skipped

    enricher = None
    progress = None
    if args.enrich:
        client = GooglePlayClient()
        enricher = lambda entry: enrich_from_play(entry, client, hits=args.hits)
        total = len(registry.active)
        position = {e.id: i for i, e in enumerate(registry.active, start=1)}

        def progress(entry: BrandEntry) -> None:
            print(f"  enriching {position[entry.id]}/{total} {entry.brand_name} ...",
                  file=sys.stderr, flush=True)

    dry_run = args.command == "check"
    report = plan_sync(
        registry, args.watchlist, enricher=enricher, refresh=args.refresh,
        prune=prune, delay=args.delay if args.enrich else 0.0, progress=progress,
    )
    if not dry_run:
        apply_sync(report, args.watchlist)
    _print_report(report, dry_run=dry_run, verbose=args.verbose)
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
