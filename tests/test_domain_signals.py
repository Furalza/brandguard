"""Tests for D1 domain signals and enrichment (no network for the pure parts)."""

from brandguard.discovery.website_hunt import (
    DomainFinding,
    DomainVerdict,
    enrich_live_lookalikes,
)


def _f(domain, verdict, live):
    return DomainFinding(domain, verdict, 0.9, ["e"], "q", confirmed_live=live)


def test_non_live_lookalike_is_low_priority_no_network():
    # A generated variant must not trigger a WHOIS/SSL lookup; low priority.
    out = enrich_live_lookalikes([_f("x.com.tr", DomainVerdict.LOOKALIKE, False)])
    assert out[0].priority == "low"
    assert out[0].domain_age_days is None


def test_unrelated_is_low_priority():
    out = enrich_live_lookalikes([_f("instagram.com", DomainVerdict.UNRELATED, True)])
    assert out[0].priority == "low"


def test_enrichment_preserves_all_findings():
    findings = [
        _f("a.com", DomainVerdict.LOOKALIKE, False),
        _f("b.com", DomainVerdict.UNRELATED, True),
        _f("c.com", DomainVerdict.MENTIONS_BRAND, True),
    ]
    out = enrich_live_lookalikes(findings)
    assert len(out) == len(findings)


def test_established_paid_cert_lowers_priority_when_age_unknown():
    # Mirrors the real .az/.de case: WHOIS unavailable, but an old paid-CA
    # certificate leans legitimate, so priority should be low, not medium.
    from unittest.mock import patch

    from brandguard.discovery import domain_signals as ds

    def no_whois(domain):
        return None

    def old_paid_cert(domain, timeout=6.0):
        return ds.CertSignal(None, "DigiCert Inc", 300, False, False, "old paid cert")

    finding = _f("ziraatbank.de", DomainVerdict.LOOKALIKE, True)
    with patch.object(ds, "whois_age", no_whois), patch.object(ds, "cert_age", old_paid_cert):
        out = enrich_live_lookalikes([finding])
    assert out[0].priority == "low"


def test_young_domain_with_free_cert_is_high_priority():
    from unittest.mock import patch

    from brandguard.discovery import domain_signals as ds

    def young_whois(domain):
        return ds.DomainAgeSignal(None, 5, True, "5 days old")

    def fresh_free_cert(domain, timeout=6.0):
        return ds.CertSignal(None, "Let's Encrypt", 3, True, True, "fresh free cert")

    finding = _f("ziraatbank-phish.com", DomainVerdict.LOOKALIKE, True)
    with patch.object(ds, "whois_age", young_whois), patch.object(ds, "cert_age", fresh_free_cert):
        out = enrich_live_lookalikes([finding])
    assert out[0].priority == "high"
