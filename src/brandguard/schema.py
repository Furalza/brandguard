"""Normalized data model shared by discovery, triage and evaluation.

Every marketplace adapter converts its source-specific payload into
``AppRecord``. Triage never sees raw source data, which keeps the scoring
logic independent of how many sources exist or how their schemas change.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class Label(str, Enum):
    """Classification labels as defined in the task brief."""

    OFFICIAL = "official"
    IMPERSONATION = "impersonation"
    REPACKAGED = "repackaged"
    THIRD_PARTY = "third_party_legitimate"
    UNRELATED = "unrelated"
    UNCERTAIN = "uncertain"


class BrandProfile(BaseModel):
    """Input describing the brand to protect.

    The first five fields mirror the brief. The optional fields improve
    repackaging and permission-drift detection, and let the customer allowlist
    known affiliates, when they can supply them.
    """

    brand_name: str
    official_domains: list[str]
    official_publishers: list[str]
    known_official_apps: list[str]
    sector: str
    official_package_ids: list[str] = Field(default_factory=list)
    official_permissions: list[str] | None = None
    # Vetted legitimate domains (subsidiaries, regional entities) an analyst has
    # cleared: treated as official, not impersonations, so they leave the
    # detected queue. Optional; a profile without it behaves as before.
    known_affiliates: list[str] = Field(default_factory=list)
    # How many publishers other than the brand lead their app names with the
    # brand word on Google Play, measured in this scan's Play run and handed to
    # the APK-site run (K-071/K-075). None = not measured.
    brand_word_shared_by: int | None = None


class Publisher(BaseModel):
    """Publisher-level signals. See THREAT_MODEL.md section 2 for trust levels."""

    name: str
    account_created: date | None = None
    other_app_count: int | None = None
    website: str | None = None
    email_domain: str | None = None
    verified: bool | None = None
    # The store's own identifier for the publisher account (Google Play's
    # developerId). Unlike the display name, nobody but the account owner can
    # publish under it, so two listings sharing it are the same publisher (K-062).
    account_id: str | None = None


class AppRecord(BaseModel):
    """A single marketplace listing after normalization.

    ``None`` means the source did not provide the field. It is distinct from
    zero or empty, which are real observed values. Scoring code must treat
    a missing signal as absent, not as negative.
    """

    app_id: str
    source: str
    name: str
    publisher: Publisher
    description: str | None = None
    icon_url: str | None = None
    icon_path: str | None = None
    permissions: list[str] = Field(default_factory=list)
    downloads: int | None = None
    rating: float | None = None
    review_count: int | None = None
    published: date | None = None
    last_updated: date | None = None
    version: str | None = None
    raw: dict = Field(default_factory=dict)


class Evidence(BaseModel):
    """One auditable finding produced by a signal.

    ``text`` is what the analyst reads. ``signal``, ``weight`` and ``tier``
    are kept for error analysis and cost reporting.
    """

    signal: str
    text: str
    weight: float
    tier: int


class Verdict(BaseModel):
    """Final decision for one record, plus internal fields used by evaluation."""

    app_id: str
    source: str
    label: Label
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[Evidence]
    score: float = 0.0
    tiers_used: list[int] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)

    def to_analyst_json(self) -> dict:
        """Return the output shape required by the brief, without internal fields."""
        return {
            "app_id": self.app_id,
            "source": self.source,
            "label": self.label.value,
            "confidence": round(self.confidence, 2),
            "evidence": [e.text for e in self.evidence],
        }
