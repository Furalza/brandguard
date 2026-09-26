"""Product categories: the operator's three-way answer on top of the engine.

The engine's labels are deliberately fine-grained (K-016 keeps unrelated and
third_party apart, K-037 keeps domain verdicts apart from app labels). An
operator triaging a scan wants coarser buckets:

    official    the brand's own listing or infrastructure
    malicious   a takedown candidate (impersonation, repackaged, live lookalike)
    suspicious  the engine could not decide; a person should look
    affiliate   benign, and its publisher identity points at the brand: probably
                the brand's own regional or secondary app, unverified (K-063)
    related     legitimately mentions the brand, no takedown
    noise       search noise; hidden by default

This mapping lives in one function so the product vocabulary can change (a
customer may want third_party shown as "related" or hidden) without touching
a single decision rule. The engine labels are always stored next to the
category, so nothing is lost.
"""

from __future__ import annotations

from enum import Enum

from brandguard.schema import Label


class Category(str, Enum):
    OFFICIAL = "official"
    MALICIOUS = "malicious"
    SUSPICIOUS = "suspicious"
    AFFILIATE = "affiliate"
    RELATED = "related"
    NOISE = "noise"


# Categories that an operator acts on, in the order they are shown.
ACTIONABLE = (Category.MALICIOUS, Category.SUSPICIOUS)
DISPLAY_ORDER = (
    Category.MALICIOUS, Category.SUSPICIOUS, Category.OFFICIAL, Category.AFFILIATE,
    Category.RELATED, Category.NOISE,
)

_APP_CATEGORY: dict[Label, Category] = {
    Label.OFFICIAL: Category.OFFICIAL,
    Label.IMPERSONATION: Category.MALICIOUS,
    Label.REPACKAGED: Category.MALICIOUS,
    Label.UNCERTAIN: Category.SUSPICIOUS,
    Label.THIRD_PARTY: Category.RELATED,
    Label.UNRELATED: Category.NOISE,
}


def app_category(label: Label | str, *, affiliate_hint: bool = False) -> Category:
    """Category for an app listing verdict.

    ``affiliate_hint`` (product.affiliate) re-buckets a benign verdict, or an
    uncertain one whose suspicion is words alone, when the publisher identity
    points at the brand. Threat verdicts are never softened by it.
    """
    label = Label(label) if not isinstance(label, Label) else label
    if affiliate_hint and label in (Label.THIRD_PARTY, Label.UNRELATED, Label.UNCERTAIN):
        # For an uncertain label the hint is only ever set when the suspicion
        # rests on words alone (product.affiliate.uncertain_only_by_words).
        return Category.AFFILIATE
    return _APP_CATEGORY[label]


def domain_category(verdict: str, *, confirmed_live: bool, priority: str | None) -> Category:
    """Category for a domain finding.

    A lookalike that a source actually returned is a real site; its review
    priority (from WHOIS/SSL, K-038/K-040) decides between malicious and
    suspicious. A generated lookalike name whose registration is unknown is a
    watch item (K-048): shown as suspicious, never as a detection. Mentions are
    related; official and unrelated map directly.
    """
    if verdict == "official":
        return Category.OFFICIAL
    if verdict == "lookalike":
        if confirmed_live and priority == "high":
            return Category.MALICIOUS
        return Category.SUSPICIOUS
    if verdict == "mentions":
        return Category.RELATED
    return Category.NOISE


def category_of_row(row: dict) -> Category:
    """Category for a raw hunt_engine row (app or domain shape)."""
    if "domain" in row:
        return domain_category(
            str(row.get("verdict", "")),
            confirmed_live=bool(row.get("confirmed_live")),
            priority=row.get("priority"),
        )
    return app_category(str(row.get("label", Label.UNCERTAIN.value)),
                        affiliate_hint=bool(row.get("affiliate_hint")))
