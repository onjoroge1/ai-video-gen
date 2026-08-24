# ReelForge — Bolt AI Video Studio

ReelForge turns a topic or narration script into a packaged YouTube video. It currently supports:

- **Short** — vertical curiosity-gap explainers.
- **Explainer** — beat-sheet-driven long-form videos with quality gates and resumable work.
- **Simulation** — vertical “change by N every period” stories whose math is compiled in code.
- **TV Review** — spoiler-scoped reviews with original location art and an evolving story board.

The former House of the Dragon / State Board workflow is now the general TV Review format. Legacy
`/api/stateboard/*` routes remain as deprecated aliases; new clients use `/api/tv-review/*`.

## Quick start

Requirements: Python 3.10+, FFmpeg/ffprobe, and credentials for the providers you enable.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Open <http://localhost:8000>. Local development remains open when `APP_PASSWORD` is unset. On
Vercel the application fails closed and shows `/login` until `APP_USERNAME`, `APP_PASSWORD`, and a
preferably separate `APP_SESSION_SECRET` are configured. Sessions use a signed HttpOnly, Secure,
SameSite cookie; credentials are never stored in browser local storage.

## Architecture

```text
app.py                    FastAPI routes, SSE job status, static UI
explainer_pipeline.py     active Short, Explainer, and Simulation orchestration
longform_retention.py     deterministic story contract, narrative-debt and timing validation
longform_shots.py         narrative-scene to adaptive visual-shot compiler
retention_readiness.py    first-minute gate, story-turn audio cues, and 100-point RRS rubric
stateboard_pipeline.py    TV Review assembly (legacy module name)
board_pipeline.py         portable story-board renderer and timeline extraction
bolt_video/
  core/                   shared output contracts and format registry
  prompts/                ordered prompt construction with explicit precedence
  simulation/             Decimal-based parser, compiler, and prompt contract
bolt_seq/                 experimental/deterministic Bolt motion toolchain
static/index.html         browser studio
tests/                    Phase 0/1 contract and regression tests
```

`GET /api/formats` returns the canonical format registry.

## Production persistence

Set `DATABASE_URL` and `BLOB_READ_WRITE_TOKEN` before starting a paid render on Vercel. Production
renders fail before provider spend when either is missing. Completed MP4s, captions, transcripts,
descriptions, grades and thumbnails are uploaded to Vercel Blob; Postgres stores their searchable
metadata. The authenticated `/finished` library survives cold starts and links back from the studio
navigation. Blob objects use random-suffixed public CDN URLs for efficient video playback; the
library and all generation APIs remain behind the studio login.

`GET /api/production-readiness` reports configuration booleans without exposing any credential.

Long-form explainer execution is also durable in production. The create route writes a queued job
to Postgres and returns immediately; a separately authenticated worker claims it with a renewable
lease. Provider calls reserve budget before execution and use a stable stage identity. Completed
stage files and full working-directory checkpoints are immutable Blob objects, so another worker can
restore the job without repurchasing a completed stage. Postgres is authoritative for events,
attempts, cost, review state, and finalization; the browser's SSE status stream reads that ledger
instead of process memory.

Set `CRON_SECRET` for Vercel's `/api/cron/render-recovery` request and set a separate
`RENDER_WORKER_SECRET` for manual/headless worker calls. The recovery cron reclaims expired leases,
caps attempts, and reconciles both registered provisional artifacts and aged unregistered objects.
`DURABLE_JOB_MAX_COST_USD`, `DURABLE_JOB_MAX_ATTEMPTS`, `DURABLE_JOB_LEASE_SECONDS`, and
`DURABLE_MAX_INFLIGHT_CALL_USD` define the failure and spend envelope. A provider request accepted
immediately before worker death is the one explicitly documented ambiguous in-flight call; its
reservation is charged conservatively at finalization.

### Rendered-gate threshold calibration

The rendered gate treats an uncalibrated threshold profile as a hard failure, so **every run caps
at 69/100 until a profile exists** — the 85 and 90 release targets are unreachable before this
step, by design. `scripts/harvest_gate_samples.py` builds the dataset:

```
harvest_gate_samples.py harvest  inspection*.json worksheet.json
# an editor fills meaningful_change / slideshow on each row
harvest_gate_samples.py status   worksheet.json      # names the exact remaining shortfall
harvest_gate_samples.py compile  worksheet.json samples.json
scripts/calibrate_rendered_gate.py samples.json profile.json --reviewer "<editor>"
```

Point `LONGFORM_GATE_CALIBRATION_PROFILE` at the result. Labels start empty and are never seeded
from planner metadata — `declared_new_information` is carried only as context, because it is the
field the threshold exists to audit. At least 20 labeled examples per class are required, drawn
from at least two distinct real videos on each side of the `slideshow` label, since that label
describes a whole video rather than one cut.

### Controlled 45-second pilots

`POST /api/explainer/pilots` atomically queues exactly two durable PR7 evaluation jobs: one
Standard explainer and one Evidence-led Mystery. Both use the fixed 45-second runtime, Standard
motion treatment, production rendered-story rubric, and current rendered-gate threshold profile.
The endpoint does not accept runtime, threshold, checkpoint, or replacement-image overrides.

Each job stops after its rendered opening. It persists the complete working artifact tree to Blob
and waits for the normal hash-bound editorial checklist at
`POST /api/explainer/human-review/{job_id}`. Editorial approval cannot override an automated score
below 85, any hard failure, an uncalibrated threshold profile, or missing artifacts. Passed and
failed pilots remain addressable through `GET /api/explainer/pilot/{job_id}`; neither can resume
into a full video. A new attempt always requires a new pilot batch and immutable job IDs.

