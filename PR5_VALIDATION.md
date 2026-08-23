# PR 5 Validation — Animatic and Rendered-Story Gates

This document is the merge disposition for PR 5 of `LONGFORM_BOLT_EXPLAINER_ROADMAP.md`.

## Requirement disposition

| Roadmap requirement | Disposition | Evidence |
|---|---|---|
| Low-cost animatic gate | PASS | Final-speed TTS is assembled with locally rendered storyboard cards before the first paid visual asset; six required story facts fail closed |
| Per-cut and midpoint sequential inspection | PASS | The encoded opening is sampled at every shot midpoint and both sides of every declared cut; frames are written in chronology and compiled into a numbered contact sheet |
| Deterministic visual-state checks | PASS | Encoded source changes and caption-excluded center-frame pixel deltas are measured separately from declared evidence |
| Deterministic source-reuse checks | PASS | Stable evidence asset IDs measure distinct sources, source-change ratio, and slideshow reuse |
| Deterministic character-frequency checks | PASS | Per-state pixel-verifier results measure Bolt frequency, pure-evidence violations, and continuity failures |
| Deterministic hold checks | PASS | Opening visual states must average 1.8–3.2 seconds with no state over 3.5 seconds |
| Per-cut required-object/state verification | PASS | Every midpoint record carries its state-before/state-after, required objects, verifier result, reasons, and frame hash; any unverified cut is a hard failure |
| Blind rendered-story judge | PASS — fail-closed | The judge receives only the chronological contact sheet and timestamped narration—not title, thumbnail, planner metadata, prompts, expected objects, or rubric answers; invalid output rejects |
| Automated observations checked against deterministic facts | PASS | Blind claims of multi-shot storytelling, evidence accumulation, low Bolt use, or non-slideshow behavior are revoked when encoded facts disagree |
| Human review checklist and approval record | PASS | Six editorial checks, reviewer identity, UTC decision time, report hash, and preview hash are required; approval cannot bind to changed bytes |
| Human approval before remaining spend | PASS | An automated pass raises `HumanReviewRequired`; the job becomes `awaiting_review`; only a hash-bound approval plus explicit resume can reach later scene generation |
| Developer-only rejected diagnostic mode | PASS | Requires explicit diagnostic env and is disabled in production; the artifact is watermarked `REJECTED DIAGNOSTIC`, reports false for PASS/publishable, and cannot authorize later spend |
| New frozen 100-point rendered contract | PASS | Implements the roadmap's 15/15/20/15/10/10/5/5/3/2 categories, 85 opening floor, hard-failure cap, 49 slideshow cap, and 59 unsupported-claim cap |
| Old Moon diagnostic scores 39% | PASS | Frozen regression fixture asserts exactly 39/100 and F |
| Failed opening cannot purchase later assets or report PASS | PASS | Rejection or pending human review occurs before `_gen_assets` receives `opening_stop:` indices; the advisory environment escape hatch is removed for long-form |

## Seeded rejection matrix

The following adversarial fixtures independently reject:

- Bolt in every shot;
- slideshow/source reuse;
- visual states held beyond 3.5 seconds;
- broken human/location/object continuity;
- a false belief that no evidence changes;
- three-beat consequence enumeration;
- invalid or unavailable blind judge output;
- an unverified rendered cut;
- production diagnostic bypass;
- stale human approval after report or preview mutation.

## Verification

```text
python -m py_compile longform_rendered_gate.py explainer_pipeline.py app.py
pytest -q
node --check < extracted static/index.html script
python -m build --wheel --sdist
git diff --check
```

Result at completion: **150 passed**. The test suite includes real H.264 generation, midpoint and cut-boundary extraction, pixel-delta measurement, contact-sheet rendering, final-TTS animatic assembly, and a decodable watermarked diagnostic encode.

## Important behavioral change

A successful automated opening is not a final PASS. It reports `AUTOMATED_PASS_AWAITING_HUMAN`, pauses the job, and exposes the encoded preview, contact sheet, rubric, and checklist. The UI submits a hash-bound approve/reject decision. Approval resumes from the existing checkpoint; rejection buys no later visual assets.

## Known limitation assigned to PR 6

The pause/resume protocol is deliberately correct but still backed by the current local checkpoint and in-process job registry. It is not reliable across Vercel worker replacement. PR 6 must persist the job, review, events, stage hashes, assets, and resume command in Postgres/Blob and move execution to a durable workflow/queue.

## Rollback

- Pre-PR5 production baseline: `checkpoint/pre-pr5-main-abc6963`

PR5 can be reverted as one commit without reverting PRs 1–4 or the roadmap.
