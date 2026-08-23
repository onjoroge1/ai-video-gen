# PR 4 Validation — Story-Role Motion and Final-Edit Compiler

This document is the merge disposition for PR 4 of `LONGFORM_BOLT_EXPLAINER_ROADMAP.md`.

## Requirement disposition

| Roadmap requirement | Disposition | Evidence |
|---|---|---|
| Stills, Standard, and Full Motion operate on evidence states | PASS | The API/UI expose the three modes; long-form selection and clip paths use stable evidence `state_id`/`asset_id` values rather than scene indices |
| Role-prioritized Standard motion | PASS | Standard reserves motion for hook, prediction/test, reversal, reveal/payoff, and callback classes before filling remaining capacity by deterministic story-role priority |
| Phrase-aligned transitions | PASS — fail-closed | Selected state anchors must be exact final-narration phrases; measured word timings drive the actual cut plan before image/I2V purchase, and final motion alignment below 90 percent rejects |
| Actual final-opening I2V generated before gate | PASS | Selected opening evidence clips are generated before `_render_first_minute_preview`; a requested motion treatment with no real opening motion aborts before later visual assets |
| Motion success, fallback, and cost reporting | PASS | Every selected state records provider attempts, provider, success/fallback, fallback reason, cache reuse, source/prompt identity, and actual motion cost in `motion_report.json` |
| Frozen approved opening reused by final edit | PASS | Preview scene segments and opening motion clips are SHA-256 frozen; the final scene loop directly reuses those exact segments and revalidates every hash before assembly completion |
| Stills purchases zero I2V | PASS | Stills selects zero motion candidates and the long-form motion generator returns without a provider request |
| Standard prioritizes hook, test, reversal, reveal, callback | PASS | Adversarial selection fixture and prior Moon-plan stress test both cover every available priority class, including the exact opening-object callback |
| Full requests every eligible state within cap | PASS | Full selects all eligible states when they fit; above the cap it deterministically distributes the complete cap across the narrative, including first and last eligible states, and reports capped-out count |
| Gated opening and final opening match in content | PASS | The final edit does not rerender approved opening scenes; it consumes the exact frozen files used to build the preview |
| Motion semantic alignment at least 90 percent | PASS | Both pre-spend measured-timing validation and post-render shot metrics enforce the 0.90 floor |
| Slow motion, captions, and Ken Burns do not count as evidence | PASS | `new_information` remains owned exclusively by PR3 pixel verification; generated motion, retiming, captions, and camera motion cannot create a verified-information event |
| Resume cannot reuse semantically stale motion | PASS | Cached clips require the same evidence-image SHA-256, motion-prompt SHA-256, state ID, and duration before reuse |
| Motion controls and reports available in product | PASS | The restored UI selector and downloadable Motion Report/Opening Freeze controls have API routes and durable-ready artifact hooks |

## Verification result

Commands:

```text
python -m py_compile longform_motion.py longform_evidence.py longform_shots.py explainer_pipeline.py app.py
PYTHONPATH=. .venv/bin/pytest -q
.venv/bin/python -m build --wheel --sdist
git diff --check
```

Result at completion: **132 passed**; package build and whitespace validation passed.

Local encoded-edit smoke test:

- built two evidence states, a real five-second H.264 motion source, and six-second narration;
- rendered the actual multi-shot opening-preview path at 320×180;
- output decoded at 6.0 seconds with one real I2V state and two verified-information states;
- measured motion semantic alignment was 100 percent;
- the approved segment and motion clip passed the opening SHA freeze.

Compatibility stress test against the prior 90-second Moon mystery plan:

- 35 motion-eligible evidence states were detected;
- Stills selected 0;
- Standard selected the 12-state cap and covered hook, prediction/test, reversal, reveal, and callback classes;
- Full Motion selected the 12-state cap across scenes 1–17 rather than exhausting it in the opening;
- both Standard and Full included the opening-object callback and reported 100 percent planned semantic alignment.

The old Moon checkpoint predates the human-led PR1 contract, so it remains a compiler compatibility fixture—not a quality pilot.

## Fail-closed order

1. Measured narration and the final evidence plan pass.
2. Motion mode is normalized; explicit Standard/Full requires a configured provider.
3. Cost headroom determines the hard motion request cap.
4. Story-role selection and measured phrase timing pass before image or I2V purchase.
5. Opening evidence assets are pixel-verified.
6. Selected opening I2V is generated and reported before the 45-second edit.
7. The opening must render, pass readiness, and freeze before later visual purchase.
8. Remaining motion is attempted with explicit fallback and cost-cap reasons.
9. Final motion alignment must remain at least 90 percent.
10. Frozen opening hashes are checked again and the same segments are used in final assembly.

## Known limitations and non-goals

- This PR proves motion selection, semantic timing, actual edit routing, fallback honesty, and opening reuse. It does not yet judge whether generated motion is aesthetically convincing; sequential rendered-pixel judgment belongs to PR5.
- A failed selected opening motion treatment stops the job instead of silently shipping a Standard/Full video as Stills. Operators can deliberately select Stills when providers are unavailable.
- Full Motion remains constrained by the configured dollar cap and `MAX_I2V_CLIPS`; it reports states excluded by the cap instead of pretending the entire video was animated.
- Provider success does not prove physical accuracy. PR5's blind rendered-story inspection and PR7/PR8 controlled paid pilots remain required.
- The controlled provider-cost pilots are intentionally not spent in this PR. PR7 validates 45-second Standard and Mystery openings; PR8 validates the complete 90-second edit.
- Opening segments and motion clips are locally frozen but not yet durable across workers. Blob/Postgres persistence and cross-worker recovery belong to PR6.

## Rollback

- Pre-PR4 production baseline: `checkpoint/pre-pr4-main-2360054`

PR4 can be reverted as one commit without reverting PRs 1–3 or the roadmap.
