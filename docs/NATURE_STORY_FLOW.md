# Nature Story v1 — shared Short / Long-form flow

**Status:** production-architecture PR  
**Channel:** Bolt Explains Nature  
**Flow ID:** `nature_story_v1`  
**Initial series:** `terrible_parents`

## Why this exists

The emperor-penguin Short and long-form were produced by separate paths. The Short used
`scripts/keyframe_short.py`; the long-form used the illustrated explainer pipeline with Nature
rules. That split let the hook, storyline, visual treatment, ending, and quality gates drift.

Nature Story makes one episode contract authoritative and gives it two output profiles:

```
Nature Story episode
  evidence + question + behavior + problem + mechanism + limitation
  + subject sheet + chronology + beat progression
             |
      shared KPI gate
             |
      shared storyboard
       /             \
 Short profile      Long profile
 portrait motion    landscape illustrated story
 keyframe renderer  existing explainer pipeline
```

The profiles share facts, promises, mechanism, continuity, and visual-proof obligations. They do
**not** share a forced runtime, identical narration, shot count, or ending duration.

## Isolation boundary

This PR does not replace or modify the global format registry. It does not reroute:

- World or History illustrated stories
- generic Short explainers
- Rapid Quiz
- Simulation
- TV Review / State Board
- user-directed long-form
- video-engine jobs

The existing `topic_channel=nature` hook remains the only place the shared Nature writing doctrine
enters the model-authored explainer. The Nature Story CLI is a separate entry point.

## Story contract

One episode requires:

- species and parent role
- one observable parenting behavior
- one practical problem
- one central question
- a supported mechanism with:
  - resource/origin
  - process/action
  - offspring benefit
- any material supported limitation
- passage-verified claim ledger
- explicit promises and their answer beats
- a beat progression
- a continuity/subject sheet
- visual proof for critical explanatory beats
- configured runtime and word cap

For Terrible Parents the default opening is the direct series question:

> Why is this [animal] the worst [mother/father/parent]?

That sentence is an editorial question being examined, not a scientific ranking. It is spoken once.
The specific behavior and practical problem follow immediately.

## Shared progression

The default causal line is:

```
question
  -> observable behavior
  -> practical constraint/problem
  -> mechanism
  -> supported development or limitation
  -> outcome
  -> one interpretation
```

A second twist is optional. It must never be fabricated to satisfy a template.

Every beat is labelled as one of:

- action
- constraint
- mechanism
- consequence
- limitation
- reinterpretation
- callback

A beat must add relevant information. Another statistic, adjective, or camera angle does not count.
One useful closing callback may repeat meaning.

## KPI / QA contract

The pre-render report uses `PASS`, `FAIL`, `UNKNOWN`, and `NOT_APPLICABLE` semantics.
An unmeasured production check is never converted into a pass.

| Check | Requirement |
|---|---|
| INPUTS_READY | Required Nature Story inputs and supported engine are present |
| WORD_CAP | All spoken narration, including the hook, fits the configured cap |
| HOOK_ONCE | The central question opens beat 1 and is spoken exactly once |
| CLAIM_SUPPORT | Every referenced material claim has a passage-verified record |
| PROMISE_CLOSED | Every substantive promise maps to an answer beat in the same video |
| MECHANISM_COMPLETE | Resource/origin -> process -> offspring benefit are all present |
| PARENT_SUBJECT_MATCH | Title/question and explained parent role match |
| NO_CONTRADICTION | Narration and implied visuals have completed contradiction review |
| PROGRESSION_REVIEW | Repeated propositions and non-developments are identified |
| VISUAL_PROOF | Every critical explanatory beat has an explicit storyboard proof state |
| TIMING_MEASURED | Exact narration has been synthesized/aligned and meets runtime |
| SCHEMA_ACTUAL | Exact production payload passed the real production validator |
| SCRIPT_GRADE_ACTUAL | Exact narration passed the configured production script grader |
| RENDER_GATE_ACTUAL | Final rendered asset passed its real rendered checks |

The first nine are the shared pre-render decision boundary. Production-only checks remain unknown until
their actual tools run.

The current 10% redundant-speech and ~6-second no-development ideas remain review/calibration metrics,
not universal hard platform laws. Do not manufacture trivia or cut comprehension pauses to satisfy a
number.

## Storyboard: use the existing evidence-state planner

Do **not** reuse `board_pipeline.py` for Nature. That module is an always-on state rail for TV episode
reviews and carries faction/character/control semantics that are unrelated to animal stories.

Nature Story instead reuses:

- `longform_evidence.compile_evidence_plan` for before/change/after evidence states, continuity,
  forbidden objects, subject-sheet identity, and Nature's no-people rule.
- `longform_shots.compile_scene_shots` in the existing long-form renderer for phrase-aligned cuts.
- `scripts/keyframe_short.py` for the Short's start/end frames, generated motion, clip gate, captions,
  audio, and assembly.

That means the storyboard answers the same question for both profiles: **what must visibly change to
prove this line of narration?**

## Short profile

The shared episode compiles to the existing keyframe format:

```
episode beats
  -> visual proof states
  -> start / end stills
  -> measured narration
  -> generated motion clips
  -> clip motion/drift/arrival gate
  -> natural-speed windows
  -> captions + music
  -> final portrait MP4
```

Looping is now continuity-aware. Legacy keyframe specs still loop by default. Nature Story explicitly
sets `loop=false` unless the episode declares the return to frame one chronologically safe.

A Short must fully answer its own promised mechanism. It is not a trailer whose explanation only
exists in the long-form.

## Long profile

The shared contract compiles to arguments for the existing `run_explainer_pipeline` with:

- `topic_channel="nature"`
- `visual_style="illustrated_story"`
- landscape output
- standard motion by default, rather than silently inheriting a stills-only identity
- the shared episode contract injected as authoritative operator direction

The existing research/evidence/script/render gates remain in force. This adapter does not bypass
them.

Long-form earns extra runtime by adding relevant changing needs, consequences, mechanisms, or
limitations. It must not become the Short stretched with longer holds or repeated hardship.

## Ending rule

The old Nature rule required every story to finish on a feeding image. That overfit the penguin.

Nature Story requires the final action to demonstrate the **episode-specific supported payoff**:
a feeding event, care changeover, remaining dependency, trade-off, or other evidence-supported
interpretation.

## Commands

All non-spending:

```bash
python scripts/nature_story.py spec/my_episode.json validate
python scripts/nature_story.py spec/my_episode.json storyboard
python scripts/nature_story.py spec/my_episode.json compile-short
python scripts/nature_story.py spec/my_episode.json long-request
```

Paid Short render:

```bash
python scripts/nature_story.py spec/my_episode.json render-short --authorize-paid
```

The Short renderer still enforces the episode's hard USD cap. A failed pre-render hard check stops
before media generation.
