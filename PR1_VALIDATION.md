# PR 1 Validation — Human-Led Story and Hook Planner

This document is the merge disposition for PR 1 of `LONGFORM_BOLT_EXPLAINER_ROADMAP.md`.

## Requirement disposition

| Roadmap requirement | Disposition | Evidence |
|---|---|---|
| Restore `assets/mascot/human-model.png` | PASS — deterministic test | Asset restored from Git history; PNG identity and path asserted by `test_human_reference_and_ui_controls_are_present` |
| Add documented human identity/role model | PASS — deterministic test | `HUMAN_NAME`, `HUMAN_DESC`, `HUMAN_REF`, human story fields, and reference-order test |
| Remove long-form “Bolt hosts every scene” instructions | PASS — source audit | Long-form beat and expansion prompts define Alex as lead and Bolt as optional support; remaining every-scene language is confined to separate social-short templates |
| Permit `bolt_mode=absent` in planning and fallback | PASS — deterministic test | Beat schema, expansion schema, normalizer, scene persistence, and `_apply_character_budget` tests |
| Deterministic Bolt role/presence budgets | PASS — deterministic test | ≤35% first act and ≤30% overall; excess proposals overridden and reported; mechanism/rules force absence |
| Standard and Evidence Mystery routing | PASS — deterministic test | Typed API/UI selection, distinct format prompt contracts, effective format persisted |
| Expansion preserves selected structure | PASS — deterministic test | Mystery expansion forbids roadmap narration and protects the deepest reveal; Standard expansion retains early-answer behavior |
| Topic-suitability fallback | PASS — deterministic test | Requires anomaly, false belief, contradictory evidence, location, goal, ≥3 evidence states, failed prediction/test, and belief change; unsuitable Mystery becomes Standard with a reason |
| Belief → prediction → evidence → belief change → decision | PASS — deterministic test | Version-2 contract fields plus hard `evidence_never_forces_decision` and knowledge-gap rules |
| Hook fields and timing | PASS — deterministic test | Required anomaly/opening object/goal; title subject by 5 seconds; visible human intention by 8 seconds; first payoff remains gated by 25 seconds |
| Opening-object callback | PASS — deterministic test | Case-insensitive exact callback equality; seeded mismatch fails |
| Persist selected structure and character plan | PASS — deterministic test | `_story_format*`, `_character_plan`, version-2 JSON contract, and human-readable report lines |
| Both structure fixtures pass | PASS — deterministic test | Standard and Evidence Mystery versions of the complete human-led fixture pass |
| Consequence-list fixture fails | PASS — deterministic test | Three adjacent beats without a causal/decision/belief/question turn fail |
| Decorative-Bolt fixture fails | PASS — deterministic test | Unsupported action and over-budget presence fail |
| Missing-human-goal fixture fails | PASS — deterministic test | Missing required human field fails |
| Fake-knowledge-gap fixture fails | PASS — deterministic test | Equal viewer/human knowledge across all beats fails |
| Broken-callback fixture fails | PASS — deterministic test | Different final object fails |
| Bolt absent from pure mechanism fixtures | PASS — deterministic test | `rules` and `mechanism` roles are forcibly normalized to absent |
| No paid media required | PASS — verified | Test suite makes no provider generation calls |
| Image-edit SDK supports the renderer contract | PASS — installed-code test | Production pin upgraded to `openai==2.54.0`; signature and two-reference submission are tested without a provider call |

## Test result

Run:

```text
.venv/bin/python -m pytest -q
```

Result at completion: **74 passed**.

## Known limitations and non-goals

- This PR proves the story plan, character selection, hook contract, report persistence, and identity-reference routing. It does not claim that generated pixels preserve identity; continuity generation and pixel verification belong to PR 3.
- It does not claim that metadata alone proves a good rendered story. Animatic and rendered-story proof belong to PR 5 and controlled pilots to PR 7.
- It does not add the research claim ledger or measured TTS timing; those belong to PR 2.
- Social simulation/curiosity templates retain their existing Bolt-led behavior. This PR changes long-form only.
- No paid model call was used as acceptance evidence.

## Rollback

- Production baseline: `checkpoint/pre-pr1-main-650e680`
- Roadmap checkpoint: `checkpoint/pre-pr1-roadmap-d5569fc`
- Previous local evidence build: `checkpoint/pre-pr1-evidence-v4-8330407`

PR 1 can be reverted as one commit without reverting the roadmap.
