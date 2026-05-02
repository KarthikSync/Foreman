# CLAUDE.md — providers/outlook (Milestone 3 active)

This file scopes Claude Code's work in the `providers/outlook` subtree to a single milestone. The root `CLAUDE.md` rules apply on top of this; in any conflict, root rules win.

## Active feature

**Milestone 3: live BrowserProvider hardening for `outlook.mail.list`.**

The previous milestone wired persistent context, profile lock, and a conservative selector pack that returns mostly-`None` fields. This milestone makes the live path actually usable against Outlook Monarch: explicit navigation, scoped selectors, populated fields, real variant detection, real login handling.

## Architectural invariant — read this first

**The live BrowserProvider must produce the same envelope shape as the fake provider.** Provider implementations may differ; the tool contract and the audit envelope shape must not. When in doubt:

1. Run `outlook.mail.list` in `HARNESS_FAKE`, capture the envelope.
2. Run `outlook.mail.list` in `HARNESS_LIVE` against an injected `FakeOutlookPage`, capture the envelope.
3. Their keys and taint-output field names must match. Provider attribution (`fake_outlook` vs `browser`) is the only expected difference.

The test `test_live_provider_envelope_shape_matches_fake_provider` enforces this. Don't loosen it; tighten it as the live path populates more fields.

## In scope

1. **Explicit navigation** to `https://outlook.office.com/mail` before the first `harvest_message_rows` call. Work-account Outlook only for this milestone; personal accounts (`outlook.live.com`) are out of scope until explicitly added to the allowlist and tested. Navigation must respect the domain allowlist; hitting any URL outside the allowlist is a policy refusal (`domain_blocked`), not a redirect.
2. **Domain allowlist enforcement** during navigation. Every navigation goes through a check against the configured allowlist. Outlook hosts only.
3. **Login redirect detection** → `needs_interactive_login`. If navigation lands on `login.microsoftonline.com` or `login.live.com`, surface this as a typed error, never silently retry.
4. **Unknown UI variant** → `ui_variant_unsupported`. No best-effort guessing. If detection cannot confirm Monarch, refuse the call. Use accessibility-role markers; do not infer Monarch from the URL alone.
5. **Scoped selectors.** The current implementation uses a global `get_by_role("option")`, which would match options in any unrelated dropdown. Anchor row enumeration **under** the message listbox: `role="listbox"[name~="Message list"]` then `role="option"` inside it. Never use a global option locator.
6. **Populate `from_address`, `received_at`, `snippet`** where Outlook Monarch exposes them stably. Leave fields as `None` only when no stable selector exists. The normalizer already tolerates missing fields.
7. **Every returned external field carries a `TaintTag`.** This includes `from_address`. The `to_taint_tags` helper handles this if the field is non-`None`; do not introduce code that strips taint for any field.
8. **`HARNESS_FAKE` stays fully isolated from any browser launch path.** The mode boundary is the only thing that prevents a HARNESS_FAKE run from accidentally launching Edge — guard it as you change code.

## Out of scope — DO NOT IMPLEMENT HERE

These belong to later milestones. Adding any of them now is scope creep:

- `outlook.mail.read` (body, headers, attachments)
- `outlook.mail.create_draft` / `prepare_send` / `send_approved`
- Teams selectors of any kind
- `resource.search` / `resource.answer`
- Browser primitives (`browser.click`, `browser.type`, `browser.press_key`)
- Approval tray app or any UI surface
- `GraphProvider` implementation
- Multi-profile activation
- Streamable HTTP transport
- Auto-update or selector-pack hot reload

If a change requires touching any of these to work, stop and ask — the milestone scope is wrong, not the code.

## Test-first workflow

Tests come before implementation. The order is:

1. Write the test using `tests/_helpers/outlook.py:FakeOutlookPage`. Confirm it fails for the right reason (not for a typo, missing import, or stale fixture).
2. Implement against `PlaywrightOutlookPage` in `page.py`.
3. For DOM-level behaviors that need a real Monarch shape, add a deterministic fixture under `tests/_fixtures/outlook/` (create the directory) — saved HTML/a11y snapshot or Playwright trace. Replay via Playwright `Page.route` if simulating network, but selector assertions must run against the captured DOM/a11y structure. The fixture path must be deterministic and committed.
4. Run `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q`. All 86 existing tests must still pass.

