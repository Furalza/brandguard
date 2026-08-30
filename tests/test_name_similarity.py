"""Tests for the multi-dimensional name similarity signal."""

from brandguard.discovery.name_similarity import compare_name

BRAND = "Örnek Bank"


def test_exact_brand_with_suffix_is_high_and_starts():
    sim = compare_name("Örnek Bank Mobil", BRAND)
    assert sim.jaro_winkler > 0.85
    assert sim.starts_with_brand
    assert sim.contains_brand
    assert not sim.exact_skeleton  # has an extra token


def test_homoglyph_is_exact_skeleton():
    # Cyrillic e in "Örnеk Bank" is the exact brand visually.
    sim = compare_name("Örn\u0435k Bank", BRAND)
    assert sim.exact_skeleton
    assert sim.jaro_winkler > 0.95


def test_turkish_flattening_is_exact_skeleton():
    sim = compare_name("Ornek Bank", BRAND)
    assert sim.exact_skeleton


def test_typosquat_high_similarity_not_exact():
    sim = compare_name("Örnek Bankk", BRAND)
    assert sim.jaro_winkler > 0.85
    assert not sim.exact_skeleton


def test_third_party_mid_mention_does_not_start_with_brand():
    sim = compare_name("Kredi Karşılaştır: Örnek Bank, Diğer Bankalar", BRAND)
    assert sim.contains_brand
    assert not sim.starts_with_brand
    assert sim.jaro_winkler < 0.70


def test_unrelated_is_noise():
    assert compare_name("Hesap Topla", BRAND).is_noise
    assert compare_name("Bankamatik Rehberi", BRAND).is_noise


def test_ecosystem_subbrand_is_not_noise_but_does_not_contain_brand():
    # "Örnek Yatırım" shares only the first token; still worth keeping for the
    # publisher check, so it must not be filtered as noise.
    sim = compare_name("Örnek Yatırım", BRAND)
    assert not sim.is_noise
    assert not sim.contains_brand
