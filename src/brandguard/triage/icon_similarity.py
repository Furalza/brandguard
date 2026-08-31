"""Icon similarity signal (T1).

Compares a candidate's icon against the brand's official icon using a perceptual
hash. Unlike a cryptographic hash, a perceptual hash changes gradually with the
image, so visually similar icons produce hashes a small Hamming distance apart.

This is a T1 signal: it runs only for records T0 left undecided and that have an
icon available, because fetching and hashing an image costs more than the string
and metadata checks in T0. Running it on every record would waste the budget the
cascade exists to protect.

Design notes and limits:
- pHash is structure-sensitive and colour-insensitive: a copy that keeps the
  layout but recolours the logo is still caught; a pure colour swap may not be.
  Recorded as a known limitation.
- Icon similarity is supporting evidence, never a veto. An icon is attacker-
  controllable (they can copy the real one), so on its own it cannot decide a
  label; it strengthens or weakens a decision alongside other signals.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import imagehash
from PIL import Image

from brandguard.triage.signals import Direction, SignalResult

# Hamming distance thresholds on a 64-bit pHash. Distances were validated on
# synthetic icons: near-identical layouts sit near 0, unrelated icons above ~20.
_IDENTICAL_MAX = 6      # effectively the same image
_SIMILAR_MAX = 12       # visually close, likely a copy
_HASH_BITS = 64


@dataclass(frozen=True)
class IconComparison:
    """Result of comparing two icons."""

    distance: int
    similarity: float      # 1.0 at distance 0, 0.0 at max distance


def _phash(path: str | Path) -> imagehash.ImageHash:
    with Image.open(path) as img:
        return imagehash.phash(img)


def compare_icons(candidate_icon: str | Path, official_icon: str | Path) -> IconComparison:
    """Compare a candidate icon against the official icon by perceptual hash."""
    distance = _phash(candidate_icon) - _phash(official_icon)
    similarity = round(1.0 - distance / _HASH_BITS, 3)
    return IconComparison(distance=distance, similarity=similarity)


def icon_signal(
    candidate_icon: str | Path | None,
    official_icon: str | Path | None,
) -> SignalResult | None:
    """Return an icon-similarity signal, or None when it cannot be computed.

    The signal abstains (returns None) when either icon is missing, rather than
    treating absence as evidence.
    """
    if not candidate_icon or not official_icon:
        return None
    try:
        cmp = compare_icons(candidate_icon, official_icon)
    except (FileNotFoundError, OSError):
        return None

    if cmp.distance <= _IDENTICAL_MAX:
        return SignalResult(
            name="icon_similarity",
            direction=Direction.SUSPICIOUS,
            strength=0.6,
            text=f"Icon is visually identical to the official icon (distance {cmp.distance}).",
            tier=1,
            meta={"distance": cmp.distance},
        )
    if cmp.distance <= _SIMILAR_MAX:
        return SignalResult(
            name="icon_similarity",
            direction=Direction.SUSPICIOUS,
            strength=0.4,
            text=f"Icon closely resembles the official icon (distance {cmp.distance}).",
            tier=1,
            meta={"distance": cmp.distance},
        )
    return SignalResult(
        name="icon_similarity",
        direction=Direction.LEGITIMATE,
        strength=0.2,
        text=f"Icon does not resemble the official icon (distance {cmp.distance}).",
        tier=1,
        meta={"distance": cmp.distance},
    )
