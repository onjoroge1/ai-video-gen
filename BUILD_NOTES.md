# ReelForge illustrated lane — build notes

Working document for collaboration. Written for a reviewer with no prior context on this branch.
Everything below is measured unless explicitly labelled a hypothesis.

**Last reported live status: the illustrated lane does not render end to end.** Fourteen full renders and seven
script-only samples have produced no video. Every failure is a deterministic gate firing *before*
image generation, so no image spend has been wasted — but no frames exist either.

**September 5 code review:** the fixes and verification limits are recorded in
[`docs/ILLUSTRATED_FLOW_REVIEW_2026-09-05.md`](docs/ILLUSTRATED_FLOW_REVIEW_2026-09-05.md).
The earlier live counts below are the author's historical observations, not new measurements of
the repaired code. No new paid sample or finished-video claim accompanies this review.

---

## 1. What this lane is trying to do

Reproduce the storytelling format of six reference videos: 101–225s vertical explainers that walk a
causal chain in spoken chapters ("Step one…"), drawn as flat illustrations with blank-faced stick
figures, closing on a callback to the opening object.

Two things are in place and working:

**A reference corpus** (`fixtures/causal/`, 6 references, 4 of 5 engines backed). Each reference is
one artifact with a structural authority split:

| block | source | may it gate? |
|---|---|---|
| `measured` | ffmpeg/whisper — cut cadence, wpm, loudness, hold times | **yes**, deterministic |
| `observed` | vision model over sampled frames — hook type, tone, composition | **no**, context only |

The split is enforced by returning them from two different functions (`reference_corpus.py`).
`gating_metrics()` *cannot* hand back a judged field. A convention would have been forgotten — three
gates built on judgement shipped earlier in this work and all three damaged scripts.

**A story contract** (`causal_story.py`, 42 error codes, all reachable, falsifiability-audited).
Five narrative engines (`story_engines.py`), each declaring its own beat sequence, required roles
and mechanism deadline.

---

## 2. The core problem, as currently understood

Scripts fail the causal contract on a rotating subset of `LATE_MECHANISM`, `ENGINE_ORDER`,
`SOFT_HINGE`, `THIN_GENERALIZATION`. Measured pass rate: **1 in 7**.

### 2a. `LATE_MECHANISM` — solved in diagnosis, not yet in code

The beat-sheet prompt contained **two contradictory instructions** in one string:

- rule C: *"Its pct MUST be under 20. This is a structural slot … not a preference"*
- FIXED ARCHITECTURE, ~100 lines later: *"· 40-55% mechanism ·"*

Both unconditional, neither referencing the other, the later favoured by recency. The code already
recorded the outcome — *"Four measured runs placed the explanation near 35%"* — the average of the
two. Removed (commit `920c099`).

Then measurement found the deeper cause. **The opening milestone count differs by engine:**

| reference | engine | milestones before mechanism | mechanism at |
|---|---|---|---|
| cobra_effect | backfiring_solution | **5** | 36s / 220s = 16.4% |
| bengal_famine | accumulating_indictment | 4 | 33s / 170s = 19.4% |
| dc_compensated_emancipation | accumulating_indictment | 4 | 20s / 101s = 19.7% |
| romanov_fall | power_reversal | 4 | 44s / 225s = 19.6% |
| pompeii | power_reversal | 3 | 22s / 127s = 17.3% |

`backfiring_solution` is the only engine needing five beats before the mechanism, and its single
reference is also the longest video. **Cobra's own 36-second opening is 21% of a 170s video and
would fail our gate.** All five failing samples chose `backfiring_solution` at ~170–190s.

Confirmed by experiment — same code, same topic:

```
170s × 5 runs   LATE_MECHANISM 5/5   (misses of 1–11s)
220s × 1 run    LATE_MECHANISM absent
```

This supports runtime sensitivity, not an engine-wide impossibility. The exact unchanged-opening
boundary is **36 / 0.20 = 180 seconds**, including equality under the current validator. A 170-second
request needs two seconds (5.56%) of opening compression. Five failures at one runtime and one
observation at another do not establish a minimum feasible runtime or isolate model variability.
The code review also found remaining contradictory prompts and equal expansion budgets, so the
planner contract could not yet be ruled out as a cause.

### 2b. `ENGINE_ORDER` — open, and partly self-inflicted

The planner emits milestones out of the engine's order (`intervention` after `mechanism`, etc.),
3/5 at 170s and 1/1 at 220s.

`_assign_causal_spine` has an escape hatch in its prompt: *"If the beats genuinely do not fit the
engine's order, choose a different engine rather than mislabelling them into this one."*
**Pinning the engine removed that hatch.** A sheet that comes back misordered now has no recovery
path. Introduced in `920c099` while fixing a different problem.

### 2c. Script length is unstable, and the deadline is a percentage of it

Five runs of an identical 170s request produced 462–589 words, so the 20% line moved between 31s
and 39s. The runtime contract passes all of them — *"not refitting; length is a request."* The
planner is aiming at a target that shifts run to run.

---

## 3. What was fixed along the way

Each replaced a rule that was *asked for* in a prompt with one *made true* in code. All are
committed and tested; none of them alone unblocked a render.

