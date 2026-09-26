"""T2 adjudicator.

T2 resolves the semantic cases the cheap tiers cannot: conflicting signals, weak
backing, or the unrelated-vs-third-party distinction that needs language and
context (K-016). It is the most expensive tier and runs only for records still
undecided after T0/T1.

Three non-negotiable design rules, all from the threat model:

1. Injection safety. Until K-078 the model never saw attacker text at all; it
   received only facts our own signals computed. Since K-078 it reads a bounded,
   delimited excerpt of the listing (``triage.reader``) but answers only fixed
   semantic questions with enum answers; the leaning is derived in code from
   those answers and the hard facts. The model still never sees raw text
   outside the delimited block and still cannot emit a label.

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
from typing import Protocol

from pathlib import Path

from brandguard.config import data_dir, load_dotenv, setting
from brandguard.discovery.normalize import normalize, tokens
from brandguard.schema import AppRecord, BrandProfile, Label
from brandguard.triage.reader import (
    CaseText,
    HardFacts,
    ReadingCache,
    TextReading,
    apply_hard_facts,
    derive_leaning,
    parse_reading,
    render_prompt,
)
from brandguard.triage.signals import Direction, SignalResult
from brandguard.triage.veto import _domain_matches_official, publisher_name_matches

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"

# A model call that hangs must not hang a scan; one retry covers transient
# network errors, anything slower than this is treated as "no opinion".
_LLM_TIMEOUT_S = 30.0


def _load_dotenv_once() -> None:
    """Consult the repo-root .env for keys (gaps only). See brandguard.config."""
    load_dotenv()


# Phrases that claim official status, and negations that retract such a claim
# ("resmi uygulama degildir" is a disclaimer, not a claim). Matched on the raw
# description; used only to derive a boolean fact, never quoted to the model.
_OFFICIAL_WORD = re.compile(r"\b(resmi|official|onayl[iı])\b", re.IGNORECASE)
_OFFICIAL_NEGATION = re.compile(
    r"(değildir|degildir|deđil|değil|not\s+(an?\s+)?official|unofficial)", re.IGNORECASE
)


_OFFICIAL_WORD_NORM = re.compile(r"\b(resmi\w*|official\w*|onayl\w*)\b")
_CLAIM_WINDOW = 80  # characters of normalized text around a brand mention


def _strip_self_reference(desc_norm: str, app_name: str, brand_norm: str) -> str:
    """Remove the app's own name from its description when that name merely
    contains the brand word.

    "PegasusPlus is the official companion app of BJain Publishers" names
    Pegasus only because the app is called Pegasus Plus; that is not a mention
    of the airline. An app named exactly like the brand keeps its mentions,
    since there the self-reference and the brand claim are the same thing.
    """
    name_norm = normalize(app_name)
    if not name_norm or name_norm == brand_norm or brand_norm not in name_norm:
        return desc_norm
    out = desc_norm.replace(name_norm, " ")
    return out.replace(name_norm.replace(" ", ""), " ")


def _brand_positions(desc_norm: str, brand_name: str) -> list[int]:
    """Offsets in normalized text where the brand (or an identity token) is named."""
    brand_norm = normalize(brand_name)
    if brand_norm and brand_norm in desc_norm:
        return [m.start() for m in re.finditer(re.escape(brand_norm), desc_norm)]
    from brandguard.registry import identity_tokens

    positions: list[int] = []
    for tok in identity_tokens(brand_name):
        positions += [m.start() for m in re.finditer(re.escape(tok), desc_norm)]
    return positions


def _claims_official(description: str, brand_name: str | None = None,
                     app_name: str = "") -> bool:
    """True only for an affirmative claim of officialness *about the brand*.

    A disclaimer ("resmi uygulama degildir") is not a claim (K-022). Neither is
    "the official app of BJain Publishers" on a scan for the airline Pegasus
    (found live, K-070): the claim must sit within a short window of a brand
    mention, and the app's own name does not count as one. Without a brand
    name the older whole-text rule applies.
    """
    if not _OFFICIAL_WORD.search(description):
        return False
    if _OFFICIAL_NEGATION.search(description):
        return False
    if not brand_name:
        return True
    desc_norm = _strip_self_reference(normalize(description), app_name, normalize(brand_name))
    positions = _brand_positions(desc_norm, brand_name)
    if not positions:
        return False
    return any(abs(m.start() - pos) <= _CLAIM_WINDOW for pos in positions
               for m in _OFFICIAL_WORD_NORM.finditer(desc_norm))


def _names_brand(description: str, brand_name: str, app_name: str) -> bool:
    desc_norm = _strip_self_reference(normalize(description), app_name, normalize(brand_name))
    return bool(_brand_positions(desc_norm, brand_name))


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
    # Publisher name on the profile's official list (identity still unverified
    # when this is the only match). Computed here, never asked of the model.
    publisher_official: bool = False
    # Developer website under an official domain (a claim, not a proof).
    website_official: bool = False


@dataclass(frozen=True)
class AdjudicatorOpinion:
    """The adjudicator's opinion, consumed by fusion as a signal."""

    leaning: str                  # one of the Label values
    strength: float               # 0..1
    reasoning: str
    # Present when the opinion came from the text reader (K-078); analyst
    # lines are rendered from it, the leaning above already accounts for it.
    reading: TextReading | None = None


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
        description_claims_official=_claims_official(description, profile.brand_name, record.name),
        description_names_brand=_names_brand(description, profile.brand_name, record.name),
        sector=profile.sector,
        conflicting_findings=conflicting_findings,
        publisher_official=publisher_name_matches(record.publisher.name, profile),
        website_official=_domain_matches_official(record.publisher.website, profile),
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
        # A brand-leading name whose description never refers to the brand
        # (beyond the app's own name) is a namesake: "Pegasus Plus" by a book
        # publisher on an airline scan (K-070). An imitation talks about the
        # brand; a namesake talks about itself. Only without youth, sensitive
        # permissions or an official claim, which would read as imitation.
        if (
            case.name_relation in ("exact", "starts")
            and case.description_present
            and not case.description_names_brand
            and not case.description_claims_official
            and not young
            and not case.sensitive_permissions
        ):
            return AdjudicatorOpinion(
                leaning=Label.THIRD_PARTY.value,
                strength=0.4,
                reasoning="Brand-leading name but the description never refers to the brand: a namesake, not an imitation.",
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
being official. description_names_brand is computed after removing the app's
own name, so a brand-leading name whose description never refers to the brand
is usually a namesake (another company using the same word), not an imitation.

Respond with JSON only:
{{"leaning": "<label>", "strength": <0..1>, "reasoning": "<one sentence>"}}
"""


def _parse_opinion(text: str) -> AdjudicatorOpinion:
    """Turn a model reply into an opinion without ever raising.

    Models occasionally answer with prose around the JSON, a fenced block, or a
    reply truncated at max_tokens. Any of those used to raise out of triage_t2
    and abort the whole scan of a brand. An unparseable answer now means the
    model could not be understood, which in this system is the same as "the
    model is not sure": a weak uncertain leaning that fusion treats as neutral.
    """
    raw = (text or "").strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    data: object = None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # Salvage the first {...} block if the model wrapped it in prose.
        start, end = raw.find("{"), raw.rfind("}")
        if 0 <= start < end:
            try:
                data = json.loads(raw[start:end + 1])
            except (json.JSONDecodeError, ValueError):
                data = None
    if not isinstance(data, dict):
        return AdjudicatorOpinion(
            leaning=Label.UNCERTAIN.value, strength=0.3,
            reasoning="Model reply could not be parsed; treated as no opinion.",
        )
    leaning = data.get("leaning", Label.UNCERTAIN.value)
    if leaning not in {label.value for label in Label}:
        leaning = Label.UNCERTAIN.value
    try:
        strength = max(0.0, min(1.0, float(data.get("strength", 0.3))))
    except (TypeError, ValueError):
        strength = 0.3
    return AdjudicatorOpinion(
        leaning=leaning,
        strength=strength,
        reasoning=str(data.get("reasoning", ""))[:300],
    )


def _case_facts(case: CaseSummary) -> dict:
    """The facts block shown to the model: the summary minus nothing, as JSON."""
    return dict(case.__dict__)


def _hard_facts(case: CaseSummary, text: CaseText | None = None) -> HardFacts:
    from brandguard.triage.veto import _UNIQUE_PACKAGE_ID_SOURCES

    title_official = False
    if text is not None:
        name_norm = normalize(text.app_name)
        brand_norm = normalize(text.brand_name)
        for app in text.known_official_apps:
            full = normalize(app)
            head = normalize(app.split(" - ")[0].split(": ")[0].split(" | ")[0])
            # "TikTok Lite" and "Wise: International Transfers" count, the
            # bare brand word does not (every namesake carries that).
            if any(c and c != brand_norm and len(c) > len(brand_norm) and c in name_norm for c in (full, head)):
                title_official = True
                break
    from brandguard.registry import identity_tokens, names_identity

    carries = False
    if text is not None and text.publisher_name:
        carries = bool(names_identity(text.publisher_name, identity_tokens(text.brand_name, text.official_domains)))
    return HardFacts(
        publisher_carries_brand=carries,
        publisher_official=case.publisher_official or case.website_official,
        publisher_verified=case.publisher_verified,
        sensitive_permissions=list(case.sensitive_permissions),
        young_account=case.account_age_days is not None and case.account_age_days <= 180,
        name_relation=case.name_relation,
        unique_package_store=case.source.startswith(_UNIQUE_PACKAGE_ID_SOURCES),
        title_names_official_app=title_official,
    )


class LLMAdjudicator:
    """Shared behaviour of the model-backed adjudicators.

    ``adjudicate`` keeps the facts-only path (used when a caller has no
    record text). ``read`` is the K-078 path: facts plus the bounded listing
    text, answered as enums, turned into a leaning by ``derive_leaning``.
    Readings are cached under the data directory; ``stats`` counts calls,
    cache hits and failures for the run log.
    """

    provider = "llm"

    def __init__(self, model: str, cache_path: Path | None = None):
        self.model = model
        cache = cache_path if cache_path is not None else data_dir() / "t2_cache.sqlite"
        self.cache = ReadingCache(cache if setting("BRANDGUARD_T2_CACHE", "1") != "0" else None)
        self.stats = {"read": 0, "calls": 0, "cache_hits": 0, "failures": 0, "injections": 0}

    def _complete(self, system: str, user: str, max_tokens: int) -> str:  # pragma: no cover - transport
        raise NotImplementedError

    def adjudicate(self, case: CaseSummary) -> AdjudicatorOpinion:
        facts = json.dumps(_case_facts(case), ensure_ascii=False, indent=2, default=str)
        text = self._complete("", _PROMPT.format(facts=facts), 300)
        return _parse_opinion(text)

    def read(self, case: CaseSummary, text: CaseText) -> AdjudicatorOpinion:
        facts = _case_facts(case)
        self.stats["read"] += 1
        key = ReadingCache.key(self.model, text, facts)
        reading = self.cache.get(key)
        if reading is None:
            system, user = render_prompt(text, facts)
            try:
                raw = self._complete(system, user, 400)
                self.stats["calls"] += 1
            except Exception:
                self.stats["failures"] += 1
                raise
            reading = parse_reading(raw, text.description_excerpt)
            if reading.parsed:
                self.cache.put(key, reading)
        else:
            self.stats["cache_hits"] += 1
        if reading.embedded_instructions == "yes":
            self.stats["injections"] += 1
        hard = _hard_facts(case, text)
        reading = apply_hard_facts(reading, hard)
        leaning, strength, reasoning = derive_leaning(reading, hard)
        return AdjudicatorOpinion(leaning=leaning, strength=strength, reasoning=reasoning, reading=reading)


class AnthropicAdjudicator(LLMAdjudicator):
    """Adjudicator backed by the Anthropic API.

    Requires ANTHROPIC_API_KEY. Import of the SDK is deferred so the core
    package installs and tests without the optional dependency.
    """

    provider = "anthropic"

    def __init__(self, model: str = DEFAULT_MODEL, cache_path: Path | None = None):
        super().__init__(model, cache_path)

    def _complete(self, system: str, user: str, max_tokens: int) -> str:
        import anthropic

        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"],
                                     timeout=_LLM_TIMEOUT_S, max_retries=1)
        kwargs = {"system": system} if system else {}
        response = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": user}],
            **kwargs,
        )
        return "".join(b.text for b in response.content if b.type == "text")


class OpenAIAdjudicator(LLMAdjudicator):
    """Adjudicator backed by the OpenAI API.

    Same contract as AnthropicAdjudicator; only the transport differs. Requires
    OPENAI_API_KEY. The SDK import is deferred like the Anthropic one.
    """

    provider = "openai"

    def __init__(self, model: str = DEFAULT_OPENAI_MODEL, cache_path: Path | None = None):
        super().__init__(model, cache_path)

    def _complete(self, system: str, user: str, max_tokens: int) -> str:
        import openai

        client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"],
                               timeout=_LLM_TIMEOUT_S, max_retries=1)
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": user}]
        try:
            response = client.chat.completions.create(
                model=self.model, max_tokens=max_tokens, messages=messages,
                response_format={"type": "json_object"},
            )
        except openai.BadRequestError:
            # An older or third-party model without JSON mode: plain reply,
            # the parser copes with prose around the object.
            response = client.chat.completions.create(
                model=self.model, max_tokens=max_tokens, messages=messages)
        return response.choices[0].message.content or ""


def get_adjudicator() -> Adjudicator:
    """Select the adjudicator by available credentials.

    Order: Anthropic key, then OpenAI key, then the deterministic rule
    adjudicator. A .env file at the repo root is consulted first (without
    overriding real environment variables), so a developer can keep keys out of
    the shell and out of the repo at once.
    """
    _load_dotenv_once()
    model = os.environ.get("BRANDGUARD_LLM_MODEL") or None
    if os.environ.get("ANTHROPIC_API_KEY"):
        _require_sdk("anthropic")
        return AnthropicAdjudicator(model or DEFAULT_MODEL)
    if os.environ.get("OPENAI_API_KEY"):
        _require_sdk("openai")
        return OpenAIAdjudicator(model or DEFAULT_OPENAI_MODEL)
    return RuleAdjudicator()


def describe_adjudicator() -> tuple[str, str | None]:
    """(provider, model) for the health endpoint, without building a client."""
    _load_dotenv_once()
    model = os.environ.get("BRANDGUARD_LLM_MODEL") or None
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic", model or DEFAULT_MODEL
    if os.environ.get("OPENAI_API_KEY"):
        return "openai", model or DEFAULT_OPENAI_MODEL
    return "rules", None


def _require_sdk(module: str) -> None:
    """Fail loudly when a key is configured but its SDK is not installed.

    Falling back silently to the rule adjudicator would be worse: the operator
    would believe the model is in use while it is not. A clear error with the
    install command keeps the system honest about what is running.
    """
    import importlib.util

    if importlib.util.find_spec(module) is None:
        raise RuntimeError(
            f"{module.upper()}_API_KEY is set but the '{module}' SDK is not installed. "
            f'Run: pip install -e ".[dev,icons,llm]"'
        )


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
