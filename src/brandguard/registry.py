"""Brand registry: one CSV file is the source of truth for the watchlist.

Scanning many brands needs one place to list them. Hand-writing a profile JSON
per brand does not scale past a handful, so the registry keeps brands as rows in
a CSV (editable in Excel) and generates the profile JSONs the hunt sweep reads:

    data/brands.csv  --check-->  validated rows  --sync-->  data/watchlist/<id>.json
                           (--enrich: official domain, publishers and apps looked up online)

    python -m brandguard.registry check
    python -m brandguard.registry sync --enrich
    python -m brandguard.hunt --watchlist data/watchlist --source play,serper

The smallest CSV is a single column: a "brand_name" header and one brand per
line. Everything else is optional and, when given, always wins over what is
looked up online. List cells use "|" between values, so the file works with
both "," and ";" delimiters:

    id                    profile file name; defaults to a slug of brand_name
    brand_name            e.g. Ziraat Bankasi (the only required column)
    official_domains      ziraatbank.com.tr|ziraat.com.tr (discovered when empty)
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

Online lookup (--enrich) runs in two steps, both cached in the profile:

  1. Domain discovery, only for rows without official_domains. The official
     domain is accepted when two independent sources agree: Google's knowledge
     panel or top result (via Serper) and the developer website of the brand's
     app on Google Play. One source alone is accepted only in the forms an
     attacker cannot cheaply produce - Google's knowledge panel, or a Play app
     with at least a million installs - and is flagged for review. Otherwise
     the brand is skipped and reported; no domain is ever guessed.
  2. Enrichment fills official publishers, package ids and app titles from
     Google Play, but only for publishers whose developer website or e-mail is
     under an official domain. A publisher name that merely looks right is
     reported for review, never written: the name is attacker-controlled, the
     domain proof is not (the same rule as the publisher veto, K-014).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import time
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Protocol

from brandguard.schema import BrandProfile

MANAGED_KEY = "_registry"
MANAGER = "brandguard.registry"
LIST_SEP = "|"

REQUIRED_COLUMNS = ("brand_name",)
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
    return host.removeprefix("www.")


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
# Online lookup: domain discovery and Google Play enrichment
# ---------------------------------------------------------------------------

# Words too common to identify a brand on their own ("Turkiye Is Bankasi" must
# not match every app that says "bankasi").
_GENERIC_TOKENS = frozenset({
    "bank", "banka", "bankasi", "turkiye", "turk", "mobil", "mobile", "app", "kargo",
    "cargo", "holding", "group", "grup", "sirketi", "anonim", "limited", "the",
})

# Hosts that are never a brand's own site: social networks, encyclopedias,
# stores, complaint sites and free mail providers.
_NOT_A_BRAND_SITE = (
    "wikipedia.org", "linkedin.com", "facebook.com", "instagram.com", "twitter.com",
    "x.com", "youtube.com", "tiktok.com", "play.google.com", "apps.apple.com",
    "google.com", "sikayetvar.com", "eksisozluk.com", "gmail.com", "hotmail.com",
    "outlook.com", "yahoo.com", "icloud.com", "yandex.com", "yandex.com.tr",
    "github.com", "medium.com", "blogspot.com", "wordpress.com", "sites.google.com",
    "bit.ly", "linktr.ee",
)

# A Play app with this many installs is treated as the brand's real app when it
# is the only evidence: organic download volume is what an impersonator cannot
# produce (THREAT_MODEL.md, "Cannot do").
PLAY_ONLY_MIN_INSTALLS = 1_000_000

# Play's developer website and e-mail are self-declared. They count as proof of
# identity only together with an app this established, for the same reason.
ESTABLISHED_MIN_INSTALLS = 100_000


def _brand_keys(brand: str) -> tuple[str, list[str]]:
    slug = slugify(brand)
    distinctive = [t for t in slug.split("_") if len(t) >= 4 and t not in _GENERIC_TOKENS]
    return slug.replace("_", ""), distinctive


def mentions_brand(text: str, brand: str, *, full_name: bool = False) -> bool:
    """True when text names the brand: its full name, or one of its distinctive words.

    With ``full_name`` only the complete brand name counts ("Yapi Kredi", not
    just "kredi"), for decisions that rest on a single source.
    """
    compact_text = slugify(text).replace("_", "")
    if not compact_text:
        return False
    compact_brand, distinctive = _brand_keys(brand)
    if len(compact_brand) >= 3 and compact_brand in compact_text:
        return True
    return not full_name and any(token in compact_text for token in distinctive)


def _is_brand_site(host: str) -> bool:
    return bool(host) and bool(_HOST_RE.match(host)) and not host_under(host, _NOT_A_BRAND_SITE)


def _same_site(a: str, b: str) -> bool:
    return host_under(a, [b]) or host_under(b, [a])


def _installs(item: dict) -> int:
    for key in ("realInstalls", "minInstalls"):
        value = item.get(key)
        if isinstance(value, int):
            return value
    digits = re.sub(r"\D", "", str(item.get("installs") or ""))
    return int(digits) if digits else 0


def _email_domain(email: object) -> str:
    return email.split("@")[-1].strip().lower() if isinstance(email, str) and "@" in email else ""


class PlayClient(Protocol):
    """The two calls the lookup needs. The real one wraps google-play-scraper."""

    def search(self, query: str, n_hits: int) -> list[dict]: ...

    def details(self, app_id: str) -> dict: ...


class WebSearchClient(Protocol):
    """One Google search returning the raw Serper JSON (organic + knowledgeGraph)."""

    def lookup(self, query: str) -> dict: ...


class GooglePlayClient:
    def __init__(self, lang: str = "tr", country: str = "tr") -> None:
        try:
            from google_play_scraper import app

            from brandguard.discovery.play_search import search  # keeps the top result (K-056)
        except ImportError as exc:  # pragma: no cover - depends on the optional extra
            raise SystemExit('--enrich needs the live extra: pip install -e ".[live]"') from exc
        self._app, self._search = app, search
        self.lang, self.country = lang, country

    def search(self, query: str, n_hits: int) -> list[dict]:
        return self._search(query, n_hits=n_hits, lang=self.lang, country=self.country)

    def details(self, app_id: str) -> dict:
        return self._app(app_id, lang=self.lang, country=self.country)


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Fill gaps in os.environ from .env, like the adjudicator and Serper source do."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#") and key.strip() not in os.environ:
            os.environ[key.strip()] = value.strip().strip("'\"")


class SerperWebClient:
    """Google search through Serper, localised to Turkey. Needs SERPER_API_KEY."""

    def __init__(self) -> None:
        _load_dotenv()
        self._key = os.environ.get("SERPER_API_KEY", "")
        if not self._key:
            raise RuntimeError("SERPER_API_KEY is not set")

    def lookup(self, query: str) -> dict:
        import requests

        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": self._key, "Content-Type": "application/json"},
            json={"q": query, "gl": "tr", "hl": "tr", "num": 10},
            timeout=20,
        )
        response.raise_for_status()
        return response.json()


def fetch_play_listings(brand: str, client: PlayClient, *, hits: int = 15) -> list[dict]:
    """Search Play for the brand and merge each hit with its detail page."""
    listings: list[dict] = []
    for hit in client.search(brand, hits):
        app_id = str(hit.get("appId") or "").strip()
        if not app_id:
            continue
        try:
            detail = client.details(app_id) or {}
        except Exception:  # noqa: BLE001 - one failed detail must not lose the brand
            detail = {}
        listings.append({**hit, **detail, "appId": app_id})
    return listings


@dataclass
class Discovery:
    """How a brand's official domain was found, kept so the proof can be audited."""

    domains: list[str]
    method: str
    evidence: list[str] = field(default_factory=list)
    review: bool = False
    checked_at: str = ""

    def to_json(self) -> dict:
        return {
            "domains": self.domains, "method": self.method, "evidence": self.evidence,
            "review": self.review, "checked_at": self.checked_at,
        }

    @classmethod
    def from_json(cls, data: dict) -> Discovery:
        return cls(
            domains=list(data.get("domains", [])), method=str(data.get("method", "")),
            evidence=list(data.get("evidence", [])), review=bool(data.get("review")),
            checked_at=str(data.get("checked_at", "")),
        )


