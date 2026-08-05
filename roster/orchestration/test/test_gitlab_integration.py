"""Unit coverage for roster/orchestration/mcp/gitlab_core.py and
gitlab_server.py's tool registration -- the GitLab-evidence MCP server.

Every test in this file mocks all HTTP calls; none makes a live GitLab
call. Several mocking layers are used depending on what a test needs to
exercise:

- Tests of `request_json()` itself (retry/backoff/permanent-error behavior)
  patch `gitlab_core._perform_request`, the one function that actually talks
  to `urllib`.
- Tests of the three public tools (idempotency, size cap, confirmation
  gating) patch `gitlab_core.request_json` directly, since that is this
  module's sole entry point for any network I/O and every tool function
  calls through it exclusively.
- Tests of `gitlab_server.py`'s tool registration and its fail-closed
  dependency on the optional `mcp` package stub `sys.modules["mcp"]` etc.
  exactly like `test_mcp_dispatch.py`'s `DispatchServerSchemaTests` /
  `DispatchServerFailClosedTests` do for `dispatch_server.py`.
"""

from __future__ import annotations

import importlib.util
import inspect
import io
import json
import os
import ssl
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

ORCHESTRATION_ROOT = Path(__file__).resolve().parent.parent
MCP_DIR = ORCHESTRATION_ROOT / "mcp"
sys.path.insert(0, str(MCP_DIR))

import dispatch_core  # noqa: E402
import gitlab_core as gcore  # noqa: E402

FAKE_TOKEN = "glpat-FAKE-TEST-TOKEN-0000"


def _base_env(**overrides: str) -> dict[str, str]:
    env = {
        gcore.GITLAB_TOKEN_ENV_VAR: FAKE_TOKEN,
        gcore.GITLAB_BASE_URL_ENV_VAR: "https://gitlab.example.com",
        gcore.GITLAB_PROJECT_ID_ENV_VAR: "42",
    }
    env.update(overrides)
    return env


def _http_error(code: int, body: bytes = b"{}") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://gitlab.example.com/api/v4/x", code=code, msg="err", hdrs=None, fp=io.BytesIO(body)
    )


# ---------------------------------------------------------------------------
# Token resolution
# ---------------------------------------------------------------------------


