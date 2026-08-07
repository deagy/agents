"""Tests for `publish-reviewer-nudge` / `list-reviewer-nudge`
(`agentic_sdlc/reviewer_nudge.py`).

No `gh` binary or network access is required -- every GitHub call is mocked
via three environment variables reused unmodified from the two features this
module composes: `AGENTIC_SDLC_TEST_GITHUB_READ_FILE` /
`AGENTIC_SDLC_TEST_GITHUB_REVIEWS_FILE` (`gate_reviewers.py`'s own mock
convention, for the classified report) and
`AGENTIC_SDLC_TEST_GITHUB_WRITE_FILE` (`gate_status.py`'s own mock
convention, for comment create/update/list/verify-identity).
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

import agentic_sdlc  # type: ignore
from agentic_sdlc import gate_issues, gate_reviewers, gate_status, github_status_write, github_write, reviewer_nudge  # type: ignore

CLI_COMMAND = [sys.executable, str(PLUGIN_ROOT / "dev_entrypoint.py")]
FIXED_TIME = "2030-01-01T00:00:00.000000Z"


# --------------------------------------------------------------------------
# Fixture builders (mirror test_gate_reviewers.py's conventions)
# --------------------------------------------------------------------------


def make_authority(*, status="assigned", assignee="human:default", github_login=None, applicability="applicable", rationale=None):
    return {
        "status": status,
        "assignee": assignee,
        "github_login": github_login,
        "applicability": applicability,
        "rationale": rationale,
    }


def make_ar(authority_id, role, *, applicability="applicable", rationale="Assigned in project authority map", authority_type="human-approver"):
    return {
        "authority_id": authority_id,
        "authority_type": authority_type,
        "role": role,
        "applicability": applicability,
        "rationale": rationale,
    }


def make_gate(gate_id, *, applicability="applicable", status="pending", required_reentry_gate=None,
              authority_requirements=None, applicability_rationale="Lifecycle gate applies by default",
              preparers=None, independent_verifier=None):
    return {
        "gate_id": gate_id,
        "applicability": applicability,
        "applicability_rationale": applicability_rationale,
        "status": status,
        "required_reentry_gate": required_reentry_gate,
        "authority_requirements": authority_requirements or [],
        "preparers": preparers or [],
        "independent_verifier": independent_verifier,
    }


def default_pr(*, repo="owner/proj", head_sha="a" * 40, base_full_name="owner/proj", author="pr-author",
                state="open", merged=False, draft=False):
    return {
        "state": state,
        "merged": merged,
        "draft": draft,
        "user": {"login": author},
        "head": {"sha": head_sha},
        "base": {"repo": {"full_name": base_full_name}},
    }


def all_collaborators_all_exist(logins, repo="owner/proj"):
    return (
        {login: True for login in logins},
        {f"{repo}:{login}": True for login in logins},
    )


class ReviewerNudgeTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.overlay = self.root / ".agentic-sdlc"
        (self.overlay / "runs" / "T1").mkdir(parents=True)
        self.addCleanup(self.temporary.cleanup)

    def write_overlay(self, *, task_id="T1", classification="internal", gates, configured_gate_ids=None,
                       authorities, dispatch_fingerprint="sha256:" + "a" * 64):
        (self.overlay / "project.json").write_text(json.dumps({"classification": classification}), encoding="utf-8")
        (self.overlay / "authorities.json").write_text(json.dumps(authorities), encoding="utf-8")
        (self.overlay / "runs" / task_id).mkdir(parents=True, exist_ok=True)
        record = {
            "classification": classification,
            "disposition": "pending",
            "scope": "Build the widget service",
            "re_entry_history": [],
            "lifecycle_gates": gates,
        }
        (self.overlay / "runs" / task_id / "run-record.json").write_text(json.dumps(record), encoding="utf-8")
        configured = configured_gate_ids if configured_gate_ids is not None else [g["gate_id"] for g in gates]
        dispatch = {
            "dispatch_fingerprint": dispatch_fingerprint,
            "gate_dispatch": [{"gate_id": gid, "status": "required"} for gid in configured],
        }
        (self.overlay / "runs" / task_id / "dispatch-plan.json").write_text(json.dumps(dispatch), encoding="utf-8")

    def mock_env(self, github_read_payload, reviews_payload=None, write_payload=None):
        read_path = self.root / "github-read.json"
        read_path.write_text(json.dumps(github_read_payload), encoding="utf-8")
        reviews_path = self.root / "reviews.json"
        reviews_path.write_text(json.dumps(reviews_payload if reviews_payload is not None else []), encoding="utf-8")
        env = {
            github_write.GITHUB_READ_MOCK_ENV_VAR: str(read_path),
            "AGENTIC_SDLC_TEST_GITHUB_REVIEWS_FILE": str(reviews_path),
        }
        if write_payload is not None:
            write_path = self.root / "github-write.json"
            write_path.write_text(json.dumps(write_payload), encoding="utf-8")
            env[github_status_write.GITHUB_WRITE_MOCK_ENV_VAR] = str(write_path)
        return mock.patch.dict(os.environ, env)

    def base_read_mock(self, *, bot="svc-bot", pr=None, requested=None, users=None, collaborators=None):
        return {
            "identity": {"login": bot},
            "pr": pr if pr is not None else default_pr(),
            "requested_reviewers": {"users": [{"login": login} for login in (requested or [])], "teams": []},
            "users": users or {},
            "collaborators": collaborators or {},
        }

    def frozen_time(self):
        return mock.patch.object(reviewer_nudge, "now", return_value=FIXED_TIME)

    def run_nudge(self, **kwargs):
        kwargs.setdefault("root", self.root)
        kwargs.setdefault("task_id", "T1")
        kwargs.setdefault("repo", "owner/proj")
        kwargs.setdefault("pr", 42)
        kwargs.setdefault("as_bot", "svc-bot")
        kwargs.setdefault("gates", None)
        kwargs.setdefault("allow_classification", "internal")
        kwargs.setdefault("apply", False)
        return reviewer_nudge.run(**kwargs)


def single_gate_with_two_reviewers():
    gates = [
        make_gate("G3", authority_requirements=[make_ar("system_architect", "System Architect")]),
        make_gate("G7", authority_requirements=[make_ar("compliance_officer", "Compliance Officer", authority_type="independent-verifier")]),
    ]
    authorities = {
        "system_architect": make_authority(assignee="human:sa", github_login="alice"),
        "compliance_officer": make_authority(assignee="human:co", github_login="carol"),
    }
    return gates, authorities


# --------------------------------------------------------------------------
# Rendering / data minimization
# --------------------------------------------------------------------------


class RenderingTests(ReviewerNudgeTestCase):
    def test_to_request_logins_named_with_motivating_gate(self):
        gates, authorities = single_gate_with_two_reviewers()
        self.write_overlay(gates=gates, authorities=authorities)
        users, collaborators = all_collaborators_all_exist(["alice", "carol"])
        with self.frozen_time(), self.mock_env(self.base_read_mock(users=users, collaborators=collaborators), write_payload={"identity": {"login": "svc-bot"}}):
            result = self.run_nudge()
        self.assertIn("`alice`", result["body"])
        self.assertIn("`carol`", result["body"])
        self.assertIn("G3", result["body"])
        self.assertIn("G7", result["body"])
        self.assertEqual(["alice", "carol"], result["nudged_logins"])
        self.assertEqual(0, result["withheld_count"])

    def test_already_requested_omitted_entirely(self):
        gates, authorities = single_gate_with_two_reviewers()
        self.write_overlay(gates=gates, authorities=authorities)
        users, collaborators = all_collaborators_all_exist(["alice", "carol"])
        with self.frozen_time(), self.mock_env(
            self.base_read_mock(users=users, collaborators=collaborators, requested=["alice"]),
            write_payload={"identity": {"login": "svc-bot"}},
        ):
            result = self.run_nudge()
        self.assertNotIn("`alice`", result["body"])
        self.assertIn("`carol`", result["body"])
        self.assertEqual(["carol"], result["nudged_logins"])

    def test_already_reviewed_at_head_sha_omitted_entirely(self):
        gates, authorities = single_gate_with_two_reviewers()
        self.write_overlay(gates=gates, authorities=authorities)
        users, collaborators = all_collaborators_all_exist(["alice", "carol"])
        head = "a" * 40
        reviews = [{"user": {"login": "alice"}, "state": "APPROVED", "commit_id": head, "submitted_at": "2030-01-01T00:00:00Z"}]
        with self.frozen_time(), self.mock_env(
            self.base_read_mock(users=users, collaborators=collaborators, pr=default_pr(head_sha=head)),
            reviews_payload=reviews, write_payload={"identity": {"login": "svc-bot"}},
        ):
            result = self.run_nudge()
        self.assertNotIn("`alice`", result["body"])
        self.assertEqual(["carol"], result["nudged_logins"])

    def test_review_stale_named_with_label(self):
        gates, authorities = single_gate_with_two_reviewers()
        self.write_overlay(gates=gates, authorities=authorities)
        users, collaborators = all_collaborators_all_exist(["alice", "carol"])
        reviews = [{"user": {"login": "alice"}, "state": "APPROVED", "commit_id": "b" * 40, "submitted_at": "2030-01-01T00:00:00Z"}]
        with self.frozen_time(), self.mock_env(
            self.base_read_mock(users=users, collaborators=collaborators, pr=default_pr(head_sha="a" * 40)),
            reviews_payload=reviews, write_payload={"identity": {"login": "svc-bot"}},
        ):
            result = self.run_nudge()
        self.assertIn("`alice`", result["body"])
        self.assertIn("review is stale", result["body"])
        self.assertIn("alice", result["nudged_logins"])

    def test_withheld_conflict_login_never_named_only_counted(self):
        gates = [make_gate(
            "G3", authority_requirements=[make_ar("system_architect", "System Architect")],
            preparers=[{"id": "human:sa"}],
        )]
        authorities = {"system_architect": make_authority(assignee="human:sa", github_login="conflicted-reviewer")}
        self.write_overlay(gates=gates, authorities=authorities)
        with self.frozen_time(), self.mock_env(self.base_read_mock(), write_payload={"identity": {"login": "svc-bot"}}):
            result = self.run_nudge()
        self.assertNotIn("conflicted-reviewer", result["body"])
        self.assertIn("1 additional reviewer not shown due to a gate-independence conflict", result["body"])
        self.assertEqual(1, result["withheld_count"])
        self.assertEqual([], result["nudged_logins"])

    def test_withheld_count_plural(self):
        gates = [
            make_gate("G3", authority_requirements=[make_ar("a1", "A1")], preparers=[{"id": "human:x"}]),
            make_gate("G4", authority_requirements=[make_ar("a2", "A2")], preparers=[{"id": "human:y"}]),
        ]
        authorities = {
            "a1": make_authority(assignee="human:x", github_login="conflict-one"),
            "a2": make_authority(assignee="human:y", github_login="conflict-two"),
        }
        self.write_overlay(gates=gates, authorities=authorities)
        with self.frozen_time(), self.mock_env(self.base_read_mock(), write_payload={"identity": {"login": "svc-bot"}}):
            result = self.run_nudge()
        self.assertIn("2 additional reviewers not shown due to a gate-independence conflict", result["body"])
        self.assertNotIn("conflict-one", result["body"])
        self.assertNotIn("conflict-two", result["body"])

    def test_github_user_unresolved_and_not_a_collaborator_omitted(self):
        gates = [
            make_gate("G3", authority_requirements=[make_ar("ghost_role", "Ghost Role")]),
            make_gate("G4", authority_requirements=[make_ar("outsider_role", "Outsider Role")]),
        ]
        authorities = {
            "ghost_role": make_authority(assignee="human:g", github_login="ghost"),
            "outsider_role": make_authority(assignee="human:o", github_login="outsider"),
        }
        self.write_overlay(gates=gates, authorities=authorities)
        with self.frozen_time(), self.mock_env(
            self.base_read_mock(users={"ghost": False, "outsider": True}, collaborators={"owner/proj:outsider": False}),
            write_payload={"identity": {"login": "svc-bot"}},
        ):
            result = self.run_nudge()
        self.assertNotIn("ghost", result["body"])
        self.assertNotIn("outsider", result["body"])
        self.assertIn("No reviewers to nudge for this PR right now.", result["body"])
        self.assertEqual([], result["nudged_logins"])

    def test_no_reviewers_to_nudge_renders_explicit_line(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        with self.frozen_time(), self.mock_env(self.base_read_mock(), write_payload={"identity": {"login": "svc-bot"}}):
            result = self.run_nudge()
        self.assertIn("No reviewers to nudge for this PR right now.", result["body"])

    def test_pr_and_repo_and_task_hash_present_task_id_never_raw(self):
        self.write_overlay(task_id="super-secret-task-id", gates=[make_gate("G1")], authorities={})
        with self.frozen_time(), self.mock_env(self.base_read_mock(), write_payload={"identity": {"login": "svc-bot"}}):
            result = self.run_nudge(task_id="super-secret-task-id")
        self.assertIn("owner/proj#42", result["body"])
        self.assertEqual("super-secret-task-id", result["task_id"])
        self.assertNotIn("super-secret-task-id", result["body"])

    def test_marker_line_present_and_matches_domain_separated_formula(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        with self.frozen_time(), self.mock_env(self.base_read_mock(), write_payload={"identity": {"login": "svc-bot"}}):
            result = self.run_nudge()
        expected_marker = reviewer_nudge.compute_nudge_marker("T1")
        self.assertIn(f"<!-- agentic-sdlc:reviewer-nudge:v1:{expected_marker} -->", result["body"])


# --------------------------------------------------------------------------
# Advisory wording (the load-bearing copy)
# --------------------------------------------------------------------------


class AdvisoryWordingTests(ReviewerNudgeTestCase):
    def _render(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        with self.frozen_time(), self.mock_env(self.base_read_mock(), write_payload={"identity": {"login": "svc-bot"}}):
            return self.run_nudge()["body"]

    def test_states_this_is_a_suggestion_not_a_request(self):
        body = self._render()
        self.assertIn("This is a suggestion, not a review request.", body)
        self.assertIn("Not a review request.", body)

    def test_states_agentic_sdlc_has_not_requested_a_review_from_anyone(self):
        body = self._render()
        self.assertIn("`agentic-sdlc` has not requested a review from anyone", body)

    def test_states_these_people_have_not_been_notified(self):
        body = self._render()
        self.assertIn("these people have not been notified by this", body)
        self.assertIn("comment being posted", body)

    def test_states_formal_request_must_be_done_by_a_human_in_githubs_ui(self):
        body = self._render()
        self.assertIn("If you want to", body)
        self.assertIn("formally request a review, do so yourself in GitHub's UI", body)

    def test_advisory_wording_distinct_from_gate_status_paragraph(self):
        self.assertNotEqual(gate_status._ADVISORY_PARAGRAPH, reviewer_nudge._ADVISORY_PARAGRAPH)
        # Not a verbatim substring reuse of gate_status's paragraph either.
        self.assertNotIn(gate_status._ADVISORY_PARAGRAPH, reviewer_nudge._ADVISORY_PARAGRAPH)

    def test_advisory_present_even_when_no_one_to_nudge(self):
        body = self._render()
        self.assertIn("This is a suggestion, not a review request.", body)


# --------------------------------------------------------------------------
# No GitHub mention/notification surface
# --------------------------------------------------------------------------


class NoMentionSurfaceTests(ReviewerNudgeTestCase):
    def test_logins_never_rendered_as_at_mentions(self):
        gates, authorities = single_gate_with_two_reviewers()
        self.write_overlay(gates=gates, authorities=authorities)
        users, collaborators = all_collaborators_all_exist(["alice", "carol"])
        with self.frozen_time(), self.mock_env(self.base_read_mock(users=users, collaborators=collaborators), write_payload={"identity": {"login": "svc-bot"}}):
            body = self.run_nudge()["body"]
        self.assertIsNone(re.search(r"@alice\b", body))
        self.assertIsNone(re.search(r"@carol\b", body))
        self.assertIn("`alice`", body)
        self.assertIn("`carol`", body)

    def test_no_at_sign_anywhere_in_rendered_body(self):
        gates, authorities = single_gate_with_two_reviewers()
        self.write_overlay(gates=gates, authorities=authorities)
        users, collaborators = all_collaborators_all_exist(["alice", "carol"])
        with self.frozen_time(), self.mock_env(self.base_read_mock(users=users, collaborators=collaborators), write_payload={"identity": {"login": "svc-bot"}}):
            body = self.run_nudge()["body"]
        # The advisory paragraph itself talks *about* @-mentions in prose
        # using a backtick-quoted literal ("`@`-mention"), never a live
        # mention -- so this asserts no bare "@login" token exists, not a
        # blanket absence of the "@" character.
        for token in re.findall(r"@\S+", body):
            self.assertTrue(token.startswith("@`") or token in ("@`-mention", "@`-mentions"), token)


# --------------------------------------------------------------------------
# Content whitelist
# --------------------------------------------------------------------------


class ContentWhitelistTests(ReviewerNudgeTestCase):
    def _allowed_charset(self):
        import string

        allowed = set(string.ascii_letters + string.digits + string.punctuation + " \n")
        allowed |= {"—", "·"}
        return allowed

    def test_rendered_body_matches_strict_character_whitelist(self):
        gates, authorities = single_gate_with_two_reviewers()
        self.write_overlay(gates=gates, authorities=authorities)
        users, collaborators = all_collaborators_all_exist(["alice", "carol"])
        with self.frozen_time(), self.mock_env(self.base_read_mock(users=users, collaborators=collaborators), write_payload={"identity": {"login": "svc-bot"}}):
            body = self.run_nudge()["body"]
        allowed = self._allowed_charset()
        offending = sorted({ch for ch in body if ch not in allowed})
        self.assertEqual([], offending, f"body contains characters outside the fixed whitelist: {offending!r}")

    def test_free_text_role_and_rationale_never_rendered(self):
        gates = [make_gate("G3", authority_requirements=[
            make_ar("system_architect", "HOSTILE-ROLE-DO-NOT-RENDER </script><img src=x onerror=alert(1)>", rationale="HOSTILE-RATIONALE"),
        ])]
        authorities = {"system_architect": make_authority(assignee="human:sa", github_login="alice")}
        self.write_overlay(gates=gates, authorities=authorities)
        users, collaborators = all_collaborators_all_exist(["alice"])
        with self.frozen_time(), self.mock_env(self.base_read_mock(users=users, collaborators=collaborators), write_payload={"identity": {"login": "svc-bot"}}):
            body = self.run_nudge()["body"]
        self.assertNotIn("HOSTILE-ROLE", body)
        self.assertNotIn("HOSTILE-RATIONALE", body)
        self.assertNotIn("<script>", body)
        self.assertNotIn("onerror", body)

    def test_authority_type_rendered_is_closed_enum_value(self):
        gates, authorities = single_gate_with_two_reviewers()
        self.write_overlay(gates=gates, authorities=authorities)
        users, collaborators = all_collaborators_all_exist(["alice", "carol"])
        with self.frozen_time(), self.mock_env(self.base_read_mock(users=users, collaborators=collaborators), write_payload={"identity": {"login": "svc-bot"}}):
            body = self.run_nudge()["body"]
        self.assertIn("(human-approver)", body)
        self.assertIn("(independent-verifier)", body)


# --------------------------------------------------------------------------
# Marker domain separation
# --------------------------------------------------------------------------


class MarkerDomainSeparationTests(unittest.TestCase):
    def test_disjoint_from_the_other_three_marker_families(self):
        task_id = "T1"
        nudge_marker = reviewer_nudge.compute_nudge_marker(task_id)
        self.assertNotEqual(nudge_marker, gate_status.compute_status_marker(task_id))
        self.assertNotEqual(nudge_marker, gate_issues.compute_gate_marker(task_id, "G1"))
        self.assertNotEqual(nudge_marker, gate_issues.compute_approval_marker(task_id, "G1", "product_owner"))
        self.assertNotEqual(nudge_marker, gate_issues.task_hash(task_id))

    def test_marker_table_updated_in_gate_issues_docstring(self):
        source = (PLUGIN_ROOT / "agentic_sdlc" / "gate_issues.py").read_text(encoding="utf-8")
        self.assertIn("reviewer-nudge", source)
        self.assertIn("reviewer_nudge.py", source)


# --------------------------------------------------------------------------
# Idempotency / marker matching / classification (comment-write plumbing)
# --------------------------------------------------------------------------


class IdempotencyTests(ReviewerNudgeTestCase):
    def _minimal_report_env(self, write_payload):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        return self.mock_env(self.base_read_mock(), write_payload=write_payload)

    def test_create_then_unchanged_on_second_run(self):
        with self.frozen_time():
            with self._minimal_report_env({"identity": {"login": "svc-bot"}, "list": {}, "create": {}, "fetch": {}}):
                dry = self.run_nudge()
            body = dry["body"]
            with self._minimal_report_env({
                "identity": {"login": "svc-bot"}, "list": {}, "create": {"owner/proj#42": {"id": 42}},
                "fetch": {"42": {"id": 42, "body": body, "user": {"login": "svc-bot"}}},
            }):
                created = self.run_nudge(apply=True, i_know_this_is_mocked=True)
            self.assertEqual("create", created["action"])
            self.assertEqual(42, created["comment_id"])

            with self._minimal_report_env({
                "identity": {"login": "svc-bot"},
                "list": {"owner/proj#42": {"1": [{"id": 42, "body": body, "user": {"login": "svc-bot"}}]}},
                "create": {}, "fetch": {},
            }):
                unchanged = self.run_nudge(apply=True, i_know_this_is_mocked=True)
            self.assertEqual("unchanged", unchanged["action"])
            self.assertEqual(42, unchanged["comment_id"])

    def test_update_when_body_differs(self):
        marker = None
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        marker = reviewer_nudge.compute_nudge_marker("T1")
        stale_body = f"<!-- agentic-sdlc:reviewer-nudge:v1:{marker} -->\nstale content from an earlier render"
        with self.frozen_time():
            with self.mock_env(self.base_read_mock(), write_payload={
                "identity": {"login": "svc-bot"},
                "list": {"owner/proj#42": {"1": [{"id": 9, "body": stale_body, "user": {"login": "svc-bot"}}]}},
                "create": {}, "update": {"9": {}}, "fetch": {"9": None},
            }):
                dry = self.run_nudge()
            self.assertEqual("update", dry["action"])
            body = dry["body"]
            with self.mock_env(self.base_read_mock(), write_payload={
                "identity": {"login": "svc-bot"},
                "list": {"owner/proj#42": {"1": [{"id": 9, "body": stale_body, "user": {"login": "svc-bot"}}]}},
                "create": {}, "update": {"9": {}}, "fetch": {"9": {"id": 9, "body": body, "user": {"login": "svc-bot"}}},
            }):
                applied = self.run_nudge(apply=True, i_know_this_is_mocked=True)
            self.assertEqual("update", applied["action"])
            self.assertEqual(9, applied["comment_id"])

    def test_multiple_matches_blocked(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        marker = reviewer_nudge.compute_nudge_marker("T1")
        body_line = f"<!-- agentic-sdlc:reviewer-nudge:v1:{marker} -->"
        with self.frozen_time(), self.mock_env(self.base_read_mock(), write_payload={
            "identity": {"login": "svc-bot"},
            "list": {"owner/proj#42": {"1": [
                {"id": 1, "body": body_line, "user": {"login": "svc-bot"}},
                {"id": 2, "body": body_line, "user": {"login": "svc-bot"}},
            ]}},
        }):
            dry = self.run_nudge()
        self.assertEqual("blocked", dry["action"])
        self.assertEqual("multiple_matches", dry["reason"])

        with self.frozen_time(), self.mock_env(self.base_read_mock(), write_payload={
            "identity": {"login": "svc-bot"},
            "list": {"owner/proj#42": {"1": [
                {"id": 1, "body": body_line, "user": {"login": "svc-bot"}},
                {"id": 2, "body": body_line, "user": {"login": "svc-bot"}},
            ]}},
        }):
            with self.assertRaises(reviewer_nudge.ReviewerNudgeBlocked):
                self.run_nudge(apply=True, i_know_this_is_mocked=True)

    def test_foreign_author_blocked(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        marker = reviewer_nudge.compute_nudge_marker("T1")
        body_line = f"<!-- agentic-sdlc:reviewer-nudge:v1:{marker} -->"
        with self.frozen_time(), self.mock_env(self.base_read_mock(), write_payload={
            "identity": {"login": "svc-bot"},
            "list": {"owner/proj#42": {"1": [{"id": 1, "body": body_line, "user": {"login": "an-attacker"}}]}},
        }):
            dry = self.run_nudge()
        self.assertEqual("blocked", dry["action"])
        self.assertEqual("foreign_author", dry["reason"])
        with self.frozen_time(), self.mock_env(self.base_read_mock(), write_payload={
            "identity": {"login": "svc-bot"},
            "list": {"owner/proj#42": {"1": [{"id": 1, "body": body_line, "user": {"login": "an-attacker"}}]}},
        }):
            with self.assertRaises(reviewer_nudge.ReviewerNudgeBlocked):
                self.run_nudge(apply=True, i_know_this_is_mocked=True)

    def test_marker_matched_ignoring_version_segment(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        marker = reviewer_nudge.compute_nudge_marker("T1")
        old_style_body = f"<!-- agentic-sdlc:reviewer-nudge:v0:{marker} -->\nold content"
        with self.frozen_time(), self.mock_env(self.base_read_mock(), write_payload={
            "identity": {"login": "svc-bot"},
            "list": {"owner/proj#42": {"1": [{"id": 999, "body": old_style_body, "user": {"login": "svc-bot"}}]}},
        }):
            result = self.run_nudge()
        self.assertEqual("update", result["action"])
        self.assertEqual(999, result["matched_comment_id"])

    def test_page_cap_exceeded_blocks_in_both_dry_run_and_apply(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        full_page = [{"id": i, "body": "noise", "user": {"login": "someone"}} for i in range(100)]
        write_payload = {
            "identity": {"login": "svc-bot"},
            "list": {"owner/proj#42": {str(page): full_page for page in range(1, 11)}},
        }
        with self.frozen_time(), self.mock_env(self.base_read_mock(), write_payload=write_payload):
            with self.assertRaises(reviewer_nudge.ReviewerNudgeBlocked):
                self.run_nudge()
        with self.frozen_time(), self.mock_env(self.base_read_mock(), write_payload=write_payload):
            with self.assertRaises(reviewer_nudge.ReviewerNudgeBlocked):
                self.run_nudge(apply=True, i_know_this_is_mocked=True)

    def test_post_write_verification_mismatch_blocked(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        with self.frozen_time(), self.mock_env(self.base_read_mock(), write_payload={
            "identity": {"login": "svc-bot"}, "list": {}, "create": {"owner/proj#42": {"id": 42}},
            "fetch": {"42": {"id": 42, "body": "WRONG BODY", "user": {"login": "svc-bot"}}},
        }):
            with self.assertRaises(reviewer_nudge.ReviewerNudgeBlocked):
                self.run_nudge(apply=True, i_know_this_is_mocked=True)
        ledger = reviewer_nudge.read_ledger(self.root, "T1")
        self.assertEqual("suspect", ledger["entries"][-1]["status"])

    def test_lock_held_blocked_break_lock_overrides(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        held = reviewer_nudge.acquire_lock(self.root, "T1", break_lock=False)
        self.assertTrue(held.is_file())
        with self.frozen_time(), self.mock_env(self.base_read_mock(), write_payload={
            "identity": {"login": "svc-bot"}, "list": {}, "create": {"owner/proj#42": {"id": 1}}, "fetch": {"1": None},
        }):
            dry = self.run_nudge()
            body = dry["body"]
        with self.frozen_time(), self.mock_env(self.base_read_mock(), write_payload={
            "identity": {"login": "svc-bot"}, "list": {}, "create": {"owner/proj#42": {"id": 1}},
            "fetch": {"1": {"id": 1, "body": body, "user": {"login": "svc-bot"}}},
        }):
            with self.assertRaises(reviewer_nudge.ReviewerNudgeBlocked):
                self.run_nudge(apply=True, i_know_this_is_mocked=True)
            result = self.run_nudge(apply=True, i_know_this_is_mocked=True, break_lock=True)
        self.assertEqual("create", result["action"])
        self.assertFalse(held.is_file())

    def test_mock_guard_apply_without_flag_raises(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        with self.frozen_time(), self.mock_env(self.base_read_mock(), write_payload={
            "identity": {"login": "svc-bot"}, "list": {}, "create": {}, "fetch": {},
        }):
            with self.assertRaises(reviewer_nudge.ReviewerNudgeError):
                self.run_nudge(apply=True, i_know_this_is_mocked=False)


# --------------------------------------------------------------------------
# Reuse (not reimplementation) of gate_reviewers.build_plan()'s logic
# --------------------------------------------------------------------------


class ReuseTests(unittest.TestCase):
    def test_run_calls_gate_reviewers_run(self):
        source = (PLUGIN_ROOT / "agentic_sdlc" / "reviewer_nudge.py").read_text(encoding="utf-8")
        self.assertIn("gate_reviewers.run(", source)

    def test_module_does_not_redefine_eligibility_or_self_approval_or_build_plan_logic(self):
        source = (PLUGIN_ROOT / "agentic_sdlc" / "reviewer_nudge.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        defined_names = {
            node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        forbidden = {"check_gate_eligibility", "is_gate_self_approval", "build_plan", "classify_login"}
        self.assertEqual(set(), forbidden & defined_names)

    def test_module_reuses_gate_status_adapter_and_classify(self):
        source = (PLUGIN_ROOT / "agentic_sdlc" / "reviewer_nudge.py").read_text(encoding="utf-8")
        self.assertIn("gate_status.GithubForgeAdapter(", source)
        self.assertIn("gate_status.classify(", source)


# --------------------------------------------------------------------------
# Orthogonality
# --------------------------------------------------------------------------


class OrthogonalityTests(ReviewerNudgeTestCase):
    def test_run_record_dispatch_plan_authorities_byte_identical_after_apply(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        record_path = self.overlay / "runs" / "T1" / "run-record.json"
        dispatch_path = self.overlay / "runs" / "T1" / "dispatch-plan.json"
        authorities_path = self.overlay / "authorities.json"
        before = {p: p.read_bytes() for p in (record_path, dispatch_path, authorities_path)}
        with self.frozen_time():
            with self.mock_env(self.base_read_mock(), write_payload={"identity": {"login": "svc-bot"}, "list": {}, "create": {}, "fetch": {}}):
                dry = self.run_nudge()
            body = dry["body"]
            with self.mock_env(self.base_read_mock(), write_payload={
                "identity": {"login": "svc-bot"}, "list": {}, "create": {"owner/proj#42": {"id": 1}},
                "fetch": {"1": {"id": 1, "body": body, "user": {"login": "svc-bot"}}},
            }):
                self.run_nudge(apply=True, i_know_this_is_mocked=True)
        for path, content in before.items():
            self.assertEqual(content, path.read_bytes(), f"{path} was modified by publish-reviewer-nudge")

    def test_module_never_imports_approval_or_issue_write_adapters(self):
        source = (PLUGIN_ROOT / "agentic_sdlc" / "reviewer_nudge.py").read_text(encoding="utf-8")
        import_lines = [
            line for line in source.splitlines()
            if line.startswith("from . import") or line.startswith("import ")
        ]
        forbidden = {
            "record_github_approval", "record_gitlab_approval", "record_gate_decision", "record_gitlab_issue_link",
            "create_gitlab_issue", "gitlab_write",
        }
        imported_names = set()
        for line in import_lines:
            imported_names.update(name.strip() for name in line.split("import", 1)[1].split(","))
        self.assertEqual(set(), forbidden & imported_names)

    def test_module_never_writes_run_record_schema_file(self):
        # Strip the module docstring (which legitimately *names*
        # "run-record.schema.json" in prose, explaining the orthogonality
        # this test proves structurally) before searching -- mirrors
        # test_gate_status.py's OrthogonalityTests.
        source = (PLUGIN_ROOT / "agentic_sdlc" / "reviewer_nudge.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        docstring_node = module.body[0]
        assert isinstance(docstring_node, ast.Expr) and isinstance(docstring_node.value, ast.Constant)
        lines = source.splitlines(keepends=True)
        code_only = "".join(lines[docstring_node.end_lineno:])
        self.assertNotIn("run-record.schema.json", code_only)


# --------------------------------------------------------------------------
# CLI wiring
# --------------------------------------------------------------------------


class CliWiringTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.overlay = self.root / ".agentic-sdlc"
        (self.overlay / "runs" / "T1").mkdir(parents=True)
        (self.overlay / "project.json").write_text(json.dumps({"classification": "internal"}), encoding="utf-8")
        (self.overlay / "authorities.json").write_text(json.dumps({}), encoding="utf-8")
        record = {
            "classification": "internal", "disposition": "pending", "scope": "s", "re_entry_history": [],
            "lifecycle_gates": [make_gate("G1")],
        }
        (self.overlay / "runs" / "T1" / "run-record.json").write_text(json.dumps(record), encoding="utf-8")
        dispatch = {
            "dispatch_fingerprint": "sha256:" + "a" * 64,
            "gate_dispatch": [{"gate_id": "G1", "status": "required"}],
        }
        (self.overlay / "runs" / "T1" / "dispatch-plan.json").write_text(json.dumps(dispatch), encoding="utf-8")
        self.addCleanup(self.temporary.cleanup)

    def run_cli(self, *arguments, expected=0, env=None):
        result = subprocess.run(
            CLI_COMMAND + list(arguments) + ["--root", str(self.root)],
            text=True, capture_output=True, check=False, env={**os.environ, **(env or {})},
        )
        self.assertEqual(expected, result.returncode, result.stderr or result.stdout)
        stdout = result.stdout or result.stderr
        return json.loads(stdout) if stdout.strip() else {}

    def _read_mock_env(self):
        read_path = self.root / "gh-read.json"
        read_path.write_text(json.dumps({
            "identity": {"login": "svc-bot"}, "pr": default_pr(), "requested_reviewers": {"users": [], "teams": []},
            "users": {}, "collaborators": {},
        }), encoding="utf-8")
        reviews_path = self.root / "reviews.json"
        reviews_path.write_text(json.dumps([]), encoding="utf-8")
        return {
            github_write.GITHUB_READ_MOCK_ENV_VAR: str(read_path),
            "AGENTIC_SDLC_TEST_GITHUB_REVIEWS_FILE": str(reviews_path),
        }

    def test_missing_classification_is_exit_1(self):
        env = self._read_mock_env()
        self.run_cli(
            "publish-reviewer-nudge", "--task-id", "T1", "--repo", "owner/proj", "--pr", "42", "--as-bot", "svc-bot",
            env=env, expected=1,
        )

    def test_dry_run_via_cli_subprocess(self):
        env = self._read_mock_env()
        write_path = self.root / "gh-write.json"
        write_path.write_text(json.dumps({"identity": {"login": "svc-bot"}, "list": {}, "create": {}, "fetch": {}}), encoding="utf-8")
        env[github_status_write.GITHUB_WRITE_MOCK_ENV_VAR] = str(write_path)
        dry = self.run_cli(
            "publish-reviewer-nudge", "--task-id", "T1", "--repo", "owner/proj", "--pr", "42", "--as-bot", "svc-bot",
            "--allow-classification", "internal", "--dry-run", env=env,
        )
        self.assertEqual("create", dry["action"])
        self.assertIn("This is a suggestion, not a review request.", dry["body"])

    def test_mock_guard_without_i_know_this_is_mocked_is_exit_1(self):
        env = self._read_mock_env()
        write_path = self.root / "gh-write.json"
        write_path.write_text(json.dumps({"identity": {"login": "svc-bot"}, "list": {}, "create": {}, "fetch": {}}), encoding="utf-8")
        env[github_status_write.GITHUB_WRITE_MOCK_ENV_VAR] = str(write_path)
        self.run_cli(
            "publish-reviewer-nudge", "--task-id", "T1", "--repo", "owner/proj", "--pr", "42", "--as-bot", "svc-bot",
            "--allow-classification", "internal", "--apply", env=env, expected=1,
        )

    def test_lock_held_via_cli_is_exit_2(self):
        from agentic_sdlc import reviewer_nudge as rn
        rn.acquire_lock(self.root, "T1", break_lock=False)
        env = self._read_mock_env()
        write_path = self.root / "gh-write.json"
        write_path.write_text(json.dumps({"identity": {"login": "svc-bot"}, "list": {}, "create": {}, "fetch": {}}), encoding="utf-8")
        env[github_status_write.GITHUB_WRITE_MOCK_ENV_VAR] = str(write_path)
        self.run_cli(
            "publish-reviewer-nudge", "--task-id", "T1", "--repo", "owner/proj", "--pr", "42", "--as-bot", "svc-bot",
            "--allow-classification", "internal", "--apply", "--i-know-this-is-mocked", env=env, expected=2,
        )

    def test_apply_and_list_reviewer_nudge_via_cli_in_process(self):
        from agentic_sdlc import reviewer_nudge as rn

        env_vars = self._read_mock_env()
        write_path = self.root / "gh-write.json"
        write_path.write_text(json.dumps({"identity": {"login": "svc-bot"}, "list": {}, "create": {}, "fetch": {}}), encoding="utf-8")

        def call_cli(*args):
            buffer = []
            with mock.patch("builtins.print", side_effect=lambda *a, **k: buffer.append(a[0] if a else "")):
                exit_code = agentic_sdlc.main(list(args) + ["--root", str(self.root)])
            return exit_code, (json.loads(buffer[0]) if buffer else {})

        with mock.patch.object(rn, "now", return_value=FIXED_TIME):
            with mock.patch.dict(os.environ, {**env_vars, github_status_write.GITHUB_WRITE_MOCK_ENV_VAR: str(write_path)}):
                exit_code, dry = call_cli(
                    "publish-reviewer-nudge", "--task-id", "T1", "--repo", "owner/proj", "--pr", "42",
                    "--as-bot", "svc-bot", "--allow-classification", "internal", "--dry-run",
                )
                self.assertEqual(0, exit_code)
                self.assertEqual("create", dry["action"])

                write_path.write_text(json.dumps({
                    "identity": {"login": "svc-bot"}, "list": {}, "create": {"owner/proj#42": {"id": 5}},
                    "fetch": {"5": {"id": 5, "body": dry["body"], "user": {"login": "svc-bot"}}},
                }), encoding="utf-8")
                exit_code, applied = call_cli(
                    "publish-reviewer-nudge", "--task-id", "T1", "--repo", "owner/proj", "--pr", "42",
                    "--as-bot", "svc-bot", "--allow-classification", "internal", "--apply", "--i-know-this-is-mocked",
                )
                self.assertEqual(0, exit_code)
                self.assertEqual(5, applied["comment_id"])

                exit_code, listed = call_cli("list-reviewer-nudge", "--task-id", "T1")
                self.assertEqual(0, exit_code)
                self.assertEqual("github", listed["forge"])
                self.assertEqual(1, len(listed["entries"]))


if __name__ == "__main__":
    unittest.main()
