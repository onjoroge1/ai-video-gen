# ReelForge User-Directed Long-Form Generation — AI Execution Runbook

**Status:** Authoritative operating contract  
**Runbook version:** 1.2 — truthful grading and hash-bound remaining-film promotion\
**Scope:** Preparing, validating, approving, rendering, promoting, recovering, inspecting and reporting a user-directed ReelForge long-form video
**Repository:** `onjoroge1/ai-video-gen`  
**Production studio:** `https://ai-video-gen-nine.vercel.app`  
**Approval page:** `https://ai-video-gen-nine.vercel.app/agent/actions`  
**Finished library:** `https://ai-video-gen-nine.vercel.app/finished`  
**Last revised:** 2026-08-31

> **AI instruction:** Read this entire file before attempting a user-directed long-form run. Execute
> the workflow during the current task; do not stop at a plan. The user directs the creative. Keep
> their narration, claims, evidence, shot order and acceptance thresholds authoritative. Never
> substitute the model-authored explainer flow for this one.

---

## 0. Automatic-execution directive

When the user supplies this document, links to it, or says **“run/render this user-directed
video”**, treat that as authorization to perform all non-spending preparation immediately and to
create one bounded, non-spending approval action for the exact first-45-second pilot.

This document does **not** bypass ReelForge's human spend gate. The operator approves the exact
immutable pilot once. That one approval authorizes its queue and dispatch; do not ask for another
execute confirmation.

Use these defaults only when the user's spec does not already define the value:

```text
schema_version       = directed_longform_v1
format               = landscape
voice                = echo
pilot window         = 0.0–45.0 seconds
pilot runtime gate   = 43.0–47.0 seconds
scope                = first-45-pilot
normal compute       = production durable ReelForge worker
finished location    = /finished
```

Do not invent or silently default creative facts, source licenses, reference hashes, narration,
shot content, cost ceilings or acceptance thresholds when those choices would change the film.
Resolve them from the user-directed source. If an input is genuinely missing, continue every
non-spending step that remains possible, return the exact validation issue and ask only for that
missing input.

The expected behavior is:

1. Fetch the current `main` version of this runbook.
2. Obtain the user's complete directed JSON or compile their supplied production document.
3. Fetch the current schema and validate without spending.
4. Run production readiness.
5. Create exactly one durable, immutable, non-spending agent action through the API.
6. Give the operator the exact title, hash, ceiling and `/agent/actions` link.
7. After the single approval, verify that the same action queued and dispatched its durable job.
8. Keep the stable action page connected to sanitized durable progress and spend events.
9. Monitor and, when necessary, recover that same job.
10. Present the finished video on the action page and verify the Blob-backed `/finished` record.
11. Inspect the actual MP4 and rendered-story artifacts.
12. Report technical delivery and editorial acceptance separately.
13. Remove any temporary recovery harness.

Do not answer only with “I can run it,” “please approve,” or a workflow description. Advance the
run as far as the current state allows.

---

## 1. Authorization boundary

There are three distinct permissions. Never blur them.

### A. Preparation — automatically authorized

The AI may:

- Read the user's source material.
- Fetch the schema and starter template.
- Normalize or compile the directed spec without changing its meaning.
- Validate the spec.
- Calculate hashes and estimates.
- Run readiness.
- Create one non-spending approval action.
- Monitor public action state.

### B. First-45 pilot spend — one operator approval

The operator reviews the exact title, normalized spec SHA-256, estimated pilot cost, hard ceiling,
expiry and `first-45-pilot` scope. Clicking **Approve & render exact pilot** once authorizes:

- TTS for the pilot.
- Paid pilot images and permitted motion.
- Pilot assembly and rendered-story grading.
- Durable Blob and Postgres persistence.
- Queue, dispatch and bounded recovery of that exact job.

Approval is not valid for edited bytes, a higher ceiling, another action, a second pilot or a full
film.

### C. Remaining-film spend — a separate operator approval

A technically complete pilot, automatic pass or editorial pass does not authorize later scenes.
Create a separate `directed_full_film` action bound to the exact parent action, parent job, parent
video SHA-256, unchanged opening contract, full spec hash, `remaining-45-to-300` scope, estimate and
hard ceiling.

Clicking **Approve & render remaining film** authorizes only the 0:45–5:00 window. The worker reuses
the accepted pilot artifact, generates only the remaining narration, images and motion, concatenates
the frozen opening, and exposes the full video on the same action page. If this separately scoped
path is unavailable in the deployed app, report that limitation; never reuse the pilot approval or
improvise an unbound render.

---

## 2. Non-negotiable rules

1. **Use ReelForge itself.** The pilot must originate from the deployed ReelForge user-directed API
   and run through its existing directed renderer.
2. **The user-directed spec is authoritative.** Do not rewrite narration, reorder shots, alter
   claims, replace sources, loosen thresholds or change asset reuse after approval.
