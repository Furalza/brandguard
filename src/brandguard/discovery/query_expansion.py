"""Query expansion for discovery.

Marketplace search engines match literally, so searching only the brand name
misses the impersonations that matter most: names deliberately altered to look
right while evading exact search. This module expands a brand name into a set of
search terms whose goal is recall. The candidates those searches return are
scored elsewhere; this module does not judge, it widens the net.

The design separates two concerns that are easy to conflate:

- Query generation (here): produce plausible search seeds. An extra term costs
  one more search; a missing term costs a threat we never see.
- Candidate matching (name_similarity): decide whether a returned listing
  resembles the brand.

Expansion is deliberately bounded. Unbounded typo generation produces thousands
of terms, most of them noise that no attacker would use and no store indexes.
Each strategy is capped and the union is deduplicated.
"""

from __future__ import annotations

from dataclasses import dataclass

from brandguard.discovery.normalize import normalize

# Confusable substitutions an attacker applies to Latin letters, keyed by the
# Latin letter. The inverse of the normalization map, limited to high-value
# targets so the output stays small.
_HOMOGLYPH_SUBS: dict[str, list[str]] = {
    "a": ["а", "α"],   # Cyrillic a, Greek alpha
    "e": ["е", "ε"],   # Cyrillic e, Greek epsilon
    "o": ["о", "ο"],   # Cyrillic o, Greek omicron
    "p": ["р", "ρ"],   # Cyrillic er, Greek rho
    "c": ["с"],        # Cyrillic es
    "k": ["к"],        # Cyrillic ka
    "x": ["х"],        # Cyrillic ha
    "i": ["і"],        # Cyrillic dotted i
    "s": ["ѕ"],        # Cyrillic dze
}

# Turkish letters an official or attacker rendering may swap in for ASCII.
_TURKISH_SUBS: dict[str, list[str]] = {
    "i": ["ı", "İ"],
    "s": ["ş"],
    "g": ["ğ"],
    "c": ["ç"],
    "o": ["ö"],
    "u": ["ü"],
}

# Multi-character (multigraph) lookalikes, both directions. Visually strong and
# genuinely used ("rn" reads as "m", "vv" as "w"). Kept small; multigraphs occur
# rarely in a name, so they add few variants. See K-012.
_MULTIGRAPH_SUBS: dict[str, list[str]] = {
    "m": ["rn"],
    "rn": ["m"],
    "w": ["vv"],
    "vv": ["w"],
    "d": ["cl"],
    "cl": ["d"],
}

# Digit and symbol lookalikes (leetspeak). Limited to high-confidence swaps that
# attackers actually use; adding these covered a real miss ("ornek 8ank") at a
# cost of a handful of extra queries. See K-011.
_LEET_SUBS: dict[str, list[str]] = {
    "o": ["0"], "i": ["1"], "l": ["1"], "b": ["8"],
    "e": ["3"], "s": ["5"], "a": ["4"], "g": ["9"], "t": ["7"],
}

# Credibility-adding words attackers append to a brand name.
_SUFFIXES = ["mobil", "yeni", "giris", "guncel", "kampanya", "online", "2026"]

# Neighbouring keys on a Turkish QWERTY layout, for typosquat generation.
_KEYBOARD_NEIGHBORS: dict[str, str] = {
    "a": "sq", "b": "vn", "c": "xv", "d": "sf", "e": "wr", "g": "fh",
    "i": "uo", "k": "jl", "l": "k", "m": "n", "n": "bm", "o": "ip",
    "r": "et", "s": "ad", "t": "ry", "u": "yi", "y": "tu",
}


@dataclass(frozen=True)
class Query:
    """A single search term plus the strategy that produced it."""

    term: str
    strategy: str


def _homoglyph_variants(name: str, cap: int) -> list[str]:
    out: list[str] = []
    for i, ch in enumerate(name):
        for sub in _HOMOGLYPH_SUBS.get(ch, []):
            out.append(name[:i] + sub + name[i + 1 :])
            if len(out) >= cap:
                return out
    return out


def _multigraph_variants(name: str, cap: int) -> list[str]:
    out: list[str] = []
    for pattern, subs in _MULTIGRAPH_SUBS.items():
        start = name.find(pattern)
        while start != -1:
            for sub in subs:
                out.append(name[:start] + sub + name[start + len(pattern) :])
                if len(out) >= cap:
                    return out
            start = name.find(pattern, start + 1)
    return out


