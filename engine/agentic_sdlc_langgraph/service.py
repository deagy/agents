"""Minimal FastAPI service exposing the G1-G10 lifecycle over HTTP,
with zero chat-CLI (Claude Code / Codex CLI) involvement.

This is what makes "standalone autonomous execution" concrete: a GitHub
webhook, a cron job, or any other HTTP caller can drive a task's lifecycle
end to end just by calling these three routes. Each route handler rebuilds
the graph fresh via `runtime.build_graph_for_task` (see `runtime.py`'s
module docstring) and never holds a graph object across requests -- the
persistent on-disk `SqliteSaver` at `<root>/.agentic-sdlc/state.db` is what
carries state between calls, exactly as it does between separate CLI
process invocations. A worker process, a second replica of this same
service, or the CLI can all interleave calls against the same task/root
and see consistent state, because nothing lives in this process's memory
between requests.

Deliberately minimal per the task spec: no auth, no pagination, no request
throttling, no background workers. `root` is accepted as a plain request
field (not a path-confined server-side setting) because this is a
developer-facing/internal-automation service, not something exposed to
untrusted callers -- adding real multi-tenant path confinement is future
work, not in scope here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import runtime
from .a2a.server import router as a2a_router
from .gitlab_issue import resolve_issue_reference

app = FastAPI(title="Agentic SDLC LangGraph Service")
app.include_router(a2a_router)


class CreateTaskRequest(BaseModel):
    task_id: str
    task: str
    root: str
    profile: str = "generic"
    ignored_gate_ids: list[str] = []
    provider_manifest: str | None = None
    # <project-path>#<iid> form, e.g. "group/project#42"; resolved to a
    # validated gitlab-issue:... URI in create_task below. See
    # gitlab_issue.py and cli.py's plan --intent-gitlab-issue for the same
    # capability on the CLI surface.
    intent_gitlab_issue: str | None = None
    requirements_gitlab_issue: str | None = None


class ResumeRequest(BaseModel):
    root: str
    decision: Any


@app.post("/tasks")
def create_task(payload: CreateTaskRequest) -> dict[str, Any]:
    try:
        intent_record_id = resolve_issue_reference(payload.intent_gitlab_issue)
        requirements_baseline_id = resolve_issue_reference(payload.requirements_gitlab_issue)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        return runtime.create_or_reconnect_task(
            payload.task_id,
            payload.task,
            Path(payload.root),
            profile=payload.profile,
            ignored_gate_ids=payload.ignored_gate_ids,
            provider_manifest=payload.provider_manifest,
            intent_record_id=intent_record_id,
            requirements_baseline_id=requirements_baseline_id,
        )
    except runtime.GraphConfigError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/tasks/{task_id}/resume")
def resume_task(task_id: str, payload: ResumeRequest) -> dict[str, Any]:
    try:
        return runtime.resume_task_at(task_id, Path(payload.root), payload.decision)
    except runtime.GraphConfigError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/tasks/{task_id}")
def get_task_status(task_id: str, root: str) -> dict[str, Any]:
    try:
        return runtime.task_status_at(task_id, Path(root))
    except runtime.GraphConfigError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