3. **Validate before spend.** Validation must import no paid generation provider and create no
   render job.
4. **Create the proposal server-side first.** `POST /api/agent/actions` is the authoritative
   creation step. A convenience query string is not.
5. **One approval only.** The approval click immediately authorizes queue and dispatch. Never ask
   the operator to approve or confirm the same pilot again.
6. **One action becomes one job.** Once a durable job ID exists, recover that job instead of
   creating another action or render.
7. **Respect the hard cost ceiling.** Never exceed the approved ceiling or reinterpret an estimate
   as permission to spend more.
8. **Fail closed on timing.** TTS is measured before visual spending. If measured narration misses
   the contract and cannot be safely adjusted within the declared rules, stop before images.
9. **Preserve failed artifacts.** A failed or rejected pilot stays failed or rejected. Never
   manually replace images, edit the MP4 or lower thresholds to convert it into a pass.
10. **Durable state is authoritative.** Browser messages, HTTP timeouts, deployment state and local
    files do not override Postgres, Blob and `/finished`.
11. **Inspect rendered pixels.** Spec validation and metadata grades do not prove story quality.
12. **Keep evidence.** Preserve action ID, job ID, exact hash, estimates, ceiling, readiness,
    attempts, leases, cost, errors, manifests, grade artifacts and final artifact hash.
13. **Never expose credentials.** Do not print, commit or return cookies, passwords, app secrets,
    worker secrets, database URLs, Blob tokens or provider keys.
14. **Separate delivery from grading.** A completed MP4 is technically complete. An unavailable
    story judge is `UNSCORED_JUDGE_UNAVAILABLE`, not a fabricated low score or technical
    degradation. Deterministic hard failures remain real rejections.
15. **Reuse the accepted opening.** A remaining-film action may not regenerate, alter or charge for
    0:00–0:45.
16. **Do not change `main` merely to run a pilot.** Temporary recovery infrastructure belongs on a
    disposable QA branch and must not be merged.

---

## 3. Canonical production flow

```text
Read user-directed source and this runbook
        ↓
Fetch schema/template when needed
        ↓
Compile or normalize exact directed JSON
        ↓
POST /api/explainer/directed/validate   (no spend)
        ↓ only when valid=true
GET /api/production-readiness
        ↓ only when ready=true
POST /api/agent/actions                (no spend)
        ↓ save action_id + spec_sha256 + ceiling
Operator opens stable /agent/actions?action=<action_id>
        ↓ one “Approve & render exact pilot” click
Approve → execute → queue → dispatch
        ↓
Approval page polls /public-status?after=<event_seq>
        ↓ sanitized progress, events and spend
        ↓
Same durable job reaches a terminal state
        ↓
Approval page embeds /api/finished/{job_id}/artifact/video
        ↓
GET /api/finished/{job_id}/artifact/video?download=true
        ↓
Probe and inspect actual Blob-backed MP4 + grade artifacts
        ↓
Report technical delivery, editorial result and promotion status
        ↓ only when operator requests the full film
POST /api/agent/actions operation=directed_full_film
        ↓ binds parent action/job/video SHA + unchanged opening + 0:45–5:00 estimate
Operator clicks “Approve & render remaining film” once
        ↓ generate only later window; reuse frozen pilot
Blob-backed directed-v1-full record + embedded five-minute video
```

The AI must create the proposal before sending the approval link. This makes proposal existence
independent of browser JavaScript, GitHub fetches, login redirects and query-string preservation.

---

## 4. Input contract and creative authority

The canonical format is JSON conforming to `directed_longform_v1`. Fetch the live contract from:

```http
GET /api/explainer/directed/schema
GET /api/explainer/directed/template
```

The required sections are:

```text
schema_version
project_id
title
negative_prompt
target
acceptance
worlds
narration
shots
evidence
references
prohibited_claims
```

### User supplies JSON

Use it as the source of truth. Normalize it only through the deployed validator. Any substantive
edit creates new bytes and therefore a new hash.

### User supplies a Markdown production document

The repository adapter may compile it:

```python
import user_directed

payload = user_directed.compile_directed_spec("path/to/operator_spec.md")
```

The adapter deliberately does not invent evidence mappings, licenses, reference hashes or asset
reuse groups. Resolve every reported omission before proposing paid work.

### User supplies only a creative brief

The AI may draft a complete directed spec as a non-spending preparation step, using the brief as
creative authority. Before creating the action, verify that the draft contains exact narration,
timed shots, acceptance thresholds, evidence treatment, reference provenance and a hard ceiling.
Do not conceal AI-authored additions as user-authored decisions.

### Asset reuse

`asset_key` identifies a paid master image. All shots sharing an asset key must share the same
master prompt, world and references. Every reuse must declare its transformation. Do not fake
visual novelty by creating repeated directional pans over one master.

### Directed visual-cadence contract

