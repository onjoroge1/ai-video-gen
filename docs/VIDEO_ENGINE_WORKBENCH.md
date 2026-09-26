# Optional video engines and the shared storyboard

Owner: ReelForge / Bolt. Added 2026-09-21. Start here before operating or extending
MoneyPrinterTurbo, Motion Canvas, OpenShorts or the ViMax import feature.

## What is shipped, and what is not

This change supplies isolated installation scripts, a provider-free storyboard
contract and ViMax description importer, a browser-memory storyboard editor,
a Motion Canvas causal-animation starter, and separate installation/media checks.
It does **not** deploy a persistent worker, enable a new paid generation route,
add an engine to the production format dropdown, or automatically publish anything.
The existing formats, approval system, durable jobs and finished library are intact.

The workbench is served by the existing authenticated static mount at
`/video-engine-workbench.html` after this branch is deployed. It is a separate
planning page, not yet linked from the main studio navigation. It keeps drafts
only in browser memory. Export JSON before leaving the page. No storyboard DB
persistence or upload to a model is performed. Browser checks are advisory; use
Python validation for the full contract. `production_enabled: false` is deliberate
capability reporting, not another environment-variable switch to turn on.

**Do not equate these states:** source checkout → dependency installation → import
or build success → local media smoke → reviewed end-to-end pilot → production.
CI installations exist on disposable runners, not in the live Vercel application.
No new Vercel environment variables are required for this planning feature.

## Where each belongs

| Capability | Type | Best fit | Avoid / boundary |
|---|---|---|---|
| Stock / Hybrid Short · MoneyPrinterTurbo | Alternate production flow | Approved narration with relevant licensed real footage; simple factual Shorts | Do not replace Rapid Quiz. Do not use generic B-roll to impersonate a specific historical event. |
| Animated Explanation · Motion Canvas | Reusable shot/scene feature | Visible cause and effect, comparisons, quantities and state changes within an illustrated story | Not a universal prompt-to-video model. Requires authored templates and reviewed timing/data. |
| Remix to Shorts · OpenShorts | Finished-video repurposing flow | A complete hook-to-payoff passage in an owned/licensed long video | Do not blindly face-track illustrations or assume a portrait crop preserves the explanation. |
| Shared Storyboard · ReelForge, ViMax-compatible import | Planning feature used by several flows | First frame → visible change → last frame, references and narration alignment | An imported shot description is not sourced evidence, approval or spending authority. |

Choose the production method from the material, not from the repository's name.
A long illustrated episode can mix existing illustration shots with Motion Canvas
scenes. Repurposing happens after a source exists. MoneyPrinterTurbo is not the
scheduler for the whole application. ViMax is not installed as a second autonomous
agent system.

## Installation

Run on a dedicated Linux CPU worker or development workstation, not inside a
Vercel request or the root application's Python environment. Linux CI is the
verified target; macOS/WSL compatibility needs its own run. Native Windows is
rejected by the wrapper. Install Python 3.11, Node 22, Git, uv, FFmpeg and ffprobe.
Linux OpenCV dependencies include `libgl1` and `libglib2.0-0`.

```bash
# From the ReelForge repository root. No provider credentials needed.
python integrations/video_engines/install.py all

# Individual installations, independently repeatable:
python integrations/video_engines/install.py moneyprinterturbo
python integrations/video_engines/install.py motion_canvas
python integrations/video_engines/install.py openshorts

# Only clone exact Python sources / inspect the Motion manifest:
python integrations/video_engines/install.py all --source-only
```

`all` runs sequentially on a workstation. The `Optional video engines` GitHub
Actions workflow installs the three engines in parallel, with independent status.
A failed engine must not be described as installed-and-ready because another passed.

Python checkouts and environments are under ignored
`integrations/video_engines/runtime/`. MPT uses its own `.venv` and frozen `uv.lock`.
OpenShorts uses `.reelforge-venv` and CPU Torch wheels. Motion Canvas uses its own
`integrations/motion-canvas/node_modules`. Do not add MoviePy 2, Torch, Ultralytics
or these tools' FastAPI versions to ReelForge's `requirements.txt`.

The installer verifies upstream origin and exact Git HEAD, rejects tracked local
changes, removes stale success reports before a new install, and writes a report
only after the required imports/build pass. It never starts a service or requests
provider generation. Dependencies and model caches still consume disk space.
Reserve worker disk for temporary media and inspect free space before real renders.

### Pins and provenance

The source of truth is `integrations/video_engines/sources.lock.json`:

- MoneyPrinterTurbo: `3d5f4e421927d61f3eac729cf4b711ac0b69d688`.
- OpenShorts: `4b2cf58922587ecb17b990a9575e46320bdb3118`.
- Motion Canvas core/2d/UI/vite-plugin: `3.17.2`.
- ViMax importer field reference: `interfaces/shot_description.py`, inspected blob
  `af8f34d4839f1ae1f84576d4b63541a2619e245f`. This is a file blob, not a repository commit.

