"""Tests for the A2A (Agent2Agent) client surface: `a2a.client.A2AClient`,
`agents.A2AModelClient`, and `agents.DispatchingModelClient`.

The "external A2A agent" in these tests is a second, standalone FastAPI
app mounting this engine's own `a2a.server.router` (exactly the module
under test in `test_a2a_service.py`), reached via `httpx.ASGITransport`
so no real network port is needed -- it stands in for an external Codex
CLI agent that happens to also speak this engine's own A2A surface.
"""

from __future__ import annotations

import sqlite3

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite import SqliteSaver

import agentic_sdlc_langgraph.a2a.client as a2a_client_module
from agentic_sdlc_langgraph.a2a.client import A2AClient
from agentic_sdlc_langgraph.a2a.server import router as a2a_router
from agentic_sdlc_langgraph.agents import A2AModelClient, DispatchingModelClient, FakeModelClient
from agentic_sdlc_langgraph.graph import build_graph

FAKE_AGENT_BASE_URL = "http://localhost"

# Saved before the autouse `_route_a2a_client_through_fake_app` fixture
# monkeypatches `a2a_client_module.httpx.Client` for the duration of each
# test -- needed by tests that want a real `httpx.Client` bound to a
# `MockTransport` rather than the fake-app routing.
_REAL_HTTPX_CLIENT = httpx.Client


