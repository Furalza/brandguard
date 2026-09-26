"""Scan lifecycle: resolve the input, create the rows, run each source, persist.

A scan is one operator request. It fans out into one job per requested source;
each job runs independently under a per-source concurrency limit, records its
own outcome on its ``scan_sources`` row, and the last one to finish closes the
scan as ``done`` (every source succeeded), ``partial`` (some failed) or
``failed`` (all failed). A source failing never hides the others' results:
that is the K-047 rule carried into the product.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from brandguard.api import brands as brand_store
from brandguard.api.db import session_scope
from brandguard.api.models import Brand, Finding, Review, Scan, ScanSource
from brandguard.hunt_engine import DEFAULTS, SOURCES, RunResult, run_source
from brandguard.product.category import ACTIONABLE, Category, category_of_row
from brandguard.product.resolve import (
    _PLATFORM_DOMAINS,
    Resolution,
    detect_input,
    resolve_from_domain,
    resolve_from_name,
    resolve_from_package,
)
from brandguard.registry import host_under, slugify

log = logging.getLogger("brandguard.api.scan")

# Depth presets: how much each source may spend. "normal" is the engine default
# with every APK dork enabled; "deep" is what an analyst runs on a brand that
# matters this week. The numbers are the cost dials of each runner.
DEPTH: dict[str, dict[str, dict[str, int | None]]] = {
    "quick": {
        "play": {"max_queries": 2, "hits": 5},
        "serper": {"max_queries": 3, "num": 10, "pages": 1},
        "website": {"max_queries": 2, "num": 10},
        "crtsh": {"cap": 100},
    },
    "normal": {
        "play": {"max_queries": 6, "hits": 5},
        "serper": {"max_queries": None, "num": 10, "pages": 1},
        "website": {"max_queries": 6, "num": 10},
        "crtsh": {"cap": 200},
    },
    "deep": {
        "play": {"max_queries": 14, "hits": 8},
        "serper": {"max_queries": None, "num": 10, "pages": 2},
        "website": {"max_queries": 15, "num": 10},
        "crtsh": {"cap": 500},
    },
}
DEFAULT_SOURCES = ("play", "serper")

_finalize_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(tz=UTC)


# ---- Resolution -------------------------------------------------------------


def _online_clients():
    """Real Play and Serper clients when available, else None (offline mode)."""
    play = web = None
    try:
        from brandguard.registry import GooglePlayClient

        play = GooglePlayClient()
    except (SystemExit, ImportError):
        play = None
    try:
        from brandguard.registry import SerperWebClient

        web = SerperWebClient()
    except (RuntimeError, ImportError):
        web = None
    return play, web


def _page_title(host: str, timeout: float = 6.0) -> str | None:
    """Fetch the <title> of the operator's own domain (only the first 64 KB).

    Used as the last fallback for the brand name when Play and Google give
    nothing. The domain was typed by the operator, so this is their site, not
    a suspected phishing page.
    """
    try:
        import re

        import requests

        response = requests.get(f"https://{host}", timeout=timeout, stream=True,
                                headers={"User-Agent": "brandguard/2.0"})
        head = next(response.iter_content(chunk_size=65536), b"")
        response.close()
        match = re.search(rb"<title[^>]*>(.*?)</title>", head, re.IGNORECASE | re.DOTALL)
        if not match:
            return None
        title = match.group(1).decode(response.encoding or "utf-8", errors="replace")
        return " ".join(title.split()) or None
    except Exception:  # noqa: BLE001 - a missing title is not an error
        return None


def resolve_input(session: Session, text: str, *, clients: Callable | None = None,
                  page_title: Callable[[str], str | None] = _page_title,
                  ) -> tuple[Brand, str, str, Resolution | None]:
    """Find or build the brand for an input.

    Returns (brand row, input_type, how, resolution-or-None). A known brand is
    reused without any network call; an unknown one is resolved online and
    stored with ``resolved_from="auto"`` and its audit trail.
    """
    detected = detect_input(text)
    if detected.kind == "domain" and host_under(detected.value, _PLATFORM_DOMAINS):
        # Refused before the brand lookup: a stale "Google LLC" row created by
        # an earlier version must not be reused for play.google.com (K-069).
        raise ValueError(f"{detected.value} is a store or platform, not a brand's own domain; "
                         "enter the brand's domain, its name, or its app's store page")
    existing: Brand | None = None
    if detected.kind == "brand":
        existing = brand_store.find_brand(session, detected.value)
    elif detected.kind == "domain":
        existing = brand_store.find_brand_by_domain(session, detected.value)
    elif detected.kind in ("package", "url") and (detected.package_id or detected.value):
        pkg = detected.package_id or detected.value
        existing = brand_store.find_brand_by_package(session, pkg)
    # An automatic profile that never got an official domain is not worth
    # keeping as-is: it cannot verify anything, and the resolver improves
    # (K-066 made TikTok resolvable). Such a row is resolved again on the
    # next scan and upgraded in place when the retry finds a domain; a row
    # an operator edited, or one that has a domain, is reused as-is.
    stale = (existing is not None and existing.resolved_from == "auto"
             and not existing.official_domains)
    if existing is not None and not stale:
        return existing, detected.kind, "existing", None

    play, web = (clients or _online_clients)()  # looked up at call time (tests patch it)
    if detected.kind == "brand":
        res = resolve_from_name(detected.value, play=play, web=web)
    elif detected.kind == "domain":
        res = resolve_from_domain(detected.value, play=play, web=web,
                                  page_title=page_title(detected.value))
    elif detected.package_id:
        res = resolve_from_package(detected.package_id, play=play, web=web)
    else:
        res = resolve_from_domain(detected.value, play=play, web=web)

    if stale and existing is not None:
        if not res.profile.official_domains:
            return existing, detected.kind, "existing", None  # still nothing; keep the row
        existing.official_domains = list(res.profile.official_domains)
        for field in ("official_publishers", "official_package_ids", "known_official_apps"):
            merged = list(getattr(existing, field) or [])
            for value in getattr(res.profile, field):
                if value not in merged:
                    merged.append(value)
            setattr(existing, field, merged)
        if res.profile.sector and res.profile.sector != "unknown":
            existing.sector = res.profile.sector
        existing.resolution = {"how": res.how, "evidence": res.evidence, "input": text,
                               "re_resolved": True}
        existing.review_notes = list(res.review)
        existing.needs_review = bool(res.review)
        return existing, detected.kind, "re-resolved:" + res.how, res

    # The resolved brand may already exist under its own name (typed a domain
    # of a known brand whose domain list was empty, say): merge into it.
    known = brand_store.find_brand(session, res.profile.brand_name)
    if known is not None:
        if not known.official_domains and res.profile.official_domains:
            known.official_domains = list(res.profile.official_domains)
        for field in ("official_publishers", "official_package_ids", "known_official_apps"):
            merged = list(getattr(known, field) or [])
            for value in getattr(res.profile, field):
                if value not in merged:
                    merged.append(value)
            setattr(known, field, merged)
        known.review_notes = list(known.review_notes or []) + res.review
        known.needs_review = bool(known.review_notes)
        return known, detected.kind, res.how, res

    brand = brand_store.from_profile(
        res.profile, brand_id=res.brand_id, resolved_from="auto",
        resolution={"how": res.how, "evidence": res.evidence, "input": text},
        review_notes=res.review,
    )
    session.add(brand)
    session.flush()
    return brand, detected.kind, res.how, res


def _merge_profile_into(brand: Brand, profile, *, add_domains: bool) -> None:
    if add_domains:
        merged_domains = list(brand.official_domains or [])
        for d in profile.official_domains:
            if d not in merged_domains:
                merged_domains.append(d)
        brand.official_domains = merged_domains
    for field in ("official_publishers", "official_package_ids", "known_official_apps"):
        merged = list(getattr(brand, field) or [])
        for value in getattr(profile, field):
            if value not in merged:
                merged.append(value)
        setattr(brand, field, merged)


def resolve_structured(session: Session, *, name: str | None, domain: str | None,
                       store: str | None, clients: Callable | None = None,
                       page_title: Callable[[str], str | None] = _page_title,
                       ) -> tuple[Brand, str, str, Resolution | None]:
    """Find or build the brand from up to three operator-typed facts.

    ``domain`` is the trust anchor when given (K-060); ``store`` (a Play link
    or package id) is the operator asserting "this is our app", so its package
    id joins the official list and its publisher the official publishers;
    ``name`` is what the brand is called. Any one is enough; all three make
    the profile the operator meant with no guessing. Facts typed for a brand
    that already exists are merged into it (a typed domain or package is
    never dropped), and the row becomes operator-edited.
    """
    name = clean_name(name)
    host = None
    if domain:
        d = detect_input(domain)
        if d.kind != "domain":
            raise ValueError(f"{domain!r} is not a domain")
        host = d.value
        if host_under(host, _PLATFORM_DOMAINS):
            raise ValueError(f"{host} is a store or platform, not a brand's own domain")
    package = None
    play, web = (clients or _online_clients)()
    if store:
        d = detect_input(store)
        if d.kind == "package":
            package = d.value
        elif d.kind == "url" and d.package_id:
            package = d.package_id
        elif d.kind == "domain" and _store_facts(store.strip().lower(), play):
            # "trendyol.com" is Trendyol's package id as well as its domain;
            # Play says which (K-081). Without Play the domain reading stands.
            package = store.strip().lower()
        else:
            hint = (" If it is the app's package id, paste the full Google Play link instead."
                    if d.kind == "domain" else "")
            raise ValueError(f"{store!r} is neither a Google Play link nor a package id.{hint}")
    if not (name or host or package):
        raise ValueError("enter a brand name, a domain or a store link")

    existing = None
    if host:
        existing = brand_store.find_brand_by_domain(session, host)
    if existing is None and package:
        existing = brand_store.find_brand_by_package(session, package)
    if existing is None and name:
        existing = brand_store.find_brand(session, name)

    store_facts = _store_facts(package, play) if package else None

    if existing is not None and (existing.official_domains or existing.resolved_from != "auto"):
        changed = False
        if host and host not in (existing.official_domains or []):
            existing.official_domains = [*(existing.official_domains or []), host]
            changed = True
        if package and package not in (existing.official_package_ids or []):
            existing.official_package_ids = [*(existing.official_package_ids or []), package]
            changed = True
        if store_facts:
            for field, value in store_facts.items():
                if field.startswith("_"):
                    continue
                if value and value not in (getattr(existing, field) or []):
                    setattr(existing, field, [*(getattr(existing, field) or []), value])
                    changed = True
        if changed:
            existing.resolved_from = "manual"
        return existing, "structured", "existing+merged" if changed else "existing", None

    # Resolve from the strongest fact.
    if host:
        res = resolve_from_domain(host, play=play, web=web, page_title=page_title(host))
    elif package:
        res = resolve_from_package(package, play=play, web=web)
    else:
        res = resolve_from_name(name or "", play=play, web=web)
    profile = res.profile
    how = res.how
    if name and normalize_text(name) != normalize_text(profile.brand_name):
        # The operator's name for the brand wins over a guessed or legal one.
        profile = profile.model_copy(update={"brand_name": name})
        res.evidence.append(f"Brand name as typed by the operator: {name!r}")
        # The operator just confirmed the name, so the "guessed from the
        # domain label" note no longer applies.
        res.review = [n for n in res.review if not n.startswith("Brand name guessed")]
        how += "+name"
    if package:
        ids = list(profile.official_package_ids)
        if package not in ids:
            ids.append(package)
            res.evidence.append(f"Official package id as typed by the operator: {package}")
            res.review = [n for n in res.review if package not in n]
        pubs, apps = list(profile.official_publishers), list(profile.known_official_apps)
        if store_facts:
            if store_facts["official_publishers"] and store_facts["official_publishers"] not in pubs:
                pubs.append(store_facts["official_publishers"])
            if store_facts["known_official_apps"] and store_facts["known_official_apps"] not in apps:
                apps.append(store_facts["known_official_apps"])
        profile = profile.model_copy(update={"official_package_ids": ids, "official_publishers": pubs,
                                             "known_official_apps": apps})
        how += "+store"
    res = Resolution(profile=profile, how=how, evidence=res.evidence, review=res.review,
                     brand_id=slugify(profile.brand_name) or res.brand_id)
    parts = " · ".join(p for p in (name, host, package) if p)

    if existing is not None:  # stale automatic row: upgrade in place
        existing.brand_name = profile.brand_name
        _merge_profile_into(existing, profile, add_domains=True)
        existing.resolution = {"how": how, "evidence": res.evidence, "input": parts, "re_resolved": True}
        existing.review_notes = list(res.review)
        existing.needs_review = bool(res.review)
        existing.resolved_from = "manual" if (host or package) else existing.resolved_from
        return existing, "structured", "re-resolved:" + how, res

    known = brand_store.find_brand(session, profile.brand_name)
    if known is not None:
        _merge_profile_into(known, profile, add_domains=True)
        known.review_notes = list(known.review_notes or []) + res.review
        known.needs_review = bool(known.review_notes)
        if host or package:
            known.resolved_from = "manual"
        return known, "structured", how, res

    brand = brand_store.from_profile(
        profile, brand_id=res.brand_id,
        resolved_from="manual" if (host or package) else "auto",
        resolution={"how": how, "evidence": res.evidence, "input": parts},
        review_notes=res.review,
    )
    session.add(brand)
    session.flush()
    return brand, "structured", how, res


def _store_facts(package: str, play) -> dict | None:
    """Publisher and title of a package the operator vouched for, from Play."""
    if play is None:
        return None
    try:
        detail = play.details(package) or {}
    except Exception:  # noqa: BLE001 - the package id alone is still recorded
        return None
    from brandguard.registry import clean_brand_name

    developer = str(detail.get("developer") or "").strip()
    title = str(detail.get("title") or "").strip()
    return {"official_publishers": developer, "known_official_apps": title,
            "_brand_hint": clean_brand_name(developer) if developer else ""}


def clean_name(name: str | None) -> str | None:
    text = (name or "").strip()
    return text or None


def normalize_text(text: str) -> str:
    from brandguard.discovery.normalize import normalize

    return normalize(text)


# ---- Creation -----------------------------------------------------------------


def create_scan(session: Session, *, text: str | None = None, sources: list[str] | None, depth: str,
                tuning: dict | None = None, clients: Callable | None = None,
                batch_id: str | None = None, trigger: str = "manual",
                name: str | None = None, domain: str | None = None,
                store: str | None = None) -> Scan:
    sources = [s for s in (sources or DEFAULT_SOURCES) if s in SOURCES]
    if not sources:
        raise ValueError(f"no valid sources; choose from {', '.join(SOURCES)}")
    if depth not in DEPTH:
        raise ValueError(f"unknown depth {depth!r}; choose from {', '.join(DEPTH)}")
    if name or domain or store:
        brand, input_type, how, _ = resolve_structured(session, name=name, domain=domain,
                                                       store=store, clients=clients)
        text = " · ".join(p.strip() for p in (name, domain, store) if p and p.strip())
    else:
        if not text or not text.strip():
            raise ValueError("enter a brand name, a domain or a store link")
        brand, input_type, how, _ = resolve_input(session, text, clients=clients)
    scan = Scan(brand_id=brand.id, input_raw=text.strip(), input_type=input_type,
                resolved_how=how, sources=sources, depth=depth, tuning=tuning or {},
                status="queued", batch_id=batch_id, trigger=trigger)
    session.add(scan)
    session.flush()
    for source in sources:
        session.add(ScanSource(scan_id=scan.id, source=source, status="queued"))
    session.flush()
    return scan


def tuning_for(scan: Scan, source: str) -> dict:
    """Effective runner options: engine default < depth preset < explicit tuning."""
    opts: dict = {**DEFAULTS.get(source, {})}
    opts.update(DEPTH[scan.depth].get(source, {}))
    for key, value in (scan.tuning or {}).items():
        if key in DEFAULTS.get(source, {}):
            opts[key] = value
    return opts


# ---- Execution ------------------------------------------------------------------


def _persist_findings(session: Session, scan: Scan, result: RunResult) -> None:
    brand_id = scan.brand_id
    # first-seen lookup for this brand, one query
    keys = [str(r.get("app_id") or r.get("domain")) for r in result.rows]
    earlier: dict[str, datetime] = {}
    if keys:
        stmt = (select(Finding.key, Finding.first_seen_at)
                .where(Finding.brand_id == brand_id, Finding.key.in_(keys)))
        for key, seen in session.execute(stmt):
            if key not in earlier or seen < earlier[key]:
                earlier[key] = seen
    now = _now()
    for row in result.rows:
        if "domain" in row:
            key = str(row["domain"])
            finding = Finding(
                scan_id=scan.id, brand_id=brand_id, kind="domain", key=key, name=key,
                source=result.source, label=str(row.get("verdict", "")),
                category=str(row.get("category") or category_of_row(row).value),
                confidence=None, score=None, similarity=row.get("similarity"),
                reason="", priority=row.get("priority"), confirmed_live=row.get("confirmed_live"),
                evidence=[{"signal": "domain", "text": t, "weight": 0.0, "tier": 0}
                          for t in (row.get("evidence") or [])],
                extra={"domain_age_days": row.get("domain_age_days"),
                       "cert_age_days": row.get("cert_age_days")},
                first_seen_at=earlier.get(key, now), created_at=now,
            )
        else:
            key = str(row["app_id"])
            evidence = row.get("evidence_detail") or [
                {"signal": "", "text": t, "weight": 0.0, "tier": 0} for t in row.get("evidence", [])
            ]
            finding = Finding(
                scan_id=scan.id, brand_id=brand_id, kind="app", key=key,
                name=str(row.get("name") or ""), source=str(row.get("source", result.source)),
                label=str(row.get("label", "")),
                category=str(row.get("category") or category_of_row(row).value),
                confidence=row.get("confidence"), score=row.get("score"), similarity=None,
                tiers_used=list(row.get("tiers_used") or []), reason=str(row.get("reason") or ""),
                priority=None, confirmed_live=None, evidence=evidence,
                extra=dict(row.get("facts") or {}),
                first_seen_at=earlier.get(key, now), created_at=now,
            )
        session.add(finding)


def _wait_for_measurement(scan_id: str, key: str, timeout_s: float = 600.0,
                          poll_s: float = 2.0) -> object | None:
    """Block until the scan's Play run ended, then return its measurement.

    Returns None when Play failed, was cancelled, was not part of the scan,
    or did not finish within the timeout; the caller proceeds without it.
    """
    import time as _time

    deadline = _time.monotonic() + timeout_s
    while True:
        with session_scope() as session:
            scan = session.get(Scan, scan_id)
            if scan is None:
                return None
            play = next((r for r in scan.source_runs if r.source == "play"), None)
            if play is None or play.status in ("failed", "cancelled"):
                return None
            if play.status == "done":
                return (scan.tuning or {}).get("_measurements", {}).get(key)
        if _time.monotonic() >= deadline:
            return None
        _time.sleep(poll_s)


def run_scan_source(scan_id: str, source: str,
                    runner: Callable[..., RunResult] = run_source,
                    play_wait_s: float = 1200.0) -> None:
    """Execute one source of a scan and record it. Never raises."""
    with session_scope() as session:
        scan = session.get(Scan, scan_id)
        if scan is None:
            return
        row = session.scalar(select(ScanSource).where(ScanSource.scan_id == scan_id,
                                                      ScanSource.source == source))
        if row is None:
            return
        if scan.status == "cancelled" or row.status == "cancelled":
            return  # cancelled while it waited in the queue: spend nothing
        row.status, row.started_at = "running", _now()
        if scan.status == "queued":
            scan.status, scan.started_at = "running", _now()
        profile = brand_store.to_profile(scan.brand)
        opts = tuning_for(scan, source)
        wants_play_facts = source == "serper" and "play" in (scan.sources or [])

    if wants_play_facts:
        # The APK-site run reads what Play measured about the brand word
        # (K-075); Play of the same scan is normally a minute ahead of it.
        shared = _wait_for_measurement(scan_id, "brand_word_shared_by", timeout_s=play_wait_s)
        if shared is not None:
            profile = profile.model_copy(update={"brand_word_shared_by": int(shared)})
        titles = _wait_for_measurement(scan_id, "official_titles", timeout_s=5)
        if isinstance(titles, list) and titles:
            extra = [str(t) for t in titles if t and str(t) not in profile.known_official_apps]
            profile = profile.model_copy(update={"known_official_apps": [*profile.known_official_apps, *extra]})

    try:
        result = runner(profile, source, **opts)
    except Exception as exc:  # noqa: BLE001 - recorded, never propagated
        log.exception("scan %s source %s failed", scan_id, source)
        with session_scope() as session:
            row = session.scalar(select(ScanSource).where(ScanSource.scan_id == scan_id,
                                                          ScanSource.source == source))
            if row is not None:
                row.status, row.error, row.finished_at = "failed", f"{type(exc).__name__}: {exc}", _now()
        _finalize_if_complete(scan_id)
        return

    with session_scope() as session:
        scan = session.get(Scan, scan_id)
        row = session.scalar(select(ScanSource).where(ScanSource.scan_id == scan_id,
                                                      ScanSource.source == source))
        if scan is None or row is None:
            return
        if scan.status == "cancelled":
            # Cancelled while this source was in flight: the network cost is
            # spent, but the result is not what the operator asked for anymore.
            row.status, row.finished_at = "cancelled", _now()
            return
        _persist_findings(session, scan, result)
        if result.measurements:
            tuning = dict(scan.tuning or {})
            tuning["_measurements"] = {**tuning.get("_measurements", {}), **result.measurements}
            scan.tuning = tuning
        row.status, row.finished_at = "done", _now()
        row.candidates, row.detected, row.watch = result.candidates, result.detected, result.watch
        row.errors, row.warnings = list(result.errors), list(result.warnings)
        row.requests, row.duration_ms = result.requests, result.duration_ms
    _finalize_if_complete(scan_id)


def _finalize_if_complete(scan_id: str) -> None:
    with _finalize_lock, session_scope() as session:
        scan = session.get(Scan, scan_id)
        if scan is None or scan.status in ("done", "partial", "failed", "cancelled"):
            return
        runs = list(scan.source_runs)
        if any(r.status in ("queued", "running") for r in runs):
            return
        failed = [r for r in runs if r.status == "failed"]
        scan.status = ("failed" if len(failed) == len(runs)
                       else "partial" if failed else "done")
        scan.finished_at = _now()
        scan.counts = summarize_counts(session, scan)


def cancel_scan(session: Session, scan: Scan) -> bool:
    """Stop a queued or running scan. Returns False when it had already ended.

    Queued sources are marked cancelled and skipped by the worker; a source
    already in flight finishes its network calls (they cannot be interrupted
    safely) and then discards its result. Findings recorded so far stay, so a
    half-finished scan still shows what its finished sources found.
    """
    if scan.status not in ("queued", "running"):
        return False
    scan.status, scan.finished_at = "cancelled", _now()
    for run in scan.source_runs:
        if run.status == "queued":
            run.status, run.finished_at = "cancelled", _now()
    scan.counts = summarize_counts(session, scan)
    return True


def summarize_counts(session: Session, scan: Scan) -> dict:
    counts = {c.value: 0 for c in Category}
    total = 0
    for category, in session.execute(select(Finding.category).where(Finding.scan_id == scan.id)):
        counts[category] = counts.get(category, 0) + 1
        total += 1
    counts["total"] = total
    return counts


def mark_interrupted(reason: str = "interrupted by restart") -> int:
    """On startup, anything left running belongs to a process that is gone."""
    n = 0
    with session_scope() as session:
        for run in session.scalars(select(ScanSource).where(ScanSource.status.in_(["queued", "running"]))):
            run.status, run.error, run.finished_at = "failed", reason, _now()
            n += 1
        for scan in session.scalars(select(Scan).where(Scan.status.in_(["queued", "running"]))):
            failed = all(r.status == "failed" for r in scan.source_runs)
            scan.status = "failed" if failed else "partial"
            scan.error = reason
            scan.finished_at = _now()
            scan.counts = summarize_counts(session, scan)
    return n


# ---- Analyst reviews ------------------------------------------------------------


def reviews_for(session: Session, brand_id: str, keys: list[str] | None = None) -> dict[str, Review]:
    """Reviews of a brand keyed by finding key (all of them, or only ``keys``)."""
    stmt = select(Review).where(Review.brand_id == brand_id)
    if keys is not None:
        if not keys:
            return {}
        stmt = stmt.where(Review.key.in_(keys))
    return {r.key: r for r in session.scalars(stmt)}


def set_review(session: Session, brand_id: str, key: str, status: str, note: str = "") -> Review:
    review = session.scalar(select(Review).where(Review.brand_id == brand_id, Review.key == key))
    if review is None:
        review = Review(brand_id=brand_id, key=key, status=status, note=note)
        session.add(review)
    else:
        review.status, review.note, review.updated_at = status, note, _now()
    session.flush()
    return review


def clear_review(session: Session, brand_id: str, key: str) -> bool:
    review = session.scalar(select(Review).where(Review.brand_id == brand_id, Review.key == key))
    if review is None:
        return False
    session.delete(review)
    session.flush()
    return True


# A finding a person has settled needs no action: dismissed as a false
# positive, resolved, or already sent for takedown. "confirmed" keeps it in
# the queue: the takedown is still to do.
SETTLED_REVIEWS = ("false_positive", "resolved", "takedown_sent")


def needs_action_count(session: Session, scan: Scan) -> int:
    rows = session.scalars(select(Finding.key).where(
        Finding.scan_id == scan.id, Finding.category.in_([c.value for c in ACTIONABLE]))).all()
    if not rows:
        return 0
    settled = {k for k, r in reviews_for(session, scan.brand_id, list(set(rows))).items()
               if r.status in SETTLED_REVIEWS}
    return sum(1 for k in rows if k not in settled)


# ---- Diff between scans --------------------------------------------------------


def previous_scan(session: Session, scan: Scan) -> Scan | None:
    """The brand's latest finished scan before this one, with the same sources."""
    stmt = (select(Scan).where(Scan.brand_id == scan.brand_id, Scan.id != scan.id,
                               Scan.created_at < scan.created_at,
                               Scan.status.in_(("done", "partial")))
            .order_by(Scan.created_at.desc()))
    for candidate in session.scalars(stmt):
        if set(candidate.sources or []) == set(scan.sources or []):
            return candidate
    return None


