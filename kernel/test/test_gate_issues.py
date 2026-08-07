"""Tests for `create-gate-issues` / `list-gate-issues`
(`agentic_sdlc/gate_issues.py`, `agentic_sdlc/gitlab_write.py`).

Exercises the module directly (fast, precise control over run-record /
authorities.json / dispatch-plan.json fixtures) rather than through
`init`/`plan`, plus a small number of subprocess CLI-level tests to prove
the `create-gate-issues`/`list-gate-issues` subcommands are wired
correctly end to end. No `glab` binary or network access is required --
every GitLab call is mocked via `AGENTIC_SDLC_TEST_ISSUE_CREATE_FILE`
(see `gitlab_write.py`'s module docstring for the multiplexed mock-file
convention).
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
from agentic_sdlc import gate_issues, gitlab_write  # type: ignore

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


class GateIssuesTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.overlay = self.root / ".agentic-sdlc"
        (self.overlay / "runs" / "T1").mkdir(parents=True)
        self.addCleanup(self.temporary.cleanup)

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

    def mock_env(self, payload):
        path = self.root / "mock.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return mock.patch.dict(os.environ, {gitlab_write.ISSUE_CREATE_MOCK_ENV_VAR: str(path)})

    def dry_run(self, **kwargs):
        kwargs.setdefault("root", self.root)
        kwargs.setdefault("task_id", "T1")
        kwargs.setdefault("project_path", "grp/proj")
        kwargs.setdefault("as_bot", "svc-bot")
        kwargs.setdefault("gates", None)
        kwargs.setdefault("apply", False)
        kwargs.setdefault("plan_digest", None)
        kwargs.setdefault("allow_classification", "internal")
        kwargs.setdefault("link_type", None)
        kwargs.setdefault("include_scope", False)
        kwargs.setdefault("reconcile_assignees", False)
        kwargs.setdefault("break_lock", False)
        kwargs.setdefault("i_know_this_is_mocked", False)
        return gate_issues.run(**kwargs)

    def apply_run(self, plan_digest, **kwargs):
        kwargs["apply"] = True
        kwargs["plan_digest"] = plan_digest
        kwargs.setdefault("i_know_this_is_mocked", True)
        return self.dry_run(**kwargs)

    def default_mock_for(self, dry, *, bot="svc-bot", extra_verify=None, task_id="T1", project_path="grp/proj",
                          include_scope=False):
        """Build a mock file that will `create` (never reuse) every gate
        and approval issue in `dry`'s scope, verifying cleanly. Recomputes
        the exact plan (titles included) via build_plan() using the same
        overlay files write_overlay() just wrote, so mocked `verify`
        responses match what the module will actually send."""
        record = json.loads((self.overlay / "runs" / task_id / "run-record.json").read_text())
        dispatch = json.loads((self.overlay / "runs" / task_id / "dispatch-plan.json").read_text())
        authorities = json.loads((self.overlay / "authorities.json").read_text())
        contracts = {g["id"]: g for g in agentic_sdlc.load_json(agentic_sdlc.CONTRACTS / "lifecycle-gates.json")["gates"]}
        gate_plans, approval_candidates, _, _, _ = gate_issues.build_plan(
            task_id=task_id, project_path=project_path, gate_ids=dry["gate_ids"], record=record,
            authorities=authorities, dispatch_plan=dispatch, lifecycle_contracts=contracts,
            include_scope=include_scope, scope_text=record.get("scope") if include_scope else None,
        )
        mock_payload = {"identity": {"username": bot}, "search": {}, "create": {}, "verify": {}, "users": {}}
        iid = 1
        for gp in gate_plans:
            key = f"{gate_issues.FIXED_LABEL},{gp.label}"
            mock_payload["search"][key] = []
            mock_payload["create"][key] = {"iid": iid}
            mock_payload["verify"][str(iid)] = {
                "title": gp.title, "state": "opened", "labels": [gate_issues.FIXED_LABEL, gp.label],
                "assignees": [], "confidential": False, "author": {"username": bot}, "project_path": project_path,
            }
            iid += 1
        for ac in approval_candidates:
            key = f"{gate_issues.FIXED_LABEL},{ac.label}"
            mock_payload["search"][key] = []
            mock_payload["create"][key] = {"iid": iid}
            mock_payload["verify"][str(iid)] = {
                "title": ac.title, "state": "opened", "labels": [gate_issues.FIXED_LABEL, ac.label],
                "assignees": [{"username": ac.username}], "confidential": False,
                "author": {"username": bot}, "project_path": project_path,
            }
            mock_payload["users"][ac.username] = [{"id": iid + 1000, "username": ac.username, "state": "active"}]
            iid += 1
        if extra_verify:
            mock_payload["verify"].update(extra_verify)
        return mock_payload


# --------------------------------------------------------------------------
# Simple single-gate/single-authority fixture used by most tests
# --------------------------------------------------------------------------


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


class FieldMappingTests(GateIssuesTestCase):
    """Items 1-7."""

    def test_gate_array_lookup_by_id_not_index_clean_error_if_absent(self):
        self.write_overlay(gates=simple_gates(), authorities=simple_authorities())
        with self.assertRaises(gate_issues.GateIssuesError) as ctx:
            self.dry_run(gates=["G9"])
        self.assertIn("G9", str(ctx.exception))

    def test_gate_issue_fields_exclude_raw_task_id_and_scope(self):
        self.write_overlay(task_id="super-secret-task", gates=simple_gates(), authorities=simple_authorities())
        result = self.dry_run(task_id="super-secret-task")
        for item in result["gate_issues"]:
            self.assertNotIn("super-secret-task", item["label"])
            self.assertNotIn("super-secret-task", item["marker"])
        # Also verify the rendered title/description never leak the raw id.
        gp = gate_issues.build_plan(
            task_id="super-secret-task", project_path="grp/proj", gate_ids=["G1"],
            record=json.loads((self.overlay / "runs/super-secret-task/run-record.json").read_text()),
            authorities=simple_authorities(),
            dispatch_plan=json.loads((self.overlay / "runs/super-secret-task/dispatch-plan.json").read_text()),
            lifecycle_contracts={g["id"]: g for g in agentic_sdlc.load_json(agentic_sdlc.CONTRACTS / "lifecycle-gates.json")["gates"]},
            include_scope=False, scope_text=None,
        )[0][0]
        self.assertNotIn("super-secret-task", gp.title)
        self.assertNotIn("super-secret-task", gp.description)

    def test_include_scope_off_by_default_sanitized_when_on_description_only(self):
        self.write_overlay(gates=simple_gates(), authorities=simple_authorities(), scope="check /confirm @mention #1")
        off = self.dry_run(gates=["G1"])
        self.assertNotIn("Scope:", "".join(off["gate_issues"][0].keys()))  # no field leaks scope anywhere in dry-run summary
        lifecycle_contracts = {g["id"]: g for g in agentic_sdlc.load_json(agentic_sdlc.CONTRACTS / "lifecycle-gates.json")["gates"]}
        record = json.loads((self.overlay / "runs/T1/run-record.json").read_text())
        dispatch = json.loads((self.overlay / "runs/T1/dispatch-plan.json").read_text())
        gp_off = gate_issues.build_plan(
            task_id="T1", project_path="grp/proj", gate_ids=["G1"], record=record, authorities=simple_authorities(),
            dispatch_plan=dispatch, lifecycle_contracts=lifecycle_contracts, include_scope=False, scope_text=None,
        )[0][0]
        self.assertNotIn("Scope:", gp_off.description)
        gp_on = gate_issues.build_plan(
            task_id="T1", project_path="grp/proj", gate_ids=["G1"], record=record, authorities=simple_authorities(),
            dispatch_plan=dispatch, lifecycle_contracts=lifecycle_contracts, include_scope=True,
            scope_text=record["scope"],
        )[0][0]
        self.assertIn("Scope:", gp_on.description)
        # Mid-line "/confirm" is not a quick-action (only a line *starting*
        # with '/' is rejected); @mention/#1 are neutralized with a ZWSP so
        # GitLab never autolinks them.
        self.assertNotIn("@mention", gp_on.description)
        self.assertIn("@​mention", gp_on.description)
        self.assertNotIn("#1\n", gp_on.description)
        self.assertIn("#​1", gp_on.description)

    def test_one_approval_issue_per_applicable_authority_requirement_and_multi_authority_counts(self):
        self.write_overlay(gates=simple_gates(), authorities=simple_authorities())
        result = self.dry_run()
        self.assertEqual(3, len(result["gate_issues"]))
        self.assertEqual(4, len(result["approval_issues"]))  # G1:1, G2:2, G3:1
        g2_authorities = {item["authority_id"] for item in result["approval_issues"] if item["gate_id"] == "G2"}
        self.assertEqual({"product_owner", "engineering_lead"}, g2_authorities)

    def test_not_applicable_authority_requirement_is_skipped_with_rationale(self):
        gates = [make_gate("G4", authority_requirements=[
            make_ar("governance_lead", "Governance Lead"),
            make_ar("data_control_owner", "Data/Control Owner", applicability="not-applicable", rationale="No regulated data in scope"),
        ])]
        authorities = {
            "governance_lead": make_authority(assignee="human:gov", gitlab_username="gov-user"),
            "data_control_owner": make_authority(status="unknown", assignee=None),
        }
        self.write_overlay(gates=gates, authorities=authorities)
        result = self.dry_run(gates=["G4"])
        self.assertEqual(1, len(result["approval_issues"]))
        self.assertEqual(1, len(result["skipped"]))
        self.assertEqual("not-applicable", result["skipped"][0]["reason"])
        self.assertEqual("No regulated data in scope", result["skipped"][0]["rationale"])

    def test_marker_domain_separation_from_gate_approval_and_requirement_issue_markers(self):
        task_id, gate_id, authority_id = "T1", "G2", "engineering_lead"
        gate_marker = gate_issues.compute_gate_marker(task_id, gate_id)
        approval_marker = gate_issues.compute_approval_marker(task_id, gate_id, authority_id)
        # Mirrors agentic_sdlc_langgraph.requirement_issues.compute_marker's formula exactly
        # (no leading domain tag): hashlib.sha256(f"{task_id}\x00{gate_id}\x00{item_key}")[:16].
        import hashlib
        requirement_item_marker = hashlib.sha256(f"{task_id}\x00{gate_id}\x00{authority_id}".encode()).hexdigest()[:16]
        self.assertEqual(3, len({gate_marker, approval_marker, requirement_item_marker}))

    def test_label_charset_conformance(self):
        gate_marker = gate_issues.compute_gate_marker("T1", "G1")
        approval_marker = gate_issues.compute_approval_marker("T1", "G1", "product_owner")
        for label in (gate_issues.gate_label(gate_marker), gate_issues.approval_label(approval_marker)):
            self.assertRegex(label, r"^[a-z0-9-]+$")

    def test_parent_reference_line_emitted_verbatim_and_rejected_from_free_text(self):
        description = gate_issues.render_approval_description("T1", "G1", "abc123", "grp/proj", 42, None)
        self.assertIn("> parent grp/proj#42", description)
        with self.assertRaises(gate_issues.GateIssuesError):
            gate_issues.sanitize_free_text("> parent evil/project#1", "test field")


class IdempotencyTests(GateIssuesTestCase):
    """Items 8-16."""

    def test_second_run_reuses_existing_labeled_gate_issue_no_create_call(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        dry = self.dry_run(gates=["G1"])
        marker = dry["gate_issues"][0]["marker"]
        label = gate_issues.gate_label(marker)
        mock_payload = {
            "identity": {"username": "svc-bot"},
            "search": {f"{gate_issues.FIXED_LABEL},{label}": [{"iid": 9, "labels": [gate_issues.FIXED_LABEL, label]}]},
            "create": {f"{gate_issues.FIXED_LABEL},{label}": {"iid": 999}},  # would fail if ever called
            "verify": {"9": {"title": "x", "state": "opened", "labels": [gate_issues.FIXED_LABEL, label],
                              "assignees": [], "confidential": False, "author": {"username": "svc-bot"},
                              "project_path": "grp/proj"}},
        }
        with self.mock_env(mock_payload):
            result = self.apply_run(dry["plan_digest"], gates=["G1"])
        self.assertEqual("reused", result["gate_results"][0]["status"])
        self.assertEqual(9, result["gate_results"][0]["issue_iid"])

    def test_two_search_hits_blocked_exit2_no_create(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        dry = self.dry_run(gates=["G1"])
        label = gate_issues.gate_label(dry["gate_issues"][0]["marker"])
        mock_payload = {
            "identity": {"username": "svc-bot"},
            "search": {f"{gate_issues.FIXED_LABEL},{label}": [{"iid": 1}, {"iid": 2}]},
            "create": {}, "verify": {},
        }
        with self.mock_env(mock_payload):
            with self.assertRaises(gate_issues.GateIssuesBlocked):
                self.apply_run(dry["plan_digest"], gates=["G1"])

    def test_foreign_anchor_label_on_matched_issue_blocked(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        dry = self.dry_run(gates=["G1"])
        marker = dry["gate_issues"][0]["marker"]
        label = gate_issues.gate_label(marker)
        mock_payload = {
            "identity": {"username": "svc-bot"},
            "search": {f"{gate_issues.FIXED_LABEL},{label}": [{"iid": 9, "labels": [label, "agentic-sdlc-gate-deadbeefcafef00d"]}]},
            "create": {}, "verify": {},
        }
        with self.mock_env(mock_payload):
            with self.assertRaises(gate_issues.GateIssuesBlocked):
                self.apply_run(dry["plan_digest"], gates=["G1"])

    def test_matched_issue_author_mismatch_blocked_ledger_suspect_no_reuse(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        dry = self.dry_run(gates=["G1"])
        label = gate_issues.gate_label(dry["gate_issues"][0]["marker"])
        mock_payload = {
            "identity": {"username": "svc-bot"},
            "search": {f"{gate_issues.FIXED_LABEL},{label}": [{"iid": 9, "labels": [gate_issues.FIXED_LABEL, label]}]},
            "create": {},
            "verify": {"9": {"title": "x", "state": "opened", "labels": [gate_issues.FIXED_LABEL, label],
                              "assignees": [], "confidential": False, "author": {"username": "attacker"},
                              "project_path": "grp/proj"}},
        }
        with self.mock_env(mock_payload):
            with self.assertRaises(gate_issues.GateIssuesBlocked):
                self.apply_run(dry["plan_digest"], gates=["G1"])
        ledger = gate_issues.read_ledger(self.root, "T1")
        self.assertEqual("suspect", ledger["entries"]["G1"]["status"])

    def test_ledger_claiming_created_with_no_matching_issue_still_creates(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        dry = self.dry_run(gates=["G1"])
        label = gate_issues.gate_label(dry["gate_issues"][0]["marker"])
        ledger = gate_issues.read_ledger(self.root, "T1")
        ledger["entries"]["G1"] = {"kind": "gate", "status": "created", "issue_iid": 42}
        gate_issues.write_ledger(self.root, "T1", ledger)
        mock_payload = self.default_mock_for(dry)
        with self.mock_env(mock_payload):
            result = self.apply_run(dry["plan_digest"], gates=["G1"])
        self.assertEqual("created", result["gate_results"][0]["status"])

    def test_apply_without_plan_digest_errors(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        with self.assertRaises(gate_issues.GateIssuesError):
            self.dry_run(apply=True, gates=["G1"], i_know_this_is_mocked=True)

    def test_stale_digest_blocked(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        with self.assertRaises(gate_issues.GateIssuesBlocked):
            self.apply_run("sha256:" + "0" * 64, gates=["G1"])

    def test_digest_recomputed_mid_run_aborts_after_authorities_change(self):
        gates = simple_gates()
        self.write_overlay(gates=gates, authorities=simple_authorities())
        dry = self.dry_run()
        mock_payload = self.default_mock_for(dry)

        original_read_ledger = gate_issues.read_ledger
        call_count = {"n": 0}

        def flaky_read_ledger(root, task_id):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # Simulate a concurrent authorities.json edit right after the run starts.
                authorities_path = self.overlay / "authorities.json"
                data = json.loads(authorities_path.read_text())
                data["product_owner"]["gitlab_username"] = "someone-else"
                authorities_path.write_text(json.dumps(data), encoding="utf-8")
            return original_read_ledger(root, task_id)

        with self.mock_env(mock_payload):
            with mock.patch.object(gate_issues, "read_ledger", side_effect=flaky_read_ledger):
                with self.assertRaises(gate_issues.GateIssuesBlocked):
                    self.apply_run(dry["plan_digest"])

    def test_digest_recomputed_mid_run_aborts_after_rationale_only_change(self):
        """Sibling to test_digest_recomputed_mid_run_aborts_after_authorities_change:
        a concurrent edit to *only* a rationale field (gate applicability_rationale
        or an authority requirement's rationale -- both rendered verbatim into
        created-issue descriptions by render_gate_description/render_approval_description)
        must be caught by the plan-digest mid-run recheck too, not just changes to
        applicability/status/assignment fields."""
        gates = simple_gates()
        self.write_overlay(gates=gates, authorities=simple_authorities())
        dry = self.dry_run()
        mock_payload = self.default_mock_for(dry)

        original_read_ledger = gate_issues.read_ledger
        call_count = {"n": 0}

        def flaky_read_ledger(root, task_id):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # Simulate a concurrent edit to only G1's applicability_rationale
                # (a run-record field, not authorities.json) right after the run starts.
                record_path = self.overlay / "runs" / "T1" / "run-record.json"
                data = json.loads(record_path.read_text())
                for gate in data["lifecycle_gates"]:
                    if gate["gate_id"] == "G1":
                        gate["applicability_rationale"] = "Rationale changed mid-run"
                record_path.write_text(json.dumps(data), encoding="utf-8")
            return original_read_ledger(root, task_id)

        with self.mock_env(mock_payload):
            with mock.patch.object(gate_issues, "read_ledger", side_effect=flaky_read_ledger):
                with self.assertRaises(gate_issues.GateIssuesBlocked):
                    self.apply_run(dry["plan_digest"])

    def test_lock_held_blocked_break_lock_overrides_released_on_success_and_exception(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        lock_path = gate_issues._lock_path(self.root, "T1")
        held = gate_issues.acquire_lock(self.root, "T1", break_lock=False)
        self.assertTrue(held.is_file())
        dry = self.dry_run(gates=["G1"])
        mock_payload = self.default_mock_for(dry)
        with self.mock_env(mock_payload):
            with self.assertRaises(gate_issues.GateIssuesBlocked):
                self.apply_run(dry["plan_digest"], gates=["G1"])
            result = self.apply_run(dry["plan_digest"], gates=["G1"], break_lock=True)
        self.assertEqual("created", result["gate_results"][0]["status"])
        self.assertFalse(lock_path.is_file())  # released on success

        # Released on exception too.
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        dry2 = self.dry_run(gates=["G1"])
        bad_mock = {"identity": {"username": "svc-bot"}, "search": {
            f"{gate_issues.FIXED_LABEL},{gate_issues.gate_label(dry2['gate_issues'][0]['marker'])}": [{"iid": 1}, {"iid": 2}]
        }, "create": {}, "verify": {}}
        with self.mock_env(bad_mock):
            with self.assertRaises(gate_issues.GateIssuesBlocked):
                self.apply_run(dry2["plan_digest"], gates=["G1"])
        self.assertFalse(lock_path.is_file())

    def test_ledger_status_creating_written_before_create_call(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        dry = self.dry_run(gates=["G1"])
        label = gate_issues.gate_label(dry["gate_issues"][0]["marker"])

        seen_statuses = []
        original_create = gitlab_write.create_gitlab_issue

        def spying_create(*args, **kwargs):
            ledger = gate_issues.read_ledger(self.root, "T1")
            seen_statuses.append(ledger["entries"]["G1"]["status"])
            return original_create(*args, **kwargs)

        mock_payload = self.default_mock_for(dry)
        with self.mock_env(mock_payload):
            with mock.patch.object(gitlab_write, "create_gitlab_issue", side_effect=spying_create):
                self.apply_run(dry["plan_digest"], gates=["G1"])
        self.assertEqual(["creating"], seen_statuses)

    def test_assignee_drift_on_reuse_reported_not_overwritten_and_reconcile_updates(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")])]
        authorities = {"product_owner": make_authority(assignee="human:po", gitlab_username="po-user")}
        self.write_overlay(gates=gates, authorities=authorities)
        dry = self.dry_run(gates=["G1"])
        gate_label = gate_issues.gate_label(dry["gate_issues"][0]["marker"])
        approval_label = gate_issues.approval_label(dry["approval_issues"][0]["marker"])
        mock_payload = {
            "identity": {"username": "svc-bot"},
            "search": {
                f"{gate_issues.FIXED_LABEL},{gate_label}": [{"iid": 1, "labels": [gate_issues.FIXED_LABEL, gate_label]}],
                f"{gate_issues.FIXED_LABEL},{approval_label}": [{"iid": 2, "labels": [gate_issues.FIXED_LABEL, approval_label]}],
            },
            "create": {},
            "verify": {
                "1": {"title": "x", "state": "opened", "labels": [gate_issues.FIXED_LABEL, gate_label], "assignees": [],
                      "confidential": False, "author": {"username": "svc-bot"}, "project_path": "grp/proj"},
                "2": {"title": "x", "state": "opened", "labels": [gate_issues.FIXED_LABEL, approval_label],
                      "assignees": [{"username": "someone-else"}], "confidential": False,
                      "author": {"username": "svc-bot"}, "project_path": "grp/proj"},
            },
            "users": {"po-user": [{"id": 55, "username": "po-user", "state": "active"}]},
        }
        with self.mock_env(mock_payload):
            result = self.apply_run(dry["plan_digest"], gates=["G1"])
        self.assertEqual("assignee_changed", result["approval_results"][0]["drift"])
        self.assertTrue(result["drift_detected"])

        with self.mock_env(mock_payload):
            with mock.patch.object(gitlab_write, "update_gitlab_issue_assignee") as updater:
                result = self.apply_run(dry["plan_digest"], gates=["G1"], reconcile_assignees=True)
        updater.assert_called_once_with("grp/proj", 2, [55])
        self.assertIn("reconciled", result["approval_results"][0]["drift"])
        self.assertFalse(result["drift_detected"])


class UnresolvableIdentityTests(GateIssuesTestCase):
    """Items 17-21."""

    def test_authority_unknown(self):
        gates = [make_gate("G4", authority_requirements=[make_ar("governance_lead", "Governance Lead")])]
        self.write_overlay(gates=gates, authorities={})
        result = self.dry_run(gates=["G4"])
        self.assertEqual([("G4", "governance_lead", "authority-unknown")],
                          [(r["gate_id"], r["authority_id"], r["reason"]) for r in result["refusals"]])
        self.assertEqual(0, len(result["approval_issues"]))

    def test_authority_unassigned(self):
        gates = [make_gate("G4", authority_requirements=[make_ar("governance_lead", "Governance Lead")])]
        authorities = {"governance_lead": make_authority(status="unknown", assignee=None)}
        self.write_overlay(gates=gates, authorities=authorities)
        result = self.dry_run(gates=["G4"])
        self.assertEqual("authority-unassigned", result["refusals"][0]["reason"])

    def test_no_gitlab_binding_github_identity_rejected_gitlab_identity_accepted(self):
        gates = [make_gate("G4", authority_requirements=[make_ar("governance_lead", "Governance Lead")])]
        authorities = {"governance_lead": make_authority(assignee="github.com/alice")}
        self.write_overlay(gates=gates, authorities=authorities)
        result = self.dry_run(gates=["G4"])
        self.assertEqual("no-gitlab-binding", result["refusals"][0]["reason"])

        authorities2 = {"governance_lead": make_authority(assignee="gitlab.com/alice")}
        self.write_overlay(gates=gates, authorities=authorities2)
        result2 = self.dry_run(gates=["G4"])
        self.assertEqual([], result2["refusals"])
        self.assertEqual(1, len(result2["approval_issues"]))

        # gitlab_username field wins over assignee-derived identity.
        authorities3 = {"governance_lead": make_authority(assignee="gitlab.com/alice", gitlab_username="bob")}
        self.write_overlay(gates=gates, authorities=authorities3)
        result3 = self.dry_run(gates=["G4"])
        dry_candidate = result3["approval_issues"][0]
        # username itself isn't in the dry-run summary shape; confirm via build_plan directly.
        record = json.loads((self.overlay / "runs/T1/run-record.json").read_text())
        dispatch = json.loads((self.overlay / "runs/T1/dispatch-plan.json").read_text())
        contracts = {g["id"]: g for g in agentic_sdlc.load_json(agentic_sdlc.CONTRACTS / "lifecycle-gates.json")["gates"]}
        _, approvals, _, _, _ = gate_issues.build_plan(
            task_id="T1", project_path="grp/proj", gate_ids=["G4"], record=record, authorities=authorities3,
            dispatch_plan=dispatch, lifecycle_contracts=contracts, include_scope=False, scope_text=None,
        )
        self.assertEqual("bob", approvals[0].username)

    def test_refusal_and_success_mixed_exits_with_both_lists_populated(self):
        gates = [
            make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")]),
            make_gate("G4", authority_requirements=[make_ar("governance_lead", "Governance Lead")]),
        ]
        authorities = {
            "product_owner": make_authority(assignee="human:po", gitlab_username="po-user"),
            "governance_lead": make_authority(status="unknown", assignee=None),
        }
        self.write_overlay(gates=gates, authorities=authorities)
        dry = self.dry_run(gates=["G1", "G4"])
        self.assertEqual(1, len(dry["approval_issues"]))
        self.assertEqual(1, len(dry["refusals"]))
        mock_payload = self.default_mock_for(dry)
        with self.mock_env(mock_payload):
            result = self.apply_run(dry["plan_digest"], gates=["G1", "G4"])
        self.assertEqual(1, len(result["refusals"]))
        self.assertTrue(len(result["gate_results"]) >= 1)

    def test_no_approval_issue_ever_created_without_assignee_ids(self):
        self.write_overlay(gates=simple_gates(), authorities=simple_authorities())
        dry = self.dry_run()
        mock_payload = self.default_mock_for(dry)
        captured = []
        original = gitlab_write.create_gitlab_issue

        def spying_create(project_path, title, description, labels, assignee_ids=None):
            if any(label.startswith(gate_issues.APPROVAL_LABEL_PREFIX) for label in labels):
                captured.append(assignee_ids)
            return original(project_path, title, description, labels, assignee_ids=assignee_ids)

        with self.mock_env(mock_payload):
            with mock.patch.object(gitlab_write, "create_gitlab_issue", side_effect=spying_create):
                self.apply_run(dry["plan_digest"])
        self.assertTrue(captured)
        self.assertTrue(all(ids for ids in captured))

    def test_username_resolving_to_zero_or_many_users_refuses_no_create(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")])]
        authorities = {"product_owner": make_authority(assignee="human:po", gitlab_username="po-user")}
        self.write_overlay(gates=gates, authorities=authorities)
        dry = self.dry_run(gates=["G1"])
        approval_label = gate_issues.approval_label(dry["approval_issues"][0]["marker"])
        base_mock = self.default_mock_for(dry)
        base_mock["search"][f"{gate_issues.FIXED_LABEL},{approval_label}"] = []
        base_mock["users"]["po-user"] = []
        with self.mock_env(base_mock):
            result = self.apply_run(dry["plan_digest"], gates=["G1"])
        self.assertEqual("gitlab-user-unresolved", result["refusals"][0]["reason"])
        self.assertEqual(0, len(result["approval_results"]))

        base_mock["users"]["po-user"] = [
            {"id": 1, "username": "po-user", "state": "active"}, {"id": 2, "username": "po-user", "state": "active"}
        ]
        with self.mock_env(base_mock):
            result2 = self.apply_run(dry["plan_digest"], gates=["G1"])
        self.assertEqual("gitlab-user-ambiguous", result2["refusals"][0]["reason"])

    def test_single_blocked_user_match_resolves_to_zero_active_matches_refuses(self):
        """A raw user-lookup response with exactly one match whose 'state'
        is not 'active' (e.g. 'blocked') must be filtered out by
        _resolve_active_user_matches, not mistaken for a valid single
        active match."""
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")])]
        authorities = {"product_owner": make_authority(assignee="human:po", gitlab_username="po-user")}
        self.write_overlay(gates=gates, authorities=authorities)
        dry = self.dry_run(gates=["G1"])
        approval_label = gate_issues.approval_label(dry["approval_issues"][0]["marker"])
        base_mock = self.default_mock_for(dry)
        base_mock["search"][f"{gate_issues.FIXED_LABEL},{approval_label}"] = []
        base_mock["users"]["po-user"] = [{"id": 1, "username": "po-user", "state": "blocked"}]
        with self.mock_env(base_mock):
            result = self.apply_run(dry["plan_digest"], gates=["G1"])
        self.assertEqual("gitlab-user-unresolved", result["refusals"][0]["reason"])
        self.assertEqual(0, len(result["approval_results"]))

    def test_resolve_active_user_matches_filters_non_active_state_directly(self):
        with self.mock_env({
            "identity": {"username": "svc-bot"},
            "users": {"po-user": [{"id": 1, "username": "po-user", "state": "blocked"}]},
        }):
            active = gate_issues._resolve_active_user_matches("po-user")
            self.assertEqual([], active)
            self.assertIsNone(gate_issues._resolve_single_active_user("po-user"))


class SelfApprovalTests(GateIssuesTestCase):
    """Items 22-25."""

    def test_preparer_match_refuses_no_issue_created(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")],
                            preparers=[{"id": "human:po"}])]
        authorities = {"product_owner": make_authority(assignee="human:po", gitlab_username="po-user")}
        self.write_overlay(gates=gates, authorities=authorities)
        result = self.dry_run(gates=["G1"])
        self.assertEqual(0, len(result["approval_issues"]))
        self.assertEqual("self-approval", result["refusals"][0]["reason"])

    def test_independent_verifier_match_refuses(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")],
                            independent_verifier={"id": "human:po"})]
        authorities = {"product_owner": make_authority(assignee="human:po", gitlab_username="po-user")}
        self.write_overlay(gates=gates, authorities=authorities)
        result = self.dry_run(gates=["G1"])
        self.assertEqual("self-approval", result["refusals"][0]["reason"])

    def test_empty_preparers_and_none_verifier_passes_vacuously(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")],
                            preparers=[], independent_verifier=None)]
        authorities = {"product_owner": make_authority(assignee="human:po", gitlab_username="po-user")}
        self.write_overlay(gates=gates, authorities=authorities)
        result = self.dry_run(gates=["G1"])
        self.assertEqual(1, len(result["approval_issues"]))
        self.assertEqual([], result["refusals"])

    def test_every_approval_description_contains_non_approval_and_independence_advisory(self):
        description = gate_issues.render_approval_description("T1", "G1", "abc", "grp/proj", 1, None)
        self.assertIn("Tracking artifact only", description)
        self.assertIn("not approval evidence", description)
        self.assertIn("must not be a preparer or the independent verifier", description)
        self.assertIn("approve-from-gitlab-mr", description)


class OrthogonalityTests(GateIssuesTestCase):
    """Items 26-28."""

    def test_input_files_byte_identical_after_full_apply_run(self):
        self.write_overlay(gates=simple_gates(), authorities=simple_authorities())
        record_path = self.overlay / "runs/T1/run-record.json"
        dispatch_path = self.overlay / "runs/T1/dispatch-plan.json"
        authorities_path = self.overlay / "authorities.json"
        before = {p: p.read_bytes() for p in (record_path, dispatch_path, authorities_path)}
        dry = self.dry_run()
        mock_payload = self.default_mock_for(dry)
        with self.mock_env(mock_payload):
            self.apply_run(dry["plan_digest"])
        for path, content in before.items():
            self.assertEqual(content, path.read_bytes(), f"{path} was modified by create-gate-issues")

    def test_never_writes_approval_or_disposition_fields(self):
        self.write_overlay(gates=simple_gates(), authorities=simple_authorities())
        record_path = self.overlay / "runs/T1/run-record.json"
        dry = self.dry_run()
        mock_payload = self.default_mock_for(dry)
        with self.mock_env(mock_payload):
            self.apply_run(dry["plan_digest"])
        record = json.loads(record_path.read_text())
        for gate in record["lifecycle_gates"]:
            self.assertEqual([], gate.get("human_approvals", []))
            self.assertEqual([], gate.get("evidence_refs", []))
            self.assertIn(gate["status"], {"pending", "ready"})
        self.assertEqual("pending", record["disposition"])

    def test_module_never_imports_approval_adapters(self):
        # Mirrors the LangGraph engine package's
        # test_graph_module_never_references_requirement_issues: only the
        # module's actual `from . import (...)` lines are checked (its
        # docstring legitimately *names* the approval adapters in prose,
        # explaining why this module is orthogonal to them).
        source = (PLUGIN_ROOT / "agentic_sdlc" / "gate_issues.py").read_text(encoding="utf-8")
        import_lines = [line for line in source.splitlines() if line.startswith("from . import") or line.startswith("import ")]
        forbidden = {"record_github_approval", "record_gitlab_approval", "record_gate_decision", "record_gitlab_issue_link"}
        imported_names = set()
        for line in import_lines:
            imported_names.update(name.strip() for name in line.split("import", 1)[1].split(","))
        self.assertEqual(set(), forbidden & imported_names)


class EligibilityFailClosedTests(GateIssuesTestCase):
    """Items 29-33."""

    def test_gate_not_in_dispatch_plan_blocked(self):
        self.write_overlay(gates=[make_gate("G1"), make_gate("G2")], authorities={}, configured_gate_ids=["G1"])
        with self.assertRaises(gate_issues.GateIssuesBlocked) as ctx:
            self.dry_run(gates=["G2"])
        self.assertIn("G2", str(ctx.exception))

    def test_applicability_not_applicable_blocked(self):
        self.write_overlay(gates=[make_gate("G1", applicability="not-applicable")], authorities={})
        with self.assertRaises(gate_issues.GateIssuesBlocked):
            self.dry_run(gates=["G1"])

    def test_status_invalidated_blocked(self):
        self.write_overlay(gates=[make_gate("G1", status="invalidated")], authorities={})
        with self.assertRaises(gate_issues.GateIssuesBlocked):
            self.dry_run(gates=["G1"])

    def test_required_reentry_gate_blocked(self):
        self.write_overlay(gates=[make_gate("G1", required_reentry_gate="G1")], authorities={})
        with self.assertRaises(gate_issues.GateIssuesBlocked):
            self.dry_run(gates=["G1"])

    def test_allow_classification_absent_or_mismatched_errors_before_any_gitlab_call(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={}, classification="internal")
        with self.assertRaises(gate_issues.GateIssuesError):
            self.dry_run(gates=["G1"], allow_classification=None)
        with self.assertRaises(gate_issues.GateIssuesError):
            self.dry_run(gates=["G1"], allow_classification="restricted")

    def test_mocked_without_i_know_this_is_mocked_under_apply_refused(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        dry = self.dry_run(gates=["G1"])
        mock_payload = self.default_mock_for(dry)
        with self.mock_env(mock_payload):
            with self.assertRaises(gate_issues.GateIssuesError):
                self.apply_run(dry["plan_digest"], gates=["G1"], i_know_this_is_mocked=False)

    def test_link_type_relates_to_403_blocks_exit2_without_flag_succeeds(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")])]
        authorities = {"product_owner": make_authority(assignee="human:po", gitlab_username="po-user")}
        self.write_overlay(gates=gates, authorities=authorities)
        dry = self.dry_run(gates=["G1"])
        mock_payload = self.default_mock_for(dry)
        mock_payload["users"] = {"po-user": [{"id": 5, "username": "po-user", "state": "active"}]}
        mock_payload["link"] = {"2": {"error_status": 403, "error": "Issue Links API not available"}}
        with self.mock_env(mock_payload):
            with self.assertRaises(gate_issues.GateIssuesBlocked) as ctx:
                self.apply_run(dry["plan_digest"], gates=["G1"], link_type="relates_to")
        self.assertIn("Issue Links API", str(ctx.exception))

        self.write_overlay(gates=gates, authorities=authorities)
        dry2 = self.dry_run(gates=["G1"])
        mock_payload2 = self.default_mock_for(dry2)
        mock_payload2["users"] = {"po-user": [{"id": 5, "username": "po-user", "state": "active"}]}
        mock_payload2["link"] = {"2": {"issue_link_id": 1}}
        with self.mock_env(mock_payload2):
            result = self.apply_run(dry2["plan_digest"], gates=["G1"], link_type="relates_to")
        self.assertEqual("created", result["approval_results"][0]["status"])

    def test_max_issues_per_run_exceeded_aborts_never_truncates(self):
        with mock.patch.object(gate_issues, "MAX_ISSUES_PER_RUN", 1):
            self.write_overlay(gates=simple_gates(), authorities=simple_authorities())
            with self.assertRaises(gate_issues.GateIssuesError):
                self.dry_run()


class LinkUnavailableDetectionTests(unittest.TestCase):
    """Unit tests for gitlab_write._is_link_unavailable_error's pure
    substring-detection logic, exercised directly since no `glab` binary
    is available in this test environment to trigger the real subprocess
    error path."""

    def test_detects_403(self):
        self.assertTrue(gitlab_write._is_link_unavailable_error("403 Forbidden: not available on this instance"))

    def test_detects_404(self):
        self.assertTrue(gitlab_write._is_link_unavailable_error("404 Not Found"))

    def test_does_not_detect_unrelated_error(self):
        self.assertFalse(gitlab_write._is_link_unavailable_error("500 Internal Server Error"))
        self.assertFalse(gitlab_write._is_link_unavailable_error("connection refused"))


class ErrorWrappingTests(GateIssuesTestCase):
    """Item: bare ValueError propagating from gitlab_write.py calls must be
    wrapped with gate-id/authority-id context, mirroring the LangGraph
    engine package's requirement_issues._process_item pattern."""

    def test_bare_value_error_from_gate_issue_processing_wrapped_with_gate_id(self):
        self.write_overlay(gates=[make_gate("G1")], authorities={})
        dry = self.dry_run(gates=["G1"])
        mock_payload = self.default_mock_for(dry)
        with self.mock_env(mock_payload):
            with mock.patch.object(
                gitlab_write, "search_gitlab_issues_by_labels", side_effect=ValueError("boom")
            ):
                with self.assertRaises(gate_issues.GateIssuesError) as ctx:
                    self.apply_run(dry["plan_digest"], gates=["G1"])
        self.assertIn("G1", str(ctx.exception))
        self.assertIn("boom", str(ctx.exception))

    def test_bare_value_error_from_approval_issue_processing_wrapped_with_gate_and_authority_id(self):
        gates = [make_gate("G1", authority_requirements=[make_ar("product_owner", "Product Owner")])]
        authorities = {"product_owner": make_authority(assignee="human:po", gitlab_username="po-user")}
        self.write_overlay(gates=gates, authorities=authorities)
        dry = self.dry_run(gates=["G1"])
        mock_payload = self.default_mock_for(dry)

        original_search = gitlab_write.search_gitlab_issues_by_labels

        def flaky_search(project_path, labels):
            if any(label.startswith(gate_issues.APPROVAL_LABEL_PREFIX) for label in labels):
                raise ValueError("boom")
            return original_search(project_path, labels)

        with self.mock_env(mock_payload):
            with mock.patch.object(gitlab_write, "search_gitlab_issues_by_labels", side_effect=flaky_search):
                with self.assertRaises(gate_issues.GateIssuesError) as ctx:
                    self.apply_run(dry["plan_digest"], gates=["G1"])
        self.assertIn("G1", str(ctx.exception))
        self.assertIn("product_owner", str(ctx.exception))
        self.assertIn("boom", str(ctx.exception))


