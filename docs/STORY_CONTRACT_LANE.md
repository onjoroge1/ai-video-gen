# Story-contract lane (design, 2026-10-21)

A second scripting lane, run beside `unfolding_consequence`, built from the editorial decisions
that made the lionfish rewrite (`jobs/lionfish-v2`) work: a real human entry point, one supported
question, development through cause and effect, and an ending that answers the opening question.

Status: first implementation (pre-media stages, segmenter, gate policy); see "Implementation" at the end. Operator decision 2026-10-21: parallel lane, not a retrofit.

## Why a separate lane

The compiled lane plans from the evidence: claims become factual functions, functions become
roles, and roles become narration. The only repeatable role is `escalation`, so the middle of every
film becomes a list (lionfish v1: ten escalations, "first wall / second wall / third wall").
Nothing in the plan records what the film promises, so no check confirms that the ending answers
the opening question.

The lane's own gates also rank the two lionfish scripts in the wrong order:

| | v1 compiled (`lionfish-invasion`) | v2 rewrite (`lionfish-v2`) |
|---|---|---|
| Retention readiness | 91 A | 74 C |
| Opening 45 s | 93 A | 74 C, stopped `OpeningBelowB` |
| Structural turn | 75 s | 146 s (the paradox is actually spoken at ~25 s) |

These scores come from role labels and structure, not from the words a listener hears. The new
lane plans from the question and selects only the evidence that serves it.

## Pipeline

```
research dossier (existing) + human-detail ask
  -> story contract                      [1 call]
  -> 3 openings x 2 endings, pick a pair  [1 call]
  -> complete continuous narration + sentence->claim map   [1 call]
  -> fresh review (blind first, then contract + evidence)  [1-2 calls]
  -> <=2 focused repairs, shared across the whole run (resume does not reset)
  -> operator approves the EXACT narration (hash-bound)
  -> segmenter: narration -> scenes (claims, visual purpose)   [no wording changes]
  -> existing claim ledger, storyboard, TTS, images, render
```

The new stages stop before media. From the segmenter onward, the lane reuses the hand-build path
that `jobs/lionfish-v2/hand_build.py` already proved: scenes carrying narration, claim IDs and
visual beats are enough input for the downstream stages.

## 1. Research ask (addition to the existing dossier)

In addition to the facts, research must return **human material**: a documented routine, choice,
cost, reward, revealing object, or quotation with personality. Rank candidates by whether one
detail does two jobs: it helps the viewer understand both the person and the larger problem. The
freezer detail did both. Mark Hixon's quotation was only expert commentary, which is why v1's
human figure stayed a cameo.

Every claim also gets a **kind**: `event` (documented), `model` (a study predicts this under its
assumptions), `interpretation`, or `illustration` (an imagined situation, framed aloud as one, such
as "put yourself on a commercial boat"). Today's ledger has no `illustration` kind, so a
hypothetical either fails binding or gets bound to a fact it does not assert.

## 2. Story contract (the plan the operator approves)

This replaces the role list in `plan_for_approval.md` for this lane.

- Topic. **Central question.** **The answer the ending delivers.** (Choose the question and the
  answer together.)
- Human perspective: their want, action or reward, each with its supporting claim.
- The reasonable attempt, and why it made sense.
- The main complication and the mechanism that produces it.
- **Developments**, in a flexible number. For each development: what happens, what it changes, and
  why the next development matters. A development that cannot name the change it causes is a
  list item, so it gets cut or merged.
- Recurring image, if one is useful. It must be planted before its callback.
- **Claims we cannot make**: forbidden expansions, such as "Carlson lost commercial income" or
  "eating lionfish made the invasion worse."
- Tangents left out on purpose. (v2 left out ciguatera and the die-off, both true and striking.)

## 3. Writer

The writer produces one continuous narration from the contract and a separate sentence-to-claim
map. The prompt describes storytelling functions. It sets no rules about form: no fixed section
count, no required second-person opening, no ban on "Picture...", and no joke quota. Humor must
come from the situation. Any number in the narration must serve the story.

## 4. Fresh reviewer (a separate call that never sees the writer's notes or scores)

**Pass A (blind):** the reviewer receives only the narration and the brief. It recovers the
central question, the main idea, the human want or reward, the pivotal discovery, and the answer
the ending gives.

**Pass B:** the reviewer receives the contract and the evidence. It then applies these checks:
- Compare the blind reconstruction with the contract. A mismatch means the narration did not
  execute the plan.
- **Opening-ending test:** do the opening and the ending ask and answer the same question?
- **Removal test, per passage:** what would be lost without it?
- **Evidence:** does each causal link and qualification hold? Does any illustration leak into a
  factual claim about a named person?
- Score each item in the ChatGPT rubric 0-3 with a quotation from the narration as evidence.
  Every 0-1 score needs a repair objective. The scores describe defects; they do not trigger
  loops.

The reviewer returns all factual blockers and at most three editorial objectives, each with its
location, the problem, the repair objective, and the material to preserve.

