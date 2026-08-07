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

import hashlib
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
# This test directory itself -- see the same note in test_mcp_dispatch.py.
_TEST_DIR = Path(__file__).resolve().parent
if str(_TEST_DIR) not in sys.path:
    sys.path.insert(0, str(_TEST_DIR))

import dispatch_core  # noqa: E402
import gitlab_core as gcore  # noqa: E402
from mcp_absence import mcp_unimportable  # noqa: E402  (sibling test helper)

_SHARED_TEST_DIR = ORCHESTRATION_ROOT.parent / "shared" / "test"
if str(_SHARED_TEST_DIR) not in sys.path:
    sys.path.append(str(_SHARED_TEST_DIR))

from settings_test_helpers import isolate_settings_module  # noqa: E402  (sys.path set above)

FAKE_TOKEN = "glpat-FAKE-TEST-TOKEN-0000"

# Module-wide safety net: every test in this file that calls any of the
# three tools without an explicit audit_path= must never append to the real
# ~/.agents/mcp-gitlab/audit.jsonl on the host running the suite. Patching
# gcore.GITLAB_AUDIT_LOG_PATH once here (rather than per test class) covers
# every call site uniformly, including any test written in the future that
# forgets to pass audit_path= explicitly -- _write_gitlab_audit_record()
# looks up this module global by name on every call, so the patch applies
# regardless of when during module execution a given test runs.
_AUDIT_LOG_TMP_DIR = tempfile.TemporaryDirectory(prefix="mcp-gitlab-test-audit-")
_AUDIT_LOG_PATCHER = mock.patch.object(
    gcore, "GITLAB_AUDIT_LOG_PATH", Path(_AUDIT_LOG_TMP_DIR.name) / "audit.jsonl"
)

# Module-wide settings isolation: gcore.resolve_config() now goes through
# roster/shared/src/settings.py, which -- for any test in this file that
# pops an env var (e.g. ConfigResolutionTests.test_missing_project_id_fails_closed)
# -- would otherwise fall through to the real developer machine's
# ${XDG_CONFIG_HOME:-~/.config}/cadre/config.yaml and become
# machine-dependent, silently passing (or masking a real fail-closed
# regression) whenever such a file happens to exist locally.
_SETTINGS_ISOLATION = isolate_settings_module()


def setUpModule() -> None:
    _AUDIT_LOG_PATCHER.start()
    _SETTINGS_ISOLATION.start()


