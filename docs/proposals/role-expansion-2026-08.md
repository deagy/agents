# Proposal: seven candidate roles, three added

Status: **IMPLEMENTED — scoped down from seven candidates to three roles, one
skill, and two routing repairs.**
Task ID: `role-expansion-2026-08-07`
Classification: internal
Author role: governance-planner (Cadre suite)
Requested by: repository owner / declared Product Owner
(`roster/shared/team-profile.yaml`)
Required approver: Product Owner

Seven roles were proposed: **AI Engineer, Project Manager, Git Expert (possibly
split into GitHub and GitLab Experts), UX Expert, UI Expert**, and — asked as an
open question — **Go Engineer and Python Engineer**, "or are those roles too
narrow?"

The governing rule is `.agents/skills/agent-authoring/SKILL.md`: *"Prefer adding
a focused specialist only when existing agents would blur accountability or miss
recurring work."* Every verdict below is that test applied, and every rejection
names the role or mechanism that already covers the ground.

## Method, and why it changed the answer

Each candidate was checked against the 71 existing roles, and then — rather than
reasoning about coverage from the definitions alone — `./bin/cadre select` was
run to see what a project *actually gets today*. That second step is what moved
three of the seven verdicts.

| Task | Files | Selected before this change |
| --- | --- | --- |
| "update the GitHub Actions release workflow to sign tags" | `.github/workflows/release.yml` | **no primary agent** |
| "update the CI pipeline to sign tags" | `.gitlab-ci.yml` | `cicd-engineer` + `pipeline-security-reviewer` |
| "define the design system tokens and component library" | `design-system/tokens.json` | **zero routes matched** |
| "implement a Python data transformation service" | `src/etl/transform.py` | **zero routes matched** |
| "build a RAG pipeline with an LLM provider and evaluate prompt quality" | `src/ai/rag.py` | `cicd-engineer` + `knowledge-store-steward` |

Rows one and two are the same task against two forges. `routing.yaml` carried six
GitLab references and **zero** GitHub ones — while this repository itself runs on
GitHub Actions.

Row five is the most misleading kind of failure: it returned a staffed,
confident-looking plan naming the wrong people. `cicd-engineer` matched on the
bare keyword `pipeline`; `knowledge-store-steward` owns *Cadre's own* retrieval
layer, not a consumer project's AI feature.

## Verdicts

| Candidate | Verdict | Vehicle |
| --- | --- | --- |
| AI Engineer | **Add** | role `ai-engineer` |
| Project Manager | **Reject as titled**, narrow substitute added | role `delivery-sequencer` |
| UI Expert | **Add** | role `visual-designer` |
| UX Expert | **Reject** | `interaction-designer` already is this role |
| Git Expert | **Reject** | skill `version-control-workflow` |
| GitHub / GitLab Experts | **Reject** | forge-neutrality repair |
| Go Engineer | **Reject** | `backend-engineer` + `technology-standards.md` |
| Python Engineer | **Reject** | routing repair |

Net: 71 → 74 roles, 11 → 12 skills.

### AI Engineer — added

No role covered AI/ML engineering for a *consuming project's product*. A
repo-wide grep across all 71 `AGENT.md` files found no owned scope mentioning
model selection, prompt engineering, inference cost, or evals.

The two roles that look adjacent are both scoped to Cadre's own agent system and
say so: `knowledge-store-steward` operates *this suite's* vectorized store, and
`agent-performance-evaluator` assesses "whether the roles **in this catalog** are
producing correct output" (`roster/operations/agent-performance-evaluator/AGENT.md:15`).
`ai-engineer`'s `## Authority` names both explicitly, because that is exactly
where this role would otherwise blur.

`roster/shared/technology-standards.md` had no AI section at all, so the new role
would have inherited no provider convention. An `ai:` block was added to
`team-profile.yaml` and a matching stanza to `technology-standards.md`, following
the existing `not_yet_selected` pattern: model provider, eval framework, and
vector store are recorded as unresolved, and the role must present alternatives
rather than choose. It also records the load-bearing constraints — model output
is untrusted data, an eval baseline precedes a prompt change, and model output
never authorizes a privileged action on its own.

### Project Manager — rejected as titled, narrow substitute added

Rejected because it overlaps six planning roles (`product-intent-agent`,
`requirements-agent`, `scope-boundary`, `assumption-register`, `premortem`,
`cost-capacity-planner`) plus eight authority aides, and because the title
collides with `IDENTITY.md:21-26`: the suite "is not the accountable product
owner." A role that sets priority and dates would claim authority the suite
explicitly disclaims.

But one artifact really was missing. `roster/planning/premortem/AGENT.md:19`
lists "the assumption register, capacity model, and dependency map" as inputs,
and **nothing produced the third**. `delivery-sequencer` owns exactly that
dangling input — dependency map, critical path, sequencing — and its `## Authority`
forbids setting priority, dates, scope, or risk tolerance. It expresses order and
prerequisites, never a schedule, because converting a sequence into dates
requires a capacity commitment this role does not hold.

This was the weakest of the three adds and was kept separable throughout.

### UI Expert — added; UX Expert — rejected

`interaction-designer` **is** the UX role: "flows, states, information
architecture, and accessibility intent"
(`roster/architecture/interaction-designer/AGENT.md:15`). Adding a second one
would split one accountability across two roles.

