"""Tests for `request-gate-reviewers`
(`agentic_sdlc/gate_reviewers.py`, `agentic_sdlc/github_write.py`).

Read-only / reporting only: no test in this file ever exercises a write
call, because none exists. `github_write.py` implements GET calls only;
`OrthogonalityTests` below asserts (by source inspection and by
byte-for-byte file comparison) that this feature never touches
run-record.json, dispatch-plan.json, or authorities.json, and that no
POST/DELETE/PATCH/PUT call is made anywhere in the module.

No `gh` binary or network access is required -- every GitHub call is
mocked via two environment variables: `AGENTIC_SDLC_TEST_GITHUB_READ_FILE`
(`github_write.py`'s own mock convention) and
`AGENTIC_SDLC_TEST_GITHUB_REVIEWS_FILE` (the kernel's pre-existing
`fetch_github_pr_reviews` mock convention, reused here rather than
reimplemented).
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
from agentic_sdlc import gate_reviewers, github_write  # type: ignore

CLI_COMMAND = [sys.executable, str(PLUGIN_ROOT / "dev_entrypoint.py")]


# --------------------------------------------------------------------------
# Fixture builders
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


class GateReviewersTestCase(unittest.TestCase):
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

    def mock_env(self, github_read_payload, reviews_payload=None):
        read_path = self.root / "github-read.json"
        read_path.write_text(json.dumps(github_read_payload), encoding="utf-8")
        reviews_path = self.root / "reviews.json"
        reviews_path.write_text(json.dumps(reviews_payload if reviews_payload is not None else []), encoding="utf-8")
        return mock.patch.dict(os.environ, {
            github_write.GITHUB_READ_MOCK_ENV_VAR: str(read_path),
            "AGENTIC_SDLC_TEST_GITHUB_REVIEWS_FILE": str(reviews_path),
        })

    def base_mock(self, *, bot="svc-bot", pr=None, requested=None, users=None, collaborators=None):
        return {
            "identity": {"login": bot},
            "pr": pr if pr is not None else default_pr(),
            "requested_reviewers": {"users": [{"login": login} for login in (requested or [])], "teams": []},
            "users": users or {},
            "collaborators": collaborators or {},
        }

    def report(self, **kwargs):
        kwargs.setdefault("root", self.root)
        kwargs.setdefault("task_id", "T1")
        kwargs.setdefault("repo", "owner/proj")
        kwargs.setdefault("pr", 42)
        kwargs.setdefault("as_bot", "svc-bot")
        kwargs.setdefault("gates", None)
        kwargs.setdefault("allow_classification", "internal")
        return gate_reviewers.run(**kwargs)


def simple_authorities():
    return {
        "product_owner": make_authority(assignee="human:po", github_login="po-user"),
        "engineering_lead": make_authority(assignee="human:el", github_login="el-user"),
        "system_architect": make_authority(assignee="human:sa", github_login="sa-user"),
    }


def simple_gates():
    return [
        make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")]),
        make_gate("G2", authority_requirements=[
            make_ar("product_owner", "Product Owner"), make_ar("engineering_lead", "Engineering Lead")
        ]),
        make_gate("G3", authority_requirements=[make_ar("system_architect", "System Architect")]),
    ]


def all_collaborators_all_exist(logins):
    return (
        {login: True for login in logins},
        {f"owner/proj:{login}": True for login in logins},
    )


# --------------------------------------------------------------------------
# Plan building
# --------------------------------------------------------------------------


class PlanBuildingTests(GateReviewersTestCase):
    def test_gate_lookup_by_id_not_index_clean_error_if_absent(self):
        self.write_overlay(gates=simple_gates(), authorities=simple_authorities())
        with self.assertRaises(gate_reviewers.GateReviewersError) as ctx:
            self.report(gates=["G9"])
        self.assertIn("G9", str(ctx.exception))

    def test_many_to_one_two_gates_same_authority(self):
        gates = [
            make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")]),
            make_gate("G6", authority_requirements=[make_ar("product_owner", "Product Owner")]),
        ]
        authorities = {"product_owner": make_authority(assignee="human:po", github_login="po-user")}
        self.write_overlay(gates=gates, authorities=authorities)
        users, collaborators = all_collaborators_all_exist(["po-user"])
        with self.mock_env(self.base_mock(users=users, collaborators=collaborators)):
            result = self.report(gates=["G1", "G6"])
        self.assertEqual(1, len(result["reviewers"]))
        entry = result["reviewers"][0]
        self.assertEqual("po-user", entry["login"])
        self.assertEqual(2, len(entry["motivations"]))
        self.assertEqual({"G1", "G6"}, {m["gate_id"] for m in entry["motivations"]})

    def test_many_to_one_two_authorities_same_login(self):
        gates = [make_gate("G2", authority_requirements=[
            make_ar("product_owner", "Product Owner"), make_ar("engineering_lead", "Engineering Lead"),
        ])]
        authorities = {
            "product_owner": make_authority(assignee="human:po", github_login="shared-login"),
            "engineering_lead": make_authority(assignee="human:el", github_login="shared-login"),
        }
        self.write_overlay(gates=gates, authorities=authorities)
        users, collaborators = all_collaborators_all_exist(["shared-login"])
        with self.mock_env(self.base_mock(users=users, collaborators=collaborators)):
            result = self.report(gates=["G2"])
        self.assertEqual(1, len(result["reviewers"]))
        entry = result["reviewers"][0]
        self.assertEqual(2, len(entry["motivations"]))
        self.assertEqual({"product_owner", "engineering_lead"}, {m["authority_id"] for m in entry["motivations"]})

    def test_not_applicable_authority_requirement_is_skipped_with_rationale(self):
        gates = [make_gate("G4", authority_requirements=[
            make_ar("governance_lead", "Governance Lead"),
            make_ar("data_control_owner", "Data/Control Owner", applicability="not-applicable", rationale="No regulated data in scope"),
        ])]
        authorities = {
            "governance_lead": make_authority(assignee="human:gov", github_login="gov-user"),
            "data_control_owner": make_authority(status="unknown", assignee=None),
        }
        self.write_overlay(gates=gates, authorities=authorities)
        users, collaborators = all_collaborators_all_exist(["gov-user"])
        with self.mock_env(self.base_mock(users=users, collaborators=collaborators)):
            result = self.report(gates=["G4"])
        self.assertEqual(1, len(result["reviewers"]))
        self.assertEqual(1, len(result["skipped"]))
        self.assertEqual("not-applicable", result["skipped"][0]["reason"])
        self.assertEqual("No regulated data in scope", result["skipped"][0]["rationale"])

    def test_authorities_not_applicable_workaround_skipped_not_refused(self):
        gates = [make_gate("G4", authority_requirements=[
            make_ar("data_control_owner", "Data/Control Owner", applicability="unknown", rationale=None),
        ])]
        authorities = {
            "data_control_owner": make_authority(status="unknown", assignee=None, applicability="not-applicable", rationale="No regulated data"),
        }
        self.write_overlay(gates=gates, authorities=authorities)
        with self.mock_env(self.base_mock()):
            result = self.report(gates=["G4"])
        self.assertEqual(1, len(result["skipped"]))
        self.assertEqual("authorities-not-applicable", result["skipped"][0]["reason"])
        self.assertEqual([], result["refusals"])

    def test_unknown_applicability_without_authorities_not_applicable_refuses(self):
        gates = [make_gate("G4", authority_requirements=[
            make_ar("data_control_owner", "Data/Control Owner", applicability="unknown", rationale=None),
        ])]
        authorities = {"data_control_owner": make_authority(status="unknown", assignee=None, applicability="unknown")}
        self.write_overlay(gates=gates, authorities=authorities)
        with self.mock_env(self.base_mock()):
            result = self.report(gates=["G4"])
        self.assertEqual("applicability-unknown", result["refusals"][0]["reason"])

    def test_eligibility_fail_closed_not_in_dispatch_plan(self):
        self.write_overlay(gates=[make_gate("G1"), make_gate("G2")], authorities={}, configured_gate_ids=["G1"])
        with self.assertRaises(gate_reviewers.GateReviewersError):
            self.report(gates=["G2"])

    def test_eligibility_fail_closed_not_applicable(self):
        self.write_overlay(gates=[make_gate("G1", applicability="not-applicable")], authorities={})
        with self.assertRaises(gate_reviewers.GateReviewersError):
            self.report(gates=["G1"])

    def test_eligibility_fail_closed_invalidated(self):
        self.write_overlay(gates=[make_gate("G1", status="invalidated")], authorities={})
        with self.assertRaises(gate_reviewers.GateReviewersError):
            self.report(gates=["G1"])

    def test_eligibility_fail_closed_pending_reentry(self):
        self.write_overlay(gates=[make_gate("G1", required_reentry_gate="G1")], authorities={})
        with self.assertRaises(gate_reviewers.GateReviewersError):
            self.report(gates=["G1"])

    def test_default_gate_set_silently_skips_ineligible_gates(self):
        self.write_overlay(
            gates=[make_gate("G1"), make_gate("G2", applicability="not-applicable")],
            authorities={}, configured_gate_ids=["G1", "G2"],
        )
        with self.mock_env(self.base_mock()):
            result = self.report(gates=None)
        self.assertEqual(["G1"], result["gate_ids"])


# --------------------------------------------------------------------------
# Identity resolution
# --------------------------------------------------------------------------


class IdentityResolutionTests(GateReviewersTestCase):
    def test_authority_unknown(self):
        gates = [make_gate("G4", authority_requirements=[make_ar("governance_lead", "Governance Lead")])]
        self.write_overlay(gates=gates, authorities={})
        with self.mock_env(self.base_mock()):
            result = self.report(gates=["G4"])
        self.assertEqual("authority-unknown", result["refusals"][0]["reason"])
        self.assertEqual(0, len(result["reviewers"]))

    def test_authority_unassigned(self):
        gates = [make_gate("G4", authority_requirements=[make_ar("governance_lead", "Governance Lead")])]
        authorities = {"governance_lead": make_authority(status="unknown", assignee=None)}
        self.write_overlay(gates=gates, authorities=authorities)
        with self.mock_env(self.base_mock()):
            result = self.report(gates=["G4"])
        self.assertEqual("authority-unassigned", result["refusals"][0]["reason"])

    def test_no_github_binding_gitlab_identity_rejected_github_identity_accepted(self):
        gates = [make_gate("G4", authority_requirements=[make_ar("governance_lead", "Governance Lead")])]
        authorities = {"governance_lead": make_authority(assignee="gitlab.com/alice")}
        self.write_overlay(gates=gates, authorities=authorities)
        with self.mock_env(self.base_mock()):
            result = self.report(gates=["G4"])
        self.assertEqual("no-github-binding", result["refusals"][0]["reason"])

        authorities2 = {"governance_lead": make_authority(assignee="github.com/alice")}
        self.write_overlay(gates=gates, authorities=authorities2)
        users, collaborators = all_collaborators_all_exist(["alice"])
        with self.mock_env(self.base_mock(users=users, collaborators=collaborators)):
            result2 = self.report(gates=["G4"])
        self.assertEqual([], result2["refusals"])
        self.assertEqual(1, len(result2["reviewers"]))

    def test_unresolved_github_user_reported(self):
        gates = [make_gate("G4", authority_requirements=[make_ar("governance_lead", "Governance Lead")])]
        authorities = {"governance_lead": make_authority(assignee="github.com/ghost")}
        self.write_overlay(gates=gates, authorities=authorities)
        with self.mock_env(self.base_mock(users={"ghost": False})):
            result = self.report(gates=["G4"])
        self.assertEqual("github-user-unresolved", result["reviewers"][0]["classification"])

    def test_not_a_collaborator_reported(self):
        gates = [make_gate("G4", authority_requirements=[make_ar("governance_lead", "Governance Lead")])]
        authorities = {"governance_lead": make_authority(assignee="github.com/outsider")}
        self.write_overlay(gates=gates, authorities=authorities)
        with self.mock_env(self.base_mock(users={"outsider": True}, collaborators={"owner/proj:outsider": False})):
            result = self.report(gates=["G4"])
        self.assertEqual("not-a-collaborator", result["reviewers"][0]["classification"])

    def test_case_insensitive_login_collapse_and_classification(self):
        gates = [
            make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")]),
            make_gate("G6", authority_requirements=[make_ar("engineering_lead", "Engineering Lead")]),
        ]
        authorities = {
            "product_owner": make_authority(assignee="human:po", github_login="Shared-Login"),
            "engineering_lead": make_authority(assignee="human:el", github_login="shared-login"),
        }
        self.write_overlay(gates=gates, authorities=authorities)
        with self.mock_env(self.base_mock(
            users={"Shared-Login": True}, collaborators={"owner/proj:Shared-Login": True},
            requested=["SHARED-LOGIN"],
        )):
            result = self.report(gates=["G1", "G6"])
        self.assertEqual(1, len(result["reviewers"]))
        self.assertEqual("already-requested", result["reviewers"][0]["classification"])
        self.assertEqual(2, len(result["reviewers"][0]["motivations"]))

    def test_no_github_user_ambiguous_reason_code_exists(self):
        """Regression guard: GET /users/{login} is an exact lookup, unlike
        GitLab's search-based resolution -- there is no ambiguous-match
        case, and no reason code for it should exist."""
        self.assertNotIn("github-user-ambiguous", gate_reviewers.CLASSIFICATIONS)
        self.assertNotIn("github-user-ambiguous", gate_reviewers.INDEPENDENCE_REASONS)
        self.assertNotIn("gitlab-user-ambiguous", gate_reviewers.CLASSIFICATIONS)


# --------------------------------------------------------------------------
# Independence / poisoning
# --------------------------------------------------------------------------


class IndependenceTests(GateReviewersTestCase):
    def test_preparer_match_refuses_self_approval(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")],
                            preparers=[{"id": "human:po"}])]
        authorities = {"product_owner": make_authority(assignee="human:po", github_login="po-user")}
        self.write_overlay(gates=gates, authorities=authorities)
        with self.mock_env(self.base_mock()):
            result = self.report(gates=["G1"])
        self.assertEqual("self-approval", result["refusals"][0]["reason"])
        self.assertEqual("withheld-conflict", result["reviewers"][0]["classification"])

    def test_independent_verifier_match_refuses_self_approval(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")],
                            independent_verifier={"id": "human:po"})]
        authorities = {"product_owner": make_authority(assignee="human:po", github_login="po-user")}
        self.write_overlay(gates=gates, authorities=authorities)
        with self.mock_env(self.base_mock()):
            result = self.report(gates=["G1"])
        self.assertEqual("self-approval", result["refusals"][0]["reason"])

    def test_pr_author_conflict(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")])]
        authorities = {"product_owner": make_authority(assignee="human:po", github_login="pr-author")}
        self.write_overlay(gates=gates, authorities=authorities)
        with self.mock_env(self.base_mock(pr=default_pr(author="pr-author"))):
            result = self.report(gates=["G1"])
        self.assertEqual("pr-author-conflict", result["refusals"][0]["reason"])
        self.assertEqual("withheld-conflict", result["reviewers"][0]["classification"])

    def test_actor_is_reviewer_conflict(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")])]
        authorities = {"product_owner": make_authority(assignee="human:po", github_login="svc-bot")}
        self.write_overlay(gates=gates, authorities=authorities)
        with self.mock_env(self.base_mock(bot="svc-bot")):
            result = self.report(gates=["G1"], as_bot="svc-bot")
        self.assertEqual("actor-is-reviewer", result["refusals"][0]["reason"])

    def test_poisoning_across_gates_taints_every_motivation(self):
        """A login that fails independence on one gate must be withheld
        from ALL its motivations, including a second, otherwise-clean
        gate/authority pair resolving to the same login."""
        gates = [
            make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")],
                       preparers=[{"id": "human:po"}]),
            make_gate("G6", authority_requirements=[make_ar("engineering_lead", "Engineering Lead")]),
        ]
        authorities = {
            "product_owner": make_authority(assignee="human:po", github_login="shared-login"),
            "engineering_lead": make_authority(assignee="human:el", github_login="shared-login"),
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
        """A resolution failure (no-github-binding) on one pair must NOT
        poison a different, clean pair resolving to the same login --
        poisoning is limited to self-approval/pr-author-conflict/
        actor-is-reviewer, never resolution failures."""
        gates = [
            make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")]),
            make_gate("G6", authority_requirements=[make_ar("engineering_lead", "Engineering Lead")]),
        ]
        authorities = {
            "product_owner": make_authority(assignee="human:po", github_login="shared-login"),
            "engineering_lead": make_authority(assignee="human:el", github_login="shared-login"),
        }
        self.write_overlay(gates=gates, authorities=authorities)
        users, collaborators = all_collaborators_all_exist(["shared-login"])
        with self.mock_env(self.base_mock(users=users, collaborators=collaborators)):
            result = self.report(gates=["G1", "G6"])
        # No independence conflict configured here; both pairs resolve cleanly.
        self.assertEqual([], result["refusals"])
        self.assertEqual("to-request", result["reviewers"][0]["classification"])

    def test_empty_preparers_and_none_verifier_passes_vacuously(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")],
                            preparers=[], independent_verifier=None)]
        authorities = {"product_owner": make_authority(assignee="human:po", github_login="po-user")}
        self.write_overlay(gates=gates, authorities=authorities)
        users, collaborators = all_collaborators_all_exist(["po-user"])
        with self.mock_env(self.base_mock(users=users, collaborators=collaborators)):
            result = self.report(gates=["G1"])
        self.assertEqual([], result["refusals"])
        self.assertEqual("to-request", result["reviewers"][0]["classification"])


# --------------------------------------------------------------------------
# Existence / review classification
# --------------------------------------------------------------------------


class ClassificationTests(GateReviewersTestCase):
    def _single_reviewer(self, login="po-user"):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")])]
        authorities = {"product_owner": make_authority(assignee="human:po", github_login=login)}
        self.write_overlay(gates=gates, authorities=authorities)
        return login

    def test_already_requested(self):
        login = self._single_reviewer()
        with self.mock_env(self.base_mock(users={login: True}, collaborators={f"owner/proj:{login}": True}, requested=[login])):
            result = self.report(gates=["G1"])
        self.assertEqual("already-requested", result["reviewers"][0]["classification"])

    def test_already_reviewed_at_head_sha(self):
        login = self._single_reviewer()
        head_sha = "b" * 40
        reviews = [{"user": {"login": login}, "state": "APPROVED", "commit_id": head_sha, "submitted_at": "2026-01-01T00:00:00Z"}]
        with self.mock_env(
            self.base_mock(users={login: True}, collaborators={f"owner/proj:{login}": True}, pr=default_pr(head_sha=head_sha)),
            reviews_payload=reviews,
        ):
            result = self.report(gates=["G1"])
        self.assertEqual("already-reviewed", result["reviewers"][0]["classification"])

    def test_review_stale_at_older_commit(self):
        login = self._single_reviewer()
        reviews = [{"user": {"login": login}, "state": "APPROVED", "commit_id": "c" * 40, "submitted_at": "2026-01-01T00:00:00Z"}]
        with self.mock_env(
            self.base_mock(users={login: True}, collaborators={f"owner/proj:{login}": True}, pr=default_pr(head_sha="d" * 40)),
            reviews_payload=reviews,
        ):
            result = self.report(gates=["G1"])
        self.assertEqual("review-stale", result["reviewers"][0]["classification"])

    def test_dismissed_review_counts_as_to_request(self):
        login = self._single_reviewer()
        head_sha = "e" * 40
        reviews = [{"user": {"login": login}, "state": "DISMISSED", "commit_id": head_sha, "submitted_at": "2026-01-01T00:00:00Z"}]
        with self.mock_env(
            self.base_mock(users={login: True}, collaborators={f"owner/proj:{login}": True}, pr=default_pr(head_sha=head_sha)),
            reviews_payload=reviews,
        ):
            result = self.report(gates=["G1"])
        self.assertEqual("to-request", result["reviewers"][0]["classification"])

    def test_to_request_when_neither_requested_nor_reviewed(self):
        login = self._single_reviewer()
        with self.mock_env(self.base_mock(users={login: True}, collaborators={f"owner/proj:{login}": True})):
            result = self.report(gates=["G1"])
        self.assertEqual("to-request", result["reviewers"][0]["classification"])

    def test_already_reviewed_takes_priority_over_already_requested(self):
        login = self._single_reviewer()
        head_sha = "f" * 40
        reviews = [{"user": {"login": login}, "state": "APPROVED", "commit_id": head_sha, "submitted_at": "2026-01-01T00:00:00Z"}]
        with self.mock_env(
            self.base_mock(
                users={login: True}, collaborators={f"owner/proj:{login}": True},
                pr=default_pr(head_sha=head_sha), requested=[login],
            ),
            reviews_payload=reviews,
        ):
            result = self.report(gates=["G1"])
        self.assertEqual("already-reviewed", result["reviewers"][0]["classification"])


# --------------------------------------------------------------------------
# PR gating
# --------------------------------------------------------------------------


class PrGatingTests(GateReviewersTestCase):
    def test_pr_not_found_404_blocked_exit1(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        with self.mock_env({"identity": {"login": "svc-bot"}, "pr": None}):
            with self.assertRaises(gate_reviewers.GateReviewersError):
                self.report(gates=["G1"])

    def test_pr_closed_blocked(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        with self.mock_env(self.base_mock(pr=default_pr(state="closed"))):
            with self.assertRaises(gate_reviewers.GateReviewersError):
                self.report(gates=["G1"])

    def test_pr_merged_blocked(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        with self.mock_env(self.base_mock(pr=default_pr(state="closed", merged=True))):
            with self.assertRaises(gate_reviewers.GateReviewersError):
                self.report(gates=["G1"])

    def test_repo_mismatch_blocked(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        with self.mock_env(self.base_mock(pr=default_pr(base_full_name="other/repo"))):
            with self.assertRaises(gate_reviewers.GateReviewersError):
                self.report(gates=["G1"])

    def test_draft_allowed_and_reported(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        with self.mock_env(self.base_mock(pr=default_pr(draft=True))):
            result = self.report(gates=["G1"])
        self.assertTrue(result["pr_draft"])

    def test_as_bot_mismatch_blocked_exit1(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        with self.mock_env(self.base_mock(bot="someone-else")):
            with self.assertRaises(gate_reviewers.GateReviewersError):
                self.report(gates=["G1"], as_bot="svc-bot")

    def test_allow_classification_absent_or_mismatched_errors_before_any_github_call(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={}, classification="internal")
        with self.assertRaises(gate_reviewers.GateReviewersError):
            self.report(gates=["G1"], allow_classification=None)
        with self.assertRaises(gate_reviewers.GateReviewersError):
            self.report(gates=["G1"], allow_classification="restricted")


# --------------------------------------------------------------------------
# Orthogonality
# --------------------------------------------------------------------------


class OrthogonalityTests(GateReviewersTestCase):
    def test_input_files_byte_identical_after_report(self):
        self.write_overlay(gates=simple_gates(), authorities=simple_authorities())
        record_path = self.overlay / "runs/T1/run-record.json"
        dispatch_path = self.overlay / "runs/T1/dispatch-plan.json"
        authorities_path = self.overlay / "authorities.json"
        before = {p: p.read_bytes() for p in (record_path, dispatch_path, authorities_path)}
        users, collaborators = all_collaborators_all_exist(["po-user", "el-user", "sa-user"])
        with self.mock_env(self.base_mock(users=users, collaborators=collaborators)):
            self.report()
        for path, content in before.items():
            self.assertEqual(content, path.read_bytes(), f"{path} was modified by request-gate-reviewers")

    def test_no_write_http_method_used_anywhere(self):
        for path_name in ("gate_reviewers.py", "github_write.py"):
            source = (PLUGIN_ROOT / "agentic_sdlc" / path_name).read_text(encoding="utf-8")
            for verb in ('"POST"', '"PUT"', '"PATCH"', '"DELETE"', "--method"):
                self.assertNotIn(verb, source, f"{path_name} contains a write-method reference: {verb}")

    def test_no_apply_flag_in_cli_wiring(self):
        source = (PLUGIN_ROOT / "agentic_sdlc" / "__init__.py").read_text(encoding="utf-8")
        # Isolate the request_gate_reviewers wiring block specifically.
        start = source.index('request_gate_reviewers = subparsers.add_parser(')
        end = source.index("decide = subparsers.add_parser(")
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
        self.assertIn("request-gate-reviewers", result.stdout)

    def test_report_via_cli_exit0_when_clean(self):
        read_payload = {
            "identity": {"login": "svc-bot"},
            "pr": default_pr(),
            "requested_reviewers": {"users": [], "teams": []},
            "users": {"po-user": True, "el-user": True, "sa-user": True},
            "collaborators": {
                "owner/proj:po-user": True, "owner/proj:el-user": True, "owner/proj:sa-user": True,
            },
        }
        read_path = self.root / "github-read.json"
        read_path.write_text(json.dumps(read_payload), encoding="utf-8")
        reviews_path = self.root / "reviews.json"
        reviews_path.write_text(json.dumps([]), encoding="utf-8")
        result = self.run_cli(
            "request-gate-reviewers", "--task-id", "T1", "--repo", "owner/proj", "--pr", "42",
            "--as-bot", "svc-bot", "--allow-classification", "internal",
            env={
                github_write.GITHUB_READ_MOCK_ENV_VAR: str(read_path),
                "AGENTIC_SDLC_TEST_GITHUB_REVIEWS_FILE": str(reviews_path),
            },
        )
        self.assertEqual([], result["refusals"])
        self.assertEqual(3, len(result["reviewers"]))

    def test_missing_required_flag_is_argparse_error(self):
        result = subprocess.run(
            CLI_COMMAND + ["request-gate-reviewers", "--task-id", "T1", "--root", str(self.root)],
            text=True, capture_output=True, check=False,
        )
        self.assertNotEqual(0, result.returncode)

    def test_no_list_gate_reviewer_requests_command(self):
        result = subprocess.run(CLI_COMMAND + ["--help"], text=True, capture_output=True, check=False)
        self.assertNotIn("list-gate-reviewer-requests", result.stdout)


if __name__ == "__main__":
    unittest.main()
