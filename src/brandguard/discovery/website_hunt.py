"""Website-impersonation discovery and triage (Phase 2a).

Finds domains that imitate a brand's official domain and classifies them on the
one signal available without extra services: domain similarity. This is the
domain-side mirror of the app pipeline, deliberately limited to what can be done
with the Serper key alone.

Honesty about scope: a real website-impersonation verdict needs signals this
phase does not have (WHOIS age, SSL issuer, page content). Those are defined as
an explicit extension point (WebsiteSignal) but not implemented here, so the
module never claims more certainty than its evidence supports. It flags
"lookalike" candidates for an analyst, it does not assert phishing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from brandguard.discovery.domain_variants import expand_domain
from brandguard.discovery.normalize import normalize

# A lookalike verdict, separate from the app Label because the signals and the
# meaning differ. An app can be "impersonation"; a domain we have only compared
# by string is at most a "lookalike" until richer signals confirm it.
class DomainVerdict(str, Enum):
    OFFICIAL = "official"          # exactly the official domain
    LOOKALIKE = "lookalike"        # close to official but not it: worth review
    MENTIONS_BRAND = "mentions"    # uses the brand name, not a domain lookalike
    UNRELATED = "unrelated"        # no meaningful relation


@dataclass(frozen=True)
class DomainFinding:
    """One discovered domain with its verdict and evidence.

    ``confirmed_live`` distinguishes a domain a web search actually returned
    (it exists and is indexed) from a generated lookalike variant (a name we
    constructed, whose registration status is unknown). This separation is
    essential honesty: a generated variant is a name to watch, not a found site.
    """

    domain: str
    verdict: DomainVerdict
    similarity: float
    evidence: list[str]
    source_query: str
    confirmed_live: bool


class SerperClient(Protocol):
    def search(self, query: str, num: int) -> list[dict]: ...


def _label_of(domain: str) -> str:
    return domain.lower().strip().split("/")[0]


def _domain_similarity(candidate: str, official: str) -> float:
    """String similarity of two domain labels after normalization."""
    from rapidfuzz import distance

    a = normalize(_label_of(candidate).replace(".", " "))
    b = normalize(_label_of(official).replace(".", " "))
    return round(distance.JaroWinkler.normalized_similarity(a, b), 3)


def _token_in_label(token: str, label: str) -> bool:
    """True if the brand token appears in the label, tolerant of leet/typo.

    Slides the token across the label and accepts a window that is a close
    fuzzy match, so a distorted brand prefix (z1raatbank) still counts as
    carrying the brand token (ziraat).
    """
    from rapidfuzz import distance

    if token in label:
        return True
    n = len(token)
    for i in range(max(1, len(label) - n + 1)):
        window = label[i : i + n]
        if distance.JaroWinkler.normalized_similarity(token, window) >= 0.85:
            return True
    return False


def classify_domain(candidate: str, profile_domains: list[str], brand_name: str) -> DomainFinding:
    """Classify one candidate domain against the official domains and brand.

    Uses only domain similarity and brand-token presence. A candidate equal to
    an official domain is official; one close to it but not equal is a lookalike
    (the phishing shape); one that merely contains the brand word is a mention;
    anything else is unrelated.
    """
    cand = _label_of(candidate)
    official_set = {d.lower() for d in profile_domains}
    if cand in official_set:
        return DomainFinding(cand, DomainVerdict.OFFICIAL, 1.0,
                             ["Exact match to an official domain."], "", confirmed_live=False)

    best = max((_domain_similarity(cand, d) for d in profile_domains), default=0.0)
    # Does the domain label carry the brand's distinctive token, allowing for
    # leet/typo distortion (z1raat still means ziraat)? Compare the brand token
    # against the label with a high fuzzy threshold rather than exact containment.
    brand_token = normalize(brand_name).split()[0] if brand_name else ""
    label_norm = normalize(cand.replace(".", " "))
    has_brand = bool(brand_token) and _token_in_label(brand_token, label_norm)

    # A lookalike must be both very close in string AND carry the brand token.
    # Two different banks share "bank" and score high on Jaro-Winkler alone;
    # requiring the distinctive brand token avoids flagging a rival's domain.
    if best >= 0.85 and has_brand:
        return DomainFinding(
            cand, DomainVerdict.LOOKALIKE, best,
            [f"Domain closely resembles an official domain (similarity {best}) but is not one."],
            "", confirmed_live=False,
        )
    if has_brand:
        return DomainFinding(
            cand, DomainVerdict.MENTIONS_BRAND, best,
            [f"Domain contains the brand name but is not a close lookalike (similarity {best})."],
            "", confirmed_live=False,
        )
    return DomainFinding(cand, DomainVerdict.UNRELATED, best,
                         [f"Domain does not resemble the brand (similarity {best})."], "",
                         confirmed_live=False)


def build_website_queries(brand_name: str, official_domains: list[str]) -> list[str]:
    """Dorks that surface impersonating websites, excluding the official domains."""
    excludes = " ".join(f"-site:{d}" for d in official_domains)
    return [
        f'"{brand_name}" giris {excludes}',
        f'"{brand_name}" mobil giris {excludes}',
        f'"{brand_name}" hesap {excludes}',
    ]


@dataclass
class WebsiteSignal:
    """Extension point for Phase 2b signals (WHOIS, SSL, page content).

    Not implemented in Phase 2a. Documented here so the architecture shows how a
    richer domain verdict would be built: each signal would contribute evidence
    the way app-side signals do, and fusion would combine them. See KARARLAR.
    """

    name: str
    evidence: list[str] = field(default_factory=list)


def hunt_websites(
    brand_name: str,
    official_domains: list[str],
    *,
    client: SerperClient,
    num: int = 10,
    max_queries: int = 4,
    include_generated_variants: bool = True,
) -> list[DomainFinding]:
    """Discover and classify impersonating-website candidates for a brand.

    Two discovery paths: generated lookalike domains (from the official domain)
    and Serper searches for the brand used off the official domain. Results are
    classified by domain similarity and deduplicated.
    """
    from urllib.parse import urlparse

    findings: dict[str, DomainFinding] = {}

    # Path 1: classify generated lookalike variants directly.
    if include_generated_variants:
        for official in official_domains:
            for variant in expand_domain(official):
                if variant.domain not in findings:
                    base = classify_domain(variant.domain, official_domains, brand_name)
                    findings[variant.domain] = DomainFinding(
                        base.domain, base.verdict, base.similarity,
                        [*base.evidence, f"Generated {variant.strategy} variant (registration unknown)."],
                        source_query="", confirmed_live=False,
                    )

    # Path 2: search the web for the brand off its official domain, classify hits.
    for query in build_website_queries(brand_name, official_domains)[:max_queries]:
        try:
            hits = client.search(query, num=num)
        except Exception as exc:  # noqa: BLE001 - surface search failures per query
            print(f"    . website query {query!r} skipped ({type(exc).__name__})")
            continue
        for hit in hits:
            link = hit.get("link") or ""
            if not link:
                continue
            host = urlparse(link).netloc.lower().removeprefix("www.")
            if host and host not in findings:
                finding = classify_domain(host, official_domains, brand_name)
                findings[host] = DomainFinding(
                    finding.domain, finding.verdict, finding.similarity,
                    [*finding.evidence, "Returned by a live web search."],
                    source_query=query, confirmed_live=True,
                )

    return list(findings.values())