For a normal 45-second user-directed pilot, author and validate the picture track against the
underlying source assets—not merely the number of shot-table rows:

- A still master normally remains onscreen for **2–3 seconds maximum** before a genuinely new
  composition replaces it.
- Crops, overlays, push-ins and pan-direction changes over the same `asset_key` do not count as new
  images. Their consecutive time is added into one source-image hold.
- Require an explicit pilot minimum for unique master images. The current bundled illustrated
  history profile uses 18 unique masters across 45 seconds.
- A deliberate callback may reuse an earlier master later in the edit; non-consecutive reuse does
  not create a long hold.
- Declared generated-video shots use the complete **5-second** provider clip unless the acceptance
  contract explicitly says otherwise.
- Front-load the highest-value motion. The current profile requires two 5-second motion shots to
  begin within the first 15 seconds, then relies on varied 2–3-second still compositions.
- Vary shot scale and visual grammar—wide, medium, close, macro, overhead, over-shoulder, diagram,
  reaction and environmental views—rather than generating near-duplicates under new keys.

If the cost ceiling cannot fund the declared unique-image and motion profile, fail validation and
revise the non-spending spec. Never make the estimate fit by silently reusing one composition for
5–9 seconds.

### Evidence and references

- A factual claim must map to declared evidence when required by the spec.
- A reference must include URI, SHA-256, MIME, origin and resolved usage/license status.
- Reference bytes are checked before TTS.
- Do not replace a missing reference with an unapproved look-alike.
- Hypothetical imagery must be visibly and narratively distinguishable from historical fact.

---

## 5. Free validation

Call:

```http
POST /api/explainer/directed/validate
Content-Type: application/json

{
  "spec": { ...complete directed_longform_v1 spec... }
}
```

A passing response must include:

```text
valid = true
spec_sha256
normalized_spec
pilot_cost_estimate
cost_estimate
title
```

Save the normalized spec and `spec_sha256`. The normalized spec—not the unnormalized source file—is
what must be proposed and later authorized.

Validation must verify at minimum:

- Schema version and required sections.
- Stable unique scene and shot IDs.
- Contiguous scene/shot timing and pilot coverage.
- Narration-to-world and narration-to-claim references.
- Shot-to-scene, evidence and reference mappings.
- Asset-key prompt identity and transformation declarations.
- Consecutive source-image hold time across shared asset keys.
- Pilot minimum for genuinely unique master compositions.
- Five-second generated-motion duration and opening motion count/window when declared.
- Duplicate master prompts hidden behind different asset keys.
- Unique-master cap.
- Bolt appearance bounds when declared.
- Evidence coverage.
- Reference SHA-256, MIME and license fields.
- Pilot runtime, visual-state and unchanged-hold thresholds.
- Automatic and editorial grade floors.
- Pilot and full-film estimates against declared caps.

If `valid=false`, do not create an action and do not spend. Return the validator's exact issues,
correct only changes consistent with the user's direction and validate again.

---

## 6. Authentication

Production studio routes are private. Use one existing ReelForge mechanism:

- An authenticated studio session using the signed `reelforge_session` cookie; or
- `X-App-Secret` for an already authorized headless client; or
- The narrowly scoped worker authentication already configured for internal recovery routes.

The proposal endpoint is intentionally a non-spending public handshake. Approval and pending-list
access require an authenticated operator session.

Never ask the user to paste credentials into chat. Never create an anonymous render endpoint,
broad authentication bypass or reusable public worker.

### Login/query-string rule

The authentication middleware must preserve the full path and query through sign-in. This makes a
server-supported bundled entry point such as:

```text
/agent/actions?pilot=hippo-v4
```

safe to open before or after authentication. Keep an automated test for this exact redirect because
dropping `pilot=...` returns the operator to an empty queue.

The reliable order is:

```text
POST /api/agent/actions successfully
        ↓
save returned action_id
        ↓
send operator to /agent/actions
```

For arbitrary inline specs, still create the durable proposal first and send the query-free approval
page. Only server-advertised bundled IDs may use the convenience query entry point.

---

## 7. Pre-spend production-readiness gate

Using an authenticated mechanism, call:

```http
GET /api/production-readiness
```

Proceed to approval only when top-level `ready` is true. At minimum verify:

```json
{
  "media_binaries": true,
  "private_access": true,
  "durable_artifacts": true,
  "database": true,
  "blob": true,
  "durable_execution": true,
  "worker_auth": true
}
```

`youtube_validation` and `fal_i2v` may describe optional capabilities. Whether either is required
depends on the exact directed spec.

Do not fail readiness solely because the detailed response says `ffprobe.found: false` when
top-level readiness, `checks.media_binaries` and `media.ready` are true and ReelForge reports an
accepted ffmpeg fallback.

Readiness proves configuration and infrastructure. It does not prove provider funding or quota.
Any provider conclusion must come from the current job and current timestamp, not an older render.