## 5. Repairs

There are at most two repair passes for the whole run. A changed reviewer or a resumed checkpoint
does not reset the count. Every candidate is kept. Changed claims are rechecked. If an issue
remains after the second pass, the lane returns the strongest factually acceptable candidate with
the issue listed, for the operator to decide. A central claim without evidence is returned as an
evidence gap or as a clearly labeled narrower draft. This follows the 10-19 rule to revise the
failed script first.

## Gates for this lane

| Gate | In this lane |
|---|---|
| Claim ledger, quotation binding, source fetch | **Kept, hard.** These are facts. |
| Storyboard, technical delivery, audio loudness | Kept. |
| Structural `late_turn` / 116-word turn budget | **Report only.** The reviewer's blind reconstruction decides whether the question lands early. |
| `opening_retry` B gate (semantic_sync cut timing) | Kept as cut-placement repair. Below B becomes **degraded, not stopped**. |
| Readiness "narrative propulsion" (role-label gaps) | **Report only.** It measures labels this lane does not use. |
| Engine role-order / min-escalation / myth-line / witness templates | **Not applied.** |
| Story-shape writer rules (`story_shape.py`) | Not applied. The contract replaces them. |

## Approval and spend

The operator approves the contract (no spend), then the exact narration (its hash). Media spend
starts only after the narration is approved, under the existing per-film ceiling. If production
changes any words, the result is a new narration version for review.

## Measuring the lane

Neither the reviewer's score nor readiness predicts retention. The lane is judged by audience data:

1. **Lionfish v2 first.** It needs the operator's `OPENING_RETRY_ALLOW_BELOW_B=1` override, because
   it was stopped by a gate this lane demotes. Compare its 30-second retention and first-minute
   drop with recent compiled World films, in `jobs/yt/experiments`.
2. Run the next 2-3 World topics through **both** lanes as far as the approved narration (cheap,
   no media). Do a blind side-by-side read with the order reversed, ties allowed. Publish the
   preferred version.
3. Calibrate the reviewer against the operator: on v1 vs v2 it must prefer v2 and give the
   reasons. A reviewer that cannot separate those two is not ready to gate anything.
4. Log every film as: *changed X, expected Y, observed Z, confounds (topic, title, thumbnail,
   length, traffic)*.

## Open questions

- Who reviews the contract: the operator at plan approval (recommended for the first films) or a
  model reviewer?
- ChatGPT's full `Consequence_Storytelling_Spec_v1.md`, with its staged prompts and the lionfish
  annotations, is not in the repo. It should go in `references/` if available.
- Which model handles each call: the writer and the reviewer should be different models, or at
  least share no context.

## Implementation (first PR, 2026-10-21)

Code: `story_contract.py` (stages, prompts, checks, repair budget, approvals),
`story_contract_segment.py` (narration -> scenes), `story_contract_policy.py` (gate policy the
pipeline reads). The compiled lane is untouched: every policy switch keys on `script["_lane"] ==
"story_contract"`, which only the segmenter writes.

### Running it

```bash
python scripts/run_illustrated_local.py --lane story_contract \
  --question "..." --out jobs/<slug> --duration 300 \
  --dossier jobs/<other>/research_dossier.json --source-pack <slug> --stop-after script
```

1. Without `--dossier` (and no `<out>/research_dossier.json`) the existing research runs once.
2. The run stops at `contract_for_approval.md`. Copy `contract.json` to `contract.approved.json`,
   edited or not, and rerun. An edited contract is re-checked; a failing one stops
   (`contract_invalid`).
3. It stops again at `narration_for_approval.md` with the narration's sha256. Rerun with
   `--approve-narration <sha256>` (written to `narration.approved.json`). `--stop-after script`
   always stops here, approved or not. `--stop-after contract` stops at the contract.
4. With the approved hash and no stop, the segmenter writes `_state.json` (the previous checkpoint
   is kept as `_state.pre_story_contract_*.json`) and the existing pipeline resumes from it.

`run_result.json` records the stop (`awaiting_contract_approval`, `awaiting_narration_approval`)
and the spend so far from `usage_ledger.jsonl`.

### Models and providers

`STORY_CONTRACT_PROVIDER=anthropic|openai` (default follows `SCRIPT_PROVIDER`). Writer and
reviewer are different models with no shared context. Defaults: Anthropic `claude-opus-5-5` writes,
`claude-sonnet-5-5` reviews; OpenAI `gpt-5.5` writes, `gpt-5.6-luna` reviews. Override with
`STORY_CONTRACT_WRITER_MODEL` / `STORY_CONTRACT_REVIEWER_MODEL`. OpenAI calls are recorded in the
usage ledger at `OPENAI_SCRIPT_RATE_IN/OUT` (default $5 / $20 per million tokens), the same
conservative estimate `script_provider` uses, not the provider's invoice.

### What is checked

- **Evidence:** every claim gets `story_kind` (event / model / interpretation) beside the
  ledger's own `claim_kind`, which roles still read. Human material is ranked, with "does both"
  (person and problem) first; a lead without a claim is listed as an evidence gap.
