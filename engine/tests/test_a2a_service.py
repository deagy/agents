"""Tests for the A2A (Agent2Agent) protocol surface mounted into
`service.py`'s FastAPI app (`a2a/server.py`): agent card discovery,
`message/send` (create + resume), `tasks/get`, and `message/stream` SSE.

Follows `test_service.py`'s pattern (`TestClient(app)`,
`AGENTIC_SDLC_LANGGRAPH_FAKE_MODEL=1`), plus pins
`AGENTIC_SDLC_LANGGRAPH_A2A_ROOT` to `tmp_path` per test so each test's
`taskId -> root` lookup file is isolated.
"""

from __future__ import annotations

import json

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
def client(monkeypatch: pytest.MonkeyPatch, tmp_path) -> TestClient:
    monkeypatch.setenv("AGENTIC_SDLC_LANGGRAPH_A2A_ROOT", str(tmp_path))
    return TestClient(app)


def _rpc(client: TestClient, method: str, params: dict, request_id: str = "1"):
    return client.post(
        "/a2a", json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    )


def _send_params(text: str, *, task_id: str | None = None, root: str | None = None, decision=None) -> dict:
    metadata: dict = {}
    if task_id is not None and decision is None:
        metadata["task_id"] = task_id
    if root is not None:
        metadata["root"] = root
    if decision is not None:
        metadata["decision"] = decision
    message: dict = {"role": "user", "parts": [{"kind": "text", "text": text}] if decision is None else [], "metadata": metadata}
    if decision is not None:
        message["taskId"] = task_id
    return {"message": message}


def test_agent_card(client: TestClient):
    response = client.get("/.well-known/agent.json")
    assert response.status_code == 200
    card = response.json()
    assert card["capabilities"]["streaming"] is True
    assert card["skills"]
    assert card["url"].endswith("/a2a")


def test_message_send_creates_task_and_interrupts_at_g1(client: TestClient, tmp_path):
    response = _rpc(client, "message/send", _send_params(TASK_TEXT, task_id="a2a-1", root=str(tmp_path)))
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["status"]["state"] == "input-required"
    assert result["status"]["message"]["gate_id"] == "G1"
    assert (tmp_path / ".agentic-sdlc" / "runs" / "a2a-1" / "graph-config.json").is_file()


def test_tasks_get_matches_status(client: TestClient, tmp_path):
    _rpc(client, "message/send", _send_params(TASK_TEXT, task_id="a2a-2", root=str(tmp_path)))
    response = _rpc(client, "tasks/get", {"id": "a2a-2"})
    result = response.json()["result"]
    assert result["status"]["state"] == "input-required"
    assert result["status"]["message"]["gate_id"] == "G1"


def test_tasks_get_unknown_task_is_404(client: TestClient):
    response = _rpc(client, "tasks/get", {"id": "does-not-exist"})
    assert response.status_code == 404


def test_message_send_resume_drives_full_lifecycle(client: TestClient, tmp_path):
    send = _rpc(client, "message/send", _send_params(TASK_TEXT, task_id="a2a-3", root=str(tmp_path)))
    assert send.json()["result"]["status"]["state"] == "input-required"

    for expected_gate in ("G2", "G3"):
        resume = _rpc(
            client, "message/send", _send_params("", task_id="a2a-3", decision=APPROVAL)
        )
        result = resume.json()["result"]
        assert result["status"]["state"] == "input-required"
        assert result["status"]["message"]["gate_id"] == expected_gate

    final = _rpc(client, "message/send", _send_params("", task_id="a2a-3", decision=APPROVAL))
    assert final.json()["result"]["status"]["state"] == "completed"

    status = _rpc(client, "tasks/get", {"id": "a2a-3"})
    assert status.json()["result"]["status"]["state"] == "completed"


def test_message_stream_emits_status_updates(client: TestClient, tmp_path):
    with client.stream(
        "POST",
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "1",
            "method": "message/stream",
            "params": _send_params(TASK_TEXT, task_id="a2a-4", root=str(tmp_path)),
        },
    ) as response:
        assert response.status_code == 200
        events = []
        for line in response.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: ") :]))

    assert len(events) > 1
    assert events[-1]["final"] is True
    assert events[-1]["status"]["state"] == "input-required"
    assert events[-1]["status"]["message"]["gate_id"] == "G1"


def test_message_stream_reports_pending_interrupt_after_noop_update_state(client: TestClient, tmp_path, monkeypatch):
    """K1 fix, exercised through the A2A `message/stream` SSE surface --
    a separate code path from `tasks/get`'s `status_summary` (see
    `a2a/server.py`'s `event_source`, which computed
    `bool(snapshot.interrupts)` directly before this fix). Mirrors
    `test_tasks_get_reports_pending_interrupt_after_invalidate` but drives
    the fallback via a fake graph whose `.stream()` yields no updates and
    whose `.get_state()` reports a snapshot with empty `interrupts` but a
    `next` still pointing at `human_approval_G1` -- exactly the shape
    `graph.update_state(...)` leaves behind (see `runtime.interrupt_status`).
    """
    from agentic_sdlc_langgraph.a2a import server

    class _FakeSnapshot:
        interrupts = ()
        next = ("human_approval_G1",)
        values = {}

    class _FakeGraph:
        def stream(self, *args, **kwargs):
            return iter(())

        def get_state(self, config):
            return _FakeSnapshot()

    def _fake_build_graph_for_task(root, task_id, **kwargs):
        return _FakeGraph(), {"configurable": {"thread_id": task_id}}, None

    monkeypatch.setattr(server.runtime, "build_graph_for_task", _fake_build_graph_for_task)

    with client.stream(
        "POST",
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "1",
            "method": "message/stream",
            "params": _send_params(TASK_TEXT, task_id="a2a-stream-k1", root=str(tmp_path)),
        },
    ) as response:
        assert response.status_code == 200
        events = [json.loads(line[len("data: "):]) for line in response.iter_lines() if line.startswith("data: ")]

    assert events[-1]["final"] is True
    assert events[-1]["status"]["state"] == "input-required"
    assert events[-1]["status"]["message"]["pending_interrupt_node"] == "human_approval_G1"
    assert events[-1]["status"]["message"]["interrupt_payload_unavailable"] is True


def test_tasks_get_reports_pending_interrupt_after_invalidate(client: TestClient, tmp_path):
    """K1 fix, exercised through the A2A `tasks/get` surface."""
    from agentic_sdlc_langgraph import runtime
    from agentic_sdlc_langgraph.reentry import invalidate_gates

    _rpc(client, "message/send", _send_params(TASK_TEXT, task_id="a2a-k1", root=str(tmp_path)))

    graph, config, metadata = runtime.build_graph_for_task(tmp_path, "a2a-k1")
    invalidate_gates(
        graph, config, earliest_gate_id="G1", reason="test", actor="tester",
        all_gate_ids=metadata.gate_sequence_ids,
    )

    response = _rpc(client, "tasks/get", {"id": "a2a-k1"})
    result = response.json()["result"]
    assert result["status"]["state"] == "input-required"
    assert result["status"]["message"]["pending_interrupt_node"] == "human_approval_G1"
    assert result["status"]["message"]["interrupt_payload_unavailable"] is True


def test_unknown_method_returns_jsonrpc_error(client: TestClient):
    response = _rpc(client, "tasks/cancel", {"id": "nope"})
    assert response.status_code == 200
    body = response.json()
    assert body["error"]["code"] == -32601
