"""OutlookMonarchSelectorPack tests."""

from __future__ import annotations

import pytest

from openclaw.providers.outlook import (
    NeedsInteractiveLogin,
    OutlookMonarchSelectorPack,
    OutlookVariant,
    UIVariantUnsupported,
)
from openclaw.providers.outlook.page import detect_variant_from_url
from tests._helpers.outlook import FakeOutlookPage, make_canned_rows


# --- pack metadata ----------------------------------------------------------


def test_selector_pack_supports_only_outlook_mail_list():
    """Required: read-only, narrow scope. No outlook.mail.read, no Teams."""
    pack = OutlookMonarchSelectorPack()
    assert pack.supported_tools == frozenset({"outlook.mail.list"})
    assert pack.supports("outlook.mail.list")
    for forbidden in (
        "outlook.mail.read",
        "outlook.mail.send_approved",
        "teams.chat.list",
        "browser.click",
    ):
        assert not pack.supports(forbidden)


# --- list_messages: happy path ---------------------------------------------


def test_pack_lists_messages_with_normalized_shape():
    pack = OutlookMonarchSelectorPack()
    page = FakeOutlookPage(rows=make_canned_rows())
    msgs = pack.list_messages(page, limit=25, unread_only=False)
    assert len(msgs) == 3
    # Shape: every summary has the new normalized fields.
    for m in msgs:
        assert m.id
        assert hasattr(m, "from_name")
        assert hasattr(m, "from_address")
        assert hasattr(m, "received_at")
        assert hasattr(m, "snippet")


def test_pack_respects_unread_only_filter():
    pack = OutlookMonarchSelectorPack()
    page = FakeOutlookPage(rows=make_canned_rows())
    msgs = pack.list_messages(page, unread_only=True)
    assert len(msgs) == 2
    assert all(m.is_read is False for m in msgs)


def test_pack_respects_limit():
    pack = OutlookMonarchSelectorPack()
    page = FakeOutlookPage(rows=make_canned_rows())
    msgs = pack.list_messages(page, limit=1)
    assert len(msgs) == 1


# --- list_messages: error paths --------------------------------------------


def test_login_redirect_raises_needs_interactive_login():
    """Required: page on the login screen → NeedsInteractiveLogin."""
    pack = OutlookMonarchSelectorPack()
    page = FakeOutlookPage(is_login=True)
    with pytest.raises(NeedsInteractiveLogin):
        pack.list_messages(page)


def test_unknown_ui_variant_raises_ui_variant_unsupported():
    """Required: unknown variant → UIVariantUnsupported."""
    pack = OutlookMonarchSelectorPack()
    page = FakeOutlookPage(variant=OutlookVariant.UNKNOWN)
    with pytest.raises(UIVariantUnsupported) as excinfo:
        pack.list_messages(page)
    assert excinfo.value.variant == OutlookVariant.UNKNOWN


def test_classic_owa_raises_ui_variant_unsupported():
    """Classic OWA is recognized but unsupported in milestone (2)."""
    pack = OutlookMonarchSelectorPack()
    page = FakeOutlookPage(variant=OutlookVariant.CLASSIC_OWA)
    with pytest.raises(UIVariantUnsupported) as excinfo:
        pack.list_messages(page)
    assert excinfo.value.variant == OutlookVariant.CLASSIC_OWA


def test_pack_does_not_guess_against_unknown_variant():
    """No 'best-effort' fallback — silence is a refusal, by design."""
    pack = OutlookMonarchSelectorPack()
    page = FakeOutlookPage(
        variant=OutlookVariant.UNKNOWN,
        rows=make_canned_rows(),  # rows present but not Monarch
    )
    with pytest.raises(UIVariantUnsupported):
        pack.list_messages(page)


# --- variant detection helper ----------------------------------------------


def test_detect_variant_from_url_login_hosts():
    assert detect_variant_from_url("https://login.microsoftonline.com/foo") == OutlookVariant.LOGIN
    assert detect_variant_from_url("https://login.live.com/oauth20_authorize.srf") == OutlookVariant.LOGIN


def test_detect_variant_from_url_outlook_hosts_returns_none():
    """On an Outlook host, URL alone is not enough — caller must inspect markers."""
    for url in (
        "https://outlook.office.com/mail",
        "https://outlook.office365.com/mail/inbox",
        "https://outlook.live.com/mail/0/inbox",
    ):
        assert detect_variant_from_url(url) is None


def test_detect_variant_from_url_unrecognized_returns_unknown():
    assert detect_variant_from_url("https://example.com") == OutlookVariant.UNKNOWN
    assert detect_variant_from_url("about:blank") == OutlookVariant.UNKNOWN
