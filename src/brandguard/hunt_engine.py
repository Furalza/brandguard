"""Unified hunting engine.

One interface over every discovery source (live Google Play, Serper, website
domains, Certificate Transparency), each producing a timestamped, recorded run
that can be compared over time. This is the operational layer a real DRP
platform exposes: pick a brand and a source, get a saved, auditable result, and
track how a brand's exposure changes between runs.

Each source runner is a thin wrapper over a discovery module: it gathers
candidates, pushes app candidates through the triage cascade (T0, then T2 when
undecided) or domain candidates through the domain cascade (D0, D1), and returns
uniform rows. Recording is uniform too: one JSON per run under results/, one
summary row in results/run_log.csv, both keyed by an ISO UTC timestamp, the
brand and the source. The product API stores the same rows in its database.

python -m brandguard.hunt --brand "X" --official-domain Y --source serper --max-queries 8
"""

from __future__ import annotations

import csv
import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from brandguard.config import setting
from brandguard.product.category import category_of_row
from brandguard.schema import AppRecord, BrandProfile, Evidence, Label, Verdict

# A source name maps to a runner that produces recorded rows for a brand.
SOURCES = ("play", "serper", "website", "crtsh")

# Engine defaults per source. Exposed so the API and the CLI show one truth.
DEFAULTS: dict[str, dict[str, int]] = {
    "play": {"max_queries": 4, "hits": 5},
    "serper": {"max_queries": 6, "num": 10, "pages": 1},
    "website": {"max_queries": 4, "num": 10},
    "crtsh": {"cap": 200},
}

_TAKEDOWN = {"impersonation", "repackaged"}
_HIGH_DOMAIN = {"lookalike"}


@dataclass(frozen=True)
class RunResult:
    """The uniform, recordable result of one hunt run."""

    brand: str
    source: str
    scanned_at: str
    candidates: int
    detected: int         # confirmed threats: app takedowns, or live (real) lookalikes
    watch: int            # generated lookalike names to monitor, not yet confirmed
    rows: list[dict]      # analyst-facing records, source-specific but JSON-safe
    errors: list[str] = field(default_factory=list)    # per-query failures, not fatal
    warnings: list[str] = field(default_factory=list)  # health hints (K-056 alarm etc.)
    duration_ms: int = 0
    requests: int = 0      # network calls made, for the cost report
    # facts a source measured that other sources of the same scan may use
    # (Play's brand_word_shared_by feeds the APK-site run, K-075)
    measurements: dict = field(default_factory=dict)

    @property
    def flagged(self) -> int:
        """Back-compat alias: total flagged = detected + watch."""
        return self.detected + self.watch


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")


def _app_row(verdict: Verdict, decision_reason: str, record: AppRecord,
             affiliate_hint: str | None = None) -> dict:
    """The brief's analyst shape plus the fields a details view needs.

    ``score``, ``tiers_used`` and ``reason`` are the decision trail; ``category``
    is the operator vocabulary (product.category); ``facts`` are the listing
    fields the details view explains the decision with (publisher, website,
    installs). The brief's five keys come first and are unchanged, so every
    existing consumer keeps working.
    """
    from brandguard.triage.reader import clean_text

    row = verdict.to_analyst_json()
    evidence = list(verdict.evidence)
    if affiliate_hint:
        evidence.append(Evidence(signal="affiliate_hint", text=affiliate_hint, weight=0.0, tier=0))
    pub = record.publisher
    row.update({
        "name": record.name,
        "score": verdict.score,
        "tiers_used": list(verdict.tiers_used),
        "reason": decision_reason,
        "evidence_detail": [e.model_dump() for e in evidence],
        "affiliate_hint": bool(affiliate_hint),
        "facts": {
            "publisher": pub.name,
            "website": pub.website,
            "account_id": pub.account_id,
            "installs": record.downloads,
            "released": record.published.isoformat() if record.published else None,
            "updated": record.last_updated.isoformat() if record.last_updated else None,
            # K-078: enough of the listing to re-read it later (replay, analyst)
            "account_created": pub.account_created.isoformat() if pub.account_created else None,
            "other_app_count": pub.other_app_count,
            "verified": pub.verified,
            "permissions": list(record.permissions)[:40],
            "description_excerpt": clean_text(record.description, 600),
            "page_kind": record.raw.get("page_kind") if isinstance(record.raw, dict) else None,
            "bundle_id": record.raw.get("bundle_id") if isinstance(record.raw, dict) else None,
        },
    })
    row["category"] = category_of_row(row).value
    return row


def promote_same_account(records: list[AppRecord], decisions: list) -> list:
    """Second pass: a listing from a verified official account is official (K-062).

    The publisher veto verifies identity per listing, so the brand's small or
    regional apps fail it (below the install bar, no package id on file). But
    Play's ``developerId`` is the account itself: only its owner can publish
    under it. When a record shares the account of a listing the veto already
    verified, it is the brand's own app, whatever its size. Records without an
    account id (evaluation data, other stores) are untouched, so the offline
    metrics do not move.
    """
    from brandguard.triage.fusion import Decision

    verified: dict[str, str] = {}
    for r, d in zip(records, decisions, strict=True):
        acc = r.publisher.account_id
        if acc and d.reason == "veto" and d.verdict.label == Label.OFFICIAL:
            verified.setdefault(acc, r.name)
    if not verified:
        return decisions
    out = []
    for r, d in zip(records, decisions, strict=True):
        acc = r.publisher.account_id
        if d.verdict.label == Label.OFFICIAL or not acc or acc not in verified:
            out.append(d)
            continue
        anchor = verified[acc]
        evidence = [Evidence(
            signal="developer_account", weight=1.0, tier=0,
            text=(f"Published from the same Google Play developer account as the verified "
                  f"official app '{anchor}' (account ids cannot be shared)."),
        ), *d.verdict.evidence]
        verdict = d.verdict.model_copy(update={
            "label": Label.OFFICIAL, "confidence": 0.95, "evidence": evidence,
            "score": 1.0, "conflicts": [],
        })
        out.append(Decision(verdict=verdict, escalate=False, reason="same_developer_account"))
    return out


