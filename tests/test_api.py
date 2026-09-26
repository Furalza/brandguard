"""Product API tests: no network, a fake engine runner, an inline worker.

They cover the contract the frontend relies on: a scan is created for any
input type, sources run in isolation and a failing one leaves the scan
``partial`` with its error visible, findings carry categories and evidence,
brands can be edited and an edit makes the row manual.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from brandguard.api import db as dbmod
from brandguard.api import scan_service
from brandguard.api.main import create_app
from brandguard.api.worker import InlineWorker
from brandguard.hunt_engine import RunResult

PROFILE = {
    "brand_name": "Papara", "official_domains": ["papara.com"],
    "official_publishers": ["PAPARA"], "known_official_apps": ["Papara"],
    "sector": "fintech", "official_package_ids": ["com.mobillium.papara"],
}


def _fake_run_source(profile, source, **kw):
    if source == "website":
        raise RuntimeError("Serper quota exhausted")
    if source == "play":
        rows = [
            {"app_id": "com.mobillium.papara", "source": "google_play_live", "label": "official",
             "confidence": 0.95, "evidence": ["Publisher matches and is corroborated."],
             "name": "Papara", "score": 1.0, "tiers_used": [0], "reason": "veto",
             "category": "official",
             "evidence_detail": [{"signal": "publisher_veto", "text": "Publisher matches.",
                                  "weight": 1.0, "tier": 0}]},
            {"app_id": "com.fake.papara.giris", "source": "google_play_live",
             "label": "impersonation", "confidence": 0.9, "evidence": ["young account"],
             "name": "Papara Giris 2026", "score": 0.9, "tiers_used": [0], "reason": "scored",
             "category": "malicious",
             "evidence_detail": [{"signal": "account_age", "text": "Account is 9 days old.",
                                  "weight": 0.7, "tier": 0}]},
        ]
        return RunResult(profile.brand_name, source, "2026-09-25T00:00:00+00:00", 2, 1, 0, rows,
                         warnings=["Play returned few listings."], requests=12, duration_ms=900)
    if source == "serper":
        rows = [{"app_id": "https://apk.dog/papara", "source": "serper:apk.dog",
                 "label": "repackaged", "confidence": 0.95, "evidence": ["(MOD) in title"],
                 "name": "Papara (MOD)", "score": 0.9, "tiers_used": [0], "reason": "veto",
                 "category": "malicious", "evidence_detail": []}]
        return RunResult(profile.brand_name, source, "2026-09-25T00:00:00+00:00", 1, 1, 0, rows)
    rows = [{"domain": "papara-giris.com", "verdict": "lookalike", "similarity": 0.9,
             "priority": "high", "confirmed_live": True, "evidence": ["young domain"],
             "category": "malicious"}]
    return RunResult(profile.brand_name, source, "2026-09-25T00:00:00+00:00", 1, 1, 0, rows)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("BRANDGUARD_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BRANDGUARD_ENV_FILE", str(tmp_path / "none.env"))
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "SERPER_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / "data" / "watchlist").mkdir(parents=True)
    (tmp_path / "data" / "watchlist" / "papara.json").write_text(
        json.dumps({**PROFILE, "_registry": {"managed_by": "brandguard.registry",
                                             "discovery": {"method": "google+play"}}}),
        encoding="utf-8")
    dbmod.reset_engine()
    # No network: resolution of unknown brands gets no clients.
    monkeypatch.setattr(scan_service, "_online_clients", lambda: (None, None))
    worker = InlineWorker(runner=lambda scan_id, source:
                          scan_service.run_scan_source(scan_id, source, runner=_fake_run_source))
    app = create_app(worker=worker, run_scheduler=False)
    with TestClient(app) as c:
        yield c
    dbmod.reset_engine()


def test_health_reports_configuration(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["adjudicator"] == "rules"
    assert "play" in h["sources"] and "deep" in h["depths"]


def test_watchlist_is_imported_on_startup(client):
    brands = client.get("/api/brands").json()
    assert [b["id"] for b in brands] == ["papara"]
    assert brands[0]["resolved_from"] == "csv"
    assert brands[0]["official_package_ids"] == ["com.mobillium.papara"]


def test_scan_known_brand_by_name_domain_and_package(client):
    for text, kind in (("Papara", "brand"), ("https://www.papara.com/tr", "domain"),
                       ("com.mobillium.papara", "package")):
        r = client.post("/api/scans", json={"input": text, "sources": ["play"]})
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["brand"]["id"] == "papara"
        assert body["input_type"] == kind and body["resolved_how"] == "existing"


def test_scan_runs_sources_in_isolation_and_ends_partial(client):
    r = client.post("/api/scans", json={"input": "Papara",
                                        "sources": ["play", "serper", "website", "crtsh"]})
    scan = client.get(f"/api/scans/{r.json()['id']}").json()
    assert scan["status"] == "partial"
    runs = {s["source"]: s for s in scan["source_runs"]}
    assert runs["website"]["status"] == "failed" and "quota" in runs["website"]["error"]
    assert runs["play"]["status"] == "done" and runs["play"]["warnings"]
    assert scan["counts"]["malicious"] == 3 and scan["counts"]["official"] == 1
    assert scan["counts"]["total"] == 4


def test_items_are_filterable_and_carry_evidence(client):
    r = client.post("/api/scans", json={"input": "Papara", "sources": ["play", "serper"]})
    scan_id = r.json()["id"]
    page = client.get(f"/api/scans/{scan_id}/items", params={"category": "malicious"}).json()
    assert page["total"] == 2
    assert {i["label"] for i in page["items"]} == {"impersonation", "repackaged"}
    item = client.get(f"/api/items/{page['items'][0]['id']}").json()
    assert item["evidence"] and item["category"] == "malicious"
    assert item["link"]
    all_items = client.get(f"/api/scans/{scan_id}/items").json()["items"]
    # display order: malicious first, then official
    assert [i["category"] for i in all_items] == ["malicious", "malicious", "official"]


def test_first_seen_survives_across_scans(client):
    first = client.post("/api/scans", json={"input": "Papara", "sources": ["play"]}).json()
    second = client.post("/api/scans", json={"input": "Papara", "sources": ["play"]}).json()
    a = client.get(f"/api/scans/{first['id']}/items").json()["items"]
    b = client.get(f"/api/scans/{second['id']}/items").json()["items"]
    by_key_a = {i["key"]: i for i in a}
    for item in b:
        assert item["first_seen_at"] == by_key_a[item["key"]]["first_seen_at"]
        assert item["seen_before"] is True
    assert all(i["seen_before"] is False for i in a)


def test_retry_reruns_only_failed_sources(client):
    r = client.post("/api/scans", json={"input": "Papara", "sources": ["play", "website"]})
    scan_id = r.json()["id"]
    assert client.get(f"/api/scans/{scan_id}").json()["status"] == "partial"
    r2 = client.post(f"/api/scans/{scan_id}/retry")
    assert r2.status_code == 200
    # website still fails in the fake engine; play was not rerun (still one official row)
    scan = client.get(f"/api/scans/{scan_id}").json()
    assert scan["status"] == "partial"
    assert scan["counts"]["official"] == 1


def test_unknown_brand_offline_gets_name_only_profile_with_review(client):
    r = client.post("/api/scans", json={"input": "Garanti BBVA", "sources": ["play"]})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["resolved_how"] == "name_only"
    assert body["brand"]["needs_review"] is True
    assert body["brand"]["resolved_from"] == "auto"


def test_brand_edit_becomes_manual_and_persists(client):
    r = client.patch("/api/brands/papara", json={"known_affiliates": ["papara.com.tr"],
                                                 "review_notes": []})
    assert r.status_code == 200
    b = client.get("/api/brands/papara").json()
    assert b["known_affiliates"] == ["papara.com.tr"]
    assert b["resolved_from"] == "manual" and b["needs_review"] is False


def test_invalid_source_and_depth_are_rejected(client):
    assert client.post("/api/scans", json={"input": "Papara", "sources": ["nope"]}).status_code == 422
    assert client.post("/api/scans", json={"input": "Papara", "depth": "max"}).status_code == 422


def test_depth_presets_override_engine_defaults():
    from brandguard.api.models import Scan

    scan = Scan(brand_id="x", input_raw="x", input_type="brand", sources=["serper"],
                depth="deep", tuning={"num": 20, "bogus": 1})
    opts = scan_service.tuning_for(scan, "serper")
    assert opts["pages"] == 2 and opts["max_queries"] is None and opts["num"] == 20
    assert "bogus" not in opts


def test_threaded_worker_completes_scan(tmp_path, monkeypatch):
    """The real worker (threads + SQLite WAL) must finish and finalize a scan."""
    import time

    from brandguard.api.worker import Worker

    monkeypatch.setenv("BRANDGUARD_DATABASE_URL", f"sqlite:///{tmp_path / 'w.db'}")
    monkeypatch.setenv("BRANDGUARD_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BRANDGUARD_ENV_FILE", str(tmp_path / "none.env"))
    (tmp_path / "data" / "watchlist").mkdir(parents=True)
    (tmp_path / "data" / "watchlist" / "papara.json").write_text(json.dumps(PROFILE), encoding="utf-8")
    dbmod.reset_engine()
    monkeypatch.setattr(scan_service, "_online_clients", lambda: (None, None))
    worker = Worker(max_workers=3, runner=lambda scan_id, source:
                    scan_service.run_scan_source(scan_id, source, runner=_fake_run_source))
    app = create_app(worker=worker)
    with TestClient(app) as c:
        r = c.post("/api/scans", json={"input": "Papara", "sources": ["play", "serper", "crtsh"]})
        scan_id = r.json()["id"]
        for _ in range(100):
            status = c.get(f"/api/scans/{scan_id}").json()["status"]
            if status in ("done", "partial", "failed"):
                break
            time.sleep(0.05)
        assert status == "done"
        assert c.get(f"/api/scans/{scan_id}/items").json()["total"] == 4
    dbmod.reset_engine()


def test_delete_brand_removes_scans_and_findings(client):
    scan = client.post("/api/scans", json={"input": "Papara", "sources": ["play"]}).json()
    assert client.get(f"/api/scans/{scan['id']}").json()["status"] in ("done", "partial")
    assert client.get("/api/brands/papara").status_code == 200
    r = client.delete("/api/brands/papara")
    assert r.status_code == 204
    assert client.get("/api/brands/papara").status_code == 404
    assert client.get(f"/api/scans/{scan['id']}").status_code == 404
    assert client.delete("/api/brands/papara").status_code == 404


def test_export_scan_is_one_json_document(client):
    scan = client.post("/api/scans", json={"input": "Papara", "sources": ["play"]}).json()
    r = client.get(f"/api/scans/{scan['id']}/export")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    body = r.json()
    assert body["scan"]["id"] == scan["id"] and body["brand"]["id"] == "papara"
    assert len(body["findings"]) == 2 and body["findings"][0]["category"] == "malicious"
    assert body["findings"][0]["evidence"]


def test_stale_automatic_profile_is_resolved_again(client, monkeypatch):
    from brandguard.api import scan_service

    # First scan of an unknown brand offline: name-only automatic profile.
    first = client.post("/api/scans", json={"input": "TikTok", "sources": ["play"]}).json()
    assert first["resolved_how"] == "name_only" and first["brand"]["official_domains"] == []

    class Play:
        def search(self, query, n_hits):
            return [{"appId": "com.zhiliaoapp.musically", "title": "TikTok", "developer": "TikTok Pte. Ltd."}]

        def details(self, app_id):
            return {"appId": app_id, "title": "TikTok", "developer": "TikTok Pte. Ltd.",
                    "developerWebsite": "https://www.tiktok.com/", "realInstalls": 3_000_000_000}

    class Web:
        def lookup(self, query):
            return {"organic": [{"link": "https://www.tiktok.com/", "title": "TikTok"}]}

    monkeypatch.setattr(scan_service, "_online_clients", lambda: (Play(), Web()))
    second = client.post("/api/scans", json={"input": "TikTok", "sources": ["play"]}).json()
    assert second["resolved_how"].startswith("re-resolved:")
    assert second["brand"]["id"] == first["brand"]["id"]
    assert second["brand"]["official_domains"] == ["tiktok.com"]
    assert "com.zhiliaoapp.musically" in second["brand"]["official_package_ids"]
    # A third scan reuses the upgraded row without touching the network.
    monkeypatch.setattr(scan_service, "_online_clients", lambda: (_ for _ in ()).throw(AssertionError("no network")))
    third = client.post("/api/scans", json={"input": "TikTok", "sources": ["play"]}).json()
    assert third["resolved_how"] == "existing"


def test_basic_auth_gate_when_configured(tmp_path, monkeypatch):
    import base64

    from brandguard.api import db as dbmod

    monkeypatch.setenv("BRANDGUARD_DATABASE_URL", f"sqlite:///{tmp_path / 'auth.db'}")
    monkeypatch.setenv("BRANDGUARD_ENV_FILE", str(tmp_path / "none.env"))
    monkeypatch.setenv("BRANDGUARD_BASIC_AUTH", "demo:s3cret")
    dbmod.reset_engine()
    app = create_app(worker=InlineWorker(runner=lambda *a: None), import_watchlist=False)
    with TestClient(app) as c:
        assert c.get("/api/health").status_code == 401
        assert c.get("/api/health").headers["www-authenticate"].startswith("Basic")
        bad = base64.b64encode(b"demo:wrong").decode()
        assert c.get("/api/health", headers={"Authorization": f"Basic {bad}"}).status_code == 401
        good = base64.b64encode(b"demo:s3cret").decode()
        assert c.get("/api/health", headers={"Authorization": f"Basic {good}"}).status_code == 200
    dbmod.reset_engine()


def test_export_filename_survives_turkish_letters(client):
    client.patch("/api/brands/papara", json={"brand_name": "Türkiye İş Bankası"})
    scan = client.post("/api/scans", json={"input": "papara.com", "sources": ["play"]}).json()
    r = client.get(f"/api/scans/{scan['id']}/export")
    assert r.status_code == 200
    assert 'filename="brandguard_turkiye_is_bankasi_' in r.headers["content-disposition"]


def test_batch_starts_one_scan_per_input_and_reports_bad_lines(client):
    r = client.post("/api/scans/batch", json={
        "inputs": ["Papara", "papara.com", "play.google.com", "   ", "PAPARA"], "sources": ["play"]})
    assert r.status_code == 202
    body = r.json()
    # duplicates (case-insensitive) and blanks are dropped; the platform domain is an error
    assert [s["input_raw"] for s in body["scans"]] == ["Papara", "papara.com"]
    assert body["errors"][0]["input"] == "play.google.com" and "platform" in body["errors"][0]["error"]
    assert all(s["batch_id"] == body["id"] for s in body["scans"])
    got = client.get(f"/api/batches/{body['id']}").json()
    assert got["status"] == "done" and len(got["scans"]) == 2
    assert got["totals"]["malicious"] == 2  # one impersonation per fake play run
    assert client.get(f"/api/scans?batch_id={body['id']}").json().__len__() == 2
    assert client.get("/api/batches/nope").status_code == 404
    assert client.post("/api/scans/batch", json={"inputs": ["play.google.com"]}).status_code == 422


def test_old_database_gets_the_batch_column(tmp_path, monkeypatch):
    import sqlite3

    from brandguard.api import db as dbmod

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE scans (id VARCHAR(32) PRIMARY KEY, brand_id VARCHAR(64), input_raw VARCHAR(500), "
                "input_type VARCHAR(32), resolved_how VARCHAR(64), sources JSON, depth VARCHAR(16), tuning JSON, "
                "status VARCHAR(16), error TEXT, counts JSON, created_at DATETIME, started_at DATETIME, finished_at DATETIME)")
    con.commit()
    con.close()
    monkeypatch.setenv("BRANDGUARD_DATABASE_URL", f"sqlite:///{path}")
    dbmod.reset_engine()
    dbmod.init_db()
    con = sqlite3.connect(path)
    cols = {row[1] for row in con.execute("PRAGMA table_info(scans)")}
    con.close()
    dbmod.reset_engine()
    assert "batch_id" in cols


def test_batch_export_is_a_zip_with_one_json_per_brand(client):
    import io
    import zipfile

    body = client.post("/api/scans/batch", json={"inputs": ["Papara"], "sources": ["play"]}).json()
    r = client.get(f"/api/batches/{body['id']}/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"].startswith('attachment; filename="brandguard_batch_')
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert "summary.json" in names and any(n.startswith("brandguard_papara_") for n in names)
    assert json.loads(zf.read("summary.json"))["totals"]["malicious"] == 1


def test_cancel_stops_queued_sources_and_keeps_finished_findings(tmp_path, monkeypatch):

    from brandguard.api import db as dbmod
    from brandguard.api import scan_service
    from brandguard.api.models import Scan, ScanSource

    monkeypatch.setenv("BRANDGUARD_DATABASE_URL", f"sqlite:///{tmp_path / 'c.db'}")
    monkeypatch.setenv("BRANDGUARD_ENV_FILE", str(tmp_path / "none.env"))
    dbmod.reset_engine()
    dbmod.init_db()
    with dbmod.session_scope() as session:
        from brandguard.api.models import Brand
        session.add(Brand(id="papara", brand_name="Papara", sector="fintech", official_domains=["papara.com"],
                          official_publishers=["PAPARA"], official_package_ids=["com.mobillium.papara"],
                          known_official_apps=[], known_affiliates=[], resolved_from="manual"))
        scan = Scan(brand_id="papara", input_raw="Papara", input_type="brand", sources=["play", "serper"],
                    depth="normal", status="queued")
        session.add(scan)
        session.flush()
        session.add(ScanSource(scan_id=scan.id, source="play", status="queued"))
        session.add(ScanSource(scan_id=scan.id, source="serper", status="queued"))
        scan_id = scan.id

    # play runs and finishes; serper is cancelled before the worker reaches it
    scan_service.run_scan_source(scan_id, "play", runner=_fake_run_source)
    with dbmod.session_scope() as session:
        scan = session.get(Scan, scan_id)
        assert scan.status == "running"
        assert scan_service.cancel_scan(session, scan) is True
    scan_service.run_scan_source(scan_id, "serper", runner=_fake_run_source)  # must be a no-op
    with dbmod.session_scope() as session:
        scan = session.get(Scan, scan_id)
        assert scan.status == "cancelled"
        runs = {r.source: r.status for r in scan.source_runs}
        assert runs == {"play": "done", "serper": "cancelled"}
        assert scan.counts["malicious"] == 1  # play's findings are kept
        assert scan_service.cancel_scan(session, scan) is False  # already ended
    dbmod.reset_engine()


def test_cancel_endpoints(client):
    body = client.post("/api/scans/batch", json={"inputs": ["Papara"], "sources": ["play"]}).json()
    scan_id = body["scans"][0]["id"]
    # the inline worker already finished it: cancel is a harmless no-op
    r = client.post(f"/api/scans/{scan_id}/cancel")
    assert r.status_code == 200 and r.json()["status"] in ("done", "partial")
    r = client.post(f"/api/batches/{body['id']}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert client.post("/api/scans/nope/cancel").status_code == 404
    assert client.post("/api/batches/nope/cancel").status_code == 404


def test_reviews_follow_the_key_across_scans_and_drop_from_needs_action(client):
    first = client.post("/api/scans", json={"input": "Papara", "sources": ["play"]}).json()
    assert first["counts"]["needs_action"] == 1
    key = "com.fake.papara.giris"
    r = client.put(f"/api/brands/papara/reviews/{key}", json={"status": "false_positive", "note": "our own test app"})
    assert r.status_code == 200 and r.json()["status"] == "false_positive"
    assert client.put(f"/api/brands/papara/reviews/{key}", json={"status": "nonsense"}).status_code == 422
    # the review is attached to the finding and removes it from the open queue
    items = client.get(f"/api/scans/{first['id']}/items?category=malicious").json()["items"]
    assert items[0]["review"]["note"] == "our own test app"
    assert client.get(f"/api/scans/{first['id']}/items?category=malicious&open_only=true").json()["total"] == 0
    assert client.get(f"/api/scans/{first['id']}").json()["counts"]["needs_action"] == 0
    # a later scan finds the same key: the decision is still there
    second = client.post("/api/scans", json={"input": "Papara", "sources": ["play"]}).json()
    items = client.get(f"/api/scans/{second['id']}/items?category=malicious").json()["items"]
    assert items[0]["review"]["status"] == "false_positive"
    assert [x["key"] for x in client.get("/api/brands/papara/reviews").json()] == [key]
    assert client.delete(f"/api/brands/papara/reviews/{key}").status_code == 204
    assert client.get(f"/api/scans/{second['id']}").json()["counts"]["needs_action"] == 1


def test_diff_reports_new_gone_and_changed_keys(client):
    first = client.post("/api/scans", json={"input": "Papara", "sources": ["play"]}).json()
    d = client.get(f"/api/scans/{first['id']}/diff").json()
    assert d["against_id"] is None and len(d["new"]) == 2      # nothing to compare: all new
    second = client.post("/api/scans", json={"input": "Papara", "sources": ["play"]}).json()
    d = client.get(f"/api/scans/{second['id']}/diff").json()
    assert d["against_id"] == first["id"] and d["new"] == [] and d["gone"] == [] and d["unchanged"] == 2
    # simulate a change in the earlier scan's row and check it is reported
    from brandguard.api import db as dbmod
    from brandguard.api.models import Finding
    from sqlalchemy import select
    with dbmod.session_scope() as session:
        f = session.scalar(select(Finding).where(Finding.scan_id == first["id"], Finding.key == "com.fake.papara.giris"))
        f.category = "suspicious"
        session.add(Finding(scan_id=first["id"], brand_id="papara", kind="app", key="com.gone.app", name="Gone",
                            source="google_play_live", label="unrelated", category="noise"))
    d = client.get(f"/api/scans/{second['id']}/diff").json()
    assert [x["key"] for x in d["gone"]] == ["com.gone.app"]
    assert d["changed"][0]["key"] == "com.fake.papara.giris" and d["changed"][0]["previous_category"] == "suspicious"
    assert client.get(f"/api/scans/{second['id']}/diff?against=nope").status_code == 404
    assert client.get(f"/api/scans/{second['id']}/items?new_only=true").json()["total"] == 0


def test_schedule_is_set_on_the_brand_and_runs_when_due(client, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from brandguard.api import db as dbmod
    from brandguard.api import scan_service
    from brandguard.api.models import Brand

    r = client.patch("/api/brands/papara", json={"schedule": "daily", "schedule_sources": ["play"]})
    body = r.json()
    assert r.status_code == 200 and body["schedule"] == "daily" and body["schedule_sources"] == ["play"]
    assert body["next_run_at"] is not None
    assert body["resolved_from"] == "csv"   # a schedule edit is not a profile edit
    assert client.patch("/api/brands/papara", json={"schedule": "hourly"}).status_code == 422
    # nothing due yet
    submitted = []
    assert scan_service.run_due_schedules(lambda sid, src: submitted.append(sid)) == 0
    # make it due and tick
    with dbmod.session_scope() as session:
        session.get(Brand, "papara").next_run_at = datetime.now(tz=UTC) - timedelta(minutes=1)
    assert scan_service.run_due_schedules(lambda sid, src: submitted.append(sid)) == 1
    scans = client.get("/api/scans?brand_id=papara").json()
    assert scans[0]["trigger"] == "schedule" and scans[0]["id"] == submitted[0]
    nxt = client.get("/api/brands/papara").json()["next_run_at"]
    assert nxt > datetime.now(tz=UTC).isoformat()
    # switching off clears the next run
    assert client.patch("/api/brands/papara", json={"schedule": "off"}).json()["next_run_at"] is None


def test_review_key_may_be_a_url(client):
    from urllib.parse import quote

    key = "https://apkdone.com/papara-mod/"
    r = client.put(f"/api/brands/papara/reviews/{quote(key, safe='')}", json={"status": "takedown_sent"})
    assert r.status_code == 200 and r.json()["key"] == key
    assert client.delete(f"/api/brands/papara/reviews/{quote(key, safe='')}").status_code == 204


def test_apk_run_waits_for_play_and_reads_its_measurement(tmp_path, monkeypatch):
    from brandguard.api import db as dbmod
    from brandguard.api import scan_service
    from brandguard.api.models import Brand, Scan, ScanSource
    from brandguard.hunt_engine import RunResult

    monkeypatch.setenv("BRANDGUARD_DATABASE_URL", f"sqlite:///{tmp_path / 'm.db'}")
    monkeypatch.setenv("BRANDGUARD_ENV_FILE", str(tmp_path / "none.env"))
    dbmod.reset_engine()
    dbmod.init_db()
    with dbmod.session_scope() as session:
        session.add(Brand(id="wise", brand_name="Wise", sector="fintech", official_domains=["wise.com"],
                          official_publishers=["Wise Payments Ltd."], official_package_ids=[],
                          known_official_apps=["Wise"], known_affiliates=[], resolved_from="manual"))
        scan = Scan(brand_id="wise", input_raw="Wise", input_type="brand", sources=["play", "serper"],
                    depth="normal", status="queued")
        session.add(scan)
        session.flush()
        session.add(ScanSource(scan_id=scan.id, source="play", status="queued"))
        session.add(ScanSource(scan_id=scan.id, source="serper", status="queued"))
        scan_id = scan.id

    seen = {}

    def runner(profile, source, **kw):
        seen[source] = profile.brand_word_shared_by
        return RunResult("Wise", source, "2026-09-25T00:00:00+00:00", 0, 0, 0, [],
                         measurements={"brand_word_shared_by": 4} if source == "play" else {})

    scan_service.run_scan_source(scan_id, "play", runner=runner)
    scan_service.run_scan_source(scan_id, "serper", runner=runner, play_wait_s=1)
    assert seen == {"play": None, "serper": 4}
    with dbmod.session_scope() as session:
        assert session.get(Scan, scan_id).tuning["_measurements"] == {"brand_word_shared_by": 4}
    dbmod.reset_engine()


def test_structured_input_merges_typed_facts_into_the_profile(client, monkeypatch):
    from brandguard.api import scan_service

    class Play:
        def search(self, query, n_hits):
            return []

        def details(self, app_id):
            return {"appId": app_id, "title": "Pegasus - En Uygun Ucak Bileti", "developer": "Pegasus Airlines",
                    "developerWebsite": "https://www.flypgs.com/", "realInstalls": 15_000_000}

    monkeypatch.setattr(scan_service, "_online_clients", lambda: (Play(), None))
    r = client.post("/api/scans", json={"brand_name": "Pegasus", "domain": "flypgs.com",
                                        "store": "https://play.google.com/store/apps/details?id=com.pozitron.pegasus",
                                        "sources": ["play"]})
    assert r.status_code == 202, r.text
    scan = r.json()
    assert scan["input_type"] == "structured" and scan["input_raw"].startswith("Pegasus · flypgs.com")
    b = scan["brand"]
    assert b["brand_name"] == "Pegasus" and b["official_domains"] == ["flypgs.com"]
    assert "com.pozitron.pegasus" in b["official_package_ids"]
    assert "Pegasus Airlines" in b["official_publishers"] and b["resolved_from"] == "manual"
    # the operator typed the name, so it is not "guessed from the domain label"
    assert not any(n.startswith("Brand name guessed") for n in b["review_notes"])
    # the same brand typed with a second package: merged, not duplicated
    r = client.post("/api/scans", json={"domain": "flypgs.com", "store": "com.pegasus.cargo", "sources": ["play"]})
    assert r.json()["resolved_how"] == "existing+merged"
    ids = client.get(f"/api/brands/{b['id']}").json()["official_package_ids"]
    assert set(ids) >= {"com.pozitron.pegasus", "com.pegasus.cargo"}
    # nothing typed
    assert client.post("/api/scans", json={"sources": ["play"]}).status_code == 422
    # a platform domain is refused here too
    assert client.post("/api/scans", json={"brand_name": "X", "domain": "play.google.com"}).status_code == 422


def test_batch_line_may_carry_name_domain_and_store(client):
    r = client.post("/api/scans/batch", json={"inputs": ["Papara | papara.com | com.mobillium.papara"], "sources": ["play"]})
    assert r.status_code == 202
    s = r.json()["scans"][0]
    assert s["input_type"] == "structured" and s["brand_name"] == "Papara"


def test_scan_search_pages_and_filters_and_scans_can_be_deleted(client):
    first = client.post("/api/scans", json={"input": "Papara", "sources": ["play"]}).json()
    batch = client.post("/api/scans/batch", json={"inputs": ["Papara"], "sources": ["play"]}).json()
    second = batch["scans"][0]["id"]
    page = client.get("/api/scans/search?limit=1").json()
    assert page["total"] == 2 and len(page["items"]) == 1 and page["items"][0]["id"] == second
    page2 = client.get("/api/scans/search?limit=1&offset=1").json()
    assert page2["items"][0]["id"] == first["id"]
    assert client.get("/api/scans/search?view=batches").json()["total"] == 1
    assert client.get("/api/scans/search?view=attention").json()["total"] == 2
    assert client.get("/api/scans/search?view=active").json()["total"] == 0
    assert client.get("/api/scans/search?q=papara").json()["total"] == 2
    assert client.get("/api/scans/search?q=nothing").json()["total"] == 0
    assert client.get("/api/scans/search?view=bogus").status_code == 422
    # delete one scan: the brand and the other scan stay
    assert client.delete(f"/api/scans/{first['id']}").status_code == 204
    assert client.get(f"/api/scans/{first['id']}").status_code == 404
    assert client.get("/api/scans/search").json()["total"] == 1
    assert client.get("/api/brands/papara").status_code == 200
    assert client.delete("/api/scans/nope").status_code == 404


def test_public_url_reads_the_tunnel_sidecar_and_never_raises(monkeypatch):
    import io
    import urllib.request

    from brandguard.api import main as m

    monkeypatch.delenv("BRANDGUARD_TUNNEL_METRICS", raising=False)
    assert m.public_url(now=1000.0) is None
    monkeypatch.setenv("BRANDGUARD_TUNNEL_METRICS", "http://cloudflared:2000")

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=0: Resp(b'{"hostname":"abc-def.trycloudflare.com"}'))
    m._tunnel_cache.update(at=0.0, url=None)
    assert m.public_url(now=2000.0) == "https://abc-def.trycloudflare.com"
    # cached: a broken sidecar within 30 s still returns the last answer
    def boom(url, timeout=0):
        raise OSError("down")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert m.public_url(now=2010.0) == "https://abc-def.trycloudflare.com"
    assert m.public_url(now=2100.0) is None
    # a hostname that is not a hostname is ignored
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=0: Resp(b'{"hostname":"evil/../x"}'))
    assert m.public_url(now=2200.0) is None


def test_batch_errors_survive_a_reload_and_a_domain_shaped_package_id_is_checked_on_play(client, monkeypatch):
    from brandguard.api import scan_service

    class Play:
        def search(self, query, n_hits):
            return []

        def details(self, app_id):
            if app_id == "trendyol.com":
                return {"appId": app_id, "title": "Trendyol - Online Alisveris", "developer": "Trendyol",
                        "developerWebsite": "https://www.trendyol.com/", "realInstalls": 100_000_000}
            raise LookupError(app_id)

    monkeypatch.setattr(scan_service, "_online_clients", lambda: (Play(), None))
    r = client.post("/api/scans/batch", json={"inputs": [
        "Trendyol | trendyol.com | trendyol.com",        # package id that looks like a domain
        "Papara | papara.com | papara.com",              # not a package on Play: reported, not fatal
    ], "sources": ["play"]})
    assert r.status_code == 202, r.text
    body = r.json()
    assert [s["brand_name"] for s in body["scans"]] == ["Trendyol"]
    assert "trendyol.com" in client.get(f"/api/brands/{body['scans'][0]['brand_id']}").json()["official_package_ids"]
    assert len(body["errors"]) == 1 and "Google Play link" in body["errors"][0]["error"]
    # the error is still there after the page is reloaded and in the ZIP summary
    again = client.get(f"/api/batches/{body['id']}").json()
    assert again["errors"] == body["errors"]
    import io
    import json
    import zipfile

    zf = zipfile.ZipFile(io.BytesIO(client.get(f"/api/batches/{body['id']}/export").content))
    assert json.loads(zf.read("summary.json"))["errors"] == body["errors"]
