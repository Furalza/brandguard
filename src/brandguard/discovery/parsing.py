"""Shared parsing helpers for source adapters.

Every marketplace expresses the same fact differently: downloads as "1,000+",
"1K", or an integer; dates as ISO strings, epoch seconds, or "2 weeks ago".
These helpers centralize the conversions so each adapter only maps field names,
not value formats. They fail soft: an unparseable value becomes ``None`` (the
signal is absent) rather than raising, because one malformed field must not drop
an otherwise useful record. Absence is a valid state; see the None discipline in
schema.py.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

_DOWNLOAD_SUFFIX = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}


def parse_downloads(value: object) -> int | None:
    """Normalize a downloads figure to an integer, or None if unknown.

    Handles ints, "1,000+", "1K", "2.5M", "1 000". Returns None for anything
    that does not clearly denote a count, keeping missing distinct from zero.
    """
    if value is None:
        return None
    if isinstance(value, bool):  # guard: bool is an int subclass
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if not isinstance(value, str):
        return None

    text = value.strip().lower().replace(",", "").replace(" ", "").rstrip("+")
    if not text:
        return None

    match = re.fullmatch(r"(\d+(?:\.\d+)?)([kmb]?)", text)
    if not match:
        return None
    number, suffix = match.groups()
    scaled = float(number) * _DOWNLOAD_SUFFIX.get(suffix, 1)
    return int(scaled)


def parse_date(value: object) -> date | None:
    """Normalize a date to ``date``, or None if unknown.

    Handles date/datetime objects, ISO strings, and epoch seconds. Relative
    strings ("2 weeks ago") are intentionally not guessed; they return None so a
    fabricated date never becomes evidence.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=UTC).date()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def split_permissions(value: object) -> list[str]:
    """Normalize a permissions field to a list of uppercase permission names.

    Accepts a list, a comma or semicolon separated string, or None. Android
    permission prefixes (android.permission.) are stripped for comparison.
    """
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r"[;,]", value)
    elif isinstance(value, (list, tuple)):
        parts = [str(p) for p in value]
    else:
        return []

    out: list[str] = []
    for part in parts:
        name = part.strip().upper().rsplit(".", 1)[-1]
        if name:
            out.append(name)
    return out
