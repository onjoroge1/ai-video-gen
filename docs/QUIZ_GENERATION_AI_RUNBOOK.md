# ReelForge Quiz Generation — AI Execution Runbook

**Status:** Authoritative operating contract  
**Runbook version:** 2.0 — validated production and recovery flow  
**Scope:** Creating, recovering, validating, and reporting a ReelForge quiz using the existing APIs and durable pipeline  
**Repository:** `onjoroge1/ai-video-gen`  
**Production studio:** `https://ai-video-gen-nine.vercel.app`  
**Finished library:** `https://ai-video-gen-nine.vercel.app/finished`  
**Last revised:** 2026-08-30

> **AI instruction:** Read this entire file before attempting to create, recover, validate, or report completion of a quiz. Execute the workflow; do not improvise a different production path and do not stop at a plan.

---

## 0. Automatic-execution directive

When the user supplies this document, links to it, or says **“run/create/render a quiz”**, treat that as authorization to execute one bounded ReelForge quiz immediately.

Do not ask the user to restate information already defined here. Resolve missing inputs as follows:

```text
category          = user-supplied category, otherwise "wild animals"
rounds            = 3
video_format       = "social"
short_template     = "quiz"
voice              = "echo"
quiz contract      = deployed Quiz V2.4 / rapid_reveal_v2_4
mascot             = prohibited
normal compute     = production durable ReelForge worker
recovery compute   = same durable job on a trusted higher-resource worker, only if required
finished location  = /finished
```

The expected behavior is:

1. Fetch the current `main` version of this runbook.
2. Authenticate using an existing ReelForge mechanism.
3. Run readiness.
4. Create one durable production job.
5. Dispatch and monitor it.
6. Recover that **same job** if the normal serverless worker fails.
7. Verify the actual Blob-backed video and `/finished` record.
8. Inspect the MP4.
9. Report the real result with the real job ID.
10. Remove any temporary recovery harness.

Do not respond with “I can run it” or merely describe the workflow. Run it during the current task.

---

## 1. Non-negotiable rules

1. **Use ReelForge itself.** A quiz must originate from the deployed ReelForge API and execute the repository’s existing quiz pipeline.
2. **Never manufacture a substitute.** Do not build a local MP4, manually re-edit an older quiz, generate a replacement in another service, or upload an externally assembled video as a ReelForge render.
3. **Do not modify `main` merely to run a quiz.** The normal workflow requires no application-code change.
4. **A temporary recovery harness is allowed only when compute or tool access requires it.** It must live on an isolated QA branch, target one exact job, expose no reusable public renderer, never be merged, and be reset or deleted after evidence is captured.
5. **Use the canonical request.** Social format, quiz template, three rounds, mascot-free.
6. **Use durable execution.** Creation, dispatch, provider stages, local assembly, Blob persistence, and `/finished` finalization are one durable job lifecycle.
7. **One user request means one authoritative job.** Once provider spend or paid artifacts exist, recover that job instead of creating another one.
8. **Do not claim success from a queued job, a completed HTTP request, provider logs, or a temporary local MP4.** Success requires a durable `/finished` record and playable video artifact.
9. **Fail closed but diagnose accurately.** Provider failures, worker failures, storage failures, and editorial degradation are different conditions. Do not mislabel one as another.
10. **Preserve evidence.** Keep the job ID, request, readiness result, status history, attempts, leases, costs, errors, finished record, artifact hash, and QA findings.
11. **Do not expose credentials.** Never print, commit, paste, return, or include passwords, session cookies, API keys, worker secrets, Blob credentials, database URLs, or protection-bypass secrets in logs or documentation.
12. **A `degraded` render is a completed artifact, not a clean editorial pass.** Preserve it in `/finished`, inspect it, and report the distinction.
13. **Never state that an account is unfunded or inactive based on a stale or different job.** Provider conclusions must be tied to the current job and current timestamp.

---

## 2. Validated reference result

The recovery path in this document was validated with this ReelForge job:

