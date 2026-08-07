"""Tests for `create-github-gate-issues` / `list-github-gate-issues`
(`agentic_sdlc/gate_issues_github.py`, `agentic_sdlc/github_issue_write.py`).

No `gh` binary or network access is required -- every GitHub call is mocked
via `AGENTIC_SDLC_TEST_GITHUB_READ_FILE` (identity/user-exists/collaborator
pre-checks, reused from `github_write.py`) and
`AGENTIC_SDLC_TEST_GITHUB_ISSUE_FILE` (issue search/create/verify/repo/labels,
see `github_issue_write.py`'s module docstring for the multiplexed
mock-file convention).
"""

from __future__ import annotations

import hashlib
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
from agentic_sdlc import gate_issues, gate_issues_github, github_issue_write, github_write  # type: ignore

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


def make_ar(authority_id, role, *, applicability="applicable", rationale="Assigned in project authority map"):
    return {
        "authority_id": authority_id,
        "authority_type": "human-approver",
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


class GateIssuesGithubTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.overlay = self.root / ".agentic-sdlc"
        (self.overlay / "runs" / "T1").mkdir(parents=True)
        self.addCleanup(self.temporary.cleanup)
        # Never sleep for real in tests -- WRITE_DELAY_SECONDS is applied
        # between mutative calls only; patched to 0 so the suite stays fast.
        patcher = mock.patch.object(github_issue_write, "WRITE_DELAY_SECONDS", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_overlay(self, *, task_id="T1", classification="internal", disposition="pending",
                       scope="Build the widget service", re_entry_count=0, gates, configured_gate_ids=None,
                       authorities, dispatch_fingerprint="sha256:" + "a" * 64):
        (self.overlay / "project.json").write_text(json.dumps({"classification": classification}), encoding="utf-8")
        (self.overlay / "authorities.json").write_text(json.dumps(authorities), encoding="utf-8")
        (self.overlay / "runs" / task_id).mkdir(parents=True, exist_ok=True)
        record = {
            "classification": classification,
            "disposition": disposition,
            "scope": scope,
            "re_entry_history": [{}] * re_entry_count,
            "lifecycle_gates": gates,
        }
        (self.overlay / "runs" / task_id / "run-record.json").write_text(json.dumps(record), encoding="utf-8")
        configured = configured_gate_ids if configured_gate_ids is not None else [g["gate_id"] for g in gates]
        dispatch = {
            "dispatch_fingerprint": dispatch_fingerprint,
            "gate_dispatch": [{"gate_id": gid, "status": "required"} for gid in configured],
        }
        (self.overlay / "runs" / task_id / "dispatch-plan.json").write_text(json.dumps(dispatch), encoding="utf-8")

    def mock_env(self, *, read=None, issue=None):
        read_payload = {"identity": {"login": "svc-bot"}, "users": {}, "collaborators": {}}
        if read:
            read_payload.update(read)
        issue_payload = {"repo": {"has_issues": True, "private": True}, "labels": {}, "search": {}, "create": {}, "verify": {}, "assignee_update": {}}
        if issue:
            issue_payload.update(issue)
        read_path = self.root / "read_mock.json"
        issue_path = self.root / "issue_mock.json"
        read_path.write_text(json.dumps(read_payload), encoding="utf-8")
        issue_path.write_text(json.dumps(issue_payload), encoding="utf-8")
        return mock.patch.dict(os.environ, {
            github_write.GITHUB_READ_MOCK_ENV_VAR: str(read_path),
            github_issue_write.GITHUB_ISSUE_MOCK_ENV_VAR: str(issue_path),
        })

    def dry_run(self, **kwargs):
        kwargs.setdefault("root", self.root)
        kwargs.setdefault("task_id", "T1")
        kwargs.setdefault("repo", "org/repo")
        kwargs.setdefault("as_bot", "svc-bot")
        kwargs.setdefault("gates", None)
        kwargs.setdefault("apply", False)
        kwargs.setdefault("plan_digest", None)
        kwargs.setdefault("allow_classification", "internal")
        kwargs.setdefault("include_scope", False)
        kwargs.setdefault("reconcile_assignees", False)
        kwargs.setdefault("allow_public_repo", True)
        kwargs.setdefault("break_lock", False)
        kwargs.setdefault("i_know_this_is_mocked", False)
        return gate_issues_github.run(**kwargs)

    def apply_run(self, plan_digest, **kwargs):
        kwargs["apply"] = True
        kwargs["plan_digest"] = plan_digest
        kwargs.setdefault("i_know_this_is_mocked", True)
        return self.dry_run(**kwargs)

    def build_plan_for(self, dry, *, task_id="T1", repo="org/repo", include_scope=False):
        record = json.loads((self.overlay / "runs" / task_id / "run-record.json").read_text())
        dispatch = json.loads((self.overlay / "runs" / task_id / "dispatch-plan.json").read_text())
        authorities = json.loads((self.overlay / "authorities.json").read_text())
        contracts = {g["id"]: g for g in agentic_sdlc.load_json(agentic_sdlc.CONTRACTS / "lifecycle-gates.json")["gates"]}
        return gate_issues_github.build_plan(
            task_id=task_id, repo=repo, gate_ids=dry["gate_ids"], record=record, authorities=authorities,
            dispatch_plan=dispatch, lifecycle_contracts=contracts, include_scope=include_scope,
            scope_text=record.get("scope") if include_scope else None,
        )

    def default_mock_for(self, dry, *, bot="svc-bot", task_id="T1", repo="org/repo", include_scope=False):
        """Build a mock pair that will `create` (never reuse) every gate and
        approval issue in `dry`'s scope, verifying cleanly."""
        gate_plans, approval_candidates, _, _, _ = self.build_plan_for(dry, task_id=task_id, repo=repo, include_scope=include_scope)
        read_payload = {"identity": {"login": bot}, "users": {}, "collaborators": {}}
        issue_payload = {"repo": {"has_issues": True, "private": True}, "labels": {}, "search": {}, "create": {}, "verify": {}, "assignee_update": {}}
        number = 1
        for gp in gate_plans:
            issue_payload["search"][gp.label] = []
            issue_payload["create"][f"agentic-sdlc,{gp.label}"] = {"number": number}
            issue_payload["verify"][str(number)] = {
                "title": gp.title, "state": "open", "labels": [{"name": "agentic-sdlc"}, {"name": gp.label}],
                "assignees": [], "user": {"login": bot}, "repository_url": f"https://api.github.com/repos/{repo}",
            }
            number += 1
        for ac in approval_candidates:
            issue_payload["search"][ac.label] = []
            issue_payload["create"][f"agentic-sdlc,{ac.label}"] = {"number": number}
            issue_payload["verify"][str(number)] = {
                "title": ac.title, "state": "open", "labels": [{"name": "agentic-sdlc"}, {"name": ac.label}],
                "assignees": [{"login": ac.login}], "user": {"login": bot},
                "repository_url": f"https://api.github.com/repos/{repo}",
            }
            read_payload["users"][ac.login] = True
            read_payload["collaborators"][f"{repo}:{ac.login}"] = True
            number += 1
        return read_payload, issue_payload

    def mock_env_pair(self, read_payload, issue_payload):
        read_path = self.root / "read_mock.json"
        issue_path = self.root / "issue_mock.json"
        read_path.write_text(json.dumps(read_payload), encoding="utf-8")
        issue_path.write_text(json.dumps(issue_payload), encoding="utf-8")
        return mock.patch.dict(os.environ, {
            github_write.GITHUB_READ_MOCK_ENV_VAR: str(read_path),
            github_issue_write.GITHUB_ISSUE_MOCK_ENV_VAR: str(issue_path),
        })


# --------------------------------------------------------------------------
# Field mapping (8)
# --------------------------------------------------------------------------


class FieldMappingTests(GateIssuesGithubTestCase):
    def test_gate_lookup_by_id_clean_error_if_absent(self):
        self.write_overlay(gates=simple_gates(), authorities=simple_authorities())
        with self.assertRaises(gate_issues_github.GateIssuesGithubError) as ctx:
            self.dry_run(gates=["G9"])
        self.assertIn("G9", str(ctx.exception))

    def test_no_raw_task_id_or_scope_anywhere(self):
        self.write_overlay(task_id="super-secret-task", gates=simple_gates(), authorities=simple_authorities())
        result = self.dry_run(task_id="super-secret-task")
        for item in result["gate_issues"]:
            self.assertNotIn("super-secret-task", item["label"])
            self.assertNotIn("super-secret-task", item["marker"])
        gp = gate_issues_github.build_plan(
            task_id="super-secret-task", repo="org/repo", gate_ids=["G1"],
            record=json.loads((self.overlay / "runs/super-secret-task/run-record.json").read_text()),
            authorities=simple_authorities(),
            dispatch_plan=json.loads((self.overlay / "runs/super-secret-task/dispatch-plan.json").read_text()),
            lifecycle_contracts={g["id"]: g for g in agentic_sdlc.load_json(agentic_sdlc.CONTRACTS / "lifecycle-gates.json")["gates"]},
            include_scope=False, scope_text=None,
        )[0][0]
        self.assertNotIn("super-secret-task", gp.title)
        self.assertNotIn("super-secret-task", gp.description)

    def test_include_scope_off_by_default_sanitized_when_on(self):
        self.write_overlay(gates=simple_gates(), authorities=simple_authorities(), scope="check /confirm @mention #1")
        lifecycle_contracts = {g["id"]: g for g in agentic_sdlc.load_json(agentic_sdlc.CONTRACTS / "lifecycle-gates.json")["gates"]}
        record = json.loads((self.overlay / "runs/T1/run-record.json").read_text())
        dispatch = json.loads((self.overlay / "runs/T1/dispatch-plan.json").read_text())
        gp_off = gate_issues_github.build_plan(
            task_id="T1", repo="org/repo", gate_ids=["G1"], record=record, authorities=simple_authorities(),
            dispatch_plan=dispatch, lifecycle_contracts=lifecycle_contracts, include_scope=False, scope_text=None,
        )[0][0]
        self.assertNotIn("Scope:", gp_off.description)
        gp_on = gate_issues_github.build_plan(
            task_id="T1", repo="org/repo", gate_ids=["G1"], record=record, authorities=simple_authorities(),
            dispatch_plan=dispatch, lifecycle_contracts=lifecycle_contracts, include_scope=True,
            scope_text=record["scope"],
        )[0][0]
        self.assertIn("Scope:", gp_on.description)
        self.assertNotIn("@mention", gp_on.description)
        self.assertIn("@​mention", gp_on.description)

    def test_one_approval_issue_per_authority_requirement_multi_authority(self):
        self.write_overlay(gates=simple_gates(), authorities=simple_authorities())
        result = self.dry_run()
        self.assertEqual(3, len(result["gate_issues"]))
        self.assertEqual(4, len(result["approval_issues"]))
        g2_authorities = {item["authority_id"] for item in result["approval_issues"] if item["gate_id"] == "G2"}
        self.assertEqual({"product_owner", "engineering_lead"}, g2_authorities)

    def test_not_applicable_authority_requirement_skipped_with_rationale(self):
        gates = [make_gate("G4", authority_requirements=[
            make_ar("governance_lead", "Governance Lead"),
            make_ar("data_control_owner", "Data/Control Owner", applicability="not-applicable", rationale="No regulated data in scope"),
        ])]
        authorities = {
            "governance_lead": make_authority(assignee="human:gov", github_login="gov-user"),
            "data_control_owner": make_authority(status="unknown", assignee=None),
        }
        self.write_overlay(gates=gates, authorities=authorities)
        result = self.dry_run(gates=["G4"])
        self.assertEqual(1, len(result["approval_issues"]))
        self.assertEqual(1, len(result["skipped"]))
        self.assertEqual("not-applicable", result["skipped"][0]["reason"])
        self.assertEqual("No regulated data in scope", result["skipped"][0]["rationale"])

    def test_marker_domain_separation_across_all_six_marker_kinds(self):
        task_id, gate_id, authority_id = "T1", "G2", "engineering_lead"
        gl_gate = gate_issues.compute_gate_marker(task_id, gate_id)
        gl_approval = gate_issues.compute_approval_marker(task_id, gate_id, authority_id)
        gh_gate = gate_issues_github.compute_gate_marker(task_id, gate_id)
        gh_approval = gate_issues_github.compute_approval_marker(task_id, gate_id, authority_id)
        gate_status_marker = hashlib.sha256(f"gate-status\x00{task_id}".encode()).hexdigest()[:16]
        requirement_marker = hashlib.sha256(f"{task_id}\x00{gate_id}\x00{authority_id}".encode()).hexdigest()[:16]
        markers = {gl_gate, gl_approval, gh_gate, gh_approval, gate_status_marker, requirement_marker}
        self.assertEqual(6, len(markers))

    def test_label_charset_and_length_conformance(self):
        gate_marker = gate_issues_github.compute_gate_marker("T1", "G1")
        approval_marker = gate_issues_github.compute_approval_marker("T1", "G1", "product_owner")
        for label in (gate_issues_github.gate_label(gate_marker), gate_issues_github.approval_label(approval_marker)):
            self.assertRegex(label, r"^[a-z0-9-]+$")
            self.assertLessEqual(len(label), 50)

    def test_parent_reference_line_emitted_verbatim_and_rejected_from_free_text(self):
        description = gate_issues_github.render_approval_description("T1", "G1", "abc123", "org/repo", 42, None)
        self.assertIn("> parent org/repo#42", description)
        with self.assertRaises(gate_issues_github.GateIssuesGithubError):
            gate_issues_github.sanitize_free_text("> parent evil/project#1", "test field")


# --------------------------------------------------------------------------
# Idempotency (13) + idempotency mechanism (4)
# --------------------------------------------------------------------------


class IdempotencyTests(GateIssuesGithubTestCase):
    def test_second_run_reuses_existing_labeled_gate_issue_no_create_call(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        dry = self.dry_run(gates=["G1"])
        label = dry["gate_issues"][0]["label"]
        issue = {
            "search": {label: [{"number": 9, "labels": [{"name": "agentic-sdlc"}, {"name": label}]}]},
            "create": {f"agentic-sdlc,{label}": {"number": 999}},  # would fail if ever called
            "verify": {"9": {"title": "x", "state": "open", "labels": [{"name": "agentic-sdlc"}, {"name": label}],
                              "assignees": [], "user": {"login": "svc-bot"}, "repository_url": "https://api.github.com/repos/org/repo"}},
        }
        with self.mock_env(issue=issue):
            result = self.apply_run(dry["plan_digest"], gates=["G1"])
        self.assertEqual("reused", result["gate_results"][0]["status"])
        self.assertEqual(9, result["gate_results"][0]["issue_number"])

    def test_multiple_matches_blocked_exit2(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        dry = self.dry_run(gates=["G1"])
        label = dry["gate_issues"][0]["label"]
        issue = {"search": {label: [{"number": 1}, {"number": 2}]}}
        with self.mock_env(issue=issue):
            with self.assertRaises(gate_issues_github.GateIssuesGithubBlocked):
                self.apply_run(dry["plan_digest"], gates=["G1"])

    def test_result_cap_exceeded_blocked(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        dry = self.dry_run(gates=["G1"])
        label = dry["gate_issues"][0]["label"]
        issue = {"search": {label: [{"number": n} for n in range(20)]}}
        with self.mock_env(issue=issue):
            with self.assertRaises(gate_issues_github.GateIssuesGithubBlocked) as ctx:
                self.apply_run(dry["plan_digest"], gates=["G1"])
        self.assertIn("result-cap-exceeded", str(ctx.exception))

    def test_missing_anchor_label_blocked(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        dry = self.dry_run(gates=["G1"])
        label = dry["gate_issues"][0]["label"]
        issue = {"search": {label: [{"number": 9, "labels": [{"name": label}]}]}}
        with self.mock_env(issue=issue):
            with self.assertRaises(gate_issues_github.GateIssuesGithubBlocked):
                self.apply_run(dry["plan_digest"], gates=["G1"])

    def test_foreign_sibling_label_blocked(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        dry = self.dry_run(gates=["G1"])
        label = dry["gate_issues"][0]["label"]
        issue = {"search": {label: [{"number": 9, "labels": [
            {"name": "agentic-sdlc"}, {"name": label}, {"name": "agentic-sdlc-gh-gate-deadbeefcafef00d"},
        ]}]}}
        with self.mock_env(issue=issue):
            with self.assertRaises(gate_issues_github.GateIssuesGithubBlocked):
                self.apply_run(dry["plan_digest"], gates=["G1"])

    def test_author_mismatch_blocked_ledger_suspect(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        dry = self.dry_run(gates=["G1"])
        label = dry["gate_issues"][0]["label"]
        issue = {
            "search": {label: [{"number": 9, "labels": [{"name": "agentic-sdlc"}, {"name": label}]}]},
            "verify": {"9": {"title": "x", "state": "open", "labels": [{"name": "agentic-sdlc"}, {"name": label}],
                              "assignees": [], "user": {"login": "attacker"}, "repository_url": "https://api.github.com/repos/org/repo"}},
        }
        with self.mock_env(issue=issue):
            with self.assertRaises(gate_issues_github.GateIssuesGithubBlocked):
                self.apply_run(dry["plan_digest"], gates=["G1"])
        ledger = gate_issues_github.read_ledger(self.root, "T1")
        self.assertEqual("suspect", ledger["entries"]["G1"]["status"])

    def test_ledger_claiming_created_with_no_matching_issue_still_creates(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        dry = self.dry_run(gates=["G1"])
        ledger = gate_issues_github.read_ledger(self.root, "T1")
        ledger["entries"]["G1"] = {"kind": "gate", "status": "created", "issue_number": 42}
        gate_issues_github.write_ledger(self.root, "T1", ledger)
        read_payload, issue_payload = self.default_mock_for(dry)
        with self.mock_env_pair(read_payload, issue_payload):
            result = self.apply_run(dry["plan_digest"], gates=["G1"])
        self.assertEqual("created", result["gate_results"][0]["status"])

    def test_apply_without_plan_digest_errors(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        with self.assertRaises(gate_issues_github.GateIssuesGithubError):
            self.dry_run(apply=True, gates=["G1"], i_know_this_is_mocked=True)

    def test_stale_digest_blocked(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        with self.assertRaises(gate_issues_github.GateIssuesGithubBlocked):
            self.apply_run("sha256:" + "0" * 64, gates=["G1"])

    def test_digest_recomputed_mid_run_aborts_after_authorities_change(self):
        gates = simple_gates()
        self.write_overlay(gates=gates, authorities=simple_authorities())
        dry = self.dry_run()
        read_payload, issue_payload = self.default_mock_for(dry)

        original_read_ledger = gate_issues_github.read_ledger
        call_count = {"n": 0}

        def flaky_read_ledger(root, task_id):
            call_count["n"] += 1
            if call_count["n"] == 1:
                authorities_path = self.overlay / "authorities.json"
                data = json.loads(authorities_path.read_text())
                data["product_owner"]["github_login"] = "someone-else"
                authorities_path.write_text(json.dumps(data), encoding="utf-8")
            return original_read_ledger(root, task_id)

        with self.mock_env_pair(read_payload, issue_payload):
            with mock.patch.object(gate_issues_github, "read_ledger", side_effect=flaky_read_ledger):
                with self.assertRaises(gate_issues_github.GateIssuesGithubBlocked):
                    self.apply_run(dry["plan_digest"])

    def test_digest_recomputed_mid_run_aborts_after_rationale_only_change(self):
        gates = simple_gates()
        self.write_overlay(gates=gates, authorities=simple_authorities())
        dry = self.dry_run()
        read_payload, issue_payload = self.default_mock_for(dry)

        original_read_ledger = gate_issues_github.read_ledger
        call_count = {"n": 0}

        def flaky_read_ledger(root, task_id):
            call_count["n"] += 1
            if call_count["n"] == 1:
                record_path = self.overlay / "runs" / "T1" / "run-record.json"
                data = json.loads(record_path.read_text())
                for gate in data["lifecycle_gates"]:
                    if gate["gate_id"] == "G1":
                        gate["applicability_rationale"] = "Rationale changed mid-run"
                record_path.write_text(json.dumps(data), encoding="utf-8")
            return original_read_ledger(root, task_id)

        with self.mock_env_pair(read_payload, issue_payload):
            with mock.patch.object(gate_issues_github, "read_ledger", side_effect=flaky_read_ledger):
                with self.assertRaises(gate_issues_github.GateIssuesGithubBlocked):
                    self.apply_run(dry["plan_digest"])

    def test_lock_held_break_lock_released_on_success_and_exception(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        lock_path = gate_issues_github._lock_path(self.root, "T1")
        held = gate_issues_github.acquire_lock(self.root, "T1", break_lock=False)
        self.assertTrue(held.is_file())
        dry = self.dry_run(gates=["G1"])
        read_payload, issue_payload = self.default_mock_for(dry)
        with self.mock_env_pair(read_payload, issue_payload):
            with self.assertRaises(gate_issues_github.GateIssuesGithubBlocked):
                self.apply_run(dry["plan_digest"], gates=["G1"])
            result = self.apply_run(dry["plan_digest"], gates=["G1"], break_lock=True)
        self.assertEqual("created", result["gate_results"][0]["status"])
        self.assertFalse(lock_path.is_file())

        self.write_overlay(gates=[make_gate("G1")], authorities={})
        dry2 = self.dry_run(gates=["G1"])
        label2 = dry2["gate_issues"][0]["label"]
        bad_issue = {"search": {label2: [{"number": 1}, {"number": 2}]}}
        with self.mock_env(issue=bad_issue):
            with self.assertRaises(gate_issues_github.GateIssuesGithubBlocked):
                self.apply_run(dry2["plan_digest"], gates=["G1"])
        self.assertFalse(lock_path.is_file())

    def test_ledger_status_creating_written_before_create_call(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        dry = self.dry_run(gates=["G1"])
        read_payload, issue_payload = self.default_mock_for(dry)

        seen_statuses = []
        original_create = github_issue_write.create_issue

        def spying_create(*args, **kwargs):
            ledger = gate_issues_github.read_ledger(self.root, "T1")
            seen_statuses.append(ledger["entries"]["G1"]["status"])
            return original_create(*args, **kwargs)

        with self.mock_env_pair(read_payload, issue_payload):
            with mock.patch.object(github_issue_write, "create_issue", side_effect=spying_create):
                self.apply_run(dry["plan_digest"], gates=["G1"])
        self.assertEqual(["creating"], seen_statuses)

    # -- Idempotency mechanism (4) --

    def test_source_never_contains_search_api_literal(self):
        for module in ("gate_issues_github.py", "github_issue_write.py"):
            source = (PLUGIN_ROOT / "agentic_sdlc" / module).read_text(encoding="utf-8")
            self.assertNotIn("search/issues", source)
            self.assertNotIn('"/search"', source)
            self.assertNotIn("'/search'", source)

    def test_existence_query_argv_is_marker_only_state_all_no_paginate(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        dry = self.dry_run(gates=["G1"])
        label = dry["gate_issues"][0]["label"]
        captured = {}
        original_run = github_issue_write._run_gh

        def spy(argv):
            if "issues?labels=" in argv[-1]:
                captured["argv"] = argv
            return original_run(argv)

        read_payload, issue_payload = self.default_mock_for(dry)
        # Force a real (non-mocked) search call path to inspect the argv by
        # clearing the issue mock's search key for this label and patching
        # _run_gh instead -- simplest is to call search_issues_by_label
        # directly without any mock env set.
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(github_issue_write.GITHUB_ISSUE_MOCK_ENV_VAR, None)
            with mock.patch.object(github_issue_write, "_run_gh", side_effect=spy) as spied:
                with mock.patch.object(subprocess, "run") as run_mock:
                    run_mock.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"[]", stderr=b"")
                    github_issue_write.search_issues_by_label("org/repo", label)
        self.assertIn("argv", captured)
        argv = captured["argv"]
        expected_tail = f"repos/org/repo/issues?labels={label}&state=all&per_page=20"
        self.assertEqual(expected_tail, argv[-1])
        self.assertNotIn("--paginate", argv)

    def test_create_and_refetch_argv_shape(self):
        captured_create = {}
        captured_verify = {}
        original_write = github_issue_write._run_gh_write
        original_run = github_issue_write._run_gh

        def spy_write(argv, body, **kwargs):
            captured_create["argv"] = argv
            return b'{"number": 1}'

        def spy_run(argv):
            captured_verify["argv"] = argv
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b'{"number": 1, "title": "x", "state": "open", "labels": [], "assignees": [], "user": {"login": "svc-bot"}, "repository_url": "https://api.github.com/repos/org/repo"}', stderr=b"")

        with mock.patch.object(github_issue_write, "_run_gh_write", side_effect=spy_write):
            with mock.patch.object(github_issue_write, "_run_gh", side_effect=spy_run):
                github_issue_write.create_issue("org/repo", "title", "body", ["agentic-sdlc", "x"])
                github_issue_write.fetch_issue_verification("org/repo", 1)
        self.assertIn("repos/org/repo/issues", captured_create["argv"])
        self.assertIn("--method", captured_create["argv"])
        self.assertIn("POST", captured_create["argv"])
        self.assertIn("repos/org/repo/issues/1", captured_verify["argv"])

    def test_read_your_own_writes_create_then_lookup_reuses_not_duplicates(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        dry = self.dry_run(gates=["G1"])
        label = dry["gate_issues"][0]["label"]
        read_payload, issue_payload = self.default_mock_for(dry)
        with self.mock_env_pair(read_payload, issue_payload):
            first = self.apply_run(dry["plan_digest"], gates=["G1"])
        self.assertEqual("created", first["gate_results"][0]["status"])
        number = first["gate_results"][0]["issue_number"]
        # Simulate a second run seeing the created issue via search.
        issue_payload["search"][label] = [{"number": number, "labels": [{"name": "agentic-sdlc"}, {"name": label}]}]
        with self.mock_env_pair(read_payload, issue_payload):
            second = self.apply_run(dry["plan_digest"], gates=["G1"])
        self.assertEqual("reused", second["gate_results"][0]["status"])
        self.assertEqual(number, second["gate_results"][0]["issue_number"])


# --------------------------------------------------------------------------
# Pull-request filtering (3)
# --------------------------------------------------------------------------


class PullRequestFilteringTests(GateIssuesGithubTestCase):
    def test_entry_with_pull_request_key_blocks(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        dry = self.dry_run(gates=["G1"])
        label = dry["gate_issues"][0]["label"]
        issue = {"search": {label: [{"number": 1, "pull_request": {"url": "x"}}]}}
        with self.mock_env(issue=issue):
            with self.assertRaises(gate_issues_github.GateIssuesGithubBlocked) as ctx:
                self.apply_run(dry["plan_digest"], gates=["G1"])
        self.assertIn("label-on-pull-request", str(ctx.exception))

    def test_mixed_issue_and_pr_response_blocks(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        dry = self.dry_run(gates=["G1"])
        label = dry["gate_issues"][0]["label"]
        issue = {"search": {label: [
            {"number": 1, "labels": [{"name": "agentic-sdlc"}, {"name": label}]},
            {"number": 2, "pull_request": {"url": "x"}},
        ]}}
        with self.mock_env(issue=issue):
            with self.assertRaises(gate_issues_github.GateIssuesGithubBlocked):
                self.apply_run(dry["plan_digest"], gates=["G1"])

    def test_clean_issue_only_response_unaffected(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        dry = self.dry_run(gates=["G1"])
        label = dry["gate_issues"][0]["label"]
        issue = {"search": {label: [{"number": 1, "labels": [{"name": "agentic-sdlc"}, {"name": label}]}]},
                 "verify": {"1": {"title": "x", "state": "open", "labels": [{"name": "agentic-sdlc"}, {"name": label}],
                                   "assignees": [], "user": {"login": "svc-bot"}, "repository_url": "https://api.github.com/repos/org/repo"}}}
        with self.mock_env(issue=issue):
            result = self.apply_run(dry["plan_digest"], gates=["G1"])
        self.assertEqual("reused", result["gate_results"][0]["status"])


# --------------------------------------------------------------------------
# Unresolvable identity (7)
# --------------------------------------------------------------------------


class UnresolvableIdentityTests(GateIssuesGithubTestCase):
    def test_authority_unknown(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("ghost", "Ghost")])]
        self.write_overlay(gates=gates, authorities={})
        result = self.dry_run(gates=["G1"])
        self.assertEqual("authority-unknown", result["refusals"][0]["reason"])

    def test_authority_unassigned(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "PO")])]
        authorities = {"product_owner": make_authority(status="unassigned", assignee=None)}
        self.write_overlay(gates=gates, authorities=authorities)
        result = self.dry_run(gates=["G1"])
        self.assertEqual("authority-unassigned", result["refusals"][0]["reason"])

    def test_no_github_binding_both_directions(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "PO")])]
        authorities = {"product_owner": make_authority(assignee="gitlab.com/po")}
        self.write_overlay(gates=gates, authorities=authorities)
        result = self.dry_run(gates=["G1"])
        self.assertEqual("no-github-binding", result["refusals"][0]["reason"])

        authorities2 = {"product_owner": make_authority(assignee="github.com/po")}
        self.write_overlay(gates=gates, authorities=authorities2)
        result2 = self.dry_run(gates=["G1"])
        self.assertEqual(1, len(result2["approval_issues"]))
        self.assertEqual([], result2["refusals"])

    def test_mixed_refusal_and_success_exits_2_both_lists_populated(self):
        gates = [make_gate("G1", authority_requirements=[
            make_ar("product_owner", "PO"), make_ar("ghost", "Ghost"),
        ])]
        authorities = {"product_owner": make_authority(assignee="human:po", github_login="po-user")}
        self.write_overlay(gates=gates, authorities=authorities)
        result = self.dry_run(gates=["G1"])
        self.assertEqual(1, len(result["approval_issues"]))
        self.assertEqual(1, len(result["refusals"]))

    def test_no_approval_issue_ever_created_without_an_assignee(self):
        source = (PLUGIN_ROOT / "agentic_sdlc" / "gate_issues_github.py").read_text(encoding="utf-8")
        self.assertIn("assignees=[ac.login]", source)

    def test_github_user_unresolved_refusal(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "PO")])]
        authorities = {"product_owner": make_authority(assignee="human:po", github_login="ghost-user")}
        self.write_overlay(gates=gates, authorities=authorities)
        dry = self.dry_run(gates=["G1"])
        gate_label = dry["gate_issues"][0]["label"]
        approval_label = dry["approval_issues"][0]["label"]
        read = {"users": {"ghost-user": False}, "collaborators": {}}
        issue = {
            "search": {gate_label: [], approval_label: []},
            "create": {f"agentic-sdlc,{gate_label}": {"number": 1}},
            "verify": {"1": {"title": dry["gate_issues"][0], "state": "open", "labels": [{"name": "agentic-sdlc"}, {"name": gate_label}],
                              "assignees": [], "user": {"login": "svc-bot"}, "repository_url": "https://api.github.com/repos/org/repo"}},
        }
        gp, _, _, _, _ = self.build_plan_for(dry)
        issue["verify"]["1"]["title"] = gp[0].title
        with self.mock_env(read=read, issue=issue):
            result = self.apply_run(dry["plan_digest"], gates=["G1"])
        self.assertEqual("github-user-unresolved", result["refusals"][0]["reason"])

    def test_not_a_collaborator_refusal(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "PO")])]
        authorities = {"product_owner": make_authority(assignee="human:po", github_login="outside-user")}
        self.write_overlay(gates=gates, authorities=authorities)
        dry = self.dry_run(gates=["G1"])
        gate_label = dry["gate_issues"][0]["label"]
        approval_label = dry["approval_issues"][0]["label"]
        gp, _, _, _, _ = self.build_plan_for(dry)
        read = {"users": {"outside-user": True}, "collaborators": {"org/repo:outside-user": False}}
        issue = {
            "search": {gate_label: [], approval_label: []},
            "create": {f"agentic-sdlc,{gate_label}": {"number": 1}},
            "verify": {"1": {"title": gp[0].title, "state": "open", "labels": [{"name": "agentic-sdlc"}, {"name": gate_label}],
                              "assignees": [], "user": {"login": "svc-bot"}, "repository_url": "https://api.github.com/repos/org/repo"}},
        }
        with self.mock_env(read=read, issue=issue):
            result = self.apply_run(dry["plan_digest"], gates=["G1"])
        self.assertEqual("not-a-collaborator", result["refusals"][0]["reason"])

    def test_github_user_ambiguous_reason_code_absent(self):
        self.assertNotIn("github-user-ambiguous", gate_issues_github.REASON_CODES)
        source = (PLUGIN_ROOT / "agentic_sdlc" / "gate_issues_github.py").read_text(encoding="utf-8")
        self.assertNotIn("github-user-ambiguous", source)


# --------------------------------------------------------------------------
# Assignee semantics (3)
# --------------------------------------------------------------------------


class AssigneeSemanticsTests(GateIssuesGithubTestCase):
    def _single_approval_setup(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "PO")])]
        authorities = {"product_owner": make_authority(assignee="human:po", github_login="po-user")}
        self.write_overlay(gates=gates, authorities=authorities)
        dry = self.dry_run(gates=["G1"])
        gp, ac, _, _, _ = self.build_plan_for(dry)
        return dry, gp[0], ac[0]

    def test_post_create_assignees_empty_despite_success_blocks(self):
        dry, gp, ac = self._single_approval_setup()
        read = {"users": {"po-user": True}, "collaborators": {"org/repo:po-user": True}}
        issue = {
            "search": {gp.label: [], ac.label: []},
            "create": {f"agentic-sdlc,{gp.label}": {"number": 1}, f"agentic-sdlc,{ac.label}": {"number": 2}},
            "verify": {
                "1": {"title": gp.title, "state": "open", "labels": [{"name": "agentic-sdlc"}, {"name": gp.label}],
                      "assignees": [], "user": {"login": "svc-bot"}, "repository_url": "https://api.github.com/repos/org/repo"},
                "2": {"title": ac.title, "state": "open", "labels": [{"name": "agentic-sdlc"}, {"name": ac.label}],
                      "assignees": [], "user": {"login": "svc-bot"}, "repository_url": "https://api.github.com/repos/org/repo"},
            },
        }
        with self.mock_env(read=read, issue=issue):
            with self.assertRaises(gate_issues_github.GateIssuesGithubBlocked):
                self.apply_run(dry["plan_digest"], gates=["G1"])
        ledger = gate_issues_github.read_ledger(self.root, "T1")
        self.assertEqual("suspect", ledger["entries"]["G1/product_owner"]["status"])

    def test_drift_on_reuse_reported_not_overwritten(self):
        dry, gp, ac = self._single_approval_setup()
        issue = {
            "search": {
                gp.label: [{"number": 1, "labels": [{"name": "agentic-sdlc"}, {"name": gp.label}]}],
                ac.label: [{"number": 2, "labels": [{"name": "agentic-sdlc"}, {"name": ac.label}]}],
            },
            "verify": {
                "1": {"title": gp.title, "state": "open", "labels": [{"name": "agentic-sdlc"}, {"name": gp.label}],
                      "assignees": [], "user": {"login": "svc-bot"}, "repository_url": "https://api.github.com/repos/org/repo"},
                "2": {"title": ac.title, "state": "open", "labels": [{"name": "agentic-sdlc"}, {"name": ac.label}],
                      "assignees": [{"login": "someone-else"}], "user": {"login": "svc-bot"},
                      "repository_url": "https://api.github.com/repos/org/repo"},
            },
        }
        with self.mock_env(issue=issue):
            result = self.apply_run(dry["plan_digest"], gates=["G1"])
        self.assertEqual("assignee_changed", result["approval_results"][0]["drift"])
        self.assertTrue(result["drift_detected"])

    def test_reconcile_assignees_patches_and_reverifies_drop_still_blocks(self):
        dry, gp, ac = self._single_approval_setup()
        issue = {
            "search": {
                gp.label: [{"number": 1, "labels": [{"name": "agentic-sdlc"}, {"name": gp.label}]}],
                ac.label: [{"number": 2, "labels": [{"name": "agentic-sdlc"}, {"name": ac.label}]}],
            },
            "verify": {
                "1": {"title": gp.title, "state": "open", "labels": [{"name": "agentic-sdlc"}, {"name": gp.label}],
                      "assignees": [], "user": {"login": "svc-bot"}, "repository_url": "https://api.github.com/repos/org/repo"},
                "2": {"title": ac.title, "state": "open", "labels": [{"name": "agentic-sdlc"}, {"name": ac.label}],
                      "assignees": [], "user": {"login": "svc-bot"}, "repository_url": "https://api.github.com/repos/org/repo"},
            },
            "assignee_update": {"2": {}},
        }
        with self.mock_env(issue=issue):
            with self.assertRaises(gate_issues_github.GateIssuesGithubBlocked) as ctx:
                self.apply_run(dry["plan_digest"], gates=["G1"], reconcile_assignees=True)
        self.assertIn("silently dropped", str(ctx.exception))