_AMBIGUITY_STOP = frozenset({
    "apk", "app", "apps", "android", "download", "descargar", "indir", "mod", "for", "free",
    "old", "eski", "version", "versions", "latest", "the", "a", "an", "de", "para", "pour",
    "fur", "per", "ios", "iphone", "pc", "windows", "mobile", "mobil", "online", "pro", "plus",
    "premium", "lite", "go", "hd", "2", "3", "v2", "new",
})
_AMBIGUOUS_MIN_PRODUCTS = 4


def _strong_identity_tokens(profile: BrandProfile) -> set[str]:
    """Identity words beyond the brand's own name: domain labels, publisher
    words, flagship-title words. Empty when the brand word is its own
    strongest identity (spotify.com for Spotify), which switches K-071 off."""
    from brandguard.registry import _GENERIC_TOKENS, _brand_keys, identity_tokens, slugify

    compact, distinctive = _brand_keys(profile.brand_name)
    own = {compact, *distinctive}
    strong = {t for t in identity_tokens(profile.brand_name, profile.official_domains,
                                         profile.known_official_apps) if t not in own}
    own_apps = [a for a in profile.known_official_apps
                if any(any(k in w for k in own) for w in slugify(a).split("_"))]
    # Publisher words always; app-title words only from titles that carry the
    # brand word ("Wise: International Transfers" yes, "Currency Converter" no).
    for text in [*profile.official_publishers, *own_apps]:
        for tok in slugify(text).split("_"):
            if len(tok) >= 4 and tok not in _GENERIC_TOKENS and tok not in own:
                strong.add(tok)
    labels = {slugify(d.split(".")[0]).replace("_", "") for d in profile.official_domains}
    shared = profile.brand_word_shared_by or 0
    if own & labels and shared < _AMBIGUOUS_MIN_PUBLISHERS:
        # The domain is the brand word itself (spotify.com) and Play showed no
        # other publishers leading with it: nothing is ambiguous. wise.com is
        # also its brand word, but Play lists Wise Vets, Wise Finwealth,
        # Wise&Rise...: the measurement wins over the domain heuristic.
        return set()
    return strong


_AMBIGUOUS_MIN_PUBLISHERS = 3


def play_name_ambiguity(records, profile: BrandProfile) -> int:
    """Distinct namesake publishers whose app name leads with the brand word.

    Measured on Play records, whose publisher names come from the store and
    not from the listing's own text. A publisher that carries the brand word
    itself ("Garanti Yatirim", "Vodafone Greece", "Wise Vets") is not counted:
    from the name alone a subsidiary and a namesake company look the same,
    and counting them softened real mods of a bank's own apps (found live).
    Companion apps ("Stats for Wise") do not lead with the word either.
    """
    from brandguard.discovery.normalize import normalize
    from brandguard.registry import _brand_keys, identity_tokens, names_identity
    from brandguard.triage.adjudicator import _names_brand

    compact, distinctive = _brand_keys(profile.brand_name)
    heads = {compact, *distinctive}
    tokens = identity_tokens(profile.brand_name, profile.official_domains)
    officials = {normalize(p) for p in profile.official_publishers}
    publishers: set[str] = set()
    for r in records:
        words = normalize(r.name).split()
        pub = normalize(r.publisher.name)
        if not words or not pub or pub in officials or names_identity(r.publisher.name, tokens):
            continue
        if not (words[0] in heads or (len(words) > 1 and (words[0] + words[1]) in heads)):
            continue
        # A companion app can lead with the word too ("Binance Ninja - P2P
        # Notifier"); its description talks about the brand. A namesake's
        # does not, once its own name is set aside (K-070). No description
        # means no evidence either way: not counted.
        if not r.description or _names_brand(r.description, profile.brand_name, r.name):
            continue
        publishers.add(pub)
    return len(publishers)


def brand_word_ambiguity(records, profile: BrandProfile) -> int:
    """How many distinct products in this batch start with the brand word.

    "Pegasus VPN", "Pegasus Browser", "Pegasus Keyboard", "Pegasus Travel" in
    one result set say the word is shared by unrelated products; "Spotify
    Premium", "Spotify Lite" do not (those are the brand's own tiers, and the
    rule is off for such brands anyway, see _strong_identity_tokens).
    """
    from brandguard.discovery.normalize import normalize
    from brandguard.registry import _brand_keys

    compact, distinctive = _brand_keys(profile.brand_name)
    heads = {compact, *distinctive}
    products: set[str] = set()
    for r in records:
        words = normalize(r.name).split()
        if len(words) < 2 or words[0] not in heads:
            continue
        nxt = next((w for w in words[1:] if w not in _AMBIGUITY_STOP and len(w) >= 3), None)
        if nxt:
            products.add(nxt)
    return len(products)


