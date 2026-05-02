"""OutlookMonarchSelectorPack.

Pure logic. Speaks to the OutlookPage protocol — does not import Playwright.
Tests use FakeOutlookPage to exercise every branch without a browser.
"""

from __future__ import annotations

import logging

from openclaw.providers.outlook.page import OutlookPage
from openclaw.providers.outlook.types import (
    NeedsInteractiveLogin,
    OutlookMessageSummary,
    OutlookVariant,
    UIVariantUnsupported,
)
from openclaw.providers.selector_pack import SelectorPack

_log = logging.getLogger("openclaw.outlook.selectors")


class OutlookMonarchSelectorPack(SelectorPack):
    """Selector pack for the Monarch (new Outlook web) variant.

    Milestone (2): read-only. `outlook.mail.list` only. No read, draft, or
    send. Other tools come later in their own packs / methods.
    """

    name = "outlook_monarch_v0"
    supported_tools = frozenset({"outlook.mail.list"})

    def list_messages(
        self,
        page: OutlookPage,
        *,
        limit: int = 25,
        unread_only: bool = False,
    ) -> list[OutlookMessageSummary]:
        """Return normalized message summaries from the inbox.

        Raises:
            NeedsInteractiveLogin: page is at a Microsoft login redirect.
            UIVariantUnsupported: detected variant is not Monarch.
        """
        if page.is_login_screen():
            raise NeedsInteractiveLogin(
                "Outlook session at login redirect; user must sign in."
            )

        variant = page.detect_variant()
        if variant != OutlookVariant.MONARCH:
            raise UIVariantUnsupported(variant)

        raw_rows = page.harvest_message_rows(limit=limit, unread_only=unread_only)
        return [self._normalize(r) for r in raw_rows]

    @staticmethod
    def _normalize(row: dict) -> OutlookMessageSummary:
        return OutlookMessageSummary(
            id=str(row.get("id") or ""),
            from_name=row.get("from_name"),
            from_address=row.get("from_address"),
            subject=row.get("subject") or "",
            received_at=row.get("received_at"),
            snippet=row.get("snippet"),
            is_read=row.get("is_read"),
        )