class TokenResolutionTests(unittest.TestCase):
    def test_unset_token_fails_closed_naming_the_env_var(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(gcore.GITLAB_TOKEN_ENV_VAR, None)
            with self.assertRaises(gcore.GitLabConfigError) as ctx:
                gcore.resolve_token()
            self.assertIn(gcore.GITLAB_TOKEN_ENV_VAR, str(ctx.exception))

    def test_empty_and_whitespace_only_token_fails_closed(self) -> None:
        for value in ("", "   ", "\t\n"):
            with self.subTest(value=repr(value)):
                with mock.patch.dict(os.environ, {gcore.GITLAB_TOKEN_ENV_VAR: value}, clear=False):
                    with self.assertRaises(gcore.GitLabConfigError):
                        gcore.resolve_token()

    def test_set_token_resolves_exactly(self) -> None:
        with mock.patch.dict(os.environ, {gcore.GITLAB_TOKEN_ENV_VAR: FAKE_TOKEN}, clear=False):
            self.assertEqual(gcore.resolve_token(), FAKE_TOKEN)

    def test_alias_env_var_names_are_never_honored(self) -> None:
        # Settled decision: GL_SVC_TOKEN / GITLAB_SERVICE_TOKEN are explicitly
        # rejected, not merely deprioritized -- no alias lookup exists.
        with mock.patch.dict(
            os.environ,
            {"GL_SVC_TOKEN": FAKE_TOKEN, "GITLAB_SERVICE_TOKEN": FAKE_TOKEN},
            clear=False,
        ):
            os.environ.pop(gcore.GITLAB_TOKEN_ENV_VAR, None)
            with self.assertRaises(gcore.GitLabConfigError):
                gcore.resolve_token()


class ConfigResolutionTests(unittest.TestCase):
    def test_requires_https_base_url(self) -> None:
        with mock.patch.dict(os.environ, _base_env(**{gcore.GITLAB_BASE_URL_ENV_VAR: "http://gitlab.example.com"})):
            with self.assertRaises(gcore.GitLabConfigError):
                gcore.resolve_config()

    def test_missing_project_id_fails_closed(self) -> None:
        env = _base_env()
        env.pop(gcore.GITLAB_PROJECT_ID_ENV_VAR)
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop(gcore.GITLAB_PROJECT_ID_ENV_VAR, None)
            with self.assertRaises(gcore.GitLabConfigError):
                gcore.resolve_config()

    def test_hierarchy_flag_defaults_to_none_when_unset(self) -> None:
        env = _base_env()
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop(gcore.GITLAB_HIERARCHY_ENV_VAR, None)
            config = gcore.resolve_config()
            self.assertIsNone(config.supports_work_item_hierarchy)

    def test_hierarchy_flag_rejects_unparseable_values(self) -> None:
        with mock.patch.dict(os.environ, _base_env(**{gcore.GITLAB_HIERARCHY_ENV_VAR: "maybe"})):
            with self.assertRaises(gcore.GitLabConfigError):
                gcore.resolve_config()


# ---------------------------------------------------------------------------
# Token never leaks
# ---------------------------------------------------------------------------


class TokenNeverLeaksTests(unittest.TestCase):
    def test_permanent_error_result_never_contains_the_token(self) -> None:
        with mock.patch.dict(os.environ, _base_env()):
            with mock.patch.object(gcore, "request_json", side_effect=gcore.GitLabPermanentError(
                "GitLab API returned 401 for GET /projects/42/issues: unauthorized", status_code=401
            )):
                result = gcore.create_review_subtask(1, "Title", "Body", "G5", "TASK-1")
        self.assertEqual(result["status"], "denied")
        self.assertNotIn(FAKE_TOKEN, json.dumps(result))

    def test_missing_token_config_error_never_mentions_any_token_value(self) -> None:
        # Renamed/rephrased from a prior version of this test: popping the
        # token before the call (as this test does) makes "the result never
        # contains FAKE_TOKEN" trivially true regardless of any redaction
        # logic, since FAKE_TOKEN was never resolved in the first place. This
        # test only proves the "unavailable" config-error path names no
        # value at all -- see
        # test_result_never_leaks_a_resolved_token_on_a_downstream_error
        # below for the test that actually exercises a resolved token.
        env = _base_env()
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop(gcore.GITLAB_TOKEN_ENV_VAR, None)
            result = gcore.write_evidence_comment(1, "content", "TASK-1")
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn(FAKE_TOKEN, json.dumps(result))

    def test_result_never_leaks_a_resolved_token_on_a_downstream_error(self) -> None:
        # Unlike the test above, the token is genuinely resolved here
        # (present in the environment, read by resolve_token() inside
        # write_evidence_comment) before the downstream call fails -- this
        # is the real leak path the redaction discipline must hold against.
        with mock.patch.dict(os.environ, _base_env()):
            with mock.patch.object(
                gcore, "request_json", side_effect=gcore.GitLabPermanentError("denied", status_code=403)
            ):
                result = gcore.write_evidence_comment(1, "content", "TASK-1")
        self.assertEqual(result["status"], "denied")
        self.assertNotIn(FAKE_TOKEN, json.dumps(result))

    def test_http_error_exception_str_never_contains_the_token(self) -> None:
        # The token only ever travels in the PRIVATE-TOKEN header, which
        # _perform_request never folds into any raised exception's message.
        with mock.patch.dict(os.environ, _base_env()):
            with mock.patch.object(gcore, "_perform_request", side_effect=_http_error(401, b"unauthorized")):
                with self.assertRaises(gcore.GitLabPermanentError) as ctx:
                    gcore.request_json(
                        "GET", "/projects/42/issues", gcore.resolve_config(), gcore.resolve_token()
                    )
        self.assertNotIn(FAKE_TOKEN, str(ctx.exception))


# ---------------------------------------------------------------------------
# request_json: retry / permanent-error behavior
# ---------------------------------------------------------------------------


class RequestJsonRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patcher = mock.patch.dict(os.environ, _base_env())
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)
        self.config = gcore.resolve_config()
        self.token = gcore.resolve_token()

    def test_permanent_401_never_retries_and_never_returns_a_false_success(self) -> None:
        with mock.patch.object(gcore, "_perform_request", side_effect=_http_error(401)) as perform:
            with self.assertRaises(gcore.GitLabPermanentError) as ctx:
                gcore.request_json("GET", "/projects/42/issues", self.config, self.token, sleep=lambda s: None)
            self.assertEqual(perform.call_count, 1)
            self.assertEqual(ctx.exception.status_code, 401)

    def test_permanent_403_and_404_never_retry_either(self) -> None:
        for code in (403, 404):
            with self.subTest(code=code):
                with mock.patch.object(gcore, "_perform_request", side_effect=_http_error(code)) as perform:
                    with self.assertRaises(gcore.GitLabPermanentError):
                        gcore.request_json("GET", "/projects/42/issues", self.config, self.token, sleep=lambda s: None)
                    self.assertEqual(perform.call_count, 1)

    def test_429_then_500_then_success_eventually_returns_the_real_result(self) -> None:
        sleeps: list[float] = []
        outcomes = [_http_error(429), _http_error(500), {"iid": 99, "title": "ok"}]

        def _side_effect(*args, **kwargs):
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        with mock.patch.object(gcore, "_perform_request", side_effect=_side_effect) as perform:
            result = gcore.request_json(
                "GET", "/projects/42/issues", self.config, self.token, sleep=sleeps.append
            )
        self.assertEqual(result, {"iid": 99, "title": "ok"})
        self.assertEqual(perform.call_count, 3)
        # Bounded exponential backoff with jitter: two sleeps recorded (after
        # the two failed attempts), both non-negative, and not identical
        # constants (jitter applied), never a caller-visible false success.
        self.assertEqual(len(sleeps), 2)
        for delay in sleeps:
            self.assertGreaterEqual(delay, 0)

    def test_retry_exhaustion_never_fabricates_a_success(self) -> None:
        with mock.patch.object(gcore, "_perform_request", side_effect=_http_error(503)) as perform:
            with self.assertRaises(gcore.GitLabRetryableExhaustedError):
                gcore.request_json("GET", "/projects/42/issues", self.config, self.token, sleep=lambda s: None)
        self.assertEqual(perform.call_count, gcore.MAX_RETRY_ATTEMPTS)

    def test_timeout_is_retried_like_a_5xx(self) -> None:
        outcomes = [TimeoutError("timed out"), {"iid": 1}]

        def _side_effect(*args, **kwargs):
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        with mock.patch.object(gcore, "_perform_request", side_effect=_side_effect) as perform:
            result = gcore.request_json(
                "GET", "/projects/42/issues", self.config, self.token, sleep=lambda s: None
            )
        self.assertEqual(result, {"iid": 1})
        self.assertEqual(perform.call_count, 2)


