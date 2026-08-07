"""Tests for `agentic_sdlc_langgraph.runtime` (`build_graph_for_task` and
its `graph-config.json` metadata file), the shared graph-rebuild logic
`cli.py` and `service.py` both depend on.

These tests exercise `build_graph_for_task` directly (not through the CLI
or the service) with an explicit `:memory:` checkpointer override, to keep
these tests fast and isolated from the on-disk-sqlite-file behavior (which
is exercised separately, deliberately, by `test_default_checkpointer_is_a_
persistent_on_disk_file` below and by the cross-process tests in
`test_cli.py`).
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from agentic_sdlc_langgraph import runtime
from agentic_sdlc_langgraph.agents import AnthropicModelClient, FakeModelClient, OpenAICompatibleModelClient

TASK_TEXT = "Define and review a small internal order-processing API architecture and service"
PROVIDER_DEFAULTS = runtime.KERNEL_ROOT / "providers" / "agentic-sdlc-defaults"


def _memory_checkpointer() -> SqliteSaver:
    return SqliteSaver(sqlite3.connect(":memory:", check_same_thread=False))


def test_first_call_requires_task_text(tmp_path: Path):
    with pytest.raises(runtime.GraphConfigError, match="task_text is required"):
        runtime.build_graph_for_task(
            tmp_path, "task-1", model_client=FakeModelClient(), checkpointer=_memory_checkpointer()
        )


def test_first_call_writes_graph_config_json(tmp_path: Path):
    graph, config, metadata = runtime.build_graph_for_task(
        tmp_path,
        "task-1",
        task_text=TASK_TEXT,
        model_client=FakeModelClient(),
        checkpointer=_memory_checkpointer(),
    )
    assert config == {"configurable": {"thread_id": "task-1"}}
    assert metadata.gate_sequence_ids == ["G1", "G2", "G3"]

    config_path = tmp_path / ".agentic-sdlc" / "runs" / "task-1" / "graph-config.json"
    assert config_path.is_file()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload == {
        "schema_version": runtime.GRAPH_CONFIG_SCHEMA_VERSION,
        "task_id": "task-1",
        "task_text": TASK_TEXT,
        "profile_id": "generic",
        "provider_manifest": None,
        "ignored_gate_ids": [],
        "gate_sequence_ids": ["G1", "G2", "G3"],
        "agent_catalog_digest": payload["agent_catalog_digest"],
        "created_at": payload["created_at"],
    }
    assert payload["agent_catalog_digest"].startswith("sha256:")

    # The graph itself is genuinely usable: it interrupts at G1.
    result = graph.invoke(runtime.initial_state("task-1", TASK_TEXT), config=config)
    assert result["__interrupt__"][0].value["gate_id"] == "G1"


def test_later_call_rebuilds_identical_graph_without_task_text(tmp_path: Path):
    checkpointer = _memory_checkpointer()
    graph, config, _metadata = runtime.build_graph_for_task(
        tmp_path, "task-1", task_text=TASK_TEXT, model_client=FakeModelClient(), checkpointer=checkpointer
    )
    graph.invoke(runtime.initial_state("task-1", TASK_TEXT), config=config)

    # Reconnect: no task_text needed, same checkpointer (simulating "the
    # same on-disk sqlite file, opened again") -> same graph shape, same
    # checkpointed state.
    graph2, config2, metadata2 = runtime.build_graph_for_task(
        tmp_path, "task-1", model_client=FakeModelClient(), checkpointer=checkpointer
    )
    assert config2 == config
    assert metadata2.gate_sequence_ids == ["G1", "G2", "G3"]

    snapshot = graph2.get_state(config2)
    assert snapshot.values["scope"] == TASK_TEXT
    assert snapshot.interrupts[0].value["gate_id"] == "G1"

    approval = {
        "status": "approved",
        "approver": {"id": "x", "role": "x", "kind": "human"},
        "evidence_refs": [{
            "evidence_id": "test-evidence",
            "uri": "test-evidence:manual",
            "hash_algorithm": "sha256",
            "hash": "0" * 64,
            "classification": "internal",
        }],
    }
    result = graph2.invoke(Command(resume=approval), config=config2)
    assert result["__interrupt__"][0].value["gate_id"] == "G2"


def test_conflicting_task_text_raises(tmp_path: Path):
    runtime.build_graph_for_task(
        tmp_path, "task-1", task_text=TASK_TEXT, model_client=FakeModelClient(), checkpointer=_memory_checkpointer()
    )
    with pytest.raises(runtime.GraphConfigError, match="already exists with different task text"):
        runtime.build_graph_for_task(
            tmp_path,
            "task-1",
            task_text="a completely different task",
            model_client=FakeModelClient(),
            checkpointer=_memory_checkpointer(),
        )


def test_same_task_text_on_existing_task_is_accepted(tmp_path: Path):
    runtime.build_graph_for_task(
        tmp_path, "task-1", task_text=TASK_TEXT, model_client=FakeModelClient(), checkpointer=_memory_checkpointer()
    )
    # Re-supplying the *same* task text for an already-planned task must
    # not raise -- only a *different* task text is a conflict.
    _graph, _config, metadata = runtime.build_graph_for_task(
        tmp_path, "task-1", task_text=TASK_TEXT, model_client=FakeModelClient(), checkpointer=_memory_checkpointer()
    )
    assert metadata.task_text == TASK_TEXT


def test_task_exists(tmp_path: Path):
    assert runtime.task_exists(tmp_path, "task-1") is False
    runtime.build_graph_for_task(
        tmp_path, "task-1", task_text=TASK_TEXT, model_client=FakeModelClient(), checkpointer=_memory_checkpointer()
    )
    assert runtime.task_exists(tmp_path, "task-1") is True


def test_default_checkpointer_is_a_persistent_on_disk_file(tmp_path: Path):
    """The default (no `checkpointer=` override) must be a real on-disk
    sqlite file at `<root>/.agentic-sdlc/state.db`, not `:memory:` -- an
    in-memory checkpointer cannot survive across the separate process
    invocations this module exists to support."""
    graph, config, _metadata = runtime.build_graph_for_task(
        tmp_path, "task-1", task_text=TASK_TEXT, model_client=FakeModelClient()
    )
    db_path = tmp_path / ".agentic-sdlc" / "state.db"
    graph.invoke(runtime.initial_state("task-1", TASK_TEXT), config=config)
    assert db_path.is_file()
    assert db_path.stat().st_size > 0  # real checkpoint data was actually written

    # Reopen a *brand new* graph/checkpointer against the same file (no
    # object shared with the call above) and confirm the checkpointed
    # state is actually there.
    graph2, config2, _metadata2 = runtime.build_graph_for_task(
        tmp_path, "task-1", model_client=FakeModelClient()
    )
    snapshot = graph2.get_state(config2)
    assert snapshot.values["scope"] == TASK_TEXT


def test_default_model_client_is_fake_when_env_var_set(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(runtime.FAKE_MODEL_ENV_VAR, "1")
    assert isinstance(runtime.default_model_client(), FakeModelClient)


def _clear_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        runtime.FAKE_MODEL_ENV_VAR,
        runtime.MODEL_PROVIDER_ENV_VAR,
        runtime.OPENAI_MODEL_ENV_VAR,
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)


def test_default_model_client_raises_when_no_provider_configured(monkeypatch: pytest.MonkeyPatch):
    # Anthropic is not an implicit default: with neither MODEL_PROVIDER_ENV_VAR
    # nor any provider credential set, dispatch must fail fast with an
    # actionable error rather than silently assuming Anthropic and only
    # failing later, inside the SDK, once a gate actually dispatches.
    _clear_provider_env(monkeypatch)
    with pytest.raises(runtime.GraphConfigError, match="no model provider configured"):
        runtime.default_model_client()


def test_default_model_client_autodetects_anthropic_from_api_key(monkeypatch: pytest.MonkeyPatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert isinstance(runtime.default_model_client(), AnthropicModelClient)


def test_default_model_client_autodetects_openai_from_api_key(monkeypatch: pytest.MonkeyPatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv(runtime.OPENAI_MODEL_ENV_VAR, "gpt-4o-mini")
    client = runtime.default_model_client()
    assert isinstance(client, OpenAICompatibleModelClient)
    assert client.model == "gpt-4o-mini"


def test_default_model_client_raises_when_both_credentials_present(monkeypatch: pytest.MonkeyPatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv(runtime.OPENAI_MODEL_ENV_VAR, "gpt-4o-mini")
    with pytest.raises(runtime.GraphConfigError, match="set .*MODEL_PROVIDER"):
        runtime.default_model_client()


def test_default_model_client_is_anthropic_when_provider_explicit(monkeypatch: pytest.MonkeyPatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv(runtime.MODEL_PROVIDER_ENV_VAR, "anthropic")
    assert isinstance(runtime.default_model_client(), AnthropicModelClient)


def test_default_model_client_is_openai_when_provider_set(monkeypatch: pytest.MonkeyPatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv(runtime.MODEL_PROVIDER_ENV_VAR, "openai")
    monkeypatch.setenv(runtime.OPENAI_MODEL_ENV_VAR, "gpt-4o-mini")
    client = runtime.default_model_client()
    assert isinstance(client, OpenAICompatibleModelClient)
    assert client.model == "gpt-4o-mini"


def test_default_model_client_openai_requires_model_env_var(monkeypatch: pytest.MonkeyPatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv(runtime.MODEL_PROVIDER_ENV_VAR, "openai")
    with pytest.raises(runtime.GraphConfigError):
        runtime.default_model_client()


def test_default_model_client_rejects_unknown_provider(monkeypatch: pytest.MonkeyPatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv(runtime.MODEL_PROVIDER_ENV_VAR, "bogus")
    with pytest.raises(runtime.GraphConfigError):
        runtime.default_model_client()


def test_fake_model_env_var_takes_precedence_over_provider(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(runtime.FAKE_MODEL_ENV_VAR, "1")
    monkeypatch.setenv(runtime.MODEL_PROVIDER_ENV_VAR, "openai")
    assert isinstance(runtime.default_model_client(), FakeModelClient)


def test_ignored_gates_are_recorded_and_excluded(tmp_path: Path):
    # "service" alone would (per the shipped generic profile's one route)
    # still match the new-service route and pull in G1-G3; ignoring G2
    # should leave G1 and G3 in the derived sequence.
    _graph, _config, metadata = runtime.build_graph_for_task(
        tmp_path,
        "task-1",
        task_text=TASK_TEXT,
        ignored_gate_ids=["G2"],
        model_client=FakeModelClient(),
        checkpointer=_memory_checkpointer(),
    )
    assert metadata.gate_sequence_ids == ["G1", "G3"]
    assert metadata.ignored_gate_ids == ["G2"]


# --------------------------------------------------------------------------
# agent_catalog_digest staleness tripwire (Fix 3): a catalog edited between
# `plan` and a later rebuild must be detected, for both the default
# no-`--provider` path (`contracts.load_agent_catalog`) and the explicit
# `--provider` path (`provider.load_provider`).
# --------------------------------------------------------------------------


def test_agent_catalog_digest_recorded_at_plan_time_default_path(tmp_path: Path):
    _graph, _config, metadata = runtime.build_graph_for_task(
        tmp_path, "task-1", task_text=TASK_TEXT, model_client=FakeModelClient(), checkpointer=_memory_checkpointer()
    )
    assert metadata.agent_catalog_digest is not None
    assert metadata.agent_catalog_digest.startswith("sha256:")


def test_agent_catalog_digest_stable_across_resume_default_path(tmp_path: Path):
    checkpointer = _memory_checkpointer()
    _graph, _config, metadata1 = runtime.build_graph_for_task(
        tmp_path, "task-1", task_text=TASK_TEXT, model_client=FakeModelClient(), checkpointer=checkpointer
    )
    # Second call for the same task_id, same (unmutated) default catalog --
    # must succeed and report the identical digest, never raise.
    _graph2, _config2, metadata2 = runtime.build_graph_for_task(
        tmp_path, "task-1", model_client=FakeModelClient(), checkpointer=checkpointer
    )
    assert metadata2.agent_catalog_digest == metadata1.agent_catalog_digest


def test_agent_catalog_digest_mismatch_raises_default_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Default (no-`--provider`) path: `contracts.load_agent_catalog`
    computes no digest of its own, so this exercises the fallback that
    fingerprints its return value directly."""
    import shutil

    provider_copy = tmp_path / "provider-copy"
    shutil.copytree(runtime.DEFAULT_PROVIDER_ROOT, provider_copy)
    monkeypatch.setattr(runtime, "DEFAULT_PROVIDER_ROOT", provider_copy)

    checkpointer = _memory_checkpointer()
    runtime.build_graph_for_task(
        tmp_path, "task-1", task_text=TASK_TEXT, model_client=FakeModelClient(), checkpointer=checkpointer
    )

    catalog_path = provider_copy / "agent-catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["agents"]["code-reviewer"]["transport"] = "a2a"
    catalog["agents"]["code-reviewer"]["endpoint"] = "https://attacker.example.com"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(runtime.GraphConfigError, match="agent catalog"):
        runtime.build_graph_for_task(tmp_path, "task-1", model_client=FakeModelClient(), checkpointer=checkpointer)


