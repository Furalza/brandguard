"""D1 domain signals: WHOIS age and SSL certificate (phase 2b).

These run only for LIVE lookalike domains that D0 (string similarity) flagged
for review, because a WHOIS lookup and a TLS handshake cost a network round trip
and only make sense for a domain that actually exists. They add the strongest
attacker-independent evidence available for a website: how recently the domain
was registered and its certificate issued. A phishing domain is typically days
or weeks old with a fresh free certificate; a legitimate brand or subsidiary
domain is years old.

Everything fails soft. WHOIS is inconsistent across TLDs (especially country
TLDs like .com.tr) and rate-limited, and a TLS handshake can time out; on any
failure the signal returns None and the pipeline continues without it. This is
the missing-vs-zero discipline: an unavailable signal is absent, never guessed.
"""

from __future__ import annotations

import socket
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class DomainAgeSignal:
    """Result of a WHOIS age lookup."""

    registered_on: datetime | None
    age_days: int | None
    suspicious: bool
    evidence: str


# Certificate authorities. A free CA (Let's Encrypt, ZeroSSL) is the phisher's
# usual choice; a paid/organization CA is a weak legitimacy hint, never proof,
# since an attacker can also buy one. Used only to nudge priority, not to decide.
_FREE_CA_MARKERS = ("let's encrypt", "lets encrypt", "zerossl", "buypass", "google trust")


@dataclass(frozen=True)
class CertSignal:
    """Result of a TLS certificate inspection."""

    issued_on: datetime | None
    issuer: str | None
    age_days: int | None
    suspicious: bool
    free_ca: bool | None      # True=free CA, False=paid/org CA, None=unknown
    evidence: str


# A domain younger than this is a strong red flag for a lookalike: an attacker
# registers shortly before a campaign. Mirrors the young-account logic on apps.
_YOUNG_DOMAIN_DAYS = 180


def whois_age(domain: str) -> DomainAgeSignal | None:
    """Return a domain-age signal from WHOIS, or None if it cannot be determined.

    Only the creation date is used; registrant details are mostly redacted post
    GDPR and are not needed. Fails soft on any WHOIS error or missing date.
    """
    try:
        import whois  # python-whois, optional dependency

        data = whois.whois(domain)
    except Exception:  # noqa: BLE001 - WHOIS is brittle; treat any failure as unknown
        return None

    created = data.creation_date if data else None
    if isinstance(created, list):
        created = created[0] if created else None
    if not isinstance(created, datetime):
        return None

    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    age_days = (datetime.now(tz=UTC) - created).days
    if age_days < 0:
        return None

    young = age_days <= _YOUNG_DOMAIN_DAYS
    return DomainAgeSignal(
        registered_on=created,
        age_days=age_days,
        suspicious=young,
        evidence=(
            f"Domain registered {age_days} days ago"
            + (" (recently, consistent with a phishing setup)." if young
               else f" ({age_days // 365} years, consistent with an established site).")
        ),
    )


def cert_age(domain: str, *, timeout: float = 6.0) -> CertSignal | None:
    """Return a TLS-certificate signal, or None if it cannot be fetched.

    Connects on 443 and reads the certificate's notBefore date and issuer. Fails
    soft on timeout, no TLS, or handshake error.
    """
    context = ssl.create_default_context()
    try:
        with (
            socket.create_connection((domain, 443), timeout=timeout) as sock,
            context.wrap_socket(sock, server_hostname=domain) as ssock,
        ):
            cert = ssock.getpeercert()
    except Exception:  # noqa: BLE001 - a lookalike may have no/broken TLS; unknown
        return None

    not_before = cert.get("notBefore") if cert else None
    if not not_before:
        return None
    try:
        issued = datetime.strptime(not_before, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
    except ValueError:
        return None

    issuer_parts = dict(x[0] for x in cert.get("issuer", ())) if cert.get("issuer") else {}
    issuer = issuer_parts.get("organizationName") or issuer_parts.get("commonName")
    age_days = (datetime.now(tz=UTC) - issued).days
    young = age_days <= _YOUNG_DOMAIN_DAYS
    free_ca: bool | None = None
    if issuer:
        low = issuer.lower()
        free_ca = any(marker in low for marker in _FREE_CA_MARKERS)
    return CertSignal(
        issued_on=issued,
        issuer=issuer,
        age_days=age_days,
        suspicious=young,
        free_ca=free_ca,
        evidence=(
            f"TLS certificate issued {age_days} days ago"
            + (f" by {issuer}" if issuer else "")
            + (" (recent, free CA)." if young and free_ca else " (recent)." if young else ".")
        ),
    )