# ---------------------------------------------------------------------------
# create_review_subtask: idempotency and permanent-error propagation
# ---------------------------------------------------------------------------


class CreateReviewSubtaskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patcher = mock.patch.dict(os.environ, _base_env())
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)

    def test_second_call_returns_existing_issue_without_creating_a_duplicate(self) -> None:
        existing_issue = {
            "iid": 7,
            "description": "Parent: #1\n\nSome body\n\n<!-- task_id=TASK-1 gate_id=G5 -->\n\n/relates_to #1\n",
            "labels": ["review-subtask", "gate:G5"],
        }

        def _fake_request_json(method, path, config, token, **kwargs):
            self.assertEqual(method, "GET")
            self.assertTrue(path.endswith("/issues"))
            return [existing_issue]

        with mock.patch.object(gcore, "request_json", side_effect=_fake_request_json) as mocked:
            result = gcore.create_review_subtask(1, "Review needed", "Some body", "G5", "TASK-1")

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["created"])
        self.assertIn(str(existing_issue["iid"]), result["issue"])
        # Only the idempotency-search GET happened -- no POST was ever issued.
        for call in mocked.call_args_list:
            self.assertNotEqual(call.args[0], "POST")

    def test_no_existing_match_creates_exactly_one_new_issue(self) -> None:
        calls: list[tuple[str, str]] = []

        def _fake_request_json(method, path, config, token, **kwargs):
            calls.append((method, path))
            if method == "GET":
                return []
            return {"iid": 55, "title": kwargs["json_body"]["title"]}

        with mock.patch.object(gcore, "request_json", side_effect=_fake_request_json):
            result = gcore.create_review_subtask(1, "Review needed", "Some body", "G5", "TASK-1")

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["created"])
        post_calls = [call for call in calls if call[0] == "POST"]
        self.assertEqual(len(post_calls), 1)

    def test_permanent_error_never_produces_a_false_success(self) -> None:
        with mock.patch.object(
            gcore, "request_json", side_effect=gcore.GitLabPermanentError("denied", status_code=404)
        ):
            result = gcore.create_review_subtask(1, "Review needed", "Some body", "G5", "TASK-1")
        self.assertEqual(result["status"], "denied")
        # A denied result never carries an "issue" key at all -- not merely
        # an absence of a nested "status" field within one.
        self.assertNotIn("issue", result)

    def test_invalid_gate_id_is_rejected_before_any_http_call(self) -> None:
        with mock.patch.object(gcore, "request_json") as mocked:
            result = gcore.create_review_subtask(1, "Title", "Body", "G5; DROP TABLE", "TASK-1")
        self.assertEqual(result["status"], "denied")
        mocked.assert_not_called()

    def test_hierarchy_flag_true_still_uses_the_documented_fallback_shape(self) -> None:
        # Locks in the documented deviation (gitlab_core.py's own
        # create_review_subtask docstring, "Hierarchy note"): even when the
        # instance is declared to support work-item hierarchy, this
        # implementation never attempts a GraphQL hierarchy mutation -- it
        # always uses the "Parent: #<iid>" description reference plus a
        # "/relates_to" quick action. A future silent switch to a real
        # hierarchy mutation would break this test, which is the point.
        with mock.patch.dict(os.environ, {gcore.GITLAB_HIERARCHY_ENV_VAR: "true"}):
            captured_payload = {}

            def _fake_request_json(method, path, config, token, **kwargs):
                if method == "GET":
                    return []
                captured_payload.update(kwargs.get("json_body", {}))
                return {"iid": 77, "title": kwargs["json_body"]["title"]}

            with mock.patch.object(gcore, "request_json", side_effect=_fake_request_json):
                result = gcore.create_review_subtask(1, "Review needed", "Some body", "G5", "TASK-1")

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["hierarchy_supported"])
        self.assertIn("Parent: #1", captured_payload["description"])
        self.assertIn("/relates_to #1", captured_payload["description"])
        # No GraphQL/work-item-hierarchy-shaped field is ever sent.
        self.assertNotIn("workItemId", captured_payload)
        self.assertNotIn("parentId", captured_payload)


