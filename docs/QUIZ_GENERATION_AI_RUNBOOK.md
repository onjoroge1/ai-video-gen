# ReelForge Quiz Generation — AI Execution Runbook

**Status:** Authoritative operating contract  
**Scope:** Creating a new ReelForge quiz using the APIs and production workflow that already exist  
**Repository:** `onjoroge1/ai-video-gen`  
**Production studio:** `https://ai-video-gen-nine.vercel.app`  
**Finished library:** `https://ai-video-gen-nine.vercel.app/finished`  
**Last revised:** 2026-08-30

> **AI instruction:** Read this entire file before attempting to create, repair, validate, or report completion of a quiz. Do not improvise a different production path.

---

## 1. Non-negotiable rules

1. **Use ReelForge itself.** A quiz must be created through the deployed ReelForge API and its existing quiz pipeline.
2. **Do not manufacture a substitute.** Never build a local MP4, manually re-edit an old video, generate a replacement outside ReelForge, or present a mockup as a ReelForge render.
3. **Do not change application code merely to run a quiz.** This runbook documents the currently deployed flow. Code changes require a separate, explicit request.
4. **Use the canonical quiz request:** social format, quiz template, exactly three requested items.
5. **Use durable execution in production.** Creation and rendering are separate API calls. Monitor the real durable job.
6. **Do not claim success until persistence is verified.** A successful render must have a durable record and a playable video artifact in `/finished`.
7. **Fail closed.** Provider quota errors, authentication failures, storage failures, timeouts, or missing artifacts are failures. Report the actual failure; do not create a substitute.
8. **Preserve failed evidence.** Keep the job ID, status, error, cost, and available logs. Never relabel a failed run as complete.
9. **Do not expose credentials.** Never print, commit, paste, or return passwords, session cookies, worker secrets, API keys, Blob credentials, or database URLs.
10. **The final report must identify the real ReelForge job.** Include the job ID, terminal status, actual cost, finished-record verification, and visual-QA result.

---

## 2. Canonical production flow

```text
Authenticate with ReelForge
        ↓
GET /api/production-readiness
        ↓  only when ready=true
POST /api/explainer/generate
        ↓  capture job_id + dispatch_url
Open GET /api/explainer/status/{job_id}
        ↓
POST /api/explainer/dispatch/{job_id}
        ↓
Monitor the SSE stream to a terminal status
        ↓
GET /api/finished/{job_id}
        ↓
GET /api/finished/{job_id}/artifact/video
        ↓
Inspect the actual ReelForge MP4
        ↓
Confirm the card exists at /finished
        ↓
Report completion with evidence
```

The status stream must be opened before dispatch when practical, matching the current ReelForge UI. Creation queues the job; dispatch claims and executes it.

---

## 3. Authentication

Production routes are private. Use one of the authentication mechanisms already supported by ReelForge:

- An authenticated studio session using the signed `reelforge_session` cookie; or
- The existing `X-App-Secret` header for an authorized headless client.

Do not add a public bypass, temporary anonymous render route, or alternate authentication path merely to run a quiz.

Authentication must be reused for all protected requests in the same run, including readiness, job creation, dispatch, status, artifact retrieval, and finished-record verification.

---

## 4. Pre-spend readiness gate

Call:

```http
GET /api/production-readiness
```

Proceed only when the response contains:

```json
{
  "ready": true
}
```

At minimum, verify these existing checks are true:

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

If readiness is false, stop before paid generation. Record the failed checks and report the run as blocked.

---

## 5. Canonical quiz request

Call:

```http
POST /api/explainer/generate
Content-Type: application/json
```

Use this request shape:

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

### Required fields and meaning

- `question`: the quiz **category**, such as `wild animals`; it is not an explainer question.
- `video_format`: must be `social`.
- `short_template`: must be `quiz`.
- `n_items`: must be `3`.
- `voice`: use the requested ReelForge voice; `echo` is the established default.
- `operator_direction`: may clarify the creative intent but must remain subordinate to the deployed quiz contract.

