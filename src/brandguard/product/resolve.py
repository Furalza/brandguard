"""Turn whatever the operator typed into a brand profile.

Accepted inputs, detected without asking:

    brand name      "Papara"
    domain / URL    "papara.com", "https://www.papara.com/tr"
    package id      "com.mobillium.papara"
    store URL       "https://play.google.com/store/apps/details?id=com.mobillium.papara"

Resolution follows the registry's trust rules (K-054/K-055): a domain the
operator typed is itself a trust anchor, so from a domain we only need to
find the brand name and its Play publisher; from a brand name we need two
independent sources to agree on the domain before it becomes official.

The online parts take injectable clients so they are testable without the
network; the API wires in the real Play and Serper clients.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

from brandguard.registry import (
    ESTABLISHED_MIN_INSTALLS,
    BrandEntry,
    PlayClient,
    WebSearchClient,
    _HOST_RE,
    _installs,
    _is_brand_site,
    clean_brand_name,
    _PACKAGE_RE,
    discover_domain,
    enrich_from_listings,
    fetch_play_listings,
    host_under,
    normalize_domain,
    slugify,
)
from brandguard.schema import BrandProfile

_STORE_HOSTS = ("play.google.com", "apkpure.com", "apkmirror.com", "apkcombo.com",
                "aptoide.com", "uptodown.com", "apps.apple.com")
_TLD_LIKE = re.compile(r"\.(com|net|org|io|co|tr|de|uk|app|info|xyz|online|site|biz|gov|edu)(\.[a-z]{2})?$")


@dataclass(frozen=True)
class DetectedInput:
    kind: str            # brand | domain | package | url
    value: str           # cleaned value (host, package id, or trimmed name)
    package_id: str | None = None


# Hosts an operator may type that are still never a brand domain. Social
# networks are absent on purpose: typed "facebook.com" means the brand Facebook.
_PLATFORM_DOMAINS = (
    "play.google.com", "apps.apple.com", "google.com", "sites.google.com", "gmail.com",
    "hotmail.com", "outlook.com", "yahoo.com", "icloud.com", "yandex.com", "yandex.com.tr",
    "bit.ly", "linktr.ee", "blogspot.com", "wordpress.com", "github.com", "medium.com",
    "sikayetvar.com", "eksisozluk.com", "wikipedia.org",
)


def detect_input(text: str) -> DetectedInput:
    """Classify an operator's input. Deterministic, no network."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty input")

    # A URL: a store page yields a package id; any other URL yields its host.
    if "://" in raw or raw.lower().startswith("www."):
        url = raw if "://" in raw else f"https://{raw}"
        parsed = urlparse(url)
        host = normalize_domain(parsed.netloc)
        if host.endswith("play.google.com"):
            ident = parse_qs(parsed.query).get("id", [""])[0].strip()
            if "/developer" in parsed.path and ident:
                # A developer page names the publisher, not an app: scan it as
                # a brand name (found live: a developer URL resolved to
                # "Google LLC" with play.google.com as its official domain).
                return DetectedInput("brand", ident.replace("+", " ").strip())
            if ident and _PACKAGE_RE.match(ident):
                return DetectedInput("url", host, package_id=ident)
            raise ValueError("this Google Play URL names neither an app (details?id=...) "
                             "nor a developer; paste the app's store page")
        if any(host.endswith(s) for s in _STORE_HOSTS):
            m = re.search(r"/([a-z][a-z0-9_]+(?:\.[a-z0-9_]+){1,})", parsed.path.lower())
            if m and (m.group(1).count(".") >= 2 or m.group(1).startswith(("com.", "net.", "org.", "tr."))):
                return DetectedInput("url", host, package_id=m.group(1))
        return DetectedInput("domain", host)

    lowered = raw.lower()
    # A package id: dotted, no spaces, looks like reverse-domain and not a host.
    if " " not in raw and _PACKAGE_RE.match(raw) and raw.count(".") >= 1:
        if lowered.startswith(("com.", "net.", "org.", "tr.", "io.", "app.", "de.", "co.")) \
                and not _TLD_LIKE.search(lowered):
            return DetectedInput("package", raw)
        # "papara.com" is a host; "com.papara" is a package
        if _HOST_RE.match(lowered) and _TLD_LIKE.search(lowered):
            return DetectedInput("domain", normalize_domain(lowered))
        if raw.count(".") >= 2:
            return DetectedInput("package", raw)
    if " " not in raw and _HOST_RE.match(lowered) and "." in lowered:
        return DetectedInput("domain", normalize_domain(lowered))
    return DetectedInput("brand", raw)