If readiness fails, stop before approval/spend and report the exact failed checks.

---

## 8. Create the durable non-spending proposal

For a normal user-directed run, submit the complete validated normalized spec inline:

```http
POST /api/agent/actions
Content-Type: application/json

{
  "operation": "directed_pilot",
  "spec": { ...normalized spec returned by validation... },
  "cost_ceiling_usd": 1.60
}
```

The ceiling above is an example, not a universal default. Use the user's declared pilot ceiling.
It must be at least the validated pilot estimate and no more than the deployed action cap.

For a genuinely deployed server-side bundle, the alternative is:

```json
{
  "operation": "directed_pilot",
  "bundled_spec_id": "<server-advertised-id>",
  "cost_ceiling_usd": 1.60
}
```

Use a bundle only if the production API currently supports that exact ID. A JSON file existing in
GitHub or `/static` does not make it a supported server bundle. Prefer the inline normalized spec
for arbitrary user-directed films.

### Create a remaining-film proposal

After the operator accepts a technically complete pilot, create a new non-spending action:

```http
POST /api/agent/actions
Content-Type: application/json

{
  "operation": "directed_full_film",
  "bundled_spec_id": "hippo_illustrated_story_v4_full_5m",
  "parent_action_id": "<accepted pilot action>",
  "parent_job_id": "<accepted pilot job>",
  "cost_ceiling_usd": 6.00
}
```

The ceiling is an example for this validated bundle, not a universal default. The returned estimate
is for 0:45–5:00 only. Before creating the proposal, the server must verify:

- The parent action is a durable directed pilot bound to the stated job.
- The parent normalized spec still matches its stored SHA-256.
- The Blob-backed pilot video and rendered-grade artifacts exist.
- The parent video SHA-256 matches the artifact record.
- No deterministic rendered-grade hard failure blocks promotion.
- The full spec preserves every opening narration and shot row through 0:45.
- The remaining-window estimate fits both the requested ceiling and deployment cap.

The action's displayed authorization SHA-256 covers the full spec and the complete promotion
envelope. Approval must show `remaining-45-to-300`, the parent job/video hash, estimated new spend,
and the hard ceiling. The accepted pilot's prior spend is sunk and excluded.

### Expected response

```json
{
  "action_id": "act_<32 hex characters>",
  "operation": "directed_pilot",
  "status": "pending",
  "title": "<exact title>",
  "spec_sha256": "<64 hex characters>",
  "estimated_cost_usd": 1.50,
  "cost_ceiling_usd": 1.60,
  "scope": "first-45-pilot",
  "expires_at": "<timestamp>",
  "claim_token": "<shown once>",
  "approval_path": "/agent/actions?action=act_<32 hex characters>",
  "reused": false
}
```

When the same spec and ceiling already have an authoritative lifecycle, the endpoint returns that
action with `"reused": true` and does not return another claim token. This is a reconnect, not a
new proposal.

Immediately verify:

- Returned title equals the intended title.
- Returned hash equals the validator's hash.
- Scope is exactly `first-45-pilot`.
- Estimate does not exceed the ceiling.
- Expiry leaves enough time for review.
- No job exists and no spend occurred yet.

Store the one-time claim token securely for recovery during the current task. Never print or return
it. Once approval rotates the execution capability, the opaque action ID is the bounded capability
used by the approval page.

### One proposal rule

Create the action once. The server must resolve repeated requests for the same exact spec-and-ceiling
boundary to its existing authoritative lifecycle, prioritizing an executing or queued action over
any later duplicate pending row. Do not create duplicates because the approval page is empty, login
occurs, a response times out or deployment is still building. First query the known action's public
status.

An expired **unapproved** action spent nothing and may be replaced with a newly validated action.
An approved or queued action must not be replaced merely because its render is slow.

---

## 9. Human approval without back-and-forth

Give the operator one concise checkpoint containing:

```text
Title
Scope: first 45 seconds only
Spec SHA-256
Estimated cost
Hard cost ceiling
Expiry
Approval link: https://ai-video-gen-nine.vercel.app/agent/actions?action=<action_id>
```

The card must show the same title, hash and ceiling returned when the action was created. If it does
not, do not approve; create no spend and investigate the mismatch.

The one button is:

```text
Approve & render exact pilot
```

For a separately scoped continuation action, the one button is:

```text
Approve & render remaining film
```

That button authorizes only the displayed later window. It does not re-authorize or regenerate the
pilot.

That click performs the authenticated hash-and-ceiling approval, then automatically calls execute
and dispatch. The page converts to a live render console and retains the stable action URL. It
shows bounded progress, sanitized durable events, spend against ceiling, and the completed video;
refreshing or reopening the URL reconnects to the same action and job.

Do not ask the operator to:

- Open `/agent/actions/request` after approving.
- Paste a claim token.
- Click a second “execute” confirmation.
- Re-approve after a dispatch timeout.
- Approve a full film as part of the pilot action.