The Motion installer uses `npm ci` when a package lock is present, otherwise
`npm install`; CI uploads the resolved lock as evidence. Direct package pins alone
are not a full transitive dependency lock. OpenShorts' upstream requirements also
contain unpinned/transitive dependencies. Freeze and audit the deployed environment
before treating it as a reproducible production image. Never silently fetch latest.

## Shared storyboard: use now

Open `/video-engine-workbench.html`. Select a production method, edit narration and
before/change/after cards, and export `storyboard.json`. References, claim IDs and
a repurposing source span are editable in Advanced JSON. Adding/removing shots does
not silently retime later shots; fix the timeline explicitly.

```bash
python -m bolt_video.engines catalog
python -m bolt_video.engines validate \
  integrations/video_engines/examples/storyboard.json
python -m bolt_video.engines validate storyboard.json --output reviewed-plan.json
```

The output is a review envelope containing the normalized `storyboard`, warnings,
duration and a stable `plan_sha256`. Existing output files are not overwritten.
The hash identifies data; it is **not** an authorization hash accepted by the paid
agent API. The draft schema is **not** the existing directed-longform request schema.
Do not POST it to `/api/agent/actions` pretending it is one.

Validation rejects gaps/overlaps, duplicate IDs, invalid/non-finite times, missing
narration, script/shot narration divergence, undeclared references and invalid
repurposing spans. A claim ID only references a ledger entry; this validator does
not verify that ledger, factual truth, media rights or image/narration correspondence.
No arbitrary URL or file path is fetched. Reference IDs do not load images yet.

For repurposing, `source` contains a `finished_video_id`, declared `duration`,
absolute source `start`/`end`, `content_type`, and `layout`. The storyboard's own
clock starts at zero and must equal the selected source-span duration. A future
worker must verify source ownership and ffprobe the actual bytes. An illustrated
source requires `general` layout in this draft contract; do not equate it with a
verified crop. Never fabricate source IDs or durations.

## ViMax: import the useful storyboard semantics

Yes: borrow its explicit first/last-frame and motion planning as a shared feature.
No: do not install its full multi-agent pipeline or let import initiate images,
voices, video calls or budget reservations.

```bash
python -m bolt_video.engines import-vimax \
  integrations/video_engines/examples/vimax-import.json --output vimax-plan.json
```

Supply ViMax `ShotDescription` objects plus an explicit `alignment` array of
`{idx, start, end, narration}` and a matching `narration_script`. The importer maps:

| ViMax field | ReelForge field |
|---|---|
| `idx` | stable `vimax-<idx>` shot ID |
| `visual_desc` | `visual` |
| `ff_desc` | `first_frame` |
| `motion_desc` | `change` |
| `lf_desc` | `last_frame` |
| `audio_desc` | `audio_notes`, **never narration** |

It neither invents missing first/last frames nor assigns guessed durations. It does
not import ViMax's camera/character objects, generated image files or reference
index graph yet. Add verified ReelForge reference IDs separately. The browser can
import the resulting review envelope or its `storyboard` member. Output is always
a draft. This feature imports descriptions; it does not call ViMax to generate one.

## MoneyPrinterTurbo: production-flow boundary

After installation, an operator may inspect its isolated API on loopback:

```bash
cd integrations/video_engines/runtime/moneyprinterturbo
.venv/bin/python -m uvicorn app.asgi:app --host 127.0.0.1 --port 9011
```

Inspected upstream endpoints are `POST /api/v1/videos` and
`GET /api/v1/tasks/{task_id}`. They belong to the optional upstream service, **not**
the current ReelForge API. Posting can spend provider credits. Do not expose this
service publicly or give an assistant broad provider keys. Configure upstream API
authentication when using a network boundary, and disable all auto-upload settings.
Its API, config, task IDs and responses require an adapter; it is not plug compatible.

The production adapter should receive approved script, narration audio and approved
ordered assets. Inspected fields include `video_script`, `video_source`,
`video_materials`, `custom_audio_file`, `video_aspect`, `video_concat_mode`,
`video_count`, `subtitle_enabled` and `bgm_type`. Local material plus supplied audio
can avoid script/TTS/stock purchases. Server-file audio input is deliberately limited
by upstream; do not pass arbitrary local paths from a web request or weaken this guard.

Do not silently rewrite a script, fall back to unrelated scenery, multiply outputs,
select random music without rights, or let cross-posting execute. Retain source URLs,
licenses, IDs, hashes and provenance with generated assets. Exact scene ordering,
caption quality and runtime still need pilot verification, even with ordered assets.

## Motion Canvas: a scene feature

```bash
cd integrations/motion-canvas
npm run dev
# Open the loopback editor on port 9013.
npm run build
```