@dataclass
class Resolution:
    """A profile plus the audit trail of how it was built."""

    profile: BrandProfile
    how: str                                  # existing | csv | domain+play | play_package | name_only ...
    evidence: list[str] = field(default_factory=list)
    review: list[str] = field(default_factory=list)   # things an analyst should confirm
    brand_id: str = ""

    @property
    def needs_review(self) -> bool:
        return bool(self.review)


def _profile_from_entry(entry: BrandEntry, enrichment) -> BrandProfile:
    return BrandProfile(
        brand_name=entry.brand_name,
        official_domains=list(entry.official_domains),
        official_publishers=list(enrichment.publishers) if enrichment else [],
        known_official_apps=list(enrichment.apps) if enrichment else [],
        sector=entry.sector,
        official_package_ids=list(enrichment.package_ids) if enrichment else [],
        official_permissions=None,
        known_affiliates=[],
    )


def _guess_brand_name_from_listings(host: str, listings: list[dict]) -> tuple[str, str] | None:
    """Return (brand name, app id) from the most-installed Play app whose
    developer site or e-mail sits under the host."""
    best: tuple[int, str, str] | None = None
    for item in listings:
        site = normalize_domain(str(item.get("developerWebsite") or ""))
        email = str(item.get("developerEmail") or "")
        email_dom = email.split("@")[-1].lower() if "@" in email else ""
        if not ((site and host_under(site, [host])) or (email_dom and host_under(email_dom, [host]))):
            continue
        installs = _installs(item)
        if best is None or installs > best[0]:
            best = (installs, str(item.get("developer") or item.get("title") or ""), item["appId"])
    if best is None:
        return None
    return best[1], best[2]


def _title_brand(title: str) -> str:
    """'Papara | Finansal Özgürlük' -> 'Papara'."""
    for sep in (" | ", " – ", " - ", " — ", ": "):
        if sep in title:
            return title.split(sep)[0].strip()
    return title.strip()


def resolve_from_domain(host: str, *, play: PlayClient | None, web: WebSearchClient | None,
                        page_title: str | None = None, hits: int = 15,
                        min_installs: int = ESTABLISHED_MIN_INSTALLS) -> Resolution:
    """Domain typed by the operator -> profile. The domain is trusted as given."""
    host = normalize_domain(host)
    if not _HOST_RE.match(host):
        raise ValueError(f"not a valid domain: {host!r}")
    if host_under(host, _PLATFORM_DOMAINS):
        # A typed domain is trusted (K-060), but a store, a mail provider or a
        # hosting platform can never be a brand's own domain: that scan would
        # make "Google LLC" official for everyone (found live).
        raise ValueError(f"{host} is a store or platform, not a brand's own domain; enter the "
                         "brand's domain, its name, or its app's store page")
    label = host.split(".")[0]
    evidence: list[str] = [f"Official domain taken from the input: {host}"]
    review: list[str] = []
    name: str | None = None
    how = "domain_only"

    listings: list[dict] = []
    if play is not None:
        # Search Play for the domain's first label; the brand's own app usually
        # ranks for it, and its developer site proves the link.
        try:
            listings = fetch_play_listings(label, play, hits=hits)
        except Exception as exc:  # noqa: BLE001
            review.append(f"Play lookup failed ({type(exc).__name__}); profile built from the domain only.")
        guess = _guess_brand_name_from_listings(host, listings)
        if guess is None and page_title:
            # "turkishairlines" finds nothing on Play; the site's own title
            # ("Turkish Airlines | ...") does, and the developer site under
            # the typed domain still proves the link (found live).
            title_name = _title_brand(page_title)
            if title_name and normalize_domain(title_name) != label:
                try:
                    more = fetch_play_listings(title_name, play, hits=hits)
                except Exception:  # noqa: BLE001 - the first lookup already reported
                    more = []
                seen_ids = {item.get("appId") for item in listings}
                listings += [item for item in more if item.get("appId") not in seen_ids]
                guess = _guess_brand_name_from_listings(host, listings)
        if guess:
            developer, app_id = guess
            name = clean_brand_name(developer)
            how = "domain+play"
            evidence.append(f"Brand name from the Play publisher of {app_id}, whose developer site is under {host}")

    if name is None and web is not None:
        try:
            result = web.lookup(host)
            panel = (result or {}).get("knowledgeGraph") or {}
            if panel.get("title"):
                name = clean_brand_name(str(panel["title"]))
                how = "domain+knowledge_panel"
                evidence.append(f"Brand name from Google's knowledge panel for {host}")
        except Exception as exc:  # noqa: BLE001
            review.append(f"Google lookup failed ({type(exc).__name__}).")

    if name is None and page_title:
        name = _title_brand(page_title)
        how = "domain+page_title"
        evidence.append(f"Brand name from the site's page title: {name!r}")

    if name is None:
        name = label.capitalize()
        how = "domain_only"
        review.append(f"Brand name guessed from the domain label ({name!r}); confirm it.")

    entry = BrandEntry(id=slugify(name), brand_name=name, official_domains=(host,),
                       sector="unknown")
    enrichment = enrich_from_listings(entry, listings, min_installs=min_installs) if listings else None
    if enrichment:
        evidence.extend(enrichment.evidence)
        review.extend(enrichment.needs_review)
        if not enrichment.publishers:
            review.append("No Play publisher could be verified for this domain; official apps unknown.")
    profile = _profile_from_entry(entry, enrichment)
    return Resolution(profile=profile, how=how, evidence=evidence, review=review, brand_id=entry.id)