def soften_ambiguous_mods(records, decisions, profile: BrandProfile):
    """K-071: a mod named only by a shared brand word is a review item, not a takedown.

    Applies when the brand's strongest identity is not its bare name and the
    batch shows the word is shared by several unrelated products. A repackaged
    verdict that rests on the build veto and names none of the brand's
    identity words (publisher, flagship title, domain label) becomes
    uncertain, with the count on record. Verdicts anchored on an official
    package id are untouched.
    """
    from brandguard.discovery.normalize import normalize
    from brandguard.triage.fusion import Decision

    strong = _strong_identity_tokens(profile)
    if not strong:
        return decisions
    ambiguity = brand_word_ambiguity(records, profile)
    shared = profile.brand_word_shared_by or 0
    if ambiguity < _AMBIGUOUS_MIN_PRODUCTS and shared < _AMBIGUOUS_MIN_PUBLISHERS:
        return decisions
    official_ids = set(profile.official_package_ids)
    out = []
    for r, d in zip(records, decisions, strict=True):
        is_build_veto = (d.verdict.label == Label.REPACKAGED and d.reason == "veto"
                         and any(e.signal == "unauthorized_build" for e in d.verdict.evidence))
        if not is_build_veto or r.app_id in official_ids:
            out.append(d)
            continue
        haystack = normalize(f"{r.name} {r.app_id} {r.publisher.name}").replace(" ", "")
        if any(tok in haystack for tok in strong):
            out.append(d)
            continue
        where = (f"shared by {ambiguity} unrelated products in this result set"
                 if ambiguity >= _AMBIGUOUS_MIN_PRODUCTS
                 else f"shared by {shared} other publishers on Google Play")
        evidence = [*d.verdict.evidence, Evidence(
            signal="ambiguous_brand_word", weight=0.0, tier=0,
            text=(f"The brand word is {where} and this listing names none of the brand's "
                  f"identity words ({', '.join(sorted(strong)[:4])}); a person should confirm "
                  "it is the brand's app."),
        )]
        verdict = d.verdict.model_copy(update={
            "label": Label.UNCERTAIN, "confidence": 0.5, "evidence": evidence, "score": 0.5,
        })
        out.append(Decision(verdict=verdict, escalate=False, reason="ambiguous_brand_word"))
    return out


_MIRROR_HOSTS = ("apkpure.", "uptodown.", "apkmirror.", "apkcombo.", "aptoide.", "softonic.",
                 "malavida.", "cepde.", "indirsoft.", "tamindir.", "apkfab.", "apkmonk.",
                 "apkfiles.", "androidapksfree.", "apk4fun.", "apps.microsoft.com", "download.it")


def _mirror_host(record: AppRecord) -> str | None:
    """The mirror host a search hit came from, or None when it is not a mirror."""
    host = (record.app_id.lower().split("//")[-1].split("/")[0] if "://" in record.app_id
            else record.source.removeprefix("serper:").lower())
    return host if any(m in host for m in _MIRROR_HOSTS) else None


# Words a mirror page adds around an app title that say nothing about which
# app it is: download verbs in the languages the mirrors use, platform words,
# store names, build details. What is left after removing them and the
# brand's own words is the "residue"; a mirror copy of the brand's app has
# none ("Spotify APK for Android Download"), a namesake or a companion does
# ("Getir Parca APK", "Spotify Songs Downloader APK").
_MIRROR_NOISE = {
    "apk", "apks", "xapk", "app", "apps", "android", "ios", "iphone", "ipad", "pc", "windows", "mac",
    "tv", "download", "downloads", "downloader", "free", "latest", "old", "older", "version", "versions",
    "new", "install", "update", "updated", "file", "files", "bundle", "beta", "nodpi", "dpi", "arm64",
    "v8a", "v7a", "for", "the", "from", "by", "on", "and", "or", "to", "of", "in", "with", "en", "tr",
    "de", "fr", "it", "es", "pt", "com", "net", "org", "io",
    # Turkish
    "indir", "indirin", "indirme", "icin", "ucretsiz", "eski", "surum", "surumler", "surumleri",
    "son", "yukle", "yukleyin", "uygulama", "uygulamasi", "ve", "ile", "dan", "den",
    # es / fr / de / it / pt
    "descargar", "gratis", "gratuito", "para", "telecharger", "pour", "gratuit", "herunterladen",
    "fur", "kostenlos", "scaricare", "per", "baixe", "baixar", "versao", "antiga", "antigua",
    # stores
    "uptodown", "aptoide", "softonic", "apkpure", "apkmirror", "apkcombo", "apkfab", "apkmonk",
    "tamindir", "malavida", "cepde", "indirsoft", "apkdone", "store", "play", "google", "amazon",
    "fire", "tablet", "phone", "mobile",
    # what the app is for, as mirrors translate official titles ("Spotify:
    # Music and Podcasts" for a profile that knows "Spotify: Muzik ve Podcast'ler")
    "music", "musik", "muzik", "podcast", "podcasts", "video", "videos", "live", "chat", "shop",
    "market", "food", "groceries", "delivery", "minutes", "community", "global", "lite", "kids",
    "beyond", "more", "dahasi", "ve", "and",
}
_MIRROR_TOKEN = re.compile(r"[a-z]+")