Tests that require Playwright or Edge to be installed must be marked with `pytest.importorskip("playwright")` so CI without browser binaries skips them gracefully.

## Selector strategy

Spec §7.3 priority ladder, applied strictly:

1. Accessibility roles with names. Most stable across UI updates. Use `page.get_by_role("...", name="...")`.
2. Stable `data-*` attributes Microsoft has historically kept (e.g., `data-app-section`, `data-convid`).
3. Visible text with structural anchoring (`get_by_text(...).filter(has=...)`).
4. CSS path matches. Last resort. Fragile.

Concrete rules for Monarch:

- **Anchor first, enumerate second.** Locate the listbox, then iterate options inside it. Global `get_by_role("option")` is forbidden.
- **Use Playwright `Locator`s, not element handles.** Locators are retryable and strictness-checked.
- **Subject** is `role="heading"` inside the row.
- **Sender display name** is in `[data-app-section="sender"]` (Monarch convention; verify against current DOM before committing).
- **Unread state** is signaled in the row's `aria-label` (contains "unread") or via a CSS class (less stable; prefer aria-label).
- **Conversation id** is `data-convid` on the row option. Use it for the `id` field — synthetic `row_N` ids are a fallback only.
- **Don't assume English locale strings.** Where the role's `name` is English-only ("Message list", "Folder pane"), document the assumption and add a TODO for localization. Do not block this milestone on it.

## Files in this subtree

- `types.py` — `OutlookVariant`, `OutlookMessageSummary`, `to_taint_tags`, exceptions. **Pure data and logic. Do not import Playwright here.**
- `page.py` — `OutlookPage` protocol, `detect_variant_from_url` pure helper, `PlaywrightOutlookPage` concrete implementation. **Production page-walking lives here.** Lazy-imports Playwright.
- `selectors.py` — `OutlookMonarchSelectorPack`. Pure logic against the `OutlookPage` protocol. **Does not import Playwright.**
- `__init__.py` — public exports.

The protocol/concrete split is intentional. Selector-pack tests use `FakeOutlookPage`. Only `PlaywrightOutlookPage` touches the real browser. Don't merge these layers.

## Test seams to use

- **`tests/_helpers/outlook.py:FakeOutlookPage`** is the canonical test fake. Extend it (don't replace) when new test scenarios need new behavior. If you add a method to the `OutlookPage` protocol, add a corresponding implementation here.
- **`BrowserProvider(_page_factory_for_test=...)`** injects a custom `OutlookPage` factory. Use it in `tests/test_browser_provider_outlook.py` for engine-level integration tests that exercise the envelope path without launching Edge.
- **`make_canned_rows()`** in `tests/_helpers/outlook.py` returns a deterministic raw-row list for harvest tests.

## Done definition

This milestone is done when all of the following are true:

1. New required tests pass:
   - Explicit navigation triggers domain-allowlist enforcement: an off-allowlist URL must return `domain_blocked`. It must not be collapsed into `provider_unavailable`. `domain_blocked` is a policy decision (the Safety Governor refused this URL); `provider_unavailable` is an operational failure (the provider could not act). Conflating them weakens the Safety Governor contract.
   - Login redirect path produces a `needs_interactive_login` envelope.
   - Unknown UI variant produces a `ui_variant_unsupported` envelope.
   - Monarch DOM walk populates `from_address`, `received_at`, and `snippet` from a deterministic fixture: saved HTML/a11y snapshot, Playwright trace, or equivalent replay surface. HAR may be used for network replay, but selector assertions must validate against DOM/a11y structure, not network traffic.
   - `HARNESS_FAKE` never launches a browser even when full readiness is configured.
   - Scoped selector test: planted out-of-listbox `role="option"` elements are NOT included in results.
2. Live envelope shape matches fake envelope shape (same keys, same taint field names where the field is populated).
3. `openclaw harness run list_unread_mail --provider live` succeeds against a manually signed-in profile (manual smoke; not part of automated CI).
4. The 86 existing tests still pass under `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q`. The new tests bring the count up; none are removed.
5. No primitives, no destructive actions, no out-of-scope tools were added.