Do not send internal directed-pilot, controlled-pilot, or controlled-production fields.

---

## 6. Queue response and cost boundary

A production response should provide a durable job, for example:

```json
{
  "job_id": "abcd1234",
  "durable": true,
  "dispatch_url": "/api/explainer/dispatch/abcd1234"
}
```

Immediately persist the following in the run record:

- `job_id`
- `dispatch_url`
- submission time
- request payload with secrets excluded
- readiness response

Do not treat a queued job as a completed video.

---

## 7. Status monitoring and dispatch

Open the existing SSE stream:

```http
GET /api/explainer/status/{job_id}
```

Then call the returned dispatch URL:

```http
POST /api/explainer/dispatch/{job_id}
```

Monitor all status and log events until the stream closes at a terminal state.

### Successful terminal states

- `done`: render and archive succeeded.
- `degraded`: a render exists, but one or more quality gates produced warnings. Preserve and report every degraded reason; do not describe it as a clean pass.

### Unsuccessful terminal states

- `error`
- `storage_error`
- `awaiting_review`
- `human_rejected`
- `format_acknowledgement_required`
- `format_rejected`
- `pilot_failed`

A timeout is not success. After a timeout, query the durable status again or use the existing recovery process; never invent the outcome.

---

## 8. Existing ReelForge quiz pipeline

The request routes to the deployed quiz pipeline only when both conditions are true:

```text
video_format == "social"
short_template == "quiz"
```

The existing pipeline is responsible for:

1. Generating three quiz items.
2. Ordering the rounds Medium → Hard → Expert.
3. Fact-checking answers and facts.
4. Selecting fair, recognizable items whose difficulty comes from confusability rather than obscurity.
5. Generating habitat/reveal image pairs.
6. Producing matching black-silhouette clues from the same scene.
7. Applying the deployed Quiz V2.3 font and difficulty labels.
8. Giving each round the deployed 2.4-second search window.
9. Generating narration, captions, countdown sounds, answer dings, and music.
10. Running visual QA for difficulty, readability, identity, anatomy, and pose continuity.
11. Producing the silhouette-to-answer transformation.
12. Assembling the final vertical MP4.
13. Returning the single mascot-free variant `a`.

An AI operator must not reproduce these stages independently outside ReelForge.

---

## 9. Durable persistence and `/finished`

When rendering completes, ReelForge archives the output through its existing finished-artifact path. Production persistence must use Blob and Postgres; local `/tmp` files are temporary worker material only.

Verify the durable record:

```http
GET /api/finished/{job_id}
```

Required evidence:

```text
id == job_id
format == "short-quiz"
status == "done" or explicitly "degraded"
storage == "blob"
artifacts.video exists
metadata.question matches the requested category
```

Verify the playable artifact:

```http
GET /api/finished/{job_id}/artifact/video
```

Verify the downloadable artifact when needed:

```http
GET /api/finished/{job_id}/artifact/video?download=true
```

Finally confirm the video appears at:

```text
https://ai-video-gen-nine.vercel.app/finished
```

The job ID is the authoritative identifier for the finished card.

---

## 10. Final video acceptance checklist

Inspect the MP4 produced by ReelForge, not a proxy or reconstruction.

### Structural checks

- [ ] Exactly three quiz rounds
- [ ] Medium → Hard → Expert progression
- [ ] Approximately 2.4 seconds of playable search time per round
- [ ] Vertical video with working audio
- [ ] No standalone intro that delays the first clue
- [ ] No dead outro after the final payoff
- [ ] Final frame returns smoothly toward the opening frame

### Visual checks

- [ ] Current Quiz V2.3 typography is present
- [ ] Difficulty labels are present and correct
- [ ] Timer/countdown is readable at phone size
- [ ] Each silhouette is visible but not instantly trivial
- [ ] Each reveal unmistakably matches the clue and answer
- [ ] Animal anatomy is acceptable
- [ ] Hard and Expert rounds are difficult because of confusables, pose, distance, and framing—not obscure species
- [ ] No mascot, robot, host, presenter, character badge, performer, or mascot-derived overlay appears on any frame