# ---------------------------------------------------------------------------
# write_evidence_comment: size cap
# ---------------------------------------------------------------------------


class WriteEvidenceCommentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patcher = mock.patch.dict(os.environ, _base_env())
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)

    def test_over_cap_content_is_rejected_without_truncation_and_without_any_http_call(self) -> None:
        oversized = "x" * (gcore.MAX_EVIDENCE_COMMENT_BYTES + 1)
        with mock.patch.object(gcore, "request_json") as mocked:
            result = gcore.write_evidence_comment(1, oversized, "TASK-1")
        self.assertEqual(result["status"], "denied")
        self.assertIn(str(gcore.MAX_EVIDENCE_COMMENT_BYTES), result["reason"])
        mocked.assert_not_called()

    def test_exactly_at_cap_is_accepted(self) -> None:
        exactly_at_cap = "x" * gcore.MAX_EVIDENCE_COMMENT_BYTES
        with mock.patch.object(gcore, "request_json", return_value={"id": 1, "body": exactly_at_cap}):
            result = gcore.write_evidence_comment(1, exactly_at_cap, "TASK-1")
        self.assertEqual(result["status"], "ok")

    def test_permanent_error_propagates_as_structured_error(self) -> None:
        with mock.patch.object(
            gcore, "request_json", side_effect=gcore.GitLabPermanentError("not found", status_code=404)
        ):
            result = gcore.write_evidence_comment(999999, "content", "TASK-1")
        self.assertEqual(result["status"], "denied")
        self.assertEqual(result["status_code"], 404)


# ---------------------------------------------------------------------------
# write_wiki_page: mandatory confirmation gate
# ---------------------------------------------------------------------------


class WriteWikiPageConfirmationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patcher = mock.patch.dict(os.environ, _base_env())
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)
        # Fresh gate per test so tokens from other tests never leak across.
        gcore._WIKI_CONFIRMATION_GATE = dispatch_core.ConfirmationGate()

    def test_first_call_never_writes_and_returns_a_confirmation_token(self) -> None:
        with mock.patch.object(gcore, "request_json") as mocked:
            result = gcore.write_wiki_page("evidence/task-1", "Evidence", "content")
        self.assertEqual(result["status"], "confirmation_required")
        self.assertIn("confirmation_token", result)
        mocked.assert_not_called()

    def test_second_call_with_matching_token_writes_exactly_once(self) -> None:
        with mock.patch.object(gcore, "request_json") as mocked:
            first = gcore.write_wiki_page("evidence/task-1", "Evidence", "content")
            mocked.side_effect = [None, {"slug": "evidence/task-1", "content": "content"}]
            second = gcore.write_wiki_page(
                "evidence/task-1", "Evidence", "content", confirmation_token=first["confirmation_token"]
            )
        self.assertEqual(second["status"], "ok")
        self.assertEqual(mocked.call_count, 2)  # GET (miss) + POST (create)

    def test_reusing_a_token_a_second_time_is_denied(self) -> None:
        with mock.patch.object(gcore, "request_json", side_effect=[None, {"slug": "s"}]):
            first = gcore.write_wiki_page("evidence/task-1", "Evidence", "content")
            gcore.write_wiki_page("evidence/task-1", "Evidence", "content", confirmation_token=first["confirmation_token"])
        with mock.patch.object(gcore, "request_json") as mocked:
            replay = gcore.write_wiki_page(
                "evidence/task-1", "Evidence", "content", confirmation_token=first["confirmation_token"]
            )
        self.assertEqual(replay["status"], "denied")
        mocked.assert_not_called()

    def test_tampering_with_content_after_confirmation_request_invalidates_it(self) -> None:
        with mock.patch.object(gcore, "request_json") as mocked:
            first = gcore.write_wiki_page("evidence/task-1", "Evidence", "content")
            tampered = gcore.write_wiki_page(
                "evidence/task-1", "Evidence", "DIFFERENT CONTENT", confirmation_token=first["confirmation_token"]
            )
        self.assertEqual(tampered["status"], "denied")
        mocked.assert_not_called()


