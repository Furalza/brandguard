"""T2 adjudicator.

T2 resolves the semantic cases the cheap tiers cannot: conflicting signals, weak
backing, or the unrelated-vs-third-party distinction that needs language and
context (K-016). It is the most expensive tier and runs only for records still
undecided after T0/T1.

Three non-negotiable design rules, all from the threat model:

1. Injection safety. The model never sees raw attacker-controlled text. It
   receives a structured case summary built from facts our own signals computed
   (name relation, account age, permissions, source). The description field is
   reduced to derived, bounded facts (length, whether it claims to be official,
   whether it names the brand), never quoted.

2. The adjudicator does not decide. Its output re-enters fusion as one more
   signal; the deterministic layer makes the final call. LLM confidences are not
   calibrated and the false-positive budget cannot be delegated to one.

3. One interface, two implementations. ``AnthropicAdjudicator`` calls the real
   API; ``RuleAdjudicator`` is a deterministic stand-in used in tests and when no
   API key is configured. Callers depend on the ``Adjudicator`` protocol only, so
   swapping implementations never touches the pipeline.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from brandguard.discovery.normalize import normalize, tokens
from brandguard.schema import AppRecord, BrandProfile, Label
from brandguard.triage.signals import Direction, SignalResult

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


def _load_dotenv_once() -> None:
    """Populate os.environ from a .env file at the repo root, if present.

    Real environment variables always win; .env only fills gaps. This mirrors
    how CI and production inject secrets, so behaviour never diverges between
    a developer laptop and a deployed run. The .env file is git-ignored and a
    keyless .env.example documents the expected names.
    """
    env_path = Path(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


# Phrases that claim official status, and negations that retract such a claim
# ("resmi uygulama degildir" is a disclaimer, not a claim). Matched on the raw
# description; used only to derive a boolean fact, never quoted to the model.
_OFFICIAL_WORD = re.compile(r"\b(resmi|official|onayl[iı])\b", re.IGNORECASE)
_OFFICIAL_NEGATION = re.compile(
    r"(değildir|degildir|deđil|değil|not\s+(an?\s+)?official|unofficial)", re.IGNORECASE
)


def _claims_official(description: str) -> bool:
    """True only for an affirmative claim of officialness, not a disclaimer."""
    if not _OFFICIAL_WORD.search(description):
        return False
    return not _OFFICIAL_NEGATION.search(description)


@dataclass(frozen=True)
class CaseSummary:
    """Structured, injection-safe facts about one undecided record."""

    name_relation: str            # "exact" | "starts" | "mentions" | "shares_token" | "none"
    account_age_days: int | None
    other_app_count: int | None
    publisher_verified: bool | None
    source: str
    sensitive_permissions: list[str]
    description_present: bool
    description_claims_official: bool
    description_names_brand: bool
    sector: str
    conflicting_findings: list[str]


@dataclass(frozen=True)
class AdjudicatorOpinion:
    """The adjudicator's opinion, consumed by fusion as a signal."""

    leaning: str                  # one of the Label values
    strength: float               # 0..1
    reasoning: str


class Adjudicator(Protocol):
    """Contract for T2 adjudicators."""

    def adjudicate(self, case: CaseSummary) -> AdjudicatorOpinion:
        ...