def _leet_variants(name: str, cap: int) -> list[str]:
    out: list[str] = []
    for i, ch in enumerate(name):
        for sub in _LEET_SUBS.get(ch, []):
            out.append(name[:i] + sub + name[i + 1 :])
            if len(out) >= cap:
                return out
    return out


def _turkish_variants(name: str, cap: int) -> list[str]:
    out: list[str] = []
    for i, ch in enumerate(name):
        for sub in _TURKISH_SUBS.get(ch, []):
            out.append(name[:i] + sub + name[i + 1 :])
            if len(out) >= cap:
                return out
    return out


def _typosquat_variants(name: str, cap: int) -> list[str]:
    out: list[str] = []
    # Doubled letters.
    for i, ch in enumerate(name):
        if ch.isalpha():
            out.append(name[:i] + ch + ch + name[i + 1 :])
    # Deletions.
    for i, ch in enumerate(name):
        if ch.isalpha():
            out.append(name[:i] + name[i + 1 :])
    # Neighbouring-key substitutions.
    for i, ch in enumerate(name):
        for sub in _KEYBOARD_NEIGHBORS.get(ch, ""):
            out.append(name[:i] + sub + name[i + 1 :])
    # Cap after building so all types are represented, then trim.
    return out[:cap]


def _spacing_variants(name: str) -> list[str]:
    collapsed = name.replace(" ", "")
    hyphen = name.replace(" ", "-")
    return [v for v in (collapsed, hyphen) if v != name]


def _suffix_variants(name: str) -> list[str]:
    return [f"{name} {suffix}" for suffix in _SUFFIXES]


def expand(
    brand_name: str,
    *,
    homoglyph_cap: int = 12,
    turkish_cap: int = 8,
    typo_cap: int = 20,
    leet_cap: int = 12,
    multigraph_cap: int = 8,
) -> list[Query]:
    """Expand a brand name into deduplicated search queries.

    The brand name itself is always the first query. Strategies are bounded so
    the union stays in the low dozens rather than the thousands.
    """
    base = normalize(brand_name)
    seen: set[str] = set()
    queries: list[Query] = []

    def add(term: str, strategy: str) -> None:
        key = term.strip().lower()
        if key and key not in seen:
            seen.add(key)
            queries.append(Query(term=term, strategy=strategy))

    add(brand_name, "exact")
    if base != brand_name.lower():
        add(base, "normalized")

    for term in _homoglyph_variants(base, homoglyph_cap):
        add(term, "homoglyph")
    for term in _turkish_variants(base, turkish_cap):
        add(term, "turkish")
    for term in _multigraph_variants(base, multigraph_cap):
        add(term, "multigraph")
    for term in _leet_variants(base, leet_cap):
        add(term, "leet")
    for term in _typosquat_variants(base, typo_cap):
        add(term, "typosquat")
    for term in _spacing_variants(base):
        add(term, "spacing")
    for term in _suffix_variants(base):
        add(term, "suffix")

    return queries


_STRATEGY_PRIORITY = ("exact", "normalized", "suffix", "typosquat", "spacing",
                      "homoglyph", "leet", "multigraph", "turkish")


def select_queries(brand_name: str, limit: int | None, **caps) -> list[Query]:
    """Pick up to ``limit`` queries with every strategy represented.

    ``expand`` lists strategies in blocks (all homoglyphs, then all Turkish
    variants, ...), so taking the first N used to spend the whole budget on
    exact + homoglyph and never reach the suffix variants ("giris", "2026")
    that real impersonators on Play use most. Round-robin over strategies
    keeps the budget spread: exact first, then one of each strategy in turn.
    """
    queries = expand(brand_name, **caps)
    if limit is None or limit >= len(queries):
        return queries
    by_strategy: dict[str, list[Query]] = {}
    for q in queries:
        by_strategy.setdefault(q.strategy, []).append(q)
    # Priority by how often each trick shows up in real store listings: suffix
    # and typo variants are what Play actually indexes; homoglyphs mostly matter
    # for the classifier, not the search box.
    order = [s for s in _STRATEGY_PRIORITY if s in by_strategy]
    order += [s for s in by_strategy if s not in order]
    picked: list[Query] = []
    while len(picked) < limit and any(by_strategy.values()):
        for strategy in order:
            bucket = by_strategy[strategy]
            if bucket:
                picked.append(bucket.pop(0))
                if len(picked) >= limit:
                    break
    return picked