class PortIntegrityTests(unittest.TestCase):
    """Item 34."""

    def test_fixed_label_and_mock_env_var_match_the_langgraph_engine_copy(self):
        engine_root = PLUGIN_ROOT.parents[1] / "agentic_sdlc_langgraph" / "agentic_sdlc_langgraph"
        requirement_issues_path = engine_root / "requirement_issues.py"  # FIXED_LABEL lives here
        gitlab_issue_path = engine_root / "gitlab_issue.py"  # ISSUE_CREATE_MOCK_ENV_VAR lives here
        if not requirement_issues_path.is_file() or not gitlab_issue_path.is_file():
            self.skipTest("agentic_sdlc_langgraph package not present in this checkout")
        self.assertIn('FIXED_LABEL = "agentic-sdlc"', requirement_issues_path.read_text(encoding="utf-8"))
        self.assertEqual("agentic-sdlc", gitlab_write.FIXED_LABEL)
        self.assertIn(
            'ISSUE_CREATE_MOCK_ENV_VAR = "AGENTIC_SDLC_TEST_ISSUE_CREATE_FILE"',
            gitlab_issue_path.read_text(encoding="utf-8"),
        )
        self.assertEqual("AGENTIC_SDLC_TEST_ISSUE_CREATE_FILE", gitlab_write.ISSUE_CREATE_MOCK_ENV_VAR)


