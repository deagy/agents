"""Agent-node machinery: the `ModelClient` protocol, a real Anthropic-backed
implementation, a deterministic fake for tests, and the LangGraph node
factory that wraps either one.

Port of the "agent nodes get a factory" idea from the architecture plan
(`make_agent_node(agent_id, kind, role_prompt, model_client)`), simplified
slightly: the role prompt is derived from `agent_id`/`kind`/an agent's own
catalog metadata/the active profile inside the node (via
`resolve_role_prompt`, a Phase 2 port of `agent_wrapper_body` /
`rich_agent_content` / `agent_wrapper_instructions`) rather than threaded
through as a separate constructor argument. `resolve_role_prompt` supports
both a provider-supplied rich role definition (`profile["rich_content_source"]`
+ an agent's `definition` file) and the generic templated instruction
fallback used whenever no richer source is available or opted into --
today, every shipped profile/catalog in this project uses the generic
fallback (see `resolve_role_prompt`'s docstring).
"""

from __future__ import annotations

import json
import os
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Protocol, TypedDict

from .provider import fingerprint, provider_resource


class Identity(TypedDict):
    id: str
    role: str
    kind: str  # "human" | "agent" | "service" -- schema's Identity.kind


class ArtifactBinding(TypedDict):
    artifact_id: str
    revision: str
    digest: str


class EvidenceRef(TypedDict):
    evidence_id: str
    uri: str
    hash_algorithm: str
    hash: str
    classification: str


class AgentOutput(TypedDict):
    agent_id: str
    kind: str  # "author" | "reviewer" -- dispatch role, not schema Identity.kind
    gate_id: str
    identity: Identity
    artifact_binding: ArtifactBinding
    evidence_ref: EvidenceRef | None
    blocking_question: str | None


class AgentContribution(TypedDict):
    """What a `ModelClient` is structurally allowed to return: its own
    contribution content, never the sensitive dispatch-identity fields
    (`agent_id`/`kind`/`gate_id`/`identity`/`evidence_ref`) that
    `make_agent_node` alone is trusted to set. This closes a
    cross-gate contribution-injection defect: a client could previously
    return a whole `AgentOutput` with a forged `gate_id`, injecting
    itself as another gate's independent verifier."""

    artifact_id: str
    revision: str
    summary: str
    blocking_question: str | None


class ModelClient(Protocol):
    def complete(
        self,
        *,
        agent_id: str,
        kind: str,
        gate_id: str,
        role_prompt: str,
        task_text: str,
    ) -> AgentContribution:
        ...


ASK_HUMAN_RULE = (
    "You are a dispatched subagent: you cannot ask the human directly. If you reach a "
    "decision only a human can make, stop and return a clearly labeled blocking question "
    "in your result instead of guessing or proceeding."
)

RICH_CONTENT_ADAPTATION_NOTE = (
    "Adapted from a role definition bundled with a provider's agent catalog. Review and "
    "tailor this role for this project's own stack, policies, and gates before relying on "
    "it -- shared-policy references in the source repository it came from will not resolve "
    "here."
)


def _agent_wrapper_instructions(agent_id: str, reviewer: bool) -> str:
    """Port of `agent_wrapper_instructions` (agentic_sdlc.py ~674-681):
    the generic templated role instruction used whenever a richer,
    provider-supplied role definition isn't available (or isn't opted
    into by the profile)."""
    return (
        f"Act as the portable Agentic SDLC role {agent_id}. "
        "Bind work to the task revision and lifecycle gate. "
        "Never approve a lifecycle or mutation gate. "
        + (
            "Remain independent and do not modify the artifact under review."
            if reviewer
            else "Prepare artifacts for independent review; do not self-review."
        )
        + " "
        + ASK_HUMAN_RULE
    )


