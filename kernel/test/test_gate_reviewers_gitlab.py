"""Tests for `request-gate-reviewers-gitlab`
(`agentic_sdlc/gate_reviewers_gitlab.py`, `agentic_sdlc/gitlab_write.py`).

Read-only / reporting only: no test in this file ever exercises a write
call, because none exists. `gitlab_write.fetch_gitlab_mr` implements a GET
call only; `OrthogonalityTests` below asserts (by source inspection and by
byte-for-byte file comparison) that this feature never touches
run-record.json, dispatch-plan.json, or authorities.json, and that no
POST/DELETE/PATCH/PUT call is made anywhere in the module.

No `glab` binary or network access is required -- every GitLab call is
mocked via two environment variables: `gitlab_write.ISSUE_CREATE_MOCK_ENV_VAR`
(shared with every other `gitlab_write.py` function's mock convention, used
here for `identity`/`mr`/`users`) and `AGENTIC_SDLC_TEST_GITLAB_APPROVALS_FILE`
(the kernel's pre-existing `fetch_gitlab_mr_approvals` mock convention,
reused here rather than reimplemented).
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
from agentic_sdlc import gate_reviewers_gitlab, gitlab_write  # type: ignore

CLI_COMMAND = [sys.executable, str(PLUGIN_ROOT / "dev_entrypoint.py")]


# --------------------------------------------------------------------------
# Fixture builders
# --------------------------------------------------------------------------


def make_authority(*, status="assigned", assignee="human:default", gitlab_username=None, applicability="applicable", rationale=None):
    return {
        "status": status,
        "assignee": assignee,
        "gitlab_username": gitlab_username,
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


def default_mr(*, project_path="group/proj", head_sha="a" * 40, author="mr-author",
                state="opened", draft=False, reviewers=None, title="Some change"):
    return {
        "state": state,
        "draft": draft,
        "sha": head_sha,
        "author": {"username": author},
        "references": {"full": f"{project_path}!7"},
        "reviewers": [{"username": login} for login in (reviewers or [])],
        "title": title,
    }


def active_user(username, user_id=1):
    return [{"id": user_id, "username": username, "state": "active"}]


class GateReviewersGitlabTestCase(unittest.TestCase):
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

    def mock_env(self, gitlab_mock_payload, approvals_payload=None):
        mock_path = self.root / "gitlab-mock.json"
        mock_path.write_text(json.dumps(gitlab_mock_payload), encoding="utf-8")
        approvals_path = self.root / "approvals.json"
        approvals_path.write_text(
            json.dumps(approvals_payload if approvals_payload is not None else {"approved_by": []}), encoding="utf-8"
        )
        return mock.patch.dict(os.environ, {
            gitlab_write.ISSUE_CREATE_MOCK_ENV_VAR: str(mock_path),
            "AGENTIC_SDLC_TEST_GITLAB_APPROVALS_FILE": str(approvals_path),
        })

    def base_mock(self, *, bot="svc-bot", mr=None, users=None):
        return {
            "identity": {"username": bot},
            "mr": mr if mr is not None else default_mr(),
            "users": users or {},
        }

    def report(self, **kwargs):
        kwargs.setdefault("root", self.root)
        kwargs.setdefault("task_id", "T1")
        kwargs.setdefault("project_path", "group/proj")
        kwargs.setdefault("mr_iid", 7)
        kwargs.setdefault("as_bot", "svc-bot")
        kwargs.setdefault("gates", None)
        kwargs.setdefault("allow_classification", "internal")
        return gate_reviewers_gitlab.run(**kwargs)


def simple_authorities():
    return {
        "product_owner": make_authority(assignee="human:po", gitlab_username="po-user"),
        "engineering_lead": make_authority(assignee="human:el", gitlab_username="el-user"),
        "system_architect": make_authority(assignee="human:sa", gitlab_username="sa-user"),
    }


def simple_gates():
    return [
        make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")]),
        make_gate("G2", authority_requirements=[
            make_ar("product_owner", "Product Owner"), make_ar("engineering_lead", "Engineering Lead")
        ]),
        make_gate("G3", authority_requirements=[make_ar("system_architect", "System Architect")]),
    ]


def all_users_active(logins):
    return {login: active_user(login, user_id=index + 1) for index, login in enumerate(logins)}


# --------------------------------------------------------------------------
# Plan building (shared build_plan/eligibility -- lighter coverage here since
# gate_reviewers.py's PlanBuildingTests already exercises the shared logic
# exhaustively; this class only checks the GitLab call site wires it up)
# --------------------------------------------------------------------------


class PlanBuildingTests(GateReviewersGitlabTestCase):
    def test_gate_lookup_by_id_not_index_clean_error_if_absent(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        with self.assertRaises(gate_reviewers_gitlab.GateReviewersGitlabError):
            self.report(gates=["G9"])

    def test_many_to_one_two_gates_same_authority(self):
        gates = [
            make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")]),
            make_gate("G2", authority_requirements=[make_ar("product_owner", "Product Owner")]),
        ]
        authorities = {"product_owner": make_authority(assignee="human:po", gitlab_username="po-user")}
        self.write_overlay(gates=gates, authorities=authorities)
        with self.mock_env(self.base_mock(users=all_users_active(["po-user"]))):
            result = self.report(gates=["G1", "G2"])
        self.assertEqual(1, len(result["reviewers"]))
        self.assertEqual(2, len(result["reviewers"][0]["motivations"]))

    def test_not_applicable_authority_requirement_is_skipped_with_rationale(self):
        gates = [make_gate("G1", authority_requirements=[
            make_ar("product_owner", "Product Owner", applicability="not-applicable", rationale="n/a here")
        ])]
        self.write_overlay(gates=gates, authorities={})
        with self.mock_env(self.base_mock()):
            result = self.report(gates=["G1"])
        self.assertEqual([], result["reviewers"])
        self.assertEqual(1, len(result["skipped"]))
        self.assertEqual("not-applicable", result["skipped"][0]["reason"])

    def test_eligibility_fail_closed_invalidated(self):
        gates = [make_gate("G1", status="invalidated")]
        self.write_overlay(gates=gates, authorities={})
        with self.assertRaises(gate_reviewers_gitlab.GateReviewersGitlabError):
            self.report(gates=["G1"])

    def test_eligibility_fail_closed_pending_reentry(self):
        gates = [make_gate("G1", required_reentry_gate="G3")]
        self.write_overlay(gates=gates, authorities={})
        with self.assertRaises(gate_reviewers_gitlab.GateReviewersGitlabError):
            self.report(gates=["G1"])

    def test_default_gate_set_silently_skips_ineligible_gates(self):
        gates = [
            make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")]),
            make_gate("G2", status="invalidated"),
        ]
        authorities = {"product_owner": make_authority(assignee="human:po", gitlab_username="po-user")}
        self.write_overlay(gates=gates, authorities=authorities)
        with self.mock_env(self.base_mock(users=all_users_active(["po-user"]))):
            result = self.report()
        self.assertEqual(["G1"], result["gate_ids"])


# --------------------------------------------------------------------------
# GitLab-specific identity resolution
# --------------------------------------------------------------------------


class IdentityResolutionTests(GateReviewersGitlabTestCase):
    def test_authority_unknown(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")])]
        self.write_overlay(gates=gates, authorities={})
        with self.mock_env(self.base_mock()):
            result = self.report(gates=["G1"])
        self.assertEqual("authority-unknown", result["refusals"][0]["reason"])

    def test_authority_unassigned(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")])]
        authorities = {"product_owner": make_authority(status="unassigned", assignee=None)}
        self.write_overlay(gates=gates, authorities=authorities)
        with self.mock_env(self.base_mock()):
            result = self.report(gates=["G1"])
        self.assertEqual("authority-unassigned", result["refusals"][0]["reason"])

    def test_no_gitlab_binding_github_identity_rejected(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")])]
        authorities = {"product_owner": make_authority(assignee="github.com/po-user", gitlab_username=None)}
        self.write_overlay(gates=gates, authorities=authorities)
        with self.mock_env(self.base_mock()):
            result = self.report(gates=["G1"])
        self.assertEqual("no-gitlab-binding", result["refusals"][0]["reason"])

    def test_gitlab_username_from_identity_convention_accepted(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")])]
        authorities = {"product_owner": make_authority(assignee="gitlab.com/po-user", gitlab_username=None)}
        self.write_overlay(gates=gates, authorities=authorities)
        with self.mock_env(self.base_mock(users=all_users_active(["po-user"]))):
            result = self.report(gates=["G1"])
        self.assertEqual([], result["refusals"])
        self.assertEqual("po-user", result["reviewers"][0]["username"])

    def test_unresolved_username_reported(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")])]
        authorities = {"product_owner": make_authority(assignee="human:po", gitlab_username="ghost-user")}
        self.write_overlay(gates=gates, authorities=authorities)
        with self.mock_env(self.base_mock(users={"ghost-user": []})):
            result = self.report(gates=["G1"])
        self.assertEqual("gitlab-user-unresolved", result["reviewers"][0]["classification"])

    def test_ambiguous_username_reported(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")])]
        authorities = {"product_owner": make_authority(assignee="human:po", gitlab_username="dup-user")}
        self.write_overlay(gates=gates, authorities=authorities)
        users = {"dup-user": [
            {"id": 1, "username": "dup-user", "state": "active"},
            {"id": 2, "username": "dup-user", "state": "active"},
        ]}
        with self.mock_env(self.base_mock(users=users)):
            result = self.report(gates=["G1"])
        self.assertEqual("gitlab-user-ambiguous", result["reviewers"][0]["classification"])

    def test_inactive_matches_do_not_count_toward_ambiguity_or_resolution(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")])]
        authorities = {"product_owner": make_authority(assignee="human:po", gitlab_username="po-user")}
        self.write_overlay(gates=gates, authorities=authorities)
        users = {"po-user": [
            {"id": 1, "username": "po-user", "state": "active"},
            {"id": 2, "username": "po-user", "state": "blocked"},
        ]}
        with self.mock_env(self.base_mock(users=users)):
            result = self.report(gates=["G1"])
        self.assertEqual("to-request", result["reviewers"][0]["classification"])

    def test_case_insensitive_username_collapse_and_classification(self):
        gates = [
            make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")]),
            make_gate("G2", authority_requirements=[make_ar("engineering_lead", "Engineering Lead")]),
        ]
        authorities = {
            "product_owner": make_authority(assignee="human:po", gitlab_username="Shared-User"),
            "engineering_lead": make_authority(assignee="human:el", gitlab_username="shared-user"),
        }
        self.write_overlay(gates=gates, authorities=authorities)
        with self.mock_env(self.base_mock(users=all_users_active(["Shared-User", "shared-user"]))):
            result = self.report(gates=["G1", "G2"])
        self.assertEqual(1, len(result["reviewers"]))
        self.assertEqual(2, len(result["reviewers"][0]["motivations"]))

    def test_no_not_a_collaborator_reason_code_exists(self):
        source = (PLUGIN_ROOT / "agentic_sdlc" / "gate_reviewers_gitlab.py").read_text(encoding="utf-8")
        self.assertNotIn('"not-a-collaborator"', source)
        self.assertNotIn("not_a_collaborator", source)


# --------------------------------------------------------------------------
# Independence / poisoning (shared logic; light regression coverage)
# --------------------------------------------------------------------------


class IndependenceTests(GateReviewersGitlabTestCase):
    def test_preparer_match_refuses_self_approval(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")],
                            preparers=[{"id": "human:po"}])]
        authorities = {"product_owner": make_authority(assignee="human:po", gitlab_username="po-user")}
        self.write_overlay(gates=gates, authorities=authorities)
        with self.mock_env(self.base_mock()):
            result = self.report(gates=["G1"])
        self.assertEqual("self-approval", result["refusals"][0]["reason"])
        self.assertEqual("withheld-conflict", result["reviewers"][0]["classification"])

    def test_mr_author_conflict(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")])]
        authorities = {"product_owner": make_authority(assignee="human:po", gitlab_username="mr-author")}
        self.write_overlay(gates=gates, authorities=authorities)
        with self.mock_env(self.base_mock(mr=default_mr(author="mr-author"))):
            result = self.report(gates=["G1"])
        self.assertEqual("mr-author-conflict", result["refusals"][0]["reason"])
        self.assertEqual("withheld-conflict", result["reviewers"][0]["classification"])

    def test_actor_is_reviewer_conflict(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")])]
        authorities = {"product_owner": make_authority(assignee="human:po", gitlab_username="svc-bot")}
        self.write_overlay(gates=gates, authorities=authorities)
        with self.mock_env(self.base_mock(bot="svc-bot")):
            result = self.report(gates=["G1"], as_bot="svc-bot")
        self.assertEqual("actor-is-reviewer", result["refusals"][0]["reason"])

    def test_poisoning_across_gates_taints_every_motivation(self):
        gates = [
            make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")],
                       preparers=[{"id": "human:po"}]),
            make_gate("G6", authority_requirements=[make_ar("engineering_lead", "Engineering Lead")]),
        ]
        authorities = {
            "product_owner": make_authority(assignee="human:po", gitlab_username="shared-user"),
            "engineering_lead": make_authority(assignee="human:el", gitlab_username="shared-user"),
        }
        self.write_overlay(gates=gates, authorities=authorities)
        with self.mock_env(self.base_mock()):
            result = self.report(gates=["G1", "G6"])
        self.assertEqual(1, len(result["reviewers"]))
        entry = result["reviewers"][0]
        self.assertEqual("withheld-conflict", entry["classification"])
        self.assertEqual(2, len(entry["motivations"]))
        self.assertEqual("G1", entry["withheld_cause"]["gate_id"])

    def test_poisoning_limited_to_three_independence_codes(self):
        gates = [
            make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")]),
            make_gate("G6", authority_requirements=[make_ar("engineering_lead", "Engineering Lead")]),
        ]
        authorities = {
            "product_owner": make_authority(assignee="human:po", gitlab_username="shared-user"),
            "engineering_lead": make_authority(assignee="human:el", gitlab_username="shared-user"),
        }
        self.write_overlay(gates=gates, authorities=authorities)
        with self.mock_env(self.base_mock(users=all_users_active(["shared-user"]))):
            result = self.report(gates=["G1", "G6"])
        self.assertEqual([], result["refusals"])
        self.assertEqual("to-request", result["reviewers"][0]["classification"])

    def test_empty_preparers_and_none_verifier_passes_vacuously(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")],
                            preparers=[], independent_verifier=None)]
        authorities = {"product_owner": make_authority(assignee="human:po", gitlab_username="po-user")}
        self.write_overlay(gates=gates, authorities=authorities)
        with self.mock_env(self.base_mock(users=all_users_active(["po-user"]))):
            result = self.report(gates=["G1"])
        self.assertEqual([], result["refusals"])
        self.assertEqual("to-request", result["reviewers"][0]["classification"])


# --------------------------------------------------------------------------
# Existence / review classification -- no `review-stale` (documented gap)
# --------------------------------------------------------------------------


class ClassificationTests(GateReviewersGitlabTestCase):
    def _single_reviewer(self, username="po-user"):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")])]
        authorities = {"product_owner": make_authority(assignee="human:po", gitlab_username=username)}
        self.write_overlay(gates=gates, authorities=authorities)
        return username

    def test_already_reviewer(self):
        username = self._single_reviewer()
        with self.mock_env(self.base_mock(mr=default_mr(reviewers=[username]), users=all_users_active([username]))):
            result = self.report(gates=["G1"])
        self.assertEqual("already-reviewer", result["reviewers"][0]["classification"])

    def test_already_approved(self):
        username = self._single_reviewer()
        approvals = {"approved_by": [{"user": {"username": username, "id": 1}}], "sha": "a" * 40, "updated_at": "2026-01-01T00:00:00Z"}
        with self.mock_env(self.base_mock(users=all_users_active([username])), approvals_payload=approvals):
            result = self.report(gates=["G1"])
        self.assertEqual("already-approved", result["reviewers"][0]["classification"])

    def test_to_request_when_neither_reviewer_nor_approved(self):
        username = self._single_reviewer()
        with self.mock_env(self.base_mock(users=all_users_active([username]))):
            result = self.report(gates=["G1"])
        self.assertEqual("to-request", result["reviewers"][0]["classification"])

    def test_already_approved_takes_priority_over_already_reviewer(self):
        username = self._single_reviewer()
        approvals = {"approved_by": [{"user": {"username": username, "id": 1}}], "sha": "a" * 40, "updated_at": "2026-01-01T00:00:00Z"}
        with self.mock_env(
            self.base_mock(mr=default_mr(reviewers=[username]), users=all_users_active([username])),
            approvals_payload=approvals,
        ):
            result = self.report(gates=["G1"])
        self.assertEqual("already-approved", result["reviewers"][0]["classification"])

    def test_no_review_stale_classification_exists(self):
        """Documents the verified GitLab API gap: the MR-approvals endpoint
        has no per-approver commit field (only an MR-level `sha` applied
        uniformly to every approver), so per-approver staleness cannot be
        computed without misrepresenting some approvers -- see
        `gate_reviewers_gitlab.py`'s module docstring. This is a permanent
        design decision, not a TODO."""
        self.assertNotIn("review-stale", gate_reviewers_gitlab.CLASSIFICATIONS)
        source = (PLUGIN_ROOT / "agentic_sdlc" / "gate_reviewers_gitlab.py").read_text(encoding="utf-8")
        self.assertNotIn('"review-stale"', source)

    def test_mr_head_sha_still_surfaced_for_human_cross_check(self):
        username = self._single_reviewer()
        with self.mock_env(self.base_mock(mr=default_mr(head_sha="c" * 40), users=all_users_active([username]))):
            result = self.report(gates=["G1"])
        self.assertEqual("c" * 40, result["mr_head_sha"])


# --------------------------------------------------------------------------
# MR gating
# --------------------------------------------------------------------------


class MrGatingTests(GateReviewersGitlabTestCase):
    def test_mr_not_found_404_blocked(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        with self.mock_env({"identity": {"username": "svc-bot"}, "mr": None}):
            with self.assertRaises(gate_reviewers_gitlab.GateReviewersGitlabError):
                self.report(gates=["G1"])

    def test_mr_closed_blocked(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        with self.mock_env(self.base_mock(mr=default_mr(state="closed"))):
            with self.assertRaises(gate_reviewers_gitlab.GateReviewersGitlabError):
                self.report(gates=["G1"])

    def test_mr_merged_blocked(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        with self.mock_env(self.base_mock(mr=default_mr(state="merged"))):
            with self.assertRaises(gate_reviewers_gitlab.GateReviewersGitlabError):
                self.report(gates=["G1"])

    def test_project_path_mismatch_blocked(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        with self.mock_env(self.base_mock(mr=default_mr(project_path="other/project"))):
            with self.assertRaises(gate_reviewers_gitlab.GateReviewersGitlabError):
                self.report(gates=["G1"])

    def test_draft_field_allowed_and_reported(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        with self.mock_env(self.base_mock(mr=default_mr(draft=True))):
            result = self.report(gates=["G1"])
        self.assertTrue(result["mr_draft"])

    def test_draft_title_prefix_fallback_when_draft_field_absent(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        mr = default_mr(title="Draft: work in progress")
        del mr["draft"]
        with self.mock_env(self.base_mock(mr=mr)):
            result = self.report(gates=["G1"])
        self.assertTrue(result["mr_draft"])

    def test_wip_title_prefix_fallback_when_draft_field_absent(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        mr = default_mr(title="WIP: work in progress")
        del mr["draft"]
        with self.mock_env(self.base_mock(mr=mr)):
            result = self.report(gates=["G1"])
        self.assertTrue(result["mr_draft"])

    def test_as_bot_mismatch_blocked(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        with self.mock_env(self.base_mock(bot="someone-else")):
            with self.assertRaises(gate_reviewers_gitlab.GateReviewersGitlabError):
                self.report(gates=["G1"], as_bot="svc-bot")

    def test_allow_classification_absent_or_mismatched_errors_before_any_gitlab_call(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={}, classification="internal")
        with self.assertRaises(gate_reviewers_gitlab.GateReviewersGitlabError):
            self.report(gates=["G1"], allow_classification=None)
        with self.assertRaises(gate_reviewers_gitlab.GateReviewersGitlabError):
            self.report(gates=["G1"], allow_classification="restricted")


# --------------------------------------------------------------------------
# Orthogonality
# --------------------------------------------------------------------------


class OrthogonalityTests(GateReviewersGitlabTestCase):
    def test_input_files_byte_identical_after_report(self):
        self.write_overlay(gates=simple_gates(), authorities=simple_authorities())
        record_path = self.overlay / "runs/T1/run-record.json"
        dispatch_path = self.overlay / "runs/T1/dispatch-plan.json"
        authorities_path = self.overlay / "authorities.json"
        before = {p: p.read_bytes() for p in (record_path, dispatch_path, authorities_path)}
        with self.mock_env(self.base_mock(users=all_users_active(["po-user", "el-user", "sa-user"]))):
            self.report()
        for path, content in before.items():
            self.assertEqual(content, path.read_bytes(), f"{path} was modified by request-gate-reviewers-gitlab")

    def test_no_write_http_method_used_anywhere(self):
        source = (PLUGIN_ROOT / "agentic_sdlc" / "gate_reviewers_gitlab.py").read_text(encoding="utf-8")
        for verb in ('"POST"', '"PUT"', '"PATCH"', '"DELETE"', "--method"):
            self.assertNotIn(verb, source, f"gate_reviewers_gitlab.py contains a write-method reference: {verb}")

    def test_no_apply_flag_in_cli_wiring(self):
        source = (PLUGIN_ROOT / "agentic_sdlc" / "__init__.py").read_text(encoding="utf-8")
        start = source.index('request_gate_reviewers_gitlab = subparsers.add_parser(')
        end = source.index("request_gate_reviewers_gitlab.set_defaults(handler=cmd_request_gate_reviewers_gitlab)")
        block = source[start:end]
        self.assertNotIn("--apply", block)
        self.assertNotIn("--dry-run", block)
        self.assertNotIn("--plan-digest", block)
        self.assertNotIn("--reviewer-login", block)


# --------------------------------------------------------------------------
# CLI wiring
# --------------------------------------------------------------------------


class CliWiringTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        overlay = self.root / ".agentic-sdlc"
        (overlay / "runs" / "T1").mkdir(parents=True)
        (overlay / "project.json").write_text(json.dumps({"classification": "internal"}), encoding="utf-8")
        (overlay / "authorities.json").write_text(json.dumps(simple_authorities()), encoding="utf-8")
        record = {
            "classification": "internal", "disposition": "pending", "scope": "s", "re_entry_history": [],
            "lifecycle_gates": simple_gates(),
        }
        (overlay / "runs" / "T1" / "run-record.json").write_text(json.dumps(record), encoding="utf-8")
        dispatch = {
            "dispatch_fingerprint": "sha256:" + "a" * 64,
            "gate_dispatch": [{"gate_id": g, "status": "required"} for g in ("G1", "G2", "G3")],
        }
        (overlay / "runs" / "T1" / "dispatch-plan.json").write_text(json.dumps(dispatch), encoding="utf-8")
        self.addCleanup(self.temporary.cleanup)

    def run_cli(self, *arguments, expected=0, env=None):
        result = subprocess.run(
            CLI_COMMAND + list(arguments) + ["--root", str(self.root)],
            text=True, capture_output=True, check=False, env={**os.environ, **(env or {})},
        )
        self.assertEqual(expected, result.returncode, result.stderr or result.stdout)
        return json.loads(result.stdout or result.stderr)

    def test_help_lists_command(self):
        result = subprocess.run(CLI_COMMAND + ["--help"], text=True, capture_output=True, check=False)
        self.assertIn("request-gate-reviewers-gitlab", result.stdout)

    def test_report_via_cli_exit0_when_clean(self):
        mock_payload = {
            "identity": {"username": "svc-bot"},
            "mr": default_mr(),
            "users": all_users_active(["po-user", "el-user", "sa-user"]),
        }
        mock_path = self.root / "gitlab-mock.json"
        mock_path.write_text(json.dumps(mock_payload), encoding="utf-8")
        approvals_path = self.root / "approvals.json"
        approvals_path.write_text(json.dumps({"approved_by": []}), encoding="utf-8")
        result = self.run_cli(
            "request-gate-reviewers-gitlab", "--task-id", "T1", "--project-path", "group/proj", "--mr-iid", "7",
            "--as-bot", "svc-bot", "--allow-classification", "internal",
            env={
                gitlab_write.ISSUE_CREATE_MOCK_ENV_VAR: str(mock_path),
                "AGENTIC_SDLC_TEST_GITLAB_APPROVALS_FILE": str(approvals_path),
            },
        )
        self.assertEqual([], result["refusals"])
        self.assertEqual(3, len(result["reviewers"]))

    def test_missing_required_flag_is_argparse_error(self):
        result = subprocess.run(
            CLI_COMMAND + ["request-gate-reviewers-gitlab", "--task-id", "T1", "--root", str(self.root)],
            text=True, capture_output=True, check=False,
        )
        self.assertNotEqual(0, result.returncode)

    def test_no_list_gate_reviewer_requests_gitlab_command(self):
        result = subprocess.run(CLI_COMMAND + ["--help"], text=True, capture_output=True, check=False)
        self.assertNotIn("list-gate-reviewer-requests-gitlab", result.stdout)


if __name__ == "__main__":
    unittest.main()