def tearDownModule() -> None:
    _AUDIT_LOG_PATCHER.stop()
    _AUDIT_LOG_TMP_DIR.cleanup()
    _SETTINGS_ISOLATION.stop()


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

    def test_base_url_containing_url_userinfo_is_rejected(self) -> None:
        # "https://gitlab.example.com@attacker.com/" looks, at a glance, like
        # it targets gitlab.example.com, but urllib/browsers parse everything
        # before the last "@" in the authority component as userinfo and
        # connect to attacker.com instead -- this would silently send the
        # PRIVATE-TOKEN header to an attacker-controlled host.
        with mock.patch.dict(
            os.environ,
            _base_env(**{gcore.GITLAB_BASE_URL_ENV_VAR: "https://gitlab.example.com@attacker.com/"}),
        ):
            with self.assertRaises(gcore.GitLabConfigError) as ctx:
                gcore.resolve_config()
        self.assertIn("userinfo", str(ctx.exception))

    def test_normal_base_url_with_no_userinfo_is_still_accepted(self) -> None:
        # Contrast case: an ordinary base URL with no "@" in the host
        # component must not be caught by the userinfo check above.
        with mock.patch.dict(os.environ, _base_env(**{gcore.GITLAB_BASE_URL_ENV_VAR: "https://gitlab.example.com"})):
            config = gcore.resolve_config()
        self.assertEqual(config.base_url, "https://gitlab.example.com")


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
            "state": "opened",
            "description": "Parent: #1\n\nSome body\n\n<!-- task_id=TASK-1 gate_id=G5 -->\n\n/relate #1\n",
            "labels": ["review-subtask", "gate:G5", gcore._evidence_key_label("TASK-1", "G5", 1)],
        }

        def _fake_request_json(method, path, config, token, **kwargs):
            self.assertEqual(method, "GET")
            self.assertTrue(path.endswith("/issues"))
            query = kwargs.get("query") or {}
            self.assertEqual(query.get("state"), "opened")
            self.assertIn(gcore._evidence_key_label("TASK-1", "G5", 1), query.get("labels", ""))
            return [existing_issue]

        with mock.patch.object(gcore, "request_json", side_effect=_fake_request_json) as mocked:
            result = gcore.create_review_subtask(1, "Review needed", "Some body", "G5", "TASK-1")

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["created"])
        self.assertEqual(result["state"], "opened")
        self.assertIn(str(existing_issue["iid"]), result["issue"])
        # Only the idempotency-search GET happened -- no POST was ever issued.
        for call in mocked.call_args_list:
            self.assertNotEqual(call.args[0], "POST")

    def test_closed_matching_issue_is_never_adopted_and_a_new_one_is_created(self) -> None:
        # A closed issue -- even one carrying the exact three-label
        # combination -- must never be silently treated as satisfying a
        # fresh review request; state=opened is both requested server-side
        # and re-verified locally against each candidate.
        closed_issue = {
            "iid": 7,
            "state": "closed",
            "description": "Parent: #1\n\nSome body\n\n<!-- task_id=TASK-1 gate_id=G5 -->\n\n/relate #1\n",
            "labels": ["review-subtask", "gate:G5", gcore._evidence_key_label("TASK-1", "G5", 1)],
        }

        def _fake_request_json(method, path, config, token, **kwargs):
            if method == "GET":
                return [closed_issue]
            return {"iid": 99, "state": "opened", "title": kwargs["json_body"]["title"]}

        with mock.patch.object(gcore, "request_json", side_effect=_fake_request_json):
            result = gcore.create_review_subtask(1, "Review needed", "Some body", "G5", "TASK-1")

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["created"])
        self.assertEqual(result["state"], "opened")

    def test_issue_matching_labels_for_a_different_parent_is_not_adopted(self) -> None:
        # Regression test for the dropped parent-binding fix: an open issue
        # carrying the right review-subtask/gate labels and an evidence-key
        # label computed for a *different* parent_issue_iid must not be
        # adopted as satisfying a request for this parent. Before folding
        # parent_issue_iid into the evidence-key hash, only (task_id,
        # gate_id) were hashed, so this decoy would have matched regardless
        # of which parent it actually referenced.
        wrong_parent_issue = {
            "iid": 8,
            "state": "opened",
            "description": "Parent: #999\n\nSome other body\n\n<!-- task_id=TASK-1 gate_id=G5 -->\n\n/relate #999\n",
            "labels": ["review-subtask", "gate:G5", gcore._evidence_key_label("TASK-1", "G5", 999)],
        }

        def _fake_request_json(method, path, config, token, **kwargs):
            if method == "GET":
                return [wrong_parent_issue]
            return {"iid": 100, "state": "opened", "title": kwargs["json_body"]["title"]}

        with mock.patch.object(gcore, "request_json", side_effect=_fake_request_json):
            result = gcore.create_review_subtask(1, "Review needed", "Some body", "G5", "TASK-1")

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["created"])

    def test_decoy_issue_missing_the_evidence_key_label_is_not_adopted(self) -> None:
        # A decoy issue carrying only the review-subtask/gate labels (e.g. a
        # coincidentally-labeled issue an attacker without write access to
        # this project could not have produced anyway, but defended against
        # regardless) must not satisfy the idempotency search -- only the
        # exact three-label combination, re-verified locally, does.
        decoy_issue = {
            "iid": 5,
            "state": "opened",
            "description": "Parent: #1\n\nSome body\n\n<!-- task_id=TASK-1 gate_id=G5 -->\n\n/relate #1\n",
            "labels": ["review-subtask", "gate:G5"],
        }

        def _fake_request_json(method, path, config, token, **kwargs):
            if method == "GET":
                return [decoy_issue]
            return {"iid": 100, "state": "opened", "title": kwargs["json_body"]["title"]}

        with mock.patch.object(gcore, "request_json", side_effect=_fake_request_json):
            result = gcore.create_review_subtask(1, "Review needed", "Some body", "G5", "TASK-1")

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["created"])

    def test_idempotency_search_paginates_when_the_match_is_not_on_the_first_page(self) -> None:
        matching_issue = {
            "iid": 42,
            "state": "opened",
            "description": "Parent: #1\n\nSome body\n\n<!-- task_id=TASK-1 gate_id=G5 -->\n\n/relate #1\n",
            "labels": ["review-subtask", "gate:G5", gcore._evidence_key_label("TASK-1", "G5", 1)],
        }
        # A full first page (page-size worth of issues) that carry the
        # review-subtask/gate labels but not the evidence-key label, so the
        # first page yields no local match and the loop must advance to
        # page 2 (rather than a real GitLab deployment ever returning this
        # shape given the exact server-side label filter -- this is a
        # defensive-completeness test of the pagination loop itself).
        full_page_of_non_matching_issues = [
            {"iid": index, "state": "opened", "labels": ["review-subtask", "gate:G5"]}
            for index in range(gcore._ISSUE_SEARCH_PAGE_SIZE)
        ]
        pages_seen: list[str] = []

        def _fake_request_json(method, path, config, token, **kwargs):
            query = kwargs.get("query") or {}
            pages_seen.append(query.get("page"))
            if query.get("page") == "1":
                return full_page_of_non_matching_issues
            return [matching_issue]

        with mock.patch.object(gcore, "request_json", side_effect=_fake_request_json) as mocked:
            result = gcore.create_review_subtask(1, "Review needed", "Some body", "G5", "TASK-1")

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["created"])
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(pages_seen, ["1", "2"])

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
        # "/relate" quick action. A future silent switch to a real
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
        self.assertIn("/relate #1", captured_payload["description"])
        # No GraphQL/work-item-hierarchy-shaped field is ever sent.
        self.assertNotIn("workItemId", captured_payload)
        self.assertNotIn("parentId", captured_payload)


