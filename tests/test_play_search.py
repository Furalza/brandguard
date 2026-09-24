"""The featured top search result must keep its package id (K-056).

The page below follows the structure google-play-scraper 1.2.7 parses: a
``ds:4`` block whose regular results carry ids as ["<package>", 7] and whose
top card no longer has the id where the library looks ([11, 0, 0]).
"""

import json

import pytest

pytest.importorskip("google_play_scraper")

import google_play_scraper.features.search as library_search_module
from google_play_scraper.constants.element import ElementSpec, ElementSpecs

from brandguard.discovery import play_search
from brandguard.discovery.play_search import find_app_id

TOP_ID = "com.mobillium.papara"
SIMILAR_ID = "com.enparabank.retail"


def _top_card():
    card = [None] * 12
    details = [None] * 80
    details[0] = ["Papara"]
    details[68] = ["PAPARA"]
    details[13] = ["10.000.000+"]
    details[77] = [[TOP_ID, 7], f"/store/apps/details?id={TOP_ID}"]
    details[78] = [[[None, None, None, [None, None, "https://img"]]]]
    details[79] = [[["Finans"]]]
    card[2] = details
    card[5] = [[TOP_ID, 7]]
    card[9] = [[SIMILAR_ID, 7]]  # a similar app shown on the card
    return card


def _regular(app_id, title):
    return [[[app_id, 7], None, None, title]]


def _page():
    block = [None] * 24
    block[22] = [[_regular("com.papara.merchant", "Papara Ticari"),
                  _regular("com.provisionpay.softpos.papara", "Papara CepPOS")]]
    block[23] = [None] * 16 + [_top_card()]
    ds4 = [[None, [block]]]
    return ("<script>AF_initDataCallback({key: 'ds:4', hash: '1', data:"
            + json.dumps(ds4) + ", sideChannel: {}});</script>")


@pytest.fixture
def fake_play(monkeypatch):
    monkeypatch.setattr(library_search_module, "get", lambda url: _page())


@pytest.fixture
def original_spec(monkeypatch):
    monkeypatch.setitem(ElementSpecs.SearchResultOnTop, "appId", ElementSpec(None, [11, 0, 0]))


def test_library_alone_loses_the_top_result_id(fake_play, original_spec):
    from google_play_scraper import search

    hits = search("Papara", n_hits=5, lang="tr", country="tr")
    assert hits[0]["title"] == "Papara" and hits[0]["appId"] is None  # the live bug


def test_top_result_id_is_recovered(fake_play, original_spec):
    hits = play_search.search("Papara", n_hits=5, lang="tr", country="tr")
    assert hits[0]["appId"] == TOP_ID
    assert hits[0]["developer"] == "PAPARA"
    # the library fills n results including the top one; the regular list follows it
    assert hits[1]["appId"] == "com.papara.merchant"


def test_most_frequent_id_wins_over_a_similar_app():
    assert find_app_id(_top_card()) == TOP_ID


def test_details_link_alone_is_enough():
    link = "https://play.google.com/store/apps/details?id=com.a.b&hl=tr"
    assert find_app_id(["x", [link]]) == "com.a.b"


def test_nothing_recognisable_keeps_none():
    assert find_app_id([["not a package", 7], ["com.a.b", 8], [True, 7], "text"]) is None


def test_duplicate_ids_are_removed(monkeypatch):
    monkeypatch.setattr(
        "google_play_scraper.search",
        lambda *a, **k: [{"appId": "a.b"}, {"appId": "a.b"}, {"appId": None}, {"appId": "c.d"}],
    )
    assert [h["appId"] for h in play_search.search("q")] == ["a.b", None, "c.d"]