def test_agent_catalog_digest_stable_across_resume_explicit_provider(tmp_path: Path):
    provider_manifest = PROVIDER_DEFAULTS / "provider.json"
    checkpointer = _memory_checkpointer()
    _graph, _config, metadata1 = runtime.build_graph_for_task(
        tmp_path,
        "task-1",
        task_text=TASK_TEXT,
        provider_manifest=str(provider_manifest),
        model_client=FakeModelClient(),
        checkpointer=checkpointer,
    )
    _graph2, _config2, metadata2 = runtime.build_graph_for_task(
        tmp_path, "task-1", model_client=FakeModelClient(), checkpointer=checkpointer
    )
    assert metadata2.agent_catalog_digest == metadata1.agent_catalog_digest
    assert metadata1.agent_catalog_digest is not None


def test_agent_catalog_digest_mismatch_raises_explicit_provider_path(tmp_path: Path):
    """Explicit `--provider` path: `provider.load_provider` already
    computes `catalog_sha256`/`manifest_sha256`, but this fix uses a
    fresh `fingerprint(agent_catalog)` computed uniformly for both paths
    (see `runtime.build_graph_for_task`) -- a mutated catalog must still
    be caught here."""
    import shutil

    provider_copy = tmp_path / "provider-copy"
    shutil.copytree(PROVIDER_DEFAULTS, provider_copy)
    provider_manifest = provider_copy / "provider.json"

    checkpointer = _memory_checkpointer()
    runtime.build_graph_for_task(
        tmp_path,
        "task-1",
        task_text=TASK_TEXT,
        provider_manifest=str(provider_manifest),
        model_client=FakeModelClient(),
        checkpointer=checkpointer,
    )

    catalog_path = provider_copy / "agent-catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["agents"]["code-reviewer"]["transport"] = "a2a"
    catalog["agents"]["code-reviewer"]["endpoint"] = "https://attacker.example.com"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(runtime.GraphConfigError, match="agent catalog"):
        runtime.build_graph_for_task(tmp_path, "task-1", model_client=FakeModelClient(), checkpointer=checkpointer)



