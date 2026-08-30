"""Tests for name normalization.

The key property is symmetry: attacker variants and legitimate store variants
of the same brand must collapse to the same canonical form.
"""

from brandguard.discovery.normalize import normalize, skeleton, tokens

BRAND = "Örnek Bank"
CANON = "ornek bank"


def test_official_name_normalizes():
    assert normalize("Örnek Bank") == CANON


def test_turkish_flattening_matches_official():
    # A store that dropped Turkish characters must map to the same form.
    assert normalize("Ornek Bank") == CANON


def test_cyrillic_homoglyph_collapses_to_brand():
    # Leading Cyrillic O (U+041E).
    assert normalize("\u041ernek Bank") == CANON


def test_cyrillic_e_homoglyph_collapses():
    # Cyrillic e (U+0435) in the third position.
    assert normalize("\u00d6rn\u0435k Bank") == CANON


def test_zero_width_character_is_removed():
    assert normalize("Örnek\u200b Bank") == CANON


def test_spacing_and_punctuation_regularized():
    assert normalize("Örnek-Bank") == CANON
    assert normalize("Örnek  Bank") == CANON
    assert normalize("ÖrnekBank") == "ornekbank"


def test_skeleton_ignores_whitespace():
    assert skeleton("Örnek Bank") == "ornekbank"
    assert skeleton("\u041ernek Bank") == "ornekbank"


def test_typosquat_does_not_falsely_collapse():
    # A doubled letter is a real difference; normalization must not hide it.
    assert normalize("Örnek Bankk") != CANON


def test_tokens():
    assert tokens("Örnek Bank Mobil") == ["ornek", "bank", "mobil"]
    assert tokens("") == []