def _rich_agent_content(definition: Any, provider_root: str | Path | None) -> str | None:
    """Port of `rich_agent_content` (agentic_sdlc.py ~700-705), extended
    with path confinement (`provider_resource`) when a `provider_root` is
    supplied. Returns `None` (triggering the generic-instruction
    fallback) whenever `definition` is missing, escapes its provider
    root, or doesn't resolve to a real file -- never raises."""
    if not isinstance(definition, str) or not definition:
        return None
    if provider_root is not None:
        try:
            path = provider_resource(Path(provider_root), definition, "definition", directory=False)
        except ValueError:
            return None
    else:
        # No root supplied: trust `definition` only if it is already an
        # absolute path (the expected shape once a provider has been
        # loaded via `provider.load_provider`, which resolves and
        # confines `definition` once, at load time -- see its
        # docstring). A relative path with no root to confine against
        # is treated as unresolved rather than resolved against cwd,
        # which would be an implicit, unconfined escape hatch.
        candidate = Path(definition)
        if not candidate.is_absolute():
            return None
        path = candidate
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8").strip()


def resolve_role_prompt(
    agent_id: str,
    kind: Literal["author", "reviewer"],
    metadata: dict[str, Any],
    profile: dict[str, Any],
    *,
    provider_root: str | Path | None = None,
) -> str:
    """Port of `agent_wrapper_body` (agentic_sdlc.py ~708-713).

    If `profile.get("rich_content_source")` is truthy and
    `metadata.get("definition")` points to a real, path-confined file,
    returns that file's stripped contents plus `RICH_CONTENT_ADAPTATION_NOTE`
    plus `ASK_HUMAN_RULE`. Otherwise returns the generic templated
    instruction (`_agent_wrapper_instructions`, which already ends in
    `ASK_HUMAN_RULE`).

    None of the three shipped profiles (`generic`/`quick`/`web-service`)
    or the `agentic-sdlc-defaults` agent catalog set `rich_content_source`
    or `definition` today, so in this project's real fixtures every agent
    still gets the generic templated instruction -- this mechanism exists
    for a future provider (e.g. `secure-cloud-agents`, which ships real
    `AGENT.md` role definitions) to opt into.

    Deviation from the task spec's literal 4-argument signature: an
    optional keyword-only `provider_root` was added. Confinement ("a
    definition can't escape its provider root") is meaningless without a
    root to confine against. In production, `metadata["definition"]` is
    already an absolute, pre-confined path by the time it reaches here --
    `provider.load_provider` resolves and confines it once, at catalog-load
    time (mirroring the legacy CLI's `load_agent_catalog()`) -- so
    `provider_root` is normally omitted. It exists so this function can
    also be unit-tested directly against a relative `definition` without
    first going through the full provider loader.
    """
    if profile.get("rich_content_source"):
        rich = _rich_agent_content(metadata.get("definition"), provider_root)
        if rich is not None:
            return "\n\n".join([rich, RICH_CONTENT_ADAPTATION_NOTE, ASK_HUMAN_RULE])
    return _agent_wrapper_instructions(agent_id, kind == "reviewer")


@dataclass
class FakeModelClient:
    """Deterministic, no-network stand-in for tests / the phase-0 smoke
    test. Never calls out to Anthropic. Canned output is a pure function of
    `agent_id`/`kind`/`gate_id` so runs are reproducible."""

    blocking_agents: set[str] = field(default_factory=set)

    def complete(
        self,
        *,
        agent_id: str,
        kind: str,
        gate_id: str,
        role_prompt: str,
        task_text: str,
    ) -> AgentContribution:
        blocking = agent_id in self.blocking_agents
        return AgentContribution(
            artifact_id=f"{gate_id}-{agent_id}-artifact",
            revision="rev-1",
            summary=f"{agent_id} completed its {kind} contribution for {gate_id}",
            blocking_question=(
                f"{agent_id} needs clarification before proceeding" if blocking else None
            ),
        )


SUBMIT_CONTRIBUTION_TOOL_NAME = "submit_contribution"
SUBMIT_CONTRIBUTION_DESCRIPTION = "Submit this agent's structured contribution for the gate."

SUBMIT_CONTRIBUTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["artifact_id", "revision", "summary"],
    "properties": {
        "artifact_id": {"type": "string"},
        "revision": {"type": "string"},
        "summary": {"type": "string"},
        "blocking_question": {"type": ["string", "null"]},
    },
}
"""Shared shape of the structured tool-call payload every real
`ModelClient` implementation asks its model to return, so
`AnthropicModelClient` and `OpenAICompatibleModelClient` don't each
maintain their own copy of the same contract -- each SDK still wraps this
schema in its own tool-declaration envelope (`input_schema` vs
`parameters`), since those envelopes aren't otherwise identical."""