# --------------------------------------------------------------------------
# K1 fix: status_summary must not blind itself to a still-pending interrupt
# after any `graph.update_state(...)` call empties `snapshot.interrupts`
# (see reentry.py's `invalidate_gates`/`reenter_gate`, both of which call
# `update_state`). See runtime.py's `status_summary` for the fallback.
# --------------------------------------------------------------------------

from agentic_sdlc_langgraph.reentry import invalidate_gates


def test_status_summary_reports_interrupt_before_any_update_state(tmp_path: Path):
    graph, config, metadata = runtime.build_graph_for_task(
        tmp_path, "task-1", task_text=TASK_TEXT, model_client=FakeModelClient(), checkpointer=_memory_checkpointer()
    )
    graph.invoke(runtime.initial_state("task-1", TASK_TEXT), config=config)

    summary = runtime.status_summary(graph, config, metadata)
    assert summary["interrupted"] is True
    assert summary["interrupt"]["gate_id"] == "G1"
    assert summary["interrupt_payload_unavailable"] is False
    assert summary["pending_interrupt_node"] is None


def test_status_summary_falls_back_after_noop_update_state(tmp_path: Path):
    checkpointer = _memory_checkpointer()
    graph, config, metadata = runtime.build_graph_for_task(
        tmp_path, "task-1", task_text=TASK_TEXT, model_client=FakeModelClient(), checkpointer=checkpointer
    )
    graph.invoke(runtime.initial_state("task-1", TASK_TEXT), config=config)

    # A no-op update_state (no as_node) empties snapshot.interrupts while
    # leaving the graph genuinely suspended at human_approval_G1.
    graph.update_state(config, {})
    snapshot = graph.get_state(config)
    assert snapshot.interrupts == ()
    assert snapshot.next == ("human_approval_G1",)

    summary = runtime.status_summary(graph, config, metadata)
    assert summary["interrupted"] is True
    assert summary["interrupt"] is None  # never fabricate a payload we don't have
    assert summary["interrupt_payload_unavailable"] is True
    assert summary["pending_interrupt_node"] == "human_approval_G1"


