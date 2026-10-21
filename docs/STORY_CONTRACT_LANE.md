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

## Second iteration (operator fixes, 2026-10-21)

After the first dry run (1,321 words, mean sentence 21, backstory rewind at sentence 7, the
paradox at sentence 54 of 61, the reviewer's 23/24) the operator asked for four fixes:

1. **Question choice.** The contract proposes three candidate central questions, each scored 0-3
   for curiosity (a gap the title does not already close), support and deliverable, and chooses
   one; `contract_for_approval.md` shows all three. `QUESTION_IS_TITLE` refuses a chosen question
   whose content words overlap the commission title by 0.6 or more (Jaccard).
2. **Length enforced.** Over 110% of the word target (`duration x 2.588 w/s`) is `LENGTH_OVER`, a
   blocker that goes back for cuts inside the shared two-pass budget. Still over after the budget:
   status `not_ready`, with the overage in `not_ready_reasons`.
3. **Spoken voice** (`voice_metrics`, the table in `narration_for_approval.md`). Blockers:
   mean sentence over 15 words (`SENTENCE_MEAN_LONG`), more than 2 source attributions a spoken
   minute (`ATTRIBUTION_DENSE`, counted against at least one minute), origin or backstory before
   both the central question and the person are heard (`BACKSTORY_BEFORE_QUESTION`: a rewind cue
   or a year more than ten years back), and `PROMPT_LEAK`. A sentence over 30 words is a flag, not
   a blocker, because the reference v2 has one 31-word sentence. Writer and reviewer prompts carry
   the same rules; the reviewer sees the measured numbers. Definitions: sentences split at `.!?`;
   numbers are digit groups and number words; attributions are "according to", said/says/told,
   reported, researchers, scientists, experts, study/studies, model/modelled/projected/estimated,
   surveys, NOAA/USGS/FWC, officials. On the three lionfish scripts these give v1 832 words / mean
   14.1 / 6 over 25 / 1.68 attributions a minute; v2 838 / 8.8 / 2 / 1.30; lane draft 1 1,321 /
   21.0 / 17 / 2.94. v2 clears every blocker.
4. **Reviewer calibration.** The rubric's 3 now means "distinctive", and the quote and note must
   name what is distinctive. `story_reviewer.yaml` ranks three scripts (v2, lane draft 1 at sha
   34c3e8f2, v1) in all six presentation orders on gpt-5.6-luna and claude-sonnet-5-5, expecting
   v2 > draft 1 > v1.

**Eval result (2026-10-21, $0.34):** 11 of 12 cases parsed (one luna reply was not JSON). Both
reviewers ranked v2 first in all 11. Both ranked **v1 above draft 1** in all 11, so the expected
order fails on that step. That is the judges disagreeing with the expected order, not noise: draft
1 is 59% longer than v1 with sentences half as long again. The rubric was not tuned to force the
order. Whether draft 1 should beat v1 is an operator decision. (The first attempt at this eval
passed list-valued vars, which promptfoo expands into one case per item; every case saw one
narration and the run, $1.49, was discarded. The vars are comma-separated strings now.)

**Dry run 2** (`jobs/lionfish-contract-v2`, Anthropic: claude-opus-5-5 writes, claude-sonnet-5-5
reviews; the same cached dossier; the contract approved as written for the test; the narration
NOT approved):
- Question chosen: "If Florida can never eat its way out of the lionfish invasion, what is all the
  hunting and eating actually for?" (9/9). Candidates: "Why does turning lionfish into a delicacy
  work against itself?" (8/9, the v2 paradox; judged to end on failure with no resolution); "Can a
  fish with no predators find one at the dinner table?" (6/9, "essentially the title restated").
- Narration v3 of 3 (sha 5aca77ae): 723 words (target 776), ~279 s, 79 sentences, mean 8.9 words,
  0 over 25, longest 20, 3.3 numbers and 0.8 attributions per 100 words, 1.29 attributions a
  minute. The question is heard at sentence 10 of 79; the paradox ("the better the harvest works,
  the worse it pays") at sentence 48. The aquarium-trade origin is at sentences 14-18, after the
  question.
- Reviewer: 20/24, no factual blockers, 3 open objectives; status `ready_with_open_objectives`.
  Candidates: v1 3 blockers / ATTRIBUTION_DENSE, v2 4 blockers, v3 0.
- Spend: 15 calls, 188,100 input and 80,372 output tokens, $1.75 (opus $1.14, sonnet $0.61). That
  includes three calls lost to two bugs fixed in this iteration: a thinking block read as the
  reply, and a review cut off at max_tokens.

## Third iteration (operator, 2026-10-21)

1. **Eval order corrected** to the operator's: v2 > v1 > lane draft 1 (34c3e8f2), and v2 > lane
   draft 2 (5aca77ae) > draft 1; draft 2 against v1 is not asserted. Four narrations, eight orders
   (four rotations and their reverses), luna and sonnet; `asserts.py:reviewer_orders_pairs`.
   Result ($0.54): 9 of 16 cases passed (luna 5/8, sonnet 4/8). By pair: v2 > v1 16/16, draft 2 >
   draft 1 16/16, v1 > draft 1 13/16 (all three misses on sonnet), **v2 > draft 2 11/16**. Draft 2
   was ranked first in 5 orders, so the reviewer cannot yet reliably separate the reference from
   the lane's best draft. Not tuned.
2. **Numbers cap:** `NUMBER_DENSE` above 2 numbers a spoken minute (v2 1.85; v1 3.9; draft 2
   5.15), a blocker. The reviewer lists `numbers_without_purpose`, which become an objective.
3. **Removal test per development** (`development_removal`): a development whose passage would not
   change the answer is a side story and becomes the first objective; one already absent from the
   narration is reported, not repaired. `LIST_FRAMING` is a deterministic blocker for counted
   obstacles ("a third limit", "the second wall"; draft 2 sentence 54, v1's walls); the reviewer
   also reports `parallel_obstacle_lists`.
4. **Question scoring:** an honest partial answer or a named constraint is a valid ending.
   Marking a candidate down for it ("ends on a constraint with little resolution", "rather than an
   answer") is `QUESTION_PENALISED_FOR_NO_FIX`, an error that sends the contract back for its one
   corrected attempt; a cached contract is re-checked under the current rules.
5. **Humour:** the reviewer credits situational humour under `voice`, calibrated on three v2 lines
   (`HUMOR_EXAMPLES`), and is told never to ask for jokes.

**Dry run 3** (`jobs/lionfish-contract-v3`, Anthropic, contract approved as written for the
test, narration NOT approved):
- The first contract marked the paradox question down for "a constraint with little resolution"
  (7/9); the rule sent it back, and the corrected contract scored it 9/9. Chosen (9/9, a tie):
  "If divers can pull a record 36,000 lionfish out of Florida waters in one summer, why does the
  hunt never get to end?" Others: "Why would a seafood market built to destroy lionfish eventually
  undermine itself?" (9/9, kept as the complication); "Why did a federal food agency frown on the
  campaign to eat lionfish?" (8/9).
- Narration v3 of 3 (sha 26d0bc52): 650 words (target 776), ~251 s, 70 sentences, mean 9.3, 0 over
  25, 1.4 numbers / 100 words (2.15 a minute), 1.7 attributions / 100 words (2.63 a minute).
  Question at sentence 10 of 70. Ciguatera was cut by the writer. No factual blockers; rubric 17/24.
- **Status `not_ready`**: NUMBER_DENSE (2.15 > 2) and ATTRIBUTION_DENSE (2.63 > 2) still open
  after both repairs. Candidate 2 (4c92c659) had only ATTRIBUTION_DENSE but two factual blockers,
  so the factually clean v3 was offered.
- Spend: $1.81.
- Two reporting bugs found and fixed after the run: the reviewer's "side story" flag on
  developments already absent from the narration became "cut this" objectives in the repair notes,
  and quotes carrying the reviewer's "[34]" sentence markers failed verification.
