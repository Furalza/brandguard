"""Tests for the live Google Play adapter mapping (no network).

Only the pure mapping is tested; the scraping call is a side effect exercised
manually with scripts/scrape_and_triage.py.
"""

from brandguard.discovery.live_google_play import _detail_to_record


def test_maps_live_detail_and_preserves_missing_as_none():
    detail = {
        "appId": "com.example.bank",
        "title": "Example Bank",
        "developer": "Example Bank Inc",
        "developerWebsite": "https://examplebank.com",
        "developerEmail": "support@examplebank.com",
        "installs": "5,000,000+",
        "score": 4.3,
        "ratings": 120000,
        "version": "9.4.1",
    }
    r = _detail_to_record(detail)
    assert r.app_id == "com.example.bank"
    assert r.source == "google_play_live"
    assert r.downloads == 5_000_000
    assert r.publisher.email_domain == "examplebank.com"
    # Fields the scraper never provides must stay None, not be invented.
    assert r.publisher.account_created is None
    assert r.publisher.verified is None
    assert r.permissions == []


def test_missing_title_and_developer_do_not_crash():
    r = _detail_to_record({"appId": "com.x.y"})
    assert r.app_id == "com.x.y"
    assert r.name == ""
    assert r.publisher.name == ""


def test_real_data_quirks_do_not_crash():
    # Shapes real Google Play returns that broke the first version: string
    # numerics, non-string id, None fields, float version, bad email.
    quirks = [
        {"appId": "a", "title": "X", "developer": "Y", "score": "4.5"},
        {"appId": 123, "title": "X", "developer": "Y"},
        {"appId": "d", "title": None, "developer": None},
        {"appId": "e", "title": "X", "developer": "Y", "version": 1.0},
        {"appId": "f", "title": "X", "developer": "Y", "developerEmail": "noatsign"},
    ]
    for q in quirks:
        r = _detail_to_record(q)
        assert isinstance(r.app_id, str)
        assert r.rating is None or isinstance(r.rating, (int, float))
        assert r.version is None or isinstance(r.version, str)
