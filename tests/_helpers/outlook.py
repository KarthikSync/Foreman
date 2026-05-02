"""FakeOutlookPage — test fake for the OutlookPage protocol.

Used both for unit tests of OutlookMonarchSelectorPack (where it stands in
for a real Playwright Page) and for integration tests of BrowserProvider
where we want to exercise the full dispatch path without launching Edge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from openclaw.providers.outlook.types import OutlookVariant


@dataclass
class FakeOutlookPage:
    variant: OutlookVariant = OutlookVariant.MONARCH
    is_login: bool = False
    rows: list[dict[str, Any]] = field(default_factory=list)
    current_url: str = "https://outlook.office.com/mail"

    def url(self) -> str:
        if self.is_login:
            return "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
        return self.current_url

    def is_login_screen(self) -> bool:
        return self.is_login

    def detect_variant(self) -> OutlookVariant:
        if self.is_login:
            return OutlookVariant.LOGIN
        return self.variant

    def harvest_message_rows(
        self, *, limit: int, unread_only: bool
    ) -> list[dict[str, Any]]:
        rows = list(self.rows)
        if unread_only:
            rows = [r for r in rows if r.get("is_read") is False]
        return rows[:limit]


def make_canned_rows() -> list[dict[str, Any]]:
    """Three rows in raw harvest shape — what `harvest_message_rows` would
    return on a real Outlook Monarch inbox.
    """
    return [
        {
            "id": "AAMkA-001",
            "from_name": "Alice Example",
            "from_address": None,
            "subject": "Q3 review draft",
            "received_at": None,
            "snippet": None,
            "is_read": False,
        },
        {
            "id": "AAMkA-002",
            "from_name": "Bob Example",
            "from_address": None,
            "subject": "Lunch tomorrow?",
            "received_at": None,
            "snippet": None,
            "is_read": False,
        },
        {
            "id": "AAMkA-003",
            "from_name": "Vendor Newsletter",
            "from_address": None,
            "subject": "Weekly digest",
            "received_at": None,
            "snippet": None,
            "is_read": True,
        },
    ]
