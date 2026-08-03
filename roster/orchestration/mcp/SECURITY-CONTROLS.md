# Security controls: agents MCP dispatch server

This document enumerates every control in `dispatch_core.py` /
`dispatch_server.py` that maps to a threat-model expectation or an
`agent-autonomy.yaml` guarantee, and states plainly whether the control is:

- **Mechanically enforced** -- the code makes the bad outcome structurally
  impossible for a caller of this tool to produce through this tool's own
  interface, and a specific automated test in
  `roster/orchestration/test/test_mcp_dispatch.py` exercises that claim.
- **Advisory** -- the code implements the control and it holds against an
  ordinary, non-adversarial, or single-turn caller, but a sufficiently
  adversarial or fully autonomous caller (in particular: a compromised child
  process with its own code-execution authority, or a host CLI/calling
  session willing to script around a human-confirmation step) could route
  around it. Advisory controls are still worth having -- they raise the bar
  and produce an audit trail -- but must never be described or relied upon as
  hard guarantees.

This is written to be accurate as of the code on disk after the H-1 (project-
tier git-clean) and L-1 (`confirmation_required` response shape) fixes. If
the code changes, this document must be re-checked against it, not
regenerated from memory or intent.

## Sandbox narrowing for `planning-review-only` mode

**Mechanically enforced.** `compute_effective_sandbox()` has exactly two
inputs: the caller-supplied `mode` (constrained to the two-value `MODES` set)
and the resolved role file's own `sandbox_mode` (never caller-supplied --
`dispatch_server.py`'s tool schema has no `developer_instructions` or
`sandbox_mode` parameter). When `mode == "planning-review-only"`, the
function unconditionally returns `read-only` regardless of what the file
declares; there is no third parameter through which a caller could request a
wider sandbox. This is asserted directly by
`SandboxNarrowingTests.test_planning_review_only_forces_read_only_regardless_of_file`
and `SandboxNarrowingTests.test_there_is_no_caller_parameter_that_can_widen_sandbox`
(which asserts the function's actual parameter list via `inspect.signature`,
not just its documented behavior), and at the top-level dispatch entry point
by
`TerminalVsFallbackDispatchTests.test_planning_review_only_mode_forces_read_only_even_for_a_write_capable_file`,
which inspects the literal `argv` handed to the child process (not just a
status field) for a role file that declares `sandbox_mode = "danger-full-access"`.

## H-1 remediation: project-tier git-clean check

**Enforced against accidental/single-turn escalation. NOT enforced against a
determined actor.** Before Fix H-1, a caller with ordinary repository write
access could write `.codex/agents/<role_id>.toml` declaring
`sandbox_mode = "danger-full-access"` and arbitrary `developer_instructions`
for an existing catalog `role_id`, then immediately call
`dispatch_secure_cloud_role` with `mode="scoped-repository-edit"` against
it, defeating the "no caller-supplied instructions" and "danger-full-access
never reachable via caller input" guarantees for that one path, all within a
single session turn.

The fix (`_is_project_tier_git_clean()`, called from `resolve_role_file()`
only when `tier == "project"` and `mode == "scoped-repository-edit"`)
requires the project-tier file to be tracked in git with no staged or
unstaged modification relative to `HEAD` (`git status --porcelain -- <path>`
must produce empty output and exit 0) before any of its fields are trusted.
Failure -- dirty, untracked, or git itself unavailable/erroring -- raises
`ProjectTierNotGitCleanError`, a distinct `DispatchDenied` subtype, with a
non-generic message, and the check's boolean outcome is carried through
`ResolvedRole.project_tier_git_clean` into every audit record for that
dispatch (`denied`, `confirmation-required`, and the terminal decision),
so this control's actual behavior is auditable rather than assumed.

