"""Tests for domain variant generation and website (domain) triage."""

from brandguard.discovery.domain_variants import expand_domain
from brandguard.discovery.website_hunt import (
    DomainVerdict,
    classify_domain,
    hunt_websites,
)


class MockSerper:
    def __init__(self, results=None):
        self._results = results or []

    def search(self, query, num):
        return self._results


OFFICIAL = ["ziraatbank.com.tr"]
BRAND = "Ziraat Bankası"


def test_expand_domain_covers_strategies():
    strategies = {v.strategy for v in expand_domain("ziraatbank.com.tr")}
    assert {"typosquat", "leet", "lure_word", "alt_tld"} <= strategies


def test_official_domain_is_official():
    assert classify_domain("ziraatbank.com.tr", OFFICIAL, BRAND).verdict == DomainVerdict.OFFICIAL


def test_alt_tld_is_lookalike():
    assert classify_domain("ziraatbank.com", OFFICIAL, BRAND).verdict == DomainVerdict.LOOKALIKE


def test_lure_word_is_lookalike():
    assert classify_domain("ziraatbank-giris.com", OFFICIAL, BRAND).verdict == DomainVerdict.LOOKALIKE


def test_leet_variant_is_lookalike():
    # z1raatbank must still be recognized as carrying the brand token.
    assert classify_domain("z1raatbank.com.tr", OFFICIAL, BRAND).verdict == DomainVerdict.LOOKALIKE


def test_rival_bank_is_not_lookalike():
    # A different bank shares "bank" but is not a Ziraat lookalike.
    assert classify_domain("garantibbva.com.tr", OFFICIAL, BRAND).verdict == DomainVerdict.UNRELATED


def test_unrelated_domain():
    assert classify_domain("example.com", OFFICIAL, BRAND).verdict == DomainVerdict.UNRELATED


def test_generated_variants_are_not_confirmed_live():
    findings = hunt_websites(BRAND, OFFICIAL, client=MockSerper())
    assert findings
    assert all(not f.confirmed_live for f in findings)


def test_search_hit_is_confirmed_live():
    hit = [{"title": "x", "link": "https://ziraatbank-giris.com/login"}]
    findings = hunt_websites(BRAND, OFFICIAL, client=MockSerper(hit),
                             include_generated_variants=False)
    live = [f for f in findings if f.confirmed_live]
    assert live and live[0].domain == "ziraatbank-giris.com"


def test_subdomain_of_official_is_not_impersonation():
    # api.paypal.com is PayPal's own infrastructure, not a lookalike.
    from brandguard.discovery.website_hunt import DomainVerdict, classify_domain
    f = classify_domain("api.paypal.com", ["paypal.com"], "PayPal")
    assert f.verdict == DomainVerdict.OFFICIAL


def test_non_domain_string_is_rejected():
    # crt.sh sometimes returns an org name like "paypal, inc." in the name field.
    from brandguard.discovery.website_hunt import DomainVerdict, classify_domain
    f = classify_domain("paypal, inc.", ["paypal.com"], "PayPal")
    assert f.verdict == DomainVerdict.UNRELATED


def test_real_phishing_shape_is_lookalike():
    from brandguard.discovery.website_hunt import DomainVerdict, classify_domain
    f = classify_domain("paypal-login.info", ["paypal.com"], "PayPal")
    assert f.verdict == DomainVerdict.LOOKALIKE


def test_brand_prefixed_lure_word_is_lookalike():
    # paypal-login.info: brand-prefixed + credential-bait word on a risky TLD.
    from brandguard.discovery.website_hunt import DomainVerdict, classify_domain
    f = classify_domain("paypal-login.info", ["paypal.com"], "PayPal")
    assert f.verdict == DomainVerdict.LOOKALIKE


def test_brand_prefixed_neutral_word_is_mention():
    # paypalobjects.com is PayPal's real CDN; brand + neutral word, no lure.
    from brandguard.discovery.website_hunt import DomainVerdict, classify_domain
    f = classify_domain("paypalobjects.com", ["paypal.com"], "PayPal")
    assert f.verdict == DomainVerdict.MENTIONS_BRAND


def test_brand_plus_extra_word_is_not_typosquat():
    # paypal-social.com: brand + neutral word is a mention, not a lookalike.
    from brandguard.discovery.website_hunt import DomainVerdict, classify_domain
    f = classify_domain("paypal-social.com", ["paypal.com"], "PayPal")
    assert f.verdict == DomainVerdict.MENTIONS_BRAND


def test_www_prefix_does_not_hide_phishing_shape():
    # Real crt.sh data returns hosts with www.; the prefix must be stripped so
    # www.paypal-login.info is still recognized as a brand-prefixed phishing shape.
    from brandguard.discovery.website_hunt import DomainVerdict, classify_domain
    f = classify_domain("www.paypal--login.info", ["paypal.com"], "PayPal")
    assert f.verdict == DomainVerdict.LOOKALIKE


def test_known_affiliate_is_allowlisted_not_lookalike():
    # An analyst-vetted affiliate (ziraatbank.de) must be official, not a
    # lookalike, so it drops out of the detected queue.
    from brandguard.discovery.website_hunt import DomainVerdict, classify_domain
    affiliates = ["ziraatbank.de", "ziraatkatilim.com.tr"]
    f = classify_domain("ziraatbank.de", ["ziraatbank.com.tr"], "Ziraat Bankası", affiliates)
    assert f.verdict == DomainVerdict.OFFICIAL


def test_allowlist_does_not_shield_real_phishing():
    # A real phishing shape is still a lookalike even with an allowlist present.
    from brandguard.discovery.website_hunt import DomainVerdict, classify_domain
    affiliates = ["ziraatbank.de"]
    f = classify_domain("ziraatbank-giris.com", ["ziraatbank.com.tr"], "Ziraat Bankası", affiliates)
    assert f.verdict == DomainVerdict.LOOKALIKE


def test_website_dorks_cover_lures_and_exclude_official():
    from brandguard.discovery.website_hunt import build_website_queries
    qs = build_website_queries("PayPal", ["paypal.com"])
    # excludes official on every dork
    assert all("-site:paypal.com" in q for q in qs)
    # covers credential-bait terms and a url-targeted dork
    assert any("login" in q for q in qs)
    assert any("inurl:login" in q for q in qs)
    assert any("giris" in q for q in qs)
    assert len(qs) >= 10  # meaningfully broader than the original three