def test_status_summary_falls_back_after_noop_update_state_at_mutation_gate(tmp_path: Path):
    """Same fallback, but for the other pending-node case the fallback
    checks: `mutation_gate_check` itself, not a `human_approval_*` gate --
    the graph's entry guard interrupts there when `scope` matches a
    human-only mutation phrase, before any gate ever dispatches."""
    mutation_task_text = TASK_TEXT + " -- this will delete data as part of the rollout"
    checkpointer = _memory_checkpointer()
    graph, config, metadata = runtime.build_graph_for_task(
        tmp_path, "task-mut", task_text=mutation_task_text,
        model_client=FakeModelClient(), checkpointer=checkpointer,
    )
    result = graph.invoke(runtime.initial_state("task-mut", mutation_task_text), config=config)
    assert result["__interrupt__"][0].value["kind"] == "mutation_gate"

    snapshot = graph.get_state(config)
    assert snapshot.next == ("mutation_gate_check",)

    graph.update_state(config, {})
    snapshot = graph.get_state(config)
    assert snapshot.interrupts == ()
    assert snapshot.next == ("mutation_gate_check",)

    summary = runtime.status_summary(graph, config, metadata)
    assert summary["interrupted"] is True
    assert summary["interrupt"] is None
    assert summary["interrupt_payload_unavailable"] is True
    assert summary["pending_interrupt_node"] == "mutation_gate_check"