Tests: `ProjectTierGitCleanTests` (clean-committed succeeds; dirty rejected;
untracked rejected; planning-review-only is unaffected by this specific
check in both the dirty and untracked case; global-tier and plugin-tier
resolution are unaffected by the project directory's git state; the default
`mode` parameter value preserves pre-H-1 behavior for callers that don't
pass `mode`) and, at the top-level dispatch entry point,
`TerminalVsFallbackDispatchTests.test_untracked_project_tier_file_denies_dispatch_with_a_distinct_reason`,
`test_clean_committed_project_tier_file_dispatches_successfully`,
`test_dirty_project_tier_file_in_planning_review_only_is_not_denied_by_the_git_check`,
`test_audit_record_captures_the_git_clean_check_outcome_on_denial`, and
`test_audit_record_captures_the_git_clean_check_outcome_on_success`.

**Honest limit of this guarantee:** this control prevents a same-session,
single-turn write-then-dispatch escalation by requiring a separate, distinct
git-commit action to happen first -- something outside this tool's own
request/response cycle. It does **not** prevent a determined actor from
locally committing malicious `developer_instructions`/`sandbox_mode` content
without any code review and then dispatching against that commit: a clean
`git status` only proves the file matches some prior commit in the local
repository, not that the commit's content was reviewed, authorized, or safe.
This is risk-reduction against accidental or blindly-automated escalation,
not risk-elimination against an adversary who fully controls the local git
history (e.g. a compromised or malicious session with ordinary `git commit`
access and no external review gate). Global (`~/.codex/agents/`) and plugin
(`provider/codex-agents/`) tiers are intentionally out of
scope for this check: the global tier is only populated through the
provenance-marker-gated `sync_codex_agents.py` sync, and the plugin tier
ships with the package -- neither is writable by an ordinary caller through
the same direct "just edit a file in the repo" path the project tier is.

## Dispatch-depth limit (`MAX_DISPATCH_DEPTH = 1`)

**Advisory against an adversarial child.** `current_dispatch_depth()` reads
an integer counter from `SECURE_CLOUD_AGENTS_DISPATCH_DEPTH` in this
process's own environment; `build_child_env()` writes `depth + 1` into the
allowlisted child environment so a child that also happens to run this same
MCP server enforces the cap against itself. This holds for a well-behaved
child that simply inherits and reads the environment variable as intended.
It does **not** hold against a child process with its own code-execution
authority (which is exactly what a write-capable, `workspace-write` or
`danger-full-access` dispatched child has): such a child can unset, forge,
or ignore `SECURE_CLOUD_AGENTS_DISPATCH_DEPTH` entirely, since nothing
outside the child's own process enforces that it actually reads or respects
that variable when it in turn tries to call this same dispatch tool again.
`current_dispatch_depth()`'s fail-closed behavior on an unparseable value
(`DispatchDepthTests.test_unparseable_value_fails_closed_to_the_limit`)
protects against accidental corruption of the counter, not against a
deliberate adversary erasing it. Treat this exactly as the depth-guard
docstring and the prior security review already state: an accident/misuse
guard, not a hard depth bound against a compromised or hostile child.

## Human-confirmation gate for write-capable dispatch (`ConfirmationGate`)

**Advisory against a fully autonomous calling session.** The gate is a
mechanical two-call, single-use, TTL-bound token scheme (see
`ConfirmationGate`'s own docstring, which this section deliberately mirrors
and expands): a first call for a write-capable dispatch never spawns a
child and instead returns `status="confirmation_required"` plus an opaque
token bound to the exact `(role_id, brief, mode, classification,
effective_sandbox)` tuple; only a second call carrying that token, with an
identical parameter tuple, actually spawns the child, and the token is
single-use and expires after `CONFIRMATION_TTL_SECONDS`. This part --
that the first call never spawns a child, that a mismatched or reused token
is rejected -- is mechanically enforced and tested
(`ConfirmationGateTests`, plus
`TerminalVsFallbackDispatchTests.test_write_capable_dispatch_without_confirmation_never_spawns_a_child`
and `test_write_capable_dispatch_requires_confirmation_round_trip`).

