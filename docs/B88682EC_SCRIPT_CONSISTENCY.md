# B88682ec: align factual editing with delivery validation

## Evidence

After PR158 recovery the saved job reviewed all 30 research claims, retained 13,
expanded an 18-scene draft and scored 79/100 preliminarily. Fact-check returned the
narration unchanged, reporting only numeric checks and subject agreement. The later
claim gate reported 12 event/narration errors and two integrity errors; both subsequent
edit candidates were rejected. The final cost was $3.99, before media spending.

The regression fixture retains the exact failed narration, events, claims and report.
It omits media directions and provider caches. Its errors are observations of the old
reviewer, not ground-truth labels for every sentence: the Guam finding itself put
'arrived by accident' in both the supported core and the unsupported detail.

## Changes

- Compiled factual scripts enter fact-checking with the same `_validate_claims` findings
  used at delivery. This includes local event ceilings, whole-script integrity and now
  title entailment against the supported events. Other existing script lanes retain
  their previous fact-check path.
- Fact-check edits occur on a copy, reconcile event updates, rebind citations, and run
  the same validator before acceptance. A no-op with unresolved errors is rejected;
  a validated partial improvement is explicitly incomplete. Provider/reviewer
  unavailability is not a prose-repair instruction. Delivery gates remain unchanged.
- Expansion explicitly treats false_resolution as a writing role, not evidence of
  initial success. Fact-check checks agency, intent versus outcome, universals and
  invented scene details, not just numbers. Matching title nouns cannot excuse an
  invented intended victim.
- First-scene repairs receive the cold open's separately cited claims and its read-only
  lead text; hook repairs can also see the story's event claims. The body event remains
  its own factual ceiling; lead evidence cannot license unrelated body assertions.
- `_edit_audit` retains candidate prose, original/candidate report, hashes, operation,
  decision and reason for fact-check, claim repair and trim. It is visible in private
  Studio and checkpointed separately. A rejected candidate never replaces narration.
- A narrow contradictory quoted-clause guard makes an internally inconsistent judgment
  indeterminate, never a pass or permission to delete prose. This is response validation,
  not a substitute for semantic evaluation. Negated supported cores are excluded.
- The second malformed entailment/integrity attempt now has a distinct request identity.
  Previously durable replay could return the identical invalid response twice. The
  attempt remains bounded and independently replayable after a restart.
- Semantic cache contracts change; the new module is included in wheel smoke checks.

## Verification and limits

Offline regression tests reproduce unchanged fact-check output on the saved draft,
rollback on new integrity failure, incomplete labeling after partial correction,
provider-unavailable refusal, title checks, cold-open evidence access, inconsistent
Guam verdict handling and distinct/replayable paid-request identities. Existing repair,
claim, integrity, planner and Studio suites also run. No paid model call or new Studio
job was made for this change. Model-generated quality remains unproven until a scoped
live evaluation; these tests verify contracts, not that a model will obey every prompt.

This change does not relax factual gates, grant a new retry to the failed job, or
claim to solve its pacing. A fuller explicit representation of hook/cold-open/body
spans is still needed to eliminate legacy exact-string synchronization risks after
lead edits. The pipeline still grades before final factual editing, so the old 79 is
not a grade of an accepted final script. Reviewer calibration needs both true failures
and acceptable paraphrases before changing semantic thresholds.
