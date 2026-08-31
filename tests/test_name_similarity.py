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


def test_ecosystem_subbrand_name_alone_looks_like_noise():
    # "Örnek Yatırım" shares only the generic token "örnek" with the brand, so on
    # name alone it reads as noise. It is rescued not by its name but by the
    # publisher veto (tested in test_veto). This documents that name similarity
    # correctly refuses to treat a single generic-token overlap as resemblance.
    sim = compare_name("Örnek Yatırım", BRAND)
    assert not sim.contains_brand
    assert sim.brand_token_coverage < 1.0


def test_leading_typosquat_is_recognized_as_starting_with_brand():
    # A distorted second token must not demote a leading brand prefix to a
    # mid-name mention; the evidence an analyst reads depends on this.
    sim = compare_name("Örnek Bankk Mobil", BRAND)
    assert sim.starts_with_brand


def test_mid_name_mention_still_does_not_start():
    sim = compare_name("Kredi Karşılaştır: Örnek Bank, Diğer Bankalar", BRAND)
    assert not sim.starts_with_brand