# --------------------------------------------------------------------------
# Self-approval (4)
# --------------------------------------------------------------------------


class SelfApprovalTests(GateIssuesGithubTestCase):
    def test_preparer_match_refuses_no_issue_created(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")],
                            preparers=[{"id": "human:po"}])]
        authorities = {"product_owner": make_authority(assignee="human:po", github_login="po-user")}
        self.write_overlay(gates=gates, authorities=authorities)
        result = self.dry_run(gates=["G1"])
        self.assertEqual(0, len(result["approval_issues"]))
        self.assertEqual("self-approval", result["refusals"][0]["reason"])

    def test_independent_verifier_match_refuses(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")],
                            independent_verifier={"id": "human:po"})]
        authorities = {"product_owner": make_authority(assignee="human:po", github_login="po-user")}
        self.write_overlay(gates=gates, authorities=authorities)
        result = self.dry_run(gates=["G1"])
        self.assertEqual("self-approval", result["refusals"][0]["reason"])

    def test_empty_preparers_and_none_verifier_passes_vacuously(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")],
                            preparers=[], independent_verifier=None)]
        authorities = {"product_owner": make_authority(assignee="human:po", github_login="po-user")}
        self.write_overlay(gates=gates, authorities=authorities)
        result = self.dry_run(gates=["G1"])
        self.assertEqual(1, len(result["approval_issues"]))
        self.assertEqual([], result["refusals"])

    def test_every_approval_description_names_approve_from_github_pr(self):
        description = gate_issues_github.render_approval_description("T1", "G1", "abc", "org/repo", 1, None)
        self.assertIn("Tracking artifact only", description)
        self.assertIn("not approval evidence", description)
        self.assertIn("must not be a preparer or the independent verifier", description)
        self.assertIn("approve-from-github-pr", description)
        self.assertNotIn("approve-from-gitlab-mr", description)


