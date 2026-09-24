"""Tests for the brand registry (CSV -> watchlist profiles)."""

import json
from pathlib import Path

import pytest

from brandguard.registry import (
    MANAGED_KEY,
    Action,
    BrandEntry,
    OnlineResolver,
    apply_sync,
    discover_domain,
    enrich_from_play,
    load_registry,
    main,
    mentions_brand,
    normalize_domain,
    parse_registry,
    plan_sync,
    slugify,
)
from brandguard.schema import BrandProfile

HEADER = "id,brand_name,official_domains,sector,official_publishers,active\n"


def _reg(body: str, header: str = HEADER):
    return parse_registry(header + body, source="brands.csv")


def _sync(reg, watchlist: Path, **kw):
    report = plan_sync(reg, watchlist, **kw)
    apply_sync(report, watchlist)
    return report


def _actions(report):
    return {c.path.name: c.action for c in report.changes}


# --- normalization -----------------------------------------------------------

def test_slugify_folds_turkish_and_punctuation():
    assert slugify("Ziraat Bankas\u0131") == "ziraat_bankasi"
    assert slugify("  \u0130\u015f Bankas\u0131 A.\u015e. ") == "is_bankasi_a_s"


@pytest.mark.parametrize(("raw", "host"), [
    ("https://www.ZiraatBank.com.tr/tr/bireysel?x=1", "ziraatbank.com.tr"),
    ("akbank.com.", "akbank.com"),
    ("http://user@paypal.com:443/", "paypal.com"),
])
def test_normalize_domain_accepts_pasted_urls(raw, host):
    assert normalize_domain(raw) == host


# --- parsing and validation --------------------------------------------------

def test_minimal_csv_parses_with_defaults():
    reg = parse_registry("brand_name,official_domains\nAkbank,akbank.com|akbank.com.tr\n")
    assert reg.ok
    (entry,) = reg.entries
    assert entry.id == "akbank"
    assert entry.official_domains == ("akbank.com", "akbank.com.tr")
    assert entry.sector == "unknown"
    assert entry.active


def test_semicolon_delimiter_from_turkish_excel():
    reg = parse_registry(
        "brand_name;official_domains;sector\nGaranti BBVA;garantibbva.com.tr;banking\n"
    )
    assert reg.ok
    assert reg.entries[0].sector == "banking"


def test_cp1254_file_is_read_with_a_warning(tmp_path):
    path = tmp_path / "brands.csv"
    text = "brand_name;official_domains\nZiraat Bankas\u0131;ziraatbank.com.tr\n"
    path.write_bytes(text.encode("cp1254"))
    reg = load_registry(path)
    assert reg.ok
    assert reg.entries[0].brand_name == "Ziraat Bankas\u0131"
    assert any("1254" in w for w in reg.warnings)


def test_errors_carry_line_numbers_and_are_all_collected():
    reg = _reg(
        "a,Alpha,alpha.com,banking,,yes\n"
        ",,beta.com,,,\n"
        "c,Gamma,not a domain,,,\n"
        "d,Delta,delta.com,,,maybe\n"
    )
    assert not reg.ok
    joined = "\n".join(reg.errors)
    assert "line 3: brand_name is empty" in joined
    assert "line 4" in joined and "not a valid domain" in joined
    assert "line 5" in joined and "active must be yes/no" in joined


def test_unknown_column_is_rejected_to_catch_typos():
    reg = parse_registry("brand_name,offical_domains\nX,x.com\n")
    assert any("unknown column" in e for e in reg.errors)


def test_duplicate_id_is_an_error_shared_domain_a_warning():
    reg = _reg("a,Alpha,alpha.com,,,\na,Alpha Two,alpha2.com,,,\nb,Beta,alpha.com,,,\n")
    assert any("already used on line 2" in e for e in reg.errors)
    assert any("shares official domain" in w for w in reg.warnings)


def test_comment_and_blank_rows_are_ignored():
    reg = _reg("a,Alpha,alpha.com,,,\n\n,#Beta,beta.com,,,\n")
    assert reg.ok
    assert [e.id for e in reg.entries] == ["a"]