```text
job_id                    = ec78c4e8
category                  = wild animals
terminal status           = degraded
format                    = short-quiz
storage                   = blob
rounds                    = 3
measured duration         = 10.833333 seconds
video                     = H.264, 1080x1920, 30 fps
sound                     = AAC
video size                = 4,496,944 bytes
durable ledger spend      = $0.424
finished metadata cost    = $0.405
video sha256              = 43b62645f50ae41531982e80147365ee523bd4adaebb61ad448d4a2b032dd97c
finished record           = verified
mascot                     = absent in sampled frames
```

This job is a reference showing that the workflow and recovery method work. **Do not reuse this job for a new user request.** Create a new durable job and use its new ID.

---

## 3. Canonical production flow

```text
Fetch this runbook from main
        ↓
Authenticate with production ReelForge
        ↓
GET /api/production-readiness
        ↓  only when ready=true
POST /api/explainer/generate
        ↓  capture job_id + dispatch_url
Open GET /api/explainer/status/{job_id}
        ↓
POST /api/explainer/dispatch/{job_id}
        ↓
Monitor SSE + durable job state
        ↓
Normal terminal state?
   ↙ yes              no ↘
verify /finished      classify failure
                     and recover SAME job
        ↓                    ↓
GET /api/finished/{job_id} ←─┘
        ↓
GET /api/finished/{job_id}/artifact/video?download=true
        ↓
Probe + inspect actual ReelForge MP4
        ↓
Confirm card exists at /finished
        ↓
Clean up temporary recovery infrastructure
        ↓
Report completion or failure with evidence
```

Creation queues the job. Dispatch claims and executes it. The status stream should be opened before dispatch when practical, matching the current ReelForge UI.

---

## 4. Authentication

Production routes are private. Use one of the mechanisms ReelForge already supports:

- An authenticated studio session using the signed `reelforge_session` cookie; or
- The existing `X-App-Secret` header for an authorized headless client.

### Preferred automation order

1. Use `X-App-Secret` when the connected execution environment already has it.
2. Otherwise use an existing authenticated ReelForge browser session.
3. If the AI’s orchestration tool cannot send the required authenticated POST request but a Vercel preview has the authorized environment, use a **temporary preview-only bridge** that calls the unchanged production API server-side.

A temporary bridge must:

- Exist only on a disposable QA branch.
- Check `VERCEL_ENV == "preview"`.
- Check the exact expected branch name.
- Use an unguessable route.
- Be restricted to one job or one bounded start operation.
- Call the normal production endpoints; it must not implement another renderer.
- Return no credentials.
- Never be merged into `main`.
- Be removed by force-resetting or deleting the QA branch after the run.

Do not add an anonymous production route, broad authentication bypass, or reusable public render endpoint.

Authentication must be reused for readiness, generation, dispatch, monitoring, finished-record retrieval, and artifact retrieval.

---

## 5. Pre-spend readiness gate

Call:

```http
GET /api/production-readiness
```

Proceed only when:

```json
{
  "ready": true
}
```

At minimum, verify:

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

### Media-binary nuance

Do not independently fail readiness merely because the detailed response says `ffprobe.found: false`. ReelForge can report:

```json
{
  "media": {
    "ready": true,
    "missing": ["ffprobe"],
    "probe_source": "ffmpeg-fallback"
  }
}
```

When top-level `ready`, `checks.media_binaries`, and `media.ready` are true, the ffmpeg fallback is an accepted deployed configuration.

### Provider-readiness limitation

`ready: true` proves configuration, media, authentication, Postgres, Blob, and worker readiness. It does **not** make a live Anthropic or OpenAI request.

Never infer current provider funding or quota from an old job. Provider diagnosis must follow these rules:

1. Match the provider response to the **current job ID** and a current timestamp.
2. If the current job logs show HTTP 200 responses from Anthropic/OpenAI, the provider is active for that job even if an earlier job reported a usage-limit error.
3. Quote the exact current error; do not paraphrase it as “no money” unless the current provider explicitly says so.
4. A stale provider error is not a current blocker.
5. Do not create a second full job merely to test billing after the first job has already incurred spend.

If readiness fails, stop before paid generation and report the failed checks.

---

## 6. Canonical quiz request

Call:

