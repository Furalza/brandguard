"""Loading and validation of the labelled evaluation set.

The set lives in ``data/testset/<brand>.json`` as a list of labelled records.
Layer and label vocabularies are validated at load time so a typo in the data
fails early instead of silently skewing metrics.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, field_validator

from brandguard.schema import AppRecord, Label

LAYERS = {
    "L1": "official",
    "L2": "ecosystem",
    "L3": "obvious_impersonation",
    "L4": "homoglyph",
    "L5": "typosquat",
    "L6": "semantic",
    "L7": "repackaged",
    "L8": "third_party",
    "L9": "noise",
    "L10": "ambiguous",
    "L11": "injection",
}


class LabelledRecord(BaseModel):
    """One evaluation example: the record, its gold label and why."""

    record: AppRecord
    label: Label
    layer: str
    rationale: str

    @field_validator("layer")
    @classmethod
    def _known_layer(cls, value: str) -> str:
        if value not in LAYERS:
            raise ValueError(f"unknown layer {value!r}, expected one of {sorted(LAYERS)}")
        return value


def load_testset(path: Path) -> list[LabelledRecord]:
    """Load one brand's labelled records from a JSON file."""
    with path.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    return [LabelledRecord(**item) for item in raw]


def layer_counts(records: list[LabelledRecord]) -> dict[str, int]:
    """Return the number of records per layer, for reporting set composition."""
    return dict(sorted(Counter(r.layer for r in records).items()))