The same sentence ends "Design the interaction, **not the visual system** or the
implementation." And `frontend-engineer/AGENT.md:33-35` forbids selecting "a
React framework, package manager, build tool, component library, styling system,
or test stack" while those remain unresolved. So the visual system sat in a gap
that *both* neighbours explicitly disclaim — which the selector confirmed, with
zero routes matching a design-system task. `visual-designer` fills it, and
inherits the same constraint: it may recommend a component library, not select
one.

### Git / GitHub / GitLab Experts — rejected

A GitHub Expert role would not have fixed the table above. `cicd-engineer` would
still have hardcoded GitLab, and the two would then overlap on the same work.
The defect was in routing and in two roles' prose, so that is what was repaired.

Two further reasons not to make this a role. First, `agent-version-control` is a
false friend — it tracks provenance of *role definitions*, not git
(`roster/operations/agent-version-control/AGENT.md:15,36`) — so a git-named role
would be a standing source of confusion. Second, branching, rebase, history
surgery, and conflict resolution are procedural know-how, not an accountability
boundary. That is a skill, and `version-control-workflow` is it.

### Go Engineer / Python Engineer — rejected

No role in the catalog scopes itself to a language. Language is a provider
convention attached to a *layer* role, always with an escape hatch:
`backend-engineer/AGENT.md:30-31` says "prefer Go … justify Python";
`frontend-engineer/AGENT.md:36` says "prefer TypeScript … justify JavaScript".
`roster/shared/technology-standards.md:27-33` is the single place those
conventions live, and every role already inherits it. Language roles would
duplicate that and break the layer model.

The genuine defect behind the request was that Python work matched no route at
all — repaired below.

## What was changed

### Routing

- **`pipeline` route:** added `.github/workflows/**`, `.github/actions/**`, and GitHub keywords. A selector test now asserts the two forges staff *identically* for the same task, so this cannot silently regress to one-forge coverage.
- **`pipeline` keywords narrowed.** The bare keyword `pipeline` matched any pipeline — data, ETL, or RAG. Replaced with compounds (`ci pipeline`, `build pipeline`, `delivery pipeline`, …). This is what made the AI-feature task stop selecting `cicd-engineer`.
- **`backend` route:** added the `python` keyword. **Deliberately not a `**/*.py` path glob** — this repository is itself Python, and a bare glob cross-matched its own orchestration source (already correctly routed to `application-engineer`), adding `backend-engineer` as a spurious second primary. The routing schema has no exclusion mechanism, so the keyword is the honest fix. The asymmetry with `**/*.go` is intentional and recorded here so it does not read as an oversight.
- **Three new routes:** `ai-feature`, `visual-system`, `delivery-sequencing`.
- **`visual-designer` was *not* added to the `frontend` route's support.** It would have put two design roles on every `.tsx` change. The dedicated `visual-system` route covers the real case.

### Roles reworded rather than re-scoped

`cicd-engineer` and `pipeline-security-reviewer` both hardcoded GitLab. Both now
require establishing which forge applies and reviewing against that forge's own
controls, naming GitLab and GitHub as the two supported shapes, with an explicit
warning not to carry a control's name across — job permission scoping,
environment approval, and workload identity federation differ materially. Neither
role's authority widened.

## Two stale documents, found in the path of this change

Both post-dated the monorepo merge and would have misled the next person:

- `.agents/skills/agent-authoring/SKILL.md` still said to regenerate the plugin into a separate `deagy/cadre-lifecycle` checkout. That repository is archived; `plugin/` is in-tree and `validate.yml` runs `generate-plugin --check --output plugin`. The step now also enumerates the count constants and corpus fixtures a new role must satisfy — five of which this change discovered the hard way, by failing.
- `CLAUDE.md` said "The generated plugin distribution is not committed." `git ls-files plugin/agents` returns 74 files, and `.gitignore` says the opposite and is correct.

`docs/skills-catalog.md` was also already stale independently of this change: it
advertised 10 skills, omitted `cadre-install-kernel`, and pointed at the archived
repository. Corrected to 12.

## Verification

All suites green: 764 orchestration, 175 shared, 42 knowledge-store, 104
plugin-tools. `cadre generate-role-metadata --check` and
`cadre generate-plugin --check --output plugin` both exit 0.

Every row of the evidence table above now selects a primary agent, and three
selector tests plus three golden-corpus fixtures pin that. The AI-feature test
asserts both halves — `ai-engineer` **is** selected and `cicd-engineer` is **not**
— because the original failure was a confidently wrong plan, not an empty one.

## Deliberately not done

- **`interaction-designer` was not renamed** to "UX Designer" despite the request naming a UX Expert. The name is referenced across routing, tests, the golden corpus, and the generated distribution; the role's scope is what was being asked about, and it already matched.
- **`knowledge-store`'s generic keywords (`embedding`, `retrieval`, `rag`) were left alone.** They arguably belong to `ai-engineer` for a consumer project, but moving them would change an existing golden-corpus case's expected output, and selecting an extra advisory role is noise rather than a wrong answer. Worth revisiting if it proves annoying in practice.
- **`supply-chain`'s bare `dependency` keyword still matches "dependency map"**, so a sequencing task also pulls in `supply-chain-security-reviewer`. Same reasoning: noise, not error. The `DELIVERY-SEQUENCING-1` fixture avoids the phrase so it pins the route rather than the interaction.