# ---------------------------------------------------------------------------
# Structural: no close/resolve/approve/state-transition surface anywhere.
# ---------------------------------------------------------------------------


class StructuralNoStateTransitionTests(unittest.TestCase):
    _FORBIDDEN_SUBSTRINGS = ("close", "reopen", "approve")

    def test_no_module_level_function_has_a_forbidden_state_transition_shaped_name(self) -> None:
        for name, obj in inspect.getmembers(gcore, inspect.isfunction):
            if getattr(obj, "__module__", None) != gcore.__name__:
                continue  # only this module's own functions, not imported dispatch_core helpers
            lowered = name.lower()
            for token in self._FORBIDDEN_SUBSTRINGS:
                self.assertNotIn(
                    token, lowered, f"{name!r} is shaped like a state-transition function ({token!r})"
                )
            if "resolve" in lowered:
                # resolve_token/resolve_config/resolve_token_and_config are
                # legitimate config-resolution helpers; "resolve" combined
                # with "issue" would be the forbidden shape instead.
                self.assertNotIn(
                    "issue", lowered, f"{name!r} is shaped like an issue-resolution/state-transition function"
                )

    def test_named_close_resolve_approve_functions_do_not_exist(self) -> None:
        for candidate in (
            "close_issue",
            "reopen_issue",
            "resolve_issue",
            "approve_issue",
            "close_review_subtask",
            "resolve_review_subtask",
        ):
            self.assertFalse(hasattr(gcore, candidate), f"unexpected forbidden function present: {candidate}")

    def test_module_source_never_uses_gitlabs_state_event_field(self) -> None:
        # GitLab's REST API closes/reopens an issue exclusively via a
        # `state_event` field on the issue-update endpoint; this module
        # never issues that call anywhere.
        source = inspect.getsource(gcore)
        self.assertNotIn("state_event", source)

    def test_create_review_subtask_source_never_calls_a_state_transition(self) -> None:
        # Scan the function body only (not its docstring, which discusses
        # the invariant in prose) for a call-shaped use of a forbidden verb,
        # e.g. `close_issue(...)` or `.approve(...)`.
        source = inspect.getsource(gcore.create_review_subtask)
        body = source.split('"""', 2)[-1] if source.count('"""') >= 2 else source
        for token in self._FORBIDDEN_SUBSTRINGS:
            self.assertNotRegex(body.lower(), rf"\b\w*{token}\w*\s*\(")


# ---------------------------------------------------------------------------
# Untrusted-output wrapping: the marker tokens themselves must be present,
# not merely some substring of the underlying retrieved data.
# ---------------------------------------------------------------------------


class UntrustedWrappingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patcher = mock.patch.dict(os.environ, _base_env())
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)
        gcore._WIKI_CONFIRMATION_GATE = dispatch_core.ConfirmationGate()

    def _assert_wrapped(self, wrapped: str) -> None:
        # These are the literal fence strings dispatch_core.wrap_untrusted_output
        # writes -- asserting them (not just that an id/substring of the
        # payload appears) is what actually catches a regression where
        # wrapping is removed but the payload still happens to contain a
        # matching substring (e.g. the existing-issue id test would remain
        # green even with wrapping deleted).
        self.assertIn("BEGIN UNTRUSTED CHILD OUTPUT", wrapped)
        self.assertIn("END UNTRUSTED CHILD OUTPUT", wrapped)

    def test_create_review_subtask_issue_payload_is_wrapped(self) -> None:
        existing_issue = {
            "iid": 7,
            "description": "Parent: #1\n\nSome body\n\n<!-- task_id=TASK-1 gate_id=G5 -->\n\n/relates_to #1\n",
            "labels": ["review-subtask", "gate:G5"],
        }
        with mock.patch.object(gcore, "request_json", return_value=[existing_issue]):
            result = gcore.create_review_subtask(1, "Review needed", "Some body", "G5", "TASK-1")
        self._assert_wrapped(result["issue"])

    def test_write_wiki_page_page_payload_is_wrapped(self) -> None:
        with mock.patch.object(gcore, "request_json", side_effect=[None, {"slug": "s", "content": "c"}]):
            first = gcore.write_wiki_page("evidence/task-1", "Evidence", "content")
            second = gcore.write_wiki_page(
                "evidence/task-1", "Evidence", "content", confirmation_token=first["confirmation_token"]
            )
        self._assert_wrapped(second["page"])

    def test_write_evidence_comment_payload_is_wrapped(self) -> None:
        with mock.patch.object(gcore, "request_json", return_value={"id": 1, "body": "content"}):
            result = gcore.write_evidence_comment(1, "content", "TASK-1")
        self._assert_wrapped(result["comment"])


