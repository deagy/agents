"""Unit coverage for roster/orchestration/mcp/gitlab_cli.py -- the non-MCP
CLI adapter over gitlab_core.py's three GitLab evidence functions.

Two layers, matching test_gitlab_integration.py's GitlabServerSchemaTests
style for gitlab_server.py's MCP adapter:

- In-process dispatch() tests mock gitlab_core's functions directly and
  assert argv is parsed and forwarded unmutated -- no subprocess, no real
  GitLab call.
- A handful of real subprocess invocations (python3 gitlab_cli.py ...)
  exercise the actual CLI entrypoint end-to-end against an unset
  GITLAB_SVC_TOKEN, catching argv-encoding/JSON-output regressions the
  in-process tests can't see.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ORCHESTRATION_ROOT = Path(__file__).resolve().parent.parent
MCP_DIR = ORCHESTRATION_ROOT / "mcp"
CLI_PATH = MCP_DIR / "gitlab_cli.py"
sys.path.insert(0, str(MCP_DIR))

import gitlab_cli  # noqa: E402  (sys.path set above)


class DispatchDelegatesToGitlabCoreUnmutatedTests(unittest.TestCase):
    def test_create_review_subtask_forwards_all_five_positional_args(self) -> None:
        captured = {}

        def fake(parent_issue_iid, title, description, gate_id, task_id):
            captured.update(
                parent_issue_iid=parent_issue_iid,
                title=title,
                description=description,
                gate_id=gate_id,
                task_id=task_id,
            )
            return {"status": "ok", "created": True}

        parser = gitlab_cli.build_parser()
        args = parser.parse_args(
            [
                "create-review-subtask",
                "--parent-issue-iid",
                "5",
                "--title",
                "Review needed",
                "--description",
                "Some body",
                "--gate-id",
                "G5",
                "--task-id",
                "TASK-1",
            ]
        )
        with mock.patch.object(gitlab_cli.core, "create_review_subtask", side_effect=fake):
            result = gitlab_cli.dispatch(args)

        self.assertEqual(result, {"status": "ok", "created": True})
        self.assertEqual(captured["parent_issue_iid"], 5)
        self.assertIsInstance(captured["parent_issue_iid"], int)
        self.assertEqual(captured["title"], "Review needed")
        self.assertEqual(captured["description"], "Some body")
        self.assertEqual(captured["gate_id"], "G5")
        self.assertEqual(captured["task_id"], "TASK-1")

    def test_write_wiki_page_forwards_format_and_confirmation_token_unmutated(self) -> None:
        captured = {}

        def fake(slug, title, content, format, confirmation_token):  # noqa: A002
            captured.update(
                slug=slug, title=title, content=content, format=format, confirmation_token=confirmation_token
            )
            return {"status": "confirmation_required", "confirmation_token": "stub"}

        parser = gitlab_cli.build_parser()
        args = parser.parse_args(
            [
                "write-wiki-page",
                "--slug",
                "evidence/task-1",
                "--title",
                "Evidence",
                "--content",
                "body",
                "--format",
                "rdoc",
                "--confirmation-token",
                "a-real-token",
            ]
        )
        with mock.patch.object(gitlab_cli.core, "write_wiki_page", side_effect=fake):
            result = gitlab_cli.dispatch(args)

        self.assertEqual(result["status"], "confirmation_required")
        self.assertEqual(captured["slug"], "evidence/task-1")
        self.assertEqual(captured["content"], "body")
        self.assertEqual(captured["format"], "rdoc")
        self.assertEqual(captured["confirmation_token"], "a-real-token")

    def test_write_wiki_page_defaults_format_to_markdown_and_token_to_none(self) -> None:
        captured = {}

        def fake(slug, title, content, format, confirmation_token):  # noqa: A002
            captured.update(format=format, confirmation_token=confirmation_token)
            return {"status": "confirmation_required"}

        parser = gitlab_cli.build_parser()
        args = parser.parse_args(
            ["write-wiki-page", "--slug", "s", "--title", "t", "--content", "c"]
        )
        with mock.patch.object(gitlab_cli.core, "write_wiki_page", side_effect=fake):
            gitlab_cli.dispatch(args)

        self.assertEqual(captured["format"], "markdown")
        self.assertIsNone(captured["confirmation_token"])

    def test_write_evidence_comment_forwards_all_three_args(self) -> None:
        captured = {}

        def fake(issue_iid, content, task_id):
            captured.update(issue_iid=issue_iid, content=content, task_id=task_id)
            return {"status": "ok", "comment": "stub"}

        parser = gitlab_cli.build_parser()
        args = parser.parse_args(
            ["write-evidence-comment", "--issue-iid", "7", "--content", "evidence text", "--task-id", "TASK-1"]
        )
        with mock.patch.object(gitlab_cli.core, "write_evidence_comment", side_effect=fake):
            result = gitlab_cli.dispatch(args)

        self.assertEqual(result, {"status": "ok", "comment": "stub"})
        self.assertEqual(captured["issue_iid"], 7)
        self.assertIsInstance(captured["issue_iid"], int)
        self.assertEqual(captured["content"], "evidence text")
        self.assertEqual(captured["task_id"], "TASK-1")


class ArgumentValidationTests(unittest.TestCase):
    def test_missing_required_argument_exits_nonzero_without_calling_gitlab_core(self) -> None:
        parser = gitlab_cli.build_parser()
        with mock.patch.object(gitlab_cli.core, "create_review_subtask") as fake:
            with self.assertRaises(SystemExit) as raised:
                parser.parse_args(["create-review-subtask", "--title", "t"])
            self.assertNotEqual(raised.exception.code, 0)
            fake.assert_not_called()

    def test_unknown_subcommand_exits_nonzero(self) -> None:
        parser = gitlab_cli.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["not-a-real-subcommand"])

    def test_write_wiki_page_rejects_a_format_outside_the_fixed_choice_set(self) -> None:
        parser = gitlab_cli.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(
                ["write-wiki-page", "--slug", "s", "--title", "t", "--content", "c", "--format", "html"]
            )


class MainPrintsExactlyOneJsonLineAndExitsZeroTests(unittest.TestCase):
    def test_main_prints_the_dispatch_result_as_a_single_json_line_and_returns_zero(self) -> None:
        buffer_calls: list[str] = []

        def fake(parent_issue_iid, title, description, gate_id, task_id):
            return {"status": "denied", "reason": "stub"}

        with mock.patch.object(gitlab_cli.core, "create_review_subtask", side_effect=fake):
            with mock.patch("builtins.print", side_effect=lambda s: buffer_calls.append(s)):
                exit_code = gitlab_cli.main(
                    [
                        "create-review-subtask",
                        "--parent-issue-iid",
                        "1",
                        "--title",
                        "t",
                        "--description",
                        "d",
                        "--gate-id",
                        "G5",
                        "--task-id",
                        "TASK-1",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(buffer_calls), 1)
        self.assertEqual(json.loads(buffer_calls[0]), {"status": "denied", "reason": "stub"})


class SubprocessEndToEndTests(unittest.TestCase):
    """Real `python3 gitlab_cli.py ...` invocations -- no mocking -- against
    an environment with no GITLAB_SVC_TOKEN set, so every call fails closed
    with status="unavailable" before any network I/O. Confirms the actual
    entrypoint (argv parsing, stdout framing, exit code) works end-to-end,
    which the in-process tests above can't see since they call
    build_parser()/dispatch()/main() directly in the test process."""

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI_PATH), *args],
            capture_output=True,
            text=True,
            env={},
            timeout=30,
        )

    def test_create_review_subtask_without_a_token_exits_zero_with_unavailable_json(self) -> None:
        result = self._run(
            "create-review-subtask",
            "--parent-issue-iid",
            "5",
            "--title",
            "t",
            "--description",
            "d",
            "--gate-id",
            "G5",
            "--task-id",
            "TASK-1",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "unavailable")
        self.assertIn("GITLAB_SVC_TOKEN", payload["reason"])

    def test_missing_required_flag_exits_nonzero_with_no_stdout(self) -> None:
        result = self._run("write-evidence-comment", "--issue-iid", "1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_multiline_content_argument_survives_argv_unmutated(self) -> None:
        # execFile-style invocation (argv array, no shell) is exactly what
        # cline-agents' native tool contributions use -- confirms a
        # multi-line, quote-containing description round-trips through
        # argv without any shell-quoting involvement.
        multiline = 'line one\nline two with a "quote" and a \'quote\''
        result = self._run(
            "write-evidence-comment",
            "--issue-iid",
            "1",
            "--content",
            multiline,
            "--task-id",
            "TASK-1",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