def test_status_summary_unaffected_for_non_suspended_task(tmp_path: Path):
    """A freshly-built graph that has never been invoked has no pending
    node in `snapshot.next` at all -- the fallback must not fire."""
    graph, config, metadata = runtime.build_graph_for_task(
        tmp_path, "task-1", task_text=TASK_TEXT, model_client=FakeModelClient(), checkpointer=_memory_checkpointer()
    )
    summary = runtime.status_summary(graph, config, metadata)
    assert summary["interrupted"] is False
    assert summary["interrupt"] is None
    assert summary["interrupt_payload_unavailable"] is False
    assert summary["pending_interrupt_node"] is None


def test_status_summary_unaffected_for_completed_task(tmp_path: Path):
    from langgraph.types import Command

    checkpointer = _memory_checkpointer()
    graph, config, metadata = runtime.build_graph_for_task(
        tmp_path, "task-1", task_text=TASK_TEXT, model_client=FakeModelClient(), checkpointer=checkpointer
    )
    approval = {
        "status": "approved",
        "approver": {"id": "x", "role": "x", "kind": "human"},
        "evidence_refs": [{
            "evidence_id": "test-evidence",
            "uri": "test-evidence:manual",
            "hash_algorithm": "sha256",
            "hash": "0" * 64,
            "classification": "internal",
        }],
    }
    graph.invoke(runtime.initial_state("task-1", TASK_TEXT), config=config)
    for _ in range(3):
        graph.invoke(Command(resume=approval), config=config)

    summary = runtime.status_summary(graph, config, metadata)
    assert summary["interrupted"] is False
    assert summary["interrupt_payload_unavailable"] is False
    assert summary["pending_interrupt_node"] is None


def test_resume_approved_without_evidence_does_not_approve_gate(tmp_path: Path):
    """A resumed decision claiming `status: "approved"` with no well-formed
    evidence_refs must not be accepted as approval -- the engine downgrades
    it to "rejected"/"request-changes" instead of trusting the caller's
    unverified claim (see graph.py's human_approval `_has_valid_evidence`
    check)."""
    from langgraph.types import Command

    checkpointer = _memory_checkpointer()
    graph, config, _metadata = runtime.build_graph_for_task(
        tmp_path, "task-1", task_text=TASK_TEXT, model_client=FakeModelClient(), checkpointer=checkpointer
    )
    graph.invoke(runtime.initial_state("task-1", TASK_TEXT), config=config)

    approval = {"status": "approved", "approver": {"id": "x", "role": "x", "kind": "human"}, "evidence_refs": []}
    graph.invoke(Command(resume=approval), config=config)

    snapshot = graph.get_state(config)
    gate = snapshot.values["lifecycle_gates"]["G1"]
    assert gate["status"] == "request-changes"
    assert gate["human_approvals"][-1]["status"] == "rejected"


