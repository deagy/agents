"""A2A (Agent2Agent) protocol server surface: agent card discovery plus a
single JSON-RPC endpoint (`message/send`, `tasks/get`, `message/stream`)
mounted into `service.py`'s FastAPI app. Reuses the exact same
task-lifecycle helpers the plain REST routes call (`runtime.
create_or_reconnect_task` / `resume_task_at` / `task_status_at`), so an
A2A caller and a REST/CLI caller operating on the same `task_id`/`root`
see identical behavior.

## The `taskId` -> `root` problem

A2A's wire format only carries an opaque `taskId` (no `root` field --
this system's multi-root concept doesn't exist in the A2A spec). Every
task created through this router is recorded in a small on-disk lookup,
`<default_root>/.agentic-sdlc/a2a-tasks.json`, mapping `taskId -> root`,
so a later `tasks/get`/continuation call can find the right root again.
`default_root` is fixed per-process (env var
`AGENTIC_SDLC_LANGGRAPH_A2A_ROOT`, default: current working directory),
consistent with this service's existing single-tenant, no-auth scope
(see `service.py`'s module docstring) -- multi-root A2A serving is
future work, not needed for this engine's own automation use case.

## Task/message mapping

One A2A `Task` = one SDLC task run (`task_id`). A `message/send` call
with no `taskId` on the message plans a new task (or reconnects a
no-op-if-already-planned one); a call with `taskId` set is a
continuation carrying a human-approval decision, equivalent to
`POST /tasks/{task_id}/resume`. See the implementation plan for the
full state-mapping rationale.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Callable, Iterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from langgraph.types import Command

from .. import runtime
from .types import (
    AgentCard,
    JSONRPCRequest,
    JSONRPCResponse,
    Message,
    Task,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)

router = APIRouter()

A2A_ROOT_ENV_VAR = "AGENTIC_SDLC_LANGGRAPH_A2A_ROOT"


def _default_root() -> Path:
    return Path(os.environ.get(A2A_ROOT_ENV_VAR, ".")).resolve()


def _lookup_path(default_root: Path) -> Path:
    return default_root / ".agentic-sdlc" / "a2a-tasks.json"


def _load_lookup(default_root: Path) -> dict[str, str]:
    path = _lookup_path(default_root)
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _record_lookup(default_root: Path, task_id: str, root: Path) -> None:
    path = _lookup_path(default_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = _load_lookup(default_root)
    entries[task_id] = str(root)
    path.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _root_for_task(default_root: Path, task_id: str) -> Path:
    entries = _load_lookup(default_root)
    root = entries.get(task_id)
    if root is None:
        raise HTTPException(status_code=404, detail=f"unknown A2A task {task_id!r}")
    return Path(root)


def _build_agent_card(base_url: str) -> AgentCard:
    all_gates = runtime.load_lifecycle_gates(runtime.CONTRACTS_DIR / "lifecycle-gates.json")
    skills = [
        {
            "id": "run-sdlc-task",
            "name": "Run Agentic SDLC task",
            "description": (
                "Plan and drive a task through the Agentic SDLC lifecycle gates "
                f"({', '.join(g['id'] for g in all_gates)}), pausing for human "
                "approval and reporting/streaming status as it progresses."
            ),
            "tags": ["sdlc", "lifecycle", "orchestration"],
        }
    ]
    return AgentCard(
        name="agentic-sdlc",
        description="Agentic SDLC LangGraph engine, exposed over A2A.",
        url=base_url.rstrip("/") + "/a2a",
        version="0.1.0",
        capabilities={"streaming": True, "pushNotifications": False},
        defaultInputModes=["text"],
        defaultOutputModes=["text"],
        skills=skills,
    )


def _status_from_invoke_result(result: dict[str, Any]) -> TaskStatus:
    if result["status"] == "interrupted":
        return TaskStatus(state=TaskState.INPUT_REQUIRED, message=result["interrupt"])
    return TaskStatus(state=TaskState.COMPLETED, message=None)


def _status_from_summary(summary: dict[str, Any]) -> TaskStatus:
    if summary["interrupted"]:
        # `interrupt` can legitimately be `None` here (see runtime.py's
        # `status_summary`): an `update_state` call (invalidate/reenter)
        # empties `snapshot.interrupts` while the graph stays genuinely
        # suspended. Never fabricate a payload we don't have -- surface
        # the fallback fields instead of silently dropping to `None`.
        message = (
            summary["interrupt"]
            if summary["interrupt"] is not None
            else {
                "interrupt_payload_unavailable": summary.get("interrupt_payload_unavailable", False),
                "pending_interrupt_node": summary.get("pending_interrupt_node"),
            }
        )
        return TaskStatus(state=TaskState.INPUT_REQUIRED, message=message)
    applicable = [g for g in summary["gates"] if g["applicability"] != "not-applicable"]
    # Vacuously true for an empty `applicable` list -- a zero-gate task
    # (e.g. "needs-triage": no route phrase matched, so
    # `derive_gate_sequence` returned no gates at all) never interrupts
    # and is complete on its first invoke, so `tasks/get` must agree with
    # `message/send`'s `invoke_result_payload`-derived "complete" rather
    # than reporting "working" forever.
    all_approved = all(g["status"] == "approved" for g in applicable)
    state = TaskState.COMPLETED if all_approved else TaskState.WORKING
    return TaskStatus(state=state, message=None)


def _decision_from(message: Message, text: str) -> Any:
    metadata = message.metadata or {}
    if "decision" in metadata:
        return metadata["decision"]
    return json.loads(text)


def _handle_message_send(params: dict[str, Any]) -> Task:
    message = Message.model_validate(params["message"])
    default_root = _default_root()
    metadata = message.metadata or {}
    text = message.parts[0].text if message.parts else ""

    if message.taskId:
        task_id = message.taskId
        root = _root_for_task(default_root, task_id)
        try:
            result = runtime.resume_task_at(task_id, root, _decision_from(message, text))
        except runtime.GraphConfigError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Task(id=task_id, contextId=task_id, status=_status_from_invoke_result(result), history=[], artifacts=[])

    task_id = metadata.get("task_id") or uuid.uuid4().hex
    root = Path(metadata.get("root", str(default_root)))
    try:
        result = runtime.create_or_reconnect_task(
            task_id,
            text,
            root,
            profile=metadata.get("profile", "generic"),
            ignored_gate_ids=metadata.get("ignored_gate_ids", []),
            provider_manifest=metadata.get("provider_manifest"),
        )
    except runtime.GraphConfigError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    _record_lookup(default_root, task_id, root)

    if result["status"] == "already-planned":
        status = TaskStatus(state=TaskState.SUBMITTED, message=None)
    else:
        status = _status_from_invoke_result(result)
    return Task(id=task_id, contextId=task_id, status=status, history=[], artifacts=[])


def _handle_tasks_get(params: dict[str, Any]) -> Task:
    task_id = params["id"]
    default_root = _default_root()
    root = _root_for_task(default_root, task_id)
    try:
        summary = runtime.task_status_at(task_id, root)
    except runtime.GraphConfigError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Task(id=task_id, contextId=task_id, status=_status_from_summary(summary), history=[], artifacts=[])


def _sse_event(event: TaskStatusUpdateEvent) -> str:
    return f"data: {event.model_dump_json()}\n\n"


def _make_stream_source(params: dict[str, Any]) -> Callable[[], Iterator[str]]:
    """Resolve the graph/config/input for a streamed `message/send` up
    front (so config errors surface before any SSE bytes are written),
    returning a generator that drives `graph.stream(..., stream_mode=
    "updates")` and yields one `TaskStatusUpdateEvent` per node
    completion, ending with a `final: true` terminal-status event."""
    message = Message.model_validate(params["message"])
    default_root = _default_root()
    metadata = message.metadata or {}
    text = message.parts[0].text if message.parts else ""

    if message.taskId:
        task_id = message.taskId
        root = _root_for_task(default_root, task_id)
        try:
            graph, config, _metadata = runtime.build_graph_for_task(root, task_id)
        except runtime.GraphConfigError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        stream_input: Any = Command(resume=_decision_from(message, text))
    else:
        task_id = metadata.get("task_id") or uuid.uuid4().hex
        root = Path(metadata.get("root", str(default_root)))
        try:
            graph, config, _metadata = runtime.build_graph_for_task(
                root,
                task_id,
                task_text=text,
                profile_id=metadata.get("profile", "generic"),
                provider_manifest=metadata.get("provider_manifest"),
                ignored_gate_ids=metadata.get("ignored_gate_ids", []),
            )
        except runtime.GraphConfigError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        _record_lookup(default_root, task_id, root)
        stream_input = runtime.initial_state(task_id, text)

    def event_source() -> Iterator[str]:
        for update in graph.stream(stream_input, config=config, stream_mode="updates"):
            node_name = next(iter(update.keys())) if update else "unknown"
            yield _sse_event(
                TaskStatusUpdateEvent(
                    taskId=task_id,
                    contextId=task_id,
                    status=TaskStatus(state=TaskState.WORKING, message={"node": node_name}),
                    final=False,
                )
            )
        snapshot = graph.get_state(config)
        status = runtime.interrupt_status(snapshot)
        if status.interrupted:
            # Same fallback as `status_summary`/`_status_from_summary`
            # (see `runtime.interrupt_status`): a genuinely pending
            # interrupt whose payload was cleared by an `update_state`
            # call (invalidate/reenter) must never be reported as
            # "completed", even though no real payload is available.
            message = (
                status.interrupt_value
                if status.interrupt_value is not None
                else {
                    "interrupt_payload_unavailable": status.interrupt_payload_unavailable,
                    "pending_interrupt_node": status.pending_interrupt_node,
                }
            )
            final_status = TaskStatus(state=TaskState.INPUT_REQUIRED, message=message)
        else:
            final_status = TaskStatus(state=TaskState.COMPLETED, message=None)
        yield _sse_event(
            TaskStatusUpdateEvent(taskId=task_id, contextId=task_id, status=final_status, final=True)
        )

    return event_source


_METHODS: dict[str, Callable[[dict[str, Any]], Task]] = {
    "message/send": _handle_message_send,
    "tasks/get": _handle_tasks_get,
}


@router.get("/.well-known/agent.json", response_model=AgentCard)
def agent_card(request: Request) -> AgentCard:
    return _build_agent_card(str(request.base_url))


@router.post("/a2a")
def a2a_rpc(payload: dict[str, Any]):
    rpc = JSONRPCRequest.model_validate(payload)

    if rpc.method == "message/stream":
        event_source = _make_stream_source(rpc.params or {})
        return StreamingResponse(event_source(), media_type="text/event-stream")

    handler = _METHODS.get(rpc.method)
    if handler is None:
        return JSONRPCResponse(
            id=rpc.id, error={"code": -32601, "message": f"method not found: {rpc.method}"}
        ).model_dump(exclude_none=True)

    result = handler(rpc.params or {})
    return JSONRPCResponse(id=rpc.id, result=result.model_dump()).model_dump(exclude_none=True)