def _mirror_residue(record: AppRecord, profile: BrandProfile) -> list[str]:
    """Title words that are neither the brand's own words nor mirror noise."""
    from brandguard.discovery.normalize import normalize

    own: set[str] = set()
    for text in [profile.brand_name, *profile.known_official_apps, *profile.official_publishers,
                 *[d.split(".")[0] for d in profile.official_domains]]:
        own.update(_MIRROR_TOKEN.findall(normalize(text)))
    words = _MIRROR_TOKEN.findall(normalize(record.name))
    return [w for w in words if len(w) > 1 and w not in own and w not in _MIRROR_NOISE]


def is_mirror_listing(record: AppRecord, profile: BrandProfile) -> bool:
    """A mirror-site listing of the brand's own app, unmodified by its title.

    Such a hit is neither an impersonation nor a namesake: it is the brand's
    app redistributed by a third party, and only a signature check could say
    whether it was touched. It therefore must not be settled benign by T2
    (found live on TikTok: 44 "TikTok Lite APK" mirror pages were read as
    namesakes and filed as noise) and need not be read at all.

    Three exclusions keep this to real copies: a build marker (a mod is a
    takedown, handled by the veto), a companion marker ("Spotify Songs
    Downloader" is a third-party tool), and a title residue (words that are
    neither the brand's nor mirror noise: "Getir Parca" is an auto-parts app
    that shares the verb). Titles with a residue go to the reader instead.
    """
    from brandguard.discovery.normalize import normalize
    from brandguard.registry import identity_tokens, names_identity
    from brandguard.triage.veto import _has_build_marker, companion_marker

    if _mirror_host(record) is None:
        return False
    name_norm = normalize(record.name)
    if _has_build_marker(name_norm):
        return False
    tokens = identity_tokens(profile.brand_name, profile.official_domains, profile.known_official_apps)
    if not names_identity(record.name, tokens):
        return False
    if companion_marker(name_norm, identity_tokens(profile.brand_name, profile.official_domains)):
        return False
    if _mirror_residue(record, profile):
        return False
    if (profile.brand_word_shared_by or 0) >= _AMBIGUOUS_MIN_PUBLISHERS:
        # "Wise APK for Android Download" on apkpure may be any of a dozen
        # Wise apps: with a shared brand word the bare word proves nothing,
        # so the title must carry one of the brand's own app titles or the
        # URL an official package id; otherwise the reader decides (K-081).
        ids = [i for i in profile.official_package_ids if i]
        return _title_names_official_app(record.name, profile) or any(i in record.app_id for i in ids)
    return True


def _title_names_official_app(name: str, profile: BrandProfile) -> bool:
    """The title carries one of the brand's app titles that is more than the bare word."""
    from brandguard.discovery.normalize import normalize

    name_norm = normalize(name)
    brand_norm = normalize(profile.brand_name)
    for app in profile.known_official_apps:
        full = normalize(app)
        head = normalize(app.split(" - ")[0].split(": ")[0].split(" | ")[0])
        for candidate in (full, head):
            if candidate and candidate != brand_norm and len(candidate) > len(brand_norm) and candidate in name_norm:
                return True
    return False


def mirror_decision(record: AppRecord, prior):
    """The uncertain, explained decision for a mirror listing (K-075/K-079)."""
    from brandguard.triage.fusion import Decision

    host = _mirror_host(record) or "a mirror site"
    text = (f"Listing of the brand's app on the mirror site {host}, with no sign of "
            "modification in its title. Whether the APK is the untouched original cannot "
            "be verified without a signature check; treat as an unauthorized copy to review.")
    evidence = [Evidence(signal="mirror_listing", weight=0.0, tier=0, text=text),
                *[e for e in prior.verdict.evidence if e.signal != "adjudicator"]]
    # Low confidence on purpose: within "suspicious" the genuinely undecided
    # rows sort above the pile of mirror copies.
    verdict = prior.verdict.model_copy(update={"label": Label.UNCERTAIN, "evidence": evidence, "confidence": 0.25})
    return Decision(verdict=verdict, escalate=False, reason="mirror_unverified")


def _mirror_by_reading(record: AppRecord, decision):
    """The reader recognised a copy of the brand's app on a site the mirror
    list does not know (fileion, techspot, bluestacks...): same reason and
    explanation as a listed mirror, so the analyst sees one class."""
    if decision.verdict.label != Label.UNCERTAIN or record.source.startswith(("google_play", "app_store")):
        return decision
    answers = next((e.text for e in decision.verdict.evidence if e.signal == "reader_answers"), "")
    if "subject=brand_app" not in answers:
        return decision
    host = record.app_id.lower().split("//")[-1].split("/")[0] if "://" in record.app_id else record.source.removeprefix("serper:")
    text = (f"The listing text describes the brand's own app, offered for download on {host}. Whether the "
            "file is the untouched original cannot be verified without a signature check; treat as an "
            "unauthorized copy to review.")
    evidence = [Evidence(signal="mirror_listing", weight=0.0, tier=2, text=text), *decision.verdict.evidence]
    verdict = decision.verdict.model_copy(update={"evidence": evidence, "confidence": 0.25})
    from brandguard.triage.fusion import Decision

    return Decision(verdict=verdict, escalate=False, reason="mirror_unverified")


