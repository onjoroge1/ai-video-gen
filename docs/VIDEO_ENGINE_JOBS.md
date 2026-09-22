# Connected local-media engine jobs

This follow-on to PR124 connects its optional runtimes to the **existing**
`generation_jobs`, `generation_stages`, `generation_artifacts`, `finished_videos`
and `DurableRuntime.finalize` path. There is no second scheduler, login, asset
library or publishing service. Read `AGENTS.md` for paid operations and
`VIDEO_ENGINE_WORKBENCH.md` for the installation baseline.

## Actual scope

| Engine | Connected v1 behavior | Not included |
|---|---|---|
| MoneyPrinterTurbo | Reuse the audio from a delivered source; assemble ordered delivered material videos using upstream `combine_videos` / `generate_video`; archive a new portrait video | Script generation, footage search, TTS, random music, auto publishing |
| Motion Canvas | Render a reviewed `motion_scene` storyboard through an authored before/change/after template and actual headless Motion Canvas PNG export, then encode with FFmpeg | Arbitrary model-written JavaScript, automatic illustration generation, mixed-engine long-form assembly |
| OpenShorts | Run upstream `cut_clip` on an explicit source span, preserve the full frame with contain/pad, rebase existing SRT cues, archive a child video | AI moment selection, face tracking, transcription, automatic cropped composition |

The database provider-cost ceiling is exactly **$0**, not a promise of free
compute, hosting, disk or bandwidth. Engine child processes receive local file
paths, not DB/Blob/provider credentials. The Python adapters have a network
tripwire and use selected rendering functions rather than launching upstream
apps; browser resource requests are restricted to the temporary loopback server.
These are application restrictions, **not a container-level security sandbox**.
Run workers under a least-privilege OS user with outbound restrictions. Do not
extend them to providers without the existing immutable paid-approval contract.
The studio session authorizes a local-media queue operation directly; no new
paid action or second paid-approval system is introduced.

## Operator flow

Open `/video-engine-jobs.html` from the studio or the **Remix with video engines**
action on a Finished Videos detail. Select a method, source ID, output title and
source-rights confirmation. For OpenShorts choose a start/end span. For MPT enter
ordered material video IDs. For Motion Canvas import an exported storyboard and
supply a narration-source video or explicitly choose a silent scene.

Click **Queue durable render**. The returned job ID remains stable across retries
of the same request. The browser reconnects to its last job ID after reload; it
does not regenerate media or create another job automatically. A dispatch on an
API host lacking that runtime reports **worker_required**, retaining the queued
job for the dedicated worker. It does not claim a render started.

Completed output, thumbnail, provenance and optional storyboard/captions use the
normal `/api/finished/{id}/artifact/{kind}` routes. The source is never modified.
`done` means technical delivery; `editorial_status=needs_review` and
`publishable=false` remain explicit. No retention/quality success is invented.
Captions are delivered as SRT sidecars, not newly transcribed or burned in.

## API contract (studio session required)

`GET /api/video-engines` reports runtime readiness **on the API host only**. It is
not a heartbeat from a remote worker. It checks pinned checkout identity and
selected executable prerequisites; real media checks remain separate evidence.

```json
POST /api/video-engines/jobs
{
  "request_id": "c4c2b44a-49d0-4471-b96e-95400d083da2",
  "engine": "openshorts",
  "title": "A self-contained excerpt",
  "source_video_id": "REPLACE_WITH_REAL_FINISHED_ID",
  "start_sec": 12,
  "end_sec": 42,
  "aspect_ratio": "9:16",
  "source_rights_confirmed": true
}
```

The example ID is not an existing source. Use a real delivered record. Other
request fields are `material_video_ids`, `storyboard`, and `silent`; unsupported
combinations, URL/path overrides, provider settings and extra fields are rejected.
A changed request needs a new `request_id`. The server resolves source records
and freezes artifact IDs, checksums and sizes. Private URLs/credentials do not
appear in the new job's public DTO or provenance manifest.

`GET /api/video-engines/jobs/{id}` reconnects to durable status and artifact links.
`POST /api/video-engines/jobs/{id}/dispatch` claims only that engine job when the
runtime is installed on this host; otherwise it leaves it queued. Browser
cross-origin mutations are rejected in addition to the existing signed-cookie
authentication. Machine read tokens cannot queue or dispatch these routes.

Limits: 90-second outputs; source recordings at most one hour; MPT narration at
most 90 seconds; up to 12 ordered material clips, each at most five minutes; each
source artifact at most 512 MiB and total inputs at most 1 GiB. Workers check
actual media duration, audio presence and hashes, not only client declarations.
Old records without checksums/byte sizes cannot be used until re-indexed. Motion
Canvas labels must fit 180 characters and each shot must be at least one second.
These are authored-template limits, not a claimed high-retention formula.

## Worker installation and execution

A source checkout on a persistent Linux worker needs the existing Postgres and
Blob configuration. Merging into Vercel does **not** install the rendering tools
there. Do not place Torch/Chromium/MoviePy 2 in the web app's main requirements.

```bash
# In this repository checkout; install documented OS prerequisites first.
python integrations/video_engines/install.py all
python -m bolt_video.engines.worker --job-id engine-REPLACE_WITH_REAL_ID
# Or run under your normal process supervisor:
python -m bolt_video.engines.worker --poll
```

The default engine root is this source checkout. `REELFORGE_ENGINE_ROOT` is an
optional path override, not an enablement/security token. The Motion installer
now downloads Chromium into its project's `.browsers` directory and verifies a
browser launch. On Linux, install browser system packages using Playwright's
`install-deps chromium` command as part of host provisioning. Runtime generation
never downloads a browser or model. Pin upgrades and bump `jobs.VERSION` when
output pixels, timing, normalization or integration behavior changes.

The existing store's `claim` defaults to kind `explainer`; the dedicated worker
claims only `video_engine`. Generic explainer cron/dispatch cannot consume these
requests as `ExplainerRequest`. Jobs use existing leases, heartbeats and bounded
attempts. Completed engine-render stages are downloaded on retry. Only a known
zero-cost `local_engine_v1` running stage with matching hash can be re-armed under
the current lease; paid-provider stages retain their ambiguity protections.
Temporary inputs, frame sequences and encodes are cleaned in `finally` contexts.

## Verification and operational boundaries

`tests/test_video_engine_jobs.py` covers immutable deduplication, mutation, source
validation, path/URL injection, auth, zero-cost configuration, caption rebasing,
actual-duration rejection and kind isolation.

The `Connected video engine jobs` CI matrix installs each upstream environment
and runs `tests/engine_job_smoke.py`. The test uses **real Postgres queue/lease/
stage/finalization operations and the real engine**, with a local Blob transport
double. It injects an outage after rendering, proves the next worker reuses the
saved stage without calling the engine again, and checks source preservation.
The uploaded MP4/report are synthetic technical fixtures, not publishable content.
A pass is not proof of production Blob credentials or a deployed worker's health.

Before live use: provision/verify the persistent worker, confirm private source
artifacts are readable there, review one real output per method, and complete the
exact code/dependency/model/media licensing review described in the baseline
guide. No provider purchases or production deployment are performed by this PR.