```http
POST /api/explainer/generate
Content-Type: application/json
```

Use this request shape, replacing only the category when the user supplied one:

```json
{
  "question": "wild animals",
  "duration_sec": 15,
  "voice": "echo",
  "style": "engaging and scientific",
  "image_guidance": "",
  "fact_check": true,
  "video_format": "social",
  "speech_bubble": false,
  "i2v": false,
  "motion_mode": null,
  "series": "",
  "short_template": "quiz",
  "n_items": 3,
  "operator_direction": "Create three fair, broadly recognizable wild-animal habitat rounds ordered MEDIUM, HARD, EXPERT. Difficulty must come from plausible confusables, pose, framing, and habitat—not obscure species. Preserve the deployed Quiz V2.3 typography, difficulty labels, timer, transformation reveal, sound design, and seamless loop. Do not include a mascot, robot, host, presenter, character badge, or performer anywhere in the quiz.",
  "story_format": "standard_explainer"
}
```

### Required contract

- `question` is the category, not an explainer question.
- `video_format` must be `social`.
- `short_template` must be `quiz`.
- `n_items` must be `3`.
- `voice` defaults to `echo`.
- `operator_direction` can clarify intent but cannot override the deployed quiz contract.
- Do not send directed-pilot, controlled-pilot, controlled-production, approval, or paid-authorization internals.

### Duplicate-job rule

Create one job. Once the response contains a job ID, that ID remains authoritative through recovery. Do not silently issue another `generate` call because dispatch timed out, the worker crashed, or the job became `storage_error`.

A replacement job may be created only when the first request never produced a job ID, or when it terminally failed before any provider stage or spend and recovery is impossible. Report both IDs if a replacement is unavoidable.

---

## 7. Queue response and run record

A successful create call should return approximately:

```json
{
  "job_id": "abcd1234",
  "durable": true,
  "dispatch_url": "/api/explainer/dispatch/abcd1234"
}
```

Immediately record:

- `job_id`
- `dispatch_url`
- category
- exact request without secrets
- submission timestamp
- readiness response
- production deployment/alias used
- initial durable status
- `max_cost_usd`

A queued job is not a video.

---

## 8. Dispatch and fresh status monitoring

Open:

```http
GET /api/explainer/status/{job_id}
```

Then call:

```http
POST /api/explainer/dispatch/{job_id}
```

### Monitor the durable job, not only the HTTP request

A dispatch request can time out, disconnect, or return no body while the worker continues. The authoritative state is the durable job in Postgres and the `/finished` record.

Track at least:

```text
status
error
attempts
max_attempts
lease_owner
lease_expires_at
updated_at
spent_cost_usd
reserved_cost_usd
max_cost_usd
finished record presence
```

### Avoid stale GET responses

SSE is preferred. If polling a GET endpoint through a cacheable proxy or temporary bridge, add both:

```text
Cache-Control: no-cache
?ts=<current-unix-milliseconds>
```

Do not repeatedly trust a response whose `Date`, `updated_at`, or body does not change while other evidence shows progress.

### Avoid concurrent workers

- `claimed: false` is not automatically a failure.
- It usually means another worker owns an active lease or the job is not in a claimable status.
- Inspect `lease_owner` and `lease_expires_at`.
- Do not fire multiple concurrent dispatch requests against the same active lease.
- Poll until the worker finishes or the lease expires.

### Terminal statuses

Completed artifact states:

- `done`
- `degraded`

Incomplete or blocked states:

- `error`
- `storage_error`
- `awaiting_review`
- `human_rejected`
- `format_acknowledgement_required`
- `format_rejected`
- `pilot_failed`

`degraded` means the video can be complete and archived, but it requires explicit editorial review.

---

## 9. Existing ReelForge quiz pipeline

The request reaches the quiz renderer only when:

```text
video_format == "social"
short_template == "quiz"
```

The existing pipeline owns the creative and production stages:

