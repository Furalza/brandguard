"""Fixes from the first live runs of the v2 console (K-062, K-063).

  * the APK-site source crashed at normal/deep depth (max_queries None);
  * the brand's own small or regional apps ended as "related" because the
    publisher veto could not verify them; the Play developer account id now
    ties them to a verified official listing;
  * benign listings whose publisher identity points at the brand are shown as
    a possible affiliate instead of disappearing among related noise.
"""

from brandguard.discovery.live_google_play import _detail_to_record
from brandguard.hunt_engine import DEFAULTS, _triage_records, run_source
from brandguard.product.affiliate import brand_tokens, possible_affiliate
from brandguard.product.category import Category, DISPLAY_ORDER, app_category, category_of_row
from brandguard.schema import AppRecord, BrandProfile, Label, Publisher

PROFILE = BrandProfile(
    brand_name="Turkiye Is Bankasi", sector="banking",
    official_domains=["isbank.com.tr"],
    official_publishers=["Turkiye Is Bankasi A.S."],
    known_official_apps=["IsCep"],
    official_package_ids=["com.pozitron.iscep"],
    known_affiliates=["isbank.de"],
)


class _NoAdjudicator:
    def adjudicate(self, case):
        raise AssertionError("adjudicator must not be needed in these tests")


def _rec(app_id, name, publisher, *, account_id=None, website=None, downloads=None, **kw):
    return AppRecord(
        app_id=app_id, source="google_play_live", name=name,
        # live Play reports no account age and no app count: the verifier must
        # come from the package id, the website+installs pair or the account id
        publisher=Publisher(name=publisher, account_id=account_id, website=website),
        downloads=downloads, permissions=["INTERNET"], **kw,
    )


# --- A. serper budget None ---------------------------------------------------

def test_serper_source_accepts_unbounded_query_budget(monkeypatch):
    calls = []

    class Client:
        def search(self, query, num, page=1):
            calls.append(query)
            return []

    monkeypatch.setattr("brandguard.discovery.serper_source.get_serper_client", lambda: Client())
    monkeypatch.setattr("brandguard.triage.adjudicator.get_adjudicator", lambda: _NoAdjudicator())
    result = run_source(PROFILE, "serper", max_queries=None, pages=1)
    assert result.errors == [] and result.candidates == 0
    assert result.requests == len(calls) > DEFAULTS["serper"]["max_queries"]


# --- B. same developer account -----------------------------------------------

def test_detail_carries_developer_account_id():
    rec = _detail_to_record({"appId": "com.x", "title": "X", "developer": "D",
                             "developerId": "5551234567890"})
    assert rec.publisher.account_id == "5551234567890"
    assert _detail_to_record({"appId": "com.x", "title": "X"}).publisher.account_id is None


def test_small_app_from_verified_account_becomes_official():
    flagship = _rec("com.pozitron.iscep", "IsCep", "Turkiye Is Bankasi A.S.",
                    account_id="acc-1", website="https://www.isbank.com.tr", downloads=50_000_000)
    small = _rec("com.isbank.isim", "Isim", "Turkiye Is Bankasi A.S.",
                 account_id="acc-1", website="https://www.isbank.com.tr", downloads=40_000)
    rows, detected = _triage_records([flagship, small], PROFILE, _NoAdjudicator())
    by_id = {r["app_id"]: r for r in rows}
    assert by_id["com.pozitron.iscep"]["label"] == "official"
    assert by_id["com.isbank.isim"]["label"] == "official"
    assert by_id["com.isbank.isim"]["reason"] == "same_developer_account"
    assert by_id["com.isbank.isim"]["category"] == "official"
    assert any(e["signal"] == "developer_account" for e in by_id["com.isbank.isim"]["evidence_detail"])
    assert detected == 0


def test_other_account_is_not_promoted_even_with_official_name():
    flagship = _rec("com.pozitron.iscep", "IsCep", "Turkiye Is Bankasi A.S.",
                    account_id="acc-1", website="https://www.isbank.com.tr", downloads=50_000_000)
    impostor = _rec("com.fake.iscep", "IsCep Giris", "Turkiye Is Bankasi A.S.",
                    account_id="acc-2", website="https://www.isbank.com.tr", downloads=300)
    rows, _ = _triage_records([flagship, impostor], PROFILE, _NoAdjudicator())
    by_id = {r["app_id"]: r for r in rows}
    assert by_id["com.fake.iscep"]["label"] != "official"


