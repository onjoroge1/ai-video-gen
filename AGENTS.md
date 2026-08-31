# ReelForge Agent Rendering Protocol

This file is the canonical contract for AI agents that want to request a paid ReelForge video render.

## Core rule: one approval per immutable spend boundary

An AI may prepare and submit an immutable first-45-second directed pilot request. The AI must never require the operator to approve the same spend twice.

The intended flow is:

1. AI creates a **non-spending** immutable pilot proposal.
2. Operator reviews the exact spec hash and hard cost ceiling at `/agent/actions`.
3. Operator clicks **Approve & render exact pilot** once.
4. That single approval immediately authorizes, queues, and dispatches exactly that pilot.
5. The same page becomes a live render console: it shows sanitized durable events, progress, spend, and the finished video when available.
6. AI monitors the same resulting job/artifacts and reports the grade/result. No second execute confirmation is expected from the operator.

Approval is bound to the exact normalized spec SHA-256, cost ceiling, expiry, and
`first-45-pilot` scope. It never authorizes the rest of the film. A completed pilot may be followed
by one separately hash-bound `directed_full_film` action for only the remaining window.

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

Creation does **not** spend money. The response includes the action ID, immutable spec hash, estimated cost, ceiling and stable action-specific approval path. Repeating the request for the same exact spec-and-ceiling boundary returns its existing pending, executing, queued, completed, or failed lifecycle; it must not create another active proposal.

## Promote an accepted pilot

The full-film proposal is also non-spending. It must name the exact pilot action and job:

```json
{
  "operation": "directed_full_film",
  "bundled_spec_id": "hippo_illustrated_story_v4_full_5m",
  "parent_action_id": "<accepted pilot action>",
  "parent_job_id": "<accepted pilot job>",
  "cost_ceiling_usd": 6.00
}
```

The server verifies the parent spec, raw rendered-grade artifact, video SHA-256, and unchanged
0:00–0:45 narration/shot contract. The approval hash covers those parent identifiers and hashes,
the five-minute spec, the `remaining-45-to-300` scope, estimate, and ceiling. Execution downloads
the frozen pilot, generates only 0:45–5:00, and concatenates the accepted opening. Never regenerate
or charge for the pilot under this action.

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

After approval, keep the operator on the stable `/agent/actions?action=<action_id>` URL. Refreshing that URL must reconnect to the same action and job. Show only allowlisted durable application events—never raw provider responses, runtime logs, internal paths, tokens, credentials, or private Blob URLs. When the finished record exists, present the video through `/api/finished/{job_id}/artifact/video` with an explicit download link.

## Execution semantics

`POST /api/agent/actions/{action_id}/execute` consumes the approved action once and binds a durable job to it.

`POST /api/agent/actions/{action_id}/dispatch` idempotently starts/restarts only that already-bound durable job. It is an infrastructure action, not a new spending approval.

An action cannot execute unless it is approved, unexpired, has the exact approved spec hash, and remains within the approved hard cost ceiling.

## Status and artifacts

The action status progression is expected to be:

`pending -> approved -> executing -> queued -> rendering -> completed|failed`

The durable job and finished-video records are the source of truth after queueing. A failed pilot
remains a failed artifact; do not manually convert it into a pass or silently lower quality
thresholds. Technical delivery, automated grade, editorial grade, and promotion state are separate
fields. An unavailable story judge is `UNSCORED_JUDGE_UNAVAILABLE`, not a numeric reject and not
technical degradation. Deterministic hard failures still block promotion.

The public status endpoint supports incremental event retrieval:

`GET /api/agent/actions/{action_id}/public-status?after=<last_event_seq>`

Its event list is a sanitized progress feed, not a substitute for private infrastructure observability.

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
- Never let a remaining-film action regenerate or charge for the accepted pilot.
- Never require a second human approval for the same immutable pilot.

If the user says they approved the pilot, first verify the production action/job state. Under the current flow the render should already have been queued and dispatched by that single approval.
