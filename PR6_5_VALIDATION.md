# PR 6.5 Validation — Rendered-Gate Threshold Calibration

## Why this phase exists

PR 5 made an uncalibrated threshold profile a **hard-contract failure**. That was the right call —
an unvalidated `pixel_delta >= 0.035` should not be allowed to produce a passing grade. But it
closed a door without building the other one: `calibrate_rendered_gate.py` consumes a human-labeled
dataset, and **nothing in the repository produced one**.

The consequence was structural rather than cosmetic. `inspect_rendered_opening` emits
`boundary_deltas` with real per-cut measurements; `calibrate_threshold_profile` consumes samples
keyed by `sample_id`; no code joined them. A flawless synthetic opening — every deterministic
measure ideal, judge fully positive, human approved — scores:

```
score      : 69 /100
status     : REJECT
hard fails : ['uncalibrated_rendered_thresholds']
```

PR 7's acceptance bar is "both pilots score at least 85/100". That was **unreachable by
construction**, and a PR 7 failure would have said nothing about the video. This phase builds the
missing path.

## What ships

| Piece | Location |
|---|---|
| `harvest_calibration_samples` — inspections → unlabeled worksheet | `longform_rendered_gate.py` |
| `calibration_readiness` — what is still missing, per class | `longform_rendered_gate.py` |
| `load_labeled_samples` — validate labels → calibration input | `longform_rendered_gate.py` |
| `harvest` / `status` / `compile` CLI | `scripts/harvest_gate_samples.py` |
| Roadmap phase, gate prerequisite, and provider-identifier rule | `LONGFORM_BOLT_EXPLAINER_ROADMAP.md` |

Operator path, end to end:

```
harvest_gate_samples.py harvest  inspection*.json worksheet.json
# editor fills meaningful_change / slideshow on each row
harvest_gate_samples.py status   worksheet.json          # names the exact shortfall
harvest_gate_samples.py compile  worksheet.json samples.json
calibrate_rendered_gate.py       samples.json profile.json --reviewer "<editor>"
```

## Requirement disposition

| Requirement | Implementation | Disposition |
|---|---|---|
| Real renders become labelable rows | One row per boundary cut, carrying the measured `pixel_delta`, the video-level `source_change_ratio`, and a `sample_id` derived from the video's SHA-256 so a row is traceable to real bytes | PASS — verified against genuine `inspect_rendered_opening` output on a real encode (`test_harvest_consumes_genuine_inspect_rendered_opening_output`) |
| Labels are never derived from planner metadata | `meaningful_change` and `slideshow` are emitted as `null`. `declared_new_information` is carried in a `context` block for the editor's eye and is never copied into a label — it is precisely the field the pixel threshold exists to audit, so seeding from it would let the planner calibrate its own auditor | PASS — deterministic test (`test_harvested_labels_start_empty_and_are_not_seeded_from_planner_metadata`) |
| Frames exist to label from | `inspect_rendered_opening` already writes `cut_NNN_before.jpg` / `cut_NNN_after.jpg`; the real-encode test asserts they are present and non-empty | PASS — verified in real artifact |
| Partial work is visible, not silently dropped | `calibration_readiness` separates unlabeled from malformed rows and names each shortfall — including a half-labeled row or a non-boolean label | PASS — deterministic test (`test_a_partially_labeled_row_is_malformed_not_silently_dropped`, `test_readiness_names_the_exact_shortfall_per_class`) |
| ≥20 labeled examples per class | Enforced by the existing `calibrate_threshold_profile`; surfaced ahead of time by readiness | PASS — deterministic test |
| A video-level label is supported by more than one video | **New constraint.** `slideshow` and `source_change_ratio` describe a whole video, not a cut, so 20 cuts from one render teach that threshold nothing. `MIN_CALIBRATION_VIDEOS_PER_SLIDESHOW_CLASS = 2` is enforced in the readiness/compile path | PASS — deterministic test (`test_a_slideshow_label_from_one_video_cannot_calibrate_a_video_level_threshold`) |
| The same video cannot be counted twice | Duplicate `sample_id` is rejected at harvest | PASS — deterministic test |
| An untraceable or unmeasured inspection is refused | Missing `video_sha256`, missing `source_change_ratio`, no boundary cuts, or a cut without a measurement each fail closed | PASS — parametrized negative tests |
| A non-predictive dataset is rejected, not weakly accepted | Labels uncorrelated with measurements fail the existing balanced-accuracy floors | PASS — deterministic test (`test_a_non_predictive_dataset_is_rejected_rather_than_weakly_accepted`) |
| A calibrated profile lifts the cap | A profile built through the full path validates as calibrated where the provisional default does not | PASS — deterministic test (`test_a_calibrated_profile_lifts_the_uncalibrated_hard_failure`) |
| Full operator path works | CLI harvest → refuse-to-compile-unlabeled → status → compile → calibrate, run as subprocesses | PASS — deterministic test (`test_cli_harvests_reports_and_compiles`) |
| **A real labeled dataset exists** | — | **NOT DELIVERED.** No profile is committed. This phase builds the path; walking it requires an editor labeling cuts from real renders. |