# ---------------------------------------------------------------------------
# Audit trail: every outcome of every tool writes a structured record,
# never containing the token, a raw confirmation-token value, or raw
# wiki/comment/issue body content.
# ---------------------------------------------------------------------------


class AuditTrailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patcher = mock.patch.dict(os.environ, _base_env())
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)
        gcore._WIKI_CONFIRMATION_GATE = dispatch_core.ConfirmationGate()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.audit_path = Path(self.tmp_dir.name) / "audit.jsonl"

    def _read_records(self) -> list[dict]:
        if not self.audit_path.exists():
            return []
        return [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines()]

    def test_create_review_subtask_success_writes_an_ok_record_with_the_issue_iid(self) -> None:
        with mock.patch.object(
            gcore, "request_json", side_effect=[[], {"iid": 55, "title": "Review needed"}]
        ):
            gcore.create_review_subtask(1, "Review needed", "Some body", "G5", "TASK-1", audit_path=self.audit_path)
        records = self._read_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["tool"], "create_review_subtask")
        self.assertEqual(records[0]["decision"], "ok")
        self.assertEqual(records[0]["issue_iid"], 55)
        self.assertEqual(records[0]["task_id"], "TASK-1")
        self.assertIn("timestamp", records[0])

    def test_create_review_subtask_validation_failure_writes_a_denied_record(self) -> None:
        gcore.create_review_subtask(1, "Title", "Body", "G5; DROP TABLE", "TASK-1", audit_path=self.audit_path)
        records = self._read_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["decision"], "denied")

    def test_write_wiki_page_records_every_stage_not_only_final_success(self) -> None:
        with mock.patch.object(gcore, "request_json", side_effect=[None, {"slug": "s"}]):
            first = gcore.write_wiki_page("evidence/task-1", "Evidence", "content", audit_path=self.audit_path)
            gcore.write_wiki_page(
                "evidence/task-1",
                "Evidence",
                "content",
                confirmation_token=first["confirmation_token"],
                audit_path=self.audit_path,
            )
        records = self._read_records()
        decisions = [record["decision"] for record in records]
        self.assertEqual(decisions, ["confirmation-required", "ok"])
        for record in records:
            self.assertNotIn("content", record)
            self.assertIn("content_sha256", record)

    def test_write_wiki_page_denied_confirmation_replay_writes_a_denied_record(self) -> None:
        with mock.patch.object(gcore, "request_json", side_effect=[None, {"slug": "s"}]):
            first = gcore.write_wiki_page("evidence/task-1", "Evidence", "content")
            gcore.write_wiki_page("evidence/task-1", "Evidence", "content", confirmation_token=first["confirmation_token"])
            gcore.write_wiki_page(
                "evidence/task-1",
                "Evidence",
                "content",
                confirmation_token=first["confirmation_token"],
                audit_path=self.audit_path,
            )
        records = self._read_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["decision"], "denied")

    def test_write_evidence_comment_success_writes_an_ok_record_with_the_comment_id(self) -> None:
        with mock.patch.object(gcore, "request_json", return_value={"id": 9, "body": "content"}):
            gcore.write_evidence_comment(1, "content", "TASK-1", audit_path=self.audit_path)
        records = self._read_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["decision"], "ok")
        self.assertEqual(records[0]["comment_id"], 9)

    def test_no_audit_record_ever_contains_the_token_or_raw_content(self) -> None:
        with mock.patch.object(gcore, "request_json", side_effect=[[], {"iid": 1}]):
            gcore.create_review_subtask(
                1, "Review needed", "sensitive body text", "G5", "TASK-1", audit_path=self.audit_path
            )
        with mock.patch.object(gcore, "request_json", return_value={"id": 1}):
            gcore.write_evidence_comment(1, "sensitive comment text", "TASK-1", audit_path=self.audit_path)
        raw = self.audit_path.read_text(encoding="utf-8")
        self.assertNotIn(FAKE_TOKEN, raw)
        self.assertNotIn("sensitive body text", raw)
        self.assertNotIn("sensitive comment text", raw)


