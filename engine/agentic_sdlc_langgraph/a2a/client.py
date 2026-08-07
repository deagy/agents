"""Thin `httpx`-based A2A client: used by `agents.A2AModelClient` to
dispatch an author/reviewer node to an external, A2A-reachable agent
(e.g. a Codex CLI agent) instead of an in-process `AnthropicModelClient`
call.

Only what `ModelClient.complete`'s synchronous contract needs is
implemented: `send_message` (`message/send`, used for the actual
dispatch) and `get_task` (`tasks/get`, for polling). Streaming
(`message/stream`) is intentionally not used on this client path -- see
`agents.A2AModelClient`'s docstring for why.
"""

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import urlsplit

import httpx

from .types import Message, Task, TextPart

DEFAULT_TIMEOUT = 60.0
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def require_https_or_local(url: str, *, label: str) -> None:
    """Raise `ValueError` unless `url` uses https or points at a
    recognized local-dev host (localhost/127.0.0.1/::1). Shared by
    `A2AClient` and `agents.OpenAICompatibleModelClient` so a
    misconfigured plain-http endpoint/base_url can't silently send
    credentials or role-prompt/task content in cleartext."""
    parsed = urlsplit(url)
    if parsed.scheme != "https" and parsed.hostname not in _LOCAL_HOSTS:
        raise ValueError(f"{label} {url!r} must use https unless the host is a recognized local-dev host")


class A2AClient:
    """Talks to one external A2A agent's JSON-RPC endpoint, discovered
    via its agent card. `transport` may be a real `httpx.Client` or an
    `httpx.Client(transport=httpx.ASGITransport(app=...))` for talking to
    an in-process ASGI app in tests, without a real network port."""

    def __init__(
        self,
        base_url: str,
        *,
        http_client: httpx.Client | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        require_https_or_local(base_url, label="A2A endpoint")
        # Auth headers/credentials for the A2A endpoint would go here --
        # tracked as a known, owned gap; not implemented in this change
        # (would require new agent-catalog schema surface).
        self._base_url = base_url.rstrip("/")
        self._http = http_client or httpx.Client(base_url=self._base_url, timeout=timeout)
        self._rpc_url: str | None = None

    def _endpoint(self) -> str:
        if self._rpc_url is None:
            response = self._http.get("/.well-known/agent.json")
            response.raise_for_status()
            card = response.json()
            rpc_url = card["url"]
            base = urlsplit(self._base_url)
            rpc = urlsplit(rpc_url)
            if (base.scheme, base.hostname, base.port) != (rpc.scheme, rpc.hostname, rpc.port):
                raise ValueError(
                    f"agent card url {rpc_url!r} origin does not match configured endpoint {self._base_url!r}"
                )
            self._rpc_url = rpc_url
        return self._rpc_url

    def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = uuid.uuid4().hex
        response = self._http.post(
            self._endpoint(),
            json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise RuntimeError(f"A2A error from {self._base_url!r}: {payload['error']}")
        return payload["result"]

    def send_message(self, text: str, *, task_id: str | None = None, metadata: dict[str, Any] | None = None) -> Task:
        """Create (or reconnect to) a task and send it `text`. `task_id`
        becomes the *new* task's id via `metadata.task_id` -- it is
        deliberately not set on `Message.taskId`, which this engine's A2A
        server (`a2a/server.py`) reserves for *continuing* an existing
        task (e.g. supplying a human-approval decision). Use
        `continue_task` for that instead."""
        combined_metadata = dict(metadata or {})
        if task_id is not None:
            combined_metadata["task_id"] = task_id
        message = Message(role="user", parts=[TextPart(text=text)], metadata=combined_metadata or None)
        result = self._call("message/send", {"message": message.model_dump(exclude_none=True)})
        return Task.model_validate(result)

    def continue_task(self, task_id: str, decision: Any) -> Task:
        """Continue an already-created task with a decision (e.g. a
        human-approval payload), equivalent to `POST /tasks/{id}/resume`
        on the plain REST surface."""
        message = Message(role="user", parts=[], taskId=task_id, metadata={"decision": decision})
        result = self._call("message/send", {"message": message.model_dump(exclude_none=True)})
        return Task.model_validate(result)

    def get_task(self, task_id: str) -> Task:
        result = self._call("tasks/get", {"id": task_id})
        return Task.model_validate(result)