def diff_scans(session: Session, scan: Scan, against: Scan | None) -> dict:
    """Keys that appeared, disappeared or changed category between two scans."""
    current = {f.key: f for f in session.scalars(select(Finding).where(Finding.scan_id == scan.id))}
    if against is None:
        return {"new": list(current.values()), "gone": [], "changed": [], "unchanged": 0}
    before = {f.key: f for f in session.scalars(select(Finding).where(Finding.scan_id == against.id))}
    new = [f for k, f in current.items() if k not in before]
    gone = [f for k, f in before.items() if k not in current]
    changed, unchanged = [], 0
    for k, f in current.items():
        if k in before:
            if before[k].category != f.category:
                changed.append((f, before[k].category))
            else:
                unchanged += 1
    return {"new": new, "gone": gone, "changed": changed, "unchanged": unchanged}


# ---- Scheduled re-scans ---------------------------------------------------------

SCHEDULE_INTERVALS = {"daily": 24 * 3600, "weekly": 7 * 24 * 3600}


def set_schedule(brand: Brand, schedule: str, sources: list[str] | None, depth: str | None) -> None:
    if schedule not in ("off", *SCHEDULE_INTERVALS):
        raise ValueError(f"unknown schedule {schedule!r}; choose off, daily or weekly")
    brand.schedule = schedule
    if sources is not None:
        brand.schedule_sources = [s for s in sources if s in SOURCES] or list(DEFAULT_SOURCES)
    if depth is not None:
        if depth not in DEPTH:
            raise ValueError(f"unknown depth {depth!r}")
        brand.schedule_depth = depth
    if schedule == "off":
        brand.next_run_at = None
    elif brand.next_run_at is None:
        # first run after one interval; "scan now" is a separate button
        from datetime import timedelta
        brand.next_run_at = _now() + timedelta(seconds=SCHEDULE_INTERVALS[schedule])