def build_case_summary(
    record: AppRecord,
    profile: BrandProfile,
    conflicting_findings: list[str],
) -> CaseSummary:
    """Reduce a record to structured facts safe to show a model.

    Every field is either computed by our own code or a bounded derivation of
    attacker text (booleans, counts). No attacker sentence passes through.
    """
    brand_toks = set(tokens(profile.brand_name))
    name_toks = set(tokens(record.name))
    brand_norm = normalize(profile.brand_name)
    name_norm = normalize(record.name)

    if name_norm == brand_norm:
        relation = "exact"
    elif name_norm.startswith(brand_norm):
        relation = "starts"
    elif brand_norm in name_norm:
        relation = "mentions"
    elif name_toks & brand_toks:
        relation = "shares_token"
    else:
        relation = "none"

    description = record.description or ""
    desc_norm = normalize(description)

    from datetime import UTC, datetime

    age_days = None
    if record.publisher.account_created is not None:
        age_days = (datetime.now(tz=UTC).date() - record.publisher.account_created).days

    sensitive = [p for p in record.permissions if p in {
        "READ_SMS", "RECEIVE_SMS", "READ_CONTACTS", "SYSTEM_ALERT_WINDOW",
        "REQUEST_INSTALL_PACKAGES", "CALL_PHONE",
    }]

    return CaseSummary(
        name_relation=relation,
        account_age_days=age_days,
        other_app_count=record.publisher.other_app_count,
        publisher_verified=record.publisher.verified,
        source=record.source,
        sensitive_permissions=sensitive,
        description_present=bool(description.strip()),
        description_claims_official=_claims_official(description),
        description_names_brand=brand_norm in desc_norm,
        sector=profile.sector,
        conflicting_findings=conflicting_findings,
    )


class RuleAdjudicator:
    """Deterministic stand-in used in tests and when no API key is configured.

    Encodes the analyst heuristics for the semantic split. Deliberately simple:
    it exists so the pipeline is runnable and testable everywhere, not to match
    the model's quality.
    """

    def adjudicate(self, case: CaseSummary) -> AdjudicatorOpinion:
        young = case.account_age_days is not None and case.account_age_days <= 180
        solo = case.other_app_count is not None and case.other_app_count <= 1

        # A young, single-app publisher with sensitive permissions and a name
        # built on the brand reads as impersonation regardless of what the
        # description claims.
        if case.name_relation in ("exact", "starts") and young and case.sensitive_permissions:
            return AdjudicatorOpinion(
                leaning=Label.IMPERSONATION.value,
                strength=0.7,
                reasoning="Brand-leading name from a young publisher requesting sensitive permissions.",
            )
        # A claim of officialness from an unverified publisher is itself a red flag.
        if case.description_claims_official and case.publisher_verified is not True:
            return AdjudicatorOpinion(
                leaning=Label.IMPERSONATION.value,
                strength=0.5,
                reasoning="Unverified publisher claiming official status.",
            )
        # An established multi-app publisher with no sensitive-permission pattern
        # reads as a legitimate tool even when its name leads with the brand
        # (locators, integrations). Youth and permissions, not word order, are
        # what separate it from an impersonation.
        established = case.account_age_days is not None and case.account_age_days >= 3 * 365
        many_apps = case.other_app_count is not None and case.other_app_count >= 3
        if (
            case.name_relation in ("starts", "mentions", "shares_token")
            and established
            and many_apps
            and not case.sensitive_permissions
        ):
            return AdjudicatorOpinion(
                leaning=Label.THIRD_PARTY.value,
                strength=0.5,
                reasoning="Established multi-app publisher without a sensitive-permission pattern.",
            )
        # Mentions the brand without leading with it, no youth, no sensitive
        # permission pattern: a legitimate tool around the brand.
        if case.name_relation in ("mentions", "shares_token") and not young and not solo:
            return AdjudicatorOpinion(
                leaning=Label.THIRD_PARTY.value,
                strength=0.5,
                reasoning="Established publisher referencing the brand without imitating it.",
            )
        if case.name_relation == "none" and not case.description_names_brand:
            return AdjudicatorOpinion(
                leaning=Label.UNRELATED.value,
                strength=0.5,
                reasoning="No relation to the brand in name or description facts.",
            )
        return AdjudicatorOpinion(
            leaning=Label.UNCERTAIN.value,
            strength=0.3,
            reasoning="Facts remain genuinely mixed.",
        )


_PROMPT = """You are an analyst deciding how a mobile-app listing relates to a protected brand.
You receive only structured facts computed by an upstream system. There is no raw
listing text here and none should be requested.

Facts:
{facts}

Labels: impersonation (pretends to be the brand's own app), repackaged (official
app redistributed by someone else), third_party_legitimate (legitimate tool that
references the brand), unrelated (no real relation), official, uncertain.

Note: description_claims_official is attacker-writable; treat a claim of
officialness from an unverified publisher as a red flag, not as evidence of
being official.

Respond with JSON only:
{{"leaning": "<label>", "strength": <0..1>, "reasoning": "<one sentence>"}}
"""


