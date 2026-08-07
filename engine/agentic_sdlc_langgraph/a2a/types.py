"""Hand-written pydantic models mirroring the minimal-plus-streaming
subset of the public A2A (Agent2Agent) wire format this engine supports:
agent card discovery, a JSON-RPC 2.0 envelope, and the `Task`/`Message`
shapes exchanged by `message/send` / `tasks/get` / `message/stream`.

Deliberately narrow: only text parts are modeled (no file/data parts),
and no push-notification/auth-scheme types are included, matching the
scope decision recorded in the implementation plan (agent card +
message/send + tasks/get + message/stream only).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel


class TextPart(BaseModel):
    kind: Literal["text"] = "text"
    text: str


class Message(BaseModel):
    role: Literal["user", "agent"] = "user"
    parts: list[TextPart] = []
    taskId: str | None = None
    contextId: str | None = None
    metadata: dict[str, Any] | None = None


class TaskState(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class TaskStatus(BaseModel):
    state: TaskState
    message: Any | None = None
    timestamp: str | None = None


class Task(BaseModel):
    id: str
    contextId: str
    status: TaskStatus
    history: list[Message] = []
    artifacts: list[Any] = []


class TaskStatusUpdateEvent(BaseModel):
    taskId: str
    contextId: str
    status: TaskStatus
    final: bool = False


class AgentCard(BaseModel):
    name: str
    description: str
    url: str
    version: str
    capabilities: dict[str, bool]
    defaultInputModes: list[str]
    defaultOutputModes: list[str]
    skills: list[dict[str, Any]]


class JSONRPCRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: Any = None
    method: str
    params: dict[str, Any] | None = None


class JSONRPCResponse(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: Any = None
    result: Any | None = None
    error: dict[str, Any] | None = None
