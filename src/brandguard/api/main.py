"""FastAPI application.

    python -m brandguard.api            # http://127.0.0.1:8000, docs at /docs

Serves the JSON API under /api and, when web/dist exists, the built frontend
at /. State lives in the database; the process holds only the worker pool.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from brandguard.api import brands as brand_store
from brandguard.api import scan_service
from brandguard.api.db import get_session, init_db
from brandguard.api.models import Batch, Brand, Finding, Review, Scan
from brandguard.api.schemas import (
    BatchError,
    BatchOut,
    BatchRequest,
    BrandSummary,
    BrandUpdate,
    DiffOut,
    ReviewIn,
    ReviewOut,
    REVIEW_STATUSES,
    FindingOut,
    FindingPage,
    HealthOut,
    ScanListItem,
    ScanPage,
    ScanOut,
    ScanRequest,
    SourceRunOut,
)
from brandguard.api.worker import InlineWorker, Worker
from brandguard.config import REPO_ROOT, data_dir, load_dotenv, setting
from brandguard.hunt_engine import SOURCES
from brandguard.product.category import DISPLAY_ORDER

log = logging.getLogger("brandguard.api")
VERSION = "2.0.0"

WEB_DIST = Path(setting("BRANDGUARD_WEB_DIST", str(REPO_ROOT / "web" / "dist")))


_tunnel_cache: dict = {"at": 0.0, "url": None}


def public_url(now: float | None = None) -> str | None:
    """The console's current public address from the cloudflared sidecar.

    A quick tunnel publishes its hostname on its metrics server
    (``/quicktunnel``); the address changes whenever the sidecar restarts, so
    the header reads it live rather than anyone copying it from a log. Cached
    for 30 s because the UI polls health often. Anything but a clean answer
    means "no public address", never an error.
    """
    import json as _json
    import time as _time
    import urllib.request

    base = os.environ.get("BRANDGUARD_TUNNEL_METRICS")
    if not base:
        return None
    now = _time.time() if now is None else now
    if now - _tunnel_cache["at"] < 30:
        return _tunnel_cache["url"]
    url = None
    try:
        with urllib.request.urlopen(f"{base.rstrip('/')}/quicktunnel", timeout=1.5) as r:  # noqa: S310
            host = (_json.load(r) or {}).get("hostname") or ""
        if host and "." in host and "/" not in host:
            url = f"https://{host}"
    except Exception:  # noqa: BLE001 - the sidecar may be absent or starting
        url = None
    _tunnel_cache.update(at=now, url=url)
    return url


def _store_link(kind: str, key: str, source: str) -> str | None:
    if kind == "domain":
        return f"https://{key}"
    if key.startswith("http://") or key.startswith("https://"):
        return key
    if source.startswith("google_play"):
        return f"https://play.google.com/store/apps/details?id={key}"
    return None


def _brand_summary(session: Session, brand: Brand) -> BrandSummary:
    last, count = session.execute(
        select(func.max(Scan.created_at), func.count(Scan.id)).where(Scan.brand_id == brand.id)
    ).one()
    return BrandSummary(
        id=brand.id, brand_name=brand.brand_name, sector=brand.sector or "unknown",
        official_domains=list(brand.official_domains or []),
        official_publishers=list(brand.official_publishers or []),
        official_package_ids=list(brand.official_package_ids or []),
        known_official_apps=list(brand.known_official_apps or []),
        known_affiliates=list(brand.known_affiliates or []),
        resolved_from=brand.resolved_from, needs_review=bool(brand.needs_review),
        review_notes=list(brand.review_notes or []), resolution=dict(brand.resolution or {}),
        last_scan_at=last, scan_count=int(count or 0),
        schedule=brand.schedule or "off", schedule_sources=list(brand.schedule_sources or []),
        schedule_depth=brand.schedule_depth or "normal", next_run_at=brand.next_run_at,
    )


def _scan_item(s: Scan) -> ScanListItem:
    return ScanListItem(
        id=s.id, brand_id=s.brand_id, brand_name=s.brand.brand_name, input_raw=s.input_raw,
        input_type=s.input_type, sources=list(s.sources), depth=s.depth, status=s.status,
        counts=s.counts or {}, created_at=s.created_at, finished_at=s.finished_at,
        batch_id=s.batch_id, trigger=s.trigger or "manual",
    )


def _batch_errors(session: Session, batch_id: str) -> list[BatchError]:
    batch = session.get(Batch, batch_id)
    return [BatchError(**e) for e in (batch.errors if batch else [])]


def _batch_out(session: Session, batch_id: str, scans: list[Scan], errors: list) -> BatchOut:
    items = [_scan_item(s) for s in scans]
    totals: dict[str, int] = {}
    for s in scans:
        for key, value in (s.counts or {}).items():
            totals[key] = totals.get(key, 0) + int(value or 0)
    live = any(s.status in ("queued", "running") for s in scans)
    return BatchOut(id=batch_id, created_at=min(s.created_at for s in scans),
                    status="running" if live else "done", scans=items, errors=list(errors),
                    totals=totals)


def _scan_out(session: Session, scan: Scan) -> ScanOut:
    runs = sorted(scan.source_runs, key=lambda r: scan.sources.index(r.source)
                  if r.source in scan.sources else 99)
    counts = dict(scan.counts or scan_service.summarize_counts(session, scan))
    counts["needs_action"] = scan_service.needs_action_count(session, scan)
    return ScanOut(
        id=scan.id, brand=_brand_summary(session, scan.brand), input_raw=scan.input_raw,
        input_type=scan.input_type, resolved_how=scan.resolved_how, sources=list(scan.sources),
        depth=scan.depth, tuning=dict(scan.tuning or {}), status=scan.status, error=scan.error,
        counts=counts, created_at=scan.created_at, started_at=scan.started_at,
        finished_at=scan.finished_at,
        source_runs=[SourceRunOut(
            source=r.source, status=r.status, error=r.error, errors=list(r.errors or []),
            warnings=list(r.warnings or []), candidates=r.candidates, detected=r.detected,
            watch=r.watch, requests=r.requests, duration_ms=r.duration_ms,
            started_at=r.started_at, finished_at=r.finished_at,
        ) for r in runs],
    )


def _review_out(r: Review | None) -> ReviewOut | None:
    if r is None:
        return None
    return ReviewOut(key=r.key, status=r.status, note=r.note or "", updated_at=r.updated_at)


def _finding_out(f: Finding, review: Review | None = None) -> FindingOut:
    return FindingOut(
        id=f.id, scan_id=f.scan_id, kind=f.kind, key=f.key, name=f.name, source=f.source,
        label=f.label, category=f.category, confidence=f.confidence, score=f.score,
        similarity=f.similarity, tiers_used=list(f.tiers_used or []), reason=f.reason,
        priority=f.priority, confirmed_live=f.confirmed_live,
        evidence=list(f.evidence or []), extra=dict(f.extra or {}),
        first_seen_at=f.first_seen_at, created_at=f.created_at,
        seen_before=bool(f.first_seen_at and f.created_at and f.first_seen_at < f.created_at),
        link=_store_link(f.kind, f.key, f.source), review=_review_out(review),
    )


def _findings_out(session: Session, brand_id: str, rows: list[Finding]) -> list[FindingOut]:
    """Serialize with each row's analyst review attached (one query)."""
    reviews = scan_service.reviews_for(session, brand_id, list({f.key for f in rows}))
    return [_finding_out(f, reviews.get(f.key)) for f in rows]


