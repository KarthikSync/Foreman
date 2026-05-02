"""MCP stdio server.

Stdout discipline (per MCP transport spec):
  - stdout MUST contain only valid JSON-RPC messages.
  - All logging, diagnostics, and audit go to stderr or files.
  - At module load, _setup_stderr_logging() actively REMOVES any pre-existing
    StreamHandler pointing at sys.stdout, then installs a stderr handler.
    This protects against parent processes or test environments that may
    have configured stdout logging before openclaw was imported.

Session discipline:
  - One session_id per server process / MCP connection.
  - Threaded into every ToolCall so audit and harness traces correlate.

Lifetime:
  - engine.close() is called when the stdio loop exits, releasing the
    browser profile lock and tearing down Playwright cleanly.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from openclaw.runtime.bootstrap import build_engine
from openclaw.runtime.modes import RuntimeMode
from openclaw.types.core import ToolCall


def _setup_stderr_logging() -> None:
    """Configure root logger to write to stderr only.

    Removes any StreamHandler whose stream is sys.stdout so that earlier
    configurations (parent processes, test harnesses) cannot corrupt the
    MCP JSON-RPC channel.
    """
    root = logging.getLogger()

    # Strip stdout handlers — these would corrupt MCP stdout if any logging
    # ever fired.
    root.handlers = [
        h
        for h in root.handlers
        if not (
            isinstance(h, logging.StreamHandler)
            and getattr(h, "stream", None) is sys.stdout
        )
    ]

    # Add our stderr handler if not already present.
    if not any(
        isinstance(h, logging.StreamHandler) and h.stream is sys.stderr
        for h in root.handlers
    ):
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s :: %(message)s")
        )
        root.addHandler(handler)

    root.setLevel(logging.INFO)


_setup_stderr_logging()
_log = logging.getLogger("openclaw.mcp")


def _new_session_id() -> str:
    return f"sess_{uuid4().hex[:26].upper()}"


async def serve_stdio(base_dir: Path) -> None:
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        import mcp.types as mcp_types
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "The 'mcp' package is required for `openclaw serve --stdio`. "
            "Install with: pip install openclaw[mcp]"
        ) from exc

    # Production MCP serve uses SERVE_LOCAL — fake providers are NOT in chain.
    engine = build_engine(base_dir=base_dir, mode=RuntimeMode.SERVE_LOCAL)

    session_id = _new_session_id()
    _log.info("openclaw-core stdio server starting (session=%s)", session_id)

    server = Server("openclaw-core")

    @server.list_tools()
    async def list_tools() -> list[Any]:
        return [
            mcp_types.Tool(
                name=spec.name,
                description=spec.description,
                inputSchema=spec.input_schema,
            )
            for spec in engine.registry.list_visible(primitives_enabled=False)
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict | None) -> list[Any]:
        call = ToolCall(
            tool=name,
            inputs=arguments or {},
            session_id=session_id,
        )
        result = engine.execute(call)
        body = {
            "ok": result.ok,
            "data": result.data,
            "taint": [t.model_dump() for t in result.taint],
            "error_code": result.error_code,
            "error_message": result.error_message,
        }
        return [
            mcp_types.TextContent(
                type="text",
                text=json.dumps(body, default=str),
            )
        ]

    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    finally:
        _log.info("openclaw-core stdio server shutting down")
        engine.close()