def test_invalid_package_id_is_rejected():
    reg = parse_registry(
        "brand_name,official_domains,official_package_ids\nX,x.com,not a package\n"
    )
    assert any("valid package id" in e for e in reg.errors)


# --- sync --------------------------------------------------------------------

def test_sync_creates_profiles_the_hunt_can_load(tmp_path):
    report = _sync(_reg("akbank,Akbank,akbank.com,banking,Akbank T.A.S.,yes\n"), tmp_path)
    assert _actions(report) == {"akbank.json": Action.CREATE}
    data = json.loads((tmp_path / "akbank.json").read_text(encoding="utf-8"))
    profile = BrandProfile(**data)  # exactly what hunt.py does
    assert profile.official_publishers == ["Akbank T.A.S."]
    assert data[MANAGED_KEY]["managed_by"] == "brandguard.registry"


def test_sync_is_idempotent(tmp_path):
    reg = _reg("akbank,Akbank,akbank.com,banking,,yes\n")
    _sync(reg, tmp_path)
    before = (tmp_path / "akbank.json").read_bytes()
    report = _sync(reg, tmp_path)
    assert _actions(report) == {"akbank.json": Action.UNCHANGED}
    assert (tmp_path / "akbank.json").read_bytes() == before


def test_sync_updates_changed_rows(tmp_path):
    _sync(_reg("akbank,Akbank,akbank.com,banking,,yes\n"), tmp_path)
    report = _sync(_reg("akbank,Akbank,akbank.com|akbank.com.tr,banking,,yes\n"), tmp_path)
    assert _actions(report) == {"akbank.json": Action.UPDATE}


def test_removed_and_deactivated_rows_are_pruned(tmp_path):
    _sync(_reg("a,Alpha,alpha.com,,,\nb,Beta,beta.com,,,\nc,Gamma,gamma.com,,,\n"), tmp_path)
    report = _sync(_reg("a,Alpha,alpha.com,,,\nb,Beta,beta.com,,,no\n"), tmp_path)
    changes = {c.path.name: c for c in report.changes}
    assert changes["b.json"].action is Action.REMOVE and "deactivated" in changes["b.json"].reason
    assert changes["c.json"].action is Action.REMOVE and "no longer" in changes["c.json"].reason
    assert sorted(p.name for p in tmp_path.glob("*.json")) == ["a.json"]


def test_no_prune_keeps_generated_profiles(tmp_path):
    _sync(_reg("a,Alpha,alpha.com,,,\nb,Beta,beta.com,,,\n"), tmp_path)
    _sync(_reg("a,Alpha,alpha.com,,,\n"), tmp_path, prune=False)
    assert (tmp_path / "b.json").exists()


def test_hand_maintained_profiles_are_never_touched(tmp_path):
    manual = {"brand_name": "Ziraat", "official_domains": ["ziraatbank.com.tr"],
              "official_publishers": [], "known_official_apps": [], "sector": "banking",
              "known_affiliates": ["ziraatbank.de"]}
    (tmp_path / "ziraat.json").write_text(json.dumps(manual), encoding="utf-8")
    original = (tmp_path / "ziraat.json").read_bytes()

    report = _sync(_reg("ziraat,Ziraat,ziraatbank.com.tr,banking,,yes\n"), tmp_path)
    assert _actions(report) == {"ziraat.json": Action.SKIP_MANUAL}
    report = _sync(_reg("other,Alpha,alpha.com,,,\n"), tmp_path)  # not in CSV: still kept
    assert "ziraat.json" not in {c.path.name for c in report.changes if c.action is Action.REMOVE}
    assert (tmp_path / "ziraat.json").read_bytes() == original


def test_brand_already_covered_by_manual_profile_is_not_scanned_twice(tmp_path):
    manual = {"brand_name": "Ziraat", "official_domains": ["ziraatbank.com.tr"],
              "official_publishers": [], "known_official_apps": [], "sector": "banking"}
    (tmp_path / "ziraat.json").write_text(json.dumps(manual), encoding="utf-8")
    row = "ziraat_bankasi,Ziraat Bankasi,https://www.ziraatbank.com.tr,,,\n"
    report = _sync(_reg(row), tmp_path)
    assert _actions(report) == {"ziraat_bankasi.json": Action.SKIP_COVERED}
    assert not (tmp_path / "ziraat_bankasi.json").exists()


