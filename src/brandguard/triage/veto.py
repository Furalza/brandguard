"""Veto signals.

These are the highest-trust signals in the threat model, but trust is placed in
publisher *identity*, not the publisher *name*. A name is attacker-controlled: an
impersonator can set it to the flattened official name ("Ornek Bank A.S" for
"Örnek Bank A.Ş.") and, on a normalized match alone, would be waved through as
official. That is a real hole, so the veto uses defense in depth.

An official veto requires two independent conditions:

1. The publisher name matches the official list (normalized, so a store's
   Turkish flattening still matches).
2. At least one verifier the attacker cannot cheaply forge is present: a website
   under an official domain, a store ``verified`` flag, or an account age
   consistent with an established brand.

Name match alone does not fire the veto. When the name matches but no verifier is
present, the record is not vetoed; it falls through to scoring as a high-risk
name imitation, where account age and permissions decide.

The package-id veto forces ``repackaged`` when an official package id ships under
a non-official publisher.
"""

from __future__ import annotations

from datetime import date

from brandguard.discovery.normalize import normalize
from brandguard.schema import AppRecord, BrandProfile, Label
from brandguard.triage.signals import Direction, SignalResult

# An account older than this is treated as an identity verifier: an attacker
# would have had to register and wait years, which does not fit the phishing
# economics in the threat model.
_ESTABLISHED_ACCOUNT_MAX_YEAR = 2020

# Unauthorized-build markers. A real app carries none of these in its NAME or
# PACKAGE id; a redistributed, modified build advertises them ("Spotify Premium
# Mod", "GB WhatsApp", com.app.cracked). Strong markers are decisive on their
# own; unlock phrases need the whole phrase because "premium"/"pro" alone are
# legitimate product words (Spotify Premium is a real product).
_STRONG_BUILD_MARKERS = (
    "mod", "modded", "cracked", "hacked", "hack", "patched", "cheat",
    "keygen", "nulled", "warez",
)
_UNLOCK_PHRASES = (
    "premium unlocked", "premium mod", "pro unlocked", "plus unlocked",
    "vip unlocked", "fully unlocked", "full unlocked", "premium free",
    "pro free", "unlocked all", "mega mod",
)


def _normset(values: list[str]) -> set[str]:
    return {normalize(v) for v in values}


def _domain_matches_official(website: str | None, profile: BrandProfile) -> bool:
    if not website:
        return False
    host = website.lower().split("//")[-1].split("/")[0].removeprefix("www.")
    return any(host == d.lower() or host.endswith("." + d.lower()) for d in profile.official_domains)


def _identity_verifier(record: AppRecord, profile: BrandProfile) -> str | None:
    """Return the name of a verifier that supports official identity, or None.

    Verifiers are chosen to be things an attacker cannot cheaply forge.
    """
    if record.publisher.verified is True:
        return "store-verified publisher"
    if _domain_matches_official(record.publisher.website, profile):
        return "publisher website on an official domain"
    created = record.publisher.account_created
    if created is not None and created <= date(_ESTABLISHED_ACCOUNT_MAX_YEAR, 1, 1):
        return f"publisher account predates {_ESTABLISHED_ACCOUNT_MAX_YEAR}"
    return None


def check_publisher_veto(record: AppRecord, profile: BrandProfile) -> SignalResult | None:
    """Official veto: publisher name matches AND an identity verifier is present."""
    if normalize(record.publisher.name) not in _normset(profile.official_publishers):
        return None
    verifier = _identity_verifier(record, profile)
    if verifier is None:
        return None  # name matches but identity unverified: do not veto
    return SignalResult(
        name="publisher_veto",
        direction=Direction.VETO,
        strength=1.0,
        text=(
            f"Publisher '{record.publisher.name}' matches the official list and is "
            f"corroborated by {verifier}."
        ),
        forced_label=Label.OFFICIAL,
    )


def check_package_veto(record: AppRecord, profile: BrandProfile) -> SignalResult | None:
    """Repackaged veto: an official package id under a non-official publisher."""
    if record.app_id not in set(profile.official_package_ids):
        return None
    # If the publisher is verifiably official, the publisher veto already handles
    # it as official; do not also flag repackaged.
    if check_publisher_veto(record, profile) is not None:
        return None
    # Even when the publisher veto did not fire for lack of an identity verifier,
    # a publisher whose name matches the official list is not a repackager: the
    # repackaged case is specifically an official package under a DIFFERENT
    # publisher. Matching the official name here means the identity is merely
    # unverified, not foreign, so this is not repackaging. (Found on live Ziraat
    # data, where an official app's publisher had no on-domain website.)
    #
    # An EMPTY publisher name is likewise not a foreign repackager: it means the
    # identity is simply unknown (e.g. a Google search hit that carries no
    # publisher field). Unknown identity is at most uncertain, never a takedown
    # on its own. (Found on live Serper data, where search results have no
    # publisher.)
    normalized_publisher = normalize(record.publisher.name)
    if not normalized_publisher or normalized_publisher in _normset(profile.official_publishers):
        return None
    return SignalResult(
        name="package_veto",
        direction=Direction.VETO,
        strength=1.0,
        text=(
            f"Package id '{record.app_id}' is an official package but publisher "
            f"'{record.publisher.name}' is not the official publisher."
        ),
        forced_label=Label.REPACKAGED,
    )


def _has_build_marker(text_norm: str) -> tuple[str, ...]:
    """Return the unauthorized-build markers present in normalized text.

    Strong markers match as whole words (so "mod" does not fire on "model");
    unlock phrases are multi-word and matched as substrings.
    """
    import re

    hits: list[str] = []
    for marker in _STRONG_BUILD_MARKERS:
        if re.search(rf"(?:^|\s){re.escape(marker)}(?:\s|$)", text_norm):
            hits.append(marker)
    hits += [p for p in _UNLOCK_PHRASES if p in text_norm]
    return tuple(hits)


def check_unauthorized_build_veto(record: AppRecord, profile: BrandProfile) -> SignalResult | None:
    """Repackaged veto: an app whose name/package advertises a modded or cracked
    build, shipped by a non-official publisher.

    A modded/cracked build is a repackaged app by definition: the real product,
    modified and redistributed by someone who is not the publisher. The guard
    that keeps legitimate mirrors safe is the publisher check: if the publisher
    matches the official list, this never fires, however a mirror labels the
    build. Markers are read from the NAME and PACKAGE id only, never the
    description (where "mod" can appear innocently).
    """
    # An official publisher's build is legitimate whatever a mirror calls it.
    if normalize(record.publisher.name) in _normset(profile.official_publishers):
        return None

    name_norm = normalize(record.name)
    pkg_norm = normalize(record.app_id.replace(".", " ").replace("_", " "))
    markers = _has_build_marker(f"{name_norm} {pkg_norm}")
    if not markers:
        return None

    return SignalResult(
        name="unauthorized_build",
        direction=Direction.VETO,
        strength=1.0,
        text=(
            f"App name or package advertises an unauthorized build "
            f"({', '.join(markers)}) from a non-official publisher; "
            "this is a repackaged, modified redistribution."
        ),
        forced_label=Label.REPACKAGED,
    )


def check_vetoes(record: AppRecord, profile: BrandProfile) -> SignalResult | None:
    """Run veto checks in priority order; return the first that fires."""
    return (
        check_publisher_veto(record, profile)
        or check_package_veto(record, profile)
        or check_unauthorized_build_veto(record, profile)
    )