def resolve_from_package(package_id: str, *, play: PlayClient | None, web: WebSearchClient | None,
                         hits: int = 15, min_installs: int = ESTABLISHED_MIN_INSTALLS) -> Resolution:
    """Package id -> its Play listing -> developer site -> domain path."""
    if play is None:
        raise ValueError("resolving a package id needs Google Play access")
    detail = play.details(package_id) or {}
    site = normalize_domain(str(detail.get("developerWebsite") or ""))
    email = str(detail.get("developerEmail") or "")
    email_dom = email.split("@")[-1].lower() if "@" in email else ""
    title = str(detail.get("title") or package_id)
    developer = str(detail.get("developer") or "")
    # The listing's own title or developer is the brand hint, so a platform
    # whose site is normally excluded (tiktok.com for TikTok) still resolves.
    host = next((h for h in (site, email_dom)
                 if _is_brand_site(h, title) or _is_brand_site(h, developer)), "")
    developer = clean_brand_name(developer) if developer else developer
    if not host:
        # No usable domain on the listing: the app becomes the seed of a
        # name-only profile and the analyst is told why.
        res = resolve_from_name(developer or title, play=play, web=web, hits=hits,
                                min_installs=min_installs)
        res.evidence.insert(0, f"Started from package {package_id} ({title!r} by {developer!r}); "
                               "its listing declares no usable website")
        return res
    res = resolve_from_domain(host, play=play, web=web, hits=hits, min_installs=min_installs)
    res.evidence.insert(0, f"Started from package {package_id} ({title!r} by {developer!r}); "
                           f"its developer site is {host}")
    res.how = "package+" + res.how
    if _installs(detail) < min_installs and package_id not in res.profile.official_package_ids:
        res.review.append(
            f"{package_id} has {_installs(detail):,} installs, below the {min_installs:,} needed to "
            "count its declared website as proof; it is scanned but not assumed official."
        )
    return res


def resolve_from_name(brand_name: str, *, play: PlayClient | None, web: WebSearchClient | None,
                      hits: int = 15, min_installs: int = ESTABLISHED_MIN_INSTALLS) -> Resolution:
    """Brand name -> registry discovery (two sources) -> enrichment."""
    name = brand_name.strip()
    entry = BrandEntry(id=slugify(name), brand_name=name, official_domains=(), sector="unknown")
    evidence: list[str] = []
    review: list[str] = []
    listings: list[dict] = []
    if play is not None:
        try:
            listings = fetch_play_listings(name, play, hits=hits)
        except Exception as exc:  # noqa: BLE001
            review.append(f"Play lookup failed ({type(exc).__name__}).")
    web_result = None
    if web is not None:
        try:
            web_result = web.lookup(name)
        except Exception as exc:  # noqa: BLE001
            review.append(f"Google lookup failed ({type(exc).__name__}).")

    discovery = discover_domain(name, listings, web_result, min_installs=min_installs)
    if discovery is None:
        review.append("No official domain could be established from two independent sources; "
                      "the scan runs on the name alone and cannot verify official apps.")
        profile = _profile_from_entry(entry, None)
        return Resolution(profile=profile, how="name_only", evidence=evidence, review=review,
                          brand_id=entry.id)

    evidence.extend(discovery.evidence)
    if discovery.review:
        review.append(f"Official domain {discovery.domains[0]} came from a single source "
                      f"({discovery.method}); confirm it.")
    entry = BrandEntry(id=entry.id, brand_name=name, official_domains=tuple(discovery.domains),
                       sector="unknown")
    enrichment = enrich_from_listings(entry, listings, min_installs=min_installs) if listings else None
    if enrichment:
        evidence.extend(enrichment.evidence)
        review.extend(enrichment.needs_review)
    profile = _profile_from_entry(entry, enrichment)
    return Resolution(profile=profile, how=f"name+{discovery.method}", evidence=evidence,
                      review=review, brand_id=entry.id)