@pytest.fixture(autouse=True)
def _fake_model_and_a2a_root(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("AGENTIC_SDLC_LANGGRAPH_FAKE_MODEL", "1")
    monkeypatch.setenv("AGENTIC_SDLC_LANGGRAPH_A2A_ROOT", str(tmp_path / "external-agent-root"))


@pytest.fixture()
def fake_external_agent_app() -> FastAPI:
    app = FastAPI()
    app.include_router(a2a_router)
    return app


@pytest.fixture()
def http_client(fake_external_agent_app: FastAPI) -> TestClient:
    return TestClient(fake_external_agent_app, base_url=FAKE_AGENT_BASE_URL)


@pytest.fixture(autouse=True)
def _route_a2a_client_through_fake_app(monkeypatch: pytest.MonkeyPatch, fake_external_agent_app: FastAPI):
    """`A2AModelClient`/`DispatchingModelClient` construct their own
    `A2AClient(endpoint)` internally (no injected transport), exactly as
    they would in production dialing a real endpoint URL. To exercise
    that real construction path in tests without a real network port,
    patch `httpx.Client` as seen from `a2a.client` so any base_url it's
    asked for is transparently routed to the in-process fake agent app
    via FastAPI's `TestClient` (an `httpx.Client` subclass that bridges
    sync calls onto the ASGI app -- plain `httpx.ASGITransport` only
    supports async and can't back a sync `httpx.Client` directly).
    """

    def _client(*, base_url: str, timeout: float | None = None) -> TestClient:
        return TestClient(fake_external_agent_app, base_url=base_url)

    monkeypatch.setattr(a2a_client_module.httpx, "Client", _client)


def test_a2a_client_send_message_round_trip(http_client: TestClient):
    client = A2AClient(FAKE_AGENT_BASE_URL, http_client=http_client)
    task = client.send_message(
        "Define and review a small internal order-processing API architecture and service",
        task_id="client-task-1",
    )
    assert task.id == "client-task-1"
    assert task.status.state.value == "input-required"
    assert task.status.message["gate_id"] == "G1"


def test_a2a_client_get_task_matches_send(http_client):
    client = A2AClient(FAKE_AGENT_BASE_URL, http_client=http_client)
    client.send_message(
        "Define and review a small internal order-processing API architecture and service",
        task_id="client-task-2",
    )
    task = client.get_task("client-task-2")
    assert task.status.state.value == "input-required"
    assert task.status.message["gate_id"] == "G1"


def test_a2a_model_client_round_trips_into_agent_output():
    model_client = A2AModelClient(endpoint=FAKE_AGENT_BASE_URL)
    contribution = model_client.complete(
        agent_id="external-author",
        kind="author",
        gate_id="G1",
        role_prompt="Act as the external author.",
        task_text="Define and review a small internal order-processing API architecture and service",
    )
    # A2AModelClient.complete only returns an AgentContribution now --
    # agent_id/kind/gate_id/identity/evidence_ref are constructed by
    # make_agent_node itself, from data the node controls, never from the
    # client's return value; this is what keeps separation-of-duties
    # enforcement in graph.py transport-agnostic and immune to a client
    # asserting another gate's identity.
    assert contribution["artifact_id"] == "G1-external-author-artifact"
    assert contribution["revision"] == "rev-1"
    # The fake external agent is a full SDLC lifecycle (this engine's own
    # `a2a/server.py`), so its task immediately reaches G1's human-approval
    # interrupt (`input-required`) -- correctly surfaced as a
    # `blocking_question` rather than a completed artifact.
    assert contribution["blocking_question"] == "external-author needs clarification before proceeding"


def test_dispatching_model_client_routes_local_vs_a2a_by_catalog_transport():
    agent_catalog = {
        "local-author": {"kind": "author", "capabilities": ["author"]},
        "external-reviewer": {
            "kind": "reviewer",
            "capabilities": ["reviewer"],
            "transport": "a2a",
            "endpoint": FAKE_AGENT_BASE_URL,
        },
    }
    default = FakeModelClient()
    dispatcher = DispatchingModelClient(default=default, agent_catalog=agent_catalog)

    local_contribution = dispatcher.complete(
        agent_id="local-author", kind="author", gate_id="G1", role_prompt="p", task_text="t"
    )
    assert local_contribution["artifact_id"] == "G1-local-author-artifact"

    external_contribution = dispatcher.complete(
        agent_id="external-reviewer", kind="reviewer", gate_id="G1", role_prompt="p", task_text="t"
    )
    assert external_contribution["artifact_id"] == "G1-external-reviewer-artifact"


def test_build_graph_separation_of_duties_fires_with_external_author_and_reviewer(tmp_path):
    """End-to-end: one gate whose author is dispatched via A2A
    (`DispatchingModelClient` -> `A2AModelClient` -> the fake external
    agent) and whose reviewer (via a colliding route, same pattern as
    `test_spike.py`'s collision test) resolves to the *same* agent id.
    `gate_decision_{gate_id}` must still detect the collision and block
    the gate -- proving separation-of-duties enforcement is unaffected
    by one side's output having been produced over A2A rather than
    in-process.
    """
    gates = [
        {
            "id": "G1",
            "name": "Intent",
            "required_contributions": ["intent"],
            "prerequisites": [],
            "authority_requirements": ["product_owner"],
        }
    ]
    gate_bindings = {
        "G1": {
            "contributions": {
                "intent": {
                    "agents": ["external-author"],
                    "tasks": ["capture-intent"],
                    "artifacts": ["intent-record"],
                }
            }
        }
    }
    routes = [
        {
            "id": "colliding-route",
            "phrases": ["architecture"],
            "agents": [],
            "reviewers": ["external-author"],
            "support": [],
            "gates": ["G1"],
        }
    ]
    agent_catalog = {
        "external-author": {
            "kind": "author",
            "capabilities": ["author"],
            "transport": "a2a",
            "endpoint": FAKE_AGENT_BASE_URL,
        },
    }

    model_client = DispatchingModelClient(default=FakeModelClient(), agent_catalog=agent_catalog)
    checkpointer = SqliteSaver(sqlite3.connect(":memory:", check_same_thread=False))
    graph = build_graph(
        gates=gates,
        gate_bindings=gate_bindings,
        routes=routes,
        agent_catalog=agent_catalog,
        model_client=model_client,
        checkpointer=checkpointer,
        mutation_gates=[],
    )
    config = {"configurable": {"thread_id": "task-a2a-collision"}}
    initial_state = {
        "task_id": "task-a2a-collision",
        "classification": "internal",
        "scope": "architecture review task",
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
    assert "cannot approve" in payload["reason"].lower() or "violation" in payload["reason"].lower()

    state_snapshot = graph.get_state(config)
    assert state_snapshot.values["lifecycle_gates"]["G1"]["status"] == "blocked"
    # `evidence_ref.uri` is now built generically by `make_agent_node`
    # (never per-transport), so it no longer distinguishes A2A from local
    # dispatch. Confirm the A2A path actually ran instead via the fake
    # external agent's own on-disk task lookup, which is only written
    # when a real message/send round trip reaches it.
    a2a_lookup_path = tmp_path / "external-agent-root" / ".agentic-sdlc" / "a2a-tasks.json"
    assert a2a_lookup_path.is_file()


def test_a2a_client_rejects_plain_http_for_non_local_host():
    with pytest.raises(ValueError):
        A2AClient("http://external-agent.example.com")


def test_a2a_client_accepts_plain_http_for_localhost():
    # Accepted at construction time; no real network call is made here.
    client = A2AClient("http://localhost:9999")
    assert client is not None


def test_a2a_client_accepts_plain_http_for_127_0_0_1():
    client = A2AClient("http://127.0.0.1:9999")
    assert client is not None


def test_a2a_client_accepts_plain_http_for_ipv6_loopback():
    client = A2AClient("http://[::1]:9999")
    assert client is not None


def test_a2a_client_rejects_agent_card_pointing_at_different_origin():
    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/.well-known/agent.json"
        return httpx.Response(200, json={"url": "https://attacker.example.com/a2a"})

    http_client = _REAL_HTTPX_CLIENT(base_url="http://localhost", transport=httpx.MockTransport(_handler))
    client = A2AClient("http://localhost", http_client=http_client)

    with pytest.raises(ValueError):
        client.send_message("hello")


def test_a2a_model_client_threads_timeout_into_constructed_a2a_client(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    class _RecordingA2AClient:
        def __init__(self, base_url, *, timeout=None, http_client=None):
            captured["base_url"] = base_url
            captured["timeout"] = timeout

    monkeypatch.setattr(a2a_client_module, "A2AClient", _RecordingA2AClient)
    model_client = A2AModelClient(endpoint=FAKE_AGENT_BASE_URL, timeout=12.5)
    model_client._a2a_client()

    assert captured["timeout"] == 12.5


def test_a2a_client_timeout_reaches_the_real_httpx_client(monkeypatch: pytest.MonkeyPatch):
    """The test above only proves the `timeout` kwarg reaches a *mocked*
    `A2AClient`. This proves it genuinely reaches the real
    `httpx.Client(...)` constructed inside `A2AClient.__init__` when no
    `http_client` is injected -- the autouse fixture's fake-app routing is
    bypassed here on purpose, via the saved real `httpx.Client`."""
    monkeypatch.setattr(a2a_client_module.httpx, "Client", _REAL_HTTPX_CLIENT)

    client = A2AClient("http://localhost", timeout=12.5)

    assert client._http.timeout.connect == 12.5
    assert client._http.timeout.read == 12.5