def due_brands(session: Session, now: datetime | None = None) -> list[Brand]:
    now = now or _now()
    return session.scalars(select(Brand).where(Brand.schedule != "off", Brand.next_run_at.is_not(None),
                                              Brand.next_run_at <= now)).all()


def run_due_schedules(submit: Callable[[str, list[str]], None], now: datetime | None = None) -> int:
    """Start a scan for every brand whose schedule is due. Returns how many."""
    from datetime import timedelta

    now = now or _now()
    pending: list[tuple[str, list[str]]] = []
    with session_scope() as session:
        for brand in due_brands(session, now):
            sources = list(brand.schedule_sources or DEFAULT_SOURCES)
            brand.next_run_at = now + timedelta(seconds=SCHEDULE_INTERVALS[brand.schedule])
            try:
                scan = create_scan(session, text=brand.brand_name, sources=sources,
                                   depth=brand.schedule_depth or "normal", trigger="schedule")
            except ValueError as exc:
                log.warning("scheduled scan of %s skipped: %s", brand.id, exc)
                continue
            session.flush()
            pending.append((scan.id, list(scan.sources)))
    # Submit only after the transaction committed: a worker that reads the
    # scan before it exists would drop it silently.
    for scan_id, sources in pending:
        submit(scan_id, sources)
    return len(pending)