def test_records_without_account_id_are_untouched():
    flagship = _rec("com.pozitron.iscep", "IsCep", "Turkiye Is Bankasi A.S.",
                    website="https://www.isbank.com.tr", downloads=50_000_000)
    small = _rec("com.isbank.isim", "Isim", "Turkiye Is Bankasi A.S.",
                 website="https://www.isbank.com.tr", downloads=40_000)
    rows, _ = _triage_records([flagship, small], PROFILE, _NoAdjudicator())
    by_id = {r["app_id"]: r for r in rows}
    assert by_id["com.isbank.isim"]["label"] != "official"


# --- C. possible affiliate ---------------------------------------------------

def test_brand_tokens_come_from_domain_and_distinctive_words():
    toks = brand_tokens(PROFILE)
    assert "isbank" in toks and "turkiyeisbankasi" in toks
    assert "bank" not in toks and "turkiye" not in toks


def test_official_name_without_verifier_is_an_affiliate_hint():
    small = _rec("com.isbank.isim", "Isim Kolay", "Turkiye Is Bankasi A.S.",
                 website="https://www.isbank.com.tr", downloads=40_000)
    hint = possible_affiliate(small, PROFILE, Label.THIRD_PARTY)
    assert hint and "matches the official publisher name" in hint


def test_regional_publisher_is_an_affiliate_hint():
    de = _rec("de.isbank.BVFinApp", "Isbank", "Isbank AG", website="https://www.isbank.de",
              downloads=20_000)
    hint = possible_affiliate(de, PROFILE, Label.THIRD_PARTY)
    assert hint and "isbank" in hint
    generic = _rec("com.atm.finder", "ATM Bul", "Some Dev Ltd", website="https://atmbul.com")
    assert possible_affiliate(generic, PROFILE, Label.THIRD_PARTY) is None


def test_affiliate_hint_never_softens_a_threat_verdict():
    from brandguard.schema import Evidence

    de = _rec("de.isbank.BVFinApp", "Isbank", "Isbank AG")
    assert possible_affiliate(de, PROFILE, Label.IMPERSONATION) is None
    # uncertain without evidence context: no hint
    assert possible_affiliate(de, PROFILE, Label.UNCERTAIN) is None
    # uncertain on words alone (name + adjudicator): a brand-named publisher is a possible affiliate (K-074)
    words_only = [Evidence(signal="name_similarity", weight=0.45, tier=0, text="starts with brand"),
                  Evidence(signal="adjudicator", weight=0.48, tier=2, text="claims official")]
    assert possible_affiliate(de, PROFILE, Label.UNCERTAIN, words_only) is not None
    # but not when an attacker-independent signal accuses it
    young = [*words_only, Evidence(signal="account_age", weight=0.7, tier=0, text="created 9 days ago")]
    assert possible_affiliate(de, PROFILE, Label.UNCERTAIN, young) is None
    # and never for a publisher that does not name the brand
    stranger = _rec("com.x.y", "Isbank Giris", "Hizli Yazilim")
    assert possible_affiliate(stranger, PROFILE, Label.UNCERTAIN, words_only) is None
    assert app_category(Label.UNCERTAIN, affiliate_hint=True) is Category.AFFILIATE
    assert app_category(Label.IMPERSONATION, affiliate_hint=True) is Category.MALICIOUS
    assert app_category(Label.THIRD_PARTY, affiliate_hint=True) is Category.AFFILIATE
    assert category_of_row({"label": "third_party_legitimate", "affiliate_hint": True}) is Category.AFFILIATE
    assert DISPLAY_ORDER.index(Category.AFFILIATE) > DISPLAY_ORDER.index(Category.OFFICIAL)


def test_triage_rows_carry_affiliate_hint_and_facts():
    de = _rec("de.isbank.BVFinApp", "Isbank", "Isbank AG", website="https://www.isbank.de",
              downloads=20_000)
    rows, _ = _triage_records([de], PROFILE, _NoAdjudicator())
    row = rows[0]
    assert row["label"] in ("third_party_legitimate", "unrelated")
    assert row["category"] == "affiliate" and row["affiliate_hint"] is True
    assert row["facts"]["publisher"] == "Isbank AG" and row["facts"]["installs"] == 20_000
    assert any(e["signal"] == "affiliate_hint" for e in row["evidence_detail"])


