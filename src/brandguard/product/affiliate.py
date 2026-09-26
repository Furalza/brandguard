"""Possible-affiliate hint: a benign listing that looks like the brand's own.

The engine's official label is strict on purpose: it needs an identity
verifier an impostor cannot forge (K-054/K-055). Real brands publish more
than their flagship app, though. A bank's card app with 40k installs, or its
German subsidiary's app under "Isbank AG", carries the brand identity but
fails the verifier and lands in ``third_party_legitimate``. Shown as
"related" next to a random ATM directory, the operator cannot tell them apart.

This module does not change the label. It attaches a hint to a benign
record whose publisher identity points at the brand, so the product can show
it as "possible affiliate: confirm and add to the profile". Nothing here is
attacker-proof (a publisher name is typed by the publisher), which is exactly
why it stays a hint on a benign record and never promotes anything to
official (K-063).
"""

from __future__ import annotations

from brandguard.discovery.normalize import normalize
from brandguard.registry import host_under, identity_tokens, names_identity
from brandguard.schema import AppRecord, BrandProfile, Label

# Labels a hint may decorate. Suspicious or uncertain records keep their
# category: a signal against them must be looked at, not softened by a hint.
_BENIGN = {Label.THIRD_PARTY, Label.UNRELATED}

_MIN_TOKEN = 4


def _host_of(website: str | None) -> str:
    if not website:
        return ""
    return website.lower().split("//")[-1].split("/")[0].removeprefix("www.")


def brand_tokens(profile: BrandProfile) -> set[str]:
    """Identity tokens of the profile: distinctive brand words, the compact
    name, official-domain labels and known app names (registry.identity_tokens)."""
    return identity_tokens(profile.brand_name, profile.official_domains,
                           profile.known_official_apps)


# Signals an attacker cannot cheaply produce; when one of these accuses an
# uncertain record, the affiliate hint stays out of it (K-074).
_INDEPENDENT_SUSPICION = {"account_age", "permission_drift", "solo_publisher", "review_consistency",
                          "unauthorized_build", "package_veto"}


def uncertain_only_by_words(evidence) -> bool:
    """True when an uncertain verdict rests on nothing but the name and the
    adjudicator's reading of the description, i.e. on attacker-writable text."""
    for e in evidence:
        if e.signal in _INDEPENDENT_SUSPICION and e.weight > 0.05:
            return False
    return True


def possible_affiliate(record: AppRecord, profile: BrandProfile, label: Label | str,
                       evidence=None) -> str | None:
    """Return an evidence sentence when a benign record looks like the brand's own.

    Checks, strongest first:
      1. publisher name equals an official publisher (identity unverified);
      2. developer website under an official domain (below the install bar);
      3. developer website under a vetted affiliate domain;
      4. publisher name carries a brand token ("Isbank AG");
      5. developer website's own label carries a brand token ("isbank.de").
    """
    label = Label(label) if not isinstance(label, Label) else label
    pub = record.publisher
    pub_norm = normalize(pub.name)
    if not pub_norm:
        return None
    # The reader read the listing and found it is about something else
    # ("Wise Vets", "Wise Finwealth"): a namesake, not a regional Wise (K-081).
    for e in evidence or []:
        signal = getattr(e, "signal", None) or (e.get("signal") if isinstance(e, dict) else None)
        text = getattr(e, "text", None) or (e.get("text") if isinstance(e, dict) else "")
        if signal == "reader_answers" and "names_brand=no" in (text or ""):
            return None
    # "Notify for Spotify" by someone whose site is notifyspotify.app is a
    # companion tool, not a regional Spotify: a companion-shaped name never
    # reads as an affiliate (found live, K-080).
    from brandguard.registry import identity_tokens
    from brandguard.triage.veto import companion_marker

    if companion_marker(normalize(record.name), identity_tokens(profile.brand_name, profile.official_domains)):
        return None
    officials = {normalize(p) for p in profile.official_publishers}
    if label == Label.UNCERTAIN:
        # An uncertain verdict whose only suspicion is words (name shape, a
        # description "claiming official") from a publisher that names the
        # brand itself is far more often a subsidiary than an impostor:
        # "BTCTURK YATIRIM" for BtcTurk, "Turkish Airlines" before the profile
        # knew it. It stays a review item, in the affiliate bucket (K-074).
        if evidence is None or not uncertain_only_by_words(evidence):
            return None
        toks = brand_tokens(profile)
        if pub_norm not in officials and not names_identity(pub.name, toks):
            return None
    elif label not in _BENIGN:
        return None
    if pub_norm in officials:
        return (f"Publisher '{pub.name}' matches the official publisher name, but the "
                "listing carries no identity verifier (install volume below the bar or "
                "package id not on the official list).")
    host = _host_of(pub.website)
    if host and host_under(host, profile.official_domains):
        return (f"Developer website {host} is under an official domain, but the listing "
                "is not established enough to verify the claim.")
    if host and profile.known_affiliates and host_under(host, profile.known_affiliates):
        return f"Developer website {host} is under a vetted affiliate domain."
    if (profile.brand_word_shared_by or 0) >= 3:
        # "ConnectWise", "Workwise GmbH" on a Wise scan: when Play showed the
        # word belongs to many, a name that merely carries it says nothing.
        return None
    toks = brand_tokens(profile)
    hit = names_identity(pub.name, toks)
    if hit:
        return (f"Publisher name '{pub.name}' carries the brand token '{hit}'; "
                "likely a regional or subsidiary publisher (unverified).")
    if host:
        hit = names_identity(host.split(".")[0], toks)
        if hit:
            return (f"Developer website {host} carries the brand token '{hit}' but is not "
                    "an official domain; likely a regional site (unverified).")
    return None