def read_softened_mods(records, decisions, profile: BrandProfile, adjudicator):
    """K-081: a mod named only by a shared brand word is read before it is
    left for review. "Doctor Wise (MOD)" whose text is about a medical app is
    a namesake mod and noise; a mod whose text describes the brand's own app
    stays a review item (the veto was right in spirit, the word alone could
    not prove it)."""
    from brandguard.triage.tier2 import triage_t2

    out = []
    for r, d in zip(records, decisions, strict=True):
        if d.reason != "ambiguous_brand_word":
            out.append(d)
            continue
        read = triage_t2(r, profile, d, adjudicator)
        answers = next((e.text for e in read.verdict.evidence if e.signal == "reader_answers"), "")
        if read.verdict.label in (Label.UNRELATED, Label.THIRD_PARTY) and "names_brand=no" in answers:
            # a namesake's mod is that product's problem: noise for this brand
            verdict = read.verdict.model_copy(update={"label": Label.UNRELATED})
            out.append(d.__class__(verdict=verdict, escalate=False, reason=read.reason))
        elif "subject=brand_app" in answers or "subject=brand_service" in answers:
            # the text says it is the brand's app: back to the takedown the veto found
            evidence = [e for e in d.verdict.evidence if e.signal != "ambiguous_brand_word"]
            evidence += [e for e in read.verdict.evidence if e.signal.startswith("reader_")]
            verdict = d.verdict.model_copy(update={"label": Label.REPACKAGED, "confidence": 0.9, "evidence": evidence})
            from brandguard.triage.fusion import Decision

            out.append(Decision(verdict=verdict, escalate=False, reason="veto"))
        else:
            evidence = [*d.verdict.evidence, *[e for e in read.verdict.evidence if e.signal.startswith("reader_")]]
            out.append(d.__class__(verdict=d.verdict.model_copy(update={"evidence": evidence}), escalate=False,
                                   reason="ambiguous_brand_word"))
    return out


def explain_mirrors(records, decisions, profile: BrandProfile):
    """K-075: an unmodified-looking listing of the brand's app on a mirror site.

    The verdict stays uncertain (without a signature check nobody can say the
    APK is untouched, K-0xx L10), but the evidence says what it is: a mirror
    of the official app, not an impersonation "claiming to be official".
    """
    from brandguard.discovery.normalize import normalize
    from brandguard.registry import identity_tokens, names_identity
    from brandguard.triage.fusion import Decision
    from brandguard.triage.veto import _has_build_marker

    tokens = identity_tokens(profile.brand_name, profile.official_domains, profile.known_official_apps)
    out = []
    for r, d in zip(records, decisions, strict=True):
        if d.verdict.label != Label.UNCERTAIN or d.reason == "mirror_unverified":
            out.append(d)
            continue
        # A mirror hit is keyed by its URL, or by the package id the URL
        # exposed (apkpure); the source names the host in both cases.
        host = (r.app_id.lower().split("//")[-1].split("/")[0] if "://" in r.app_id
                else r.source.removeprefix("serper:").lower())
        if not any(m in host for m in _MIRROR_HOSTS):
            out.append(d)
            continue
        name_norm = normalize(r.name)
        if _has_build_marker(name_norm) or not names_identity(r.name, tokens):
            out.append(d)
            continue
        text = (f"Listing of the brand's app on the mirror site {host}, with no sign of "
                "modification in its title. Whether the APK is the untouched original cannot "
                "be verified without a signature check; treat as an unauthorized copy to review.")
        evidence = [Evidence(signal="mirror_listing", weight=0.0, tier=0, text=text),
                    *[e for e in d.verdict.evidence if e.signal != "adjudicator"]]
        verdict = d.verdict.model_copy(update={"evidence": evidence, "confidence": 0.25})
        out.append(Decision(verdict=verdict, escalate=False, reason="mirror_unverified"))
    return out