- **Contract** (`validate_contract`): question and answer; a person with a want, action or reward,
  each cited; the attempt and why it made sense; the complication and its mechanism, cited; every
  development names what it changes (`DEVELOPMENT_NO_CHANGE`), does not repeat an earlier change
  (`DEVELOPMENT_REPEATS_CHANGE`), says why the next matters (`DEVELOPMENT_NO_LINK`) and cites a
  claim; the recurring image is planted before it returns; forbidden claims are listed; every
  claim ID exists. One corrected attempt, then a stop.
- **Narration** (`validate_narration`): every factual sentence cites a claim
  (`UNSOURCED_FACT`); illustrations carry no claim and have a framing cue nearby; the writer's
  view of its inputs does not leak in (`PROMPT_LEAK`: "the supplied record", "the title's
  problem"); length against the runtime (a warning: length is a request).
- **Review:** pass A reconstructs the question, idea, human, pivot and answer from the narration
  alone; pass B compares that with the contract, runs the opening-ending, removal and evidence
  tests, and scores the rubric 0-3 with quotations (each checked against the narration). Factual
  blockers are unlimited; editorial objectives are capped at three, and any 0-1 score the reviewer
  left without one is added (the rest are kept as deferred).
- **Repairs:** a repair runs only for blockers or objectives, never for a score.
  `story_contract_repairs.jsonl` is append-only and a pass is written before its call, so two is
  the limit for the job directory across crashes, resumes, reviewer changes and re-approved
  contracts. Every candidate is kept in `story_contract_candidates/`; the strongest factually
  clean one is offered (status `ready`, `ready_with_open_objectives`, or `evidence_gap`).

### The segmenter

The split is deterministic (sentence boundaries, contract part, about 34 words a scene, at most
50), so no model can reword the approved text; `check_words_preserved` refuses any difference. A
single model call plans the pictures; an anchor that is not a verbatim phrase of its scene is
dropped and replaced by the sentence's first words, with about one picture per 8 spoken words
(`STORY_CONTRACT_VISUAL_PLAN=0` skips the call). The role on each scene is a picture and palette
label for the renderer. It is taken from the contract part and moved to a role whose accepted claim
kinds cover the scene's claims, so the hard claim ledger never refuses a true fact because of its
label. A run of scenes in one role becomes one beat told in parts (`event_03`, `event_03b`, ...),
the shape `jobs/lionfish-v2/hand_build.py` resumed with.

### Gate policy in the pipeline

| Gate | Where | Lane behaviour |
|---|---|---|
| Claim ledger | unchanged | hard |
| Storyboard integrity (`NO_STEPS`, `NO_RUNTIME`, `UNKNOWN_ROLE`, `DANGLING_CAUSE`, `BACKWARD_CAUSE`), location budget, human intent | `illustrated_story.build_storyboard` | hard |
| Every other `causal_story` code (role order, escalation count, hinge, hook, close, synthesis, sentence-mix) | same | reported with `[report only, story_contract lane]` |
| `story_shape` findings | same | not applied |
| Hook and hinge fitting, the opening read and its revision, the storyboard repair, the measured-audio refit | `explainer_pipeline` | skipped (each rewrites narration) |
| Turn budget | `_record_lane_turn` | structural measure stamped `report_only`; recorded in run_result |
| Readiness "Narrative propulsion" | `score_retention_readiness` | scored and printed, left out of the grade |
| `opening_retry` below B | `_stop_if_opening_below_b` | `continued_below_b`, marked degraded, not stopped |
| Compiled spine (`unvalidated_compiled_story`) | `validate_longform_story` | not asked of the lane |
| Any word changed after approval | `check_approved_narration`, before the first TTS or image | stops (`STORY_CONTRACT_NARRATION_CHANGED`) and writes `narration_changed_for_approval.md` |

### Calibration and the first dry run

- `evals/promptfoo/story_reviewer.yaml`: the reviewer compares lionfish v1 (the compiled catalogue)
  with v2 (the Carlson rewrite) in both orders, on a neutral brief. On 2026-10-21 `gpt-5.6-luna`
  preferred v2 in both orders, with 5-6 reasons quoting it verbatim. It scored v2 3/3 on every
  item, so the rubric is saturated at the top and does not yet separate good from very good.
- Dry run on the cached lionfish v2 dossier (`jobs/lionfish-contract`, OpenAI, contract approved
  as written for the test): 12 calls, 87,913 input and 23,575 output tokens, $0.91 at the default
  rate estimate, reaching the narration stop after both repairs (v1 and v2 had 3 factual blockers
  each, v3 had none and 2 open objectives). Findings for the next iteration: the writer produced
  1,320 words against a ~776-word target; the contract planned 9 developments, one a list of
  spread dates the contract check cannot see; two sentences leak prompt language (now flagged as
  `PROMPT_LEAK`) that the reviewer did not mark.