What is **not** enforced, and cannot be from inside this tool: whether a
human actually read and approved the intermediate `confirmation_required`
response before the second call happened. A fully autonomous host CLI or
calling session is free to issue both calls back-to-back, itself, with no
human ever seeing the intermediate result -- this tool has no visibility
into, and no control over, the host CLI's own approval-prompt or
user-confirmation behavior around tool invocations. True human-presence
enforcement is entirely a property of the host environment this server runs
inside, not of this module. Treat this gate as a necessary layer that raises
the bar against a single accidental or blindly-scripted write-capable
dispatch, never as a sufficient proof that a human was in the loop.

## Env allowlist for the child process

**Mechanically enforced.** `build_child_env()` only ever copies names
present in the fixed `ENV_ALLOWLIST` tuple out of this server process's own
environment; it never does a blanket `os.environ` inheritance, so an
arbitrary variable in this process's environment (API keys, tokens, other
credentials) cannot reach the dispatched child by default. Tested by
`EnvAllowlistTests.test_only_allowlisted_names_are_copied` and
`test_credential_shaped_variables_never_leak_through`, which poisons the
environment with credential-shaped variable names
(`AWS_SECRET_ACCESS_KEY`, `API_TOKEN`, `GITLAB_TOKEN`, `OPENAI_API_KEY`) and
asserts none of them appear in the resulting child environment.

## Audit-record secret redaction

**Mechanically enforced.** `build_audit_record()` asserts (raises
`AssertionError`, not a silent drop) if any of the fixed `_FORBIDDEN_AUDIT_KEYS`
(`developer_instructions`, `brief`, `prompt`, `output`, `stdout`, `stderr`,
`stdout_text`, `environment`, `env`, `child_env`, `credentials`, `auth`,
`token`, `confirmation_token`) are present in the fields it's asked to
record, so a future code change that accidentally tries to log one of these
fails loudly at record-construction time rather than silently leaking into
the on-disk JSON-lines audit log. Tested directly by
`AuditRecordTests.test_forbidden_keys_raise` (parameterized over every
forbidden key) and, at the top-level dispatch entry point, by
`TerminalVsFallbackDispatchTests.test_audit_records_never_contain_the_brief_or_instructions_or_output`,
which dispatches with a marked secret brief and marked child output and
asserts neither marker appears anywhere in the raw audit file contents.

## Concurrency / timeout / output caps

**Mechanically enforced.**

- Concurrency: `ConcurrencyLimiter` is a bounded semaphore (`try_acquire()`
  returns `False`, never blocks or queues unboundedly, once
  `MAX_CONCURRENT_CHILDREN` children are active); a full limiter causes the
  top-level dispatch to return a structured `denied` backpressure error
  before any child is spawned. Tested by
  `ConcurrencyLimiterTests.test_caps_concurrent_acquisitions` and
  `TerminalVsFallbackDispatchTests.test_concurrency_cap_returns_structured_backpressure_error`.
- Timeout: `spawn_and_wait()` spawns the child in its own process group
  (`start_new_session=True`) specifically so a timeout can group-kill
  (`os.killpg(..., SIGKILL)`) the whole process group, not just the direct
  child, on expiry. Tested by
  `SpawnAndWaitTests.test_group_kill_on_timeout`, which spawns a child that
  sleeps far longer than the configured timeout and asserts it is
  terminated promptly.
- Output cap: the child's stdout is read and capped at `max_output_bytes`
  in a background reader thread, with truncation explicitly recorded
  (`stdout_truncated`) rather than silently dropped, and the audit record
  never contains the captured output itself (see the redaction section
  above). Tested by
  `SpawnAndWaitTests.test_output_is_capped_and_truncation_recorded`.

## Role-file resolution safety (symlink/non-regular refusal, path containment)

**Mechanically enforced.**

