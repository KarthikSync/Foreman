# CLAUDE.md — OpenClaw Core Runtime (codename: Foreman)

This file is the operating manual for Claude Code working in this repo. Read it before writing any code. The rules below are not preferences — they are architectural invariants that protect the runtime from regressions that would be hard to back out.

## What this repo is

OpenClaw Core Runtime is a **local agent action framework** for Windows and Microsoft 365. It exposes high-level domain tools (Outlook, Teams) over MCP so any MCP-compatible client (VS Code Copilot Chat, Claude Desktop, Claude Code) can drive the user's already-authenticated work surfaces safely.

It is **not** a browser automation script. The browser is one provider behind a Tool Registry, Safety Governor, Provider Router, audit trace, memory store, and agent harness.

## Where to read first

- `SPEC-v0.2.md` — source of truth. Do not modify without discussion.
- `README.md` — install and usage.
- `CLAUDE.md` files in subdirectories — scoped instructions for the active feature in that subtree.

## Architectural invariants — DO NOT BREAK

These rules are non-negotiable. Violations are reverted, not debated.

1. **Provider-routed runtime, not a browser script.** Every tool call flows: MCP → Tool Registry → Safety Governor → Provider Router → Provider → Audit Envelope. Do not add code paths that bypass this. Do not put dispatch logic anywhere except where it already lives (`engine.py`, `router.py`).

2. **`RuntimeMode` is mandatory.** Modes: `SERVE_LOCAL`, `HARNESS_FAKE`, `HARNESS_LIVE`. Provider chains are declared in `runtime/modes.py`, never in tool metadata. **Never add `fake_outlook` to `SERVE_LOCAL`.** Every `build_engine(...)` call must specify a `mode=`.

3. **No fake provider in production paths.** `fake_outlook` exists in the `HARNESS_FAKE` chain only. If you find yourself wanting fake data in `SERVE_LOCAL`, you are solving the wrong problem.

4. **stdout is MCP-only.** The MCP stdio transport reserves stdout for JSON-RPC. All logging, diagnostics, and audit go to stderr or files. The `logging` module is configured at MCP server module load to strip any pre-existing stdout `StreamHandler`. Never call `print()` from runtime code. The CLI is the exception — it owns its own stdout because it is not the MCP server.

5. **Primitives are hidden by default.** `browser.click` and similar gated primitives are `GATED_PRIMITIVE`. They are absent from `tools/list` unless explicitly enabled. The MCP `serve` path never enables primitives. Tests that need primitives use `--harness` mode or pass `primitives_enabled=True` to `build_engine`.

6. **All external content is tainted.** Every byte from email bodies, chat messages, page text, document contents, or any other external surface carries a `TaintTag` with `TrustLevel.UNTRUSTED_USER_CONTENT`. Do not strip taint. Do not special-case "subject" or "sender" as safe. Tainted content cannot authorize destructive actions, cannot extend allowlists, cannot create long-term memory entries.

7. **No destructive actions without an approval-token flow.** `confirm: true` is not a safety boundary. Destructive tools split into `prepare_*` (returns `action_hash`) and `*_approved` (requires `approval_token` + matching `action_hash`, both server-issued, both bound, both single-use). Server issues tokens only after human approval. The model never sees a token until a human has approved the exact action.

8. **Profile-aware schema from day one.** Every persisted record — audit envelope, approval token, memory row, harness trace, rate-limit counter — carries `profile_id`. v0.1 ships single-profile, but the schema must already accept multi-profile without migration.

9. **No silent inference.** Memory stores how the runtime operates (selectors, preferences). Memory does not silently index the user's mailbox. There is no `memory.write(any_key, any_value)` tool. All writes go through schema-validated, typed paths.

## Test discipline

The pinned command is:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

Plain `pytest` may hang or behave unpredictably due to environment-installed plugins. Always use the pinned command in CI and when validating changes locally. All tests must pass before any commit; the suite was 86/86 at milestone (2). New work adds tests, never removes them.

Tests must run without Playwright or Edge installed unless explicitly testing the live launch path. Browser-touching code is exercised through the `FakeOutlookPage` seam in `tests/_helpers/outlook.py`; the `_page_factory_for_test` parameter on `BrowserProvider` exists for this. Never launch real Edge in CI.

## File layout

```
src/openclaw/
  types/         core dataclasses + closed error enum
  registry/      ToolRegistry + default catalog (NO provider_chain in metadata)
  runtime/       engine + bootstrap + modes (RuntimeMode + chain resolver)
  safety/        SafetyGovernor (classify, validate, gate)
  router/        ProviderRouter
  providers/
    base.py             abstract Provider with optional close()
    selector_pack.py    abstract SelectorPack base
    fake_outlook.py     deterministic harness fake; same shape as live
    memory.py           SQLite-backed preferences provider
    browser.py          Playwright BrowserProvider with selector dispatch
    browser_lifecycle.py  ProfileLock, profile path resolution
    outlook/            outlook subpackage — see CLAUDE.md inside
  audit/                JSONL envelope trace
  memory/               SQLite store
  harness/              scenario runner + scenarios/*.yaml
  mcp_server/           stdio server (stderr-only logging)
  cli.py                CLI entry point

tests/
  _helpers/             test-only fakes (e.g., FakeOutlookPage)
  test_*.py             test modules
```

## Workflow rules

- **Tests first.** When adding a feature, write the failing tests first, confirm they fail for the right reason, then implement. The test suite is the contract.
- **Lazy imports for heavy deps.** Playwright, MCP SDK, and other optional dependencies are imported inside the function that uses them, never at module load. The package must import cleanly without optional extras.
- **New tools require chain entries.** Adding a tool means adding it to the `default_registry()` *and* declaring its provider chain in all three `PROVIDER_CHAINS[mode]` maps in `runtime/modes.py`, even if the chain is `()` for some modes. Silence is a refusal, by design.
- **New tools require an action class.** Pick `read`, `state`, `destructive`, or `gated_primitive`. The class drives Safety Governor behavior; getting it wrong silently lowers the security posture.
- **Stable error codes only.** The `ErrorCode` enum in `types/errors.py` is closed. New error codes need a corresponding spec entry. Don't add ad-hoc error strings.
- **Audit envelope is the source of truth.** Anything that needs to be observed by the harness, telemetry, or debugging belongs in the envelope, not in side-channel logs.

## What NOT to do

- Don't add fake providers to `SERVE_LOCAL` chains.
- Don't surface primitives in default `tools/list`.
- Don't introduce a `confirm: true` shortcut for destructive actions.
- Don't `print()` from runtime code (CLI is the only exception).
- Don't import Playwright or MCP SDK at module load.
- Don't write a generic `memory.write(key, value)` tool.
- Don't bypass `ProfileLock` to "just launch a browser quickly."
- Don't point a browser context at the user's normal Edge/Chrome profile — `reject_normal_browser_profile` exists to prevent this.
- Don't modify `SPEC-v0.2.md` without explicit discussion.
- Don't add a new dependency without checking `pyproject.toml`'s extras structure (`mcp`, `browser`, `dev`).
- Don't change envelope keys without updating every consumer (audit, harness, telemetry).

## Naming

"Foreman" is a working codename used in some commits and discussion. The architectural name used in code is "OpenClaw Core Runtime". Final product/package naming is unresolved. Do not rename packages, repository names, or imports as a side effect of feature work.