# --- Play: a no-result page is an empty result, not a failed query ------------

def test_play_search_treats_library_typeerror_as_no_results(monkeypatch):
    from brandguard.discovery import play_search

    def boom(query, n_hits, lang, country):
        raise TypeError("'NoneType' object is not subscriptable")

    monkeypatch.setattr("google_play_scraper.search", boom)
    assert play_search.search("tturkiye is bankasi", n_hits=5) == []


# --- a platform's own site is not "not a brand site" for that platform -------

def test_platform_brand_resolves_to_its_own_excluded_domain():
    from brandguard.registry import _is_brand_site

    assert _is_brand_site("tiktok.com") is False           # a listing pointing at TikTok
    assert _is_brand_site("tiktok.com", "TikTok") is True   # TikTok itself
    assert _is_brand_site("www.tiktok.com", "TikTok Pte. Ltd.") is True
    assert _is_brand_site("facebook.com", "TikTok") is False


def test_package_of_a_platform_resolves_its_domain():
    from brandguard.product.resolve import resolve_from_package

    class Play:
        def details(self, app_id):
            return {"appId": app_id, "title": "TikTok", "developer": "TikTok Pte. Ltd.",
                    "developerWebsite": "https://www.tiktok.com/", "realInstalls": 3_000_000_000}

        def search(self, query, n_hits):
            return [{"appId": "com.zhiliaoapp.musically", "title": "TikTok", "developer": "TikTok Pte. Ltd."}]

    res = resolve_from_package("com.zhiliaoapp.musically", play=Play(), web=None)
    assert res.profile.official_domains == ["tiktok.com"]
    assert "com.zhiliaoapp.musically" in res.profile.official_package_ids


def test_play_run_fetches_official_anchors_directly(monkeypatch):
    from brandguard.discovery import live_google_play as lgp
    from brandguard.hunt_engine import _Trace, _run_play

    lgp.clear_detail_cache()
    monkeypatch.setattr(lgp, "_paced", lambda: None)
    fetched = []

    def fake_app(app_id, lang, country):
        fetched.append((app_id, lang))
        title = "IsCep: Banking & Finance" if lang == "en" else "IsCep"
        return {"appId": app_id, "title": title, "developer": "Turkiye Is Bankasi A.S.",
                "developerWebsite": "https://www.isbank.com.tr", "realInstalls": 50_000_000}

    monkeypatch.setattr("google_play_scraper.app", fake_app)
    monkeypatch.setattr("brandguard.discovery.play_search.search", lambda *a, **k: [])
    trace = _Trace()
    rows, detected, _ = _run_play(PROFILE, max_queries=1, hits=3, adjudicator=_NoAdjudicator(), trace=trace)
    # the listing once (tr) plus its English title (K-081), nothing else
    assert fetched == [("com.pozitron.iscep", "tr"), ("com.pozitron.iscep", "en")]
    assert trace.measurements["official_titles"] == ["IsCep: Banking & Finance"]
    assert [r["label"] for r in rows] == ["official"] and trace.warnings == []
    lgp.clear_detail_cache()


def test_mod_of_the_brands_app_name_is_still_a_takedown_for_a_generic_brand_name():
    # "Turkiye Is Bankasi" has no distinctive word; its app name "IsCep" and
    # its domain label "isbank" identify it instead.
    from brandguard.triage.veto import check_unauthorized_build_veto

    mod = AppRecord(app_id="https://apkdone.com/iscep-mod/", source="serper:apkdone.com",
                    name="IsCep Mod APK v9.1 (Premium Unlocked)", publisher=Publisher(name=""))
    v = check_unauthorized_build_veto(mod, PROFILE)
    assert v is not None and v.forced_label == Label.REPACKAGED
    other = AppRecord(app_id="https://apkdone.com/amazon-music/", source="serper:apkdone.com",
                      name="Amazon Music MOD APK 26.26.1 (Premium Unlocked)", publisher=Publisher(name=""))
    assert check_unauthorized_build_veto(other, PROFILE) is None


