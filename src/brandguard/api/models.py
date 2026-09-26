"""Product tables.

brands        the profiles the engine scans against (the DB form of the
              registry's JSON profiles; user-edited fields win over automatic ones)
scans         one operator request: an input, the sources asked for, a status
scan_sources  one row per (scan, source): where a partial failure is recorded
findings      one row per candidate app or domain, with the engine's verdict,
              the operator category and the evidence the details view shows

``first_seen_at`` on findings carries the earliest time this brand+key was
ever seen, across scans. Nothing uses it today; notifications and "what
changed since last week" will, and it costs nothing to keep from the start.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from brandguard.api.db import Base


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _uuid() -> str:
    return uuid.uuid4().hex


class Brand(Base):
    __tablename__ = "brands"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)     # slug
    brand_name: Mapped[str] = mapped_column(String(200), nullable=False)
    sector: Mapped[str] = mapped_column(String(64), default="unknown")
    official_domains: Mapped[list] = mapped_column(JSON, default=list)
    official_publishers: Mapped[list] = mapped_column(JSON, default=list)
    official_package_ids: Mapped[list] = mapped_column(JSON, default=list)
    known_official_apps: Mapped[list] = mapped_column(JSON, default=list)
    known_affiliates: Mapped[list] = mapped_column(JSON, default=list)
    official_permissions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # csv | watchlist | manual | auto  (how the profile came to exist)
    resolved_from: Mapped[str] = mapped_column(String(32), default="manual")
    # audit trail of automatic resolution: discovery / enrichment evidence
    resolution: Mapped[dict] = mapped_column(JSON, default=dict)
    review_notes: Mapped[list] = mapped_column(JSON, default=list)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now,
                                                 onupdate=_now)
    # Scheduled re-scans: off | daily | weekly. The scheduler thread starts a
    # scan when next_run_at has passed and advances it by the interval.
    schedule: Mapped[str] = mapped_column(String(16), default="off")
    schedule_sources: Mapped[list] = mapped_column(JSON, default=list)
    schedule_depth: Mapped[str] = mapped_column(String(16), default="normal")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    scans: Mapped[list[Scan]] = relationship(back_populates="brand")
    reviews: Mapped[list[Review]] = relationship(back_populates="brand",
                                                 cascade="all, delete-orphan")


class Scan(Base):
    __tablename__ = "scans"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id"), index=True)
    input_raw: Mapped[str] = mapped_column(String(500))
    input_type: Mapped[str] = mapped_column(String(32))          # brand | domain | package | url
    resolved_how: Mapped[str] = mapped_column(String(64), default="")
    sources: Mapped[list] = mapped_column(JSON, default=list)
    depth: Mapped[str] = mapped_column(String(16), default="normal")
    tuning: Mapped[dict] = mapped_column(JSON, default=dict)
    # queued | running | done | partial | failed
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    # Scans started together from one multi-line input share a batch id.
    batch_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # manual | schedule: who started it
    trigger: Mapped[str] = mapped_column(String(16), default="manual")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    brand: Mapped[Brand] = relationship(back_populates="scans")
    source_runs: Mapped[list[ScanSource]] = relationship(back_populates="scan",
                                                         cascade="all, delete-orphan")
    findings: Mapped[list[Finding]] = relationship(back_populates="scan",
                                                   cascade="all, delete-orphan")


class ScanSource(Base):
    __tablename__ = "scan_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scans.id"), index=True)
    source: Mapped[str] = mapped_column(String(32))
    # queued | running | done | failed
    status: Mapped[str] = mapped_column(String(16), default="queued")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    errors: Mapped[list] = mapped_column(JSON, default=list)      # per-query, non-fatal
    warnings: Mapped[list] = mapped_column(JSON, default=list)    # health hints
    candidates: Mapped[int] = mapped_column(Integer, default=0)
    detected: Mapped[int] = mapped_column(Integer, default=0)
    watch: Mapped[int] = mapped_column(Integer, default=0)
    requests: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    scan: Mapped[Scan] = relationship(back_populates="source_runs")


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scans.id"), index=True)
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id"), index=True)
    kind: Mapped[str] = mapped_column(String(8))                 # app | domain
    key: Mapped[str] = mapped_column(String(600), index=True)    # app_id or domain
    name: Mapped[str] = mapped_column(String(400), default="")
    source: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(32))               # engine label / domain verdict
    category: Mapped[str] = mapped_column(String(16), index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    tiers_used: Mapped[list] = mapped_column(JSON, default=list)
    reason: Mapped[str] = mapped_column(String(64), default="")
    priority: Mapped[str | None] = mapped_column(String(16), nullable=True)
    confirmed_live: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    evidence: Mapped[list] = mapped_column(JSON, default=list)   # [{signal,text,weight,tier}]
    extra: Mapped[dict] = mapped_column(JSON, default=dict)      # domain ages, page kind, ...
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    scan: Mapped[Scan] = relationship(back_populates="findings")


class Review(Base):
    """An analyst's decision about one finding key of a brand.

    Keyed by (brand, key) rather than by finding row, so the decision follows
    the app or domain across scans: a false positive marked today is still a
    false positive when tomorrow's scan finds the same package id.
    """

    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id"), index=True)
    key: Mapped[str] = mapped_column(String(600), index=True)
    # false_positive | confirmed | takedown_sent | resolved
    status: Mapped[str] = mapped_column(String(24))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now,
                                                 onupdate=_now)

    brand: Mapped[Brand] = relationship(back_populates="reviews")


class Batch(Base):
    """A multi-brand submission. Holds what the scans cannot: the lines that
    never became a scan (a store field that was a domain, a platform domain),
    so the batch page and the ZIP show them after the page is reloaded."""

    __tablename__ = "batches"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    errors: Mapped[list] = mapped_column(JSON, default=list)   # [{input, error}]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
