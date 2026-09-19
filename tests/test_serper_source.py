"""Tests for the Serper source: URL parsing and record inference (no network)."""

from brandguard.discovery.serper_source import (
    _extract_package_id,
    _result_to_record,
    build_apk_queries,
    search_apks,
)


class MockSerper:
    """Deterministic stand-in for the Serper API."""

    def __init__(self, results):
        self._results = results

    def search(self, query, num):
        return self._results


def test_build_apk_queries_excludes_play_and_targets_hosts():
    queries = build_apk_queries("Ziraat Bankasi")
    assert any("-site:play.google.com" in q for q in queries)
    assert any("apkpure.com" in q for q in queries)


def test_extract_package_id_from_url():
    assert _extract_package_id("https://apkpure.com/x/com.fake.bank") == "com.fake.bank"
    assert _extract_package_id("https://apkmirror.com/apk/tr.com.ziraat.mobil/") == "tr.com.ziraat.mobil"
    assert _extract_package_id("https://example.com/no-package-here") is None


def test_result_to_record_infers_fields():
    hit = {
        "title": "Ziraat Bankasi APK indir",
        "link": "https://apkpure.com/ziraat/com.fake.ziraat",
        "snippet": "Download the latest apk",
    }
    r = _result_to_record(hit)
    assert r.app_id == "com.fake.ziraat"
    assert r.source == "serper:apkpure.com"
    assert r.name == "Ziraat Bankasi APK indir"
    assert r.publisher.name == ""
    assert r.permissions == []


def test_result_without_package_id_falls_back_to_link():
    hit = {"title": "Some page", "link": "https://weird-apk-site.com/download/123"}
    r = _result_to_record(hit)
    assert r.app_id == "https://weird-apk-site.com/download/123"
    assert r.source == "serper:weird-apk-site.com"


def test_search_apks_dedupes_by_app_id():
    dupe = {"title": "X", "link": "https://apkpure.com/a/com.x.y"}
    records = search_apks("Brand", client=MockSerper([dupe, dupe]), max_queries=1)
    assert len(records) == 1


def test_missing_link_is_skipped():
    records = search_apks("Brand", client=MockSerper([{"title": "no link"}]), max_queries=1)
    assert records == []