def test_invalid_csv_writes_nothing(tmp_path):
    _sync(_reg("a,Alpha,alpha.com,,,\nb,Beta,beta.com,,,\n"), tmp_path)
    report = _sync(_reg("a,Alpha,alpha.com,,,\n,,broken,,,\n"), tmp_path)
    assert report.errors and not report.applied
    assert (tmp_path / "b.json").exists()


def test_empty_registry_refuses_to_prune_everything(tmp_path):
    _sync(_reg("a,Alpha,alpha.com,,,\n"), tmp_path)
    report = _sync(_reg(""), tmp_path)
    assert any("refusing to remove" in e for e in report.errors)
    assert (tmp_path / "a.json").exists()


def test_unreadable_json_in_watchlist_is_left_alone(tmp_path):
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    report = _sync(_reg("a,Alpha,alpha.com,,,\n"), tmp_path)
    assert any("broken.json" in w for w in report.warnings)
    assert (tmp_path / "broken.json").exists()


# --- enrichment --------------------------------------------------------------

class FakePlay:
    def __init__(self, listings):
        self.listings = listings
        self.calls = 0

    def search(self, query, n_hits):
        self.calls += 1
        return [{"appId": a["appId"], "title": a["title"], "developer": a["developer"]}
                for a in self.listings][:n_hits]

    def details(self, app_id):
        return next(a for a in self.listings if a["appId"] == app_id)


ZIRAAT_PLAY = [
    {"appId": "com.ziraat.ziraatmobil", "title": "Ziraat Mobil",
     "developer": "T.C. Ziraat Bankas\u0131 A.\u015e.", "developerWebsite": "https://www.ziraatbank.com.tr"},
    {"appId": "com.bankkart.mobil", "title": "Bankkart Mobil",
     "developer": "T.C. Ziraat Bankas\u0131 A.\u015e.", "developerWebsite": None},
    {"appId": "com.ziraat.fake", "title": "Ziraat Giris",
     "developer": "Ziraat Bank Destek", "developerWebsite": "https://ziraat-destek.xyz"},
    {"appId": "com.ziraatkatilim.mobil", "title": "Ziraat Kat\u0131l\u0131m",
     "developer": "Ziraat Katilim", "developerEmail": "mobil@ziraatkatilim.com.tr"},
    {"appId": "com.other.game", "title": "Tarla Oyunu",
     "developer": "Oyun Stud", "developerWebsite": "https://oyun.example.com"},
]


def _ziraat(domains=("ziraatbank.com.tr",)):
    return BrandEntry(id="ziraat", brand_name="Ziraat", official_domains=tuple(domains))


def test_enrichment_accepts_only_domain_verified_publishers():
    result = enrich_from_play(_ziraat(), FakePlay(ZIRAAT_PLAY))
    assert result.publishers == ["T.C. Ziraat Bankas\u0131 A.\u015e."]
    # the verified publisher's second app counts too, even without its own website
    assert result.package_ids == ["com.ziraat.ziraatmobil", "com.bankkart.mobil"]
    assert "com.ziraat.fake" not in result.package_ids
    assert any("com.ziraat.fake" in r for r in result.needs_review)
    # an affiliate is not official unless its domain is listed
    assert "com.ziraatkatilim.mobil" not in result.package_ids


def test_enrichment_accepts_email_domain_proof():
    entry = _ziraat(("ziraatbank.com.tr", "ziraatkatilim.com.tr"))
    result = enrich_from_play(entry, FakePlay(ZIRAAT_PLAY))
    assert "Ziraat Katilim" in result.publishers