1. Generate three items.
2. Order Medium → Hard → Expert.
3. Fact-check answers and facts.
4. Choose familiar but plausibly confusable animals.
5. Generate habitat/reveal image pairs.
6. Derive matching silhouette clues.
7. Apply Quiz V2.3 typography and labels.
8. Use the deployed 2.4-second search window.
9. Generate narration, captions, ticks, dings, and music.
10. Grade visual difficulty, readability, identity, anatomy, and continuity.
11. Render silhouette-to-answer transformations.
12. Assemble the vertical MP4.
13. Return the single mascot-free variant `a`.
14. Persist paid stages and final artifacts durably.
15. Create the `/finished` record.

An AI operator must not reproduce these stages in a separate editing pipeline.

---

## 10. Recovery decision tree

Use this decision tree before declaring failure.

```text
queued
  └─ dispatch once

processing + active lease
  └─ poll; do not start another worker

processing + expired lease
  └─ dispatch/recovery worker may reclaim SAME job

serverless request timeout
  └─ inspect durable state; timeout is not terminal

Vercel OOM log
  └─ stop identical serverless retries; preserve job; use higher-resource worker

storage_error + "No space left on device"
  └─ requeue SAME job; run existing durable worker on higher-disk worker

done/degraded + /finished record
  └─ retrieve, inspect, report

done/degraded without /finished record
  └─ incomplete persistence; do not claim delivery

error
  └─ inspect exact current error, provider stages, attempts, and recoverability
```

---

## 11. Known worker challenges and exact responses

### 11.1 Vercel serverless out-of-memory

Known runtime message:

```text
Vercel Runtime Error: instance was killed because it ran out of available memory
```

Response:

1. Keep the same job ID.
2. Check current provider calls and durable spend.
3. Wait for the lease to expire if the dead worker still owns it.
4. Do not keep burning attempts on the identical serverless host.
5. Move the same durable job to the higher-resource recovery procedure in Section 12.

A serverless OOM is not an Anthropic failure and is not evidence that the video cannot be made.

### 11.2 Ephemeral disk exhaustion

Known durable state and error:

```text
status = storage_error
error  = [Errno 28] No space left on device
```

Response:

1. Confirm `reserved_cost_usd` and completed provider stages.
2. Requeue the same immutable job through the existing durable store:

```python
store = durable_execution.PostgresStore()
store.requeue(job_id, allowed_statuses=("storage_error",))
```

3. Execute the existing worker on a host with more disk and memory:

```python
asyncio.run(app._run_durable_explainer_worker(job_id))
```

4. Verify that completed stages are reused and that the final Blob artifacts are created.

Do not create a new quiz to work around local disk exhaustion.

### 11.3 Stale lease after a killed worker

A killed serverless function may leave:

```text
status = processing
lease_owner = <old worker>
lease_expires_at = <future timestamp>
```

Response:

- Poll through the lease expiry during the current task.
- Do not modify the lease manually while it is valid.
- After expiry, the store’s normal claim logic can reclaim the job.
- Preserve enough attempts for a higher-resource recovery worker.

### 11.4 Attempt exhaustion

Each successful claim increments `attempts`, even when resuming a durable job.

- Do not blindly retry identical compute after a repeatable OOM or disk failure.
- Move to the recovery worker before `attempts == max_attempts`.
- If attempts are exhausted, do not create a replacement job without reporting the failed job and its spend.

### 11.5 Python module-resolution collision in one-off workers

A recovery script inside `scripts/` can import an unrelated installed module named `durable_execution` because `scripts/` becomes `sys.path[0]`.

Before importing repository modules, prepend the repository root:

```python
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import durable_execution
```

Without this, a recovery worker can fail with:

```text
ModuleNotFoundError: No module named '_durable_execution_legacy'
```

That is an execution-environment error, not a ReelForge pipeline error.

---

## 12. Validated higher-resource recovery procedure

Use this only after the normal production worker encounters repeatable memory or ephemeral-disk limits.

### Goal

Run the **same repository worker** against the **same durable production job**, Postgres ledger, Blob checkpoints, and `/finished` table—only changing the compute host.

### Validated host

A Vercel build machine was successfully used with:

```text
4 CPU cores
8 GB memory
repository checkout
Vercel environment variables
shared production Postgres and Blob resources
```

