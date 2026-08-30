"""Signal interface for triage.

Every signal inspects an ``AppRecord`` against a ``BrandProfile`` and returns a
uniform ``SignalResult``: a direction, a strength, and a human-readable evidence
line. Keeping the shape uniform lets the fusion layer treat all signals the same
way and lets every score turn into an audit line for the analyst.

Direction encodes what the signal argues for, not a final label. A signal can
point toward impersonation, toward legitimacy, or act as a veto that ends the
decision. Fusion, not the individual signal, produces the label.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from brandguard.schema import Evidence, Label


class Direction(str, Enum):
    """What a signal argues for."""

    SUSPICIOUS = "suspicious"        # raises impersonation/repackaged likelihood
    LEGITIMATE = "legitimate"        # lowers it
    NEUTRAL = "neutral"              # observed but not decisive
    VETO = "veto"                    # forces a label, overriding other signals


@dataclass(frozen=True)
class SignalResult:
    """The uniform output of one signal.

    ``strength`` is a 0..1 magnitude of how strongly the signal argues in its
    direction. For a veto, ``forced_label`` names the label it imposes.
    """

    name: str
    direction: Direction
    strength: float
    text: str
    tier: int = 0
    forced_label: Label | None = None
    meta: dict = field(default_factory=dict)

    def as_evidence(self) -> Evidence:
        """Render this signal as an analyst-facing evidence line."""
        signed = self.strength if self.direction == Direction.SUSPICIOUS else -self.strength
        if self.direction in (Direction.NEUTRAL, Direction.VETO):
            signed = self.strength
        return Evidence(signal=self.name, text=self.text, weight=round(signed, 3), tier=self.tier)