### Controlled 90-second production run

`POST /api/explainer/production` queues the single PR8 job that buys one complete 90-second video.
It takes only a passed PR7 `batch_id` and the question: the structure is derived from the recorded
PR7 scores rather than chosen by the caller, and a reviewer may decide only an exact score tie —
with their identity and written reason recorded in the hashed selection. A batch whose pilots did
not both pass cannot start a production run.

The run inherits the PR7 winner's approved opening freeze by hash and must reuse those exact bytes:
a regenerated callback object fails. Beyond the ordinary release gate it requires an 87.3–92.7
second runtime measured from both the encoded MP4 and natural-speed narration (time-stretching is
rejected), a rendered-contract score of at least 90, zero dropped-narration scenes, zero filler
frames, no unresolved narrative loop, provenance for every produced media file, a fast-start MP4,
and observed cross-worker recovery. Every gate is independent, and none of them — nor a failed
automated or editorial grade — can be promoted in place. `GET /api/explainer/production/{id}`
returns the run and its job, ending in a `publish` or `do_not_publish` recommendation.
`PR8_PRODUCTION_MAX_COST_USD` caps a run's spend.

Render music is fetched from external object storage into a checksum-verified local cache. Neon stores
the asset URL, checksum, size, licence, and provider in `music_assets`; the MP3 bytes are deliberately
not stored in Postgres or bundled into the Vercel function. Run `python scripts/sync_music_assets.py`
once with `DATABASE_URL` set to seed the metadata table. A first render also creates/updates its track's
row automatically. `MUSIC_<MOOD>_URL` and `MUSIC_<MOOD>_SHA256` can point a track at Vercel Blob or
another CDN without a code change.

## Topic ROI v2

Topic research is aligned to three Bolt lanes—Earth, Physics, and Space—and generates separate Short
and long-form candidates. YouTube validation compares equivalent duration buckets and scores
age-normalized views/day, logarithmic outlier demand, competition and recency. The rank also includes
the channel's stored retention/subscriber outcomes, visual promise, production feasibility, fact
confidence and novelty. Close paraphrases are removed across lanes. A GET never starts paid research;
use the protected **Refresh research** action explicitly.

## Prompt and simulation guarantees

Prompt precedence is explicit: safety, output schema, deterministic facts, format rules, then creative
direction. Simulation titles are parsed before the script model is called. Supported linear units are
length (`mm`, `cm`, `m`, `km`), mass (`g`, `kg`, `lb`, `tonne`), Celsius, and explicit count units.
Percent/compound rules, unknown units, and missing rates fail closed instead of handing arithmetic to
an LLM.

Long-form explainers persist a versioned story contract before rendering: the title/visual promise,
false and replacement mental models, personal stake, stages, per-beat role, visible consequence, and
explicit narrative-loop openings/closures. A provider-free validator enforces an early prediction and
payoff, recurring attention turns, bounded exposition, a correctly placed peak, resolved loops, and a
final title payoff. One automatic re-plan may repair structural failures; remaining failures stop before
image/TTS spend when `LONGFORM_RETENTION_HARD=1` (the default). Successful renders expose a downloadable
text report and archive the machine-readable `retention_report.json` beside the other artifacts.

Landscape scenes are narrative beats rather than fixed five-second slides. The semantic shot compiler
cuts on exact narration phrases and only when clause-specific B-roll adds setup, action, evidence, or
consequence information. A single source uses one continuous camera path; every shot is at least 1.5
seconds. Generated motion begins at the spoken action and absorbs small timing remainders instead of
creating flash frames. Before image or TTS spend, the runtime planner fits or rejects narration outside
the requested-duration window. Shorts retain their existing four-second motion contract.

Before purchasing the remainder of a long-form asset set, the pipeline renders the opening tranche
into `first_minute_preview.mp4` and assigns a transparent **Retention Readiness Score (RRS)**. The
100-point rubric covers opening contract (25), narrative propulsion (25), visual continuity and
semantic sync (20), audio
rhythm (15), packaging/payoff alignment (10), and technical delivery (5). A score below 70 stops the
run when `FIRST_MINUTE_GATE_HARD=1`; sub-1.5-second shots, low semantic alignment, and same-source hard
cuts are blocking failures even when the total would otherwise pass. RRS is an editorial readiness grade—not a claim or forecast of
actual YouTube retention, which must be measured after publishing. Prediction gates, payoffs, reversals,
and rehooks receive sparse locally synthesized audio cues; background music ducks at deliberate drops.
Post-publish results use a separate runtime-aware Observed Retention Grade; it never substitutes a
pre-render RRS for real analytics, and results below 100 views are explicitly marked low-confidence.

Every checkpoint includes both the **delta** and the **total state from a stated baseline**. Decreasing
quantities stop at a defined floor and include scientific-boundary warnings.

## TV Review input contract

Provide a title and narration split into at least two blank-line-separated chapters. Optional metadata
includes show name, season, episode, spoiler scope, and review angle. The extractor may track characters,
groups, plotlines, theories, mysteries, control, and genuinely countable assets. It uses only the pasted
narration and spoiler scope. Background art is generic and original; the board uses text chips instead
of actor likenesses or show footage.

## Configuration and verification

Copy `.env.example` and fill only the credentials for enabled providers. Do not commit credentials,
provider tokens, licensed music, or local absolute artifact paths.

```bash
python -m compileall -q app.py bolt_video board_pipeline.py stateboard_pipeline.py explainer_pipeline.py
pytest tests bolt_seq/tests/test_state.py
```

GitHub Actions runs these focused checks on pushes and pull requests.
