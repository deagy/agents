"""Tests for `agentic_sdlc_langgraph.github_approval`.

Covers:

- `select_github_review`'s "latest review wins" semantics, porting the
  legacy CLI test
  `test_github_latest_change_request_invalidates_older_approval`
  (plugins/agentic-sdlc/test/test_agentic_sdlc.py ~117-123) onto the new
  function verbatim (same two-review scenario, same expected raise).
- A happy-path selection + adapter test: two reviews (an old one from a
  different reviewer, a later effective APPROVED from the right
  reviewer/commit) -> `select_github_review` picks the right one ->
  `github_review_to_approval` builds a correctly-shaped `Approval`.
- `fetch_github_pr_reviews` reading from
  `AGENTIC_SDLC_TEST_GITHUB_REVIEWS_FILE` when set, restoring the
  environment afterward via the `monkeypatch` fixture (auto-restored,
  never leaks across tests).
- The optional `expected_login` cross-check: raises on mismatch, is
  skipped cleanly when omitted.
- An end-to-end test: build a real G1-only graph (using the actual
  contract/profile/catalog fixtures, exactly like test_spike.py/
  test_reentry.py do), drive it to the `human_approval_G1` interrupt, and
  resume it with `Command(resume=github_review_to_approval(...))` built
  from a synthetic review -- proving the adapter's output is genuinely
  consumable by the real interrupt/resume mechanism, not just
  structurally plausible in isolation.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from agentic_sdlc_langgraph.agents import FakeModelClient
from agentic_sdlc_langgraph.contracts import (
    load_agent_catalog,
    load_lifecycle_gates,
    load_mutation_gates,
    load_profile,
)
from agentic_sdlc_langgraph.github_approval import (
    fetch_github_pr_reviews,
    github_review_to_approval,
    parse_github_review_uri,
    resume_gate_with_github_approval,
    select_github_review,
)
from agentic_sdlc_langgraph.graph import build_graph

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = REPO_ROOT / "plugins" / "agentic-sdlc" / "contracts"
PROVIDER_DEFAULTS = REPO_ROOT / "providers" / "agentic-sdlc-defaults"

TASK_TEXT = "Define and review a small internal order-processing API architecture and service"


# --- select_github_review: latest-review-wins semantics ---------------------


def test_select_github_review_latest_change_request_invalidates_older_approval():
    """Port of the legacy CLI test
    `test_github_latest_change_request_invalidates_older_approval`: an
    earlier APPROVED review followed by a later CHANGES_REQUESTED review
    from the same reviewer/commit must invalidate the approval, because
    `select_github_review` always evaluates the *latest* review only.
    """
    reviews = [
        {
            "id": 1,
            "state": "APPROVED",
            "submitted_at": "2030-01-01T00:00:00Z",
            "commit_id": "abc",
            "user": {"login": "reviewer"},
        },
        {
            "id": 2,
            "state": "CHANGES_REQUESTED",
            "submitted_at": "2030-01-02T00:00:00Z",
            "commit_id": "abc",
            "user": {"login": "reviewer"},
        },
    ]
    with pytest.raises(ValueError):
        select_github_review(reviews, "reviewer", "abc")


# --- happy path: selection + adapter ----------------------------------------


def test_select_github_review_and_adapter_happy_path():
    reviews = [
        {
            "id": 1,
            "state": "APPROVED",
            "submitted_at": "2030-01-01T00:00:00Z",
            "commit_id": "deadbeef",
            "user": {"login": "someone-else"},
        },
        {
            "id": 2,
            "state": "APPROVED",
            "submitted_at": "2030-02-01T00:00:00Z",
            "commit_id": "CAFEBABE",
            "user": {"login": "octocat"},
        },
    ]

    selected = select_github_review(reviews, "OctoCat", "cafebabe")
    assert selected["id"] == 2

    approval = github_review_to_approval(
        selected,
        gate_id="G1",
        authority_id="product_owner",
        role_label="Product Owner",
        repo="acme/widgets",
        pr=42,
        expected_login="octocat",
    )

    assert approval["status"] == "approved"
    assert approval["approver"] == {
        "id": "product_owner",
        "role": "Product Owner",
        "kind": "human",
    }
    assert approval["decided_at"] is not None

    assert len(approval["evidence_refs"]) == 1
    evidence = approval["evidence_refs"][0]
    assert evidence["evidence_id"] == "g1-product_owner-github-review-2"
    assert evidence["hash_algorithm"] == "sha256"
    assert isinstance(evidence["hash"], str) and len(evidence["hash"]) == 64
    int(evidence["hash"], 16)  # valid hex
    assert evidence["classification"] == "internal"

    uri = evidence["uri"]
    assert uri == "github-review:acme/widgets:pull/42:review/2:reviewer/octocat"
    parsed = parse_github_review_uri(uri)
    assert parsed == {
        "owner": "acme",
        "repo": "widgets",
        "pull": "42",
        "review": "2",
        "login": "octocat",
    }


# --- fetch_github_pr_reviews: env-var mocking convention --------------------


def test_fetch_github_pr_reviews_reads_mock_file(tmp_path, monkeypatch):
    mock_reviews = [
        {
            "id": 99,
            "state": "APPROVED",
            "submitted_at": "2030-03-01T00:00:00Z",
            "commit_id": "abc123",
            "user": {"login": "octocat"},
        }
    ]
    mock_file = tmp_path / "reviews.json"
    mock_file.write_text(json.dumps(mock_reviews), encoding="utf-8")

    monkeypatch.setenv("AGENTIC_SDLC_TEST_GITHUB_REVIEWS_FILE", str(mock_file))

    result = fetch_github_pr_reviews("acme/widgets", 42)
    assert result == mock_reviews
    # monkeypatch restores the environment automatically after the test.


def test_fetch_github_pr_reviews_rejects_non_array_payload(tmp_path, monkeypatch):
    mock_file = tmp_path / "not_a_list.json"
    mock_file.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    monkeypatch.setenv("AGENTIC_SDLC_TEST_GITHUB_REVIEWS_FILE", str(mock_file))

    with pytest.raises(ValueError):
        fetch_github_pr_reviews("acme/widgets", 42)


# --- optional expected_login cross-check ------------------------------------


def _approved_review(login: str = "octocat") -> dict:
    return {
        "id": 7,
        "state": "APPROVED",
        "submitted_at": "2030-01-01T00:00:00Z",
        "commit_id": "abc123",
        "user": {"login": login},
    }


def test_expected_login_mismatch_raises():
    review = _approved_review("octocat")
    with pytest.raises(ValueError):
        github_review_to_approval(
            review,
            gate_id="G1",
            authority_id="product_owner",
            role_label="Product Owner",
            repo="acme/widgets",
            pr=1,
            expected_login="someone-else",
        )


def test_expected_login_omitted_skips_check():
    review = _approved_review("octocat")
    approval = github_review_to_approval(
        review,
        gate_id="G1",
        authority_id="product_owner",
        role_label="Product Owner",
        repo="acme/widgets",
        pr=1,
        # expected_login omitted entirely -- no cross-check performed.
    )
    assert approval["status"] == "approved"


def test_expected_login_matches_case_insensitively():
    review = _approved_review("OctoCat")
    approval = github_review_to_approval(
        review,
        gate_id="G1",
        authority_id="product_owner",
        role_label="Product Owner",
        repo="acme/widgets",
        pr=1,
        expected_login="octocat",
    )
    assert approval["status"] == "approved"


# --- end-to-end: adapter output is consumable by the real graph ------------


@pytest.fixture()
def g1_graph():
    lifecycle_gates = load_lifecycle_gates(CONTRACTS / "lifecycle-gates.json")
    mutation_gates = load_mutation_gates(CONTRACTS / "mutation-gates.json")
    agent_catalog = load_agent_catalog(PROVIDER_DEFAULTS / "agent-catalog.json")
    profile = load_profile(PROVIDER_DEFAULTS / "profiles" / "generic" / "profile.json")
    g1_only = [g for g in lifecycle_gates if g["id"] == "G1"]

    model_client = FakeModelClient()
    checkpointer = SqliteSaver(sqlite3.connect(":memory:", check_same_thread=False))
    graph = build_graph(
        gates=g1_only,
        gate_bindings=profile["gate_bindings"],
        routes=profile["routing"],
        agent_catalog=agent_catalog,
        model_client=model_client,
        checkpointer=checkpointer,
        mutation_gates=mutation_gates,
    )
    return graph


def test_end_to_end_resume_with_github_review_approves_gate(g1_graph):
    graph = g1_graph
    config = {"configurable": {"thread_id": "github-approval-task"}}

    initial_state = {
        "task_id": "github-approval-task",
        "classification": "internal",
        "scope": TASK_TEXT,
        "current_lifecycle_phase": "intent",
        "lifecycle_gates": {},
        "re_entry_history": [],
        "authorities": {"product_owner": {"status": "assigned"}},
        "agent_outputs": {},
        "mutation_gate_pending": None,
        "mutation_gate_decision": None,
        "run_halted": False,
    }

    result = graph.invoke(initial_state, config=config)

    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["gate_id"] == "G1"

    # Synthetic GitHub review: the assigned product owner's real PR review
    # approving the G1 revision.
    review = {
        "id": 555,
        "state": "APPROVED",
        "submitted_at": "2030-04-01T12:00:00Z",
        "commit_id": "feedface",
        "user": {"login": "product-owner-login"},
    }
    selected = select_github_review([review], "product-owner-login", "feedface")

    approval = github_review_to_approval(
        selected,
        gate_id="G1",
        authority_id="product_owner",
        role_label="Product Owner",
        repo="acme/widgets",
        pr=101,
        expected_login="product-owner-login",
    )

    result = resume_gate_with_github_approval(graph, config, approval)
    assert "__interrupt__" not in result or not result["__interrupt__"]

    final_state = graph.get_state(config).values
    g1 = final_state["lifecycle_gates"]["G1"]
    assert g1["status"] == "approved"
    assert len(g1["human_approvals"]) == 1
    recorded = g1["human_approvals"][0]
    assert recorded["status"] == "approved"
    assert recorded["approver"] == {
        "id": "product_owner",
        "role": "Product Owner",
        "kind": "human",
    }
    assert len(recorded["evidence_refs"]) == 1
    evidence = recorded["evidence_refs"][0]
    assert evidence["uri"] == (
        "github-review:acme/widgets:pull/101:review/555:reviewer/product-owner-login"
    )
    assert evidence["hash_algorithm"] == "sha256"
    assert parse_github_review_uri(evidence["uri"]) is not None


def test_direct_command_resume_also_works(g1_graph):
    """Same as the end-to-end test above, but resuming via a plain
    `Command(resume=...)` call directly (bypassing
    `resume_gate_with_github_approval`) to prove the `Approval` shape
    itself -- not just the wrapper -- is what the graph actually
    consumes.
    """
    graph = g1_graph
    config = {"configurable": {"thread_id": "github-approval-task-direct"}}

    initial_state = {
        "task_id": "github-approval-task-direct",
        "classification": "internal",
        "scope": TASK_TEXT,
        "current_lifecycle_phase": "intent",
        "lifecycle_gates": {},
        "re_entry_history": [],
        "authorities": {"product_owner": {"status": "assigned"}},
        "agent_outputs": {},
        "mutation_gate_pending": None,
        "mutation_gate_decision": None,
        "run_halted": False,
    }
    graph.invoke(initial_state, config=config)

    review = {
        "id": 42,
        "state": "APPROVED",
        "submitted_at": "2030-05-01T00:00:00Z",
        "commit_id": "0123abcd",
        "user": {"login": "product-owner-login"},
    }
    selected = select_github_review([review], "product-owner-login")
    approval = github_review_to_approval(
        selected,
        gate_id="G1",
        authority_id="product_owner",
        role_label="Product Owner",
        repo="acme/widgets",
        pr=7,
    )

    result = graph.invoke(Command(resume=approval), config=config)
    assert "__interrupt__" not in result or not result["__interrupt__"]
    assert graph.get_state(config).values["lifecycle_gates"]["G1"]["status"] == "approved"
