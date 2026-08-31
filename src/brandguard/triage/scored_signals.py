"""Scored T0 signals.

These run only when no veto fired. Each returns a ``SignalResult`` with a
direction and a strength, plus an evidence line. None of them decides a label
alone; fusion weighs them together. Signals return ``None`` when the data they
need is absent, so a missing field never masquerades as a negative finding.

The permission signal is sector-aware: a bank app reading SMS is a strong red
flag, a courier app reading SMS is routine (delivery codes). The expected-by-
sector baseline keeps the signal from firing false positives across sectors.
"""

from __future__ import annotations

from datetime import UTC, datetime

from brandguard.discovery.name_similarity import compare_name
from brandguard.schema import AppRecord, BrandProfile
from brandguard.triage.signals import Direction, SignalResult

# Permissions that are sensitive in general and, for finance, unexpected.
_SENSITIVE_PERMISSIONS = {
    "READ_SMS", "RECEIVE_SMS", "READ_CONTACTS", "SYSTEM_ALERT_WINDOW",
    "REQUEST_INSTALL_PACKAGES", "ACCESSIBILITY_SERVICE", "BIND_ACCESSIBILITY_SERVICE",
}

# Permissions that are routine for a sector and must not count as drift there.
_SECTOR_EXPECTED: dict[str, set[str]] = {
    "logistics": {"RECEIVE_SMS", "READ_SMS", "ACCESS_FINE_LOCATION", "ACCESS_BACKGROUND_LOCATION", "CAMERA"},
    "banking": {"USE_BIOMETRIC", "CAMERA", "ACCESS_FINE_LOCATION"},
    "crypto": {"USE_BIOMETRIC", "CAMERA", "INTERNET"},
}

_YOUNG_ACCOUNT_DAYS = 180
_ESTABLISHED_ACCOUNT_DAYS = 365 * 3
_TODAY = datetime.now(tz=UTC).date()


def name_signal(record: AppRecord, profile: BrandProfile) -> SignalResult | None:
    """Similarity of the app name to the brand, as a scored signal.

    High similarity raises suspicion but does not decide; an exact-brand name is
    equally consistent with an official app (which a veto would have caught) and
    an impersonation (which reaches here).
    """
    sim = compare_name(record.name, profile.brand_name)
    if sim.is_noise:
        return SignalResult(
            name="name_similarity",
            direction=Direction.LEGITIMATE,
            strength=0.2,
            text=f"App name '{record.name}' does not resemble the brand.",
            meta={"jaro_winkler": sim.jaro_winkler},
        )
    if sim.exact_skeleton:
        return SignalResult(
            name="name_similarity",
            direction=Direction.SUSPICIOUS,
            strength=0.6,
            text=f"App name '{record.name}' is visually identical to the brand name.",
            meta={"exact_skeleton": True},
        )
    if sim.starts_with_brand:
        return SignalResult(
            name="name_similarity",
            direction=Direction.SUSPICIOUS,
            strength=0.45,
            text=f"App name '{record.name}' begins with the brand name.",
            meta={"jaro_winkler": sim.jaro_winkler},
        )
    if sim.contains_brand:
        return SignalResult(
            name="name_similarity",
            direction=Direction.NEUTRAL,
            strength=0.3,
            text=f"App name '{record.name}' mentions the brand but does not lead with it.",
            meta={"jaro_winkler": sim.jaro_winkler},
        )
    return SignalResult(
        name="name_similarity",
        direction=Direction.SUSPICIOUS,
        strength=round(sim.jaro_winkler * 0.5, 3),
        text=f"App name '{record.name}' is similar to the brand (jw={sim.jaro_winkler}).",
        meta={"jaro_winkler": sim.jaro_winkler},
    )


def account_age_signal(record: AppRecord, profile: BrandProfile) -> SignalResult | None:
    """Publisher account age, graded rather than binary.

    Very young accounts are strongly suspicious. Genuinely old accounts are
    weakly legitimate. The middle (months, not years) is neutral: not fresh, but
    not evidence of an established publisher either, so it neither accuses nor
    exonerates.
    """
    created = record.publisher.account_created
    if created is None:
        return None
    age_days = (_TODAY - created).days
    if age_days <= _YOUNG_ACCOUNT_DAYS:
        return SignalResult(
            name="account_age",
            direction=Direction.SUSPICIOUS,
            strength=0.7,
            text=f"Publisher account was created {age_days} days ago.",
            meta={"age_days": age_days},
        )
    if age_days >= _ESTABLISHED_ACCOUNT_DAYS:
        return SignalResult(
            name="account_age",
            direction=Direction.LEGITIMATE,
            strength=0.4,
            text=f"Publisher account is {age_days // 365} years old.",
            meta={"age_days": age_days},
        )
    return SignalResult(
        name="account_age",
        direction=Direction.NEUTRAL,
        strength=0.2,
        text=f"Publisher account is {age_days // 30} months old.",
        meta={"age_days": age_days},
    )


def solo_publisher_signal(record: AppRecord, profile: BrandProfile) -> SignalResult | None:
    """A publisher with a single app is weakly suspicious on its own."""
    count = record.publisher.other_app_count
    if count is None:
        return None
    if count <= 1:
        return SignalResult(
            name="solo_publisher",
            direction=Direction.SUSPICIOUS,
            strength=0.35,
            text="Publisher has no other apps.",
            meta={"other_app_count": count},
        )
    return None


def permission_signal(record: AppRecord, profile: BrandProfile) -> SignalResult | None:
    """Permissions that are sensitive and not expected for this sector.

    Uses the profile's official permission set when available; otherwise falls
    back to a sector baseline. When neither is available the signal abstains.
    """
    if not record.permissions:
        return None

    expected: set[str] = set()
    if profile.official_permissions:
        expected |= {p.upper() for p in profile.official_permissions}
    expected |= _SECTOR_EXPECTED.get(profile.sector, set())
    if not expected:
        return None  # no baseline to judge against; abstain rather than guess

    flagged = [p for p in record.permissions if p in _SENSITIVE_PERMISSIONS and p not in expected]
    if not flagged:
        return None
    # When the official permission set is known, drift is a strong signal. When
    # we only have a sector baseline, we cannot be sure a permission is truly
    # unexpected, so the signal is weaker and cannot by itself cross a threshold.
    have_official = bool(profile.official_permissions)
    base = 0.4 if have_official else 0.25
    step = 0.15 if have_official else 0.1
    cap = 0.85 if have_official else 0.5
    strength = min(base + step * len(flagged), cap)
    confidence_note = "" if have_official else " (no official permission baseline; treated as a weak signal)"
    return SignalResult(
        name="permission_drift",
        direction=Direction.SUSPICIOUS,
        strength=round(strength, 3),
        text=(
            f"Requests sensitive permissions not expected for a {profile.sector} app: "
            f"{', '.join(flagged)}{confidence_note}."
        ),
        meta={"flagged": flagged, "have_official_baseline": have_official},
    )


SCORED_SIGNALS = (
    name_signal,
    account_age_signal,
    solo_publisher_signal,
    permission_signal,
)


def collect_signals(record: AppRecord, profile: BrandProfile) -> list[SignalResult]:
    """Run all scored signals and return those that fired."""
    results = []
    for signal in SCORED_SIGNALS:
        result = signal(record, profile)
        if result is not None:
            results.append(result)
    return results
