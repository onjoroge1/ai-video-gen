# Scene contracts after the PR160 Studio run

## Observed failure

Production job `2bc5ef3a`, on `bc87febe5dd64b62af640f53506db94838a03d68`, failed
at the claim-ledger gate after about 22 minutes and $4.51 recorded spend. No media
was produced. These changes address measured failures, not a claim of guaranteed
creative quality or zero future provider errors.

- A replan returned six of seven requested expansion rows. A whole-batch retry
  also missed the count, so the otherwise usable replan was discarded.
- The retained draft had two separate reversal beats. Splitting either into
  screen-time parts was legitimate; having two separate story turns was not.
- Some callbacks referred to the evidenced original intervention, but their
  scene-local factual ceiling omitted it. Other failures were real inventions
  about ruin, warnings, nesting, and trap learning; those still must be removed.
- A narration repair reduced ten errors to eight. A new review noticed `today`
  in unchanged scene 10 and the acceptance comparison rejected the entire edit.
- The title implied that harming kiwi was deliberate. The targeted claim editor
  had no title-repair route after the fact-check candidate was rejected.
- The finalizer appended a period after a question mark. This was a code defect.

`tests/fixtures/2bc5ef3a_scene_repair.json` preserves the relevant observed scene
fields and review reports. It is regression evidence, not an approved script or
an assertion that the historical claims are true.

## Reused capabilities

| Capability | Verified location/state | Use in this change |
| --- | --- | --- |
| Dramatron-inspired planner | `story_planner.py`, merged | Score compiled role cardinality before purchasing expansion. |
| Beat/scene identity and screen-time splitting | `story_compiler.py`, merged | Assign IDs before writing and keep each accepted row under that identity. |
| Structured narration response parser | `storyboard_repair.py`, merged | Reuse tool-result parsing without buying a JSON repair. |
| Durable provider accounting and semantic checkpoints | `durable_execution`, `script_stages.py`, merged | Preserve partial rows, attempt counts, terminal failure and charged responses across workers. |
| Targeted editors and Promptfoo production adapters | `script_editor.py`, `evals/promptfoo`, merged | Keep evidence context consistent in production and evaluation prompts. |
| Shared storyboard / ViMax import design | PR124, open draft; inspected head `4bf7597b` | Reuse the explicit-ID/exact-coverage design principle. No dependency on its unmerged package. |
| MoneyPrinterTurbo, Motion Canvas, OpenShorts | PR124 plus PR125, both unmerged; PR125 targets PR124's branch | Useful for rendering/repurposing after script acceptance. Not available production writing tools. |
| ShortGPT | Gitlink `3df4e0f7`, source not checked out here | No runtime reuse or readiness claim. |

PR124's workbench is a draft storyboard feature; PR125 adds bounded local-media
jobs and requires a persistent render worker. Neither should be described as an
installed production scene writer. No large render dependencies are added here.

## Changed flow

1. Compile factual roles and detect multiple occupants of a single-turn role.
   The existing one-shot mechanical correction may reclassify labels while
   retaining event text and citations. Evidence/spine validation still follows.
2. Assign scene IDs before expansion. Request at most four rows per initial
   causal batch through an output-only tool. Reconcile by ID, not position.
3. Persist structurally valid rows. Retry only missing or malformed rows,
   individually, with at most two total attempts per row. Duplicate IDs cannot
   choose a winner; unknown IDs cannot occupy another beat's slot. Exhausted
   attempts stay exhausted after resume. These records are not factual passes.
4. Bind later scenes to the accepted setup/intervention as explicit context.
   Existing mechanism/reversal context is retained. Cross-case, unknown, empty
   and self context references fail structurally; unsupported context cannot
   raise the narration ceiling. Writers, fact-checkers and editors receive the
   same named context events. Final acceptance hashes include those bindings.
5. Compare edits using exact changed inputs. A newly discovered grammar/time/
   metric defect can count as preexisting only with the same scene identity,
   narration, event, context, evidence and an exact quote. Global causal,
   continuity and hook-payment regressions remain vetoes. The audit records
   the reconciled baseline; all remaining findings still block final delivery.
   Known local findings persist for identical scene/evidence inputs, including
   when replaying an older whole-story clean result. Changing another scene
   cannot make an unresolved defect disappear through judge variation.
6. Repair a flagged title from existing story events, and preserve question
   punctuation when assembling the spoken opening. A malformed targeted edit
   uses its existing attempt and cost; no extra JSON-repair call is purchased.
7. Run the existing evidence, integrity, storyboard, cadence, runtime and final
   editorial gates. Provider/budget/lease/storage stops propagate through replan
   handling. Preliminary grades no longer say the script is being shipped.

Anthropic receives the forced output tool. The existing OpenAI compatibility
adapter receives a JSON schema; expansion permits additional visual fields and
uses local ID/coverage validation rather than claiming strict schema enforcement.
Narration-only edit schemas retain their existing strict behavior.

## Verification and next production measurement

Offline tests cover the actual 10-to-8-error comparison, duplicate and missing
IDs, truncated responses, partial checkpoint restoration on another worker,
exhausted retry budgets, provider accounting/replay, title-only repair, context
boundaries, approved-content invalidation, and question punctuation. Model
responses in these tests are fixtures; they do not establish writing quality.

After merge and deployment, use one authenticated Studio **fresh script-only**
job for the same 180-second stoat/kiwi topic and existing bounded spending scope.
A fresh job exercises planning and expansion. Evaluating an old saved draft
does not retroactively exercise those changes or rebuild its context bindings.
Do not restart the failed job simply because the PR merged.

Capture the job/commit/provider, requested and returned scene IDs, per-row
attempts, saved partial results, evidence/integrity findings, repair audit,
finished narration, final gate reports, elapsed time and actual spend. Success
requires zero blocking findings on the exact delivered text, complete scene
coverage, and passing final editorial/readiness gates. Read the hook, causal
progression and closing callback aloud before calling the result ship-ready.

Still unproven: how often the live writer needs the second attempt, live judge
consistency, real editorial quality after repairs, and cost/latency under the
smaller batch size. A transient judge outage still fails closed after its bounded
review attempts. YouTube retention requires actual audience measurement; an
automatic grade is not that measurement.
