#!/usr/bin/env python3
"""Stdio MCP server exposing GitLab evidence/review operations to any agent
session (in this repo or a consuming project).

Transport: stdio only. Optional dependency: the official `mcp` Python SDK
(see `requirements-mcp.txt`), exactly like `dispatch_server.py`. Importing
`gitlab_core` (the actual safety-relevant logic: token/config resolution,
HTTP calls, retry, the confirmation gate) never requires `mcp` -- only
*running this server* does, and it fails with a clear install pointer if
`mcp` isn't installed, matching `dispatch_server.py`'s own fail-closed
pattern exactly.

Every tool registered here is create-only: `create_review_subtask`,
`write_wiki_page`, `write_evidence_comment`. None of them, nor anything they
call, can ever close, reopen, resolve, or relabel-away-from-open-review a
GitLab issue -- see `gitlab_core.py`'s module docstring and its "STATE
TRANSITION" comment.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_MODULE_DIR = Path(__file__).resolve().parent
if str(_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_MODULE_DIR))

import gitlab_core as core  # noqa: E402  (sys.path set above; also appends roster/shared/src)
import settings  # noqa: E402

# Unconditional, at import time: this is also a stdio-transport server (see
# module docstring), so gitlab_core.resolve_config()'s underlying
# roster/shared/src/settings.py resolver must never fall through to an
# interactive input() prompt here either.
settings.disable_interactive()
# Same reasoning for the project tier: this server is long-lived and
# project-agnostic, so its cwd is wherever the host CLI was launched and
# is not the project any given tool call is about. Callers that know the
# real project (e.g. dispatch_core's project_root) pass start= explicitly
# and are unaffected. See settings.disable_project_tier_cwd_fallback().
settings.disable_project_tier_cwd_fallback()

MCP_INSTALL_MESSAGE = (
    "The 'mcp' package is required to run the GitLab evidence MCP "
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


def build_server():
    """Construct the FastMCP server and register the three create-only
    GitLab tools. Kept as a standalone function (rather than inline in
    main()) so tests can build the server against a stubbed `mcp` module and
    inspect the registered tools' signatures without the real dependency
    installed -- mirrors `dispatch_server.py::build_server`."""
    fast_mcp_cls = _require_mcp()
    server = fast_mcp_cls("gitlab-evidence")

    @server.tool()
    def create_review_subtask(
        parent_issue_iid: int,
        title: str,
        description: str,
        gate_id: str,
        task_id: str,
    ) -> dict[str, Any]:
        """Create (or, if a matching one already exists, return) a GitLab
        issue linked to `parent_issue_iid` as a review subtask.

        parent_issue_iid: the iid of the existing parent GitLab issue in the
            configured project.
        title / description: the subtask issue's own title and body;
            description is untrusted task data the caller supplies, not an
            instruction to this tool.
        gate_id: identifies which lifecycle gate this subtask evidences,
            e.g. "G5"; used to build the `gate:<gate_id>` label and this
            call's idempotency key.
        task_id: the calling task's identifier; used, together with
            gate_id, as this call's idempotency key so repeated calls never
            create duplicate subtasks.

        Never closes, reopens, resolves, or relabels any issue -- create-only.
        """
        return core.create_review_subtask(
            parent_issue_iid=parent_issue_iid,
            title=title,
            description=description,
            gate_id=gate_id,
            task_id=task_id,
        )

    @server.tool()
    def write_wiki_page(
        slug: str,
        title: str,
        content: str,
        format: str = "markdown",
        confirmation_token: str | None = None,
    ) -> dict[str, Any]:
        """Create or update a versioned wiki page in the configured GitLab
        project. Requires human confirmation on every call, with no
        exception: the first call (omit confirmation_token) never writes
        anything and instead returns a confirmation_token to replay on a
        second, otherwise-identical call.

        slug: the wiki page's slug (path), e.g. "evidence/task-42".
        title / content: the page's title and body (untrusted task data).
        format: one of "markdown" (default), "rdoc", "asciidoc", "org".
        confirmation_token: omit on the first call; supply the token from
            that call's confirmation_required response on the second call.
        """
        return core.write_wiki_page(
            slug=slug,
            title=title,
            content=content,
            format=format,
            confirmation_token=confirmation_token,
        )

    @server.tool()
    def write_evidence_comment(issue_iid: int, content: str, task_id: str) -> dict[str, Any]:
        """Add a comment to an existing GitLab issue for small, structured
        per-task evidence.

        issue_iid: the iid of the existing GitLab issue to comment on.
        content: the comment body (untrusted task data); rejected outright
            (never truncated) if its UTF-8 encoding exceeds 1 MiB.
        task_id: the calling task's identifier, recorded for traceability.
        """
        return core.write_evidence_comment(issue_iid=issue_iid, content=content, task_id=task_id)

    return server


def main() -> int:
    server = build_server()
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"gitlab-mcp-server: {error}", file=sys.stderr)
        raise SystemExit(1) from error
