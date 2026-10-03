# Script repair integrity

Production regression: Studio job `72d6e8da` on PR148 generated a 16-scene draft but failed
the claim ledger. A 19-word hook and 12-word hinge triggered a full story replan; fact-check
corrections outgrew stale events; substring trimming then produced incomplete sentences.

## Behavior

- A contract blocked only by `LONG_HOOK`, `MULTI_SENTENCE_HOOK`, and/or `SOFT_HINGE` uses
  the existing bounded hook and hinge rewrites. A rejected rewrite retains the draft and
  its failures for the final gates instead of regenerating the story. Other structural
  failures retain the existing replan policy.
- Fact-check responses may propose `event_updates` for changed scenes, identifying existing
  claim IDs. The existing scope/kind checks, source-to-event entailment and event-to-narration
  fidelity must pass before the event and narration bindings change. A failed proposal
  keeps the prior event and corrected narration for the final ledger to reject. It never
  makes the fact-checker's notes authoritative evidence. Derived events cannot be changed
  by this path. The final full-script ledger and relationship checks remain mandatory.
- The deterministic trim only removes complete unbound sentences or comma-delimited
  purpose adjuncts. Arbitrary interior spans and predicates require a rewrite. It preserves
  the hook, overlapping source bindings, and at least one sentence per scene.
- A shared fragment guard rejects dangling constructions at the editor, claim repair,
  hook/hinge repair, fact-check and final ledger boundaries. This is a conservative check
  for incomplete repairs, not a comprehensive English grammar or editorial quality score.
- Evidence judgments use the existing content-addressed cache, and their costs are included
  in fact-check cost. Rejected model responses retain their billed cost. No media or live
  provider calls are required by the offline regression tests.

## Verification

`tests/test_script_repair_integrity.py` covers the production fragments, local repair versus
replan, event correction acceptance/rejection, source-scope isolation, derived-event locks,
cost accounting, editor budgets and final ledger rejection. Provider responses and semantic
judgments are mocked; the suite's network guard prevents external calls.

Known baseline failure: `test_opening_questions_are_judged_with_the_hook_not_against_beat_one`
in `tests/test_claim_ledger_trim.py` also fails on untouched main `aa276a8`. It concerns an
opening question without a cold open and is outside these repairs.

A passing offline test does not establish a passing production script. Rerun the script-only
Studio scenario after deployment; retain all evidence and storyboard gates.
