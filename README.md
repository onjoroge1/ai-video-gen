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

Open <http://localhost:8000>. Set `APP_SHARED_SECRET` before exposing the server beyond localhost;
the web UI requests it on the first protected operation.

## Architecture

```text
app.py                    FastAPI routes, SSE job status, static UI
explainer_pipeline.py     active Short, Explainer, and Simulation orchestration
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

## Prompt and simulation guarantees

Prompt precedence is explicit: safety, output schema, deterministic facts, format rules, then creative
direction. Simulation titles are parsed before the script model is called. Supported linear units are
length (`mm`, `cm`, `m`, `km`), mass (`g`, `kg`, `lb`, `tonne`), Celsius, and explicit count units.
Percent/compound rules, unknown units, and missing rates fail closed instead of handing arithmetic to
an LLM.

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