def discover_domain(
    brand: str,
    listings: list[dict],
    web_result: dict | None,
    *,
    min_installs: int = ESTABLISHED_MIN_INSTALLS,
) -> Discovery | None:
    """Find a brand's official domain from Play listings and a Google search result.

    Accepted, strongest first:
      1. a Google candidate that matches the developer site of the brand's Play
         app: the knowledge panel website, or a top result about the brand when
         that Play app is established (``min_installs``);
      2. Google's knowledge panel website alone (flagged for review);
      3. the developer site of a brand app with >= 1M installs alone (review).
    Returns None when none applies: an unproven domain is worse than none,
    because the veto would trust it.
    """
    today = datetime.now(tz=UTC).date().isoformat()

    play_sites: list[tuple[str, int, str, bool]] = []  # (host, installs, app_id, full-name match)
    for item in listings:
        title, developer = str(item.get("title") or ""), str(item.get("developer") or "")
        if not (mentions_brand(title, brand) or mentions_brand(developer, brand)):
            continue
        full = mentions_brand(title, brand, full_name=True) or mentions_brand(
            developer, brand, full_name=True)
        website, email = str(item.get("developerWebsite") or ""), item.get("developerEmail")
        for raw in (website, _email_domain(email)):
            host = normalize_domain(raw) if raw else ""
            if _is_brand_site(host):
                play_sites.append((host, _installs(item), item["appId"], full))

    google: list[tuple[str, str]] = []  # (host, where it came from)
    if web_result:
        panel = web_result.get("knowledgeGraph") or {}
        site = normalize_domain(str(panel.get("website") or ""))
        if _is_brand_site(site):
            google.append((site, "Google knowledge panel"))
        for rank, hit in enumerate((web_result.get("organic") or [])[:5], start=1):
            host = normalize_domain(str(hit.get("link") or ""))
            if _is_brand_site(host) and (mentions_brand(host, brand)
                                         or mentions_brand(str(hit.get("title") or ""), brand)):
                google.append((host, f"Google result #{rank}"))

    for g_host, g_where in google:
        for p_host, installs, app_id, _full in play_sites:
            # A web result can be ranked and a Play site typed in by the same
            # attacker; the knowledge panel cannot. Organic agreement therefore
            # needs the Play side to be an established app.
            organic = g_where != "Google knowledge panel"
            if organic and installs < min_installs:
                continue
            if _same_site(g_host, p_host):
                domain = min(g_host, p_host, key=len)
                return Discovery(
                    domains=[domain], method="google+play", checked_at=today,
                    evidence=[f"{g_where}: {g_host}",
                              f"Play developer site of {app_id} ({installs:,} installs): {p_host}"],
                )

    panel_hits = [(h, w) for h, w in google if w == "Google knowledge panel"]
    if panel_hits:
        host, where = panel_hits[0]
        return Discovery(domains=[host], method="google_knowledge_panel", review=True,
                         checked_at=today, evidence=[f"{where}: {host} (not confirmed on Play)"])

    popular = sorted(
        (s for s in play_sites if s[3] and s[1] >= PLAY_ONLY_MIN_INSTALLS), key=lambda s: -s[1]
    )
    if popular:
        host, installs, app_id, _full = popular[0]
        return Discovery(
            domains=[host], method="play_popular_app", review=True, checked_at=today,
            evidence=[(f"Play developer site of {app_id} ({installs:,} installs): {host} "
                       "(not confirmed by Google)")],
        )
    return None


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


