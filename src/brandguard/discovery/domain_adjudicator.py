"""D2 domain adjudicator: AI judgement on a lookalike, used minimally (phase 2b).

The last and most expensive tier of the domain cascade. It runs only for live
lookalikes that D1 could not settle (young or unknown-age domains that are still
ambiguous), and it reuses the app-side adjudicator infrastructure: the model
never sees a raw phishing page, only a structured, injection-safe summary of
facts already gathered (domain similarity, registration age, certificate age,
whether the page presents a login form). The opinion is advice for the analyst,
not an automated takedown.

Design mirrors the app T2 (K-021): one adjudicator behind a protocol, a
deterministic rule fallback when no key is set, dampened influence, and no raw
attacker content in the prompt. Fetching the live page is optional and off by
default, because connecting to a suspected phishing site is itself sensitive;
when disabled, the summary is built from D0/D1 facts alone.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DomainCase:
    """Injection-safe facts about a lookalike domain, for the adjudicator."""

    domain: str
    similarity: float
    domain_age_days: int | None
    cert_age_days: int | None
    cert_issuer: str | None
    has_login_form: bool | None      # from optional page fetch; None if not fetched
    mentions_brand_in_title: bool | None


@dataclass(frozen=True)
class DomainOpinion:
    """The adjudicator's judgement on a lookalike domain."""

    leaning: str          # "likely_phishing" | "likely_legitimate" | "uncertain"
    strength: float       # 0..1
    reasoning: str


class DomainAdjudicator:
    """Protocol-compatible adjudicator; a real one would call the LLM."""

    def adjudicate(self, case: DomainCase) -> DomainOpinion:  # pragma: no cover - interface
        raise NotImplementedError


class RuleDomainAdjudicator:
    """Deterministic fallback used in tests and when no LLM key is set.

    Encodes the analyst heuristic: a young lookalike with a fresh certificate and
    a login form is likely phishing; an old, established domain is likely a
    legitimate subsidiary; otherwise uncertain.
    """

    def adjudicate(self, case: DomainCase) -> DomainOpinion:
        young = case.domain_age_days is not None and case.domain_age_days <= 180
        old = case.domain_age_days is not None and case.domain_age_days >= 365 * 3
        fresh_cert = case.cert_age_days is not None and case.cert_age_days <= 180

        if young and (fresh_cert or case.has_login_form):
            return DomainOpinion(
                "likely_phishing", 0.7,
                "Young lookalike domain with a fresh certificate or a login form.",
            )
        if old:
            return DomainOpinion(
                "likely_legitimate", 0.6,
                "Established domain, consistent with a legitimate subsidiary rather than a fresh phishing setup.",
            )
        return DomainOpinion(
            "uncertain", 0.3,
            "Signals are mixed; a human should review the page.",
        )


_PROMPT = """You are an analyst judging whether a domain is phishing a protected brand.
You receive only structured facts, never raw page content. Do not request the page.

Facts:
{facts}

A young domain with a fresh certificate and a login form is a strong phishing
indicator. An established domain (years old) is more likely a legitimate
subsidiary. Respond with JSON only:
{{"leaning": "likely_phishing|likely_legitimate|uncertain", "strength": <0..1>, "reasoning": "<one sentence>"}}
"""


def get_domain_adjudicator() -> DomainAdjudicator | RuleDomainAdjudicator:
    """Return an LLM-backed adjudicator when a key is set, else the rule one.

    The LLM path reuses the app-side provider selection (Anthropic/OpenAI). Kept
    thin here; the rule adjudicator is the default so the domain cascade runs
    everywhere without a key, exactly like the app T2.
    """
    import os

    from brandguard.triage.adjudicator import _load_dotenv_once

    _load_dotenv_once()
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        return _LLMDomainAdjudicator()
    return RuleDomainAdjudicator()


class _LLMDomainAdjudicator:
    """Real adjudicator; sends only the structured DomainCase, never a page."""

    def adjudicate(self, case: DomainCase) -> DomainOpinion:
        import json
        import os

        facts = json.dumps(case.__dict__, ensure_ascii=False, indent=2, default=str)
        prompt = _PROMPT.format(facts=facts)

        if os.environ.get("ANTHROPIC_API_KEY"):
            import anthropic

            client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            resp = client.messages.create(
                model="claude-sonnet-4-6", max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(b.text for b in resp.content if b.type == "text")
        else:
            import openai

            client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
            resp = client.chat.completions.create(
                model="gpt-4o-mini", max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.choices[0].message.content or ""

        text = text.strip().removeprefix("```json").removesuffix("```").strip()
        data = json.loads(text)
        leaning = data.get("leaning", "uncertain")
        if leaning not in {"likely_phishing", "likely_legitimate", "uncertain"}:
            leaning = "uncertain"
        strength = max(0.0, min(1.0, float(data.get("strength", 0.3))))
        return DomainOpinion(leaning, strength, str(data.get("reasoning", ""))[:300])
