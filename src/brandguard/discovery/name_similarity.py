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
    brand_token_coverage: float
    token_alignment: float

    @property
    def is_noise(self) -> bool:
        """True when the name is too dissimilar to be worth further analysis.

        Uses token alignment (each brand token's best match among the candidate's
        tokens) to separate a typosquat, which stays close to every brand token,
        from search noise, which matches one brand token exactly and drops the
        rest. A whole-string metric like Jaro-Winkler cannot make this split:
        "Omek Bank" (a threat) and "Örnek Oyun" (noise) score almost the same on
        it, but differ clearly on alignment.
        """
        if self.contains_brand:
            return False
        if self.jaro_winkler < 0.60:
            return True
        return self.brand_token_coverage < 1.0 and self.token_alignment < 0.85


def compare_name(candidate: str, brand_name: str) -> NameSimilarity:
    """Compare a candidate app name against the brand name."""
    cand = normalize(candidate)
    brand = normalize(brand_name)
    brand_toks = tokens(brand_name)
    cand_toks = cand.split()

    jw = distance.JaroWinkler.normalized_similarity(brand, cand)
    token_set = fuzz.token_set_ratio(brand, cand) / 100.0
    if brand_toks:
        # A leading typosquat ("ornek bankk") still leads with the brand even
        # though its tokens are not identical. Match each brand token against the
        # candidate token in the same position with a high fuzzy threshold, so a
        # distorted brand prefix is recognized as leading, not as a mid-name
        # mention. Exact equality remains the common, cheap path.
        lead = cand_toks[: len(brand_toks)]
        if lead == brand_toks:
            starts = True
        elif len(lead) == len(brand_toks):
            starts = all(
                distance.JaroWinkler.normalized_similarity(b, c) >= 0.85
                for b, c in zip(brand_toks, lead)
            )
        else:
            starts = False
    else:
        starts = False
    contains = brand in cand
    exact_skeleton = skeleton(candidate) == skeleton(brand_name)
    if brand_toks:
        covered = sum(1 for t in brand_toks if t in cand_toks)
        coverage = covered / len(brand_toks)
        if cand_toks:
            alignment = sum(
                max(distance.JaroWinkler.normalized_similarity(bt, ct) for ct in cand_toks)
                for bt in brand_toks
            ) / len(brand_toks)
        else:
            alignment = 0.0
    else:
        coverage = 0.0
        alignment = 0.0

    return NameSimilarity(
        jaro_winkler=round(jw, 3),
        token_set=round(token_set, 3),
        starts_with_brand=starts,
        contains_brand=contains,
        exact_skeleton=exact_skeleton,
        brand_token_coverage=round(coverage, 3),
        token_alignment=round(alignment, 3),
    )
