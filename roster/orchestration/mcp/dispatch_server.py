#!/usr/bin/env python3
"""Stdio MCP server exposing `dispatch_secure_cloud_role` to a Codex CLI session.

Fixes the "Known upstream limitation" documented in
`.agents/skills/run-agent-orchestration/references/runner-adapters.md`:
Codex CLI's model-visible `spawn_agent` tool has no parameter to select a
named custom agent from `.codex/agents/`. This server gives a running Codex
session a real tool that does that resolution and dispatch itself, instead
of relying on the model to read the target `.toml` file and hand-inject its
`developer_instructions` into a generic `spawn_agent` call.

Transport: stdio only. Optional dependency: the official `mcp` Python SDK
(see `requirements-mcp.txt`). Mirrors `roster/shared/src/resolve.py`'s
`_require_yaml()` fail-closed pattern -- importing `dispatch_core` (the
actual safety-relevant logic) never requires `mcp`, so this optional
component being unavailable can never break the rest of the orchestration
tooling; only *running this server* requires `mcp` to be installed, and it
fails with a clear install pointer if it isn't.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

_MODULE_DIR = Path(__file__).resolve().parent
if str(_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_MODULE_DIR))

import dispatch_core as core  # noqa: E402  (sys.path set above)

MCP_INSTALL_MESSAGE = (
    "The 'mcp' package is required to run the agents MCP dispatch "
    "server; install it with `pip install -r "
    "roster/orchestration/mcp/requirements-mcp.txt` (stdio transport only -- "
    "do not install networked-transport extras)."
)


def _require_mcp():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as error:
        raise RuntimeError(MCP_INSTALL_MESSAGE) from error
    return FastMCP


def _parent_classification() -> str | None:
    return os.environ.get(core.PARENT_CLASSIFICATION_ENV_VAR)


def _task_id() -> str | None:
    return os.environ.get("SECURE_CLOUD_AGENTS_TASK_ID")


def _session_id() -> str | None:
    return os.environ.get("SECURE_CLOUD_AGENTS_SESSION_ID")


def build_server():
    """Construct the FastMCP server and register the single dispatch tool.

    Kept as a standalone function (rather than inline in main()) so tests can
    build the server against a stubbed `mcp` module and inspect the
    registered tool's signature without the real dependency installed.
    """
    fast_mcp_cls = _require_mcp()
    server = fast_mcp_cls("agents-dispatch")

    @server.tool()
    def dispatch_secure_cloud_role(
        role_id: str,
        brief: str,
        mode: str = "planning-review-only",
        classification: str = "internal",
        confirmation_token: str | None = None,
    ) -> dict[str, Any]:
        """Dispatch a named agents role as a Codex CLI child process.

        role_id: catalog role identifier, e.g. "application-engineer"; must
            match ^[a-z0-9-]+$ and exist in roster/catalog.yaml.
        brief: untrusted task data appended after the resolved role's own
            developer_instructions; never merged into or able to override them.
        mode: "planning-review-only" (default, read-only forced regardless of
            the resolved role file) or "scoped-repository-edit".
        classification: must not exceed this server's configured parent
            classification.
        confirmation_token: required on a second call to actually dispatch
            when the effective sandbox is write-capable; omit on the first
            call and the tool returns a confirmation_token to replay.
        """
        return core.dispatch_secure_cloud_role(
            role_id=role_id,
            brief=brief,
            mode=mode,
            classification=classification,
            confirmation_token=confirmation_token,
            task_id=_task_id(),
            session_id=_session_id(),
            parent_classification=_parent_classification(),
        )

    return server


def main() -> int:
    server = build_server()
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"agents-mcp-dispatch: {error}", file=sys.stderr)
        raise SystemExit(1) from error