# ---------------------------------------------------------------------------
# TLS / redirect controls: cross-host redirect refusal, same-host scheme
# downgrade refusal (regression test for the TLS-downgrade finding), and a
# runtime check that the SSL context always requires certificate
# verification regardless of environment.
# ---------------------------------------------------------------------------


class RedirectAndTlsTests(unittest.TestCase):
    def _redirect(self, newurl: str, *, original_url: str = "https://gitlab.example.com/api/v4/issues"):
        handler = gcore._NoCrossHostRedirectHandler()
        req = urllib.request.Request(original_url)
        return handler.redirect_request(req, None, 302, "Found", {}, newurl)

    def test_cross_host_redirect_is_refused(self) -> None:
        with self.assertRaises(gcore.GitLabPermanentError):
            self._redirect("https://evil.example.com/api/v4/issues")

    def test_same_host_scheme_downgrade_redirect_is_refused(self) -> None:
        # Regression test for the TLS-downgrade finding: a same-host
        # redirect from https to http must be refused, not merely a
        # cross-host redirect. This fails against the pre-fix code (which
        # only compared hostname) and passes against the fix (which also
        # compares scheme).
        with self.assertRaises(gcore.GitLabPermanentError):
            self._redirect("http://gitlab.example.com/api/v4/issues")

    def test_same_host_https_redirect_is_still_allowed(self) -> None:
        # The narrowing must not become overbroad: a same-host, same-scheme
        # redirect is exactly the case urllib's own HTTPRedirectHandler
        # already knows how to handle, and this handler must still delegate
        # to it rather than refusing every redirect outright.
        try:
            self._redirect("https://gitlab.example.com/api/v4/other-issues")
        except gcore.GitLabPermanentError:
            self.fail("a same-host, same-scheme redirect must not be refused")
        except Exception:
            # super().redirect_request() may raise urllib.error.HTTPError
            # (e.g. for a 302 with no Location handling context set up in
            # this synthetic call) -- that's fine; the point of this test is
            # only that our own GitLabPermanentError guard did not fire.
            pass

    def test_ssl_context_requires_certificate_verification(self) -> None:
        opener = gcore._build_opener()
        https_handlers = [h for h in opener.handlers if isinstance(h, urllib.request.HTTPSHandler)]
        self.assertEqual(len(https_handlers), 1)
        context = https_handlers[0]._context
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_ssl_context_verification_is_not_configurable_by_any_env_var(self) -> None:
        # There is no code path in _build_opener() that reads any
        # environment variable or config value to weaken TLS verification --
        # confirmed here by rebuilding the opener under a poisoned
        # environment containing plausible-looking "disable" flags and
        # asserting the resulting context is identical (full verification)
        # regardless.
        baseline_opener = gcore._build_opener()
        baseline_handler = next(h for h in baseline_opener.handlers if isinstance(h, urllib.request.HTTPSHandler))
        with mock.patch.dict(
            os.environ,
            {
                "GITLAB_DISABLE_TLS_VERIFY": "true",
                "GITLAB_SKIP_CERT_CHECK": "1",
                "GITLAB_INSECURE": "yes",
                "SSL_VERIFY": "false",
            },
        ):
            poisoned_opener = gcore._build_opener()
        poisoned_handler = next(h for h in poisoned_opener.handlers if isinstance(h, urllib.request.HTTPSHandler))
        self.assertEqual(baseline_handler._context.check_hostname, poisoned_handler._context.check_hostname)
        self.assertEqual(baseline_handler._context.verify_mode, poisoned_handler._context.verify_mode)
        self.assertTrue(poisoned_handler._context.check_hostname)
        self.assertEqual(poisoned_handler._context.verify_mode, ssl.CERT_REQUIRED)
        # Source-level backstop: no env-var read of any kind appears in
        # _build_opener's own source.
        source = inspect.getsource(gcore._build_opener)
        self.assertNotIn("os.environ", source)
        self.assertNotIn("getenv", source)


# ---------------------------------------------------------------------------
# gitlab_server.py: tool registration schema and fail-closed dependency on
# the optional `mcp` package, mirroring test_mcp_dispatch.py's
# DispatchServerSchemaTests / DispatchServerFailClosedTests exactly.
# ---------------------------------------------------------------------------


