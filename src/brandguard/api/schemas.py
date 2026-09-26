"""Request and response shapes of the product API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field


def _ensure_utc(value: object) -> object:
    """SQLite stores naive timestamps; every value we write is UTC, so say so.

    Without this the browser would read "15:00" as local time and show the
    scan two or three hours off in Istanbul.
    """
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


UtcDateTime = Annotated[datetime, BeforeValidator(_ensure_utc)]


class ScanRequest(BaseModel):
    input: str | None = Field(default=None, max_length=500,
                              description="Free-form: brand name, domain, package id or store URL")
    brand_name: str | None = Field(default=None, max_length=200)
    domain: str | None = Field(default=None, max_length=200, description="Official domain (trust anchor)")
    store: str | None = Field(default=None, max_length=500,
                              description="Google Play link or package id of the brand's own app")
    sources: list[str] | None = Field(default=None,
                                      description="Subset of play, serper, website, crtsh")
    depth: str = Field(default="normal", description="quick | normal | deep")
    tuning: dict = Field(default_factory=dict, description="Per-source runner overrides")


class SourceRunOut(BaseModel):
    source: str
    status: str
    error: str | None = None
    errors: list[str] = []
    warnings: list[str] = []
    candidates: int = 0
    detected: int = 0
    watch: int = 0
    requests: int = 0
    duration_ms: int = 0
    started_at: UtcDateTime | None = None
    finished_at: UtcDateTime | None = None


class BrandSummary(BaseModel):
    id: str
    brand_name: str
    sector: str
    official_domains: list[str]
    official_publishers: list[str]
    official_package_ids: list[str]
    known_official_apps: list[str]
    known_affiliates: list[str]
    resolved_from: str
    needs_review: bool
    review_notes: list[str] = []
    resolution: dict = {}
    last_scan_at: UtcDateTime | None = None
    scan_count: int = 0
    schedule: str = "off"
    schedule_sources: list[str] = []
    schedule_depth: str = "normal"
    next_run_at: UtcDateTime | None = None


class BrandUpdate(BaseModel):
    brand_name: str | None = None
    sector: str | None = None
    official_domains: list[str] | None = None
    official_publishers: list[str] | None = None
    official_package_ids: list[str] | None = None
    known_official_apps: list[str] | None = None
    known_affiliates: list[str] | None = None
    official_permissions: list[str] | None = None
    review_notes: list[str] | None = None
    needs_review: bool | None = None
    schedule: str | None = None            # off | daily | weekly
    schedule_sources: list[str] | None = None
    schedule_depth: str | None = None


REVIEW_STATUSES = ("false_positive", "confirmed", "takedown_sent", "resolved")


class ReviewIn(BaseModel):
    status: str = Field(description="false_positive | confirmed | takedown_sent | resolved")
    note: str = Field(default="", max_length=2000)


class ReviewOut(BaseModel):
    key: str
    status: str
    note: str = ""
    updated_at: UtcDateTime


class DiffOut(BaseModel):
    brand_id: str
    scan_id: str
    against_id: str | None
    new: list["FindingOut"]
    gone: list["FindingOut"]
    changed: list["FindingOut"]      # same key, different category; current row
    unchanged: int


class ScanOut(BaseModel):
    id: str
    brand: BrandSummary
    input_raw: str
    input_type: str
    resolved_how: str
    sources: list[str]
    depth: str
    tuning: dict
    status: str
    error: str | None = None
    counts: dict
    created_at: UtcDateTime
    started_at: UtcDateTime | None = None
    finished_at: UtcDateTime | None = None
    source_runs: list[SourceRunOut]


class BatchRequest(BaseModel):
    inputs: list[str] = Field(min_length=1, max_length=100,
                              description="One brand name, domain, package id or store URL per item")
    sources: list[str] | None = None
    depth: str = "normal"
    tuning: dict = Field(default_factory=dict)


class BatchError(BaseModel):
    input: str
    error: str


class BatchOut(BaseModel):
    id: str
    created_at: UtcDateTime
    status: str                  # running | done
    scans: list["ScanListItem"]
    errors: list[BatchError] = []
    totals: dict = {}


class ScanListItem(BaseModel):
    id: str
    brand_id: str
    brand_name: str
    input_raw: str
    input_type: str
    sources: list[str]
    depth: str
    status: str
    counts: dict
    created_at: UtcDateTime
    finished_at: UtcDateTime | None = None
    batch_id: str | None = None
    trigger: str = "manual"


class ScanPage(BaseModel):
    items: list[ScanListItem]
    total: int
    limit: int
    offset: int


class EvidenceOut(BaseModel):
    signal: str = ""
    text: str
    weight: float = 0.0
    tier: int = 0


class FindingOut(BaseModel):
    id: str
    scan_id: str
    kind: str
    key: str
    name: str
    source: str
    label: str
    category: str
    confidence: float | None = None
    score: float | None = None
    similarity: float | None = None
    tiers_used: list[int] = []
    reason: str = ""
    priority: str | None = None
    confirmed_live: bool | None = None
    evidence: list[EvidenceOut] = []
    extra: dict = {}
    first_seen_at: UtcDateTime
    created_at: UtcDateTime
    seen_before: bool = False
    link: str | None = None
    review: ReviewOut | None = None
    previous_category: str | None = None   # set by the diff endpoint for changed rows


class FindingPage(BaseModel):
    items: list[FindingOut]
    total: int
    limit: int
    offset: int


class HealthOut(BaseModel):
    status: str
    adjudicator: str
    adjudicator_model: str | None = None
    serper_configured: bool
    play_available: bool
    sources: list[str]
    depths: list[str]
    inflight: int
    version: str
    # current public address of the console when a tunnel sidecar runs
    public_url: str | None = None