class CliWiringTests(unittest.TestCase):
    """CLI-level smoke tests proving create-gate-issues/list-gate-issues are
    wired into the parser and produce the same behavior as calling
    gate_issues.run() directly."""

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

    def test_dry_run_then_apply_via_cli_and_list_gate_issues(self):
        dry = self.run_cli(
            "create-gate-issues", "--task-id", "T1", "--project-path", "grp/proj", "--as-bot", "svc-bot",
            "--allow-classification", "internal", "--dry-run",
        )
        overlay = self.root / ".agentic-sdlc"
        record = json.loads((overlay / "runs" / "T1" / "run-record.json").read_text())
        dispatch = json.loads((overlay / "runs" / "T1" / "dispatch-plan.json").read_text())
        authorities = json.loads((overlay / "authorities.json").read_text())
        contracts = {g["id"]: g for g in agentic_sdlc.load_json(agentic_sdlc.CONTRACTS / "lifecycle-gates.json")["gates"]}
        gate_plans, approval_candidates, _, _, _ = gate_issues.build_plan(
            task_id="T1", project_path="grp/proj", gate_ids=dry["gate_ids"], record=record, authorities=authorities,
            dispatch_plan=dispatch, lifecycle_contracts=contracts, include_scope=False, scope_text=None,
        )
        mock_payload = {"identity": {"username": "svc-bot"}, "search": {}, "create": {}, "verify": {}, "users": {}}
        iid = 1
        for gp in gate_plans:
            key = f"agentic-sdlc,{gp.label}"
            mock_payload["search"][key] = []
            mock_payload["create"][key] = {"iid": iid}
            mock_payload["verify"][str(iid)] = {
                "title": gp.title, "state": "opened", "labels": ["agentic-sdlc", gp.label],
                "assignees": [], "confidential": False, "author": {"username": "svc-bot"}, "project_path": "grp/proj",
            }
            iid += 1
        for ac in approval_candidates:
            key = f"agentic-sdlc,{ac.label}"
            mock_payload["search"][key] = []
            mock_payload["create"][key] = {"iid": iid}
            mock_payload["verify"][str(iid)] = {
                "title": ac.title, "state": "opened", "labels": ["agentic-sdlc", ac.label],
                "assignees": [{"username": ac.username}], "confidential": False,
                "author": {"username": "svc-bot"}, "project_path": "grp/proj",
            }
            mock_payload["users"][ac.username] = [{"id": iid + 1000, "username": ac.username, "state": "active"}]
            iid += 1
        mock_path = self.root / "mock.json"
        mock_path.write_text(json.dumps(mock_payload), encoding="utf-8")
        apply_result = self.run_cli(
            "create-gate-issues", "--task-id", "T1", "--project-path", "grp/proj", "--as-bot", "svc-bot",
            "--allow-classification", "internal", "--apply", "--plan-digest", dry["plan_digest"],
            "--i-know-this-is-mocked",
            env={"AGENTIC_SDLC_TEST_ISSUE_CREATE_FILE": str(mock_path)},
        )
        self.assertEqual([], apply_result["refusals"])
        listed = self.run_cli("list-gate-issues", "--task-id", "T1")
        self.assertIn("G1", listed["entries"])

    def test_missing_plan_digest_on_apply_is_exit_1(self):
        self.run_cli(
            "create-gate-issues", "--task-id", "T1", "--project-path", "grp/proj", "--as-bot", "svc-bot",
            "--allow-classification", "internal", "--apply", expected=1,
        )


if __name__ == "__main__":
    unittest.main()
