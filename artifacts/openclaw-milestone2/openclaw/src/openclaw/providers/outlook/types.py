"""Public types for the Outlook provider package.

Kept independent of Playwright so the logic layers (variant detection,
normalization, taint tagging) are testable without a browser.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from openclaw.types.core import TaintTag, TrustLevel


# --------------------------------------------------------------------------- #
# UI variant
# --------------------------------------------------------------------------- #


class OutlookVariant(str, Enum):
    """UI variants the runtime knows about.

    Only MONARCH is supported by milestone (2); CLASSIC_OWA and UNKNOWN
    return ui_variant_unsupported. LOGIN is detected separately and surfaces
    as needs_interactive_login.
    """

    LOGIN = "login"
    MONARCH = "monarch"
    CLASSIC_OWA = "classic_owa"
    UNKNOWN = "unknown"


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class NeedsInteractiveLogin(RuntimeError):
    """The current session is at a Microsoft login page; user must sign in."""


class UIVariantUnsupported(RuntimeError):
    """The detected Outlook UI variant has no selector pack."""

    def __init__(self, variant: OutlookVariant) -> None:
        super().__init__(f"Unsupported Outlook UI variant: {variant.value}")
        self.variant = variant


# --------------------------------------------------------------------------- #
# Normalized message summary
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class OutlookMessageSummary:
    """Normalized message summary returned by `outlook.mail.list`.

    Fields are deliberately separated (`from_name` vs `from_address`,
    `received_at` as ISO 8601) so downstream consumers don't have to parse
    a combined display string. Every external field carries taint.
    """

    id: str
    from_name: str | None
    from_address: str | None
    subject: str
    received_at: str | None  # ISO 8601 in UTC when known
    snippet: str | None
    is_read: bool | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Field-to-source mapping. Every external field carries taint per spec §11.2;
# do not special-case "subject" or "from" as safe.
_TAINT_FIELDS: tuple[tuple[str, str], ...] = (
    ("from_name", "outlook_email_header"),
    ("from_address", "outlook_email_header"),
    ("subject", "outlook_email_subject"),
    ("received_at", "outlook_email_header"),
    ("snippet", "outlook_email_body"),
)


def to_taint_tags(messages: list[OutlookMessageSummary]) -> list[TaintTag]:
    """Build the taint-tag list for a normalized message array."""
    tags: list[TaintTag] = []
    for i, msg in enumerate(messages):
        prefix = f"messages[{i}]"
        for field, source in _TAINT_FIELDS:
            if getattr(msg, field) is not None:
                tags.append(
                    TaintTag(
                        field=f"{prefix}.{field}",
                        trust=TrustLevel.UNTRUSTED_USER_CONTENT,
                        source=source,
                    )
                )
    return tags