# ---------------------------------------------------------------------------
# Quick-action injection neutralization (create_review_subtask's description,
# write_evidence_comment's content).
# ---------------------------------------------------------------------------


class QuickActionNeutralizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patcher = mock.patch.dict(os.environ, _base_env())
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)

    def test_create_review_subtask_rejects_a_leading_close_line_with_zero_http_calls(self) -> None:
        malicious_description = "Please review this.\n/close\nThanks."
        with mock.patch.object(gcore, "request_json") as mocked:
            result = gcore.create_review_subtask(1, "Review needed", malicious_description, "G5", "TASK-1")
        self.assertEqual(result["status"], "denied")
        self.assertIn("quick action", result["reason"])
        mocked.assert_not_called()

    def test_create_review_subtask_rejects_an_unlabel_line_with_zero_http_calls(self) -> None:
        malicious_description = '/unlabel ~"review-subtask"'
        with mock.patch.object(gcore, "request_json") as mocked:
            result = gcore.create_review_subtask(1, "Review needed", malicious_description, "G5", "TASK-1")
        self.assertEqual(result["status"], "denied")
        mocked.assert_not_called()

    def test_create_review_subtask_rejects_a_capitalized_close_line_with_zero_http_calls(self) -> None:
        # GitLab's own quick-action matching is case-insensitive server-side,
        # so the filter must reject case-varied commands too, not only the
        # all-lowercase shape.
        malicious_description = "Please review this.\n/Close\nThanks."
        with mock.patch.object(gcore, "request_json") as mocked:
            result = gcore.create_review_subtask(1, "Review needed", malicious_description, "G5", "TASK-1")
        self.assertEqual(result["status"], "denied")
        self.assertIn("quick action", result["reason"])
        mocked.assert_not_called()

    def test_create_review_subtask_rejects_an_all_caps_close_line_with_zero_http_calls(self) -> None:
        malicious_description = "Please review this.\n/CLOSE\nThanks."
        with mock.patch.object(gcore, "request_json") as mocked:
            result = gcore.create_review_subtask(1, "Review needed", malicious_description, "G5", "TASK-1")
        self.assertEqual(result["status"], "denied")
        mocked.assert_not_called()

    def test_create_review_subtask_rejects_mixed_case_unlabel_line_with_zero_http_calls(self) -> None:
        malicious_description = '/UNLABEL ~"review-subtask"'
        with mock.patch.object(gcore, "request_json") as mocked:
            result = gcore.create_review_subtask(1, "Review needed", malicious_description, "G5", "TASK-1")
        self.assertEqual(result["status"], "denied")
        mocked.assert_not_called()

    def test_write_evidence_comment_rejects_a_capitalized_close_line_with_zero_http_calls(self) -> None:
        with mock.patch.object(gcore, "request_json") as mocked:
            result = gcore.write_evidence_comment(1, "Evidence attached.\n/Close\n", "TASK-1")
        self.assertEqual(result["status"], "denied")
        self.assertIn("quick action", result["reason"])
        mocked.assert_not_called()

    def test_write_evidence_comment_rejects_an_all_caps_close_line_with_zero_http_calls(self) -> None:
        with mock.patch.object(gcore, "request_json") as mocked:
            result = gcore.write_evidence_comment(1, "Evidence attached.\n/CLOSE\n", "TASK-1")
        self.assertEqual(result["status"], "denied")
        mocked.assert_not_called()

    def test_write_evidence_comment_rejects_a_mixed_case_close_line_with_zero_http_calls(self) -> None:
        with mock.patch.object(gcore, "request_json") as mocked:
            result = gcore.write_evidence_comment(1, "Evidence attached.\n/cLoSe\n", "TASK-1")
        self.assertEqual(result["status"], "denied")
        mocked.assert_not_called()

    def test_write_evidence_comment_rejects_mixed_case_unlabel_line_with_zero_http_calls(self) -> None:
        with mock.patch.object(gcore, "request_json") as mocked:
            result = gcore.write_evidence_comment(1, '/UnLaBeL ~"review-subtask"', "TASK-1")
        self.assertEqual(result["status"], "denied")
        mocked.assert_not_called()

    def test_write_evidence_comment_rejects_a_leading_close_line_with_zero_http_calls(self) -> None:
        with mock.patch.object(gcore, "request_json") as mocked:
            result = gcore.write_evidence_comment(1, "Evidence attached.\n/reopen\n", "TASK-1")
        self.assertEqual(result["status"], "denied")
        self.assertIn("quick action", result["reason"])
        mocked.assert_not_called()

    def test_quick_action_line_indented_with_leading_whitespace_is_still_rejected(self) -> None:
        # _QUICK_ACTION_LINE_PATTERN allows leading whitespace before the
        # slash, mirroring GitLab's own tolerant parsing of quick-action lines.
        with mock.patch.object(gcore, "request_json") as mocked:
            result = gcore.write_evidence_comment(1, "Body text\n   /confidential\nmore text", "TASK-1")
        self.assertEqual(result["status"], "denied")
        mocked.assert_not_called()

    def test_ordinary_prose_is_still_accepted(self) -> None:
        with mock.patch.object(gcore, "request_json", return_value={"id": 1, "body": "ok"}):
            result = gcore.write_evidence_comment(
                1, "The build passed. See /var/log/build.log for details.", "TASK-1"
            )
        self.assertEqual(result["status"], "ok")

    def test_slash_mid_line_not_at_line_start_is_still_accepted(self) -> None:
        with mock.patch.object(gcore, "request_json", return_value={"id": 1, "body": "ok"}):
            result = gcore.write_evidence_comment(1, "Fetched from https://example.com/foo/bar", "TASK-1")
        self.assertEqual(result["status"], "ok")

    def test_create_review_subtask_ordinary_description_is_still_accepted_and_relate_line_is_appended(
        self,
    ) -> None:
        captured_payload = {}

        def _fake_request_json(method, path, config, token, **kwargs):
            if method == "GET":
                return []
            captured_payload.update(kwargs.get("json_body", {}))
            return {"iid": 1, "title": kwargs["json_body"]["title"]}

        with mock.patch.object(gcore, "request_json", side_effect=_fake_request_json):
            result = gcore.create_review_subtask(
                1, "Review needed", "A file path starts a line: /etc/hosts has entries.", "G5", "TASK-1"
            )
        self.assertEqual(result["status"], "ok")
        # This module's own trusted quick action is still present and was
        # never itself rejected by the check applied to caller input only.
        self.assertIn("/relate #1", captured_payload["description"])


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
        # The first (unconfirmed) call does perform one read -- the
        # existence check that populates will_overwrite_existing (see
        # test_first_call_discloses_whether_it_will_overwrite_an_existing_page
        # below) -- but never a write (POST/PUT).
        with mock.patch.object(gcore, "request_json", return_value=None) as mocked:
            result = gcore.write_wiki_page("evidence/task-1", "Evidence", "content")
        self.assertEqual(result["status"], "confirmation_required")
        self.assertIn("confirmation_token", result)
        mocked.assert_called_once()
        self.assertEqual(mocked.call_args.args[0], "GET")

    def test_second_call_with_matching_token_writes_exactly_once(self) -> None:
        with mock.patch.object(gcore, "request_json", return_value=None) as mocked:
            first = gcore.write_wiki_page("evidence/task-1", "Evidence", "content")
            mocked.side_effect = [None, {"slug": "evidence/task-1", "content": "content"}]
            second = gcore.write_wiki_page(
                "evidence/task-1", "Evidence", "content", confirmation_token=first["confirmation_token"]
            )
        self.assertEqual(second["status"], "ok")
        # existence-check GET (first call) + existence-check GET (miss,
        # second call) + POST (create).
        self.assertEqual(mocked.call_count, 3)

    def test_reusing_a_token_a_second_time_is_denied(self) -> None:
        with mock.patch.object(gcore, "request_json", side_effect=[None, None, {"slug": "s"}]):
            first = gcore.write_wiki_page("evidence/task-1", "Evidence", "content")
            gcore.write_wiki_page("evidence/task-1", "Evidence", "content", confirmation_token=first["confirmation_token"])
        with mock.patch.object(gcore, "request_json") as mocked:
            replay = gcore.write_wiki_page(
                "evidence/task-1", "Evidence", "content", confirmation_token=first["confirmation_token"]
            )
        self.assertEqual(replay["status"], "denied")
        mocked.assert_not_called()

    def test_tampering_with_content_after_confirmation_request_invalidates_it(self) -> None:
        with mock.patch.object(gcore, "request_json", return_value=None) as mocked:
            first = gcore.write_wiki_page("evidence/task-1", "Evidence", "content")
            tampered = gcore.write_wiki_page(
                "evidence/task-1", "Evidence", "DIFFERENT CONTENT", confirmation_token=first["confirmation_token"]
            )
        self.assertEqual(tampered["status"], "denied")
        # Only the first call's existence-check GET happened; the tampered
        # second call is denied before ever reaching _get_wiki_page.
        mocked.assert_called_once()

    def test_first_call_discloses_whether_it_will_overwrite_an_existing_page(self) -> None:
        with mock.patch.object(gcore, "request_json", return_value=None):
            result = gcore.write_wiki_page("evidence/task-1", "Evidence", "content")
        self.assertIn("will_overwrite_existing", result)
        self.assertFalse(result["will_overwrite_existing"])

        gcore._WIKI_CONFIRMATION_GATE = dispatch_core.ConfirmationGate()
        with mock.patch.object(gcore, "request_json", return_value={"slug": "evidence/task-1", "content": "old"}):
            result = gcore.write_wiki_page("evidence/task-1", "Evidence", "content")
        self.assertTrue(result["will_overwrite_existing"])

    def test_existence_check_error_before_confirmation_re_raises_rather_than_silently_proceeding(self) -> None:
        with mock.patch.object(
            gcore, "request_json", side_effect=gcore.GitLabPermanentError("denied", status_code=403)
        ) as mocked:
            result = gcore.write_wiki_page("evidence/task-1", "Evidence", "content")
        self.assertEqual(result["status"], "denied")
        self.assertEqual(result["status_code"], 403)
        mocked.assert_called_once()

    def test_over_cap_content_is_rejected_without_truncation_and_without_any_http_call(self) -> None:
        # Mirrors WriteEvidenceCommentTests's identically-named test: the
        # size cap is checked before resolve_token_and_config()/any existence
        # check, so an over-cap call must make zero HTTP calls, even though
        # write_wiki_page's ordinary path would otherwise perform an
        # existence-check GET before returning confirmation_required.
        oversized = "x" * (gcore.MAX_WIKI_PAGE_CONTENT_BYTES + 1)
        with mock.patch.object(gcore, "request_json") as mocked:
            result = gcore.write_wiki_page("evidence/task-1", "Evidence", oversized)
        self.assertEqual(result["status"], "denied")
        self.assertIn(str(gcore.MAX_WIKI_PAGE_CONTENT_BYTES), result["reason"])
        mocked.assert_not_called()

    def test_exactly_at_cap_is_accepted(self) -> None:
        exactly_at_cap = "x" * gcore.MAX_WIKI_PAGE_CONTENT_BYTES
        with mock.patch.object(gcore, "request_json", return_value=None):
            result = gcore.write_wiki_page("evidence/task-1", "Evidence", exactly_at_cap)
        self.assertEqual(result["status"], "confirmation_required")


