"""Verify MCP server stdout discipline.

The MCP stdio transport requires stdout to contain ONLY valid JSON-RPC
messages. Logging, diagnostics, and audit must go to stderr or files.

These tests pin three invariants:

  1. Importing openclaw.mcp_server.server writes nothing to stdout.
  2. After import, the root logger has at least one stderr StreamHandler
     and zero stdout StreamHandlers.
  3. _setup_stderr_logging actively REMOVES any pre-existing stdout
     StreamHandler — even one installed by a parent process, test
     environment, or earlier import.
"""

from __future__ import annotations

import io
import logging
import sys


def _reimport_server():
    if "openclaw.mcp_server.server" in sys.modules:
        del sys.modules["openclaw.mcp_server.server"]
    import openclaw.mcp_server.server  # noqa: F401
    return openclaw.mcp_server.server


def test_importing_mcp_server_does_not_write_to_stdout():
    captured = io.StringIO()
    real_stdout = sys.stdout
    sys.stdout = captured
    try:
        _reimport_server()
    finally:
        sys.stdout = real_stdout
    assert captured.getvalue() == "", (
        f"MCP server module wrote to stdout on import: {captured.getvalue()!r}"
    )


def test_logging_is_configured_to_stderr_not_stdout():
    _reimport_server()
    root = logging.getLogger()

    stream_handlers = [h for h in root.handlers if isinstance(h, logging.StreamHandler)]
    assert stream_handlers, "no StreamHandler configured"
    assert any(h.stream is sys.stderr for h in stream_handlers)
    assert not any(
        getattr(h, "stream", None) is sys.stdout for h in stream_handlers
    ), "a logging handler is writing to stdout — this breaks MCP stdio"


def test_setup_stderr_logging_strips_pre_existing_stdout_handler():
    """Reviewer's micro-patch: a parent process or test environment may have
    installed a stdout handler before openclaw is imported. _setup_stderr_logging
    must remove it.
    """
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    try:
        # Wipe and install a contaminating stdout handler.
        root.handlers = []
        bad = logging.StreamHandler(stream=sys.stdout)
        root.addHandler(bad)
        assert any(
            getattr(h, "stream", None) is sys.stdout for h in root.handlers
        )

        # Reimport — this calls _setup_stderr_logging which must strip the
        # stdout handler.
        _reimport_server()

        assert not any(
            getattr(h, "stream", None) is sys.stdout for h in root.handlers
        ), "stdout handler survived _setup_stderr_logging"
        assert any(
            isinstance(h, logging.StreamHandler) and h.stream is sys.stderr
            for h in root.handlers
        )
    finally:
        root.handlers = saved_handlers