# --- K-068: modded companion apps are not the brand's takedown ---------------

def _serper(name, url):
    return AppRecord(app_id=url, source="serper:apkdone.com", name=name,
                     publisher=Publisher(name=""), raw={"page_kind": "listing"})


INSTAGRAM = BrandProfile(brand_name="Instagram", official_domains=["instagram.com"],
                         official_publishers=["Instagram"], known_official_apps=["Instagram"],
                         official_package_ids=["com.instagram.android"], sector="social")


def test_modded_companion_app_is_related_not_malicious():
    rows, detected = _triage_records([
        _serper("Video Downloader for Instagram MOD APK 3.25.0", "https://apkdone.com/vd-insta/"),
        _serper("Download Preview for Instagram Feed (MOD) APK for Android", "https://preview.apk.dog/"),
        _serper("Instagram MOD APK v448.0.052.84 Download For Android", "https://apkdone.com/instagram/"),
        _serper("Elite Instagram Mod Apk v530 (Unlocked Premium)", "https://gamekillerapp.com/insta/"),
    ], INSTAGRAM, _NoAdjudicator())
    by = {r["app_id"]: r for r in rows}
    assert by["https://apkdone.com/vd-insta/"]["category"] == "related"
    assert by["https://preview.apk.dog/"]["category"] == "related"
    assert any(e["signal"] == "companion_build" for e in by["https://apkdone.com/vd-insta/"]["evidence_detail"])
    assert by["https://apkdone.com/instagram/"]["label"] == "repackaged"
    assert by["https://gamekillerapp.com/insta/"]["label"] == "repackaged"
    assert detected == 2


def test_brands_own_secondary_app_mod_is_still_a_takedown():
    spotify = BrandProfile(brand_name="Spotify", official_domains=["spotify.com"],
                           official_publishers=["Spotify AB"], known_official_apps=["Spotify"],
                           sector="media")
    rows, detected = _triage_records([
        _serper("Download Spotify for Artists (MOD) APK for Android", "https://s4a.apk.dog/"),
        _serper("Download Stats for Spotify - Receiptify (MOD) APK", "https://stats.apk.dog/"),
    ], spotify, _NoAdjudicator())
    by = {r["app_id"]: r for r in rows}
    assert by["https://s4a.apk.dog/"]["label"] == "repackaged"       # brand leads: its own app
    assert by["https://stats.apk.dog/"]["category"] == "related"      # brand is the object


# --- complaint boards and forums are not listings ------------------------------

def test_complaint_and_forum_pages_are_articles():
    from brandguard.discovery.serper_source import page_kind

    assert page_kind("https://www.sikayetvar.com/papara/uygulama") == "article"
    assert page_kind("https://xdaforums.com/t/app-mod-instagram-without-ads.123/") == "article"
    assert page_kind("https://apkdone.com/instagram/") == "listing"


# --- store and platform URLs as input -----------------------------------------

def test_play_developer_url_is_a_brand_name_input():
    from brandguard.product.resolve import detect_input

    d = detect_input("https://play.google.com/store/apps/developer?id=TikTok+Pte.+Ltd.&hl=tr")
    assert d.kind == "brand" and d.value == "TikTok Pte. Ltd."


def test_platform_domains_are_refused_as_brand_domains():
    import pytest

    from brandguard.product.resolve import resolve_from_domain

    with pytest.raises(ValueError, match="store or platform"):
        resolve_from_domain("play.google.com", play=None, web=None)
    # a typed social-network domain is the brand itself
    res = resolve_from_domain("facebook.com", play=None, web=None, page_title="Facebook")
    assert res.profile.official_domains == ["facebook.com"]


# --- K-070: an app's own name is not a brand mention -------------------------