### Empty approval queue diagnosis

If the page says **No pending or approved actions**:

1. Check `GET /api/agent/actions/{action_id}/public-status` for the exact saved action.
2. If it is `pending` and unexpired, the row exists; verify the operator is in the same production
   deployment/database and reload the authenticated page.
3. If it is `expired`, create one replacement action from the unchanged validated spec.
4. If it is `approved`, `executing` or `queued`, do not create another proposal; continue that
   action/job.
5. If it is 404, proposal creation never persisted. Re-run the single non-spending POST and verify
   its returned action ID before sending the link.

Never “fix” an empty queue by creating a second spend candidate. A convenience URL may make the
same non-spending create request only because the server resolves it idempotently by validated spec
hash plus exact ceiling and returns the existing lifecycle. Spec construction and GitHub translation
do not belong in approval-page JavaScript.

---

## 10. Execution and dispatch semantics

The approval page uses:

```http
POST /api/agent/actions/{action_id}/approve
POST /api/agent/actions/{action_id}/execute
POST /api/agent/actions/{action_id}/dispatch
```

Execution consumes the approval exactly once, revalidates the stored payload and hash, and binds one
durable job to the action. A pilot action reconstructs only the first-45 request. A remaining-film
action revalidates the parent binding and reconstructs only the 0:45–5:00 request with frozen-pilot
reuse. Dispatch starts only that already-bound job.

Expected action-side progression is:

```text
pending → approved → executing → queued
```

After `queued`, the durable job and finished record are authoritative. Do not require the action row
itself to transition to every later worker state.

### Approval succeeded but automatic execution failed

This is not a new approval event. Verify the action is still `approved`. The AI or approval page may
retry the bounded execute call using:

```http
Authorization: Bearer <action_id>
```

If a job is already bound, do not execute again. Dispatch/recovery may be retried only for that job.

### Dispatch timeout

A dispatch request may time out while the durable worker continues. Do not create another action or
job. Poll public status and durable job state. Treat an HTTP body as transport evidence, not render
completion.

---

## 11. Monitoring the authoritative job

The public, non-sensitive status endpoint is:

```http
GET /api/agent/actions/{action_id}/public-status?after=<last_event_seq>
```

It intentionally omits spec payloads and credentials. Once queued, capture:

```text
action_id
job.id
job.status
job.attempts / max_attempts
job.spent_cost_usd
job.reserved_cost_usd
job.max_cost_usd
job.lease_expires_at
job.updated_at
job.checkpoint_present
job.error
job.result
finished_video
progress.stage / progress.percent
progress.narration_completed / progress.narration_total
progress.images_completed / progress.images_total
progress.motion_completed / progress.motion_total
events
next_event_seq
```

The action page polls incrementally using `next_event_seq`, retains recent events across each poll,
and reconnects after refresh using the opaque action ID in its URL. Public events are an allowlisted,
sanitized application feed. Never expose raw Vercel logs, provider responses, credentials, tokens,
internal filesystem paths or private Blob URLs in this endpoint.

When `finished_video` exists, the page must embed the authenticated same-origin player path and
offer the same-origin download path. The operator should not need to find the artifact in a separate
screen, though `/finished/{job_id}` remains the detailed record.

When authenticated status streaming is available, it may also be observed at:

```http
GET /api/explainer/status/{job_id}
```

Poll fresh state. Do not rely on an old browser card, cached response, prior job or Vercel deployment
status.

Relevant terminal/paused job states include:

```text
done
degraded
error
storage_error
pilot_awaiting_editorial
pilot_passed
pilot_failed
awaiting_review
human_rejected
```

The directed pilot's rendered grade determines whether it is eligible for editorial consideration.
A rendered artifact can be technically delivered while still failing promotion.

---

## 12. Paid stage order and fail-closed behavior

The directed renderer must preserve this order:

```text
validate exact spec and reference bytes
        ↓
generate TTS
        ↓
measure word timings and pilot runtime
        ↓ only if timing contract passes
generate/reuse images and approved motion
        ↓
assemble and mux MP4 with fast-start
        ↓
grade encoded pixels and story
        ↓
persist artifacts, job result and /finished row
```

Important consequences:

- Missing/corrupt reference bytes stop before TTS.
- Missing measured word timings stop before visual spending.
- Runtime outside the approved gate stops before visual spending unless the existing safe audio-fit
  rule applies and records the actual transformation.
- Provider/model IDs, asset SHA-256 and MIME must be recorded in the generation manifest.
- I2V cache identity must include source bytes, prompt, duration, dimensions and model.
- A visual-generation or render failure preserves every completed paid artifact and checkpoint.
- The system must not silently fall back from the user's story format or creative direction.

---

## 13. Recovery decision tree

Recovery always targets the same action and same durable job.