- Symlink refusal: `_read_role_file_capped()` opens with `O_NOFOLLOW` and
  then verifies `S_ISREG` on the resulting file descriptor's `fstat`,
  refusing any resolved role-file path that is (or resolves through) a
  symlink at every tier. Tested by
  `SymlinkAndNonRegularRefusalTests.test_project_tier_symlink_refused`,
  `test_global_tier_symlink_refused`, `test_plugin_tier_symlink_refused`,
  and `test_symlink_at_higher_tier_does_not_fall_through_to_lower_valid_tier`
  (a symlinked higher-tier file must be a terminal denial, never a silent
  fallthrough to a valid lower tier).
- Non-regular-file refusal: the same `S_ISREG` check also refuses
  directories or other non-regular file types at the expected path. Tested
  by `test_project_tier_directory_refused`, `test_global_tier_directory_refused`,
  and `test_plugin_tier_directory_refused`.
- Path containment: `_ensure_contained()` verifies the resolved candidate
  path sits under the realpath of its declared tier root, defending against
  the tier root itself being replaced by a symlink pointed elsewhere (the
  `role_id` value itself cannot produce a traversal path, since it is
  already constrained to `^[a-z0-9-]+$` before any path is built from it).
  Exercised indirectly by the symlink-refusal tests above (which construct
  exactly this shape) and by `RoleIdValidationTests.test_rejects_path_traversal_shapes`
  for the `role_id` input side of the same defense-in-depth boundary.

## Team dispatch (`dispatch_team`)

Generalizes the single-role mechanism above to more than one member per call,
waiting for every member to reach a terminal state before returning
(implements `INTENT-CADRE-TEAM-DISPATCH-001`). Every control above still
applies per member exactly as documented; this section covers only the
team-specific additions and how each answers the intent record's OD-5
questions. `dispatch_secure_cloud_role()` itself, `ConfirmationGate`, and
`ConcurrencyLimiter.try_acquire()` are untouched by any of this -- team
support is additive, verified by
`DispatchTeamTests.test_single_role_dispatch_is_unaffected_by_team_support`
and the full pre-existing single-role suite passing unmodified.

- **Classification/sandbox narrowing: mechanically enforced, per member
  independently.** Each member is resolved and narrowed against the same
  caller-declared `parent_classification` exactly as a single dispatch would
  be -- there is no team-wide ceiling distinct from each member's own check,
  and no member can use another member's classification or sandbox as
  cover. Tested by `DispatchTeamTests.test_missing_parent_classification_is_denied`
  and the shared `validate_classification()`/`compute_effective_sandbox()`
  code path (same functions the single-role tests already cover).
- **Team size cap: mechanically enforced.** `MAX_TEAM_SIZE = 8`; a team
  larger than this is denied entirely before any member is resolved. This is
  a conservative v1 constant, not derived from a load test -- revisit if a
  real team recipe needs more. Tested by
  `DispatchTeamTests.test_team_over_max_size_is_denied`.
- **Dispatch-depth guard: same advisory limit as single-role, checked once
  per team.** `current_dispatch_depth() >= MAX_DISPATCH_DEPTH` denies the
  *entire* team before any member is resolved, exactly like a single
  dispatch; each spawned child still receives `depth + 1` in its own
  environment. This does **not** add a separate total-fan-out cap beyond
  `MAX_TEAM_SIZE` -- a team dispatch at depth 0 can cause up to 8 children to
  run, same honest limitation as the single-role depth guard above (advisory
  against a well-behaved child, not enforceable against one with its own
  code-execution authority).