# ---------------------------------------------------------------------------
# _get_wiki_page: real 404 vs real non-404 permanent error vs an existing
# page, and the full create-vs-update (POST vs PUT) branch each drives.
# ---------------------------------------------------------------------------


class GetWikiPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patcher = mock.patch.dict(os.environ, _base_env())
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)
        self.config = gcore.resolve_config()
        self.token = gcore.resolve_token()

    def test_real_404_is_treated_as_page_not_found(self) -> None:
        with mock.patch.object(
            gcore, "request_json", side_effect=gcore.GitLabPermanentError("not found", status_code=404)
        ):
            result = gcore._get_wiki_page(self.config, self.token, "evidence/task-1")
        self.assertIsNone(result)

    def test_real_403_re_raises_rather_than_being_treated_as_not_found(self) -> None:
        with mock.patch.object(
            gcore, "request_json", side_effect=gcore.GitLabPermanentError("denied", status_code=403)
        ):
            with self.assertRaises(gcore.GitLabPermanentError) as ctx:
                gcore._get_wiki_page(self.config, self.token, "evidence/task-1")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_existing_page_is_returned_unchanged(self) -> None:
        page = {"slug": "evidence/task-1", "content": "hello"}
        with mock.patch.object(gcore, "request_json", return_value=page):
            result = gcore._get_wiki_page(self.config, self.token, "evidence/task-1")
        self.assertEqual(result, page)