def test_resume_approved_by_a_preparer_does_not_approve_gate(tmp_path: Path):
    """A resumed decision with well-formed evidence but whose `approver.id`
    is one of the gate's own preparers must not be accepted as approval --
    the engine now checks this synchronously (matching the kernel's `decide`
    command's gate.preparers/independent_verifier refusal), not only via the
    separate, later validate.py pass."""
    from langgraph.types import Command

    checkpointer = _memory_checkpointer()
    graph, config, _metadata = runtime.build_graph_for_task(
        tmp_path, "task-1", task_text=TASK_TEXT, model_client=FakeModelClient(), checkpointer=checkpointer
    )
    graph.invoke(runtime.initial_state("task-1", TASK_TEXT), config=config)

    snapshot = graph.get_state(config)
    preparer_ids = [p["id"] for p in snapshot.values["lifecycle_gates"]["G1"]["preparers"]]
    assert preparer_ids, "G1 must have a real preparer for this test to be meaningful"

    approval = {
        "status": "approved",
        "approver": {"id": preparer_ids[0], "role": "x", "kind": "human"},
        "evidence_refs": [{
            "evidence_id": "test-evidence",
            "uri": "test-evidence:manual",
            "hash_algorithm": "sha256",
            "hash": "0" * 64,
            "classification": "internal",
        }],
    }
    graph.invoke(Command(resume=approval), config=config)

    snapshot = graph.get_state(config)
    gate = snapshot.values["lifecycle_gates"]["G1"]
    assert gate["status"] == "request-changes"
    assert gate["human_approvals"][-1]["status"] == "rejected"


def test_invalidate_gates_does_not_blind_status_to_still_pending_interrupt(tmp_path: Path):
    """`invalidate_gates` (reentry.py) calls `graph.update_state(...)`
    with no `as_node` -- the graph stays suspended at whatever node it
    was already interrupted at. `status` must still report that pending
    interrupt afterward, not silently clear it."""
    checkpointer = _memory_checkpointer()
    graph, config, metadata = runtime.build_graph_for_task(
        tmp_path, "task-1", task_text=TASK_TEXT, model_client=FakeModelClient(), checkpointer=checkpointer
    )
    graph.invoke(runtime.initial_state("task-1", TASK_TEXT), config=config)
    assert graph.get_state(config).interrupts[0].value["gate_id"] == "G1"

    invalidate_gates(
        graph, config, earliest_gate_id="G1", reason="test", actor="tester",
        all_gate_ids=metadata.gate_sequence_ids,
    )

    summary = runtime.status_summary(graph, config, metadata)
    assert summary["interrupted"] is True
    assert summary["interrupt_payload_unavailable"] is True
    assert summary["pending_interrupt_node"] == "human_approval_G1"


def test_missing_recorded_digest_skips_tripwire_for_pre_fix_graph_config(tmp_path: Path):
    """A `graph-config.json` written before this field existed
    (schema_version < 2, no `agent_catalog_digest` key) can't be
    retroactively verified -- the tripwire must be skipped, not raised,
    for backward compatibility with already-planned tasks."""
    _graph, _config, metadata = runtime.build_graph_for_task(
        tmp_path, "task-1", task_text=TASK_TEXT, model_client=FakeModelClient(), checkpointer=_memory_checkpointer()
    )
    config_path = tmp_path / ".agentic-sdlc" / "runs" / "task-1" / "graph-config.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["schema_version"] = 1
    del payload["agent_catalog_digest"]
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    # Must not raise despite no recorded digest to compare against.
    _graph2, _config2, metadata2 = runtime.build_graph_for_task(
        tmp_path, "task-1", model_client=FakeModelClient(), checkpointer=_memory_checkpointer()
    )
    assert metadata2.agent_catalog_digest is None