def test_official_claim_about_another_owner_is_not_a_brand_claim():
    from brandguard.triage.adjudicator import build_case_summary

    pegasus = BrandProfile(brand_name="Pegasus", official_domains=["flypgs.com"],
                           official_publishers=["Pegasus Airlines"], known_official_apps=[],
                           sector="travel")
    books = AppRecord(app_id="com.bjain.plusapp", source="google_play_live", name="Pegasus Plus",
                      publisher=Publisher(name="BJAIN Apps"), downloads=1000,
                      description="PegasusPlus is the official companion app for parents using "
                                  "books from BJain Publishers. Scan a book cover to get worksheets.")
    case = build_case_summary(books, pegasus, [])
    assert case.description_claims_official is False
    assert case.description_names_brand is False

    fake = AppRecord(app_id="com.x.pegasus", source="google_play_live", name="Pegasus Bilet",
                     publisher=Publisher(name="Somebody"),
                     description="Pegasus Airlines resmi bilet uygulamasi. Ucuza ucun.")
    case = build_case_summary(fake, pegasus, [])
    assert case.description_claims_official is True and case.description_names_brand is True


# --- K-071: dictionary-word brands ------------------------------------------

def test_phone_model_named_after_the_brand_is_not_a_takedown():
    from brandguard.triage.veto import check_unauthorized_build_veto

    pegasus = BrandProfile(brand_name="pegasus", official_domains=["flypgs.com"],
                           official_publishers=["Pegasus Airlines"], known_official_apps=[], sector="travel")
    rec = _serper("Vegas Crime Simulator (MOD) for Asus Pegasus 5000", "https://vegas-crime-simulator.apk.dog/asus/pegasus-5000")
    assert check_unauthorized_build_veto(rec, pegasus) is None
    own = _serper("Pegasus Ucak Bileti (MOD) APK", "https://pegasus.apk.dog/")
    assert check_unauthorized_build_veto(own, pegasus) is not None


def test_identity_terms_name_the_brand_more_precisely():
    from brandguard.hunt_engine import identity_terms

    pegasus = BrandProfile(brand_name="pegasus", official_domains=["flypgs.com"],
                           official_publishers=["Pegasus Airlines"],
                           known_official_apps=["Pegasus - En Uygun Ucak Bileti"], sector="travel")
    assert identity_terms(pegasus) == ["Pegasus Airlines", "Pegasus - En Uygun Ucak Bileti"]
    # a brand whose publisher and app carry no extra words adds nothing
    assert identity_terms(BrandProfile(brand_name="Papara", official_domains=["papara.com"],
                                       official_publishers=["PAPARA"], known_official_apps=["Papara"],
                                       sector="fintech")) == []


def test_apk_search_adds_identity_terms(monkeypatch):
    from brandguard.discovery.serper_source import search_apks

    seen = []

    class Client:
        def search(self, query, num, page=1):
            seen.append(query)
            return []

    search_apks("pegasus", client=Client(), max_queries=1, extra_terms=["Pegasus Airlines"])
    assert seen == ['"pegasus" apk -site:play.google.com', '"Pegasus Airlines" apk -site:play.google.com']


def test_ambiguous_brand_word_softens_unanchored_mods_only():
    from brandguard.hunt_engine import brand_word_ambiguity

    pegasus = BrandProfile(brand_name="pegasus", official_domains=["flypgs.com"],
                           official_publishers=["Pegasus Airlines"],
                           known_official_apps=["Pegasus - En Uygun Ucak Bileti"], sector="travel")
    batch = [_serper(n, f"https://x{i}.apk.dog/") for i, n in enumerate([
        "Pegasus VPN APK", "Pegasus Browser APK", "Pegasus Keyboard APK", "Pegasus Travel APK",
        "Pegasus Education App", "Download Little Pegasus (MOD) APK for Android",
        "Pegasus Ucak Bileti (MOD) APK", "Pegasus Airlines MOD APK",
    ])]
    assert brand_word_ambiguity(batch, pegasus) >= 4
    rows, detected = _triage_records(batch, pegasus, _NoAdjudicator())
    by = {r["name"]: r for r in rows}
    assert by["Download Little Pegasus (MOD) APK for Android"]["category"] == "suspicious"
    assert by["Download Little Pegasus (MOD) APK for Android"]["reason"] == "ambiguous_brand_word"
    assert by["Pegasus Ucak Bileti (MOD) APK"]["category"] == "malicious"
    assert by["Pegasus Airlines MOD APK"]["category"] == "malicious"
    assert detected == 2