def enrich_from_listings(
    entry: BrandEntry,
    listings: list[dict],
    *,
    min_installs: int = ESTABLISHED_MIN_INSTALLS,
) -> Enrichment:
    """Pick the brand's official Play apps from search listings.

    Play's developer website and e-mail are typed in by the developer, so a
    domain under an official domain is only a claim: an impersonator can type
    the brand's domain too. A publisher is accepted only when that claim is
    backed by what an impersonator cannot produce, organic install volume: at
    least one of its apps in the results has ``min_installs`` or more. Every app
    of an accepted publisher is then official, however small (a new product of
    an established publisher). Claims without an established app, and
    publishers that only resemble the brand by name, go to needs_review and are
    never written into the profile.
    """
    result = Enrichment(
        domains=list(entry.official_domains),
        checked_at=datetime.now(tz=UTC).date().isoformat(),
    )
    claims: dict[str, str] = {}
    reach: dict[str, tuple[int, str]] = {}  # publisher -> (max installs, app id)
    for item in listings:
        publisher = str(item.get("developer") or "").strip()
        if not publisher:
            continue
        installs = _installs(item)
        if installs > reach.get(publisher, (-1, ""))[0]:
            reach[publisher] = (installs, item["appId"])
        if publisher in claims:
            continue
        website = str(item.get("developerWebsite") or "")
        email_dom = _email_domain(item.get("developerEmail"))
        if website and host_under(website, entry.official_domains):
            claims[publisher] = f"developer website {normalize_domain(website)}"
        elif email_dom and host_under(email_dom, entry.official_domains):
            claims[publisher] = f"developer e-mail domain {email_dom}"

    accepted: dict[str, str] = {}
    for publisher, claim in claims.items():
        installs, top_app = reach[publisher]
        if installs >= min_installs:
            accepted[publisher] = f"{claim}, established by {top_app} ({installs:,} installs)"
        else:
            result.needs_review.append(
                f"publisher {publisher!r} claims {claim} but none of its apps has "
                f"{min_installs:,}+ installs (largest: {top_app}, {installs:,}); a claimed "
                "domain alone is not proof. Add it to official_publishers if it is genuine"
            )

    for item in listings:
        publisher = str(item.get("developer") or "").strip()
        app_id = item["appId"]
        title = str(item.get("title") or "").strip()
        if publisher in accepted:
            result.package_ids.append(app_id)
            if title:
                result.apps.append(title)
            result.evidence.append(f"{app_id}: {publisher!r} via {accepted[publisher]}")
        elif publisher and publisher not in claims and mentions_brand(publisher, entry.brand_name):
            result.needs_review.append(
                f"{app_id}: publisher {publisher!r} resembles the brand but has no "
                "website/e-mail under an official domain"
            )

    result.publishers = list(accepted)
    result.package_ids = _dedupe(result.package_ids)
    result.apps = _dedupe(result.apps)
    result.needs_review = _dedupe(result.needs_review)
    return result