@dataclass
class AnthropicModelClient:
    """Real Anthropic-backed implementation. Not exercised in this
    environment (no ANTHROPIC_API_KEY configured) -- exists so the spike
    isn't fake-only, per the phase-0 spec. Uses tool-use for a structured
    reply so we don't have to hand-roll prose parsing.
    """

    model: str = "claude-sonnet-4-5"
    api_key: str | None = None

    def _client(self):  # -> anthropic.Anthropic
        import anthropic  # local import: keep this optional dependency lazy

        return anthropic.Anthropic(api_key=self.api_key or os.environ.get("ANTHROPIC_API_KEY"))

    def complete(
        self,
        *,
        agent_id: str,
        kind: str,
        gate_id: str,
        role_prompt: str,
        task_text: str,
    ) -> AgentContribution:
        tool = {
            "name": SUBMIT_CONTRIBUTION_TOOL_NAME,
            "description": SUBMIT_CONTRIBUTION_DESCRIPTION,
            "input_schema": SUBMIT_CONTRIBUTION_SCHEMA,
        }
        client = self._client()
        response = client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=role_prompt,
            tools=[tool],
            tool_choice={"type": "tool", "name": SUBMIT_CONTRIBUTION_TOOL_NAME},
            messages=[{"role": "user", "content": task_text}],
        )
        payload: dict[str, Any] = {}
        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == SUBMIT_CONTRIBUTION_TOOL_NAME:
                payload = block.input
                break
        return AgentContribution(
            artifact_id=payload.get("artifact_id", f"{gate_id}-{agent_id}-artifact"),
            revision=payload.get("revision", "rev-1"),
            summary=payload.get("summary", ""),
            blocking_question=payload.get("blocking_question"),
        )


@dataclass
class OpenAICompatibleModelClient:
    """Talks to any OpenAI-compatible chat-completions HTTP API: OpenAI
    itself, or a self-hosted/third-party server mirroring its
    `/v1/chat/completions` request/response shape (vLLM, Ollama's
    OpenAI-compat endpoint, Azure OpenAI, LiteLLM proxies, etc) via
    `base_url`. Client-side integration only -- nothing in this repo
    serves an OpenAI-compatible API. Uses tool (function) calling for a
    structured reply, mirroring `AnthropicModelClient`.
    """

    model: str
    api_key: str | None = None
    base_url: str | None = None

    def _client(self):  # -> openai.OpenAI
        import openai  # local import: keep this optional dependency lazy

        base_url = self.base_url or os.environ.get("OPENAI_BASE_URL")
        if base_url is not None:
            # `base_url=None` is a legitimate "use the SDK's own default"
            # signal (real api.openai.com over https), not an error -- the
            # guard only applies once a base_url is actually configured.
            from .a2a.client import require_https_or_local  # local import: shared host-scheme guard

            require_https_or_local(base_url, label="OPENAI_BASE_URL")

        return openai.OpenAI(
            api_key=self.api_key or os.environ.get("OPENAI_API_KEY"),
            base_url=base_url,
        )

    def complete(
        self,
        *,
        agent_id: str,
        kind: str,
        gate_id: str,
        role_prompt: str,
        task_text: str,
    ) -> AgentContribution:
        tool = {
            "type": "function",
            "function": {
                "name": SUBMIT_CONTRIBUTION_TOOL_NAME,
                "description": SUBMIT_CONTRIBUTION_DESCRIPTION,
                "parameters": SUBMIT_CONTRIBUTION_SCHEMA,
            },
        }
        client = self._client()
        response = client.chat.completions.create(
            model=self.model,
            tools=[tool],
            tool_choice={"type": "function", "function": {"name": SUBMIT_CONTRIBUTION_TOOL_NAME}},
            messages=[
                {"role": "system", "content": role_prompt},
                {"role": "user", "content": task_text},
            ],
        )
        payload: dict[str, Any] = {}
        tool_calls = response.choices[0].message.tool_calls or []
        for call in tool_calls:
            if call.function.name == SUBMIT_CONTRIBUTION_TOOL_NAME:
                try:
                    parsed = json.loads(call.function.arguments)
                except json.JSONDecodeError:
                    # Unlike Anthropic's already-parsed `block.input`, this is a
                    # JSON string an arbitrary OpenAI-compatible server produced --
                    # non-conformant servers are exactly what this client exists to
                    # tolerate, so malformed arguments fall back to the same
                    # defaults as "no matching tool call" rather than crashing the
                    # graph node.
                    break
                if isinstance(parsed, dict):
                    payload = parsed
                break
        return AgentContribution(
            artifact_id=payload.get("artifact_id", f"{gate_id}-{agent_id}-artifact"),
            revision=payload.get("revision", "rev-1"),
            summary=payload.get("summary", ""),
            blocking_question=payload.get("blocking_question"),
        )


