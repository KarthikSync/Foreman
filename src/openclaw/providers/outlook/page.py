"""Outlook page abstraction.

`OutlookPage` is the protocol the selector pack speaks to. Two concrete
implementations:

  - `PlaywrightOutlookPage` (production) wraps a real Playwright Page.
  - `FakeOutlookPage` (tests) returns canned variant + rows.

This split lets every layer above the page protocol — normalization,
selector pack logic, BrowserProvider dispatch — be tested without
launching a real browser.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from openclaw.providers.outlook.types import OutlookVariant

_log = logging.getLogger("openclaw.outlook.page")


@runtime_checkable
class OutlookPage(Protocol):
    """Abstract page surface."""

    def url(self) -> str: ...

    def is_login_screen(self) -> bool: ...

    def detect_variant(self) -> OutlookVariant: ...

    def harvest_message_rows(
        self, *, limit: int, unread_only: bool
    ) -> list[dict[str, Any]]:
        """Return raw row dicts (un-normalized).

        Each row dict should contain: id, from_name?, from_address?, subject?,
        received_at?, snippet?, is_read?. Missing fields are tolerated by the
        normalizer.
        """


# --------------------------------------------------------------------------- #
# Variant detection helpers (URL-based, structural-marker-based).
#
# Pure functions — no Playwright import. PlaywrightOutlookPage uses these.
# --------------------------------------------------------------------------- #


_LOGIN_HOSTS = (
    "login.microsoftonline.com",
    "login.live.com",
)
_OUTLOOK_HOSTS = (
    "outlook.office.com",
    "outlook.office365.com",
    "outlook.live.com",
)


def detect_variant_from_url(url: str) -> OutlookVariant | None:
    """First-pass variant detection from URL only.

    Returns:
      LOGIN if URL is a Microsoft login redirect.
      None if URL is an Outlook host (caller must inspect the page for
        Monarch vs Classic markers).
      UNKNOWN otherwise.
    """
    u = url.lower()
    for host in _LOGIN_HOSTS:
        if host in u:
            return OutlookVariant.LOGIN
    for host in _OUTLOOK_HOSTS:
        if host in u:
            return None  # caller must inspect markers
    return OutlookVariant.UNKNOWN


# --------------------------------------------------------------------------- #
# Production Playwright-backed page (lazy)
# --------------------------------------------------------------------------- #


class PlaywrightOutlookPage:
    """OutlookPage backed by a real Playwright Page.

    Constructed by BrowserProvider after the persistent context is launched
    and the Outlook surface is navigated. This class never imports Playwright
    at module load — only when methods are called against a real page.

    Selectors follow the priority from spec §7.3:
      1. Accessibility roles with names (most stable).
      2. Stable data-* attributes Microsoft has historically kept.
      3. Visible text with structural anchoring.
      4. CSS path matches (last resort).
    """

    def __init__(self, page: Any) -> None:
        # `page` is duck-typed Playwright Page; we don't import the type here.
        self._page = page

    def url(self) -> str:
        return self._page.url

    def is_login_screen(self) -> bool:
        return detect_variant_from_url(self.url()) == OutlookVariant.LOGIN

    def detect_variant(self) -> OutlookVariant:
        url_verdict = detect_variant_from_url(self.url())
        if url_verdict is not None:
            return url_verdict

        # On an outlook.* host. Look for known structural markers.
        # Monarch's folder pane is a tree with the accessible name "Folder pane"
        # in English locales. Use accessibility role first per the priority
        # ladder; stable across UI minor revisions.
        try:
            folder_pane = self._page.get_by_role("tree", name="Folder pane")
            if folder_pane.count() > 0:
                return OutlookVariant.MONARCH
        except Exception as exc:  # pragma: no cover
            _log.warning("variant detection: tree role probe failed: %s", exc)

        # Classic OWA marker (heuristic): legacy `#mailModule` element.
        try:
            classic_marker = self._page.locator("#mailModule")
            if classic_marker.count() > 0:
                return OutlookVariant.CLASSIC_OWA
        except Exception as exc:  # pragma: no cover
            _log.warning("variant detection: classic marker probe failed: %s", exc)

        return OutlookVariant.UNKNOWN

    def harvest_message_rows(
        self, *, limit: int, unread_only: bool
    ) -> list[dict[str, Any]]:
        """Walk the Monarch message list and return raw row dicts.

        Selector strategy (Monarch):
          - The message list is `role=listbox` with the accessible name
            containing "Message list".
          - Each row is `role=option` underneath.
          - Within a row: subject is `role=heading`, sender is the first
            visible text element with the speaker name, etc.

        v0 implementation is intentionally conservative: it prefers role
        locators and returns whatever subset of fields it can extract.
        Missing fields stay None and the normalizer tolerates them.
        """
        try:
            listbox = self._page.get_by_role("listbox").filter(
                has_text=""
            )  # any non-empty listbox; refined below
        except Exception as exc:  # pragma: no cover
            _log.warning("harvest: listbox locator failed: %s", exc)
            return []

        rows = []
        try:
            options = self._page.get_by_role("option")
            count = min(options.count(), limit if not unread_only else limit * 3)
        except Exception as exc:  # pragma: no cover
            _log.warning("harvest: options enumeration failed: %s", exc)
            return []

        for i in range(count):
            opt = options.nth(i)
            try:
                aria_label = (opt.get_attribute("aria-label") or "").strip()
            except Exception:  # pragma: no cover
                aria_label = ""

            # Subject: prefer heading role inside the row.
            subject = None
            try:
                heading = opt.get_by_role("heading").first
                if heading.count() > 0:
                    subject = heading.inner_text(timeout=500).strip()
            except Exception:  # pragma: no cover
                pass

            # Sender: first non-heading text node — heuristic.
            from_name = None
            try:
                # Monarch puts sender display name in a span with `data-app-section="sender"`.
                sender = opt.locator('[data-app-section="sender"]').first
                if sender.count() > 0:
                    from_name = sender.inner_text(timeout=500).strip()
            except Exception:  # pragma: no cover
                pass

            # is_read: Monarch sets aria-selected/aria-checked or a CSS class
            # for unread; aria-label often contains "unread" too.
            is_read: bool | None
            if "unread" in aria_label.lower():
                is_read = False
            elif aria_label:
                is_read = True
            else:
                is_read = None

            # Stable id: the row's data-convid attribute when present.
            try:
                row_id = opt.get_attribute("data-convid") or f"row_{i}"
            except Exception:  # pragma: no cover
                row_id = f"row_{i}"

            row = {
                "id": row_id,
                "from_name": from_name,
                "from_address": None,  # Monarch does not expose mailbox in the row
                "subject": subject,
                "received_at": None,  # populated post-v0 once the timestamp
                # locator stabilizes; explicitly None for v0
                "snippet": None,
                "is_read": is_read,
            }

            if unread_only and is_read is True:
                continue
            rows.append(row)
            if len(rows) >= limit:
                break

        return rows
