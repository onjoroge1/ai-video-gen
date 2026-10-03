# Final sourced-script editorial pass

Production Script Only job `7cab298a` on PR149 passed research and claim repair but stopped
at the final storyboard gate. The mechanism arrived at 34 seconds against a 28-second
limit. Its narration repair returned extra fields and was rejected. The earlier engagement
score was 73 (hook 80, story 72, ending 74, repetition 58, cadence 77), before the final
claim edits, so it could not establish the quality of the delivered words.

This change addresses that observed path:

- Timing/callback errors reported by both validators stay on the bounded local repair path.
  Structural errors and unexplained validation failures still require the existing replan.
- The first storyboard repair receives exact per-scene opening caps. The hook and sourced
  cold open reserve space in the budget. Repairs preserve both and reject incomplete tails.
- The provider receives a forced narration-only response schema. Native Anthropic tool-use
  blocks and their durable replay are decoded; OpenAI translates this output-only tool to
  strict JSON schema. Server-side research tools still require native Anthropic in durable runs.
- Sourced illustrated scripts receive a fresh grade after factual and timing repairs.
  At most two editorial passes may edit at most four scenes each. Events, source references,
  order, and causal metadata cannot be rewritten by the editor. Candidates must pass the
  existing storyboard, long-form, duplicate, and claim validators. A previously passing
  runtime budget cannot regress. Overall score must improve without any axis declining.
- Script Only and `SCRIPT_GATE_HARD` require final overall, hook and story scores of at least
  `SCRIPT_GATE_PASS` (default 78), and ending, repetition and cadence of at least
  `SCRIPT_GATE_FLOOR` (default 70). Missing or invalid final grades are UNSCORED, not passes.
  Ordinary full-video runs retain their existing advisory editorial policy.

The private `retention_polish_v1.json` records input, candidate responses, validation results,
final narration identity and final score. Atomic checkpoints and durable provider identities
reuse completed work after a yield. Saved results are bound to evidence, question and thresholds.
A rejection stops additional editorial purchases; existing media prevents narration edits.
Existing job spending limits continue to apply. No new terminal-job recovery entitlement or
media approval is introduced by this change.

These scores are model editorial judgments, not measured audience retention. A production
Studio run and human review of its final script remain necessary after merge. The target is a
concrete hook, distinct causal developments, less repeated explanation and an earned callback;
unsupported drama, hidden mechanisms and manufactured certainty are not acceptable shortcuts.

## Validation

158 focused offline tests passed across repair integrity, storyboard repair, editorial acceptance
and rejection, provider schema translation/replay, hook/hinge budgets, narration bindings and
Script Only integration. Three existing HTTP dispatch cases were excluded after the first
stalled in the ASGI/event-loop test path. They were not changed by this PR. No production
provider run was performed with this unmerged code.
