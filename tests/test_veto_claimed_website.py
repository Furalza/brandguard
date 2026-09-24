"""The publisher veto must not trust a website that a listing merely claims.

On Google Play the developer website is typed in by the developer. An
impersonator can copy the official publisher name and type the brand's domain,
so "website on an official domain" identifies a publisher only when the listing
also shows what an impersonator cannot produce: organic install volume, or an
official package id on a store where package ids are unique (K-055).
"""

from brandguard.schema import AppRecord, BrandProfile, Label, Publisher
from brandguard.triage.veto import check_package_veto, check_publisher_veto

PROFILE = BrandProfile(
    brand_name="Binance",
    official_domains=["binance.com"],
    official_publishers=["Binance Inc."],
    known_official_apps=["Binance"],
    sector="crypto",
    official_package_ids=["com.binance.dev", "com.binance.junior"],
)


def _record(app_id, *, publisher="Binance Inc.", website="https://www.binance.com",
            downloads=None, source="google_play_live", verified=None, account_created=None):
    return AppRecord(
        app_id=app_id, source=source, name="Binance",
        publisher=Publisher(name=publisher, website=website, verified=verified,
                            account_created=account_created),
        downloads=downloads,
    )


def test_copied_name_and_claimed_website_on_a_fresh_listing_is_not_official():
    impostor = _record("com.binance.secure.login", downloads=500)
    assert check_publisher_veto(impostor, PROFILE) is None


def test_established_listing_with_the_official_website_is_official():
    real = _record("com.binance.lite", downloads=50_000_000)  # not yet on the package list
    veto = check_publisher_veto(real, PROFILE)
    assert veto is not None and veto.forced_label is Label.OFFICIAL
    assert "installs" in veto.text


def test_small_official_app_on_play_is_official_through_its_package_id():
    junior = _record("com.binance.junior", downloads=10_000, website=None)
    veto = check_publisher_veto(junior, PROFILE)
    assert veto is not None and "package id" in veto.text


def test_official_package_id_off_play_does_not_count_as_proof():
    # package ids are unique on Play only; a third-party store can carry any id
    mirror = _record("com.binance.junior", downloads=10_000, source="apkpure")
    assert check_publisher_veto(mirror, PROFILE) is None


def test_source_without_install_data_keeps_the_previous_rule():
    no_reach = _record("com.binance.other", downloads=None, source="mock")
    assert check_publisher_veto(no_reach, PROFILE) is not None


def test_other_verifiers_are_unchanged():
    verified = _record("x.y.z", website=None, downloads=10, verified=True)
    assert check_publisher_veto(verified, PROFILE) is not None


def test_rejected_claim_does_not_turn_into_a_repackaged_takedown():
    # K-032: a matching official name is unverified identity, not a foreign repackager
    small = _record("com.binance.dev", downloads=500, source="apkpure")
    assert check_publisher_veto(small, PROFILE) is None
    assert check_package_veto(small, PROFILE) is None


def test_official_package_on_play_is_official_whatever_website_it_declares():
    # Bankkart: Ziraat's own app under its card-brand site, not ziraatbank.com.tr
    ziraat = BrandProfile(
        brand_name="Ziraat", official_domains=["ziraatbank.com.tr"],
        official_publishers=["T.C. Ziraat Bankasi A.S."], known_official_apps=[],
        sector="banking", official_package_ids=["com.bankkart.mobil"],
    )
    bankkart = AppRecord(
        app_id="com.bankkart.mobil", source="google_play_live", name="Bankkart Mobil",
        publisher=Publisher(name="T.C. Ziraat Bankasi A.S.", website="https://www.bankkart.com.tr"),
        downloads=10_000_000,
    )
    veto = check_publisher_veto(bankkart, ziraat)
    assert veto is not None and veto.forced_label is Label.OFFICIAL
    assert "official package id" in veto.text
    # the same package on a third-party store proves nothing on its own
    mirror = bankkart.model_copy(update={"source": "apkpure"})
    assert check_publisher_veto(mirror, ziraat) is None