def test_enrichment_is_merged_after_csv_values_and_reused(tmp_path):
    reg = _reg("ziraat,Ziraat,ziraatbank.com.tr,banking,Manual Publisher,yes\n")
    play = FakePlay(ZIRAAT_PLAY)
    enricher = lambda e: enrich_from_play(e, play)

    _sync(reg, tmp_path, enricher=enricher)
    data = json.loads((tmp_path / "ziraat.json").read_text(encoding="utf-8"))
    assert data["official_publishers"] == ["Manual Publisher", "T.C. Ziraat Bankas\u0131 A.\u015e."]
    assert data[MANAGED_KEY]["enrichment"]["package_ids"]

    # second run: cached, no network; a plain sync keeps the enrichment
    report = _sync(reg, tmp_path, enricher=enricher)
    assert play.calls == 1 and _actions(report) == {"ziraat.json": Action.UNCHANGED}
    _sync(reg, tmp_path)
    assert "T.C. Ziraat Bankas\u0131 A.\u015e." in json.loads(
        (tmp_path / "ziraat.json").read_text(encoding="utf-8"))["official_publishers"]

    # refresh forces a new lookup
    _sync(reg, tmp_path, enricher=enricher, refresh=True)
    assert play.calls == 2


def test_enrichment_is_dropped_when_official_domains_change(tmp_path):
    play = FakePlay(ZIRAAT_PLAY)
    _sync(_reg("ziraat,Ziraat,ziraatbank.com.tr,,,\n"), tmp_path,
          enricher=lambda e: enrich_from_play(e, play))
    report = _sync(_reg("ziraat,Ziraat,ziraat.com.tr,,,\n"), tmp_path)
    data = json.loads((tmp_path / "ziraat.json").read_text(encoding="utf-8"))
    assert "enrichment" not in data[MANAGED_KEY]
    assert data["official_publishers"] == []
    assert any("previous enrichment dropped" in w for w in report.warnings)


def test_enrichment_failure_still_writes_the_profile(tmp_path):
    def boom(entry):
        raise TimeoutError

    report = _sync(_reg("a,Alpha,alpha.com,,,\n"), tmp_path, enricher=boom)
    assert (tmp_path / "a.json").exists()
    assert any("enrichment failed" in w for w in report.warnings)


# --- CLI ---------------------------------------------------------------------

def test_cli_check_writes_nothing_and_sync_writes(tmp_path, capsys):
    csv_path = tmp_path / "brands.csv"
    csv_path.write_text("brand_name,official_domains\nAkbank,akbank.com\n", encoding="utf-8")
    wl = tmp_path / "watchlist"
    assert main(["check", "--csv", str(csv_path), "--watchlist", str(wl)]) == 0
    assert not wl.exists() or not list(wl.glob("*.json"))
    assert main(["sync", "--csv", str(csv_path), "--watchlist", str(wl)]) == 0
    assert (wl / "akbank.json").exists()
    assert "1 create" in capsys.readouterr().out


def test_cli_only_does_not_prune_other_brands(tmp_path):
    csv_path = tmp_path / "brands.csv"
    wl = tmp_path / "watchlist"
    body = "brand_name,official_domains\nAlpha,alpha.com\nBeta,beta.com\n"
    csv_path.write_text(body, encoding="utf-8")
    main(["sync", "--csv", str(csv_path), "--watchlist", str(wl)])
    assert main(["sync", "--csv", str(csv_path), "--watchlist", str(wl), "--only", "alpha"]) == 0
    assert (wl / "beta.json").exists()


def test_cli_returns_nonzero_on_invalid_csv(tmp_path):
    csv_path = tmp_path / "brands.csv"
    csv_path.write_text("brand_name,official_domains\nAlpha,not a domain\n", encoding="utf-8")
    assert main(["check", "--csv", str(csv_path), "--watchlist", str(tmp_path / "w")]) == 1


def test_sector_aliases_and_missing_baseline_warning(monkeypatch):
    import sys
    import types

    fake = types.ModuleType("brandguard.triage.scored_signals")
    fake._SECTOR_EXPECTED = {"banking": set(), "logistics": set(), "crypto": set()}
    monkeypatch.setitem(sys.modules, "brandguard.triage.scored_signals", fake)
    reg = parse_registry(
        "brand_name,official_domains,sector\n"
        "Aras,araskargo.com.tr,Kargo\nTrendyol,trendyol.com,ecommerce\n"
    )
    assert [e.sector for e in reg.entries] == ["logistics", "ecommerce"]
    assert any("'ecommerce' has no permission baseline" in w and "Trendyol" in w
               for w in reg.warnings)