```text
No job ID
  ├─ action pending → wait for the one approval
  ├─ action approved → bounded execute; no second approval
  └─ action expired/unpersisted → recreate only if no spend occurred

Job ID exists
  ├─ active lease → monitor; do not dispatch concurrently
  ├─ stale/expired lease → reclaim same job through durable worker rules
  ├─ storage_error → requeue same job through allowed-status mechanism
  ├─ repaired exact infrastructure error → bounded rearm of same job
  ├─ repeatable OOM/disk limit → same job on trusted higher-resource worker
  └─ terminal creative/provider failure → preserve and report; do not manufacture a pass
```

Do not:

- Issue another agent-action POST after provider spend begins.
- Fire concurrent dispatches against an active lease.
- Exhaust attempts on compute already proven unable to finish.
- Change the spec, hash, thresholds or ceiling during recovery.
- Manually assemble or upload a substitute MP4.

### Higher-resource recovery

If normal compute hits a repeatable memory or ephemeral-disk limit, a temporary trusted worker may
call the repository's existing durable worker for the exact job. It must use the same production
Postgres and Blob stores, target one explicit job ID, live on a disposable QA branch and be deleted
or reset after evidence is captured.

Do not merge a recovery route, broad renderer or job-creation workflow into `main`.

---

## 14. Durable persistence and finished artifacts

When the pilot reaches technical completion, verify:

```http
GET /api/finished/{job_id}
```

Required evidence:

```text
id == job_id
format == directed-v1-pilot
status is a real terminal delivery state
storage == blob
artifacts.video exists
metadata identifies the directed project/title
```

Retrieve the actual video:

```http
GET /api/finished/{job_id}/artifact/video?download=true
```

Confirm the card exists at:

```text
https://ai-video-gen-nine.vercel.app/finished
```

Local `/tmp`, build output and provider URLs are not authoritative delivery locations.

Expected supporting artifacts may include:

```text
normalized directed spec
validation report
generation manifest
audio timing report
motion report
rendered contract/grade
rendered contact sheet
human editorial review form or record
captions/transcript
final MP4
```

Report an artifact only after verifying it exists in the durable finished record or Blob-backed
artifact set.

---

## 15. Cost accounting

Track both:

- `generation_jobs.spent_cost_usd`: authoritative durable job-ledger spend.
- `finished_videos.metadata.actual_cost`: pipeline-reported creative/render cost.

These may differ. Report both when available, plus the remaining reservation:

```text
durable ledger spend   = $X.XXXX
finished metadata cost = $Y.YYYY
reserved cost          = $0.0000 at finalization
approved hard ceiling  = $Z.ZZ
```

If spent plus reserved would exceed the ceiling, stop. Do not claim zero spend unless the current
job confirms it.

---

## 16. Technical validation

Inspect the exact Blob-backed MP4.

### Integrity checks

- Artifact download succeeds.
- SHA-256 matches durable artifact metadata.
- MP4 decodes without errors.
- Video and audio streams exist.
- Dimensions match the directed format (normally 16:9 landscape).
- Duration satisfies the approved pilot runtime gate.
- Frame rate and audio sample rate are plausible.
- MP4 is fast-started for web playback.
- No long frozen hold violates the declared threshold.

Reference probe:

```bash
ffprobe -v error \
  -show_entries format=duration,size:stream=index,codec_type,codec_name,width,height,r_frame_rate \
  -of json pilot.mp4
```

### Timeline evidence

Create a contact sheet and regular timeline samples. Review the whole 45 seconds, not only the
thumbnail or first frame.

Verify:

- Every narrated beat has a semantically relevant visual state.
- Shot order, timing, world and transformations match the approved spec.
- The opening consequence/hook is visible immediately.
- Visual changes meet the spec's minimum state count and hold limits.
- Source-image changes meet the unique-master floor and 2–3-second consecutive source-hold limit;
  crops or overlays over one master are not counted as fresh images.
- Asset reuse is intentional and transformations are real.
- Motion appears at the declared semantic action, uses its declared five-second duration and is
  front-loaded when the acceptance profile requires it.
- On-screen text is readable and factually aligned.
- Evidence/reference imagery is used only where declared.
- Hypothetical and historical visuals cannot be confused.
- Bolt appears only within the approved minimum/maximum and contributes useful story action.
- The ending completes the declared callback or payoff.

### Audio evidence

Verify:

- Narration matches the exact approved text.
- Measured timing is recorded.
- Any audio transformation is accurately recorded rather than hardcoded as natural speed.
- Speech is intelligible and not unnaturally slow or rushed.
- Music/SFX do not mask narration.
- Cuts align with phrases and semantic events.
- The ending is not clipped.

---

## 17. Automatic and editorial grading

Keep these conclusions separate:

```text
Technical delivery: passed or failed
Automatic rendered grade: score/status
Editorial grade: score/status or not yet completed
Promotion decision: eligible, rejected or awaiting editorial review
```

