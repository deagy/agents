# End-to-End Lifecycle Workflow

This example shows the full flow from task creation through post-release review using the Agentic SDLC G1-G10 lifecycle.

## Scenario

A team needs to add a new payment processing endpoint to their e-commerce platform. The change affects the payment service, requires security review, and will be deployed to production.

## Step 1: Initialize the Project Overlay

```sh
# Bootstrap the project's .agentic-sdlc/ directory
./bin/agentic-sdlc init --root /path/to/project --profile secure-cloud
```

This creates:
- `.agentic-sdlc/project.json` — project configuration
- `.agentic-sdlc/authorities.json` — authority assignments
- `.agentic-sdlc/routing.json` — task routing rules
- `.agentic-sdlc/version.lock` — kernel version lock

## Step 2: Create a Task Plan (G1 Intent)

```sh
./bin/agentic-sdlc plan \
  --task "Add Stripe payment processing endpoint for subscription renewals" \
  --files src/payment_service/api.py \
  --task-id PAY-2026-001 \
  --classification internal
```

This creates `.agentic-sdlc/runs/PAY-2026-001/run-record.json` with G1 as the first pending gate.

## Step 3: Check Gate Status

```sh
./bin/agentic-sdlc status PAY-2026-001
```

Output shows:
- G1 Intent: pending
- G2-G10: not yet active

## Step 4: Approve G1 (Intent)

The task source (e.g., a product manager) approves the intent via GitHub PR review:

```sh
./bin/agentic-sdlc approve-from-github \
  --task-id PAY-2026-001 --gate G1 \
  --repo owner/ecommerce --pr 142 \
  --review-id rev-abc123 --reviewerLogin pm-jane \
  --commit-sha abc123def456
```

## Step 5: Progress Through Gates

The lifecycle proceeds through G2 (Requirements), G3 (Architecture), G4 (Security), G5 (Implementation), G6 (Integration), G7 (UAT), G8 (Performance), G9 (Release).

Each gate is approved via the appropriate evidence adapter:
- GitHub PR reviews for code-related gates (G5, G6)
- Direct decisions for architecture gates (G3, G4)
- Release checklists for G9

## Step 6: Release (G9)

```sh
./bin/agentic-sdlc approve-from-github \
  --task-id PAY-2026-001 --gate G9 \
  --repo owner/ecommerce --pr 155 \
  --review-id rev-xyz789 --reviewerLogin release-lead \
  --commit-sha def456ghi789
```

## Step 7: Post-Release Review (G10)

After deployment, the evidence-curator role assesses whether the release met its intent:

```sh
./bin/agentic-sdlc status PAY-2026-001
# G10 Post-Release Review: pending
```

The evidence-curator collects metrics and compares against G1 intent and G2 requirements, then approves G10 to close the loop.

## Gate Invalidation Example

If a security vulnerability is discovered after G4:

```sh
# Invalidate G4
./bin/agentic-sdlc invalidate PAY-2026-001 G4 \
  --note "CVE-2026-12345: input validation bypass in payment parser"

# Check status - downstream gates are now pending re-approval
./bin/agentic-sdlc status PAY-2026-001
# G4 Security Review: invalidated
# G5 Implementation: pending (requires re-approval)
# G6-G9: pending (downstream of invalidated gate)
```

The system re-baselines from G4, requiring all downstream gates to be re-evaluated with the fix.

## See Also

- [docs/gate-rationale.md](../gate-rationale.md) — why these ten gates
- [README.md](../README.md) — full system documentation
