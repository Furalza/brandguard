"""T1 tier of the cascade.

T1 runs only for records T0 could not decide (escalate=True). It adds signals
that cost more than T0's string and metadata checks, currently icon similarity,
then re-runs fusion over the combined signal set. Records T0 already decided are
passed through untouched, so the extra cost is spent only where it can change an
outcome.

T1 does not introduce new label logic; it feeds richer evidence into the same
fusion so the decision rule stays in one place. A record still undecided after T1
is passed on for T2 (the LLM adjudicator) to handle.
"""

from __future__ import annotations

from brandguard.schema import AppRecord, BrandProfile
from brandguard.triage.fusion import Decision, _decide_from_signals
from brandguard.triage.icon_similarity import icon_signal
from brandguard.triage.scored_signals import collect_signals


def triage_t1(
    record: AppRecord,
    profile: BrandProfile,
    t0: Decision,
    official_icon: str | None = None,
) -> Decision:
    """Refine an undecided T0 decision with T1 signals.

    ``official_icon`` is the path to the brand's official icon, supplied by the
    caller (the pipeline), since it belongs to the brand, not the record.
    """
    if not t0.escalate:
        return t0  # already decided at T0; do not spend T1 cost

    signals = collect_signals(record, profile)
    icon = icon_signal(record.icon_path, official_icon)
    if icon is not None:
        signals = [*signals, icon]

    decision = _decide_from_signals(record, profile, signals, tier=1)
    return decision
