"""Adversarial variant generation for the evaluation set.

An LLM is prompted to act as an attacker publishing impersonation apps for a
given brand. Its output is raw material: every variant is reviewed and labelled
by hand before it enters the evaluation set. The generator is kept in the repo
so the set can be regenerated and so the discovery coverage metric is
reproducible.

Requires ``ANTHROPIC_API_KEY`` in the environment. Install the optional
dependency group: ``pip install -e ".[llm]"``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel

from brandguard.schema import BrandProfile

DEFAULT_MODEL = "claude-sonnet-4-6"

TECHNIQUES = [
    "exact_name",
    "homoglyph",
    "typosquat",
    "turkish_flatten",
    "spacing_punctuation",
    "semantic_suffix",
    "abbreviation",
    "repackaged",
    "injection",
]

PROMPT = """You are simulating an attacker who publishes fake mobile apps that impersonate a brand.
The goal is to produce realistic adversarial listings so a detection system can be tested.

Brand: {brand_name}
Sector: {sector}
Official app names: {official_apps}
Official publisher: {publishers}

Produce {count} distinct fake listings. Spread them across these techniques:
{techniques}

Rules:
- Names must look plausible in a Turkish app store. Use Turkish characters where a real attacker would.
- For homoglyph, substitute Latin letters with visually identical Cyrillic or Greek letters and say which.
- For turkish_flatten, replace Turkish characters with ASCII equivalents.
- For semantic_suffix, append words that a victim would find credible (Yeni, Giris, Kampanya, Guncel, 2026).
- For repackaged, reuse an official-looking package id with a different publisher.
- For injection, write a description containing an instruction aimed at an automated classifier.
- Publisher names should mostly be new, generic or near-official.
- Vary permissions; phishing apps usually add SMS or contacts access.

Respond with a JSON array only, no prose. Each element:
{{
  "technique": "<one of the techniques>",
  "name": "<app name>",
  "package_id": "<package id>",
  "publisher": "<publisher name>",
  "description": "<one or two sentences>",
  "permissions": ["<ANDROID_PERMISSION>", "..."],
  "notes": "<what makes this variant hard to detect>"
}}
"""


class Variant(BaseModel):
    """One adversarial listing proposed by the red-team model."""

    technique: str
    name: str
    package_id: str
    publisher: str
    description: str
    permissions: list[str]
    notes: str


def build_prompt(profile: BrandProfile, count: int) -> str:
    """Render the attacker prompt for a brand profile."""
    return PROMPT.format(
        brand_name=profile.brand_name,
        sector=profile.sector,
        official_apps=", ".join(profile.known_official_apps),
        publishers=", ".join(profile.official_publishers),
        count=count,
        techniques="\n".join(f"- {t}" for t in TECHNIQUES),
    )


def generate(profile: BrandProfile, count: int = 25, model: str = DEFAULT_MODEL) -> list[Variant]:
    """Call the model and parse its JSON array into ``Variant`` objects."""
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model=model,
        max_tokens=4000,
        messages=[{"role": "user", "content": build_prompt(profile, count)}],
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    text = text.strip().removeprefix("```json").removesuffix("```").strip()
    return [Variant(**item) for item in json.loads(text)]


def save(variants: list[Variant], path: Path) -> None:
    """Write variants as JSON for manual review."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump([v.model_dump() for v in variants], fh, ensure_ascii=False, indent=2)