def _triage_records(records, profile: BrandProfile, adjudicator) -> tuple[list[dict], int]:
    """Run the app cascade over records; return rows and the takedown count."""
    from brandguard.product.affiliate import possible_affiliate
    from brandguard.triage.fusion import Decision, triage_t0
    from brandguard.triage.tier2 import triage_t2

    from brandguard.registry import host_under, normalize_domain

    decisions: list[Decision] = []
    for r in records:
        kind = r.raw.get("page_kind") if isinstance(r.raw, dict) else None
        if "://" in r.app_id and host_under(normalize_domain(r.app_id), profile.official_domains):
            # A page on the brand's own domain (its download guide, its blog)
            # is not a third-party listing and cannot be a threat to itself;
            # judging it produced "claims to be official" suspicions (found
            # live on binance.com).
            verdict = Verdict(
                app_id=r.app_id, source=r.source, label=Label.UNRELATED, confidence=0.9,
                evidence=[Evidence(signal="page_kind", weight=0.0, tier=0,
                                   text="Page on the brand's own official domain, not a store listing.")],
                score=0.0, tiers_used=[0],
            )
            decisions.append(Decision(verdict=verdict, escalate=False, reason="non_listing_official_site"))
            continue
        if kind and kind != "listing":
            # An article, forum thread, government page or SEO-spam page is not
            # an app listing; judging it as one produced "third_party" labels on
            # lottery pages. It is search noise with the reason on record.
            verdict = Verdict(
                app_id=r.app_id, source=r.source, label=Label.UNRELATED, confidence=0.9,
                evidence=[Evidence(signal="page_kind", weight=0.0, tier=0,
                                   text=f"Not an app listing: the URL is a {kind} page.")],
                score=0.0, tiers_used=[0],
            )
            decisions.append(Decision(verdict=verdict, escalate=False, reason=f"non_listing_{kind}"))
            continue
        d = triage_t0(r, profile)
        if d.reason != "veto" and is_mirror_listing(r, profile):
            # A copy of the brand's app on a mirror: the same answer whether
            # T0 found it benign ("Download Spotify 9.1 | Uptodown") or
            # undecided ("Spotify for Android - Uptodown"); never read.
            d = mirror_decision(r, d)
        elif d.escalate or d.verdict.label.value == "uncertain":
            d = triage_t2(r, profile, d, adjudicator)
            d = _mirror_by_reading(r, d)
        decisions.append(d)

    decisions = promote_same_account(list(records), decisions)
    decisions = soften_ambiguous_mods(list(records), decisions, profile)
    decisions = read_softened_mods(list(records), decisions, profile, adjudicator)
    decisions = explain_mirrors(list(records), decisions, profile)

    rows, detected = [], 0
    for r, d in zip(records, decisions, strict=True):
        hint = None
        if not d.reason.startswith("non_listing"):
            hint = possible_affiliate(r, profile, d.verdict.label, d.verdict.evidence)
        rows.append(_app_row(d.verdict, d.reason, r, hint))
        if d.verdict.label.value in _TAKEDOWN:
            detected += 1
    return rows, detected


def identity_terms(profile: BrandProfile, limit: int = 3) -> list[str]:
    """Search terms that name the brand more precisely than its bare name.

    A brand called by a dictionary word ("Pegasus") is found by its publisher
    ("Pegasus Airlines") and by its flagship app's title ("Pegasus - En Uygun
    Ucak Bileti" -> "Pegasus En Uygun Ucak Bileti"), which the bare name
    never surfaces among horses, phones and book publishers (K-071).
    """
    from brandguard.discovery.normalize import normalize

    brand_norm = normalize(profile.brand_name)
    seen = {brand_norm}
    out: list[str] = []
    for text in [*profile.official_publishers, *profile.known_official_apps]:
        head = text.split(" - ")[0].split(": ")[0].split(" | ")[0].strip()
        for candidate in (head, text.strip()):
            norm = normalize(candidate)
            if candidate and norm not in seen and len(norm) > len(brand_norm):
                seen.add(norm)
                out.append(candidate)
                break
        if len(out) >= limit:
            break
    return out


# ---- Source runners -------------------------------------------------------
# Each returns (rows, detected, watch, errors, warnings, requests).


@dataclass
class _Trace:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    requests: int = 0
    measurements: dict = field(default_factory=dict)


def _run_play(profile: BrandProfile, *, max_queries: int | None, hits: int, adjudicator,
              trace: _Trace) -> tuple[list[dict], int, int]:
    from brandguard.discovery.live_google_play import search_and_fetch
    from brandguard.discovery.query_expansion import select_queries

    from brandguard.discovery.live_google_play import _detail_to_record, cached_detail

    seen: set[str] = set()
    records = []
    # The brand's known apps are fetched directly, not hoped for in search:
    # they anchor the account rule (K-062) and must show even when search
    # ranks them out or the scraper drops the featured result (K-056).
    english_titles: list[str] = []
    if profile.official_package_ids:
        from google_play_scraper import app as play_app
        for pkg in profile.official_package_ids:
            trace.requests += 1
            try:
                detail = cached_detail(pkg, "tr", "tr", play_app)
                r = _detail_to_record(detail)
            except Exception as exc:  # noqa: BLE001
                trace.errors.append(f"official package {pkg} could not be fetched ({type(exc).__name__})")
                continue
            if r.app_id and r.app_id not in seen:
                seen.add(r.app_id)
                records.append(r)
            # Mirrors and the App Store show the English title ("Spotify:
            # Music and Podcasts", "IsCep: Banking & Finance") where the
            # profile knows the Turkish one; one cached request per official
            # app gives the mirror rule and the reader that title too (K-081).
            trace.requests += 1
            try:
                title = str((cached_detail(pkg, "en", "us", play_app) or {}).get("title") or "").strip()
            except Exception:  # noqa: BLE001 - a missing translation is not an error
                title = ""
            if title and title not in profile.known_official_apps and title not in english_titles:
                english_titles.append(title)
    if english_titles:
        profile = profile.model_copy(update={"known_official_apps": [*profile.known_official_apps, *english_titles]})
        trace.measurements["official_titles"] = english_titles
    anchors = set(seen)
    search_seen: set[str] = set()
    terms = [x.term for x in select_queries(profile.brand_name, max_queries)]
    terms += [t for t in identity_terms(profile) if t not in terms]
    for q in terms:
        trace.requests += 1 + hits
        try:
            # Anchors are skipped as already fetched; whether search itself
            # returned them is tracked separately for the K-056 alarm below.
            found = search_and_fetch(q, n_hits=hits, skip_ids=seen - anchors, seen_out=search_seen)
        except Exception as exc:  # noqa: BLE001
            trace.errors.append(f"play query {q!r} skipped ({type(exc).__name__})")
            continue
        for r in found:
            if r.app_id and r.app_id not in seen:
                seen.add(r.app_id)
                records.append(r)

    # K-056 live alarm: the brand's own apps should surface on Play. When none
    # of the known official package ids came back, either the scraper broke
    # again (its featured-result rule) or Play is throttling; either way the
    # result is incomplete and the operator must know.
    official = set(profile.official_package_ids)
    if official and search_seen and not (official & search_seen):
        trace.warnings.append(
            "Play returned none of the brand's official package ids; the scraper "
            "may be dropping the featured result again (K-056) or Play is throttling."
        )
    if not records and (max_queries is None or max_queries > 0):
        trace.warnings.append("Play returned no listings for any query.")

    # Store publishers are attacker-independent: count how many others lead
    # with the brand word, for the APK-site run of the same scan (K-075).
    shared = play_name_ambiguity(records, profile)
    profile = profile.model_copy(update={"brand_word_shared_by": shared})

    rows, detected = _triage_records(records, profile, adjudicator)
    # The reader's verdicts on Play listings are a second, better measure
    # (K-081): a publisher that carries the brand word itself was excluded
    # from the name-only count (subsidiary or namesake, the name cannot
    # tell), but a description that never refers to the brand settles it.
    by_reader = reader_namesakes(records, rows, profile)
    if by_reader > shared:
        shared = by_reader
    trace.measurements["brand_word_shared_by"] = shared
    if shared >= _AMBIGUOUS_MIN_PUBLISHERS:
        trace.warnings.append(
            f"The brand word leads the app names of {shared} other publishers on Play; "
            "modded listings and mirror pages that name none of the brand's other identity "
            "words are read or left for review instead of being decided on the word alone."
        )
    _note_reader_stats(adjudicator, trace)
    return rows, detected, 0


