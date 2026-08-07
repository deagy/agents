"""Tests for `agentic_sdlc_langgraph.service` (the minimal FastAPI
service), via FastAPI's `TestClient`.

Each `client.post`/`client.get` call below goes through a full HTTP
request/response cycle against the real route handlers in `service.py`,
none of which hold a graph object in any module-level or fixture-level
variable between calls -- every handler rebuilds the graph fresh via
`runtime.build_graph_for_task` and lets the on-disk sqlite checkpointer
(named by `root` in the request body/query string) carry state from one
call to the next, exactly as separate CLI process invocations do (see
`test_cli.py`'s `test_plan_then_resume_across_separate_processes` for the
real-subprocess version of this same proof).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentic_sdlc_langgraph.service import app

TASK_TEXT = "Define and review a small internal order-processing API architecture and service"

APPROVAL = {
    "status": "approved",
    "approver": {"id": "product_owner", "role": "Product Owner", "kind": "human"},
    "evidence_refs": [{
        "evidence_id": "test-evidence",
        "uri": "test-evidence:manual",
        "hash_algorithm": "sha256",
        "hash": "0" * 64,
        "classification": "internal",
    }],
}


@pytest.fixture(autouse=True)
def _fake_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTIC_SDLC_LANGGRAPH_FAKE_MODEL", "1")


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_create_task_interrupts_at_g1(client: TestClient, tmp_path):
    response = client.post(
        "/tasks",
        json={"task_id": "svc-1", "task": TASK_TEXT, "root": str(tmp_path)},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "interrupted"
    assert payload["interrupt"]["gate_id"] == "G1"
    assert (tmp_path / ".agentic-sdlc" / "runs" / "svc-1" / "graph-config.json").is_file()


def test_create_task_twice_is_a_noop_second_time(client: TestClient, tmp_path):
    client.post("/tasks", json={"task_id": "svc-1", "task": TASK_TEXT, "root": str(tmp_path)})
    response = client.post(
        "/tasks", json={"task_id": "svc-1", "task": TASK_TEXT, "root": str(tmp_path)}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "already-planned"


def test_create_task_conflicting_text_is_409(client: TestClient, tmp_path):
    client.post("/tasks", json={"task_id": "svc-1", "task": TASK_TEXT, "root": str(tmp_path)})
    response = client.post(
        "/tasks", json={"task_id": "svc-1", "task": "a different task text", "root": str(tmp_path)}
    )
    assert response.status_code == 409


def test_resume_unknown_task_is_404(client: TestClient, tmp_path):
    response = client.post(
        "/tasks/does-not-exist/resume", json={"root": str(tmp_path), "decision": APPROVAL}
    )
    assert response.status_code == 404


def test_status_unknown_task_is_404(client: TestClient, tmp_path):
    response = client.get("/tasks/does-not-exist", params={"root": str(tmp_path)})
    assert response.status_code == 404


def test_full_g1_g3_lifecycle_via_http(client: TestClient, tmp_path):
    root = str(tmp_path)

    response = client.post("/tasks", json={"task_id": "svc-1", "task": TASK_TEXT, "root": root})
    assert response.json()["interrupt"]["gate_id"] == "G1"

    for expected_next in ("G2", "G3"):
        response = client.post(
            "/tasks/svc-1/resume", json={"root": root, "decision": APPROVAL}
        )
        assert response.status_code == 200
        assert response.json()["interrupt"]["gate_id"] == expected_next

    response = client.post("/tasks/svc-1/resume", json={"root": root, "decision": APPROVAL})
    assert response.json()["status"] == "complete"

    # A completely fresh GET (no object shared with the POST calls above
    # beyond the on-disk sqlite file) confirms durable persistence.
    response = client.get("/tasks/svc-1", params={"root": root})
    assert response.status_code == 200
    status = response.json()
    assert status["interrupted"] is False
    assert [g["status"] for g in status["gates"]] == ["approved", "approved", "approved"]
    assert status["re_entry_history_length"] == 0


def test_create_task_links_gitlab_issues(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch, capsys):
    import json as json_module

    from agentic_sdlc_langgraph import cli

    mock_issue = {"iid": 0, "title": "Support SSO login", "state": "opened", "web_url": None, "updated_at": None}
    mock_file = tmp_path / "issue.json"
    mock_file.write_text(json_module.dumps(mock_issue), encoding="utf-8")
    monkeypatch.setenv("AGENTIC_SDLC_TEST_GITLAB_ISSUE_FILE", str(mock_file))

    response = client.post(
        "/tasks",
        json={
            "task_id": "svc-2",
            "task": TASK_TEXT,
            "root": str(tmp_path),
            "intent_gitlab_issue": "group/project#42",
            "requirements_gitlab_issue": "group/project#43",
        },
    )
    assert response.status_code == 200

    code = cli.main(["export", "--root", str(tmp_path), "--task-id", "svc-2"])
    assert code == 0
    record = json_module.loads(capsys.readouterr().out)
    assert record["intent_record_id"] == "gitlab-issue:group/project:issues/42"
    assert record["requirements_baseline_id"] == "gitlab-issue:group/project:issues/43"


def test_create_task_rejects_malformed_gitlab_issue_reference(client: TestClient, tmp_path):
    response = client.post(
        "/tasks",
        json={
            "task_id": "svc-3",
            "task": TASK_TEXT,
            "root": str(tmp_path),
            "intent_gitlab_issue": "not-a-valid-reference",
        },
    )
    assert response.status_code == 422


def test_service_and_cli_share_the_same_on_disk_state(tmp_path):
    """The service and the CLI must be interchangeable against the same
    `root`/`task_id`: plan via the service, resume via the CLI. Proves
    `runtime.build_graph_for_task` is genuinely the single shared
    reconnection path both entrypoints use, not two divergent
    implementations that happen to look similar.
    """
    import json as json_module

    from agentic_sdlc_langgraph import cli

    root = tmp_path
    client = TestClient(app)

    response = client.post(
        "/tasks", json={"task_id": "shared-1", "task": TASK_TEXT, "root": str(root)}
    )
    assert response.json()["interrupt"]["gate_id"] == "G1"

    decision_path = root / "decision.json"
    decision_path.write_text(json_module.dumps(APPROVAL), encoding="utf-8")
    code = cli.main(
        ["resume", "--root", str(root), "--task-id", "shared-1", "--decision", str(decision_path)]
    )
    assert code == 0

    response = client.get("/tasks/shared-1", params={"root": str(root)})
    status = response.json()
    assert status["gates"][0]["status"] == "approved"  # G1, approved via the CLI
    assert status["interrupt"]["gate_id"] == "G2"  # now suspended at G2, via the service's own view


def test_get_task_status_reports_pending_interrupt_after_invalidate(client: TestClient, tmp_path):
    """K1 fix, exercised through the REST surface: `invalidate` (CLI-only
    today) calls `graph.update_state(...)`, which empties
    `snapshot.interrupts` while the graph stays genuinely suspended.
    `GET /tasks/{task_id}` must still report the pending interrupt."""
    from agentic_sdlc_langgraph import runtime
    from agentic_sdlc_langgraph.reentry import invalidate_gates

    root = tmp_path
    response = client.post("/tasks", json={"task_id": "svc-k1", "task": TASK_TEXT, "root": str(root)})
    assert response.json()["interrupt"]["gate_id"] == "G1"

    graph, config, metadata = runtime.build_graph_for_task(root, "svc-k1")
    invalidate_gates(
        graph, config, earliest_gate_id="G1", reason="test", actor="tester",
        all_gate_ids=metadata.gate_sequence_ids,
    )

    response = client.get("/tasks/svc-k1", params={"root": str(root)})
    status = response.json()
    assert status["interrupted"] is True
    assert status["interrupt"] is None
    assert status["interrupt_payload_unavailable"] is True
    assert status["pending_interrupt_node"] == "human_approval_G1"
