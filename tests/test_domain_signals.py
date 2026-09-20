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