The automatic grade must inspect the encoded rendered story, not only source metadata. A story judge
that did not run is neither a pass nor a creative rejection. Report it as
`UNSCORED_JUDGE_UNAVAILABLE` with no numeric composite score. Do not convert absent judge booleans
into zeros. Deterministic pixel, cadence, continuity and claim failures remain authoritative and may
still produce `REJECT` when the story judge is unavailable.

Use four separate fields everywhere downstream:

```text
technical_status       = completed | failed
automated_grade_status = pass | reject | unscored
editorial_status       = pending | approved | rejected
promotion_status       = blocked | awaiting_editorial | eligible | full_film_completed
```

Legacy immutable reports are not rewritten. A read-time classification may correct an old durable
delivery label from `degraded` to `done` only after it verifies the raw rendered report has no
deterministic hard failures. Preserve the old report, original label, artifact hashes and spend.

A pilot below `automatic_grade_min` is rejected for promotion even if the MP4 plays. A pilot above
the automatic floor may still require editorial review. Editorial review must use the approved
rubric and actual contact sheet/MP4; it must not change the film in place.

If a pilot fails:

- Preserve the MP4 and all supporting artifacts.
- Record the real failure reasons.
- Do not lower thresholds.
- Do not manually swap images or rewrite the manifest.
- A revised creative requires a new spec, new hash, new estimate and new approval action.

---

## 18. Failure handling

### Empty approval page

Use the saved action ID and Section 9. Do not recreate spec client-side.

### Authentication redirect

Sign in through the existing secure flow, then open query-free `/agent/actions`. Never request or
expose the user's password.

### Request or dispatch timeout

Poll public action/job state. Continue the same job.

### Current provider failure

Tie the exact error to the current job and timestamp. Do not infer account funding from stale jobs.

### Timing failure

Confirm the measured timing artifact and that visual spend stopped. Revise only through a new spec
and new action if the user chooses.

### OOM or ephemeral-disk failure

Preserve job/checkpoint, wait for lease expiry and move the same job to the trusted higher-resource
worker.

### Storage failure

Requeue only the same job through the durable store's allowed-state mechanism. Verify Blob and
`/finished` afterward.

### Rendered quality failure

Preserve the failed artifact and grade. Do not convert it to a pass.

---

## 19. Prohibited shortcuts

The following violate this runbook:

- Calling `/api/explainer/generate` as a substitute for the user-directed path.
- Sending internal `directed_spec`, `controlled_pilot` or `controlled_production` fields to the
  public generic endpoint.
- Calling `/api/explainer/directed/process` with `authorize_paid=true` outside the approved
  hash-bound action workflow and then asking for another approval.
- Depending on `?pilot=...` approval-page JavaScript to create the durable proposal.
- Fetching a spec from GitHub in the operator's browser as the authoritative production handoff.
- Treating a static JSON file as a supported `bundled_spec_id` without server support.
- Creating duplicate actions/jobs after timeout or login redirect.
- Editing the spec after approval.
- Replacing generated images manually.
- Rebuilding the pilot with local FFmpeg, Canva or another service and presenting it as ReelForge.
- Uploading an external MP4 into `/finished` as though ReelForge generated it.
- Lowering runtime, visual-state, evidence, automatic-grade or editorial-grade thresholds.
- Treating `degraded` or `pilot_failed` as a clean pass.
- Using first-45 approval for the full film.
- Leaving temporary recovery infrastructure deployed.
- Exposing credentials or one-time tokens.

---

## 20. Temporary-infrastructure cleanup

After durable artifacts and evidence are secured:

1. Preserve the production action, job, finished row and Blob artifacts.
2. Preserve QA artifacts long enough for editorial review.
3. Reset or delete temporary QA branches and workflows.
4. Confirm no temporary route, build command or broad worker remains deployed.
5. Confirm `main` contains no one-off job ID, claim token or recovery credential.
6. Do not delete the finished pilot unless the user explicitly requests deletion through a
   supported operation.

Cleanup is part of completion.

---

## 21. Required final report

### Completed pilot

```markdown
## ReelForge user-directed pilot completed

- Action ID: `<action_id>`
- Job ID: `<job_id>`
- Title: `<exact title>`
- Spec SHA-256: `<hash>`
- Scope: `first-45-pilot`
- Terminal job status: `<status>`
- Measured duration: `<seconds>`
- Visual states/shots: `<count>`
- Resolution/frame rate: `<width>x<height> at <fps>`
- Approved hard ceiling: `$<ceiling>`
- Durable ledger spend: `$<spent_cost_usd>`
- Finished metadata cost: `$<metadata.actual_cost>`
- Remaining reserved cost: `$0.00`
- Technical delivery: `Passed`
- Automatic rendered grade: `<score/status>`
- Editorial grade: `<score/status or awaiting review>`
- Promotion decision: `<eligible/rejected/awaiting review>`
- Finished record: `Verified`
- Blob video artifact: `Verified`
- Video SHA-256: `<hash>`
- Recovery used: `<No or exact same-job recovery>`
- Full film authorized: `No`
- Finished library: `https://ai-video-gen-nine.vercel.app/finished`
- Temporary infrastructure cleanup: `Verified`
```

### Pilot did not complete

```markdown
## ReelForge user-directed pilot did not complete