A trusted CI runner or dedicated render worker with equivalent credentials and resources is also acceptable.

### Temporary-branch requirements

1. Create a QA branch from the latest `main`.
2. Do not modify creative, quiz, renderer, API, or persistence logic.
3. Add only an exact-job recovery script and temporary build/runner invocation.
4. Hardcode or pass exactly one job ID.
5. Requeue only a documented recoverable state such as `storage_error`.
6. Call the repository’s existing `app._run_durable_explainer_worker(job_id)`.
7. Do not create a second job.
8. Monitor build logs and the durable job simultaneously.
9. Verify `/finished` after the worker exits.
10. Force-reset or delete the QA branch after evidence is captured.

### Minimal recovery algorithm

```python
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import durable_execution

JOB_ID = "<exact-eight-character-job-id>"
store = durable_execution.PostgresStore()
row = store.get_job(JOB_ID)

if row["status"] == "storage_error":
    store.requeue(JOB_ID, allowed_statuses=("storage_error",))

import app
asyncio.run(app._run_durable_explainer_worker(JOB_ID))

row = store.get_job(JOB_ID)
finished = store.finished_get(JOB_ID)
assert row["status"] in {"done", "degraded"}
assert finished
assert (finished.get("artifacts") or {}).get("video")
```

### Important build-worker behavior

- A Vercel deployment can remain `BUILDING` while the recovery script is rendering. Monitor the job and build logs; deployment state alone is not the quiz state.
- A build deployment can end `ERROR` because the recovery script deliberately exits nonzero after an unsuccessful render. The durable job remains authoritative.
- The higher-resource worker must use the same production database and Blob store. Test store initialization without printing credentials.
- Use `PYTHONUNBUFFERED=1` so progress reaches build logs.
- Completed provider stages should be reused from durable artifacts rather than purchased again.

---

## 13. Durable persistence and `/finished`

When rendering completes, ReelForge must archive through its normal finished-artifact path. `/tmp` or build-machine files are temporary and never authoritative.

Verify:

```http
GET /api/finished/{job_id}
```

Required evidence:

```text
id == job_id
format == "short-quiz"
status == "done" or "degraded"
storage == "blob"
artifacts.video exists
metadata.question matches category
```

Retrieve the actual video:

```http
GET /api/finished/{job_id}/artifact/video?download=true
```

Confirm the card exists at:

```text
https://ai-video-gen-nine.vercel.app/finished
```

The finished record and video artifact must both use the authoritative job ID.

### Generic script endpoint is not authoritative for quizzes

Do **not** reject a completed quiz solely because:

```http
GET /api/explainer/script/{job_id}
```

returns:

```json
{
  "detail": "Script not yet generated"
}
```

The generic explainer script-materialization endpoint may not expose the quiz state even after the quiz is finalized. For completion, trust the durable job, finished record, artifacts, transcript/SRT, quiz-control artifact, and the actual MP4.

---

## 14. Cost accounting

ReelForge may expose two related figures:

- `generation_jobs.spent_cost_usd`: durable ledger spend, including all durable provider stages and conservative accounting.
- `finished_videos.metadata.actual_cost`: pipeline-reported creative/render cost.

These can differ slightly. Do not silently choose one or claim they are identical.

Report both when available:

```text
durable ledger spend   = $X.XXXX
finished metadata cost = $Y.YYY
```

Use durable `spent_cost_usd` as the authoritative total job-ledger figure. Also report `reserved_cost_usd`; it should be zero at finalization.

Do not claim `$0.00` unless the current durable job confirms it.

---

## 15. Technical and editorial validation

Inspect the exact Blob-backed MP4, not a reconstruction.

### Artifact-integrity checks

- Download succeeds through the finished API.
- File size is greater than 100 KB.
- Compute SHA-256 and compare it with `artifacts.video.sha256`.
- MP4 decodes without errors.
- Video stream exists.
- Audio stream exists.
- Portrait dimensions are present.
- Duration is plausible for three rounds.

Reference probe command:

```bash
ffprobe -v error \
  -show_entries format=duration,size:stream=index,codec_type,codec_name,width,height,r_frame_rate \
  -of json quiz.mp4
```