def enrich_from_play(
    entry: BrandEntry,
    client: PlayClient,
    *,
    hits: int = 15,
    min_installs: int = ESTABLISHED_MIN_INSTALLS,
) -> Enrichment:
    """Search Play for the brand and enrich from the results."""
    listings = fetch_play_listings(entry.brand_name, client, hits=hits)
    return enrich_from_listings(entry, listings, min_installs=min_installs)


class OnlineResolver:
    """Domain discovery and enrichment sharing one Play search per brand."""

    def __init__(
        self,
        play: PlayClient,
        web: WebSearchClient | None,
        *,
        hits: int = 15,
        min_installs: int = ESTABLISHED_MIN_INSTALLS,
    ) -> None:
        self.play, self.web, self.hits, self.min_installs = play, web, hits, min_installs
        self._listings: dict[str, list[dict]] = {}

    def listings(self, brand: str) -> list[dict]:
        if brand not in self._listings:
            self._listings[brand] = fetch_play_listings(brand, self.play, hits=self.hits)
        return self._listings[brand]

    def discover(self, entry: BrandEntry) -> Discovery | None:
        web_result = self.web.lookup(entry.brand_name) if self.web is not None else None
        return discover_domain(entry.brand_name, self.listings(entry.brand_name), web_result,
                               min_installs=self.min_installs)

    def enrich(self, entry: BrandEntry) -> Enrichment:
        return enrich_from_listings(entry, self.listings(entry.brand_name),
                                    min_installs=self.min_installs)


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
    SKIP_UNRESOLVED = "skip-no-domain"


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