### Audio checks

- [ ] Narration begins with gameplay rather than a preamble
- [ ] Narration does not overlap the wrong reveal
- [ ] Countdown ticks align with the active search window
- [ ] Reveal dings align with answer appearances
- [ ] Final CTA narration is not clipped
- [ ] Music does not overpower the voice

### Persistence checks

- [ ] Finished record exists in Postgres
- [ ] Video artifact exists in Blob
- [ ] `/api/finished/{job_id}` resolves
- [ ] Video artifact plays through the finished API
- [ ] Card appears in `/finished`

---

## 11. Failure handling

### Provider quota or authentication failure

- Stop the run.
- Preserve the real provider error.
- Record `$0.00` spend only when the job record confirms no spend.
- Do not create a local replacement.
- Do not say the video is complete.

### Render or media failure

- Preserve the job ID, status events, error, checkpoint information, and any paid artifacts.
- Use only the existing durable retry or recovery path when the job status permits it.
- Do not begin an unrelated second render unless the user explicitly requests a new attempt.

### Storage failure

- Treat the run as incomplete even if a temporary MP4 existed.
- Do not claim the video is in `/finished` until the finished record and Blob artifact are verified.

### Degraded quality

- Preserve the video in `/finished` if ReelForge archived it.
- Report every degraded reason.
- Distinguish “render completed” from “editorially accepted.”

---

## 12. Prohibited shortcuts

The following actions violate this runbook:

- Making a quiz with a local editor, Python, FFmpeg, Canva, or another video service and presenting it as the ReelForge output.
- Downloading an old quiz and manually covering, cropping, replacing, or rebuilding its elements without an explicit request for an external edit.
- Uploading a manually edited video into `/finished` as though ReelForge generated it.
- Skipping `/api/production-readiness`.
- Calling a generic explainer or directed-video route instead of the quiz route.
- Treating `POST /api/explainer/generate` as completion without dispatching the durable job.
- Reporting success from logs alone without verifying `/api/finished/{job_id}` and the video artifact.
- Using a temporary public bypass or modifying application authentication to avoid signing in.
- Exposing credentials in source code, documentation, logs, artifacts, or chat.

---

## 13. Required final report format

A successful report must use this structure:

```markdown
## ReelForge quiz completed

- Job ID: `<job_id>`
- Terminal status: `done` or `degraded`
- Category: `<category>`
- Quiz contract: `rapid_reveal_v2_3`
- Rounds: `3`
- Primary variant: `a`
- Mascot present: `No`
- Measured duration: `<seconds>`
- Actual ReelForge cost: `$<amount>`
- Finished record: `Verified`
- Blob video artifact: `Verified`
- Visual QA: `Passed` or `Failed — <reasons>`
- Finished library: `https://ai-video-gen-nine.vercel.app/finished`
```

If the run fails, use:

```markdown
## ReelForge quiz did not complete

- Job ID: `<job_id or not created>`
- Last verified status: `<status>`
- Failure stage: `<stage>`
- Error: `<actual error>`
- Confirmed spend: `$<amount or unknown>`
- Finished record: `Not created` or `Not verified`
- Substitute video created: `No`
```

Never soften a failed run into a successful-sounding summary.

---

## 14. Completion definition

A quiz is complete only when all of the following are true:

```text
The production readiness gate passed
AND a durable ReelForge job was created
AND the job was dispatched through the existing API
AND the job reached done or explicitly degraded
AND /api/finished/{job_id} returned the durable record
AND the Blob video artifact was retrievable and playable
AND the actual MP4 passed the stated visual and audio inspection
AND the video appeared in /finished
```

Anything less is a blocked, failed, pending, or degraded attempt—not a completed ReelForge quiz.
