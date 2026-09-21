"""Tests for structural domain anatomy."""

from brandguard.discovery.domain_anatomy import analyze_domain


def test_brand_prefix_plus_lure_is_phishing_shape():
    a = analyze_domain("paypal-login.info", "paypal")
    assert a.phishing_shape and "login" in a.lure_words and a.risky_tld


def test_brand_prefix_plus_neutral_is_not_phishing_shape():
    a = analyze_domain("paypal-social.com", "paypal")
    assert not a.phishing_shape and not a.lure_words


def test_lure_word_not_at_brand_prefix_is_not_shape():
    # login present but the domain is not brand-prefixed
    a = analyze_domain("login-portal.com", "paypal")
    assert not a.phishing_shape


def test_risky_tld_detected():
    a = analyze_domain("something.xyz", "paypal")
    assert a.risky_tld