def reader_namesakes(records, rows, profile: BrandProfile) -> int:
    """Distinct non-official Play publishers whose brand-leading app the reader
    found to be about something else (subject namesake/unrelated, brand not
    named in the text)."""
    from brandguard.discovery.normalize import normalize
    from brandguard.registry import _brand_keys
    from brandguard.triage.veto import publisher_name_matches

    compact, distinctive = _brand_keys(profile.brand_name)
    heads = {compact, *distinctive}
    publishers: set[str] = set()
    for r, row in zip(records, rows, strict=True):
        words = normalize(r.name).split()
        if not words or not r.publisher.name or publisher_name_matches(r.publisher.name, profile):
            continue
        if not (words[0] in heads or (len(words) > 1 and (words[0] + words[1]) in heads)):
            continue
        answers = next((e["text"] for e in row.get("evidence_detail", []) if e.get("signal") == "reader_answers"), "")
        if ("subject=namesake" in answers or "subject=unrelated" in answers) and "names_brand=no" in answers:
            publishers.add(normalize(r.publisher.name))
    return len(publishers)


def _note_reader_stats(adjudicator, trace: _Trace) -> None:
    """One line in the run notes saying what the text reader did (K-078)."""
    stats = getattr(adjudicator, "stats", None)
    if not stats or not stats.get("read"):
        return
    trace.measurements["t2"] = dict(stats)
    parts = [f"{stats['read']} listing(s) read by the {getattr(adjudicator, 'provider', 'model')} reader"]
    if stats.get("cache_hits"):
        parts.append(f"{stats['cache_hits']} from cache")
    if stats.get("failures"):
        parts.append(f"{stats['failures']} call(s) failed")
    if stats.get("injections"):
        parts.append(f"{stats['injections']} listing(s) carried reader-directed instructions")
    trace.warnings.append("T2: " + ", ".join(parts) + ".")


def _app_store_client():
    """The iTunes lookup client; tests replace this."""
    from brandguard.discovery.app_store import ItunesLookupClient

    return ItunesLookupClient()


def _run_serper(profile: BrandProfile, *, num: int, max_queries: int | None, pages: int,
                adjudicator, trace: _Trace) -> tuple[list[dict], int, int]:
    from brandguard.discovery.serper_source import (
        build_apk_queries,
        get_serper_client,
        search_apks,
    )

    client = get_serper_client()
    context = None
    if (profile.brand_word_shared_by or 0) >= _AMBIGUOUS_MIN_PUBLISHERS:
        # Play showed the bare word belongs to several unrelated products:
        # anchor the general dorks with one of the brand's own words (K-076).
        context = next(iter(sorted(_strong_identity_tokens(profile), key=len)), None)
        if context:
            trace.warnings.append(
                f"Brand word is shared with other products on Play; APK-site queries were "
                f"anchored with '{context}' (the mod query stays bare)."
            )
    records = search_apks(profile.brand_name, client=client, num=num,
                          max_queries=max_queries, pages=pages, errors=trace.errors,
                          extra_terms=identity_terms(profile), context=context)
    if setting("BRANDGUARD_APP_STORE", "1") != "0":
        # App Store hits become real listings (seller, website, bundle id)
        # through the keyless iTunes lookup (K-079).
        from brandguard.discovery.app_store import enrich_app_store

        records, lookups = enrich_app_store(records, client=_app_store_client(), errors=trace.errors)
        trace.requests += lookups
    # max_queries None means "every query" (normal/deep depth); count what was
    # actually planned, never multiply None.
    planned = len(build_apk_queries(profile.brand_name)) + len(identity_terms(profile))
    if max_queries is not None:
        planned = min(planned, max_queries)
    trace.requests += planned * max(pages, 1)
    rows, detected = _triage_records(records, profile, adjudicator)
    _note_reader_stats(adjudicator, trace)
    return rows, detected, 0