def build_profile(
    entry: BrandEntry,
    enrichment: Enrichment | None,
    source: str,
    discovery: Discovery | None = None,
) -> dict:
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
    if discovery is not None:
        block["discovery"] = discovery.to_json()
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


class _Online:
    """Rate limiting, progress and a circuit breaker shared by all online calls."""

    def __init__(self, delay: float, max_failures: int,
                 progress: Callable[[BrandEntry], None] | None, report: SyncReport) -> None:
        self.delay, self.max_failures = delay, max_failures
        self.progress, self.report = progress, report
        self.failures = 0
        self.down = False
        self._last_brand: str | None = None

    def call(
        self, what: str, entry: BrandEntry, fn: Callable[[BrandEntry], object]
    ) -> tuple[bool, object]:
        """Run fn(entry). Returns (ok, result); never raises."""
        if self.down:
            return False, None
        if self._last_brand != entry.id:
            if self._last_brand is not None and self.delay:
                time.sleep(self.delay)
            self._last_brand = entry.id
            if self.progress is not None:
                self.progress(entry)
        try:
            result = fn(entry)
        except Exception as exc:  # noqa: BLE001 - one brand failing must not stop the sync
            self.failures += 1
            self.report.warnings.append(f"{entry.brand_name}: {what} failed ({type(exc).__name__})")
            if self.failures >= self.max_failures:
                self.down = True
                self.report.warnings.append(
                    f"online lookup stopped after {self.failures} consecutive failures "
                    "(unreachable or rate-limited?); remaining brands use the CSV and cache only. "
                    "Re-run later: brands already looked up are not queried again."
                )
            return False, None
        self.failures = 0
        return True, result