def test_enrichment_stops_after_consecutive_failures(tmp_path):
    calls = []

    def down(entry):
        calls.append(entry.id)
        raise ConnectionError

    rows = "".join(f"b{i},Brand {i},brand{i}.com,,,\n" for i in range(10))
    report = _sync(_reg(rows), tmp_path, enricher=down, max_failures=3)
    assert len(calls) == 3
    assert report.count(Action.CREATE) == 10  # every profile still written from the CSV
    assert any("stopped after 3 consecutive failures" in w for w in report.warnings)


def test_failed_refresh_keeps_previous_enrichment(tmp_path):
    reg = _reg("ziraat,Ziraat,ziraatbank.com.tr,,,\n")
    _sync(reg, tmp_path, enricher=lambda e: enrich_from_play(e, FakePlay(ZIRAAT_PLAY)))

    def down(entry):
        raise TimeoutError

    report = _sync(reg, tmp_path, enricher=down, refresh=True)
    assert _actions(report) == {"ziraat.json": Action.UNCHANGED}
    assert any("previous enrichment kept" in w for w in report.warnings)


# --- domain discovery (brand name only) ---------------------------------------

PARIBU_PLAY = [
    {"appId": "com.paribu.app", "title": "Paribu | Bitcoin Al Sat", "developer": "Paribu",
     "developerWebsite": "https://www.paribu.com", "realInstalls": 5_000_000},
    {"appId": "com.fake.paribu", "title": "Paribu Airdrop", "developer": "Paribu Destek",
     "developerWebsite": "https://paribu-airdrop.xyz", "realInstalls": 900},
    {"appId": "com.cointracker", "title": "Kripto Takip", "developer": "Tracker Ltd",
     "developerWebsite": "https://tracker.example.com", "realInstalls": 50_000},
]
PARIBU_GOOGLE = {
    "knowledgeGraph": {"title": "Paribu", "website": "https://www.paribu.com/"},
    "organic": [{"title": "Paribu - Wikipedia", "link": "https://tr.wikipedia.org/wiki/Paribu"},
                {"title": "Paribu", "link": "https://www.paribu.com/"}],
}


class FakeWeb:
    def __init__(self, result):
        self.result, self.calls = result, 0

    def lookup(self, query):
        self.calls += 1
        return self.result


def test_mentions_brand_ignores_generic_words():
    assert mentions_brand("Is Bankasi Mobil", "T\u00fcrkiye \u0130\u015f Bankas\u0131") is False
    assert mentions_brand("T\u00fcrkiye \u0130\u015f Bankas\u0131 A.\u015e.",
                          "T\u00fcrkiye \u0130\u015f Bankas\u0131")
    assert mentions_brand("Yap\u0131 Kredi Mobil", "Yap\u0131 Kredi")
    assert mentions_brand("mngkargo.com.tr", "MNG Kargo")
    assert not mentions_brand("Ziraat Mobil", "Paribu")


def test_discovery_needs_google_and_play_to_agree():
    found = discover_domain("Paribu", PARIBU_PLAY, PARIBU_GOOGLE)
    assert found.domains == ["paribu.com"]
    assert found.method == "google+play" and not found.review
    assert any("com.paribu.app" in e for e in found.evidence)


def test_discovery_never_takes_a_low_install_lookalike_site():
    only_fake = [PARIBU_PLAY[1]]
    assert discover_domain("Paribu", only_fake, None) is None
    # Google's result for a different site does not rescue it either
    assert discover_domain("Paribu", only_fake, {"organic": [
        {"title": "Paribu", "link": "https://paribu.com"}]}) is None


def test_discovery_single_source_rules_are_flagged_for_review():
    panel_only = discover_domain("Paribu", [], PARIBU_GOOGLE)
    assert panel_only.domains == ["paribu.com"] and panel_only.review
    play_only = discover_domain("Paribu", PARIBU_PLAY, None)
    assert play_only.domains == ["paribu.com"] and play_only.method == "play_popular_app"
    assert play_only.review


def test_discovery_skips_social_and_mail_hosts():
    play = [{"appId": "a.b.c", "title": "Paribu", "developer": "Paribu",
             "developerWebsite": "https://instagram.com/paribu",
             "developerEmail": "paribu@gmail.com", "realInstalls": 9_000_000}]
    assert discover_domain("Paribu", play, None) is None


