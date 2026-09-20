"""Tests for the crt.sh source (parsing and token selection, no network)."""

from brandguard.discovery.crtsh_source import _clean, brand_token_of


def test_clean_strips_wildcard_and_case():
    assert _clean("*.paypa1.com") == "paypa1.com"
    assert _clean("  Instagram-Verify.COM ") == "instagram-verify.com"


def test_clean_takes_first_line():
    assert _clean("binance-login.com\nwww.x.com") == "binance-login.com"


def test_brand_token_picks_distinctive_part():
    assert brand_token_of("Ziraat Bankası") == "ziraat"
    assert brand_token_of("Binance") == "binance"


def test_brand_token_skips_generic_words():
    # "bankasi" is generic; the distinctive token should win.
    assert brand_token_of("Ziraat Bankası") != "bankasi"
