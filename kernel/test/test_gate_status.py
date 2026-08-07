"""Tests for `publish-gate-status` / `list-gate-status`
(`agentic_sdlc/gate_status.py`, `agentic_sdlc/github_status_write.py`,
`agentic_sdlc/gitlab_write.py`'s MR-notes extension), plus the
`gate_status_projection()` / `status()` refactor in `agentic_sdlc/__init__.py`.

No `gh`/`glab` binary or network access is required -- every forge call is
mocked via `AGENTIC_SDLC_TEST_GITHUB_WRITE_FILE` (github_status_write.py) or
`AGENTIC_SDLC_TEST_ISSUE_CREATE_FILE` (gitlab_write.py, reused).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

import agentic_sdlc  # type: ignore
from agentic_sdlc import gate_status, gate_issues, github_status_write, gitlab_write  # type: ignore

CLI_COMMAND = [sys.executable, str(PLUGIN_ROOT / "dev_entrypoint.py")]

FIXED_TIME = "2030-01-01T00:00:00.000000Z"


# --------------------------------------------------------------------------
# Fixture builders
# --------------------------------------------------------------------------


def make_gate(gate_id, *, applicability="applicable", status="pending", required_reentry_gate=None):
    return {
        "gate_id": gate_id,
        "applicability": applicability,
        "applicability_rationale": "Lifecycle gate applies by default -- HOSTILE </table> <script>alert(1)</script>",
        "status": status,
        "required_reentry_gate": required_reentry_gate,
        "authority_requirements": [],
        "preparers": [],
        "independent_verifier": None,
        "findings": [{"id": "F1", "detail": "HOSTILE-FINDING-DO-NOT-RENDER @evil #999"}],
        "evidence_refs": [{"uri": "doc:HOSTILE-EVIDENCE-DO-NOT-RENDER"}],
    }


def make_full_gates(overrides: dict | None = None):
    overrides = overrides or {}
    gates = []
    for index in range(1, 11):
        gate_id = f"G{index}"
        kwargs = overrides.get(gate_id, {})
        gates.append(make_gate(gate_id, **kwargs))
    return gates


class GateStatusTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.overlay = self.root / ".agentic-sdlc"
        (self.overlay / "runs" / "T1").mkdir(parents=True)
        self.addCleanup(self.temporary.cleanup)

    def write_overlay(
        self, *, task_id="T1", classification="internal", gates=None, re_entry_history=None, scope="HOSTILE-SCOPE-DO-NOT-RENDER",
    ):
        gates = gates if gates is not None else make_full_gates()
        (self.overlay / "project.json").write_text(json.dumps({"classification": classification}), encoding="utf-8")
        (self.overlay / "authorities.json").write_text(json.dumps({}), encoding="utf-8")
        (self.overlay / "impact-profile.json").write_text(json.dumps({}), encoding="utf-8")
        (self.overlay / "routing.json").write_text(json.dumps({}), encoding="utf-8")
        (self.overlay / "runs" / task_id).mkdir(parents=True, exist_ok=True)
        record = {
            "classification": classification,
            "disposition": "pending",
            "scope": scope,
            "re_entry_history": re_entry_history or [],
            "lifecycle_gates": gates,
            "current_lifecycle_phase": "intent",
        }
        (self.overlay / "runs" / task_id / "run-record.json").write_text(json.dumps(record), encoding="utf-8")

    def github_mock_env(self, payload):
        path = self.root / "github-mock.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return mock.patch.dict(os.environ, {github_status_write.GITHUB_WRITE_MOCK_ENV_VAR: str(path)})

    def gitlab_mock_env(self, payload):
        path = self.root / "gitlab-mock.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return mock.patch.dict(os.environ, {gitlab_write.ISSUE_CREATE_MOCK_ENV_VAR: str(path)})

    def frozen_time(self):
        return mock.patch.object(gate_status, "now", return_value=FIXED_TIME)

    def run_github(self, **kwargs):
        kwargs.setdefault("root", self.root)
        kwargs.setdefault("task_id", "T1")
        kwargs.setdefault("forge", "github")
        kwargs.setdefault("repo", "o/r")
        kwargs.setdefault("pr", 1)
        kwargs.setdefault("as_bot", "svc-bot")
        kwargs.setdefault("allow_classification", "internal")
        kwargs.setdefault("apply", False)
        return gate_status.run(**kwargs)

    def run_gitlab(self, **kwargs):
        kwargs.setdefault("root", self.root)
        kwargs.setdefault("task_id", "T1")
        kwargs.setdefault("forge", "gitlab")
        kwargs.setdefault("project_path", "grp/proj")
        kwargs.setdefault("mr_iid", 7)
        kwargs.setdefault("as_bot", "svc-bot")
        kwargs.setdefault("allow_classification", "internal")
        kwargs.setdefault("apply", False)
        return gate_status.run(**kwargs)


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


class RenderingTests(GateStatusTestCase):
    def test_all_ten_gates_rendered_in_order(self):
        self.write_overlay()
        with self.frozen_time(), self.github_mock_env({"identity": {"login": "svc-bot"}}):
            result = self.run_github()
        body = result["body"]
        for index in range(1, 11):
            self.assertIn(f"| G{index} ", body)
        self.assertLess(body.index("| G1 "), body.index("| G10 "))

    def test_not_applicable_overrides_status_cell(self):
        gates = make_full_gates({"G3": {"applicability": "not-applicable"}})
        self.write_overlay(gates=gates)
        with self.frozen_time(), self.github_mock_env({"identity": {"login": "svc-bot"}}):
            result = self.run_github()
        self.assertIn("| G3 Architecture | not applicable |", result["body"])

    def test_required_reentry_gate_renders_invalidated_with_pointer(self):
        gates = make_full_gates({"G4": {"status": "invalidated", "required_reentry_gate": "G2"}})
        self.write_overlay(gates=gates)
        with self.frozen_time(), self.github_mock_env({"identity": {"login": "svc-bot"}}):
            result = self.run_github()
        self.assertIn("| G4 Governance and Data | invalidated (re-entry required from G2) |", result["body"])

    def test_g9_human_only_suffix_present_until_approved(self):
        self.write_overlay()
        with self.frozen_time(), self.github_mock_env({"identity": {"login": "svc-bot"}}):
            result = self.run_github()
        self.assertIn("| G9 Deployment Authorization | pending (human-only gate) |", result["body"])

        gates = make_full_gates({"G9": {"status": "approved"}})
        self.write_overlay(gates=gates)
        with self.frozen_time(), self.github_mock_env({"identity": {"login": "svc-bot"}}):
            result2 = self.run_github()
        self.assertIn("| G9 Deployment Authorization | approved |", result2["body"])
        self.assertNotIn("human-only gate", result2["body"].split("G9")[1].split("\n")[0])

    def test_reentry_summary_present_when_history_nonempty_and_omitted_when_empty(self):
        self.write_overlay(re_entry_history=[])
        with self.frozen_time(), self.github_mock_env({"identity": {"login": "svc-bot"}}):
            empty_result = self.run_github()
        self.assertNotIn("Re-entries recorded", empty_result["body"])

        history = [
            {"earliest_gate": "G4", "actor": "HOSTILE-ACTOR-DO-NOT-RENDER", "reason": "HOSTILE-REASON-DO-NOT-RENDER"},
            {"earliest_gate": "G2", "actor": "someone-else", "reason": "another reason"},
        ]
        self.write_overlay(re_entry_history=history)
        with self.frozen_time(), self.github_mock_env({"identity": {"login": "svc-bot"}}):
            result = self.run_github()
        self.assertIn("Re-entries recorded: 2 (earliest re-entered gate: G2)", result["body"])
        self.assertNotIn("HOSTILE-ACTOR", result["body"])
        self.assertNotIn("HOSTILE-REASON", result["body"])
        self.assertNotIn("someone-else", result["body"])
        self.assertNotIn("another reason", result["body"])

    def test_marker_line_present_and_matches_domain_separated_formula(self):
        self.write_overlay()
        with self.frozen_time(), self.github_mock_env({"identity": {"login": "svc-bot"}}):
            result = self.run_github()
        expected_marker = gate_status.compute_status_marker("T1")
        self.assertIn(f"<!-- agentic-sdlc:gate-status:v1:{expected_marker} -->", result["body"])
        # Domain-separated from gate_issues.py's own markers for the same task_id.
        self.assertNotEqual(expected_marker, gate_issues.compute_gate_marker("T1", "G1"))
        self.assertNotEqual(expected_marker, gate_issues.task_hash("T1"))

    def test_raw_task_id_never_rendered_in_the_comment_body(self):
        """The raw `task_id` legitimately appears in `run()`'s local CLI
        result dict (`result["task_id"]`, for operator convenience -- the
        caller already supplied `--task-id`) but must NEVER appear in
        `result["body"]`, the text actually posted to the PR/MR: only its
        `gate_issues.task_hash()` hash may appear there (see the module
        docstring's "Marker and matching" section)."""
        self.write_overlay(task_id="super-secret-task-id")
        with self.frozen_time(), self.github_mock_env({"identity": {"login": "svc-bot"}}):
            result = self.run_github(task_id="super-secret-task-id")
        self.assertEqual("super-secret-task-id", result["task_id"])  # expected, local-only
        self.assertNotIn("super-secret-task-id", result["body"])  # never in the posted text


# --------------------------------------------------------------------------
# Content whitelist / hostile-fixture exclusion (no injection surface)
# --------------------------------------------------------------------------


class ContentWhitelistTests(GateStatusTestCase):
    def _allowed_charset(self) -> set[str]:
        import string

        allowed = set(string.ascii_letters + string.digits + string.punctuation + " \n")
        allowed |= {"—", "·"}  # em dash, middle dot -- the only non-ASCII fixed-template characters
        return allowed

    def test_rendered_body_matches_strict_character_whitelist(self):
        history = [{"earliest_gate": "G2", "actor": "x", "reason": "y"}]
        self.write_overlay(re_entry_history=history)
        with self.frozen_time(), self.github_mock_env({"identity": {"login": "svc-bot"}}):
            result = self.run_github()
        allowed = self._allowed_charset()
        offending = sorted({ch for ch in result["body"] if ch not in allowed})
        self.assertEqual([], offending, f"body contains characters outside the fixed whitelist: {offending!r}")

    def test_hostile_run_record_fields_never_appear_in_rendered_body(self):
        self.write_overlay(scope="HOSTILE-SCOPE </script><img src=x onerror=alert(1)>")
        with self.frozen_time(), self.github_mock_env({"identity": {"login": "svc-bot"}}):
            result = self.run_github()
        forbidden_substrings = [
            "HOSTILE-SCOPE", "HOSTILE </table>", "<script>", "HOSTILE-FINDING", "HOSTILE-EVIDENCE",
            "onerror", "<img",
        ]
        for substring in forbidden_substrings:
            self.assertNotIn(substring, result["body"])

    def test_gate_status_projection_output_excludes_disallowed_fields(self):
        self.write_overlay()
        projection = agentic_sdlc.gate_status_projection(self.root, "T1")
        serialized = json.dumps(projection)
        self.assertNotIn("HOSTILE", serialized)
        self.assertNotIn("evidence_refs", serialized)
        self.assertNotIn("findings", serialized)
        self.assertNotIn("applicability_rationale", serialized)
        self.assertNotIn("scope", serialized)


# --------------------------------------------------------------------------
# Idempotency / marker matching / classification
# --------------------------------------------------------------------------


class IdempotencyTests(GateStatusTestCase):
    def test_create_then_unchanged_on_second_run(self):
        self.write_overlay()
        with self.frozen_time():
            with self.github_mock_env({"identity": {"login": "svc-bot"}, "list": {}, "create": {}, "fetch": {}}):
                dry = self.run_github()
            body = dry["body"]
            with self.github_mock_env({
                "identity": {"login": "svc-bot"}, "list": {}, "create": {"o/r#1": {"id": 42}},
                "fetch": {"42": {"id": 42, "body": body, "user": {"login": "svc-bot"}}},
            }):
                created = self.run_github(apply=True, i_know_this_is_mocked=True)
            self.assertEqual("create", created["action"])
            self.assertEqual(42, created["comment_id"])

            with self.github_mock_env({
                "identity": {"login": "svc-bot"},
                "list": {"o/r#1": {"1": [{"id": 42, "body": body, "user": {"login": "svc-bot"}}]}},
                "create": {}, "fetch": {},
            }):
                unchanged = self.run_github(apply=True, i_know_this_is_mocked=True)
            self.assertEqual("unchanged", unchanged["action"])
            self.assertEqual(42, unchanged["comment_id"])

    def test_unchanged_across_two_real_runs_with_different_rendered_at_timestamps(self):
        """Regression test for the bug where classify() compared the full
        rendered body byte-for-byte, including the live `rendered_at`
        timestamp embedded by render_gate_status_body() on every call. Two
        real, separate CLI invocations always have different timestamps, so
        that byte-equality check made "unchanged" unreachable in real usage
        -- every re-run classified as "update" and (once applied) rewrote
        the comment, even when gate state was identical. Every other
        "unchanged"-detection test in this class wraps all its calls in a
        single frozen_time() context, which coincidentally makes the
        timestamps identical across calls and masks this bug entirely; this
        test deliberately uses two genuinely different timestamps across two
        separate run() invocations to actually exercise the fix."""
        self.write_overlay()
        t1 = "2030-01-01T00:00:00.000000Z"
        t2 = "2030-06-01T00:00:00.000000Z"
        # now() is called once for `rendered_at` on every run(), plus once
        # more per apply run for the ledger's `recorded_at` -- dry run (1
        # call) + apply/create (2 calls: rendered_at, ledger) + apply/second
        # run (2 calls: rendered_at, ledger) = 5 calls total. The dry run and
        # the create-apply share t1 so the body posted matches the body the
        # dry run computed (mirroring how the mocked fetch response is
        # wired below); the second real invocation gets a genuinely
        # different rendered_at (t2), which is exactly what a real re-run
        # produces and what the original bug failed to tolerate.
        with mock.patch.object(gate_status, "now", side_effect=[t1, t1, t1, t2, t2]):
            with self.github_mock_env({"identity": {"login": "svc-bot"}, "list": {}, "create": {}, "fetch": {}}):
                dry = self.run_github()
            first_body = dry["body"]
            with self.github_mock_env({
                "identity": {"login": "svc-bot"}, "list": {}, "create": {"o/r#1": {"id": 42}},
                "fetch": {"42": {"id": 42, "body": first_body, "user": {"login": "svc-bot"}}},
            }):
                created = self.run_github(apply=True, i_know_this_is_mocked=True)
            self.assertEqual("create", created["action"])

            # Second, genuinely later invocation: identical gate state, but
            # now() returns a different timestamp than the one baked into
            # the comment already posted above.
            with self.github_mock_env({
                "identity": {"login": "svc-bot"},
                "list": {"o/r#1": {"1": [{"id": 42, "body": first_body, "user": {"login": "svc-bot"}}]}},
                "create": {}, "fetch": {},
            }):
                second = self.run_github(apply=True, i_know_this_is_mocked=True)
        self.assertNotEqual(first_body, second["body"])  # sanity: the timestamp really did change
        self.assertEqual("unchanged", second["action"])
        self.assertEqual(42, second["comment_id"])

    def test_update_when_body_differs(self):
        self.write_overlay()
        marker = gate_status.compute_status_marker("T1")
        # Must carry the real marker (so it is found as a match) but a
        # different rest-of-body (so classification is "update", not
        # "unchanged") -- e.g. a stale rendered-at timestamp/status table.
        stale_body = f"<!-- agentic-sdlc:gate-status:v1:{marker} -->\nstale content from an earlier render"
        with self.frozen_time():
            with self.github_mock_env({
                "identity": {"login": "svc-bot"},
                "list": {"o/r#1": {"1": [{"id": 9, "body": stale_body, "user": {"login": "svc-bot"}}]}},
                "create": {}, "update": {"9": {}},
                "fetch": {"9": None},
            }):
                dry = self.run_github()
            self.assertEqual("update", dry["action"])
            self.assertEqual(9, dry["matched_comment_id"])
            body = dry["body"]
            with self.github_mock_env({
                "identity": {"login": "svc-bot"},
                "list": {"o/r#1": {"1": [{"id": 9, "body": stale_body, "user": {"login": "svc-bot"}}]}},
                "create": {}, "update": {"9": {}},
                "fetch": {"9": {"id": 9, "body": body, "user": {"login": "svc-bot"}}},
            }):
                applied = self.run_github(apply=True, i_know_this_is_mocked=True)
            self.assertEqual("update", applied["action"])
            self.assertEqual(9, applied["comment_id"])

    def test_marker_matched_across_paginated_comments_ignoring_version_segment(self):
        self.write_overlay()
        marker = gate_status.compute_status_marker("T1")
        # A "v0" (older/different version) comment with the same marker
        # must still be found and matched -- matching is on the marker
        # token only, never the version segment.
        old_style_body = f"<!-- agentic-sdlc:gate-status:v0:{marker} -->\nold content"
        page1 = [{"id": i, "body": "noise", "user": {"login": "someone"}} for i in range(99)]
        page1.append({"id": 999, "body": old_style_body, "user": {"login": "svc-bot"}})
        with self.frozen_time(), self.github_mock_env({
            "identity": {"login": "svc-bot"}, "list": {"o/r#1": {"1": page1, "2": []}},
        }):
            result = self.run_github()
        self.assertEqual("update", result["action"])
        self.assertEqual(999, result["matched_comment_id"])

    def test_multiple_matches_blocked(self):
        self.write_overlay()
        marker = gate_status.compute_status_marker("T1")
        body_line = f"<!-- agentic-sdlc:gate-status:v1:{marker} -->"
        with self.frozen_time(), self.github_mock_env({
            "identity": {"login": "svc-bot"},
            "list": {"o/r#1": {"1": [
                {"id": 1, "body": body_line, "user": {"login": "svc-bot"}},
                {"id": 2, "body": body_line, "user": {"login": "svc-bot"}},
            ]}},
        }):
            dry = self.run_github()
        self.assertEqual("blocked", dry["action"])
        self.assertEqual("multiple_matches", dry["reason"])
        # Dry-run reports "blocked" without raising.

        with self.frozen_time(), self.github_mock_env({
            "identity": {"login": "svc-bot"},
            "list": {"o/r#1": {"1": [
                {"id": 1, "body": body_line, "user": {"login": "svc-bot"}},
                {"id": 2, "body": body_line, "user": {"login": "svc-bot"}},
            ]}},
        }):
            with self.assertRaises(gate_status.GateStatusBlocked):
                self.run_github(apply=True, i_know_this_is_mocked=True)

    def test_foreign_author_blocked(self):
        self.write_overlay()
        marker = gate_status.compute_status_marker("T1")
        body_line = f"<!-- agentic-sdlc:gate-status:v1:{marker} -->"
        with self.frozen_time(), self.github_mock_env({
            "identity": {"login": "svc-bot"},
            "list": {"o/r#1": {"1": [{"id": 1, "body": body_line, "user": {"login": "an-attacker"}}]}},
        }):
            dry = self.run_github()
        self.assertEqual("blocked", dry["action"])
        self.assertEqual("foreign_author", dry["reason"])

        with self.frozen_time(), self.github_mock_env({
            "identity": {"login": "svc-bot"},
            "list": {"o/r#1": {"1": [{"id": 1, "body": body_line, "user": {"login": "an-attacker"}}]}},
        }):
            with self.assertRaises(gate_status.GateStatusBlocked):
                self.run_github(apply=True, i_know_this_is_mocked=True)

    def test_system_notes_excluded_from_matching_gitlab(self):
        self.write_overlay()
        marker = gate_status.compute_status_marker("T1")
        body_line = f"<!-- agentic-sdlc:gate-status:v1:{marker} -->"
        with self.frozen_time(), self.gitlab_mock_env({
            "identity": {"username": "svc-bot"},
            "notes_list": {"grp/proj:7": {"1": [
                {"id": 1, "body": body_line, "author": {"username": "svc-bot"}, "system": True},
            ]}},
        }):
            result = self.run_gitlab()
        self.assertEqual("create", result["action"])  # the system note is excluded, so treated as no match

    def test_page_cap_exceeded_blocks_in_both_dry_run_and_apply(self):
        self.write_overlay()
        full_page = [{"id": i, "body": "noise", "user": {"login": "someone"}} for i in range(100)]
        mock_payload = {
            "identity": {"login": "svc-bot"},
            "list": {"o/r#1": {str(page): full_page for page in range(1, 11)}},
        }
        with self.frozen_time(), self.github_mock_env(mock_payload):
            with self.assertRaises(gate_status.GateStatusBlocked):
                self.run_github()  # dry-run also raises: cannot safely determine the classification
        with self.frozen_time(), self.github_mock_env(mock_payload):
            with self.assertRaises(gate_status.GateStatusBlocked):
                self.run_github(apply=True, i_know_this_is_mocked=True)

    def test_post_write_verification_mismatch_blocked(self):
        self.write_overlay()
        with self.frozen_time(), self.github_mock_env({
            "identity": {"login": "svc-bot"}, "list": {}, "create": {"o/r#1": {"id": 42}},
            "fetch": {"42": {"id": 42, "body": "WRONG BODY", "user": {"login": "svc-bot"}}},
        }):
            with self.assertRaises(gate_status.GateStatusBlocked):
                self.run_github(apply=True, i_know_this_is_mocked=True)
        ledger = gate_status.read_ledger(self.root, "T1", "github")
        self.assertEqual("suspect", ledger["entries"][-1]["status"])

    def test_lock_held_blocked_break_lock_overrides(self):
        self.write_overlay()
        held = gate_status.acquire_lock(self.root, "T1", "github", break_lock=False)
        self.assertTrue(held.is_file())
        with self.frozen_time(), self.github_mock_env({
            "identity": {"login": "svc-bot"}, "list": {}, "create": {"o/r#1": {"id": 1}},
            "fetch": {"1": None},
        }) as _:
            dry = self.run_github()
            body = dry["body"]
        with self.frozen_time(), self.github_mock_env({
            "identity": {"login": "svc-bot"}, "list": {}, "create": {"o/r#1": {"id": 1}},
            "fetch": {"1": {"id": 1, "body": body, "user": {"login": "svc-bot"}}},
        }):
            with self.assertRaises(gate_status.GateStatusBlocked):
                self.run_github(apply=True, i_know_this_is_mocked=True)
            result = self.run_github(apply=True, i_know_this_is_mocked=True, break_lock=True)
        self.assertEqual("create", result["action"])
        self.assertFalse(held.is_file())


# --------------------------------------------------------------------------
# No reactions/awards surface
# --------------------------------------------------------------------------


class NoReactionSurfaceTests(GateStatusTestCase):
    def test_parsed_comment_never_carries_reactions_or_award_fields(self):
        """`_parse_github_comment`/`_parse_gitlab_note` extract exactly
        `{id, body, author, is_system}` -- this is a structural check on the
        parsed representation, not a substring check on the whole rendered
        body: the advisory paragraph's fixed template text legitimately
        contains the English word "reactions" in prose (warning readers that
        reacting to the comment does not approve anything), so a blanket
        substring check on the full result (including `body`) would be a
        false positive against that intentional, fixed, non-hostile text."""
        raw_github = {
            "id": 1, "body": "x", "user": {"login": "svc-bot"},
            "reactions": {"+1": 5, "url": "https://example.com"},
        }
        parsed_github = gate_status._parse_github_comment(raw_github)
        self.assertEqual({"id", "body", "author", "is_system"}, set(parsed_github.keys()))

        raw_gitlab = {
            "id": 1, "body": "x", "author": {"username": "svc-bot"}, "system": False,
            "award_emoji": [{"name": "thumbsup"}],
        }
        parsed_gitlab = gate_status._parse_gitlab_note(raw_gitlab)
        self.assertEqual({"id", "body", "author", "is_system"}, set(parsed_gitlab.keys()))

    def test_hostile_reaction_and_award_fields_never_reach_ledger_or_matched_comment_id(self):
        self.write_overlay()
        marker = gate_status.compute_status_marker("T1")
        body_line = f"<!-- agentic-sdlc:gate-status:v1:{marker} -->"
        hostile_comment = {
            "id": 1, "body": body_line, "user": {"login": "svc-bot"},
            "reactions": {"+1": 5, "url": "https://example.com"}, "award_emoji": [{"name": "thumbsup"}],
        }
        with self.frozen_time(), self.github_mock_env({
            "identity": {"login": "svc-bot"}, "list": {"o/r#1": {"1": [hostile_comment]}},
        }):
            result = self.run_github()
        # Only the closed, structural result fields are present -- no raw
        # comment payload (and therefore no reactions/award_emoji) is ever
        # echoed back.
        self.assertEqual(1, result["matched_comment_id"])
        self.assertEqual(
            {"mode", "task_id", "task_hash", "forge", "marker", "action", "reason", "matched_comment_id", "mocked", "body"},
            set(result.keys()),
        )
        ledger = gate_status.read_ledger(self.root, "T1", "github")
        self.assertNotIn("reaction", json.dumps(ledger).lower())
        self.assertNotIn("award", json.dumps(ledger).lower())


# --------------------------------------------------------------------------
# Orthogonality
# --------------------------------------------------------------------------


class OrthogonalityTests(GateStatusTestCase):
    def test_input_files_byte_identical_after_full_apply_run(self):
        self.write_overlay()
        record_path = self.overlay / "runs" / "T1" / "run-record.json"
        authorities_path = self.overlay / "authorities.json"
        before = {p: p.read_bytes() for p in (record_path, authorities_path)}
        with self.frozen_time():
            with self.github_mock_env({"identity": {"login": "svc-bot"}, "list": {}, "create": {}, "fetch": {}}):
                dry = self.run_github()
            body = dry["body"]
            with self.github_mock_env({
                "identity": {"login": "svc-bot"}, "list": {}, "create": {"o/r#1": {"id": 1}},
                "fetch": {"1": {"id": 1, "body": body, "user": {"login": "svc-bot"}}},
            }):
                self.run_github(apply=True, i_know_this_is_mocked=True)
        for path, content in before.items():
            self.assertEqual(content, path.read_bytes(), f"{path} was modified by publish-gate-status")

    def test_module_never_imports_approval_adapters_or_gate_issues_writers(self):
        source = (PLUGIN_ROOT / "agentic_sdlc" / "gate_status.py").read_text(encoding="utf-8")
        import_lines = [
            line for line in source.splitlines()
            if line.startswith("from . import") or line.startswith("import ")
        ]
        forbidden = {
            "record_github_approval", "record_gitlab_approval", "record_gate_decision", "record_gitlab_issue_link",
        }
        imported_names = set()
        for line in import_lines:
            imported_names.update(name.strip() for name in line.split("import", 1)[1].split(","))
        self.assertEqual(set(), forbidden & imported_names)

    def test_module_never_opens_authorities_json(self):
        # Strip the module docstring (which legitimately *names*
        # "authorities.json" in prose, explaining the orthogonality this
        # test proves structurally) before searching -- mirrors
        # test_gate_issues.py's OrthogonalityTests, which likewise only
        # inspects executable `from . import` lines, not docstring prose.
        import ast

        source = (PLUGIN_ROOT / "agentic_sdlc" / "gate_status.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        docstring_node = module.body[0]
        assert isinstance(docstring_node, ast.Expr) and isinstance(docstring_node.value, ast.Constant)
        lines = source.splitlines(keepends=True)
        code_only = "".join(lines[docstring_node.end_lineno:])
        self.assertNotIn("authorities.json", code_only)

    def test_gate_status_projection_never_writes(self):
        self.write_overlay()
        record_path = self.overlay / "runs" / "T1" / "run-record.json"
        before_mtime = record_path.stat().st_mtime_ns
        before_bytes = record_path.read_bytes()
        agentic_sdlc.gate_status_projection(self.root, "T1")
        self.assertEqual(before_bytes, record_path.read_bytes())
        self.assertEqual(before_mtime, record_path.stat().st_mtime_ns)


# --------------------------------------------------------------------------
# Symmetry across forges
# --------------------------------------------------------------------------


class SymmetryTests(GateStatusTestCase):
    def test_same_fixture_both_forges_produce_byte_identical_bodies(self):
        self.write_overlay()
        with self.frozen_time():
            with self.github_mock_env({"identity": {"login": "svc-bot"}}):
                github_result = self.run_github()
            with self.gitlab_mock_env({"identity": {"username": "svc-bot"}}):
                gitlab_result = self.run_gitlab()
        self.assertEqual(github_result["body"], gitlab_result["body"])


# --------------------------------------------------------------------------
# Exit code never varies with gate readiness
# --------------------------------------------------------------------------


class ExitCodeInvarianceTests(GateStatusTestCase):
    def test_every_gate_blocked_still_dry_run_succeeds(self):
        gates = make_full_gates({f"G{i}": {"status": "blocked"} for i in range(1, 11)})
        self.write_overlay(gates=gates)
        with self.frozen_time(), self.github_mock_env({"identity": {"login": "svc-bot"}}):
            result = self.run_github()
        self.assertEqual("create", result["action"])
        for i in range(1, 11):
            self.assertIn(f"| G{i} ", result["body"])

    def test_cli_exit_zero_when_every_gate_blocked(self):
        self.write_overlay(gates=make_full_gates({f"G{i}": {"status": "blocked"} for i in range(1, 11)}))
        env = {**os.environ, github_status_write.GITHUB_WRITE_MOCK_ENV_VAR: str(self._write_github_mock({"identity": {"login": "svc-bot"}}))}
        result = subprocess.run(
            CLI_COMMAND + [
                "publish-gate-status", "--task-id", "T1", "--forge", "github", "--repo", "o/r", "--pr", "1",
                "--as-bot", "svc-bot", "--allow-classification", "internal", "--root", str(self.root),
            ],
            text=True, capture_output=True, check=False, env=env,
        )
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)

    def _write_github_mock(self, payload):
        path = self.root / "cli-mock.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path


# --------------------------------------------------------------------------
# CLI wiring
# --------------------------------------------------------------------------


class CliWiringTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        overlay = self.root / ".agentic-sdlc"
        (overlay / "runs" / "T1").mkdir(parents=True)
        for name, content in [
            ("project.json", {"classification": "internal"}), ("authorities.json", {}),
            ("impact-profile.json", {}), ("routing.json", {}),
        ]:
            (overlay / name).write_text(json.dumps(content), encoding="utf-8")
        record = {
            "classification": "internal", "disposition": "pending", "scope": "s", "re_entry_history": [],
            "lifecycle_gates": make_full_gates(), "current_lifecycle_phase": "intent",
        }
        (overlay / "runs" / "T1" / "run-record.json").write_text(json.dumps(record), encoding="utf-8")
        self.addCleanup(self.temporary.cleanup)

    def run_cli(self, *arguments, expected=0, env=None):
        result = subprocess.run(
            CLI_COMMAND + list(arguments) + ["--root", str(self.root)],
            text=True, capture_output=True, check=False, env={**os.environ, **(env or {})},
        )
        self.assertEqual(expected, result.returncode, result.stderr or result.stdout)
        stdout = result.stdout or result.stderr
        return json.loads(stdout) if stdout.strip() else {}

    def test_wrong_flag_pair_for_forge_is_exit_1(self):
        self.run_cli(
            "publish-gate-status", "--task-id", "T1", "--forge", "gitlab", "--repo", "o/r", "--pr", "1",
            "--as-bot", "svc-bot", "--allow-classification", "internal", expected=1,
        )
        self.run_cli(
            "publish-gate-status", "--task-id", "T1", "--forge", "github", "--project-path", "grp/proj",
            "--mr-iid", "7", "--as-bot", "svc-bot", "--allow-classification", "internal", expected=1,
        )

    def test_missing_classification_is_exit_1(self):
        self.run_cli(
            "publish-gate-status", "--task-id", "T1", "--forge", "github", "--repo", "o/r", "--pr", "1",
            "--as-bot", "svc-bot", expected=1,
        )

    def test_mock_guard_without_i_know_this_is_mocked_is_exit_1(self):
        mock_path = self.root / "mock.json"
        mock_path.write_text(json.dumps({"identity": {"login": "svc-bot"}, "list": {}, "create": {}, "fetch": {}}), encoding="utf-8")
        self.run_cli(
            "publish-gate-status", "--task-id", "T1", "--forge", "github", "--repo", "o/r", "--pr", "1",
            "--as-bot", "svc-bot", "--allow-classification", "internal", "--apply",
            env={github_status_write.GITHUB_WRITE_MOCK_ENV_VAR: str(mock_path)},
            expected=1,
        )

    def test_lock_held_via_cli_is_exit_2(self):
        gate_status.acquire_lock(self.root, "T1", "github", break_lock=False)
        mock_path = self.root / "mock.json"
        mock_path.write_text(json.dumps({"identity": {"login": "svc-bot"}, "list": {}, "create": {}, "fetch": {}}), encoding="utf-8")
        self.run_cli(
            "publish-gate-status", "--task-id", "T1", "--forge", "github", "--repo", "o/r", "--pr", "1",
            "--as-bot", "svc-bot", "--allow-classification", "internal", "--apply", "--i-know-this-is-mocked",
            env={github_status_write.GITHUB_WRITE_MOCK_ENV_VAR: str(mock_path)},
            expected=2,
        )

    def test_dry_run_via_cli_subprocess(self):
        """Real subprocess dry-run: proves argparse wiring, env-based mock
        loading, and JSON stdout all work end to end. The apply round-trip
        (create -> re-fetch -> byte-identical verification) is NOT
        exercised via a real subprocess here: the rendered body embeds a
        fresh `rendered_at` timestamp on every call (by design -- see
        `render_gate_status_body`), so two independent process invocations
        a few milliseconds apart would legitimately compute two different
        bodies and never byte-match, making a subprocess-level round-trip
        assertion inherently flaky through no fault of the implementation.
        That exact round trip (create -> unchanged) is covered with frozen
        time in `IdempotencyTests` above; see
        `test_apply_and_list_gate_status_via_cli_in_process` below for the
        equivalent through the real CLI entry point with time frozen
        in-process."""
        mock_path = self.root / "mock.json"
        mock_path.write_text(json.dumps({"identity": {"login": "svc-bot"}, "list": {}, "create": {}, "fetch": {}}), encoding="utf-8")
        dry = self.run_cli(
            "publish-gate-status", "--task-id", "T1", "--forge", "github", "--repo", "o/r", "--pr", "1",
            "--as-bot", "svc-bot", "--allow-classification", "internal", "--dry-run",
            env={github_status_write.GITHUB_WRITE_MOCK_ENV_VAR: str(mock_path)},
        )
        self.assertEqual("create", dry["action"])

    def test_apply_and_list_gate_status_via_cli_in_process(self):
        """Same `agentic_sdlc.main()` CLI entry point as the real subprocess
        above, invoked in-process so `gate_status.now` can be frozen (see
        `test_dry_run_via_cli_subprocess`'s docstring for why a real
        subprocess round trip would be flaky here) -- still exercises the
        actual argparse table and `cmd_publish_gate_status`/
        `cmd_list_gate_status` handlers, not `gate_status.run()` directly."""
        mock_path = self.root / "mock.json"
        mock_path.write_text(json.dumps({"identity": {"login": "svc-bot"}, "list": {}, "create": {}, "fetch": {}}), encoding="utf-8")

        def call_cli(*args):
            buffer = []
            with mock.patch("builtins.print", side_effect=lambda *a, **k: buffer.append(a[0] if a else "")):
                exit_code = agentic_sdlc.main(list(args) + ["--root", str(self.root)])
            return exit_code, (json.loads(buffer[0]) if buffer else {})

        with mock.patch.object(gate_status, "now", return_value=FIXED_TIME):
            with mock.patch.dict(os.environ, {github_status_write.GITHUB_WRITE_MOCK_ENV_VAR: str(mock_path)}):
                exit_code, dry = call_cli(
                    "publish-gate-status", "--task-id", "T1", "--forge", "github", "--repo", "o/r", "--pr", "1",
                    "--as-bot", "svc-bot", "--allow-classification", "internal", "--dry-run",
                )
                self.assertEqual(0, exit_code)
                self.assertEqual("create", dry["action"])

                mock_path.write_text(json.dumps({
                    "identity": {"login": "svc-bot"}, "list": {}, "create": {"o/r#1": {"id": 5}},
                    "fetch": {"5": {"id": 5, "body": dry["body"], "user": {"login": "svc-bot"}}},
                }), encoding="utf-8")
                exit_code, applied = call_cli(
                    "publish-gate-status", "--task-id", "T1", "--forge", "github", "--repo", "o/r", "--pr", "1",
                    "--as-bot", "svc-bot", "--allow-classification", "internal", "--apply", "--i-know-this-is-mocked",
                )
                self.assertEqual(0, exit_code)
                self.assertEqual(5, applied["comment_id"])

                exit_code, listed = call_cli("list-gate-status", "--task-id", "T1")
                self.assertEqual(0, exit_code)
                self.assertEqual("github", listed["github"]["forge"])
                self.assertEqual([], listed["gitlab"]["entries"])


# --------------------------------------------------------------------------
# status() / gate_status_projection() refactor (task step 0)
# --------------------------------------------------------------------------


class StatusRefactorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        overlay = self.root / ".agentic-sdlc"
        (overlay / "runs" / "T1").mkdir(parents=True)
        # G1's lifecycle contract has required_contributions == ["intent"];
        # advance_lifecycle() only moves a gate to "ready" once its routing
        # binding supplies every required contribution field
        # (agents/tasks/artifacts) -- an empty routing.json would leave
        # every gate "pending" forever, which would make this test unable
        # to observe status()'s write behavior at all.
        routing = {
            "gate_bindings": {
                "G1": {"contributions": {"intent": {"agents": ["a"], "tasks": ["t"], "artifacts": ["x"]}}},
            },
        }
        for name, content in [
            ("project.json", {"classification": "internal"}), ("authorities.json", {}),
            ("impact-profile.json", {}), ("routing.json", routing),
        ]:
            (overlay / name).write_text(json.dumps(content), encoding="utf-8")
        gates = make_full_gates({"G1": {"status": "pending"}})
        record = {
            "classification": "internal", "disposition": "pending", "scope": "s", "re_entry_history": [],
            "lifecycle_gates": gates, "current_lifecycle_phase": "intent",
        }
        (overlay / "runs" / "T1" / "run-record.json").write_text(json.dumps(record), encoding="utf-8")
        self.record_path = overlay / "runs" / "T1" / "run-record.json"
        self.addCleanup(self.temporary.cleanup)

    def test_gate_status_projection_never_writes_run_record(self):
        before = self.record_path.read_bytes()
        before_mtime = self.record_path.stat().st_mtime_ns
        projection = agentic_sdlc.gate_status_projection(self.root, "T1")
        self.assertEqual(before, self.record_path.read_bytes())
        self.assertEqual(before_mtime, self.record_path.stat().st_mtime_ns)
        self.assertEqual("T1", projection["task_id"])
        self.assertEqual(10, len(projection["gates"]))
        self.assertIn("classification", projection)

    def test_status_still_writes_run_record_and_advances_a_gate(self):
        before = json.loads(self.record_path.read_text(encoding="utf-8"))
        self.assertEqual("pending", before["lifecycle_gates"][0]["status"])
        args = argparse_namespace(root=str(self.root), task_id="T1")
        exit_code = agentic_sdlc.status(args)
        self.assertEqual(0, exit_code)
        after = json.loads(self.record_path.read_text(encoding="utf-8"))
        statuses = [gate["status"] for gate in after["lifecycle_gates"]]
        self.assertIn("ready", statuses)  # advance_lifecycle moved the earliest eligible gate to "ready"

    def test_status_print_output_matches_projection_fields(self):
        # Compute the expected projection BEFORE status() runs (and writes);
        # a projection computed *after* the write would observe the
        # already-advanced record and could legitimately differ (the next
        # gate would no longer be eligible to advance a second time).
        expected = agentic_sdlc.gate_status_projection(self.root, "T1")
        args = argparse_namespace(root=str(self.root), task_id="T1")
        buffer = []
        with mock.patch("builtins.print", side_effect=lambda *a, **k: buffer.append(a[0] if a else "")):
            agentic_sdlc.status(args)
        printed = json.loads(buffer[0])
        self.assertEqual(expected["current_phase"], printed["current_phase"])
        self.assertEqual(expected["gates"], printed["gates"])
        self.assertEqual(expected["re_entry_history"], printed["re_entry_history"])


def argparse_namespace(**kwargs):
    import argparse

    return argparse.Namespace(**kwargs)


if __name__ == "__main__":
    unittest.main()
