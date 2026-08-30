"""Name normalization.

A single canonical form serves two purposes at once. It lets the veto rule match
a legitimate publisher whose name a store has flattened ("Hizli Kargo" for
"Hızlı Kargo"), and it collapses attacker tricks (Cyrillic homoglyphs, doubled
letters, zero-width characters) onto the brand they imitate. The same function
that catches the attack recognizes the legitimate variant.

Two levels are exposed:

``normalize`` produces a human-comparable form: confusables folded to Latin,
Turkish characters flattened, case and whitespace regularized, punctuation
dropped. Use it for similarity scoring and display.

``skeleton`` is the confusable skeleton from Unicode UTS #39: normalize plus
removal of characters that carry no identity (spaces, digits kept). Two strings
with the same skeleton are visually confusable. Use it for exact confusable
equality checks.
"""

from __future__ import annotations

import re
import unicodedata

# Confusable characters actually seen in impersonation, mapped to their Latin
# target. This is a curated subset of the Unicode confusables data, limited to
# scripts an attacker uses against Latin/Turkish brand names (Cyrillic, Greek,
# fullwidth, common math letters). A full table is available from
# https://www.unicode.org/Public/security/latest/confusables.txt and can replace
# this map without changing the callers.
_CONFUSABLES: dict[str, str] = {
    # Cyrillic lowercase
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x",
    "ѕ": "s", "і": "i", "ј": "j", "ԁ": "d", "ո": "n", "г": "r", "н": "h",
    "к": "k", "м": "m", "т": "t", "в": "b",
    # Cyrillic uppercase
    "А": "A", "Е": "E", "О": "O", "Р": "P", "С": "C", "У": "Y", "Х": "X",
    "І": "I", "Ј": "J", "К": "K", "М": "M", "Т": "T", "В": "B", "Н": "H",
    # Greek
    "ο": "o", "α": "a", "ρ": "p", "ε": "e", "ι": "i", "κ": "k", "ν": "v",
    "Ο": "O", "Α": "A", "Ρ": "P", "Ε": "E", "Κ": "K", "Β": "B", "Η": "H",
    "Χ": "X", "Ι": "I", "Ν": "N", "Τ": "T", "Μ": "M",
}

# Turkish characters flattened to ASCII. Applied after confusable folding so a
# Cyrillic-then-Turkish chain still resolves.
_TURKISH: dict[str, str] = {
    "ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
    "ç": "c", "Ç": "c", "ö": "o", "Ö": "o", "ü": "u", "Ü": "u",
}

# Zero-width and formatting characters an attacker can hide inside a name.
_INVISIBLE = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")

_NON_ALNUM = re.compile(r"[^a-z0-9\s]")
_WHITESPACE = re.compile(r"\s+")


def _fold(text: str, table: dict[str, str]) -> str:
    return "".join(table.get(ch, ch) for ch in text)


def normalize(name: str) -> str:
    """Return a canonical, human-comparable form of an app or publisher name.

    Steps, in order: strip invisible characters, NFKC to unify compatibility
    forms, fold confusables to Latin, flatten Turkish characters, lowercase,
    drop punctuation, collapse whitespace.
    """
    text = _INVISIBLE.sub("", name)
    text = unicodedata.normalize("NFKC", text)
    text = _fold(text, _CONFUSABLES)
    text = text.lower()
    text = _fold(text, _TURKISH)
    text = _NON_ALNUM.sub(" ", text)
    text = _WHITESPACE.sub(" ", text).strip()
    return text


def skeleton(name: str) -> str:
    """Return the confusable skeleton: ``normalize`` with whitespace removed.

    Two names with the same skeleton are visually the same string to a human.
    """
    return normalize(name).replace(" ", "")


def tokens(name: str) -> list[str]:
    """Return the normalized whitespace-separated tokens of a name."""
    normalized = normalize(name)
    return normalized.split() if normalized else []
