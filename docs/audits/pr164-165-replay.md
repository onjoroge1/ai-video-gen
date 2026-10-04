# PR164/165 saved-input replay and matched writer experiment

The deterministic replay is complete. The live provider comparison has **not run** on this branch. These results do not establish factual approval, better writing, or audience retention.

## Exact records

- PR164: Studio job `sr-3decb63eed0999aa6cdbfa026c7a`, `claim_failure.script`.
- PR165: Studio job `sr-42177d95273857aafb6322f229d6`, `polish.input_script` (the post-claim-repair input to editorial polish).
- The PR165 evaluation starts from the PR164 parent script. The second fixture records what actually reached polish, rather than falsely describing it as a new initial generation.
- Full script objects are preserved in `tests/fixtures/pr164_saved_script.json` and `pr165_saved_script.json`; exported from the authenticated Studio's rendered JSON reports, not reconstructed from memory.
- `scripts/replay_saved_scripts.py` runs each through `script_revisions.prepare/restore` without providers. Its offline title/checkpoint values are explicitly marked synthetic; the script payloads are exact. Hashes and exact diffs are in `pr164-165-replay.json`.

## Repairs and boundaries

The old hinge referenced only `event_04`; it now also references accepted same-case `event_01` (problem) and `event_02` (intervention). The old callback referenced `event_04` and `event_09`; it now also references those two anchors. Explicit hook context is retained. Migration preserves narration, events, claim IDs and paragraph order; mismatched accepted facts, identities, case boundaries or missing references stop the job. It does not manufacture a semantic pass.

The Northland source reports 19 of 31 identified-cause chick deaths and 63%. The arithmetic is approximately 61.29%, but that does not establish which published number is wrong. This source-specific adjudication uses the reported count, omits the percentage, and keeps the original quote unchanged. The working ledger, accepted events and narration agree. The before/after report preserves the original ledger statement and calculation. Unknown source/quote variants are not automatically corrected; unsupported alternate narration wording fails rather than receiving a broad numerical rewrite. This is an explicit adjudication of one known conflict, not a general numerical fact checker.

The replacement spoken sentence is: “Where the agent could be identified, stoats were responsible for 19 of 31 identified-cause chick deaths.” It remains open to editorial improvement, but no longer asks the judge to reconcile two incompatible numbers.

## Matched comparison protocol

Studio adds **Compare writing flows**, with one shared default $5 application reservation/settlement cap. Four provider calls maximum: two drafts and two common reviews. No media calls, no automatic approval, and no semantic retry loop. Existing durable provider replay and stage checkpoints preserve paid responses and rejected drafts.

Both arms receive identical reconciled evidence, question, duration, operator direction, provider/model identity, system message and output-token ceiling. Temperature is omitted on both, using the same provider default. Exact prompts, schemas, responses, input hashes and costs are retained. Current arm uses the existing seven-section drafting prompt/schema; document arm treats the evidence paragraphs as reference material rather than mandatory narration slots. Both use the same review prompt/schema. Reviews see narration and evidence, not the arm label. A/B display hides arm names in the initial reading view; the diagnostic report exposes the mapping, so this is not a formal blinded trial.

This isolates the **writer and common review**. It does not compare end-to-end research, plan selection, production targeted-repair loops or final grading. It must not be presented as a whole-flow win. The next decision is whether a whole-document writer improves the actual prose enough to justify adapting the downstream gates. One paired story is a diagnostic example, not a retention benchmark.

## Deployment and live continuation

The authenticated production Studio was still running PR165 during implementation. This workspace has no production provider credentials. After deploying this change, open the PR165 job and run **Compare writing flows** under the shared $5 cap. Separately, **Evaluate and repair saved script** exercises the migrated contexts and reconciled numbers through the existing full acceptance gates. Neither action should be called successful until its saved production report exists.

Keep a human assessment of earned hook, causal progression, new information, sentence cadence, repetition and callback alongside factual findings, contract failures, spend and completed calls. Do not pick a winner solely from a model-generated score.