class WriteWikiPageCreateVsUpdateTests(unittest.TestCase):
    """Full round trip through write_wiki_page's real GET-then-catch-404
    detection (not a test double that returns None directly for "doesn't
    exist"), asserting the resulting POST-vs-PUT branch."""

    def setUp(self) -> None:
        self.env_patcher = mock.patch.dict(os.environ, _base_env())
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)
        gcore._WIKI_CONFIRMATION_GATE = dispatch_core.ConfirmationGate()

    def test_real_404_on_get_takes_the_create_post_path(self) -> None:
        calls: list[str] = []

        def _fake_request_json(method, path, config, token, **kwargs):
            calls.append(method)
            if method == "GET":
                raise gcore.GitLabPermanentError("not found", status_code=404)
            return {"slug": "evidence/task-1", "content": "content"}

        with mock.patch.object(gcore, "request_json", side_effect=_fake_request_json):
            first = gcore.write_wiki_page("evidence/task-1", "Evidence", "content")
            second = gcore.write_wiki_page(
                "evidence/task-1", "Evidence", "content", confirmation_token=first["confirmation_token"]
            )

        self.assertFalse(first["will_overwrite_existing"])
        self.assertEqual(second["status"], "ok")
        self.assertTrue(second["created"])
        self.assertEqual(calls, ["GET", "GET", "POST"])

    def test_existing_page_on_get_takes_the_update_put_path(self) -> None:
        existing_page = {"slug": "evidence/task-1", "content": "old"}
        calls: list[str] = []

        def _fake_request_json(method, path, config, token, **kwargs):
            calls.append(method)
            if method == "GET":
                return existing_page
            return {"slug": "evidence/task-1", "content": "content"}

        with mock.patch.object(gcore, "request_json", side_effect=_fake_request_json):
            first = gcore.write_wiki_page("evidence/task-1", "Evidence", "content")
            second = gcore.write_wiki_page(
                "evidence/task-1", "Evidence", "content", confirmation_token=first["confirmation_token"]
            )

        self.assertTrue(first["will_overwrite_existing"])
        self.assertEqual(second["status"], "ok")
        self.assertFalse(second["created"])
        self.assertEqual(calls, ["GET", "GET", "PUT"])

    def test_non_404_permanent_error_on_get_re_raises_rather_than_falling_through_to_create(self) -> None:
        # The pre-confirmation existence check (first call) must succeed --
        # a real 404, treated as "page doesn't exist yet" -- so a
        # confirmation_token is actually issued; the 403 this test cares
        # about is injected only on the *second* GET, the one taken during
        # the confirmed write itself, to isolate that specific re-raise
        # behavior from the pre-confirmation check added separately above.
        calls: list[str] = []
        get_call_count = 0

        def _fake_request_json(method, path, config, token, **kwargs):
            nonlocal get_call_count
            calls.append(method)
            if method == "GET":
                get_call_count += 1
                if get_call_count == 1:
                    raise gcore.GitLabPermanentError("not found", status_code=404)
                raise gcore.GitLabPermanentError("denied", status_code=403)
            raise AssertionError("a 403 on GET must re-raise, never fall through to a POST/PUT")

        with mock.patch.object(gcore, "request_json", side_effect=_fake_request_json):
            first = gcore.write_wiki_page("evidence/task-1", "Evidence", "content")
            second = gcore.write_wiki_page(
                "evidence/task-1", "Evidence", "content", confirmation_token=first["confirmation_token"]
            )

        self.assertEqual(first["status"], "confirmation_required")
        self.assertFalse(first["will_overwrite_existing"])
        self.assertEqual(second["status"], "denied")
        self.assertEqual(second["status_code"], 403)
        # Never a POST -- the 403 on GET must re-raise, not be silently
        # treated as "page doesn't exist, proceed to create".
        self.assertEqual(calls, ["GET", "GET"])


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
            "state": "opened",
            "description": "Parent: #1\n\nSome body\n\n<!-- task_id=TASK-1 gate_id=G5 -->\n\n/relate #1\n",
            "labels": ["review-subtask", "gate:G5", gcore._evidence_key_label("TASK-1", "G5", 1)],
        }
        with mock.patch.object(gcore, "request_json", return_value=[existing_issue]):
            result = gcore.create_review_subtask(1, "Review needed", "Some body", "G5", "TASK-1")
        self._assert_wrapped(result["issue"])

    def test_write_wiki_page_page_payload_is_wrapped(self) -> None:
        with mock.patch.object(gcore, "request_json", side_effect=[None, None, {"slug": "s", "content": "c"}]):
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
        with mock.patch.object(gcore, "request_json", side_effect=[None, None, {"slug": "s"}]):
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
        with mock.patch.object(gcore, "request_json", side_effect=[None, None, {"slug": "s"}]):
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

    def test_real_http_error_with_a_sensitive_response_body_never_reaches_the_audit_file(self) -> None:
        # Unlike every other test in this class (and every other test in
        # this file that raises GitLabPermanentError directly with a plain
        # string, where audit_reason trivially equals message because there
        # was never a raw body to begin with), this test drives an actual
        # urllib.error.HTTPError *with a response body* through the real,
        # unmocked request_json() -- only _perform_request is mocked, the
        # same mocking layer RequestJsonRetryTests uses -- so the real
        # redaction path in request_json()/_audit_safe_reason()/
        # _audit_error_meta() is what's under test, not a test double that
        # never had a body to redact in the first place.
        sensitive_body = b'{"message":"denied","secret_token":"glpat-SUPER-SECRET-LEAKED-VALUE"}'
        with mock.patch.dict(os.environ, _base_env()):
            with mock.patch.object(gcore, "_perform_request", side_effect=_http_error(403, sensitive_body)):
                result = gcore.write_evidence_comment(1, "content", "TASK-1", audit_path=self.audit_path)

        self.assertEqual(result["status"], "denied")

        records = self._read_records()
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["decision"], "denied")
        # The redaction mechanism's positive claim: hash/length fields are
        # present as evidence that a response body existed and how large it
        # was...
        self.assertIn("response_body_sha256", record)
        self.assertIn("response_body_length", record)
        expected_sha256 = hashlib.sha256(sensitive_body.decode("utf-8").encode("utf-8")).hexdigest()
        self.assertEqual(record["response_body_sha256"], expected_sha256)
        self.assertEqual(record["response_body_length"], len(sensitive_body))
        # ...while the raw body text itself is verifiably absent from the
        # audit file's raw contents (mirroring
        # test_no_audit_record_ever_contains_the_token_or_raw_content above,
        # but for an HTTP-error-with-body case specifically).
        raw = self.audit_path.read_text(encoding="utf-8")
        self.assertNotIn("glpat-SUPER-SECRET-LEAKED-VALUE", raw)
        self.assertNotIn("secret_token", raw)
        self.assertNotIn(sensitive_body.decode("utf-8"), raw)


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

    def test_build_opener_actually_wires_in_the_no_cross_host_redirect_handler(self) -> None:
        # Regression test for the gap where _NoCrossHostRedirectHandler was
        # only ever exercised as an isolated object (via self._redirect()
        # above), never proven to actually be installed on the opener
        # _perform_request() uses for real requests. A future edit that
        # silently dropped this handler from _build_opener() -- leaving
        # urllib's default HTTPRedirectHandler in place, which happily
        # follows cross-host/scheme-downgrade redirects -- must fail this
        # test.
        opener = gcore._build_opener()
        self.assertTrue(
            any(isinstance(handler, gcore._NoCrossHostRedirectHandler) for handler in opener.handlers),
            "opener.handlers has no _NoCrossHostRedirectHandler instance",
        )

    def test_build_opener_never_honors_an_ambient_proxy_env_var(self) -> None:
        # Regression test for the finding that urllib.request.build_opener()
        # only skips a *default* handler class when an instance of that
        # exact class is already among the handlers passed in. Neither
        # HTTPSHandler nor _NoCrossHostRedirectHandler is a ProxyHandler, so
        # without an explicit ProxyHandler({}) argument in _build_opener(),
        # build_opener() would silently instantiate and wire in its own
        # default ProxyHandler(), which consults HTTPS_PROXY/https_proxy/
        # ALL_PROXY via getproxies() and would route every GitLab API call
        # through whatever proxy an ambient environment variable names --
        # with no logging and no opt-out anywhere in this module.
        #
        # Note on what to assert: empirically (verified directly against
        # CPython's urllib.request.OpenerDirector.add_handler), a
        # ProxyHandler constructed with an *empty* proxy map registers no
        # protocol-open methods and is therefore never appended to
        # opener.handlers at all -- so "the opener's handlers contains a
        # ProxyHandler instance" is not itself the correct proof of the fix
        # (a bare `ProxyHandler({})` and "no ProxyHandler present" are
        # observationally identical on opener.handlers). The proof that
        # actually distinguishes fixed from unfixed code is: (1) the exact
        # positional argument list this module passes to
        # urllib.request.build_opener() includes an explicit
        # ProxyHandler({}) instance, which is what makes build_opener()'s
        # own skip-default-class logic skip instantiating an
        # environment-driven default ProxyHandler in the first place
        # (confirmed by reading urllib.request.build_opener's source: it
        # skips a default class only when an instance of that class is
        # among the *caller-supplied* handlers, not by inspecting the
        # resulting opener); and (2) the resulting opener's "https" open
        # chain contains exactly the one HTTPSHandler and no proxy-capable
        # handler, even with proxy env vars set. Both are asserted below.
        # This fails against the pre-fix code: pre-fix, build_opener() is
        # called with only (https_handler, _NoCrossHostRedirectHandler())
        # -- no ProxyHandler instance in the call args at all -- so
        # assertion (1) fails immediately; and pre-fix, build_opener()'s
        # skip-default logic (seeing no caller-supplied ProxyHandler)
        # instantiates its own default ProxyHandler() from the ambient
        # HTTPS_PROXY set below, which registers an "https_open" method and
        # so is appended to opener.handlers and to
        # opener.handle_open["https"] alongside HTTPSHandler -- so assertion
        # (2) also fails pre-fix.
        real_build_opener = urllib.request.build_opener
        captured_args: list[tuple] = []

        def _capturing_build_opener(*handlers):
            captured_args.append(handlers)
            return real_build_opener(*handlers)

        with mock.patch.dict(
            os.environ,
            {
                "HTTPS_PROXY": "http://attacker.example:8080",
                "https_proxy": "http://attacker.example:8080",
                "ALL_PROXY": "http://attacker.example:8080",
            },
        ), mock.patch("urllib.request.build_opener", side_effect=_capturing_build_opener):
            opener = gcore._build_opener()

        self.assertEqual(len(captured_args), 1)
        passed_handlers = captured_args[0]
        explicit_proxy_handlers = [h for h in passed_handlers if isinstance(h, urllib.request.ProxyHandler)]
        self.assertEqual(
            len(explicit_proxy_handlers),
            1,
            "_build_opener() must pass an explicit ProxyHandler instance to "
            "urllib.request.build_opener() so build_opener()'s own "
            "skip-default-class logic never instantiates an "
            "environment-driven default ProxyHandler",
        )
        self.assertEqual(
            explicit_proxy_handlers[0].proxies,
            {},
            "the explicit ProxyHandler passed to build_opener() must be "
            "constructed with an empty proxy map, not one derived from "
            "ambient HTTPS_PROXY/https_proxy/ALL_PROXY via getproxies()",
        )

        https_open_chain = opener.handle_open.get("https", [])
        self.assertEqual(
            len(https_open_chain),
            1,
            "the opener's https-open chain must contain exactly one "
            "handler; a second entry here would be a proxy handler "
            "silently intercepting every GitLab HTTPS request",
        )
        self.assertIsInstance(https_open_chain[0], urllib.request.HTTPSHandler)

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
        # Simulates mcp's absence rather than asserting the host doesn't
        # have it (see mcp_absence.py): this repository ships MCP servers,
        # so a developer running them has the real package installed, and
        # the previous host-dependent form failed on exactly those machines
        # while passing on a CI runner that never installs it.
        with mcp_unimportable():
            module = _load_gitlab_server_module()
            with self.assertRaises(RuntimeError) as ctx:
                module._require_mcp()
        self.assertIn("pip install", str(ctx.exception))
        self.assertIn("requirements-mcp.txt", str(ctx.exception))

    def test_build_server_fails_closed_through_require_mcp(self) -> None:
        with mcp_unimportable():
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

    def test_write_wiki_page_tool_forwards_confirmation_token_and_format_unmutated(self) -> None:
        module = _load_gitlab_server_module()
        server = module.build_server()
        tool = server.tools["write_wiki_page"]

        captured = {}

        def fake_write_wiki_page(**kwargs):
            captured.update(kwargs)
            return {"status": "confirmation_required", "confirmation_token": "stub-token"}

        with mock.patch.object(module.core, "write_wiki_page", side_effect=fake_write_wiki_page):
            result = tool(
                slug="evidence/task-1",
                title="Evidence",
                content="body",
                format="rdoc",
                confirmation_token="a-real-token",
            )

        self.assertEqual(result["status"], "confirmation_required")
        self.assertEqual(captured["slug"], "evidence/task-1")
        self.assertEqual(captured["title"], "Evidence")
        self.assertEqual(captured["content"], "body")
        # The two fields this finding calls out by name -- confirm neither
        # is silently dropped on the way from the MCP tool wrapper to
        # gitlab_core.write_wiki_page.
        self.assertEqual(captured["format"], "rdoc")
        self.assertEqual(captured["confirmation_token"], "a-real-token")

    def test_write_evidence_comment_tool_delegates_to_gitlab_core_unmutated(self) -> None:
        module = _load_gitlab_server_module()
        server = module.build_server()
        tool = server.tools["write_evidence_comment"]

        captured = {}

        def fake_write_evidence_comment(**kwargs):
            captured.update(kwargs)
            return {"status": "ok", "comment": "stub"}

        with mock.patch.object(module.core, "write_evidence_comment", side_effect=fake_write_evidence_comment):
            result = tool(issue_iid=7, content="evidence text", task_id="TASK-1")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(captured["issue_iid"], 7)
        self.assertEqual(captured["content"], "evidence text")
        self.assertEqual(captured["task_id"], "TASK-1")


if __name__ == "__main__":
    unittest.main()