- **Confirmation gating: mechanically enforced, one team-wide token covering
  every member.** `TeamConfirmationGate` mirrors `ConfirmationGate`'s
  single-use, TTL-bound, exact-match mechanism, but its bound subject is the
  ordered tuple of *every* member's `(role_id, brief_hash, mode,
  classification, effective_sandbox)` -- not only the write-capable ones --
  so altering any member (including a read-only one) after the first call
  invalidates the token. The `confirmation_required` response explicitly
  lists which members are write-capable (`write_capable_members`), so a
  human reviewing it sees exactly what they're approving rather than an
  opaque "this team needs confirmation." Tested by
  `TeamConfirmationGateTests` and
  `DispatchTeamTests.test_write_capable_member_requires_one_team_wide_confirmation`
  / `test_tampering_with_a_member_after_confirmation_request_invalidates_it`.
  Same honest limit as the single-role gate: this proves the two calls
  matched, not that a human actually read the intermediate response.
- **Concurrency: mechanically enforced, shared with single-role dispatch,
  blocking instead of immediate-deny.** Team members acquire the *same*
  `ConcurrencyLimiter` instance/pool single-role dispatch uses -- there is no
  separate team-scoped cap -- but via a new `acquire(timeout=...)` method
  that blocks until a slot frees (or the dispatch timeout elapses), rather
  than `try_acquire()`'s immediate denial. This is deliberate: a team can
  exceed `MAX_CONCURRENT_CHILDREN` by design (`routing.yaml`'s
  `competing-hypotheses-debugging` recipe allows up to 4 instances against a
  default cap of 3), and immediate denial would make dispatching any such
  team larger than the global cap unusable. `try_acquire()` itself is
  unchanged. Tested by `ConcurrencyLimiterBlockingAcquireTests` (waits for a
  released slot; times out when none frees) and
  `DispatchTeamTests.test_team_larger_than_the_concurrency_cap_still_completes_by_waiting`.
- **Audit logging: mechanically enforced, one record per member plus one
  team-summary record, correlated by `team_id`.** Every member's audit
  record (`decision="dispatched"`/`"denied"`/`"unavailable"`) carries
  `team_id`, `team_size`, and `team_member_index` alongside the same fields a
  single dispatch's record would have; one additional record with
  `decision="team-completed"` (or `"team-denied"`/`"team-unavailable"` for a
  whole-team-level failure before any member is resolved) is written once
  every member reaches a terminal state, with a `status_counts` summary.
  `_FORBIDDEN_AUDIT_KEYS`'s redaction assertion applies identically -- team
  support introduces no new audit fields that could carry secret-shaped
  content. Tested by
  `DispatchTeamTests.test_audit_records_carry_a_shared_team_id_across_members`.
- **A concurrency bug found and fixed while building this feature:**
  `_ensure_audit_log_path()`'s `os.path.lexists()` check followed by an
  `O_CREAT | O_EXCL` open was not itself race-safe -- two threads (team
  members write audit records concurrently) could both observe the file
  absent and both attempt the exclusive create, and the loser raised
  `FileExistsError` uncaught, silently killing that member's thread before
  it recorded a result (surfaced as an intermittent `None` entry in
  `dispatch_team`'s results list during this feature's own test
  development). Fixed by catching `FileExistsError` from the losing thread's
  create attempt and treating it as success (the file exists with the
  correct mode either way); still `O_EXCL`, not `O_CREAT` alone, so a
  pre-placed symlink at this path is refused exactly as before. This bug
  predates team dispatch (the same race was always theoretically reachable
  from concurrent single-role dispatches sharing one audit path) but was
  never exercised by a test until team dispatch's genuine multi-threaded
  writes made it happen routinely; the single-role test suite gained no new
  regression coverage for it specifically because the fix is in the shared
  `_ensure_audit_log_path()` path both call.

## Not covered above

M-2 (hash-pinning the `mcp` dependency in `requirements-mcp.txt`) and M-3
(verifying the `codex exec` invocation shape in `build_child_argv()` against
a real `codex` binary) remain open, tracked via dated `TODO` comments at
their respective locations in the source. Neither could be meaningfully
resolved in this sandbox (no network/package access to fetch a verified
package hash or invoke a real Codex CLI binary), and both were categorized
by the security reviewer as shippable with a tracked follow-up rather than
must-fix-before-merge.