## The honest limit

**This phase does not produce a calibrated profile.** It produces the machinery to make one. The
gate remains uncalibrated, and PR 7 remains blocked, until an editor harvests real renders and
labels roughly 40+ cuts across at least two slideshow-ish and two developing videos. That is
deliberate — a profile fabricated here would be exactly the hand-tuned fixture this phase exists
to replace.

Test fixtures in `tests/test_gate_calibration_harvest.py` are synthetic *by necessity* and are
labeled consistently with their own measurements to exercise the path. They are not a dataset and
must never be used as one.

## Corrected provider-identifier claim

`explainer_pipeline.py` recorded the Anthropic entry as `"identifier_stability": "pinned_snapshot"`
while every other entry was `request_identifier`. That overstated its provenance:
`claude-opus-4-8` is the complete canonical ID for the model, but a canonical ID is not a pinned
snapshot — current-generation Anthropic IDs carry no date suffix, and **no dated snapshot of this
model exists to pin to** (dated snapshots exist only for older generations, e.g.
`claude-opus-4-5-20251101`). The docstring three lines above already disclaimed what the field
asserted.

The entry is now `request_identifier`, and the closure test asserts that **no** entry claims a
pinned snapshot. `PR5_PR6_CLOSURE_VALIDATION.md` has been corrected in place, with the change
marked rather than quietly rewritten.

This mattered more than a one-word label: it is the model behind the fact-checker, the evidence
verifier, and the blind story judge, so a false provenance record there is the worst place to
have one. The roadmap now carries the general rule in §12.

Note for anyone reading the original review: the fix is **not** to swap in a dated snapshot ID.
There is no dated snapshot of Opus 4.8; the older dated IDs visible in a model listing belong to
different, less capable models, and adopting one would be a downgrade.

## Validation run

- `python -m pytest -q`: **352 passed**, no failures or skips (334 before this change, 18 added).
- `python -m py_compile` on every changed module and the new CLI: passed.
- `git diff --check`: passed.
- Harvest verified against genuine `inspect_rendered_opening` output from a real `ffmpeg` encode,
  not only synthetic fixtures.
- Provider cost incurred: **$0.00**.

## Known limitations and non-goals

- No calibrated profile is committed (see the honest limit above).
- The harvester reads inspection reports; it does not itself run renders. Sourcing the renders is
  the operator's step, and the roadmap names a deliberately-failing pilot as the cheapest source.
- `MIN_CALIBRATION_VIDEOS_PER_SLIDESHOW_CLASS = 2` is a floor, not a sufficiency claim. Two videos
  per class is the minimum that makes the label meaningful, not the minimum for a good threshold.
- Audit findings F2 (the 39% Moon baseline is still a hand-tuned fixture) and F4 (Bolt budgets
  still count scenes rather than visual states) are **not** addressed here and remain open.

## Rollback path

Additive. Reverting removes three functions, the CLI, the test module, the roadmap section, and
the identifier-label correction; no existing contract, route, or stored column changes behaviour.