def test_brand_whose_domain_is_its_name_is_never_ambiguous():
    spotify = BrandProfile(brand_name="Spotify", official_domains=["spotify.com"],
                           official_publishers=["Spotify AB"], known_official_apps=["Spotify"], sector="media")
    batch = [_serper(n, f"https://x{i}.apk.dog/") for i, n in enumerate([
        "Spotify Premium MOD APK", "Spotify Lite APK", "Spotify Kids APK", "Spotify Stats APK",
        "Spotify Wrapped APK", "Spotify Connect APK",
    ])]
    rows, _ = _triage_records(batch, spotify, _NoAdjudicator())
    assert {r["name"]: r["category"] for r in rows}["Spotify Premium MOD APK"] == "malicious"


# --- second live round: 16 brands ---------------------------------------------

def test_legal_suffixes_are_not_part_of_a_brand_name():
    from brandguard.registry import clean_brand_name

    assert clean_brand_name("WhatsApp LLC") == "WhatsApp"
    assert clean_brand_name("Netflix, Inc.") == "Netflix"
    assert clean_brand_name("TikTok Pte. Ltd.") == "TikTok"
    assert clean_brand_name("Türkiye İş Bankası A.Ş.") == "Türkiye İş Bankası"
    assert clean_brand_name("Pegasus Airlines") == "Pegasus Airlines"
    assert clean_brand_name("AG") == "AG"  # never emptied


def test_sector_words_do_not_make_affiliates():
    yk = BrandProfile(brand_name="Yapı Kredi", official_domains=["yapikredi.com.tr"],
                      official_publishers=["Yapı ve Kredi Bankası A.Ş."], known_official_apps=["Yapı Kredi Mobil"],
                      sector="banking")
    loan = _rec("com.hizli.kredi", "Hızlı Kredi", "HIZLI KREDİ", website="https://hizlikredi.com", downloads=50_000)
    assert possible_affiliate(loan, yk, Label.THIRD_PARTY) is None
    nl = _rec("nl.yapikredi.mobile", "Yapi Kredi Nederland", "YAPI KREDI BANK NEDERLAND N.V.",
              website="https://yapikredi.nl", downloads=20_000)
    assert possible_affiliate(nl, yk, Label.THIRD_PARTY) is not None


def test_page_on_the_official_domain_is_noise():
    binance = BrandProfile(brand_name="Binance", official_domains=["binance.com"],
                           official_publishers=["Binance Inc."], known_official_apps=["Binance"], sector="crypto")
    rec = _serper("Binance app download complete guide 2026", "https://www.binance.com/en/download")
    rows, detected = _triage_records([rec], binance, _NoAdjudicator())
    assert rows[0]["category"] == "noise" and rows[0]["reason"] == "non_listing_official_site"
    assert detected == 0


def test_ambiguity_rule_is_off_when_any_brand_word_is_the_domain():
    from brandguard.hunt_engine import _strong_identity_tokens

    wa = BrandProfile(brand_name="WhatsApp LLC", official_domains=["whatsapp.com"],
                      official_publishers=["WhatsApp LLC"], known_official_apps=["WhatsApp Messenger"],
                      sector="social")
    assert _strong_identity_tokens(wa) == set()


def test_platform_domain_is_refused_even_when_a_stale_brand_exists(tmp_path, monkeypatch):
    import pytest

    from brandguard.api import db as dbmod
    from brandguard.api import scan_service
    from brandguard.api.models import Brand

    monkeypatch.setenv("BRANDGUARD_DATABASE_URL", f"sqlite:///{tmp_path / 'p.db'}")
    monkeypatch.setenv("BRANDGUARD_ENV_FILE", str(tmp_path / "none.env"))
    dbmod.reset_engine()
    dbmod.init_db()
    with dbmod.session_scope() as session:
        session.add(Brand(id="google_llc", brand_name="Google LLC", sector="unknown",
                          official_domains=["play.google.com"], official_publishers=["Google LLC"],
                          official_package_ids=[], known_official_apps=[], known_affiliates=[],
                          resolved_from="auto"))
    with dbmod.session_scope() as session:
        with pytest.raises(ValueError, match="store or platform"):
            scan_service.resolve_input(session, "play.google.com", clients=lambda: (None, None))
    dbmod.reset_engine()


