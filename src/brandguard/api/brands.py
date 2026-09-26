"""Brand rows <-> engine profiles, and the watchlist import.

The registry (brandguard.registry) keeps writing JSON profiles for the CLI;
the product keeps the same profiles in the ``brands`` table so the API can
create and edit them. Import is idempotent: an existing row is only updated
from a profile when the row itself was created automatically. A row an
operator has edited by hand is never overwritten by an import (the same
"user's value wins" rule the registry applies to the CSV).
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from brandguard.api.models import Brand
from brandguard.registry import MANAGED_KEY, slugify
from brandguard.schema import BrandProfile


def to_profile(brand: Brand) -> BrandProfile:
    return BrandProfile(
        brand_name=brand.brand_name,
        official_domains=list(brand.official_domains or []),
        official_publishers=list(brand.official_publishers or []),
        known_official_apps=list(brand.known_official_apps or []),
        sector=brand.sector or "unknown",
        official_package_ids=list(brand.official_package_ids or []),
        official_permissions=list(brand.official_permissions) if brand.official_permissions else None,
        known_affiliates=list(brand.known_affiliates or []),
    )


def from_profile(profile: BrandProfile, *, brand_id: str | None = None,
                 resolved_from: str = "manual", resolution: dict | None = None,
                 review_notes: list[str] | None = None) -> Brand:
    return Brand(
        id=brand_id or slugify(profile.brand_name),
        brand_name=profile.brand_name,
        sector=profile.sector or "unknown",
        official_domains=list(profile.official_domains),
        official_publishers=list(profile.official_publishers),
        official_package_ids=list(profile.official_package_ids),
        known_official_apps=list(profile.known_official_apps),
        known_affiliates=list(profile.known_affiliates),
        official_permissions=profile.official_permissions,
        resolved_from=resolved_from,
        resolution=resolution or {},
        review_notes=review_notes or [],
        needs_review=bool(review_notes),
    )


def find_brand(session: Session, text: str) -> Brand | None:
    """Find a brand by id, exact name, or case-insensitive name."""
    key = text.strip()
    if not key:
        return None
    brand = session.get(Brand, slugify(key))
    if brand is not None:
        return brand
    rows = session.scalars(select(Brand)).all()
    lowered = key.casefold()
    for row in rows:
        if row.brand_name.casefold() == lowered:
            return row
    return None


def find_brand_by_domain(session: Session, host: str) -> Brand | None:
    """Find the brand whose official domains or affiliates cover a host."""
    from brandguard.registry import host_under, normalize_domain

    host = normalize_domain(host)
    if not host:
        return None
    for row in session.scalars(select(Brand)).all():
        if host_under(host, list(row.official_domains or []) + list(row.known_affiliates or [])):
            return row
    return None


def find_brand_by_package(session: Session, package_id: str) -> Brand | None:
    pkg = package_id.strip().lower()
    for row in session.scalars(select(Brand)).all():
        if pkg in {p.lower() for p in (row.official_package_ids or [])}:
            return row
    return None


def import_watchlist(session: Session, directory: Path) -> dict[str, int]:
    """Load every profile JSON in a directory into the brands table.

    Returns counts of created / updated / kept rows. Rows created by hand in
    the product (``resolved_from == "manual"`` and not from a file) are kept.
    """
    created = updated = kept = 0
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        block = data.pop(MANAGED_KEY, None) or {}
        try:
            profile = BrandProfile(**data)
        except Exception:  # noqa: BLE001 - a malformed profile is skipped, not fatal
            continue
        brand_id = path.stem
        resolved_from = "csv" if block else "watchlist"
        resolution = {k: v for k, v in block.items() if k in ("discovery", "enrichment")}
        existing = session.get(Brand, brand_id)
        if existing is None:
            session.add(from_profile(profile, brand_id=brand_id, resolved_from=resolved_from,
                                     resolution=resolution))
            created += 1
        elif existing.resolved_from in ("csv", "watchlist"):
            fresh = from_profile(profile, brand_id=brand_id, resolved_from=resolved_from,
                                 resolution=resolution)
            changed = False
            for field in ("brand_name", "sector", "official_domains", "official_publishers",
                          "official_package_ids", "known_official_apps", "known_affiliates",
                          "official_permissions", "resolution"):
                if getattr(existing, field) != getattr(fresh, field):
                    setattr(existing, field, getattr(fresh, field))
                    changed = True
            if changed:
                updated += 1
            else:
                kept += 1
        else:
            kept += 1
    session.flush()
    return {"created": created, "updated": updated, "kept": kept}