### Visual evidence

Create both:

```text
contact sheet at approximately 2 frames/second
individual samples at approximately 4 frames/second
```

Review the entire sampled timeline for:

- Exactly three complete rounds.
- Medium → Hard → Expert progression.
- First clue visible at frame zero.
- Approximately 2.4 seconds of playable search time per round.
- Current Quiz V2.3 typography.
- Correct difficulty labels.
- Readable countdown.
- Clue/reveal identity match.
- Acceptable animal anatomy.
- Fair silhouette difficulty.
- No mascot, robot, presenter, host, character badge, performer, or mascot-derived overlay on any sampled frame.
- Final payoff and loop back toward frame zero.

Source-code absence of mascot functions is useful evidence, but it does not replace rendered-frame inspection.

### Audio evidence

Check:

- Narration begins with gameplay, not a preamble.
- Narration maps to the correct round.
- Countdown ticks align with search windows.
- Dings align with reveals.
- CTA is not clipped.
- Music does not mask speech.
- No unintended long silence.

### Round-count verification

Prefer the actual rendered video, transcript/SRT, quiz-control artifact, and finished metadata. Do not make the generic script endpoint a hard dependency.

---

## 16. Interpreting `degraded`

A quiz with:

```text
status = degraded
finished record exists
Blob video artifact exists
video is playable
```

is a **completed render deliverable**. It is not a clean editorial pass.

If `degraded_reasons` is missing or empty:

1. Do not invent reasons.
2. Inspect the video and contact sheet.
3. Report observed creative weaknesses separately.
4. State that the backend marked it degraded without exposing a reason array.

Use these distinct conclusions:

```text
Technical delivery: passed/failed
Editorial acceptance: passed/failed/degraded
```

A degraded video can satisfy the user’s request for a finished test video while still requiring creative revision.

---

## 17. Failure handling

### Current provider failure

- Confirm it belongs to the current job and timestamp.
- Preserve the exact message.
- Inspect whether any current provider calls succeeded.
- Do not characterize stale errors as current account status.
- Do not manufacture a replacement.

### Request timeout

- Inspect durable state.
- Continue polling during the current task.
- Do not create another job.

### OOM

- Preserve job ID and provider stages.
- Wait for lease expiry.
- Move the same job to the higher-resource recovery worker.

### Disk/storage error

- Confirm exact error.
- Requeue only through the durable store’s allowed-status mechanism.
- Run the same worker on more capable compute.
- Verify Blob and `/finished` before reporting success.

### Render or media failure

- Preserve stage evidence, checkpoint, attempts, costs, and error.
- Use only the existing durable recovery path.
- Do not manually rebuild the video.

### Degraded quality

- Preserve the artifact in `/finished`.
- Inspect it.
- Distinguish completed delivery from editorial approval.

---

## 18. Prohibited shortcuts

The following violate this runbook:

- Making a quiz with local Python, FFmpeg, Canva, another video service, or a manual editor and presenting it as ReelForge output.
- Downloading an old quiz and covering, cropping, replacing, or rebuilding its elements without an explicit external-edit request.
- Uploading a manually edited MP4 into `/finished` as though ReelForge generated it.
- Skipping readiness.
- Calling a generic explainer, directed-video, or pilot route instead of the quiz route.
- Treating `generate` as completion without dispatching.
- Creating repeated jobs because dispatch timed out.
- Running concurrent workers against one active lease.
- Burning all durable attempts on the same known-bad serverless compute.
- Reporting provider insolvency from a stale job.
- Treating missing `ffprobe` as fatal when ReelForge explicitly reports a ready ffmpeg fallback.
- Treating the generic script endpoint as the sole completion check.
- Reporting `degraded` as a clean pass.
- Leaving temporary QA routes, workflows, build commands, or branches deployed after the run.
- Merging recovery scaffolding into `main`.
- Exposing credentials.

---

## 19. Temporary-infrastructure cleanup

After the MP4 and evidence are secured:

1. Preserve the production `/finished` record and Blob artifacts.
2. Preserve the workflow artifact/contact sheet long enough for review.
3. Force-reset or delete every temporary QA branch to current `main`.
4. Confirm temporary routes no longer exist.
5. Confirm temporary `vercel.json` build commands are not on `main`.
6. Confirm `main` contains no recovery script or public bridge.
7. Do not delete the finished quiz unless the user explicitly requests deletion and a supported API exists.

Cleanup is part of completion.

---

## 20. Required final report

### Completed render

```markdown
## ReelForge quiz completed

- Job ID: `<job_id>`
- Terminal status: `done` or `degraded`
- Category: `<category>`
- Quiz contract: `rapid_reveal_v2_4`
- Rounds: `3`
- Primary variant: `a`
- Mascot present: `No`
- Measured duration: `<seconds>`
- Resolution/frame rate: `<width>x<height> at <fps>`
- Durable ledger spend: `$<spent_cost_usd>`
- Finished metadata cost: `$<metadata.actual_cost>`
- Remaining reserved cost: `$0.00`
- Finished record: `Verified`
- Blob video artifact: `Verified`
- Video SHA-256: `<hash>`
- Technical delivery: `Passed`
- Editorial acceptance: `Passed` or `Degraded — <observed reasons>`
- Recovery used: `No` or `<normal worker / stale-lease recovery / high-resource durable worker>`
- Finished library: `https://ai-video-gen-nine.vercel.app/finished`
- Temporary infrastructure cleanup: `Verified`
```

### Incomplete render

```markdown
## ReelForge quiz did not complete

- Job ID: `<job_id or not created>`
- Last verified status: `<status>`
- Failure class: `<provider | authentication | worker OOM | disk | storage | media | unknown>`
- Failure stage: `<stage>`
- Exact current error: `<error>`
- Attempts used: `<attempts>/<max_attempts>`
- Durable ledger spend: `$<amount or unknown>`
- Reserved cost: `$<amount or unknown>`
- Finished record: `Not created` or `Not verified`
- Recovery attempted: `<what was attempted>`
- Substitute video created: `No`
- Temporary infrastructure cleanup: `Verified`
```

Never soften a failed run into a successful-sounding summary.

---

## 21. Completion definition

### Technical render completion

A ReelForge quiz is technically delivered only when:

```text
readiness passed
AND one durable production job was created
AND the job was dispatched
AND any recovery reused that same job
AND terminal status is done or degraded
AND /api/finished/{job_id} resolves
AND storage is blob
AND artifacts.video exists
AND the video is retrievable and decodable
AND the card appears in /finished
AND temporary recovery infrastructure is removed
```

### Editorial completion

Editorial acceptance additionally requires the visual and audio checklist to pass. A `degraded` artifact can be technically delivered while editorial acceptance remains degraded.

Anything less must be labeled blocked, pending, failed, or degraded with the exact evidence.

---

## 22. Compact agent checklist

Use this when executing under time pressure:

```text
[ ] Fetch latest runbook from main
[ ] Resolve category; default wild animals
[ ] Authenticate without exposing secrets
[ ] GET production-readiness; respect media.ready fallback
[ ] POST generate once with social + quiz + n_items=3
[ ] Save job_id and dispatch_url
[ ] Open status SSE
[ ] POST dispatch once
[ ] Poll fresh durable state; track lease, attempts, spent, reserved
[ ] If timeout: inspect state, do not create another job
[ ] If active lease: poll
[ ] If expired lease: reclaim same job
[ ] If OOM repeats: move same job to high-resource worker
[ ] If storage_error/Errno 28: durable requeue, then high-resource worker
[ ] Prepend repo root in recovery script before importing durable_execution
[ ] Stop before max attempts are exhausted
[ ] Verify /api/finished/{job_id}
[ ] Verify Blob video artifact and SHA-256
[ ] Do not require generic script endpoint for quiz completion
[ ] Probe MP4
[ ] Generate contact sheet + 4 fps samples
[ ] Verify 3 rounds and no mascot
[ ] Review audio and loop
[ ] Report ledger cost and metadata cost separately
[ ] Label degraded honestly
[ ] Reset/delete all temporary QA branches and routes
```