def plan_sync(
    registry: Registry,
    watchlist: Path,
    *,
    enricher: Callable[[BrandEntry], Enrichment] | None = None,
    discoverer: Callable[[BrandEntry], Discovery | None] | None = None,
    refresh: bool = False,
    prune: bool = True,
    delay: float = 0.0,
    max_failures: int = 3,
    progress: Callable[[BrandEntry], None] | None = None,
) -> SyncReport:
    """Work out every file change without writing anything.

    Online work is incremental: a brand whose domain was already discovered, or
    that was already enriched against its current official domains, is not
    queried again unless ``refresh`` is set, so a sweep over a large CSV only
    pays for new or changed brands. After ``max_failures`` consecutive online
    failures the sources are treated as down for the rest of the run.
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

    online = _Online(delay, max_failures, progress, report)
    keep: set[Path] = set()
    for row in registry.active:
        entry = row  # replaced below by a copy carrying the discovered domains
        path = watchlist / f"{entry.id}.json"
        if path in manual:
            report.changes.append(Change(
                Action.SKIP_MANUAL, path, entry.brand_name,
                "hand-maintained profile with this id exists; it takes priority",
            ))
            continue

        current = existing.get(path)
        block = (current or {}).get(MANAGED_KEY, {})

        # 1. Official domains: the CSV wins; otherwise the cached or a new discovery.
        discovery: Discovery | None = None
        if not entry.official_domains:
            if block.get("discovery") and not refresh:
                discovery = Discovery.from_json(block["discovery"])
            elif discoverer is not None:
                ok, found = online.call("domain discovery", entry, discoverer)
                if ok and found is None:
                    report.warnings.append(
                        f"{entry.brand_name}: no official domain could be proven online"
                    )
                discovery = found if ok else (
                    Discovery.from_json(block["discovery"]) if block.get("discovery") else None
                )
            if discovery is None:
                hint = ("add official_domains to its CSV row" if discoverer is not None
                        else "run 'sync --enrich' or add official_domains to its CSV row")
                report.changes.append(Change(
                    Action.SKIP_UNRESOLVED, path, entry.brand_name, f"no official domain; {hint}",
                ))
                if current is not None:
                    keep.add(path)  # keep a previously resolved profile rather than drop coverage
                continue
            entry = replace(entry, official_domains=tuple(discovery.domains))
            fresh = discovery.to_json() != block.get("discovery")
            if discovery.review and fresh:  # remind once, when first found
                proof = "; ".join(discovery.evidence)
                report.review.append(
                    f"{entry.brand_name}: domain {', '.join(discovery.domains)} from "
                    f"{discovery.method}; confirm it or put it in the CSV ({proof})"
                )

        covered = next(
            (manual_domains[d] for d in entry.official_domains if d in manual_domains), None
        )
        if covered is not None:
            report.changes.append(Change(
                Action.SKIP_COVERED, path, entry.brand_name,
                f"already covered by hand-maintained {covered.name}",
            ))
            continue

        # 2. Enrichment against those domains, cached until the domains change.
        enrichment = None
        if block.get("enrichment"):
            enrichment = Enrichment.from_json(block["enrichment"])
            if enrichment.domains != list(entry.official_domains):
                enrichment = None  # official domains changed: the old proof is stale
                report.warnings.append(
                    f"{entry.brand_name}: official domains changed, previous enrichment dropped"
                )
        if enricher is not None and (enrichment is None or refresh):
            ok, fresh = online.call("enrichment", entry, enricher)
            if ok:
                enrichment = fresh
                report.review.extend(f"{entry.brand_name}: {r}" for r in fresh.needs_review)
                if not fresh.publishers:
                    report.warnings.append(
                        f"{entry.brand_name}: Play enrichment found no domain-verified publisher"
                    )
            elif not online.down:
                kept = "previous enrichment kept" if enrichment else "profile written from CSV only"
                report.warnings[-1] += f"; {kept}"

        content = _dump(build_profile(entry, enrichment, registry.source, discovery))
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
    Action.SKIP_MANUAL: "!", Action.SKIP_COVERED: "!", Action.SKIP_UNRESOLVED: "?",
    Action.UNCHANGED: "=",
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
        print(f"  {_SYMBOL[c.action]} {c.action.value:<15}{c.path.name:<34}{c.brand}{note}")
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
                       help="look up missing official domains (Google + Play) and fill "
                            "official publishers/apps from Play (domain-verified)")
        p.add_argument("--refresh", action="store_true",
                       help="with --enrich, look up again brands already resolved")
        p.add_argument("--hits", type=int, default=15, help="Play results per brand for --enrich")
        p.add_argument("--min-installs", type=int, default=ESTABLISHED_MIN_INSTALLS,
                       help="installs a publisher's largest app needs before its claimed "
                            "domain is trusted (default: %(default)s)")
        p.add_argument("--delay", type=float, default=2.0,
                       help="seconds between brands during --enrich (rate-limit courtesy)")
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

    enricher = discoverer = progress = None
    if args.enrich:
        web: WebSearchClient | None
        try:
            web = SerperWebClient()
        except RuntimeError:
            web = None
            print("warning SERPER_API_KEY not set: domains are discovered from Google Play only "
                  f"(apps with {PLAY_ONLY_MIN_INSTALLS:,}+ installs), each flagged for review",
                  file=sys.stderr)
        resolver = OnlineResolver(GooglePlayClient(), web, hits=args.hits,
                                  min_installs=args.min_installs)
        enricher, discoverer = resolver.enrich, resolver.discover
        total = len(registry.active)
        position = {e.id: i for i, e in enumerate(registry.active, start=1)}

        def progress(entry: BrandEntry) -> None:
            print(f"  looking up {position[entry.id]}/{total} {entry.brand_name} ...",
                  file=sys.stderr, flush=True)

    dry_run = args.command == "check"
    report = plan_sync(
        registry, args.watchlist, enricher=enricher, discoverer=discoverer, refresh=args.refresh,
        prune=prune, delay=args.delay if args.enrich else 0.0, progress=progress,
    )
    if not dry_run:
        apply_sync(report, args.watchlist)
    _print_report(report, dry_run=dry_run, verbose=args.verbose)
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