def _resolver(play_listings, google):
    return OnlineResolver(FakePlay(play_listings), FakeWeb(google))


def test_brand_name_only_row_becomes_a_full_profile(tmp_path):
    reg = parse_registry("brand_name\nParibu\n", source="brands.csv")
    assert reg.ok
    resolver = _resolver(PARIBU_PLAY, PARIBU_GOOGLE)
    report = _sync(reg, tmp_path, enricher=resolver.enrich, discoverer=resolver.discover)
    assert _actions(report) == {"paribu.json": Action.CREATE}
    data = json.loads((tmp_path / "paribu.json").read_text(encoding="utf-8"))
    assert data["official_domains"] == ["paribu.com"]
    assert data["official_publishers"] == ["Paribu"]
    assert data["official_package_ids"] == ["com.paribu.app"]
    assert data[MANAGED_KEY]["discovery"]["method"] == "google+play"
    assert resolver.play.calls == 1  # discovery and enrichment share one Play search
    assert any("com.fake.paribu" in r for r in report.review)


def test_discovery_is_cached_and_csv_domain_wins(tmp_path):
    resolver = _resolver(PARIBU_PLAY, PARIBU_GOOGLE)
    kw = {"enricher": resolver.enrich, "discoverer": resolver.discover}
    _sync(parse_registry("brand_name\nParibu\n", source="brands.csv"), tmp_path, **kw)
    report = _sync(parse_registry("brand_name\nParibu\n", source="brands.csv"), tmp_path, **kw)
    assert resolver.web.calls == 1 and _actions(report) == {"paribu.json": Action.UNCHANGED}
    # a plain sync (no --enrich) keeps the discovered domain
    _sync(parse_registry("brand_name\nParibu\n", source="brands.csv"), tmp_path)
    assert json.loads((tmp_path / "paribu.json").read_text(encoding="utf-8"))[
        "official_domains"] == ["paribu.com"]
    # a domain typed into the CSV replaces the discovered one
    _sync(parse_registry("brand_name,official_domains\nParibu,paribu.com.tr\n",
                         source="brands.csv"), tmp_path)
    data = json.loads((tmp_path / "paribu.json").read_text(encoding="utf-8"))
    assert data["official_domains"] == ["paribu.com.tr"]
    assert "discovery" not in data[MANAGED_KEY]


def test_unresolved_brand_is_skipped_not_guessed(tmp_path):
    resolver = _resolver([], {"organic": []})
    report = _sync(parse_registry("brand_name\nNobody Knows Ltd\n"), tmp_path,
                   enricher=resolver.enrich, discoverer=resolver.discover)
    assert _actions(report) == {"nobody_knows_ltd.json": Action.SKIP_UNRESOLVED}
    assert not list(tmp_path.glob("*.json"))


def test_row_without_domain_and_without_enrich_is_skipped(tmp_path):
    report = _sync(parse_registry("brand_name\nParibu\n"), tmp_path)
    assert _actions(report) == {"paribu.json": Action.SKIP_UNRESOLVED}
    assert "sync --enrich" in report.changes[0].reason


def test_failed_lookup_keeps_a_previously_resolved_profile(tmp_path):
    resolver = _resolver(PARIBU_PLAY, PARIBU_GOOGLE)
    reg = parse_registry("brand_name\nParibu\n", source="brands.csv")
    _sync(reg, tmp_path, enricher=resolver.enrich, discoverer=resolver.discover)

    def down(entry):
        raise ConnectionError

    _sync(reg, tmp_path, enricher=down, discoverer=down, refresh=True)
    data = json.loads((tmp_path / "paribu.json").read_text(encoding="utf-8"))
    assert data["official_domains"] == ["paribu.com"]


def test_play_only_rule_needs_the_full_brand_name():
    calculator = [{"appId": "com.kredi.hesap", "title": "Kredi Hesaplama", "developer": "Hesap Ltd",
                   "developerWebsite": "https://kredihesap.example.com", "realInstalls": 5_000_000}]
    assert discover_domain("Yap\u0131 Kredi", calculator, None) is None