@dataclass
class A2AModelClient:
    """Dispatches `.complete()` to one external, A2A-reachable agent
    (e.g. a Codex CLI agent) over `message/send`, translating the
    returned `Task` back into an `AgentContribution` of the same shape
    `AnthropicModelClient.complete` builds.

    Deliberately synchronous, single-shot (`message/send`, not
    `message/stream`): `ModelClient.complete` is called from inside
    `make_agent_node`'s `node(payload)` closure, which runs synchronously
    as one LangGraph node and has no way to consume a streamed partial
    result anyway -- streaming is only exposed on the A2A *server* side
    (`a2a/server.py`), for external callers watching this engine's own
    gates progress. If the external agent's task ends in
    `input-required`, that's surfaced as a `blocking_question` rather
    than treated as an error, matching how a human-in-the-loop author
    reports "I can't decide this" today.
    """

    endpoint: str
    client: Any = None  # A2AClient, lazily constructed if not supplied
    timeout: float = 60.0

    def _a2a_client(self):
        from .a2a.client import A2AClient  # local import: avoid a hard dependency for callers that never use A2A

        if self.client is None:
            self.client = A2AClient(self.endpoint, timeout=self.timeout)
        return self.client

    def complete(
        self,
        *,
        agent_id: str,
        kind: str,
        gate_id: str,
        role_prompt: str,
        task_text: str,
    ) -> AgentContribution:
        task = self._a2a_client().send_message(f"{role_prompt}\n\n{task_text}")
        blocking_question = None
        if task.status.state.value == "input-required":
            message = task.status.message
            blocking_question = (
                message if isinstance(message, str) else f"{agent_id} needs clarification before proceeding"
            )
        # `task.artifacts`/`task.history` aren't parsed here yet (new work,
        # not this fix) -- summary stays a synthesized placeholder.
        return AgentContribution(
            artifact_id=f"{gate_id}-{agent_id}-artifact",
            revision="rev-1",
            summary=f"{agent_id} completed its {kind} contribution for {gate_id} via A2A task {task.id}",
            blocking_question=blocking_question,
        )


@dataclass
class DispatchingModelClient:
    """Routes `.complete()` to a per-`agent_id` `ModelClient` based on the
    agent catalog's `transport` field: `transport: "a2a"` entries go to an
    `A2AModelClient` built from the entry's `endpoint`; everything else
    (including agents absent from the catalog) goes to `default`.

    This is the one place the local-vs-external decision is made. It
    exists so `graph.py`'s `build_graph`/`make_agent_node` -- which take
    exactly one shared `model_client` for every node -- need no changes
    at all to support a mix of local and external agents.
    """

    default: ModelClient
    agent_catalog: dict[str, Any] = field(default_factory=dict)
    _a2a_clients: dict[str, A2AModelClient] = field(default_factory=dict, repr=False)

    def _client_for(self, agent_id: str) -> ModelClient:
        entry = self.agent_catalog.get(agent_id, {})
        if entry.get("transport") != "a2a":
            return self.default
        endpoint = entry["endpoint"]
        if agent_id not in self._a2a_clients:
            self._a2a_clients[agent_id] = A2AModelClient(endpoint=endpoint)
        return self._a2a_clients[agent_id]

    def complete(
        self,
        *,
        agent_id: str,
        kind: str,
        gate_id: str,
        role_prompt: str,
        task_text: str,
    ) -> AgentContribution:
        return self._client_for(agent_id).complete(
            agent_id=agent_id,
            kind=kind,
            gate_id=gate_id,
            role_prompt=role_prompt,
            task_text=task_text,
        )


