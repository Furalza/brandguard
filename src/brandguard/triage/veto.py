"""Veto signals.

These are the highest-trust signals in the threat model, but trust is placed in
publisher *identity*, not the publisher *name*. A name is attacker-controlled: an
impersonator can set it to the flattened official name ("Ornek Bank A.S" for
"Örnek Bank A.Ş.") and, on a normalized match alone, would be waved through as
official. That is a real hole, so the veto uses defense in depth.

An official veto requires two independent conditions:

1. The publisher name matches the official list (normalized, so a store's
   Turkish flattening still matches).
2. At least one verifier the attacker cannot cheaply forge is present: a store
   ``verified`` flag, an official package id on Google Play (package ids are
   unique there), an account age consistent with an established brand, or a
   website under an official domain backed by organic reach (see K-055: the
   website field is self-declared, so on its own it is only a claim).

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

# A claimed developer website counts only on a listing with this many installs
# (organic reach an impersonator cannot produce). An official package id counts
# on its own on stores that guarantee package ids are unique.
_ESTABLISHED_DOWNLOADS = 100_000
# Stores where one app id belongs to one developer account: Google Play
# (package id) and the App Store (bundle id, via the iTunes lookup, K-079).
_UNIQUE_PACKAGE_ID_SOURCES = ("google_play", "app_store")

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
    """Normalized names, each also without its legal suffix (K-080).

    The App Store shows "Spotify" where Play shows "Spotify AB"; Play shows
    "TikTok Pte. Ltd." where the profile may carry "TikTok". The legal tail
    is not identity, so both forms of every official name are accepted.
    """
    from brandguard.registry import clean_brand_name

    out: set[str] = set()
    for v in values:
        out.add(normalize(v))
        out.add(normalize(clean_brand_name(v)))
    out.discard("")
    return out


def publisher_name_matches(name: str, profile: BrandProfile) -> bool:
    """Publisher name on the official list, with or without a legal suffix."""
    from brandguard.registry import clean_brand_name

    if not name:
        return False
    officials = _normset(profile.official_publishers)
    return normalize(name) in officials or normalize(clean_brand_name(name)) in officials


def _domain_matches_official(website: str | None, profile: BrandProfile) -> bool:
    if not website:
        return False
    host = website.lower().split("//")[-1].split("/")[0].removeprefix("www.")
    return any(host == d.lower() or host.endswith("." + d.lower()) for d in profile.official_domains)


def _official_package_on_unique_store(record: AppRecord, profile: BrandProfile) -> bool:
    """An official package id on a store that enforces unique package ids is the listing.

    Nobody but the owner can publish under a package id on Google Play, so a
    Play listing whose id is on the official list is the brand's own app,
    whatever website it declares (Bankkart declares its own card-brand site).
    On other stores any id can be carried, which is what repackaging is.
    """
    if not record.source.startswith(_UNIQUE_PACKAGE_ID_SOURCES):
        return False
    ids = set(profile.official_package_ids)
    if record.app_id in ids:
        return True
    # An App Store listing is keyed by its URL; its bundle id (often the same
    # string as the Android package id) rides in raw.
    bundle = record.raw.get("bundle_id") if isinstance(record.raw, dict) else None
    return bool(bundle) and bundle in ids


def _website_verifier(record: AppRecord, profile: BrandProfile) -> str | None:
    """Accept a website on an official domain only when the listing backs the claim.

    A store's developer website is typed in by the developer, so on its own it
    is a claim an impersonator can copy together with the official name (K-055).
    It identifies the publisher when the listing also shows what an
    impersonator cannot produce: organic install volume. (An official package id
    on Play is checked separately and needs no website.) A source that reports
    no install figure keeps the earlier rule, since there is nothing to check
    the claim against; live Play always reports one.
    """
    if not _domain_matches_official(record.publisher.website, profile):
        return None
    base = "publisher website on an official domain"
    if record.downloads is None:
        return base
    if record.downloads >= _ESTABLISHED_DOWNLOADS:
        return f"{base}, with {record.downloads:,}+ installs"
    return None


def _identity_verifier(record: AppRecord, profile: BrandProfile) -> str | None:
    """Return the name of a verifier that supports official identity, or None.

    Verifiers are chosen to be things an attacker cannot cheaply forge.
    """
    if record.publisher.verified is True:
        return "store-verified publisher"
    if _official_package_on_unique_store(record, profile):
        return f"official package id on {record.source} (package ids are unique there)"
    website = _website_verifier(record, profile)
    if website is not None:
        return website
    created = record.publisher.account_created
    if created is not None and created <= date(_ESTABLISHED_ACCOUNT_MAX_YEAR, 1, 1):
        return f"publisher account predates {_ESTABLISHED_ACCOUNT_MAX_YEAR}"
    return None


def check_publisher_veto(record: AppRecord, profile: BrandProfile) -> SignalResult | None:
    """Official veto: publisher name matches AND an identity verifier is present.

    On a store that enforces unique package ids, an official package id is the
    identity on its own (K-077): the profile may not know the publisher's exact
    store name yet (an operator typed the Play link and the domain; the CSV
    carries the legal name while Play shows a trading name), and a name the
    profile does not know must never turn the brand's own listing into a
    "repackaged" takedown. The text says the name was not on the list so the
    analyst can add it.
    """
    name_match = publisher_name_matches(record.publisher.name, profile)
    if _official_package_on_unique_store(record, profile):
        note = "" if name_match else (
            f" Publisher name '{record.publisher.name}' is not on the profile's list yet;"
            " add it to the profile."
        )
        return SignalResult(
            name="publisher_veto",
            direction=Direction.VETO,
            strength=1.0,
            text=(
                f"Package id '{record.app_id}' is an official package id on {record.source} "
                f"(package ids are unique there), so this listing is the brand's own.{note}"
            ),
            forced_label=Label.OFFICIAL,
        )
    if not name_match:
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
    if not normalized_publisher or publisher_name_matches(record.publisher.name, profile):
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


def _relates_to_brand(record: AppRecord, profile: BrandProfile) -> bool:
    """True when the listing names the brand (or one of its apps or domains)
    in its name, package, URL or publisher, or carries an official package id."""
    from brandguard.registry import identity_tokens, mentions_brand, names_identity

    if record.app_id in set(profile.official_package_ids):
        return True
    tokens = identity_tokens(profile.brand_name, profile.official_domains, profile.known_official_apps)
    candidates = [record.name, record.app_id]
    if record.publisher.name:
        candidates.append(record.publisher.name)
    return any(mentions_brand(text, profile.brand_name) or names_identity(text, tokens)
               for text in candidates if text)


# Words that mark a third-party companion app: a downloader, a stats widget,
# a tips guide or a ringtone pack that names the brand as its subject. A
# modded build of such an app is that app's problem, not the brand's (K-068).
_COMPANION_WORDS = (
    "downloader", "download video", "video download", "save video", "saver", "stats",
    "statistics", "tips", "guide", "tutorial", "walkthrough", "wallpaper", "widget",
    "template", "templates", "followers", "likes", "ringtone", "sounds", "fonts",
    "captions", "hashtag", "reward", "rewards", "cheat", "tricks", "trik", "dj ",
    "katalog", "catalog", "catalogue", "brosur", "aktuel",
)
# The brand as the object of a preposition ("for Instagram", "para Spotify").
_COMPANION_PREPOSITIONS = ("for", "on", "from", "with", "para", "pour", "fur", "per", "untuk", "icin")


def companion_marker(name_norm: str, brand_tokens: set[str]) -> str | None:
    """Return the phrase that marks a companion app in a normalized name, or None.

    Either a preposition immediately before a brand token ("... for instagram")
    or one of the companion words anywhere in the name. The name must already
    be known to name the brand; this only says in what role.
    """
    words = name_norm.split()

    def is_brand_word(word: str) -> bool:
        return len(word) >= 4 and any(word == t or word.startswith(t) or t.startswith(word)
                                      for t in brand_tokens if len(t) >= 4)

    for i in range(1, len(words)):
        # the brand within three words of the preposition: "for instagram",
        # "for the pegasus", "for asus pegasus 5000" (a phone model, found live)
        if words[i - 1] in _COMPANION_PREPOSITIONS:
            window = words[i:i + 3]
            if any(is_brand_word(w) for w in window):
                return " ".join([words[i - 1], *window])
        # "download tiktok video", "save instagram videos": a downloader named
        # by its verb rather than by a "downloader" noun
        if (i + 1 < len(words) and words[i - 1] in ("download", "save", "downloader")
                and is_brand_word(words[i]) and words[i + 1] in ("video", "videos", "photo", "photos")):
            return " ".join(words[i - 1:i + 2])
    for w in _COMPANION_WORDS:
        if (w.strip() in words) or (" " in w and w in name_norm) or (w.endswith(" ") and name_norm.startswith(w)):
            return w.strip()
    return None


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

    # Some search hits are not app listings at all but articles, how-to guides,
    # forum threads or government pages that happen to contain "mod apk" in their
    # title or URL ("how-to-download-minecraft-mod", a gov.in download page). An
    # article is not a repackaged build, so if the app_id (a URL when no package
    # was extracted) points at one of these, do not treat it as an app here.
    app_id_low = record.app_id.lower()
    _NON_APP_MARKERS = (
        "/howto", "how-to", "/blog", "/news", "/article", "/watch",
        "wikipedia.", "reddit.", "youtube.", "medium.", ".gov.", "gov.in",
    )
    if "://" in app_id_low and any(m in app_id_low for m in _NON_APP_MARKERS):
        return None

    name_norm = normalize(record.name)
    # app_id is a real package id only when it is not a URL. A search hit whose
    # package could not be extracted carries the raw link as app_id, and a link
    # path (…/howto/how-to-download-spotify-mod-apk) is an article title, not a
    # build name; a marker there is not evidence of a modded build. So scan the
    # package id only when it looks like a dotted package, never a URL.
    is_url = "://" in record.app_id or "/" in record.app_id
    pkg_norm = "" if is_url else normalize(record.app_id.replace(".", " ").replace("_", " "))
    markers = _has_build_marker(f"{name_norm} {pkg_norm}".strip())
    if not markers:
        return None

    # A modded build of SOME app is only this brand's problem when it is a
    # build of this brand's app: the name, the package or the listing URL must
    # name the brand, or the package must be an official one. Without that
    # relation the hit is a store's index page or another product's mod
    # ("Amazon Music MOD" on a Spotify scan, found live) and is left to the
    # scored signals, which read it as unrelated.
    if not _relates_to_brand(record, profile):
        return None

    # "Video Downloader for Instagram (MOD)" is a modded third-party companion
    # app, not a modified Instagram: no takedown for the brand. The scored
    # layer records why (companion_build_signal) and reads it as related.
    from brandguard.registry import identity_tokens

    # Brand and domain tokens only: an app name like "Spotify for Artists"
    # must not make "artists" a brand word.
    tokens = identity_tokens(profile.brand_name, profile.official_domains)
    if record.app_id not in set(profile.official_package_ids) and companion_marker(name_norm, tokens):
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
