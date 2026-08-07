"""Declarative graph builder: turns `lifecycle-gates.json` (sliced to
whatever gate list the caller passes in) + a profile's `gate_bindings` /
`routing` + the agent catalog into a compiled LangGraph `StateGraph`.

No gate id is hardcoded anywhere in this module -- everything is driven by
iterating the `gates` argument and following each gate's own
`prerequisites` array for edges. The caller decides which gates to build
(e.g. slicing `lifecycle-gates.json`'s G1-G3 for the phase-0 spike).

Per gate, this wires:

- `dispatch_authors_{gate_id}` -> conditional edge (`Send` fan-out) to one
  `{gate_id}_author_{agent_id}` node per author-kind agent bound to the
  gate's own `required_contributions` (via `gate_dispatch_binding`).
- `dispatch_reviewers_{gate_id}` -> conditional edge (`Send` fan-out) to one
  `{gate_id}_reviewer_{agent_id}` node per reviewer-kind agent, where the
  reviewer set is (reviewer-kind agents in the gate's own contribution
  list) UNION (any matched route's `reviewers` list, for routes whose
  `gates` includes this gate_id) -- route matching is evaluated *at
  runtime* against `state["scope"]` (the task text), since a single
  compiled graph is reused across tasks/threads with different text.
- `gate_decision_{gate_id}` -- pure function; merges collected
  `agent_outputs` for this gate into preparers / independent_verifier /
  artifact_bindings / evidence_refs, enforces separation of duties, and
  computes `authority_requirements` from the gate contract + the
  `authorities` assignment map in state.
- `human_approval_{gate_id}` -- present whenever the gate's resolved
  `authority_requirements` end up non-empty, or `gate.get("human_only")`
  is true. Calls `interrupt(...)`; the resume value is treated as an
  approval decision and is re-validated against the separation-of-duties
  finding before being allowed to set `status="approved"`.

Deliberate simplification: per-gate agent nodes are instantiated once per
(gate_id, agent_id, role) triple, even when the same underlying agent_id
backs multiple gates (e.g. `code-reviewer` reviews G1, G2, and G3 here).
This keeps the fan-in join trivial (distinct node names -> distinct normal
edges into one join node) at the cost of duplicate node registrations for
a shared agent identity. A future phase could dedupe by agent_id and
thread `gate_id` purely through the `Send` payload if the join semantics
are reworked; not worth the complexity for a 3-gate spike.

Deviation from the plan-doc's literal `build_graph(gates, routes,
agent_catalog, model_client, checkpointer)` signature: gate dispatch
(author/tasks/artifacts) is resolved from a profile's `gate_bindings`,
which is a separate structure from the `routing` array (`routes`). Both
are required to resolve dispatch, so `gate_bindings` is threaded through
as an explicit parameter here rather than folded into `routes`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt

from .agents import ModelClient, make_agent_node
from .contracts import choose_route, gate_dispatch_binding, mutation_gate_guard
from .state import SDLCState, merge_gate_updates


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _role_label(authority_id: str) -> str:
    # Best-effort human-readable label; the schema only requires non-empty
    # strings, it doesn't prescribe exact wording. Port of ROLE_LABELS
    # would require importing the legacy script's dict; instead we derive
    # a readable label mechanically since exact wording isn't load-bearing
    # for schema validity.
    return authority_id.replace("_", " ").title()


def _authority_requirements_for(
    gate: dict[str, Any], authorities: dict[str, Any]
) -> list[dict[str, Any]]:
    requirements = []
    for authority_id in gate.get("authority_requirements", []):
        assigned = authorities.get(authority_id, {}).get("status") == "assigned"
        requirements.append(
            {
                "authority_id": authority_id,
                "authority_type": "human-approver",
                "role": _role_label(authority_id),
                "applicability": "applicable" if assigned else "unknown",
                "rationale": (
                    "Assigned in project authority map"
                    if assigned
                    else "Authority is not assigned"
                ),
            }
        )
    return requirements


def _empty_gate_state(gate: dict[str, Any]) -> dict[str, Any]:
    return {
        "tier": "lifecycle",
        "gate_id": gate["id"],
        "name": gate["name"],
        "applicability": "applicable",
        "applicability_rationale": "Lifecycle gate applies by default",
        "status": "pending",
        "artifact_bindings": [],
        "preparers": [],
        "independent_verifier": None,
        "independence_declaration": {
            "verifier_confirmed_not_preparer": False,
            "verifier_made_material_correction": False,
        },
        "authority_requirements": [],
        "human_approvals": [],
        "decided_at": None,
        "evidence_refs": [],
        "knowledge_status": "unavailable",
        "findings": [],
        "exceptions": [],
        "invalidation_history": [],
        "required_reentry_gate": None,
    }


def build_graph(
    gates: list[dict[str, Any]],
    gate_bindings: dict[str, Any],
    routes: list[dict[str, Any]],
    agent_catalog: dict[str, Any],
    model_client: ModelClient,
    checkpointer,
    mutation_gates: list[dict[str, Any]] | None = None,
    profile: dict[str, Any] | None = None,
    provider_root: str | None = None,
):
    """Build and compile the StateGraph for the given (already sliced)
    gate list. See module docstring for the wiring rules.

    `profile` (the full active profile dict, e.g. from
    `provider.merge_profile`) and `provider_root` are optional and are
    threaded straight through to `make_agent_node`/`resolve_role_prompt`
    so a provider that opts into rich role-definition content
    (`profile["rich_content_source"]`) gets it; both default to `None`
    (treated as "no rich content"), which reproduces this function's
    prior generic-instruction-only behavior exactly, so existing callers
    that only pass `gate_bindings`/`routes` (not the full profile) are
    unaffected.
    """

    mutation_gates = mutation_gates or []
    profile = profile or {}
    gate_ids = [g["id"] for g in gates]
    gates_by_id = {g["id"]: g for g in gates}

    builder = StateGraph(SDLCState)

    # --- entry: mutation-gate guard -------------------------------------
    # A hard stop, independent of and prior to any per-gate human-approval
    # interrupt: if `scope` matches a human-only mutation phrase, the graph
    # interrupts *here*, before any gate's `dispatch_authors_*` node runs,
    # and requires an explicit human authorization decision to proceed.
    # Resuming with `{"authorized": False}` (or anything that isn't an
    # explicit `True`) halts the run -- `run_halted` is set and the
    # conditional edge below routes straight to END without dispatching
    # any gate. No gate ever gets a `lifecycle_gates` entry in that case,
    # so every included gate is structurally "pending" (see export.py,
    # which synthesizes the pending placeholder for any in-sequence gate
    # id absent from `lifecycle_gates`).
    def mutation_gate_check(state: SDLCState) -> dict[str, Any]:
        pending = mutation_gate_guard(state.get("scope", ""), mutation_gates)
        if not pending:
            return {
                "mutation_gate_pending": None,
                "mutation_gate_decision": None,
                "run_halted": False,
            }
        decision = interrupt(
            {
                "kind": "mutation_gate",
                "matched": pending["matched"],
                "reason": (
                    "Human authorization required before any gate dispatch "
                    "may proceed"
                ),
            }
        )
        authorized = bool(isinstance(decision, dict) and decision.get("authorized") is True)
        decision_record = {
            "authorized": authorized,
            "approver": decision.get("approver") if isinstance(decision, dict) else None,
            "reason": decision.get("reason") if isinstance(decision, dict) else None,
            "decided_at": _now(),
        }
        return {
            "mutation_gate_pending": pending,
            "mutation_gate_decision": decision_record,
            "run_halted": not authorized,
        }

    builder.add_node("mutation_gate_check", mutation_gate_check)
    builder.add_edge(START, "mutation_gate_check")

    # --- per-gate wiring -----------------------------------------------
    for gate in gates:
        gate_id = gate["id"]
        binding = gate_dispatch_binding(gate, gate_bindings)
        author_ids = [
            agent_id
            for agent_id in binding["agents"]
            if agent_catalog.get(agent_id, {}).get("kind") == "author"
        ]
        static_reviewer_ids = [
            agent_id
            for agent_id in binding["agents"]
            if agent_catalog.get(agent_id, {}).get("kind") == "reviewer"
        ]

        # dispatch_authors_{gate_id}: passthrough node + conditional Send fan-out
        builder.add_node(f"dispatch_authors_{gate_id}", lambda state: {})

        def make_author_router(gate_id=gate_id, author_ids=author_ids):
            def router(state: SDLCState):
                if not author_ids:
                    return f"dispatch_reviewers_{gate_id}"
                task_text = state.get("scope", "")
                classification = state.get("classification", "internal")
                return [
                    Send(
                        f"{gate_id}_author_{agent_id}",
                        {"gate_id": gate_id, "task_text": task_text, "classification": classification},
                    )
                    for agent_id in author_ids
                ]

            return router

        author_targets = [f"{gate_id}_author_{a}" for a in author_ids] + [f"dispatch_reviewers_{gate_id}"]
        builder.add_conditional_edges(
            f"dispatch_authors_{gate_id}", make_author_router(), author_targets
        )

        for agent_id in author_ids:
            node_name = f"{gate_id}_author_{agent_id}"
            builder.add_node(
                node_name,
                make_agent_node(
                    agent_id,
                    "author",
                    model_client,
                    metadata=agent_catalog.get(agent_id, {}),
                    profile=profile,
                    provider_root=provider_root,
                ),
            )
            builder.add_edge(node_name, f"dispatch_reviewers_{gate_id}")

        # dispatch_reviewers_{gate_id}: passthrough node + conditional Send fan-out
        builder.add_node(f"dispatch_reviewers_{gate_id}", lambda state: {})

        def make_reviewer_router(gate_id=gate_id, static_reviewer_ids=static_reviewer_ids):
            def router(state: SDLCState):
                matched = choose_route(state.get("scope", ""), routes)
                dynamic = [
                    reviewer_id
                    for route in matched
                    if gate_id in route.get("gates", [])
                    for reviewer_id in route.get("reviewers", [])
                ]
                reviewer_ids = list(dict.fromkeys(static_reviewer_ids + dynamic))
                if not reviewer_ids:
                    return f"gate_decision_{gate_id}"
                task_text = state.get("scope", "")
                classification = state.get("classification", "internal")
                return [
                    Send(
                        f"{gate_id}_reviewer_{agent_id}",
                        {"gate_id": gate_id, "task_text": task_text, "classification": classification},
                    )
                    for agent_id in reviewer_ids
                ]

            return router

        # Possible reviewer targets: static ones known now, plus any agent
        # referenced anywhere in `routes` as a reviewer (route-matching is
        # runtime-dependent, so we must pre-register all *possible*
        # targets up front for LangGraph's conditional-edge path map).
        possible_reviewer_ids = set(static_reviewer_ids)
        for route in routes:
            if gate_id in route.get("gates", []):
                possible_reviewer_ids.update(route.get("reviewers", []))
        reviewer_targets = [f"{gate_id}_reviewer_{a}" for a in possible_reviewer_ids] + [
            f"gate_decision_{gate_id}"
        ]
        builder.add_conditional_edges(
            f"dispatch_reviewers_{gate_id}", make_reviewer_router(), reviewer_targets
        )

        for agent_id in possible_reviewer_ids:
            node_name = f"{gate_id}_reviewer_{agent_id}"
            builder.add_node(
                node_name,
                make_agent_node(
                    agent_id,
                    "reviewer",
                    model_client,
                    metadata=agent_catalog.get(agent_id, {}),
                    profile=profile,
                    provider_root=provider_root,
                ),
            )
            builder.add_edge(node_name, f"gate_decision_{gate_id}")

        # gate_decision_{gate_id}: pure merge + separation-of-duties enforcement
        def gate_decision(state: SDLCState, gate=gate, gate_id=gate_id) -> dict[str, Any]:
            outputs = [o for o in state.get("agent_outputs", {}).values() if o.get("gate_id") == gate_id]
            preparers = [o["identity"] for o in outputs if o.get("kind") == "author"]
            reviewer_outputs = [o for o in outputs if o.get("kind") == "reviewer"]
            # Spike simplification: at most one independent verifier is
            # modeled (the first reviewer output), matching the schema's
            # single `independent_verifier` field. Multiple reviewers
            # (e.g. G4/G5 in the full contract) would need a richer model;
            # out of scope for G1-G3.
            independent_verifier = reviewer_outputs[0]["identity"] if reviewer_outputs else None

            artifact_bindings = [o["artifact_binding"] for o in outputs if o.get("artifact_binding")]
            evidence_refs = [o["evidence_ref"] for o in outputs if o.get("evidence_ref")]

            preparer_ids = {p["id"] for p in preparers}
            violation = independent_verifier is not None and independent_verifier["id"] in preparer_ids

            authority_requirements = _authority_requirements_for(gate, state.get("authorities", {}))

            existing = state.get("lifecycle_gates", {}).get(gate_id, _empty_gate_state(gate))
            new_gate = dict(existing)
            new_gate["preparers"] = preparers
            new_gate["independent_verifier"] = independent_verifier
            new_gate["independence_declaration"] = {
                "verifier_confirmed_not_preparer": not violation,
                "verifier_made_material_correction": False,
            }
            new_gate["artifact_bindings"] = artifact_bindings
            new_gate["evidence_refs"] = evidence_refs
            new_gate["authority_requirements"] = authority_requirements
            new_gate["status"] = "blocked" if violation else "ready"
            if violation:
                new_gate["applicability_rationale"] = (
                    "Blocked: independent verifier matches a preparer id "
                    "(author_cannot_review_or_approve_same_revision)"
                )
            return {"lifecycle_gates": {gate_id: new_gate}}

        builder.add_node(f"gate_decision_{gate_id}", gate_decision)

        # human_approval_{gate_id}: present iff resolved authority
        # requirements are non-empty (this contract makes every one of
        # G1-G3's authority_requirements entries a human-approver
        # requirement, so all three gates get one -- not "just G2").
        has_authority_requirements = bool(gate.get("authority_requirements")) or bool(
            gate.get("human_only")
        )

        if has_authority_requirements:

            def _has_valid_evidence(evidence_refs: Any) -> bool:
                if not isinstance(evidence_refs, list) or not evidence_refs:
                    return False
                required_fields = ("evidence_id", "uri", "hash_algorithm", "hash", "classification")
                return all(
                    isinstance(item, dict)
                    and all(isinstance(item.get(field), str) and item[field] for field in required_fields)
                    for item in evidence_refs
                )

            def human_approval(state: SDLCState, gate_id=gate_id) -> dict[str, Any]:
                current = state["lifecycle_gates"][gate_id]
                violation = current["status"] == "blocked"
                decision = interrupt(
                    {
                        "gate_id": gate_id,
                        "authority_requirements": current["authority_requirements"],
                        "reason": (
                            "Separation-of-duties violation: cannot approve"
                            if violation
                            else f"Human approval required for gate {gate_id}"
                        ),
                    }
                )
                new_gate = dict(current)
                # `approval.status` is constrained by the schema's `approval`
                # $def to pending|approved|rejected|not-required -- it is a
                # *different*, narrower enum than `gate.status`
                # (pending|ready|approved|request-changes|needs-information|
                # blocked|invalidated). A separation-of-duties violation
                # forces the human_approvals entry to "rejected" (never
                # "approved"), while the richer "blocked" outcome is recorded
                # on the gate itself, not on the approval record.
                decision_is_dict = isinstance(decision, dict)
                evidence_refs = decision.get("evidence_refs", []) if decision_is_dict else []
                approver = decision.get("approver") if decision_is_dict else None
                approver_id = approver.get("id") if isinstance(approver, dict) else None
                preparer_ids = {p.get("id") for p in current.get("preparers", []) if isinstance(p, dict)}
                verifier = current.get("independent_verifier")
                verifier_id = verifier.get("id") if isinstance(verifier, dict) else None
                if violation:
                    approval_status = "rejected"
                    gate_status = "blocked"
                else:
                    raw_status = decision.get("status", "pending") if decision_is_dict else "pending"
                    if raw_status == "approved" and not _has_valid_evidence(evidence_refs):
                        # Fail-closed: an "approved" claim with no well-formed
                        # external evidence is not accepted as approval (see
                        # CLAUDE.md's evidence invariant, enforced synchronously
                        # here the same way the kernel's `decide` command
                        # enforces it at write time).
                        raw_status = "rejected"
                    if raw_status == "approved" and approver_id and (approver_id in preparer_ids or approver_id == verifier_id):
                        # Fail-closed: the resumed approver is one of this
                        # gate's own preparers or its independent verifier --
                        # the same self-approval refusal the kernel's `decide`
                        # command enforces synchronously against
                        # gate.preparers/independent_verifier, not left to a
                        # later, separate validate.py pass.
                        raw_status = "rejected"
                    if raw_status in ("approved", "rejected", "pending", "not-required"):
                        approval_status = raw_status
                    else:
                        approval_status = "rejected"
                    gate_status = "approved" if approval_status == "approved" else (
                        "pending" if approval_status == "pending" else "request-changes"
                    )
                approval = {
                    "status": approval_status,
                    "approver": decision.get("approver") if decision_is_dict else None,
                    "decided_at": _now(),
                    "evidence_refs": evidence_refs,
                }
                new_gate["human_approvals"] = current.get("human_approvals", []) + [approval]
                new_gate["decided_at"] = approval["decided_at"]
                new_gate["status"] = gate_status
                return {"lifecycle_gates": {gate_id: new_gate}}

            builder.add_node(f"human_approval_{gate_id}", human_approval)
            builder.add_edge(f"gate_decision_{gate_id}", f"human_approval_{gate_id}")

    # --- prerequisite-driven edges between gates ------------------------
    def exit_node(gate_id: str) -> str:
        gate = gates_by_id[gate_id]
        has_authority_requirements = bool(gate.get("authority_requirements")) or bool(
            gate.get("human_only")
        )
        return f"human_approval_{gate_id}" if has_authority_requirements else f"gate_decision_{gate_id}"

    def entry_node(gate_id: str) -> str:
        return f"dispatch_authors_{gate_id}"

    has_dependent: set[str] = set()
    root_gate_ids: list[str] = []
    for gate in gates:
        gate_id = gate["id"]
        prerequisites = [p for p in gate.get("prerequisites", []) if p in gate_ids]
        if not prerequisites:
            root_gate_ids.append(gate_id)
        for prereq in prerequisites:
            builder.add_edge(exit_node(prereq), entry_node(gate_id))
            has_dependent.add(prereq)

    for gate_id in gate_ids:
        if gate_id not in has_dependent:
            builder.add_edge(exit_node(gate_id), END)

    # Conditional edge out of the mutation-gate guard: a halted run
    # (unauthorized/rejected mutation-gate match) goes straight to END
    # without dispatching any gate; otherwise fan out to every root gate
    # (a gate with no in-sequence prerequisites) exactly as a plain edge
    # would have, for every gate list this module has ever been built
    # with (root_gate_ids has exactly one entry -- G1 -- for the full
    # G1-G10 chain, but nothing here assumes that).
    def mutation_gate_router(state: SDLCState):
        if state.get("run_halted"):
            return END
        if not root_gate_ids:
            return END
        return [entry_node(gid) for gid in root_gate_ids]

    builder.add_conditional_edges(
        "mutation_gate_check",
        mutation_gate_router,
        [entry_node(gid) for gid in root_gate_ids] + [END],
    )

    return builder.compile(checkpointer=checkpointer)