# --------------------------------------------------------------------------
# Orthogonality (3)
# --------------------------------------------------------------------------


class OrthogonalityTests(GateIssuesGithubTestCase):
    def test_input_files_byte_identical_after_full_apply_run(self):
        self.write_overlay(gates=simple_gates(), authorities=simple_authorities())
        record_path = self.overlay / "runs/T1/run-record.json"
        dispatch_path = self.overlay / "runs/T1/dispatch-plan.json"
        authorities_path = self.overlay / "authorities.json"
        before = {p: p.read_bytes() for p in (record_path, dispatch_path, authorities_path)}
        dry = self.dry_run()
        read_payload, issue_payload = self.default_mock_for(dry)
        with self.mock_env_pair(read_payload, issue_payload):
            self.apply_run(dry["plan_digest"])
        for path, content in before.items():
            self.assertEqual(content, path.read_bytes(), f"{path} was modified by create-github-gate-issues")

    def test_never_writes_approval_or_disposition_fields(self):
        self.write_overlay(gates=simple_gates(), authorities=simple_authorities())
        record_path = self.overlay / "runs/T1/run-record.json"
        dry = self.dry_run()
        read_payload, issue_payload = self.default_mock_for(dry)
        with self.mock_env_pair(read_payload, issue_payload):
            self.apply_run(dry["plan_digest"])
        record = json.loads(record_path.read_text())
        for gate in record["lifecycle_gates"]:
            self.assertEqual([], gate.get("human_approvals", []))
            self.assertEqual([], gate.get("evidence_refs", []))
            self.assertIn(gate["status"], {"pending", "ready"})
        self.assertEqual("pending", record["disposition"])

    def test_module_never_imports_approval_adapters(self):
        for module in ("gate_issues_github.py", "github_issue_write.py"):
            source = (PLUGIN_ROOT / "agentic_sdlc" / module).read_text(encoding="utf-8")
            import_lines = [line for line in source.splitlines() if line.startswith("from . import") or line.startswith("import ")]
            forbidden = {"record_github_approval", "record_gitlab_approval", "record_gate_decision", "record_github_issue_link", "record_gitlab_issue_link"}
            imported_names = set()
            for line in import_lines:
                imported_names.update(name.strip() for name in line.split("import", 1)[1].split(","))
            self.assertEqual(set(), forbidden & imported_names)


