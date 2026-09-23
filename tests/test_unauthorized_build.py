"""Tests for the unauthorized-build (mod/cracked) repackaged veto."""

from brandguard.schema import AppRecord, BrandProfile, Label, Publisher
from brandguard.triage.veto import check_unauthorized_build_veto, check_vetoes

PROFILE = BrandProfile(
    brand_name="Spotify", official_domains=["spotify.com"],
    official_publishers=["Spotify AB"], known_official_apps=["Spotify"], sector="unknown",
)


def _rec(name, app_id="com.x.y", publisher="Third Party"):
    return AppRecord(app_id=app_id, source="serper:apkmirror.com", name=name,
                     publisher=Publisher(name=publisher))


def test_mod_build_is_repackaged():
    v = check_unauthorized_build_veto(_rec("Spotify Premium Mod", "com.spotify.mod"), PROFILE)
    assert v is not None and v.forced_label == Label.REPACKAGED


def test_cracked_build_is_repackaged():
    v = check_unauthorized_build_veto(_rec("Netflix Cracked", "com.netflix.cracked"), PROFILE)
    assert v is not None and v.forced_label == Label.REPACKAGED


def test_unlock_phrase_is_repackaged():
    v = check_unauthorized_build_veto(_rec("Spotify Premium Unlocked"), PROFILE)
    assert v is not None and v.forced_label == Label.REPACKAGED


def test_marker_in_package_id_is_repackaged():
    v = check_unauthorized_build_veto(_rec("GB WhatsApp", "com.gbwhatsapp.mod"), PROFILE)
    assert v is not None and v.forced_label == Label.REPACKAGED


def test_official_publisher_build_is_not_flagged():
    # An official publisher's build is legitimate however a mirror labels it.
    v = check_unauthorized_build_veto(_rec("Spotify Premium Mod", "com.spotify.mod", "Spotify AB"), PROFILE)
    assert v is None


def test_premium_alone_is_not_a_marker():
    # "premium" is a real product word; alone it must not fire.
    v = check_unauthorized_build_veto(_rec("Spotify Premium", "com.review.blog", "Blog"), PROFILE)
    assert v is None


def test_word_boundary_mod_not_in_model():
    # "mod" must not fire inside "model".
    v = check_unauthorized_build_veto(_rec("Model Maker Pro", "com.model.maker", "ToyCo"), PROFILE)
    assert v is None


def test_veto_chain_returns_repackaged():
    # End to end through check_vetoes.
    v = check_vetoes(_rec("Spotify Cracked", "com.spotify.cracked", "Pirate"), PROFILE)
    assert v is not None and v.forced_label == Label.REPACKAGED
