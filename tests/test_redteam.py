"""Tests for the red-team prompt builder. Model calls are not exercised."""

import json
from pathlib import Path

from brandguard.eval.redteam import TECHNIQUES, Variant, build_prompt
from brandguard.schema import BrandProfile

PROFILE = Path(__file__).resolve().parents[1] / "data" / "profiles" / "ornek_bank.json"


def test_prompt_mentions_brand_and_all_techniques():
    profile = BrandProfile(**json.loads(PROFILE.read_text(encoding="utf-8")))
    prompt = build_prompt(profile, count=10)
    assert profile.brand_name in prompt
    for technique in TECHNIQUES:
        assert technique in prompt


def test_variant_round_trip():
    payload = {
        "technique": "homoglyph",
        "name": "Ornek Bank",
        "package_id": "com.ornek.bank",
        "publisher": "Ornek Yazilim",
        "description": "x",
        "permissions": ["READ_SMS"],
        "notes": "n",
    }
    assert Variant(**payload).model_dump() == payload