- Action ID: `<action_id or not created>`
- Job ID: `<job_id or not created>`
- Title: `<exact title>`
- Spec SHA-256: `<hash or validation failed>`
- Last verified status: `<status>`
- Failure class: `<validation | readiness | authentication | approval | timing | provider | worker | storage | render | unknown>`
- Failure stage: `<stage>`
- Exact current error: `<error>`
- Attempts used: `<attempts>/<max_attempts>`
- Durable ledger spend: `$<amount or unknown>`
- Reserved cost: `$<amount or unknown>`
- Finished record: `<not created/not verified/failed artifact preserved>`
- Recovery attempted: `<what was attempted>`
- Duplicate action/job created: `No`
- Substitute video created: `No`
- Full film authorized: `No`
- Temporary infrastructure cleanup: `Verified`
```

Never soften a pending, failed or rejected run into a successful-sounding summary.

---

## 22. Completion definition

### Technical pilot completion

A user-directed pilot is technically delivered only when:

```text
the exact directed spec validated
AND readiness passed
AND one durable non-spending action was created
AND the operator approved its exact hash and ceiling once
AND that action bound exactly one durable job
AND the same job was dispatched/recovered
AND a real terminal delivery state was recorded
AND /api/finished/{job_id} resolves
AND storage is Blob-backed
AND artifacts.video exists
AND the MP4 is retrievable, hash-verified and decodable
AND the card appears in /finished
AND temporary recovery infrastructure is removed
```

### Editorial completion

Editorial acceptance additionally requires the automatic rendered grade and human editorial grade
required by the spec. Technical delivery does not imply promotion.

### Full-film completion

A user-directed full film is complete only when:

```text
a separately approved directed_full_film action exists
AND its authorization hash binds the exact parent action/job/video hash and five-minute spec
AND the full spec preserves the accepted 0:00–0:45 narration and shots
AND the worker generates only 0:45–5:00
AND the accepted pilot is reused without new pilot spend
AND the concatenated MP4 is duration-checked, decodable and fast-started
AND the full delivery report records both parent and final video hashes
AND a Blob-backed directed-v1-full finished record exists
AND the action page embeds the full video
```

Full-film technical completion does not imply editorial publication approval.

---

## 23. Compact agent checklist

```text
[ ] Fetch latest runbook from main and read it completely
[ ] Treat user narration, claims, shots and thresholds as authoritative
[ ] Fetch live directed schema/template when needed
[ ] Compile/normalize complete directed_longform_v1 JSON
[ ] Measure source-image cadence by asset_key, not by shot-row count
[ ] Require 2–3s still-master turnover and declared unique-master minimum
[ ] Require full 5s motion clips and opening motion window when directed
[ ] POST directed/validate; save normalized spec + spec_sha256 + estimates
[ ] Resolve every validation issue before proposing spend
[ ] GET production-readiness through existing authentication
[ ] POST /api/agent/actions exactly once with normalized inline spec
[ ] Verify title, hash, first-45 scope, estimate, ceiling and expiry
[ ] Save action_id; never expose claim_token
[ ] Send stable /agent/actions?action=<action_id> approval link
[ ] Require one “Approve & render exact pilot” click only
[ ] If approval page is empty, inspect saved action_id; do not create client-side spec
[ ] Verify approval automatically executed, queued and dispatched
[ ] Capture authoritative job_id
[ ] Keep the action page on sanitized incremental events and progress
[ ] Poll public-status; track lease, attempts, spent, reserved and checkpoint
[ ] On timeout, continue same action/job
[ ] On recoverable infrastructure failure, recover same job only
[ ] Verify /api/finished/{job_id} and Blob video artifact
[ ] Verify the action page embeds the same-origin finished-video player and download
[ ] Verify SHA-256, decode, duration, streams and dimensions
[ ] Inspect complete MP4/contact sheet against approved shot plan
[ ] Report automatic grade, editorial grade and promotion separately
[ ] Preserve failed/degraded artifacts without manual conversion
[ ] State clearly that full film is not authorized by the pilot
[ ] When requested, create a separate remaining-film action bound to parent action/job/video hashes
[ ] Verify the full spec preserves every accepted 0:00–0:45 narration and shot row
[ ] Display remaining-window estimate and ceiling; exclude sunk pilot spend
[ ] Verify execution renders only 0:45–5:00 and reuses the frozen pilot
[ ] Verify the Blob-backed directed-v1-full record and final delivery report
[ ] Remove temporary recovery infrastructure
```
