"""Name similarity between a candidate listing and a brand.

The evidence above (measured across the evaluation set) shows a single ratio is
not enough. An exact-brand name can be official, impersonation or repackaged;
name similarity cannot tell them apart on its own, and must not pretend to.
What it can do well is (1) filter out unrelated noise cheaply and (2) describe
*how* a name resembles the brand, so later signals can weigh it.

``NameSimilarity`` therefore reports several dimensions rather than one number:

- ``jaro_winkler``: prefix-weighted similarity, strong on typosquats and
  homoglyphs once names are normalized.
- ``token_set``: set overlap of words, ignores order and extra suffixes.
- ``starts_with_brand`` / ``contains_brand``: where the brand sits in the name.
  Impersonations usually lead with the brand; legitimate third-party tools more
  often mention it mid-name.
- ``exact_skeleton``: the normalized skeletons are identical, i.e. the names are
  visually the same string (homoglyph or flattening of the exact brand name).
"""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import distance, fuzz

from brandguard.discovery.normalize import normalize, skeleton, tokens


@dataclass(frozen=True)
class NameSimilarity:
    """Multi-dimensional comparison of a candidate name against a brand."""

    jaro_winkler: float
    token_set: float
    starts_with_brand: bool
    contains_brand: bool
    exact_skeleton: bool

    @property
    def is_noise(self) -> bool:
        """True when the name is too dissimilar to be worth further analysis."""
        return self.jaro_winkler < 0.60 and not self.contains_brand


def compare_name(candidate: str, brand_name: str) -> NameSimilarity:
    """Compare a candidate app name against the brand name."""
    cand = normalize(candidate)
    brand = normalize(brand_name)
    brand_toks = tokens(brand_name)
    cand_toks = cand.split()

    jw = distance.JaroWinkler.normalized_similarity(brand, cand)
    token_set = fuzz.token_set_ratio(brand, cand) / 100.0
    starts = cand_toks[: len(brand_toks)] == brand_toks if brand_toks else False
    contains = brand in cand
    exact_skeleton = skeleton(candidate) == skeleton(brand_name)

    return NameSimilarity(
        jaro_winkler=round(jw, 3),
        token_set=round(token_set, 3),
        starts_with_brand=starts,
        contains_brand=contains,
        exact_skeleton=exact_skeleton,
    )