def _domain_rows(enriched) -> tuple[list[dict], int, int]:
    """Return (rows, detected, watch).

    detected = lookalikes a source actually found (confirmed_live): real threats.
    watch    = generated lookalike names we produced, not yet confirmed to exist.
    """
    rows, detected, watch = [], 0, 0
    for e in enriched:
        f = e.finding
        row = {
            "domain": f.domain,
            "verdict": f.verdict.value,
            "similarity": f.similarity,
            "priority": e.priority,
            "confirmed_live": f.confirmed_live,
            "evidence": e.evidence,
            "domain_age_days": getattr(e, "domain_age_days", None),
            "cert_age_days": getattr(e, "cert_age_days", None),
        }
        row["category"] = category_of_row(row).value
        rows.append(row)
        if f.verdict.value in _HIGH_DOMAIN:
            if f.confirmed_live:
                detected += 1
            else:
                watch += 1
    return rows, detected, watch


def _run_website(profile: BrandProfile, *, num: int, max_queries: int,
                 trace: _Trace) -> tuple[list[dict], int, int]:
    from brandguard.discovery.serper_source import get_serper_client
    from brandguard.discovery.website_hunt import enrich_live_lookalikes, hunt_websites

    client = get_serper_client()
    findings = hunt_websites(profile.brand_name, profile.official_domains,
                             client=client, num=num, max_queries=max_queries,
                             known_affiliates=profile.known_affiliates)
    trace.requests += max_queries or 0
    return _domain_rows(enrich_live_lookalikes(findings))


def _run_crtsh(profile: BrandProfile, *, cap: int, trace: _Trace) -> tuple[list[dict], int, int]:
    from brandguard.discovery.crtsh_source import brand_token_of, search_crtsh
    from brandguard.discovery.website_hunt import (
        DomainFinding,
        DomainVerdict,
        classify_domain,
        enrich_live_lookalikes,
    )

    token = brand_token_of(profile.brand_name)
    trace.requests += 1
    ct = search_crtsh(token)
    if not ct:
        trace.warnings.append(
            f"crt.sh returned nothing for {token!r}; it may be throttling (retry later)."
        )
    findings = []
    for c in ct[:cap]:
        f = classify_domain(c.domain, profile.official_domains, profile.brand_name,
                            profile.known_affiliates)
        findings.append(DomainFinding(
            f.domain, f.verdict, f.similarity,
            [*f.evidence, f"Seen in CT logs, first cert {c.first_seen or 'unknown'}."],
            source_query="crt.sh", confirmed_live=True,
        ))
    interesting = [f for f in findings
                   if f.verdict in (DomainVerdict.LOOKALIKE, DomainVerdict.MENTIONS_BRAND)]
    return _domain_rows(enrich_live_lookalikes(interesting))


# ---- Engine ---------------------------------------------------------------


def run_source(profile: BrandProfile, source: str, **kw) -> RunResult:
    """Run one source for a brand and return a uniform RunResult (unrecorded).

    Keyword arguments override the per-source DEFAULTS; unknown ones are
    ignored so a caller can pass one tuning dict to every source.
    """
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}, expected one of {SOURCES}")

    opts = {**DEFAULTS[source], **{k: v for k, v in kw.items() if k in DEFAULTS[source]}}
    started = _now_iso()
    t0 = time.perf_counter()
    trace = _Trace()
    if source == "play":
        from brandguard.triage.adjudicator import get_adjudicator
        rows, detected, watch = _run_play(profile, adjudicator=get_adjudicator(),
                                          trace=trace, **opts)
    elif source == "serper":
        from brandguard.triage.adjudicator import get_adjudicator
        rows, detected, watch = _run_serper(profile, adjudicator=get_adjudicator(),
                                            trace=trace, **opts)
    elif source == "website":
        rows, detected, watch = _run_website(profile, trace=trace, **opts)
    else:  # crtsh
        rows, detected, watch = _run_crtsh(profile, trace=trace, **opts)

    return RunResult(
        brand=profile.brand_name, source=source, scanned_at=started,
        candidates=len(rows), detected=detected, watch=watch, rows=rows,
        errors=trace.errors, warnings=trace.warnings,
        duration_ms=int((time.perf_counter() - t0) * 1000), requests=trace.requests,
        measurements=dict(trace.measurements),
    )


def record_run(result: RunResult, results_dir: Path = Path("results")) -> Path:
    """Write a timestamped JSON for the run and append a summary row to the log.

    Returns the path of the per-run JSON. The raw JSON is git-ignored; the log
    is a non-sensitive summary safe to commit. Same convention as the watchlist.
    """
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = result.scanned_at.replace(":", "-").replace("+00-00", "Z")
    fname = f"{stamp}__{_slug(result.brand)}__{result.source}.json"
    out = results_dir / fname
    out.write_text(
        json.dumps(result.__dict__, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    log = results_dir / "run_log.csv"
    new = not log.exists()
    with log.open("a", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["scanned_at", "brand", "source", "candidates",
                        "detected", "watch", "result_file"])
        w.writerow([result.scanned_at, result.brand, result.source,
                    result.candidates, result.detected, result.watch, fname])
    return out
