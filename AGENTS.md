# ReelForge Agent Rendering Protocol

This file is the canonical contract for AI agents that want to request a paid ReelForge video render.

## Core rule: one human approval only

An AI may prepare and submit an immutable first-45-second directed pilot request. The AI must never require the operator to approve the same spend twice.

The intended flow is:

1. AI creates a **non-spending** immutable pilot proposal.
2. Operator reviews the exact spec hash and hard cost ceiling at `/agent/actions`.
3. Operator clicks **Approve & render exact pilot** once.
4. That single approval immediately authorizes, queues, and dispatches exactly that pilot.
5. AI monitors the resulting job/artifacts and reports the grade/result. No second execute confirmation is expected from the operator.

Approval is bound to the exact normalized spec SHA-256, cost ceiling, expiry, and `first-45-pilot` scope. Full-film generation is not authorized by this flow.

## Create a proposal

`POST /api/agent/actions`

JSON body for a bundled pilot:

```json
{
  "operation": "directed_pilot",
  "bundled_spec_id": "hippo_illustrated_story_v4",
  "cost_ceiling_usd": 1.60
}
```

Or provide a complete validated directed spec in `spec` instead of `bundled_spec_id`.

Creation does **not** spend money. The response includes the action ID, immutable spec hash, estimated cost, ceiling and approval path.

## Human approval

Send the operator to:

`/agent/actions`

For the bundled Hippo experiment the convenient entry point is:

`/agent/actions?pilot=hippo-v4`

If necessary, that page creates the non-spending bundled proposal and then presents one button:

**Approve & render exact pilot**

The approval endpoint is:

`POST /api/agent/actions/{action_id}/approve`

with the displayed `spec_sha256` and `cost_ceiling_usd`.

The authenticated approval page automatically follows successful approval with the bounded execute/dispatch calls. Do not ask the operator for a second approval or ask them to return to `/agent/actions/request`.

## Execution semantics

`POST /api/agent/actions/{action_id}/execute` consumes the approved action once and binds a durable job to it.

`POST /api/agent/actions/{action_id}/dispatch` idempotently starts/restarts only that already-bound durable job. It is an infrastructure action, not a new spending approval.

An action cannot execute unless it is approved, unexpired, has the exact approved spec hash, and remains within the approved hard cost ceiling.

## Status and artifacts

The action status progression is expected to be:

`pending -> approved -> executing -> queued -> rendering -> completed|failed`

The durable job and finished-video records are the source of truth after queueing. A failed pilot remains a failed artifact; do not manually convert it into a pass or silently lower quality thresholds.

Agents should report at minimum:

- action ID and job ID
- runtime
- visual-state/shot count
- actual spend vs hard ceiling
- technical validation status
- automatic grade
- editorial grade when available
- final promotion decision
- artifact/video location

## Safety and scope

- Never expose or request studio passwords, reusable worker secrets, or provider API keys.
- Never mutate the spec after approval. Create a new action for a changed spec.
- Never exceed the displayed hard cost ceiling.
- Never use a first-45 approval to generate a full film.
- Never require a second human approval for the same immutable pilot.

If the user says they approved the pilot, first verify the production action/job state. Under the current flow the render should already have been queued and dispatched by that single approval.