# --------------------------------------------------------------------------
# Eligibility fail-closed (8)
# --------------------------------------------------------------------------


class EligibilityFailClosedTests(GateIssuesGithubTestCase):
    def test_gate_not_in_dispatch_plan(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={}, configured_gate_ids=[])
        with self.assertRaises(gate_issues_github.GateIssuesGithubBlocked):
            self.dry_run(gates=["G1"])

    def test_not_applicable(self):
        self.write_overlay(gates=[make_gate("G1", applicability="not-applicable")], authorities={})
        with self.assertRaises(gate_issues_github.GateIssuesGithubBlocked):
            self.dry_run(gates=["G1"])

    def test_invalidated(self):
        self.write_overlay(gates=[make_gate("G1", status="invalidated")], authorities={})
        with self.assertRaises(gate_issues_github.GateIssuesGithubBlocked):
            self.dry_run(gates=["G1"])

    def test_pending_reentry(self):
        self.write_overlay(gates=[make_gate("G1", required_reentry_gate="G1")], authorities={})
        with self.assertRaises(gate_issues_github.GateIssuesGithubBlocked):
            self.dry_run(gates=["G1"])

    def test_classification_absent_errors_before_any_github_call(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        with self.assertRaises(gate_issues_github.GateIssuesGithubError):
            self.dry_run(gates=["G1"], allow_classification=None)

    def test_classification_mismatch_errors(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        with self.assertRaises(gate_issues_github.GateIssuesGithubError):
            self.dry_run(gates=["G1"], allow_classification="restricted")

    def test_mocked_without_ack_refused_including_read_mock_only(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        dry = self.dry_run(gates=["G1"])
        read_path = self.root / "read_mock.json"
        read_path.write_text(json.dumps({"identity": {"login": "svc-bot"}}), encoding="utf-8")
        with mock.patch.dict(os.environ, {github_write.GITHUB_READ_MOCK_ENV_VAR: str(read_path)}):
            os.environ.pop(github_issue_write.GITHUB_ISSUE_MOCK_ENV_VAR, None)
            with self.assertRaises(gate_issues_github.GateIssuesGithubError):
                self.apply_run(dry["plan_digest"], gates=["G1"], i_know_this_is_mocked=False)

    def test_max_issues_per_run_exceeded_aborts_without_truncating(self):
        gates = [
            make_gate(f"G{n}", authority_requirements=[make_ar(f"a{n}", f"A{n}")])
            for n in range(1, 11)
        ]
        # 10 gates + 10 approvals = 20, still under 40; scale authority
        # requirements per gate to exceed MAX_ISSUES_PER_RUN=40.
        gates = [
            make_gate(f"G{n}", authority_requirements=[make_ar(f"a{n}_{i}", f"A{n}_{i}") for i in range(4)])
            for n in range(1, 11)
        ]
        authorities = {}
        for n in range(1, 11):
            for i in range(4):
                authorities[f"a{n}_{i}"] = make_authority(assignee=f"human:a{n}_{i}", github_login=f"login{n}_{i}")
        self.write_overlay(gates=gates, authorities=authorities)
        with self.assertRaises(gate_issues_github.GateIssuesGithubError):
            self.dry_run()

    def test_public_repo_and_issues_disabled_preflight(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        dry = self.dry_run(gates=["G1"])
        issue = {"repo": {"has_issues": False, "private": True}}
        with self.mock_env(issue=issue):
            with self.assertRaises(gate_issues_github.GateIssuesGithubError):
                self.apply_run(dry["plan_digest"], gates=["G1"])
        issue2 = {"repo": {"has_issues": True, "private": False}}
        with self.mock_env(issue=issue2):
            with self.assertRaises(gate_issues_github.GateIssuesGithubError):
                self.apply_run(dry["plan_digest"], gates=["G1"], allow_public_repo=False)


# --------------------------------------------------------------------------
# State vocabulary (1)
# --------------------------------------------------------------------------


class StateVocabularyTests(GateIssuesGithubTestCase):
    def test_state_opened_gitlab_vocabulary_is_a_failure(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        dry = self.dry_run(gates=["G1"])
        gp, _, _, _, _ = self.build_plan_for(dry)
        label = dry["gate_issues"][0]["label"]
        issue = {
            "search": {label: []},
            "create": {f"agentic-sdlc,{label}": {"number": 1}},
            "verify": {"1": {"title": gp[0].title, "state": "opened", "labels": [{"name": "agentic-sdlc"}, {"name": label}],
                              "assignees": [], "user": {"login": "svc-bot"}, "repository_url": "https://api.github.com/repos/org/repo"}},
        }
        with self.mock_env(issue=issue):
            with self.assertRaises(gate_issues_github.GateIssuesGithubBlocked) as ctx:
                self.apply_run(dry["plan_digest"], gates=["G1"])
        self.assertIn("state", str(ctx.exception))


# --------------------------------------------------------------------------
# No-link-type surface (2)
# --------------------------------------------------------------------------


class NoLinkTypeSurfaceTests(GateIssuesGithubTestCase):
    def test_source_never_contains_link_type_or_relates_to_token(self):
        for module in ("gate_issues_github.py", "github_issue_write.py"):
            source = (PLUGIN_ROOT / "agentic_sdlc" / module).read_text(encoding="utf-8")
            self.assertNotIn("relates_to", source)
            self.assertNotIn("link_type", source)
            self.assertNotIn("--link-type", source)

    def test_cli_rejects_link_type_flag(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        result = subprocess.run(
            CLI_COMMAND + ["create-github-gate-issues", "--task-id", "T1", "--repo", "org/repo",
                            "--as-bot", "svc-bot", "--allow-classification", "internal",
                            "--link-type", "relates_to", "--root", temporary.name],
            text=True, capture_output=True, check=False,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("unrecognized arguments", result.stderr)


# --------------------------------------------------------------------------
# Rate-limit detection (3)
# --------------------------------------------------------------------------


class RateLimitDetectionTests(unittest.TestCase):
    def test_detects_throttle_signature(self):
        self.assertTrue(github_issue_write._is_secondary_rate_limit_error(
            "gh: You have exceeded a secondary rate limit. Please wait a few minutes before you try again."
        ))

    def test_does_not_fire_on_unrelated_403(self):
        self.assertFalse(github_issue_write._is_secondary_rate_limit_error("gh: HTTP 403 Forbidden"))

    def test_does_not_fire_on_unrelated_error(self):
        self.assertFalse(github_issue_write._is_secondary_rate_limit_error("gh: connection reset by peer"))


# --------------------------------------------------------------------------
# Error wrapping (2)
# --------------------------------------------------------------------------


class ErrorWrappingTests(GateIssuesGithubTestCase):
    def test_gate_processing_valueerror_wrapped_with_gate_id(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        dry = self.dry_run(gates=["G1"])
        with self.mock_env():
            with mock.patch.object(github_issue_write, "search_issues_by_label", side_effect=ValueError("boom")):
                with self.assertRaises(gate_issues_github.GateIssuesGithubError) as ctx:
                    self.apply_run(dry["plan_digest"], gates=["G1"])
        self.assertIn("G1", str(ctx.exception))

    def test_approval_processing_valueerror_wrapped_with_gate_and_authority_id(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "PO")])]
        authorities = {"product_owner": make_authority(assignee="human:po", github_login="po-user")}
        self.write_overlay(gates=gates, authorities=authorities)
        dry = self.dry_run(gates=["G1"])
        gp, ac, _, _, _ = self.build_plan_for(dry)
        read = {}
        issue = {
            "search": {gp[0].label: [], ac[0].label: []},
            "create": {f"agentic-sdlc,{gp[0].label}": {"number": 1}},
            "verify": {"1": {"title": gp[0].title, "state": "open", "labels": [{"name": "agentic-sdlc"}, {"name": gp[0].label}],
                              "assignees": [], "user": {"login": "svc-bot"}, "repository_url": "https://api.github.com/repos/org/repo"}},
        }
        with self.mock_env(read=read, issue=issue):
            with mock.patch.object(github_write, "check_github_user_exists", side_effect=ValueError("boom")):
                with self.assertRaises(gate_issues_github.GateIssuesGithubError) as ctx:
                    self.apply_run(dry["plan_digest"], gates=["G1"])
        self.assertIn("product_owner", str(ctx.exception))


# --------------------------------------------------------------------------
# Parity (3)
# --------------------------------------------------------------------------


class ParityTests(unittest.TestCase):
    def test_fixed_label_identical_across_modules(self):
        from agentic_sdlc import gitlab_write
        self.assertEqual("agentic-sdlc", github_issue_write.FIXED_LABEL)
        self.assertEqual(gitlab_write.FIXED_LABEL, github_issue_write.FIXED_LABEL)
        self.assertEqual(gate_issues_github.FIXED_LABEL, github_issue_write.FIXED_LABEL)

    def test_marker_domain_tags_pairwise_disjoint_prefixes(self):
        prefixes = [
            gate_issues.GATE_LABEL_PREFIX, gate_issues.APPROVAL_LABEL_PREFIX,
            gate_issues_github.GATE_LABEL_PREFIX, gate_issues_github.APPROVAL_LABEL_PREFIX,
        ]
        for i, a in enumerate(prefixes):
            for b in prefixes[i + 1:]:
                self.assertFalse(a.startswith(b) or b.startswith(a), f"{a!r} and {b!r} are not disjoint")

    def test_refusal_codes_differ_only_by_documented_substitutions(self):
        gitlab_reasons = {
            "authority-unknown", "authority-unassigned", "applicability-unknown", "self-approval",
            "no-gitlab-binding", "gitlab-user-unresolved", "gitlab-user-ambiguous",
        }
        github_reasons = gate_issues_github.REASON_CODES
        shared = {"authority-unknown", "authority-unassigned", "applicability-unknown", "self-approval"}
        self.assertTrue(shared.issubset(gitlab_reasons))
        self.assertTrue(shared.issubset(github_reasons))
        self.assertIn("no-github-binding", github_reasons)
        self.assertIn("github-user-unresolved", github_reasons)
        self.assertIn("not-a-collaborator", github_reasons)
        self.assertNotIn("github-user-ambiguous", github_reasons)


# --------------------------------------------------------------------------
# Digest cross-forge incompatibility
# --------------------------------------------------------------------------


class DigestCrossForgeTests(GateIssuesGithubTestCase):
    def test_gitlab_digest_structurally_incapable_of_validating_github_apply(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        github_dry = self.dry_run(gates=["G1"])
        record = json.loads((self.overlay / "runs/T1/run-record.json").read_text())
        dispatch = json.loads((self.overlay / "runs/T1/dispatch-plan.json").read_text())
        authorities = json.loads((self.overlay / "authorities.json").read_text())
        contracts = {g["id"]: g for g in agentic_sdlc.load_json(agentic_sdlc.CONTRACTS / "lifecycle-gates.json")["gates"]}
        _, _, _, _, per_gate = gate_issues.build_plan(
            task_id="T1", project_path="org/repo", gate_ids=["G1"], record=record, authorities=authorities,
            dispatch_plan=dispatch, lifecycle_contracts=contracts, include_scope=False, scope_text=None,
        )
        gitlab_digest = gate_issues.compute_plan_digest(
            task_id="T1", project_path="org/repo", gate_ids=["G1"],
            dispatch_fingerprint_value=dispatch.get("dispatch_fingerprint"), per_gate=per_gate,
            disposition=record.get("disposition"), classification=record.get("classification"),
            re_entry_count=len(record.get("re_entry_history", [])),
        )
        self.assertNotEqual(gitlab_digest, github_dry["plan_digest"])


# --------------------------------------------------------------------------
# CLI wiring (3)
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

    def test_dry_run_then_apply_via_cli_and_list_github_gate_issues(self):
        dry = self.run_cli(
            "create-github-gate-issues", "--task-id", "T1", "--repo", "org/repo", "--as-bot", "svc-bot",
            "--allow-classification", "internal", "--allow-public-repo", "--dry-run",
        )
        overlay = self.root / ".agentic-sdlc"
        record = json.loads((overlay / "runs" / "T1" / "run-record.json").read_text())
        dispatch = json.loads((overlay / "runs" / "T1" / "dispatch-plan.json").read_text())
        authorities = json.loads((overlay / "authorities.json").read_text())
        contracts = {g["id"]: g for g in agentic_sdlc.load_json(agentic_sdlc.CONTRACTS / "lifecycle-gates.json")["gates"]}
        gate_plans, approval_candidates, _, _, _ = gate_issues_github.build_plan(
            task_id="T1", repo="org/repo", gate_ids=dry["gate_ids"], record=record, authorities=authorities,
            dispatch_plan=dispatch, lifecycle_contracts=contracts, include_scope=False, scope_text=None,
        )
        read_payload = {"identity": {"login": "svc-bot"}, "users": {}, "collaborators": {}}
        issue_payload = {"repo": {"has_issues": True, "private": True}, "labels": {}, "search": {}, "create": {}, "verify": {}, "assignee_update": {}}
        number = 1
        for gp in gate_plans:
            issue_payload["search"][gp.label] = []
            issue_payload["create"][f"agentic-sdlc,{gp.label}"] = {"number": number}
            issue_payload["verify"][str(number)] = {
                "title": gp.title, "state": "open", "labels": [{"name": "agentic-sdlc"}, {"name": gp.label}],
                "assignees": [], "user": {"login": "svc-bot"}, "repository_url": "https://api.github.com/repos/org/repo",
            }
            number += 1
        for ac in approval_candidates:
            issue_payload["search"][ac.label] = []
            issue_payload["create"][f"agentic-sdlc,{ac.label}"] = {"number": number}
            issue_payload["verify"][str(number)] = {
                "title": ac.title, "state": "open", "labels": [{"name": "agentic-sdlc"}, {"name": ac.label}],
                "assignees": [{"login": ac.login}], "user": {"login": "svc-bot"},
                "repository_url": "https://api.github.com/repos/org/repo",
            }
            read_payload["users"][ac.login] = True
            read_payload["collaborators"][f"org/repo:{ac.login}"] = True
            number += 1
        read_path = self.root / "read_mock.json"
        issue_path = self.root / "issue_mock.json"
        read_path.write_text(json.dumps(read_payload), encoding="utf-8")
        issue_path.write_text(json.dumps(issue_payload), encoding="utf-8")
        apply_result = self.run_cli(
            "create-github-gate-issues", "--task-id", "T1", "--repo", "org/repo", "--as-bot", "svc-bot",
            "--allow-classification", "internal", "--allow-public-repo", "--apply",
            "--plan-digest", dry["plan_digest"], "--i-know-this-is-mocked",
            env={
                github_write.GITHUB_READ_MOCK_ENV_VAR: str(read_path),
                github_issue_write.GITHUB_ISSUE_MOCK_ENV_VAR: str(issue_path),
            },
        )
        self.assertEqual([], apply_result["refusals"])
        listed = self.run_cli("list-github-gate-issues", "--task-id", "T1")
        self.assertIn("G1", listed["entries"])

    def test_missing_plan_digest_on_apply_is_exit_1(self):
        self.run_cli(
            "create-github-gate-issues", "--task-id", "T1", "--repo", "org/repo", "--as-bot", "svc-bot",
            "--allow-classification", "internal", "--allow-public-repo", "--apply", expected=1,
        )

    def test_refusals_present_is_exit_2(self):
        overlay = self.root / ".agentic-sdlc"
        gates = [make_gate("G1", authority_requirements=[make_ar("ghost", "Ghost")])]
        record = {
            "classification": "internal", "disposition": "pending", "scope": "s", "re_entry_history": [],
            "lifecycle_gates": gates,
        }
        (overlay / "runs" / "T1" / "run-record.json").write_text(json.dumps(record), encoding="utf-8")
        dispatch = {
            "dispatch_fingerprint": "sha256:" + "a" * 64,
            "gate_dispatch": [{"gate_id": "G1", "status": "required"}],
        }
        (overlay / "runs" / "T1" / "dispatch-plan.json").write_text(json.dumps(dispatch), encoding="utf-8")
        (overlay / "authorities.json").write_text(json.dumps({}), encoding="utf-8")
        dry = self.run_cli(
            "create-github-gate-issues", "--task-id", "T1", "--repo", "org/repo", "--as-bot", "svc-bot",
            "--allow-classification", "internal", "--allow-public-repo", "--dry-run",
            expected=2,  # dry-run already reports a non-empty refusals[] for the unknown "ghost" authority
        )
        read_payload = {"identity": {"login": "svc-bot"}, "users": {}, "collaborators": {}}
        issue_payload = {"repo": {"has_issues": True, "private": True}, "labels": {}, "search": {gate_issues_github.gate_label(dry["gate_issues"][0]["marker"]): []},
                          "create": {}, "verify": {}, "assignee_update": {}}
        contracts = {g["id"]: g for g in agentic_sdlc.load_json(agentic_sdlc.CONTRACTS / "lifecycle-gates.json")["gates"]}
        gate_plans, _, _, _, _ = gate_issues_github.build_plan(
            task_id="T1", repo="org/repo", gate_ids=dry["gate_ids"], record=record, authorities={},
            dispatch_plan=dispatch, lifecycle_contracts=contracts, include_scope=False, scope_text=None,
        )
        issue_payload["create"][f"agentic-sdlc,{gate_plans[0].label}"] = {"number": 1}
        issue_payload["verify"]["1"] = {
            "title": gate_plans[0].title, "state": "open",
            "labels": [{"name": "agentic-sdlc"}, {"name": gate_plans[0].label}],
            "assignees": [], "user": {"login": "svc-bot"}, "repository_url": "https://api.github.com/repos/org/repo",
        }
        read_path = self.root / "read_mock.json"
        issue_path = self.root / "issue_mock.json"
        read_path.write_text(json.dumps(read_payload), encoding="utf-8")
        issue_path.write_text(json.dumps(issue_payload), encoding="utf-8")
        self.run_cli(
            "create-github-gate-issues", "--task-id", "T1", "--repo", "org/repo", "--as-bot", "svc-bot",
            "--allow-classification", "internal", "--allow-public-repo", "--apply",
            "--plan-digest", dry["plan_digest"], "--i-know-this-is-mocked",
            env={
                github_write.GITHUB_READ_MOCK_ENV_VAR: str(read_path),
                github_issue_write.GITHUB_ISSUE_MOCK_ENV_VAR: str(issue_path),
            },
            expected=2,
        )


if __name__ == "__main__":
    unittest.main()