# --- K-075: Play publishers measure how shared the brand word is ---------------

def test_play_ambiguity_counts_other_publishers_leading_with_the_brand_word():
    from brandguard.hunt_engine import play_name_ambiguity

    wise = BrandProfile(brand_name="Wise", official_domains=["wise.com"],
                        official_publishers=["Wise Payments Ltd."], known_official_apps=["Wise"], sector="fintech")
    records = [
        _rec("com.wise", "Wise", "Wise Payments Ltd.", downloads=50_000_000),
        _rec("com.a.wisepdf", "Wise PDF", "PDF Tools Inc", description="Wise PDF reads and annotates PDF files."),
        _rec("com.b.wisetime", "Wise Timetable", "School Apps", description="Plan your school week."),
        _rec("com.c.doctorwise", "Wise Doctor", "Health Co", description="Talk to a doctor."),
        _rec("com.wisevets", "Wise Vets", "WISE VETS", description="Vet clinic app."),   # carries the word: subsidiary or namesake, not counted
        _rec("com.stats.wise", "Stats for Wise", "Someone", description="Statistics for your Wise account."),   # companion: does not lead
        _rec("com.ninja", "Wise Ninja - Notifier", "Anvith", description="Get alerts from your Wise transfers."),   # leads, but is about the brand
        _rec("com.nodesc", "Wise Notes", "Nobody"),                 # no description: no evidence
    ]
    assert play_name_ambiguity(records, wise) == 3
    garanti = BrandProfile(brand_name="Garanti BBVA", official_domains=["garantibbva.com.tr"],
                           official_publishers=["T. Garanti Bankasi A.S."], known_official_apps=[], sector="banking")
    subs = [_rec("com.g.trader", "Garanti BBVA I-Trader", "Garanti Yatirim Menkul"),
            _rec("com.g.ro", "Garanti BBVA Romania", "Garanti BBVA Romania"),
            _rec("com.g.em", "Garanti BBVA Emeklilik", "Garanti Emeklilik")]
    assert play_name_ambiguity(subs, garanti) == 0


def test_play_measurement_turns_the_ambiguity_rule_on_for_a_dictionary_word_brand():
    wise = BrandProfile(brand_name="Wise", official_domains=["wise.com"],
                        official_publishers=["Wise Payments Ltd."], known_official_apps=["Wise"],
                        sector="fintech", brand_word_shared_by=3)
    rows, detected = _triage_records([
        _serper("Download Wise Budget: Spending & Debts (MOD) APK", "https://wise-budget.apk.dog/"),
        _serper("Download Wise PDF - Read PDF (MOD) APK", "https://wise-pdf.apk.dog/"),
        _serper("Wise Payments MOD APK (Unlocked)", "https://x.apk.dog/"),
    ], wise, _NoAdjudicator())
    by = {r["name"]: r for r in rows}
    assert by["Download Wise Budget: Spending & Debts (MOD) APK"]["category"] == "suspicious"
    assert by["Download Wise PDF - Read PDF (MOD) APK"]["reason"] == "ambiguous_brand_word"
    assert by["Wise Payments MOD APK (Unlocked)"]["category"] == "malicious"   # names the publisher
    assert detected == 1
    # without the measurement (None) the domain heuristic keeps the old behaviour
    plain = wise.model_copy(update={"brand_word_shared_by": None})
    rows, _ = _triage_records([_serper("Download Wise PDF (MOD) APK", "https://wise-pdf.apk.dog/")], plain, _NoAdjudicator())
    assert rows[0]["category"] == "malicious"