| fix | evidence it was real |
|---|---|
| `_story_engine` collision | a report dict overwrote the engine id; every illustrated story was validated against `The Backfiring Solution` regardless of its actual engine |
| location budget | prompt asked for ≤4 locations, gate killed the run when it got 6; now collapsed deterministically, nearest-neighbour |
| `repair_chain` unwired | the storyboard re-derived steps and validated them raw, so an order repair already applied upstream reappeared as a hard failure |
| chapter markers | same ask-and-kill pattern; now announced in code, *before* the clock counts the words |
| `repair_chain` inventing a beat | demoted strays to `generalization`, which needs 2 parallel cases; `accumulating_indictment` fetches none by design, so a render died on a beat the repair created |
| `accidental_invention` unusable | requires a hinge, has no false resolution, and `UNEARNED_HINGE` fired unconditionally — that engine could not pass for **any** input |
| engine chosen after the sheet | order/deadline now derived from the engine before planning |

### Reverted after measurement

Aiming the mechanism at 75% of the deadline. It rested on one observation; 5 samples showed no
benefit (0/5). Reverted. The gate itself was never moved.

### Measured and rejected

Raising `MECHANISM_DEADLINE_PCT` 20% → 26% moved the mechanism **later** (43s → 55s). Recorded at
the constant in `causal_story.py` so it is not retried. Five references sit at 16.4–19.7%; the 20%
line is corpus-backed and should not move.

---

## 4. Plan of action

Ordered by evidence strength. Items 1–2 are the open blocker; the rest are independent defects a
separate review confirmed.

### 1. Restore the engine escape hatch — *implemented; live sampling pending*
The pre-chosen engine should guide the sheet but let the labeller re-choose when the beats
genuinely do not fit. Replans keep the hard pin so a retry repairs the same contract.
**Test:** 5-sample harness, `ENGINE_ORDER` rate should fall from 3/5.

### 2. Make engine selection runtime-aware — *implemented; live sampling pending*
The selector already received duration but had no explicit opening-fit evidence. It now receives
reference timestamps, support counts, optional milestones and compression required at the requested
duration. Factual story fit remains primary: 170s is not a blanket ban on `backfiring_solution`.
Individual expansion budgets reserve opening words for the hook and format tag, and keep required
short-story beats instead of slicing off the ending. No validator deadline changed.
**Test:** fresh samples at the requested runtime must pass the production script checks without
manual relabeling, threshold changes, or dropping failed samples. Do not measure success merely by
how often a different engine is selected.

### 3. Verification discipline
Use the **$1 script-only dry run**, sampled ≥5×, before any render. Fourteen renders were bought one
roll at a time at ~$8 each; a single passing observation was mistaken for a working fix (see §6).

### Independent defects — confirmed, not yet addressed

- **Hippo approval card misstates scope 4.6×.** `spec/hippo_weed_directed_v1.json` sets
  `duration_sec` and `pilot_end_sec` to 208s while the approval UI renders "First 45 seconds only",
  at a $25 ceiling against a $5 default pilot limit. **A human approving that card consents to 45
  seconds and authorises 208.** This is a consent defect — fix or disable before that flow is used.
- Readiness never checks `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` or quota, so runs die mid-render
  *after* spend has started. Observed repeatedly.
- Durable cache restores only `.content` and `.usage`, dropping `stop_reason`, so the truncation
  check can never fire and a truncated response caches as complete. `charts_pipeline.py:285` reads
  the same attribute with no default → `AttributeError`.
- Every `ValueError` is terminal, including one whose own message says it is "a search-budget or
  provider-availability problem".
- Retry selection ignores causal error count when both drafts fail — a 1-error draft can lose to a
  3-error one.
- `script_provider.py` justifies dropping `tools=` on a stated precondition that is false; the
  dossier is still labelled `anthropic_server_web_search`.
- `tests/test_hippo_weed_converter.py` skips every test when an author-local path is absent.

---

## 5. How to verify anything here

```bash
python3 -m pytest tests/ -q     # 823 passed; 2 long-standing pre-existing failures
```

Script-only sample (paid, no images) — use only after approval of the sampling budget:

```bash
python3 scripts/longform_script_check.py --visual-style illustrated_story \
  --duration 170 --samples 5 --output script-check.json "<topic>"
```

Unlike the former direct `_generate_script_chunked` snippet, this harness includes production
research, graded generation/replans, fact-checking, binding checks, configured runtime handling
and the final illustrated storyboard. It still excludes HTTP approval, durable media execution,
TTS, images, MP4 and publication. Recorded usage costs are estimates, not guaranteed $1 samples or
an enforced aggregate budget. Failures waived by diagnostic flags never earn a clean script-check pass.

Knobs: `LONGFORM_CONTRACT_RETRIES` (replan budget, each retry is a full script),
`BLUEPRINT_ADHERENCE` (`loose|balanced|strong|off`), `CLAIM_LEDGER_HARD=0` (diagnostic renders,
**output is not publishable**), `MECHANISM_DEADLINE_PCT` (escape hatch; raising it is measured to
make things worse).

---

## 6. Corrections to the record

Kept because the mistakes are informative.

- **`920c099` labels the engine-selection fix VERIFIED on a single passing dry run.** Five further
  samples passed 0/5. The fix is real and measurably moved `LATE_MECHANISM` from 42–55% to misses
  of 1–11 seconds, but "verified" overstates it. True pass rate: **1 in 7**.
- I twice recommended loosening `MECHANISM_DEADLINE_PCT`, then measured that it makes things worse.
- I reported a dry-run "mechanism at 21%" as a near-miss; that number is *beat position*, while the
  contract measures `start_sec / runtime`. Different metric, not comparable.
- I changed the mechanism aim on one observation after criticising exactly that pattern.
