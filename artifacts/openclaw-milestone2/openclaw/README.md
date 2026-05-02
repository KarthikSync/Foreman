# OpenClaw Core Runtime — v0.1 Scaffold (review patch)

> **Codename: Foreman.** Naming unresolved. See `SPEC-v0.2.md` (sibling document).

This is the v0.1 runnable skeleton, with the reviewer patch applied. The point
is to prove the framework shape — registry, safety governor, router, envelope,
audit, memory, harness — without letting Playwright selector fragility dominate
development.

## Reviewer patch summary

The first scaffold passed all tests but had an architectural blocker: the
fake provider was reachable from the production serve path because the
provider chain was hardcoded into the registry. This patch fixes that and
addresses four related issues.

| # | Fix |
|---|---|
| 1 | Provider chains are no longer in `ToolSpec`. They are resolved per `RuntimeMode` by `openclaw.runtime.modes.make_resolver`. The fake provider is reachable only in `HARNESS_FAKE`. |
| 2 | `RuntimeMode` enum added: `SERVE_LOCAL`, `HARNESS_FAKE`, `HARNESS_LIVE`. `build_engine` requires `mode=…`. |
| 3 | `session_id` is now stable per scenario (harness) and per connection (MCP server). The harness threads it into every `ToolCall`; the MCP server threads it into every `tools/call`. |
| 4 | `BrowserProvider.supports()` checks `enabled AND profile_dir AND profile_lock_acquired AND selector_pack AND tool_in_pack`. Live work starts with profile lock, not selectors. |
| 5 | Pytest is reproducible from a clean checkout: `[tool.pytest.ini_options]` pins `pythonpath`, `testpaths`, `addopts`. README documents `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` for CI. |

Plus an MCP discipline guarantee: stdout is reserved for MCP JSON-RPC, all
logging goes to stderr. There is a test for this (`test_mcp_stdout_discipline.py`).

## What's in v0.1

- **MCP stdio server** that starts cleanly in `SERVE_LOCAL` mode and exposes only safe default tools.
- **Tool Registry** with `outlook.mail.list`, `outlook.mail.read`, `memory.preferences.get`, `memory.preferences.set`, plus a hidden `browser.click` primitive (gated off).
- **RuntimeMode + per-mode chain map** in `runtime/modes.py`.
- **Safety Governor** that classifies action class, validates input via JSON Schema, blocks destructive calls outright (no approval flow yet), and gates primitives by default.
- **Provider Router** that walks the chain returned by the resolver and falls back on non-terminal failures.
- **FakeOutlookProvider** returning canned, taint-tagged messages — only routable in `HARNESS_FAKE`.
- **MemoryProvider** backed by SQLite at `~/.openclaw/openclaw.db`. Profile-aware (`profile_id` on every row). Schema-validated preference keys only.
- **Audit Trace** writing one normalized envelope per tool call to `~/.openclaw/audit.log` as JSONL.
- **Agent Harness** that runs YAML scenarios through the same execution path as live MCP traffic, with one stable `session_id` per scenario.
- **BrowserProvider** with explicit `BrowserReadiness` model; contract is in place; live selectors are not.

## What is *not* in v0.1 (deliberately)

`outlook.mail.send_approved`, `teams.chat.post_approved`, `resource.answer`,
selector pack hot updates, local tray approval app, GraphProvider, DesktopProvider,
Streamable HTTP, auto-update. All deferred. See spec.

## Acceptance criteria

```
openclaw harness run summarize_unread_mail --provider fake
```

Should prove (and does):

- harness uses `HARNESS_FAKE` mode
- one stable `session_id` for the whole scenario
- `outlook.mail.list` returns fake unread messages
- each message body/snippet/subject/from is tainted
- `audit.log` receives a valid envelope per call
- `tools/list` excludes primitives
- harness report passes
- no browser required

```
openclaw serve --stdio
```

Starts the MCP server in `SERVE_LOCAL` mode. Calling `outlook.mail.list` over
MCP returns `provider_unavailable` (the BrowserProvider is not selector-ready
in v0.1) — which is correct: refusal until live providers land. The fake
provider is **not** reachable from this path.

## Layout

```
src/openclaw/
  types/         core dataclasses & error enum
  registry/      ToolRegistry + default catalog (NO provider_chain)
  runtime/       engine + bootstrap + modes (RuntimeMode + chain resolver)
  safety/        SafetyGovernor (classify, validate, gate)
  router/        ProviderRouter
  providers/     base, fake_outlook, memory, browser (BrowserReadiness)
  audit/         JSONL envelope trace
  memory/        SQLite store
  harness/       scenario runner + scenarios/*.yaml
  mcp_server/    stdio server (stderr-only logging)
  cli.py         entry point
tests/           pytest suite
```

## Running

```bash
pip install -e ".[dev]"            # core + tests
pip install -e ".[dev,mcp]"        # + MCP stdio server

# Run the harness scenario (no browser, no network)
openclaw harness run summarize_unread_mail --provider fake

# Start the MCP stdio server (requires .[mcp])
openclaw serve --stdio

# Run tests — pyproject pins pythonpath/testpaths/addopts
pytest

# In CI, also set this to avoid environment plugin interference:
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest
```

## Configuration

Default base directory: `$OPENCLAW_HOME` or `~/.openclaw/`. Override with `--base-dir`.

Primitives are off by default. To enable for the harness only:

```bash
openclaw harness run my_scenario --enable-primitives
```

The MCP stdio server **never** enables primitives in v0.1.

## Next milestone

Live BrowserProvider (now safe to start, with the patch in place):

1. `BrowserProvider._ensure_context()`:
   - `launch_persistent_context` against `BrowserReadiness.profile_dir`
   - acquire profile lock file
   - headed first run, headless thereafter
   - never automate the user's normal Edge/Chrome profile
   - logs go to stderr only

2. First selector pack (Outlook Monarch only):
   - accessibility roles first
   - return `ui_variant_unsupported` on unknown variants

3. Flip `BrowserProvider.invoke()` for `outlook.mail.list`:
   - only in `SERVE_LOCAL` and `HARNESS_LIVE`
   - never reachable from `HARNESS_FAKE`

The `RuntimeMode` boundary is what makes step (3) safe: there is no chain in
the system that lets a fake call leak into production, no matter how the
BrowserProvider grows.