def make_agent_node(
    agent_id: str,
    kind: str,
    model_client: ModelClient,
    metadata: dict[str, Any] | None = None,
    profile: dict[str, Any] | None = None,
    provider_root: str | Path | None = None,
) -> Callable[[dict], dict]:
    """Build a LangGraph node function bound to one agent + dispatch role.

    The node reads `gate_id` and `task_text` off whatever payload the
    triggering `Send` carried (see graph.py's dispatch conditional edges)
    and returns a state update writing one `AgentOutput` dict to its own
    `f"{gate_id}:{kind}:{agent_id}"` slot in the `agent_outputs`
    map-reduce scratch field (see `state.merge_agent_outputs` for why this
    is a keyed dict, not an append-only list: a redispatch of the same
    agent/role/gate -- e.g. after `reenter_gate` -- must overwrite its own
    prior output, not duplicate it alongside a stale one).

    `metadata` (the agent's own agent-catalog entry, e.g.
    `agent_catalog.get(agent_id, {})`) and `profile` (the active profile
    dict) are threaded through to `resolve_role_prompt` so a
    provider-supplied rich role definition is used when the profile opts
    into it (`profile["rich_content_source"]`), falling back to the
    generic templated instruction otherwise -- both default to `{}`,
    which always takes the generic-instruction path, so existing callers
    that don't pass them are unaffected.
    """
    metadata = metadata or {}
    profile = profile or {}

    def _sanitized_artifact_field(value: Any, default: str) -> str:
        # Reject anything a model client can't be trusted to assert as
        # real provenance: not a string, empty, containing a control or
        # format character (C0/C1 controls, e.g. \n or \x00; Unicode
        # format characters, e.g. zero-width space or RTL override -- a
        # display-spoofing risk once this flows into the run record), or
        # unreasonably long. Falls back to the existing default rather
        # than raising.
        if not isinstance(value, str) or not value or len(value) > 200:
            return default
        if any(unicodedata.category(char) in {"Cc", "Cf"} for char in value):
            return default
        return value

    def node(payload: dict[str, Any]) -> dict[str, Any]:
        gate_id = payload["gate_id"]
        task_text = payload.get("task_text", "")
        classification = payload.get("classification", "internal")
        role_prompt = resolve_role_prompt(agent_id, kind, metadata, profile, provider_root=provider_root)
        contribution = model_client.complete(
            agent_id=agent_id,
            kind=kind,
            gate_id=gate_id,
            role_prompt=role_prompt,
            task_text=task_text,
        )

        artifact_id = _sanitized_artifact_field(
            contribution.get("artifact_id"), f"{gate_id}-{agent_id}-artifact"
        )
        revision = _sanitized_artifact_field(contribution.get("revision"), "rev-1")

        # Digest attests self-consistency of the binding (artifact_id +
        # revision), not content -- `summary` is discarded before export
        # (run-record.schema.json has nowhere to retain it), so hashing it
        # would be unverifiable and misleadingly look like real
        # verification.
        digest = fingerprint({"artifact_id": artifact_id, "revision": revision})
        digest_hex = digest.removeprefix("sha256:")

        identity = Identity(id=agent_id, role=f"{kind}:{agent_id}", kind="agent")
        artifact_binding = ArtifactBinding(artifact_id=artifact_id, revision=revision, digest=digest)
        evidence_ref = EvidenceRef(
            evidence_id=f"{gate_id}-{agent_id}-evidence",
            uri=f"agent-dispatch://{gate_id}/{agent_id}",
            hash_algorithm="sha256",
            hash=digest_hex,
            classification=classification,
        )
        output = AgentOutput(
            agent_id=agent_id,
            kind=kind,
            gate_id=gate_id,
            identity=identity,
            artifact_binding=artifact_binding,
            evidence_ref=evidence_ref,
            blocking_question=contribution.get("blocking_question"),
        )
        slot_key = f"{gate_id}:{kind}:{agent_id}"
        return {"agent_outputs": {slot_key: dict(output)}}

    return node