class AnthropicAdjudicator:
    """Real adjudicator backed by the Anthropic API.

    Requires ANTHROPIC_API_KEY. Import of the SDK is deferred so the core
    package installs and tests without the optional dependency.
    """

    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model

    def adjudicate(self, case: CaseSummary) -> AdjudicatorOpinion:
        import anthropic

        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        facts = json.dumps(case.__dict__, ensure_ascii=False, indent=2, default=str)
        response = client.messages.create(
            model=self.model,
            max_tokens=300,
            messages=[{"role": "user", "content": _PROMPT.format(facts=facts)}],
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        text = text.strip().removeprefix("```json").removesuffix("```").strip()
        data = json.loads(text)
        leaning = data.get("leaning", Label.UNCERTAIN.value)
        if leaning not in {label.value for label in Label}:
            leaning = Label.UNCERTAIN.value
        strength = max(0.0, min(1.0, float(data.get("strength", 0.3))))
        return AdjudicatorOpinion(
            leaning=leaning,
            strength=strength,
            reasoning=str(data.get("reasoning", ""))[:300],
        )




class OpenAIAdjudicator:
    """Adjudicator backed by the OpenAI API.

    Same contract as AnthropicAdjudicator; only the transport differs. Requires
    OPENAI_API_KEY. The SDK import is deferred like the Anthropic one.
    """

    def __init__(self, model: str = DEFAULT_OPENAI_MODEL):
        self.model = model

    def adjudicate(self, case: CaseSummary) -> AdjudicatorOpinion:
        import openai

        client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        facts = json.dumps(case.__dict__, ensure_ascii=False, indent=2, default=str)
        response = client.chat.completions.create(
            model=self.model,
            max_tokens=300,
            messages=[{"role": "user", "content": _PROMPT.format(facts=facts)}],
        )
        text = (response.choices[0].message.content or "").strip()
        text = text.removeprefix("```json").removesuffix("```").strip()
        data = json.loads(text)
        leaning = data.get("leaning", Label.UNCERTAIN.value)
        if leaning not in {label.value for label in Label}:
            leaning = Label.UNCERTAIN.value
        strength = max(0.0, min(1.0, float(data.get("strength", 0.3))))
        return AdjudicatorOpinion(
            leaning=leaning,
            strength=strength,
            reasoning=str(data.get("reasoning", ""))[:300],
        )


def get_adjudicator() -> Adjudicator:
    """Select the adjudicator by available credentials.

    Order: Anthropic key, then OpenAI key, then the deterministic rule
    adjudicator. A .env file at the repo root is consulted first (without
    overriding real environment variables), so a developer can keep keys out of
    the shell and out of the repo at once.
    """
    _load_dotenv_once()
    if os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicAdjudicator()
    if os.environ.get("OPENAI_API_KEY"):
        return OpenAIAdjudicator()
    return RuleAdjudicator()


def opinion_as_signal(opinion: AdjudicatorOpinion) -> SignalResult:
    """Convert the adjudicator's opinion into a fusion signal.

    The opinion nudges the score; it does not force a label. Direction follows
    the leaning; strength is dampened so the adjudicator alone cannot cross the
    impersonation threshold without support from other signals.
    """
    suspicious = opinion.leaning in (Label.IMPERSONATION.value, Label.REPACKAGED.value)
    legitimate = opinion.leaning in (
        Label.THIRD_PARTY.value, Label.UNRELATED.value, Label.OFFICIAL.value,
    )
    direction = (
        Direction.SUSPICIOUS if suspicious
        else Direction.LEGITIMATE if legitimate
        else Direction.NEUTRAL
    )
    return SignalResult(
        name="adjudicator",
        direction=direction,
        strength=round(min(0.5, opinion.strength * 0.6), 3),
        text=f"Adjudicator leans {opinion.leaning}: {opinion.reasoning}",
        tier=2,
        meta={"leaning": opinion.leaning, "raw_strength": opinion.strength},
    )