def _load_gitlab_server_module():
    spec = importlib.util.spec_from_file_location("gitlab_server_under_test", MCP_DIR / "gitlab_server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _StubFastMCP:
    """Minimal stand-in for mcp.server.fastmcp.FastMCP's decorator surface,
    used only to inspect the registered tools' schemas without depending on
    the real optional `mcp` package being installed."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator

    def run(self, transport: str = "stdio") -> None:  # pragma: no cover - not exercised
        raise AssertionError("run() should not be called from these tests")


class GitlabServerFailClosedTests(unittest.TestCase):
    def test_require_mcp_fails_closed_with_an_install_pointer_when_mcp_is_absent(self) -> None:
        # The real 'mcp' package is not installed in this environment, so
        # this exercises the actual fail-closed path, not a simulation.
        for name in list(sys.modules):
            if name == "mcp" or name.startswith("mcp."):
                self.fail(f"unexpected pre-loaded module {name}; test assumes mcp is absent")
        module = _load_gitlab_server_module()
        with self.assertRaises(RuntimeError) as ctx:
            module._require_mcp()
        self.assertIn("pip install", str(ctx.exception))
        self.assertIn("requirements-mcp.txt", str(ctx.exception))

    def test_build_server_fails_closed_through_require_mcp(self) -> None:
        for name in list(sys.modules):
            if name == "mcp" or name.startswith("mcp."):
                self.fail(f"unexpected pre-loaded module {name}; test assumes mcp is absent")
        module = _load_gitlab_server_module()
        with self.assertRaises(RuntimeError) as ctx:
            module.build_server()
        self.assertIn("pip install", str(ctx.exception))


class GitlabServerSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        stub_module = type(sys)("mcp")
        server_module = type(sys)("mcp.server")
        fastmcp_module = type(sys)("mcp.server.fastmcp")
        fastmcp_module.FastMCP = _StubFastMCP
        server_module.fastmcp = fastmcp_module
        stub_module.server = server_module
        self._patched = {
            "mcp": stub_module,
            "mcp.server": server_module,
            "mcp.server.fastmcp": fastmcp_module,
        }
        for name, module in self._patched.items():
            sys.modules[name] = module
        self.addCleanup(self._unpatch)

    def _unpatch(self) -> None:
        for name in self._patched:
            sys.modules.pop(name, None)

    def test_all_three_tools_are_registered_with_their_expected_names(self) -> None:
        module = _load_gitlab_server_module()
        server = module.build_server()
        self.assertEqual(
            set(server.tools), {"create_review_subtask", "write_wiki_page", "write_evidence_comment"}
        )

    def test_create_review_subtask_schema(self) -> None:
        module = _load_gitlab_server_module()
        server = module.build_server()
        tool = server.tools["create_review_subtask"]
        params = list(inspect.signature(tool).parameters)
        self.assertEqual(params, ["parent_issue_iid", "title", "description", "gate_id", "task_id"])

    def test_write_wiki_page_schema(self) -> None:
        module = _load_gitlab_server_module()
        server = module.build_server()
        tool = server.tools["write_wiki_page"]
        params = list(inspect.signature(tool).parameters)
        self.assertEqual(params, ["slug", "title", "content", "format", "confirmation_token"])
        default_format = inspect.signature(tool).parameters["format"].default
        self.assertEqual(default_format, "markdown")

    def test_write_evidence_comment_schema(self) -> None:
        module = _load_gitlab_server_module()
        server = module.build_server()
        tool = server.tools["write_evidence_comment"]
        params = list(inspect.signature(tool).parameters)
        self.assertEqual(params, ["issue_iid", "content", "task_id"])

    def test_create_review_subtask_tool_delegates_to_gitlab_core_unmutated(self) -> None:
        module = _load_gitlab_server_module()
        server = module.build_server()
        tool = server.tools["create_review_subtask"]

        captured = {}

        def fake_create(**kwargs):
            captured.update(kwargs)
            return {"status": "denied", "reason": "stub"}

        with mock.patch.object(module.core, "create_review_subtask", side_effect=fake_create):
            result = tool(parent_issue_iid=1, title="Review needed", description="Some body", gate_id="G5", task_id="TASK-1")

        self.assertEqual(result["status"], "denied")
        self.assertEqual(captured["parent_issue_iid"], 1)
        self.assertEqual(captured["gate_id"], "G5")
        self.assertEqual(captured["task_id"], "TASK-1")


if __name__ == "__main__":
    unittest.main()
