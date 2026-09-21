"""Structural analysis of a candidate domain's anatomy.

String similarity alone cannot tell paypal-login.info (a phishing shape) from
paypalobjects.com (PayPal's real CDN); both merely "contain paypal". What
separates them is anatomy: where the brand token sits, what word sits next to
it, and how risky the TLD is. This module scores those three, so a brand token
followed by an account-action word on a cheap TLD is recognized as a lookalike
even when its overall string distance from the official domain is large.

The lexicon is intent-based: an account-action word (login, secure, verify) next
to the brand is the phishing pattern; a neutral word (a country, a product name)
is not. This keeps legitimate "brand-product" and "brand-region" domains as
mentions while promoting "brand-login" style domains to lookalikes.
"""

from __future__ import annotations

from dataclasses import dataclass

# Words attackers pair with a brand to bait a credential entry. Presence of one
# of these next to the brand token is the strongest structural phishing signal.
_LURE_WORDS = frozenset({
    "login", "signin", "secure", "security", "verify", "verification", "account",
    "update", "confirm", "auth", "authenticate", "wallet", "unlock", "recover",
    "recovery", "support", "service", "billing", "payment", "alert", "suspended",
    "giris", "guvenli", "dogrulama", "hesap", "sifre", "parola", "destek",  # Turkish
})

# Cheap or abuse-prone TLDs phishers favour; a lure on one of these is worse.
_RISKY_TLDS = frozenset({
    "info", "xyz", "top", "online", "site", "click", "link", "live", "app",
    "icu", "cyou", "shop", "store", "buzz", "rest", "fit", "mobi", "tk", "ml",
    "ga", "cf", "gq", "work", "sbs", "cfd",
})


@dataclass(frozen=True)
class DomainAnatomy:
    """Structural read of a candidate domain relative to a brand token."""

    brand_at_start: bool
    lure_words: tuple[str, ...]
    risky_tld: bool
    phishing_shape: bool      # brand-prefixed AND carries a lure word
    evidence: list[str]


def _split_label_and_tld(domain: str) -> tuple[str, str]:
    parts = domain.lower().strip().split(".")
    if len(parts) >= 3 and parts[-2] in {"com", "co", "net", "org", "gov", "edu"}:
        return ".".join(parts[:-2]), parts[-1]   # tld is the last part; keep it simple
    if len(parts) >= 2:
        return ".".join(parts[:-1]), parts[-1]
    return domain, ""


def _words(label: str) -> list[str]:
    """Split a domain label into words on hyphen, underscore and dot."""
    out: list[str] = []
    for chunk in label.replace("_", "-").replace(".", "-").split("-"):
        chunk = chunk.strip()
        if chunk:
            out.append(chunk)
    return out


def analyze_domain(domain: str, brand_token: str) -> DomainAnatomy:
    """Read a domain's anatomy relative to the brand token.

    ``domain`` is a hostname (no scheme). ``brand_token`` is the distinctive
    brand word already normalized (e.g. "paypal", "ziraat").
    """
    label, tld = _split_label_and_tld(domain)
    words = _words(label)
    lures = tuple(w for w in words if w in _LURE_WORDS)
    risky = tld in _RISKY_TLDS

    # Brand at the start: the first word is (or fuzzily is) the brand token, or
    # the first word begins with it (paypal-login -> first word "paypal").
    brand_at_start = False
    if words:
        first = words[0]
        brand_at_start = first == brand_token or first.startswith(brand_token)

    phishing_shape = brand_at_start and bool(lures)

    evidence: list[str] = []
    if phishing_shape:
        evidence.append(
            f"Domain is brand-prefixed and pairs it with credential-bait word(s): "
            f"{', '.join(lures)}."
        )
    elif lures:
        evidence.append(f"Domain contains credential-bait word(s): {', '.join(lures)}.")
    if risky:
        evidence.append(f"Uses a cheap/abuse-prone TLD (.{tld}).")

    return DomainAnatomy(
        brand_at_start=brand_at_start,
        lure_words=lures,
        risky_tld=risky,
        phishing_shape=phishing_shape,
        evidence=evidence,
    )