def test_play_run_records_the_measurement(monkeypatch):
    from brandguard.discovery import live_google_play as lgp
    from brandguard.hunt_engine import run_source

    lgp.clear_detail_cache()
    monkeypatch.setattr(lgp, "_paced", lambda: None)
    hits = [{"appId": "com.a.wisepdf", "title": "Wise PDF", "developer": "PDF Tools Inc", "description": "Read PDFs."},
            {"appId": "com.b.wisetime", "title": "Wise Timetable", "developer": "School Apps", "description": "School week."},
            {"appId": "com.c.doctorwise", "title": "Wise Doctor", "developer": "Health Co", "description": "Doctors."}]
    monkeypatch.setattr("brandguard.discovery.play_search.search", lambda *a, **k: hits)
    monkeypatch.setattr("google_play_scraper.app", lambda app_id, lang, country: next(h for h in hits if h["appId"] == app_id))
    monkeypatch.setattr("brandguard.triage.adjudicator.get_adjudicator", lambda: _NoAdjudicator())
    wise = BrandProfile(brand_name="Wise", official_domains=["wise.com"],
                        official_publishers=["Wise Payments Ltd."], known_official_apps=["Wise"], sector="fintech")
    result = run_source(wise, "play", max_queries=1, hits=3)
    assert result.measurements["brand_word_shared_by"] == 3
    assert any("other publishers" in w for w in result.warnings)
    lgp.clear_detail_cache()


# --- mirrors are explained, not accused ---------------------------------------

def test_mirror_listing_of_the_official_app_is_explained():
    from brandguard.triage.adjudicator import AdjudicatorOpinion

    class Accuser:
        def adjudicate(self, case):
            return AdjudicatorOpinion(leaning="impersonation", strength=0.48, reasoning="claims official")

    lcw = BrandProfile(brand_name="LC Waikiki", official_domains=["lcw.com"],
                       official_publishers=["LC Waikiki"], known_official_apps=["LCW: Giyim & Online Alisveris"],
                       sector="retail")
    rows, detected = _triage_records([
        _serper("LC Waikiki for Android - Download the APK from Uptodown", "https://lc-waikiki.en.uptodown.com/android"),
        _serper("LCWAIKIKI Maroc (MOD) 3.0", "https://apk.dog/download?file_id=1"),
    ], lcw, Accuser())
    by = {r["app_id"]: r for r in rows}
    mirror = by["https://lc-waikiki.en.uptodown.com/android"]
    assert mirror["category"] == "suspicious" and mirror["reason"] == "mirror_unverified"
    assert mirror["evidence_detail"][0]["signal"] == "mirror_listing"
    assert not any(e["signal"] == "adjudicator" for e in mirror["evidence_detail"])
    assert by["https://apk.dog/download?file_id=1"]["category"] == "malicious"


def test_three_letter_brands_have_an_identity_matched_as_a_whole_word():
    from brandguard.registry import identity_tokens, names_identity

    toks = identity_tokens("QNB", ["qnb.com.tr"])
    assert "qnb" in toks
    assert names_identity("PT Bank QNB Indonesia", toks) == "qnb"
    assert names_identity("QNB Yatırım Menkul Değerler A.Ş.", toks) == "qnb"
    bim = identity_tokens("BİM", ["bim.com.tr"])
    assert names_identity("Bimbo Bakeries", bim) is None
    assert names_identity("BİM Birleşik Mağazalar", bim) == "bim"


def test_ambiguous_brand_anchors_apk_queries_with_an_identity_word(monkeypatch):
    from brandguard.hunt_engine import run_source

    seen = []

    class Client:
        def search(self, query, num, page=1):
            seen.append(query)
            return []

    monkeypatch.setattr("brandguard.discovery.serper_source.get_serper_client", lambda: Client())
    monkeypatch.setattr("brandguard.triage.adjudicator.get_adjudicator", lambda: _NoAdjudicator())
    pegasus = BrandProfile(brand_name="pegasus", official_domains=["flypgs.com"],
                           official_publishers=["Pegasus Airlines"],
                           known_official_apps=["Pegasus - En Uygun Ucak Bileti"], sector="travel",
                           brand_word_shared_by=4)
    result = run_source(pegasus, "serper", max_queries=3, pages=1)
    anchored = [q for q in seen if q.startswith('"pegasus" ') and " apk" in q and "download mod" not in q]
    assert anchored and all(q.split()[1] in ("ucak", "bileti", "uygun", "flypgs", "airlines") for q in anchored)
    assert any("download mod" in q and q.startswith('"pegasus" apk') for q in seen)   # the mod dork stays bare
    assert any("anchored" in w for w in result.warnings)
    # an unambiguous brand keeps the bare queries
    seen.clear()
    run_source(pegasus.model_copy(update={"brand_word_shared_by": 0}), "serper", max_queries=2, pages=1)
    assert seen[0] == '"pegasus" apk -site:play.google.com'