`src/scenes/mechanism.tsx` is an eight-second fictional mechanism demonstration:
a reward appears, a token changes choices, and the consequence panel changes. It
uses original geometry, not historical evidence or external media. There is no TTS.
The JSON storyboard fixture is a planning example; automatic compilation from any
storyboard JSON into arbitrary Motion Canvas code is not implemented.

Copy the scene into a named authored template and substitute reviewed labels,
reference geometry and narration timings. Export through the editor's image-sequence
exporter. Use the actual exported filename pattern, frame rate and first frame to
encode with ReelForge's existing FFmpeg boundary. Do not guess frame numbering,
drop narration, stretch audio or hide failed states to make the encode pass.

The optional `@motion-canvas/ffmpeg` exporter is not installed: its package declares
GPL-3.0. Core/2d/UI/vite-plugin declare MIT. Using our existing encoder does not
constitute a blanket license clearance for FFmpeg builds or other dependencies.
A successful Vite build is not evidence of a rendered MP4 or correct visual timing.

## OpenShorts: repurposing a finished artifact

The isolated install is core Python dependencies, not the cloud billing product,
public gallery, YouTube Studio or Remotion service. A production adapter should
reuse ReelForge's existing source video and transcript/word timings when available,
then produce a new child artifact retaining the source job ID and time span.

Inspected upstream CLI flags include `-i/--input`, `-o/--output`, `--format`,
`--transcript`, and `--skip-analysis`. The full CLI can download model weights at
startup; a fresh install is not a complete model-cache installation.

**`--skip-analysis` is not an all-network/all-spend-off guarantee.** `AUTO_LAYOUT=1`
or shadow mode enables the source-layout AI stage before that branch. Explicitly
review `AUTO_LAYOUT`, LLM configuration, weights and loaded environment before
running it. This integration does not launch the complete CLI automatically.

For an illustrated source, preserve the full meaningful frame or reconstruct a
vertical scene from original assets rather than blindly track faces. For a talking
head, tracking can be reviewed; screen recordings may need a screencast layout.
Require a self-contained hook and payoff, readable captions, and no invented source
statements. Scores labeled viral are not measured or guaranteed YouTube retention.
No auto publishing; finish in ReelForge's library for normal review.

## Tests and evidence

```bash
python -m pytest --noconftest tests/test_video_engines.py
python integrations/video_engines/smoke.py moneyprinterturbo
python integrations/video_engines/smoke.py openshorts
```

The targeted tests are independent of provider packages; the full repository suite
still runs normally with its own conftest. Do not describe targeted success as a
full-suite pass. The MPT media fixture uses local generated video and a tone track
with subtitles/music/publishing disabled. The OpenShorts fixture exercises only
`ffmpeg_utils.cut_clip`, not transcription, moment selection, tracking or captions.
Both probe output media and refuse Python socket connections during the fixture.
They do not constitute a container-level egress firewall or a paid pilot.

Inspect each workflow's reports and logs. Known checkout issue: an existing orphan
`ShortGPT` gitlink can make checkout's recursive credential-removal fail. This
workflow removes its read-only checkout credential explicitly before third-party
code instead; it does not delete or reset that legacy component.

## Production integration still required

1. Select and deploy a persistent CPU render worker with bounded disk/concurrency.
   Installing on CI or merging into Vercel does not provide this worker.
2. Extend the existing approved-job contract with one small adapter per flow. Bind
   engine/version, script, source assets, duration and cost ceiling to approval.
   Persist stage receipts before dispatch and retain immutable checkpoint identity.
3. Resolve source assets privately, verify ownership and actual media, and return
   video/captions/provenance to Blob + Postgres as a child of the source/approved job.
4. Add real readiness probes and main-studio / finished-video buttons. A planning
   feature can be available before a generation worker; do not offer a dead render button.
5. Run one reviewed, bounded end-to-end pilot per flow, including interruption and
   recovery without duplicate provider purchases. Only then report production enabled.

This is a staged extension of the current architecture, not an instruction to build
another approval system, another login or a second billing/publishing application.

## Licensing and rollback

Retain upstream licenses/notices. MPT source is MIT. OpenShorts core is MIT but
`cloud/` is excluded and dependencies/models need separate review, including the
Ultralytics stack. A source checkout can contain excluded directories; this install
does not launch, copy into our package, or license those modules. ViMax source is MIT;
this importer is original mapping code, not a vendored full pipeline. Audit exact
code, model weights, media, fonts and provider terms for the deployed use.

To roll back, stop optional local processes and remove only their disposable runtime
or node_modules after preserving desired artifacts. Do not purge production Blob
objects or completed jobs. Revert this PR to remove the workbench; current formats
have no dependency on the optional environments. Upgrade one pinned engine at a
time and repeat its imports/build, source-contract checks, media smoke and pilot.
