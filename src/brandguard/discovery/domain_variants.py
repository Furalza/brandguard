"""Lookalike domain generation for website-impersonation discovery.

Phishing sites live on domains that imitate the brand's real domain: typosquats,
homoglyphs, added words ("-giris", "-guvenli"), and different TLDs. This module
generates those variants so the discovery layer (Serper) can search for them.
It is the domain-side mirror of query_expansion, and reuses the same character
transformations, since a domain and an app name are attacked the same way.

Discovery is meant to be broad here: a variant we do not generate is a lookalike
domain we can never flag. The list is bounded per strategy so it stays in the
low hundreds, not thousands.
"""

from __future__ import annotations

from dataclasses import dataclass

# Confusable and keyboard maps mirror query_expansion; kept local so the domain
# module has no dependency on the app-name module beyond the idea.
_HOMOGLYPH_SUBS: dict[str, list[str]] = {
    "a": ["a"], "e": ["e"], "o": ["0"], "i": ["1", "l"], "l": ["1", "i"],
    "s": ["5"], "b": ["8"], "g": ["9"],
}

# Words attackers append to a brand domain to look credible.
_LURE_WORDS = ["giris", "guvenli", "online", "mobil", "hesap", "destek", "app", "login"]

# Alternative TLDs a phisher registers when the real one is taken.
_ALT_TLDS = ["com", "net", "org", "info", "online", "site", "app", "com.tr"]

# Common typo operations on the label (the part before the TLD).
def _typos(label: str) -> list[str]:
    out: list[str] = []
    for i in range(len(label)):
        out.append(label[:i] + label[i + 1 :])                       # deletion
        if label[i].isalpha():
            out.append(label[:i] + label[i] + label[i] + label[i + 1 :])  # doubling
    for i in range(len(label) - 1):
        out.append(label[:i] + label[i + 1] + label[i] + label[i + 2 :])  # swap
    return out


@dataclass(frozen=True)
class DomainVariant:
    """A candidate lookalike domain plus the strategy that produced it."""

    domain: str
    strategy: str


def _split(domain: str) -> tuple[str, str]:
    """Split a domain into (label, tld). 'ornekbank.com.tr' -> ('ornekbank', 'com.tr')."""
    parts = domain.lower().strip().split(".")
    if len(parts) >= 3 and parts[-2] in {"com", "co", "net", "org", "gov"}:
        return parts[0], ".".join(parts[1:])   # two-part TLD like com.tr
    if len(parts) >= 2:
        return parts[0], ".".join(parts[1:])
    return domain, ""


def expand_domain(official_domain: str, *, typo_cap: int = 30, leet_cap: int = 20) -> list[DomainVariant]:
    """Generate lookalike variants of one official domain, deduplicated."""
    label, tld = _split(official_domain)
    seen: set[str] = set()
    out: list[DomainVariant] = []

    def add(domain: str, strategy: str) -> None:
        d = domain.lower().strip(".")
        if d and d != official_domain.lower() and d not in seen:
            seen.add(d)
            out.append(DomainVariant(domain=d, strategy=strategy))

    # Typosquats on the label, keeping the real TLD.
    for variant in _typos(label)[:typo_cap]:
        add(f"{variant}.{tld}", "typosquat")

    # Leet/homoglyph digit swaps on the label.
    leet: list[str] = []
    for i, ch in enumerate(label):
        for sub in _HOMOGLYPH_SUBS.get(ch, []):
            if sub != ch:
                leet.append(label[:i] + sub + label[i + 1 :])
    for variant in leet[:leet_cap]:
        add(f"{variant}.{tld}", "leet")

    # Lure words appended with a hyphen, keeping the real TLD.
    for word in _LURE_WORDS:
        add(f"{label}-{word}.{tld}", "lure_word")
        add(f"{label}{word}.{tld}", "lure_word")

    # Same label under a different TLD.
    for alt in _ALT_TLDS:
        if alt != tld:
            add(f"{label}.{alt}", "alt_tld")

    return out
