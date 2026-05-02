"""Outlook provider package — selectors, types, page abstraction."""

from openclaw.providers.outlook.page import (
    OutlookPage,
    PlaywrightOutlookPage,
    detect_variant_from_url,
)
from openclaw.providers.outlook.selectors import OutlookMonarchSelectorPack
from openclaw.providers.outlook.types import (
    NeedsInteractiveLogin,
    OutlookMessageSummary,
    OutlookVariant,
    UIVariantUnsupported,
    to_taint_tags,
)

__all__ = [
    "OutlookMonarchSelectorPack",
    "OutlookPage",
    "PlaywrightOutlookPage",
    "OutlookVariant",
    "OutlookMessageSummary",
    "NeedsInteractiveLogin",
    "UIVariantUnsupported",
    "to_taint_tags",
    "detect_variant_from_url",
]
