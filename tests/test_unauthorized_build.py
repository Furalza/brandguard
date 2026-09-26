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
    v = check_unauthorized_build_veto(_rec("Spotify Cracked", "com.spotify.cracked"), PROFILE)
    assert v is not None and v.forced_label == Label.REPACKAGED


def test_mod_of_another_product_is_not_this_brands_takedown():
    # K-065: "Amazon Music MOD" on a Spotify scan is a real repackaged app, but
    # not of Spotify. Without a brand relation the veto stays silent and the
    # scored signals read the hit as unrelated.
    v = check_unauthorized_build_veto(_rec("Netflix Cracked", "com.netflix.cracked"), PROFILE)
    assert v is None
    netflix = BrandProfile(brand_name="Netflix", official_domains=["netflix.com"],
                           official_publishers=["Netflix, Inc."], known_official_apps=["Netflix"],
                           sector="unknown")
    v = check_unauthorized_build_veto(_rec("Netflix Cracked", "com.netflix.cracked"), netflix)
    assert v is not None and v.forced_label == Label.REPACKAGED


def test_store_index_page_with_mod_in_title_is_not_a_takedown():
    v = check_unauthorized_build_veto(
        _rec("Android Apps & MOD APKs Download with Safety 2026 - Page 2",
             "https://apkdone.com/app/page/2/"), PROFILE)
    assert v is None


def test_unlock_phrase_is_repackaged():
    v = check_unauthorized_build_veto(_rec("Spotify Premium Unlocked"), PROFILE)
    assert v is not None and v.forced_label == Label.REPACKAGED


def test_marker_in_package_id_is_repackaged():
    profile = BrandProfile(brand_name="WhatsApp", official_domains=["whatsapp.com"],
                           official_publishers=["WhatsApp LLC"], known_official_apps=["WhatsApp"],
                           sector="unknown")
    v = check_unauthorized_build_veto(_rec("GB WhatsApp", "com.gbwhatsapp.mod"), profile)
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


def test_marker_in_url_path_does_not_fire():
    # A search hit whose app_id is a URL (package not extractable): a marker in
    # the URL path is an article title, not a build name, and must not fire.
    rec = _rec("How to download Spotify",
               "https://apkpure.com/howto/how-to-download-spotify-mod-apk", "APKPure")
    v = check_unauthorized_build_veto(rec, PROFILE)
    assert v is None


def test_clean_name_with_marker_only_in_host_does_not_fire():
    # Name and package are clean; "mod" only appears in the host (modplays.com).
    # Site name is not evidence the app itself is modded.
    rec = _rec("Spotify", "https://modplays.com/apps/spotify", "ModPlays")
    v = check_unauthorized_build_veto(rec, PROFILE)
    assert v is None


def test_howto_article_url_is_not_an_app():
    # A how-to article whose URL/title contains "mod" is not a repackaged app.
    rec = _rec("How to download Minecraft Mod",
               "https://apkpure.com/howto/how-to-download-minecraft-mod-on-android", "APKPure")
    profile = BrandProfile(brand_name="Minecraft", official_domains=["minecraft.net"],
                           official_publishers=["Mojang"], known_official_apps=["Minecraft"],
                           sector="unknown")
    assert check_unauthorized_build_veto(rec, profile) is None


def test_government_page_is_not_an_app():
    rec = _rec("WhatsApp download apk mod",
               "https://pcs.mahaonline.gov.in/latest/whatsapp-download-apk-mod/", "Gov")
    profile = BrandProfile(brand_name="WhatsApp", official_domains=["whatsapp.com"],
                           official_publishers=["WhatsApp LLC"], known_official_apps=["WhatsApp"],
                           sector="unknown")
    assert check_unauthorized_build_veto(rec, profile) is None


def test_real_aptoide_mod_app_still_flagged():
    # A genuine mod app on an APK site (aptoide /app) is still repackaged when
    # it names the brand; an add-on that only uses an abbreviation ("MCPE")
    # is a known limit of the brand-relation guard (K-065).
    rec = _rec("Minecraft PE Hardcore Mod", "https://minecraft-pe-hardcore-mod.en.aptoide.com/app", "ModDev")
    profile = BrandProfile(brand_name="Minecraft", official_domains=["minecraft.net"],
                           official_publishers=["Mojang"], known_official_apps=["Minecraft"],
                           sector="unknown")
    v = check_unauthorized_build_veto(rec, profile)
    assert v is not None and v.forced_label == Label.REPACKAGED