def _scheduler_loop(worker, stop: "threading.Event", interval_s: float = 60.0) -> None:
    """Every minute, start the scans whose schedule is due (K-073)."""
    while not stop.wait(interval_s):
        try:
            started = scan_service.run_due_schedules(worker.submit_scan)
            if started:
                log.info("scheduler started %d scan(s)", started)
        except Exception:  # noqa: BLE001 - the loop must survive any failure
            log.exception("scheduler tick failed")


def create_app(*, worker: Worker | InlineWorker | None = None, import_watchlist: bool = True,
               run_scheduler: bool = True) -> FastAPI:
    load_dotenv()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db()
        interrupted = scan_service.mark_interrupted()
        if interrupted:
            log.warning("marked %d interrupted source runs as failed", interrupted)
        if import_watchlist:
            watchlist = data_dir() / "watchlist"
            if watchlist.is_dir():
                from brandguard.api.db import session_scope

                with session_scope() as session:
                    stats = brand_store.import_watchlist(session, watchlist)
                log.info("watchlist import: %s", stats)
        app.state.worker = worker or Worker()
        stop = threading.Event()
        app.state.scheduler_stop = stop
        if run_scheduler:
            thread = threading.Thread(target=_scheduler_loop, args=(app.state.worker, stop),
                                      name="bg-schedule", daemon=True)
            thread.start()
        try:
            yield
        finally:
            stop.set()
            app.state.worker.shutdown()

    app = FastAPI(title="BrandGuard", version=VERSION, lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json")

    # ---- optional access gate -------------------------------------------------
    # The console has no user model; when it is reachable beyond localhost (a
    # demo over a tunnel, an office LAN) one shared login keeps strangers from
    # starting scans on the operator's API keys. HTTP Basic: browsers prompt
    # for it natively, curl takes -u, nothing in the UI changes.
    basic = setting("BRANDGUARD_BASIC_AUTH")  # "user:password"
    if basic and ":" in basic:
        import base64
        import secrets

        expected = basic.strip().encode()

        @app.middleware("http")
        async def require_login(request, call_next):
            header = request.headers.get("authorization", "")
            ok = False
            if header.lower().startswith("basic "):
                try:
                    given = base64.b64decode(header[6:].strip())
                    ok = secrets.compare_digest(given, expected)
                except Exception:  # noqa: BLE001 - malformed header is just "not ok"
                    ok = False
            if not ok:
                return JSONResponse({"detail": "login required"}, status_code=401,
                                    headers={"WWW-Authenticate": 'Basic realm="BrandGuard"'})
            return await call_next(request)

    # ---- health ---------------------------------------------------------------

    @app.get("/api/health", response_model=HealthOut)
    def health():
        from brandguard.triage.adjudicator import describe_adjudicator

        adjudicator, model = describe_adjudicator()
        return HealthOut(
            status="ok", adjudicator=adjudicator, adjudicator_model=model,
            serper_configured=bool(os.environ.get("SERPER_API_KEY")),
            play_available=importlib.util.find_spec("google_play_scraper") is not None,
            sources=list(SOURCES), depths=list(scan_service.DEPTH),
            inflight=getattr(app.state.worker, "inflight", 0), version=VERSION,
            public_url=public_url(),
        )

    # ---- scans ----------------------------------------------------------------

    @app.post("/api/scans", response_model=ScanOut, status_code=202)
    def create_scan(body: ScanRequest, session: Session = Depends(get_session)):
        try:
            scan = scan_service.create_scan(session, text=body.input, sources=body.sources,
                                            depth=body.depth, tuning=body.tuning,
                                            name=body.brand_name, domain=body.domain, store=body.store)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        session.commit()
        app.state.worker.submit_scan(scan.id, list(scan.sources))
        session.refresh(scan)
        return _scan_out(session, scan)

    @app.post("/api/scans/batch", response_model=BatchOut, status_code=202)
    def create_batch(body: BatchRequest, session: Session = Depends(get_session)):
        """One scan per input, started together. An input that cannot be
        resolved (a platform domain, an empty line) is reported, not fatal:
        the other brands still run."""
        import uuid

        batch_id = uuid.uuid4().hex
        seen: set[str] = set()
        errors: list[BatchError] = []
        created: list[Scan] = []
        for raw in body.inputs:
            text = raw.strip()
            if not text or text.lower() in seen:
                continue
            seen.add(text.lower())
            try:
                if "|" in text:
                    parts = [p.strip() for p in text.split("|")] + ["", "", ""]
                    scan = scan_service.create_scan(session, sources=body.sources, depth=body.depth,
                                                    tuning=body.tuning, batch_id=batch_id,
                                                    name=parts[0] or None, domain=parts[1] or None,
                                                    store=parts[2] or None)
                else:
                    scan = scan_service.create_scan(session, text=text, sources=body.sources,
                                                    depth=body.depth, tuning=body.tuning,
                                                    batch_id=batch_id)
            except ValueError as exc:
                session.rollback()
                errors.append(BatchError(input=text, error=str(exc)))
                continue
            session.commit()
            created.append(scan)
        if not created:
            raise HTTPException(status_code=422, detail={"errors": [e.model_dump() for e in errors]})
        session.add(Batch(id=batch_id, errors=[e.model_dump() for e in errors]))
        session.commit()
        for scan in created:
            app.state.worker.submit_scan(scan.id, list(scan.sources))
        for scan in created:
            session.refresh(scan)
        return _batch_out(session, batch_id, created, errors)

    @app.post("/api/scans/{scan_id}/cancel", response_model=ScanOut)
    def cancel_scan(scan_id: str, session: Session = Depends(get_session)):
        scan = session.get(Scan, scan_id)
        if scan is None:
            raise HTTPException(status_code=404, detail="scan not found")
        scan_service.cancel_scan(session, scan)
        session.flush()
        return _scan_out(session, scan)

    @app.post("/api/batches/{batch_id}/cancel", response_model=BatchOut)
    def cancel_batch(batch_id: str, session: Session = Depends(get_session)):
        """Cancel every scan of the batch that has not finished."""
        scans = session.scalars(select(Scan).where(Scan.batch_id == batch_id)
                                .order_by(Scan.created_at)).all()
        if not scans:
            raise HTTPException(status_code=404, detail="batch not found")
        for scan in scans:
            scan_service.cancel_scan(session, scan)
        session.flush()
        return _batch_out(session, batch_id, scans, _batch_errors(session, batch_id))

    @app.get("/api/batches/{batch_id}", response_model=BatchOut)
    def get_batch(batch_id: str, session: Session = Depends(get_session)):
        scans = session.scalars(select(Scan).where(Scan.batch_id == batch_id)
                                .order_by(Scan.created_at)).all()
        if not scans:
            raise HTTPException(status_code=404, detail="batch not found")
        return _batch_out(session, batch_id, scans, _batch_errors(session, batch_id))

    @app.get("/api/scans", response_model=list[ScanListItem])
    def list_scans(brand_id: str | None = None, batch_id: str | None = None,
                   limit: int = Query(30, le=200), session: Session = Depends(get_session)):
        stmt = select(Scan).order_by(Scan.created_at.desc()).limit(limit)
        if brand_id:
            stmt = stmt.where(Scan.brand_id == brand_id)
        if batch_id:
            stmt = stmt.where(Scan.batch_id == batch_id)
        scans = session.scalars(stmt).all()
        return [_scan_item(s) for s in scans]

    @app.get("/api/scans/search", response_model=ScanPage)
    def search_scans(q: str | None = None, view: str = Query("all", pattern="^(all|active|attention|batches)$"),
                     limit: int = Query(50, le=200), offset: int = Query(0, ge=0),
                     session: Session = Depends(get_session)):
        """The scans console: filtered, newest first, in pages.

        ``view`` is one of all / active (queued or running) / attention (at
        least one malicious or suspicious finding) / batches (part of a batch);
        ``q`` matches the brand name or the typed input. The attention filter
        reads the stored counts, so it is evaluated in Python over the
        filtered rows; scan counts stay in the thousands, not millions.
        """
        stmt = select(Scan).order_by(Scan.created_at.desc())
        if q:
            needle = f"%{q.strip().lower()}%"
            stmt = stmt.join(Brand, Brand.id == Scan.brand_id).where(
                func.lower(Brand.brand_name).like(needle) | func.lower(Scan.input_raw).like(needle))
        if view == "active":
            stmt = stmt.where(Scan.status.in_(("queued", "running")))
        elif view == "batches":
            stmt = stmt.where(Scan.batch_id.is_not(None))
        rows = session.scalars(stmt).all()
        if view == "attention":
            rows = [s for s in rows if ((s.counts or {}).get("malicious", 0) + (s.counts or {}).get("suspicious", 0)) > 0]
        page = rows[offset:offset + limit]
        return ScanPage(items=[_scan_item(s) for s in page], total=len(rows), limit=limit, offset=offset)

    @app.get("/api/scans/{scan_id}", response_model=ScanOut)
    def get_scan(scan_id: str, session: Session = Depends(get_session)):
        scan = session.get(Scan, scan_id)
        if scan is None:
            raise HTTPException(status_code=404, detail="scan not found")
        return _scan_out(session, scan)

    def _export_payload(session: Session, scan: Scan) -> tuple[dict, str]:
        """One scan as a JSON document plus its file name."""
        items = session.scalars(select(Finding).where(Finding.scan_id == scan.id)).all()
        order = {c.value: i for i, c in enumerate(DISPLAY_ORDER)}
        items.sort(key=lambda f: (order.get(f.category, 9), -(f.confidence or 0), f.key))
        payload = {
            "scan": _scan_out(session, scan).model_dump(mode="json"),
            "brand": _brand_summary(session, scan.brand).model_dump(mode="json"),
            "findings": [_finding_out(f).model_dump(mode="json") for f in items],
        }
        # HTTP headers are latin-1: "Is Bankasi" must not carry its dotted I or
        # its s-cedilla into Content-Disposition (found live: three Turkish
        # banks exported as an empty "export.txt", every other brand worked).
        from brandguard.registry import slugify

        slug = slugify(scan.brand.brand_name) or "brand"
        stamp = scan.created_at.strftime("%Y%m%d_%H%M") if scan.created_at else "scan"
        return payload, f"brandguard_{slug}_{stamp}.json"

    @app.get("/api/scans/{scan_id}/export")
    def export_scan(scan_id: str, session: Session = Depends(get_session)):
        """The whole scan as one JSON file: header, source runs, every finding
        with its evidence. For sharing a result outside the console."""
        scan = session.get(Scan, scan_id)
        if scan is None:
            raise HTTPException(status_code=404, detail="scan not found")
        payload, name = _export_payload(session, scan)
        return JSONResponse(payload, headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/api/batches/{batch_id}/export")
    def export_batch(batch_id: str, session: Session = Depends(get_session)):
        """Every scan of a batch as one ZIP: one JSON per brand, plus a
        summary.json with the totals and the per-brand counts."""
        import io
        import json
        import zipfile

        scans = session.scalars(select(Scan).where(Scan.batch_id == batch_id)
                                .order_by(Scan.created_at)).all()
        if not scans:
            raise HTTPException(status_code=404, detail="batch not found")
        buf = io.BytesIO()
        used: set[str] = set()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for scan in scans:
                payload, name = _export_payload(session, scan)
                if name in used:  # two scans of one brand in the same minute
                    name = name.replace(".json", f"_{scan.id[:6]}.json")
                used.add(name)
                zf.writestr(name, json.dumps(payload, ensure_ascii=False, indent=2))
            summary = _batch_out(session, batch_id, scans, _batch_errors(session, batch_id)).model_dump(mode="json")
            zf.writestr("summary.json", json.dumps(summary, ensure_ascii=False, indent=2))
        stamp = min(s.created_at for s in scans).strftime("%Y%m%d_%H%M")
        return Response(buf.getvalue(), media_type="application/zip", headers={
            "Content-Disposition": f'attachment; filename="brandguard_batch_{stamp}.zip"',
        })

    @app.post("/api/scans/{scan_id}/retry", response_model=ScanOut)
    def retry_scan(scan_id: str, source: str | None = None,
                   session: Session = Depends(get_session)):
        """Re-run the failed sources of a scan (or one named source)."""
        scan = session.get(Scan, scan_id)
        if scan is None:
            raise HTTPException(status_code=404, detail="scan not found")
        targets = [r for r in scan.source_runs
                   if (r.status == "failed" if source is None else r.source == source)]
        if not targets:
            raise HTTPException(status_code=409, detail="nothing to retry")
        for run in targets:
            run.status, run.error, run.started_at, run.finished_at = "queued", None, None, None
            for f in session.scalars(select(Finding).where(Finding.scan_id == scan.id,
                                                            Finding.source.like(f"{run.source}%"))):
                session.delete(f)
        scan.status, scan.finished_at, scan.error = "queued", None, None
        session.commit()
        app.state.worker.submit_scan(scan.id, [r.source for r in targets])
        session.refresh(scan)
        return _scan_out(session, scan)

    @app.get("/api/scans/{scan_id}/items", response_model=FindingPage)
    def list_items(scan_id: str, category: str | None = None, source: str | None = None,
                   kind: str | None = None, q: str | None = None,
                   new_only: bool = False, open_only: bool = False,
                   limit: int = Query(200, le=1000), offset: int = 0,
                   session: Session = Depends(get_session)):
        """``new_only``: keys first seen in this scan. ``open_only``: drop
        findings an analyst settled (false positive, resolved, takedown sent)."""
        if session.get(Scan, scan_id) is None:
            raise HTTPException(status_code=404, detail="scan not found")
        scan = session.get(Scan, scan_id)
        stmt = select(Finding).where(Finding.scan_id == scan_id)
        if category:
            stmt = stmt.where(Finding.category.in_(category.split(",")))
        if source:
            stmt = stmt.where(Finding.source.like(f"{source}%"))
        if kind:
            stmt = stmt.where(Finding.kind == kind)
        if q:
            like = f"%{q}%"
            stmt = stmt.where((Finding.key.like(like)) | (Finding.name.like(like)))
        if new_only:
            stmt = stmt.where(Finding.first_seen_at == Finding.created_at)
        rows = session.scalars(stmt).all()
        reviews = scan_service.reviews_for(session, scan.brand_id, list({f.key for f in rows}))
        if open_only:
            rows = [f for f in rows
                    if reviews.get(f.key) is None
                    or reviews[f.key].status not in scan_service.SETTLED_REVIEWS]
        total = len(rows)
        order = {c.value: i for i, c in enumerate(DISPLAY_ORDER)}
        rows.sort(key=lambda f: (order.get(f.category, 9), -(f.confidence or 0), f.key))
        page = rows[offset:offset + limit]
        return FindingPage(items=[_finding_out(f, reviews.get(f.key)) for f in page], total=total,
                           limit=limit, offset=offset)

    @app.get("/api/items/{item_id}", response_model=FindingOut)
    def get_item(item_id: str, session: Session = Depends(get_session)):
        f = session.get(Finding, item_id)
        if f is None:
            raise HTTPException(status_code=404, detail="finding not found")
        return _findings_out(session, f.brand_id, [f])[0]

    # ---- brands ---------------------------------------------------------------

    @app.get("/api/brands", response_model=list[BrandSummary])
    def list_brands(session: Session = Depends(get_session)):
        brands = session.scalars(select(Brand).order_by(Brand.brand_name)).all()
        return [_brand_summary(session, b) for b in brands]

    @app.get("/api/brands/{brand_id}", response_model=BrandSummary)
    def get_brand(brand_id: str, session: Session = Depends(get_session)):
        brand = session.get(Brand, brand_id)
        if brand is None:
            raise HTTPException(status_code=404, detail="brand not found")
        return _brand_summary(session, brand)

    @app.patch("/api/brands/{brand_id}", response_model=BrandSummary)
    def update_brand(brand_id: str, body: BrandUpdate, session: Session = Depends(get_session)):
        brand = session.get(Brand, brand_id)
        if brand is None:
            raise HTTPException(status_code=404, detail="brand not found")
        data = body.model_dump(exclude_unset=True)
        schedule_fields = {k: data.pop(k) for k in ("schedule", "schedule_sources", "schedule_depth")
                           if k in data}
        for field, value in data.items():
            setattr(brand, field, value)
        if schedule_fields:
            try:
                scan_service.set_schedule(
                    brand, schedule_fields.get("schedule", brand.schedule or "off"),
                    schedule_fields.get("schedule_sources"), schedule_fields.get("schedule_depth"))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        if data:
            # An operator's profile edit is authoritative: no longer automatic.
            brand.resolved_from = "manual"
        if body.review_notes is not None and body.needs_review is None:
            brand.needs_review = bool(body.review_notes)
        session.flush()
        return _brand_summary(session, brand)

    @app.delete("/api/brands/{brand_id}", status_code=204)
    def delete_brand(brand_id: str, session: Session = Depends(get_session)):
        """Remove a brand with all its scans and findings (a mistyped input, say).

        Refused while one of its scans is still running, because the worker
        would write findings for a row that no longer exists.
        """
        brand = session.get(Brand, brand_id)
        if brand is None:
            raise HTTPException(status_code=404, detail="brand not found")
        active = session.scalar(select(func.count()).select_from(Scan).where(
            Scan.brand_id == brand_id, Scan.status.in_(("queued", "running"))))
        if active:
            raise HTTPException(status_code=409, detail="a scan of this brand is still running")
        for scan in session.scalars(select(Scan).where(Scan.brand_id == brand_id)):
            session.delete(scan)  # cascades to source runs and findings
        session.delete(brand)
        session.flush()
        return None

    @app.delete("/api/scans/{scan_id}", status_code=204)
    def delete_scan(scan_id: str, session: Session = Depends(get_session)):
        """Remove one scan with its source runs and findings.

        The brand and the analyst's reviews stay (they are keyed by brand, not
        by scan). Refused while the scan is queued or running: cancel it first.
        """
        scan = session.get(Scan, scan_id)
        if scan is None:
            raise HTTPException(status_code=404, detail="scan not found")
        if scan.status in ("queued", "running"):
            raise HTTPException(status_code=409, detail="the scan is still running; cancel it first")
        session.delete(scan)  # cascades to source runs and findings
        session.flush()
        return None

    @app.get("/api/brands/{brand_id}/reviews", response_model=list[ReviewOut])
    def list_reviews(brand_id: str, session: Session = Depends(get_session)):
        if session.get(Brand, brand_id) is None:
            raise HTTPException(status_code=404, detail="brand not found")
        return [_review_out(r) for r in scan_service.reviews_for(session, brand_id).values()]

    @app.put("/api/brands/{brand_id}/reviews/{key:path}", response_model=ReviewOut)
    def put_review(brand_id: str, key: str, body: ReviewIn, session: Session = Depends(get_session)):
        """Record an analyst's decision about a finding key; it follows the key
        across future scans of the brand."""
        if session.get(Brand, brand_id) is None:
            raise HTTPException(status_code=404, detail="brand not found")
        if body.status not in REVIEW_STATUSES:
            raise HTTPException(status_code=422, detail=f"status must be one of {REVIEW_STATUSES}")
        return _review_out(scan_service.set_review(session, brand_id, key, body.status, body.note))

    @app.delete("/api/brands/{brand_id}/reviews/{key:path}", status_code=204)
    def delete_review(brand_id: str, key: str, session: Session = Depends(get_session)):
        if not scan_service.clear_review(session, brand_id, key):
            raise HTTPException(status_code=404, detail="review not found")
        return None

    @app.get("/api/scans/{scan_id}/diff", response_model=DiffOut)
    def scan_diff(scan_id: str, against: str | None = None, session: Session = Depends(get_session)):
        """What changed since the previous finished scan of the same brand and
        sources (or since ``against``): new keys, keys that disappeared, keys
        whose category moved."""
        scan = session.get(Scan, scan_id)
        if scan is None:
            raise HTTPException(status_code=404, detail="scan not found")
        prev = session.get(Scan, against) if against else scan_service.previous_scan(session, scan)
        if against and prev is None:
            raise HTTPException(status_code=404, detail="scan to compare against not found")
        d = scan_service.diff_scans(session, scan, prev)
        changed = []
        for f, before in d["changed"]:
            out = _findings_out(session, scan.brand_id, [f])[0]
            out.previous_category = before
            changed.append(out)
        return DiffOut(brand_id=scan.brand_id, scan_id=scan.id, against_id=prev.id if prev else None,
                       new=_findings_out(session, scan.brand_id, d["new"]),
                       gone=_findings_out(session, scan.brand_id, d["gone"]),
                       changed=changed, unchanged=d["unchanged"])

    @app.get("/api/brands/{brand_id}/findings", response_model=FindingPage)
    def brand_findings(brand_id: str, category: str | None = None,
                       limit: int = Query(200, le=1000), offset: int = 0,
                       session: Session = Depends(get_session)):
        """Latest verdict per key across all scans of a brand."""
        if session.get(Brand, brand_id) is None:
            raise HTTPException(status_code=404, detail="brand not found")
        stmt = select(Finding).where(Finding.brand_id == brand_id).order_by(Finding.created_at.desc())
        latest: dict[str, Finding] = {}
        for f in session.scalars(stmt):
            latest.setdefault(f.key, f)
        rows = [f for f in latest.values() if not category or f.category in category.split(",")]
        order = {c.value: i for i, c in enumerate(DISPLAY_ORDER)}
        rows.sort(key=lambda f: (order.get(f.category, 9), f.key))
        return FindingPage(items=_findings_out(session, brand_id, rows[offset:offset + limit]),
                           total=len(rows), limit=limit, offset=offset)

    # ---- frontend -------------------------------------------------------------

    if WEB_DIST.is_dir():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            candidate = WEB_DIST / path
            if path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(WEB_DIST / "index.html")

    return app


app = create_app()
