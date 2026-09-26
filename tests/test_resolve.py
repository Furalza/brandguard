"""Input detection and brand resolution from a domain, a package id or a name.

All online parts are driven by fake Play / Google clients, so these tests pin
the trust rules (K-054/K-055 carried into the product): a domain the operator
typed is the anchor; a Play publisher is accepted only with a claim under that
domain AND an established app; single-source resolutions are flagged.
"""

import pytest

from brandguard.product.resolve import (
    detect_input,
    resolve_from_domain,
    resolve_from_name,
    resolve_from_package,
)

PLAY = {
    "com.mobillium.papara": {
        "appId": "com.mobillium.papara", "title": "Papara", "developer": "PAPARA",
        "developerWebsite": "https://www.papara.com", "developerEmail": "info@papara.com",
        "realInstalls": 21_000_000,
    },
    "com.papara.merchant": {
        "appId": "com.papara.merchant", "title": "Papara Ticari", "developer": "PAPARA",
        "developerWebsite": "https://www.papara.com", "realInstalls": 50_000,
    },
    "com.fake.papara": {
        "appId": "com.fake.papara", "title": "Papara Giris", "developer": "Papara Inc",
        "developerWebsite": "https://papara.com", "realInstalls": 500,
    },
    "com.other.wallet": {
        "appId": "com.other.wallet", "title": "Wallet", "developer": "Other Ltd",
        "developerWebsite": "https://other.example", "realInstalls": 9_000_000,
    },
}


class FakePlay:
    def __init__(self, hits=None, fail=False):
        self.hits = hits or list(PLAY)
        self.fail = fail

    def search(self, query, n_hits):
        if self.fail:
            raise ConnectionError("play down")
        return [{"appId": a, "title": PLAY[a]["title"], "developer": PLAY[a]["developer"]}
                for a in self.hits[:n_hits]]

    def details(self, app_id):
        return dict(PLAY[app_id])


class FakeWeb:
    def __init__(self, result=None):
        self.result = result or {}
        self.queries = []

    def lookup(self, query):
        self.queries.append(query)
        return self.result


@pytest.mark.parametrize("text,kind", [
    ("Papara", "brand"), ("Ziraat Bankası", "brand"), ("garanti bbva", "brand"),
    ("papara.com", "domain"), ("www.binance.com", "domain"), ("ziraatbank.com.tr", "domain"),
    ("https://www.papara.com/tr", "domain"),
    ("com.mobillium.papara", "package"), ("tr.com.ziraat.mobil", "package"),
    ("https://play.google.com/store/apps/details?id=com.mobillium.papara&hl=tr", "url"),
    ("https://apkpure.com/papara/com.mobillium.papara", "url"),
])
def test_detect_input(text, kind):
    assert detect_input(text).kind == kind


def test_detect_store_url_yields_package():
    d = detect_input("https://play.google.com/store/apps/details?id=com.mobillium.papara")
    assert d.package_id == "com.mobillium.papara"


def test_empty_input_rejected():
    with pytest.raises(ValueError):
        detect_input("   ")


def test_domain_resolves_name_and_verified_publisher():
    res = resolve_from_domain("papara.com", play=FakePlay(), web=None)
    p = res.profile
    assert p.brand_name == "PAPARA" and p.official_domains == ["papara.com"]
    assert p.official_publishers == ["PAPARA"]
    # every app of the established publisher, including the small one
    assert set(p.official_package_ids) == {"com.mobillium.papara", "com.papara.merchant"}
    # the impostor claims the domain but has 500 installs: review, never written
    assert "com.fake.papara" not in p.official_package_ids
    assert any("Papara Inc" in note for note in res.review)
    assert res.how == "domain+play" and not any("guessed" in n for n in res.review)


def test_domain_without_play_match_falls_back_and_flags_review():
    res = resolve_from_domain("newbrand.io", play=FakePlay(hits=["com.other.wallet"]), web=None,
                              page_title="NewBrand | Ödeme")
    assert res.profile.brand_name == "NewBrand"
    assert res.how == "domain+page_title"
    assert res.profile.official_publishers == []
    assert res.needs_review


def test_domain_when_play_is_down_still_resolves():
    res = resolve_from_domain("papara.com", play=FakePlay(fail=True), web=None)
    assert res.profile.official_domains == ["papara.com"]
    assert res.how == "domain_only" and res.needs_review


def test_package_resolves_through_its_developer_site():
    res = resolve_from_package("com.mobillium.papara", play=FakePlay(), web=None)
    assert res.profile.official_domains == ["papara.com"]
    assert res.how.startswith("package+domain")
    assert "com.mobillium.papara" in res.profile.official_package_ids


def test_small_package_is_scanned_but_not_assumed_official():
    res = resolve_from_package("com.fake.papara", play=FakePlay(), web=None)
    assert res.profile.official_domains == ["papara.com"]   # the claimed site is the input anchor
    assert "com.fake.papara" not in res.profile.official_package_ids
    assert any("below" in n for n in res.review)


def test_name_needs_two_sources_for_the_domain():
    web = FakeWeb({"organic": [{"link": "https://papara.com/", "title": "Papara"}]})
    res = resolve_from_name("Papara", play=FakePlay(), web=web)
    assert res.profile.official_domains == ["papara.com"]
    assert res.how == "name+google+play"
    assert not any("single source" in n for n in res.review)


def test_name_with_only_play_evidence_is_flagged():
    res = resolve_from_name("Papara", play=FakePlay(), web=None)
    assert res.profile.official_domains == ["papara.com"]
    assert res.how == "name+play_popular_app"
    assert any("single source" in n for n in res.review)


def test_name_with_nothing_is_name_only():
    res = resolve_from_name("Unknown Brand", play=FakePlay(hits=["com.other.wallet"]), web=FakeWeb())
    assert res.how == "name_only" and res.profile.official_domains == []
    assert res.needs_review


def test_domain_whose_label_finds_nothing_on_play_retries_with_the_page_title():
    class Play:
        def __init__(self):
            self.queries = []

        def search(self, query, n_hits):
            self.queries.append(query)
            if query == "Turkish Airlines":
                return [{"appId": "com.thy.mobile", "title": "Türk Hava Yolları", "developer": "Turkish Airlines"}]
            return []

        def details(self, app_id):
            return {"appId": app_id, "title": "Türk Hava Yolları", "developer": "Turkish Airlines",
                    "developerWebsite": "https://www.turkishairlines.com/", "realInstalls": 20_000_000}

    play = Play()
    res = resolve_from_domain("turkishairlines.com", play=play, web=None,
                              page_title="Turkish Airlines | Uçak Bileti Al")
    assert play.queries == ["turkishairlines", "Turkish Airlines"]
    assert res.how == "domain+play" and res.profile.brand_name == "Turkish Airlines"
    assert "com.thy.mobile" in res.profile.official_package_ids
