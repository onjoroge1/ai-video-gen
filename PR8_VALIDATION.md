# PR 8 Validation — Controlled 90-Second Production Contract

## Scope and honest headline

This PR delivers the **immutable PR8 contract, gates, and durable/API surface** for the controlled
90-second production run. It does **not** claim that a controlled 90-second video has been
produced. No paid render was performed here, so every requirement below that the roadmap expects to
be proven "in a real artifact" is dispositioned `PARTIAL` with the limitation named, not `PASS`.

The deliverable is the machinery that makes the eventual purchase gradeable and un-fudgeable:
structure selection from recorded PR7 scores, frozen-opening reuse by hash, a runtime window
measured from real bytes, a raised score floor, eight independent delivery gates, and a
publish/no-publish recommendation with no promotion path.

## Requirement disposition

| Roadmap requirement | Implementation | Disposition |
|---|---|---|
| One 90-second video selected from the **stronger Phase 7 structure** | `select_production_structure` reduces a PR7 batch to its two graded outcomes, refuses to start unless *both* pilots passed with no hard failures, and picks the higher recorded score. A reviewer cannot override a real score difference; only an exact tie is decided by a named reviewer with a written reason, recorded inside the hashed selection. | PASS — deterministic test (`test_production_structure_selects_the_higher_pr7_score`, `test_a_failed_pr7_pilot_blocks_the_90_second_purchase`, `test_pr7_hard_failures_cannot_be_promoted_into_production`, `test_reviewer_cannot_override_the_stronger_structure`, `test_exact_tie_requires_an_identified_reviewer_and_written_reason`) |
| **Frozen approved opening** | `build_production_request` refuses to build without the winner's PR7 opening freeze manifest and binds its hash into the request. The pilot pipeline now returns the manifest *content* (not just a local path) and `run_explainer_task` persists it in the durable job result, so a later container can condition on it. | PASS — deterministic test (`test_production_requires_the_approved_frozen_opening`, `test_pilot_result_carries_the_frozen_opening_into_durable_storage`) |
| **Opening object returns as the exact conditioned/reused asset** | `validate_opening_object_return` re-validates the freeze manifest, then compares the callback asset's SHA-256 against the opening asset's on disk. A regenerated look-alike differs by hash and fails; an opening asset edited after approval fails both freeze integrity and the frozen-hash membership check. | PASS — deterministic test over real files (`test_callback_reusing_the_exact_opening_bytes_passes`, `test_a_regenerated_callback_object_fails_exact_reuse`, `test_an_opening_asset_edited_after_approval_fails`) |
| **Runtime 87.3–92.7 seconds at natural TTS speed** | `validate_production_runtime` requires the window in the **encoded MP4 duration** *and* in measured narration, requires `natural_speed`, rejects `post_stretched`, and rejects an encode that diverges from its own narration by more than the tolerance (padding or lost narration). The window is derived from the pipeline's existing ±3% tolerance at 90s rather than hardcoded twice; a module-level assertion pins it to (87.3, 92.7). | PASS — deterministic test (boundary-parametrized `test_runtime_window_boundaries_are_enforced`, `test_post_stretched_narration_cannot_buy_the_runtime_window`, `test_encoded_video_that_lost_narration_fails_reconciliation`) |
| **At least 90/100 rendered-contract score** | `PRODUCTION_RELEASE_SCORE = 90` replaces the ordinary `RELEASE_SCORE = 85` in `final_production_outcome`. Threshold calibration is still required, so an uncalibrated profile cannot publish. | PASS — deterministic test (`test_the_ordinary_eighty_five_release_floor_is_not_enough_for_production`, `test_uncalibrated_thresholds_cannot_publish_a_production_video`) |
| **No hard failures** | Hard failures from the existing rendered contract are carried into the automated grade unchanged and block the outcome. | PASS — deterministic test (`test_a_complete_pass_recommends_publish` and the automated-grade assertions) |
| **No filler** | Two independent definitions: a frozen phrase list of channel padding matched on word boundaries, and *structural* filler — a scene that opens no question, closes none, binds no claim, and shows no visible consequence. The pipeline's already-tracked `filler` counter (scenes rendered on a placeholder frame) must be exactly zero, where the ordinary path only degrades above 25%. | PASS — deterministic test (`test_every_frozen_filler_phrase_is_detected`, `test_filler_detection_does_not_fire_inside_a_longer_word`, `test_a_scene_that_does_no_story_work_is_structural_filler`, `test_dropped_narration_and_filler_frames_are_production_failures`) |
| **No dropped narration** | The pipeline's `dropped` counter must be exactly zero; script and timing scene counts must match; no scene may produce zero measured spoken words. | PASS — deterministic test (`test_a_silent_scene_fails_narration_integrity`, `test_script_and_timing_scene_counts_must_match`) |
| **No unexplained artifacts** | `validate_artifact_provenance` walks the produced media tree and requires every media file's SHA-256 to appear in the generation manifest. Matching by hash rather than path means renaming a file cannot launder it, and substituting bytes under a declared name still fails. | PASS — deterministic test over real files (`test_an_unexplained_media_file_fails_provenance`, `test_renaming_a_file_cannot_launder_provenance`) |
| **No unresolved questions** | `validate_resolved_questions` binds to the existing retention validator's tracked loops: any `unresolved_loops` entry fails, a story tracking no open question at all fails, and a missing or malformed report fails closed. | PASS — deterministic test (`test_resolved_questions_pass_and_unresolved_ones_fail`, `test_a_story_tracking_no_question_fails`, `test_a_missing_or_malformed_retention_report_fails_closed`) |
| **Scientific claims and visuals reconcile with the ledger** | `validate_claim_visual_reconciliation` requires the claim ledger to pass, requires every claim-bound scene to have a compiled state carrying *verified* visible information, and rejects visual spend on a scene with neither a claim nor a visible consequence. | PASS — deterministic test (`test_a_claim_without_a_verified_visual_state_fails`, `test_a_claim_with_no_compiled_visual_state_fails`, `test_visual_spend_without_a_story_join_fails`) |
| **Downloadable MP4 is fast-start** | `inspect_fast_start` parses real MP4 box headers (including 64-bit and to-EOF sizes) and requires `moov` before `mdat`. Verified against genuine ffmpeg output remuxed both with and without `+faststart`. A box declaring bytes past EOF is reported as truncated. | PASS — verified against real encoded artifacts in test (`test_real_faststart_and_non_faststart_mp4s_are_distinguished`, `test_a_truncated_mp4_does_not_hang_the_parser`) |
| **Complete job survives cross-worker recovery testing** | `validate_cross_worker_recovery` requires observed evidence rather than capability: at least two distinct lease owners, a recorded resume event, reuse of already-persisted work, and a successful terminal state. A recovery that reused nothing is rejected as indistinguishable from a full re-run. | PARTIAL — the validator and its negatives are deterministically tested (`test_a_single_worker_job_cannot_prove_cross_worker_recovery`, `test_recovery_that_reused_no_work_is_indistinguishable_from_a_rerun`, `test_recovery_without_a_recorded_resume_fails`), but **no real multi-worker Postgres/Blob recovery run was executed in this PR**. |
| **Production storage proof** | `production_storage_proof.json` is a required artifact, and the durable run is persisted through the existing PR7 hash-addressed snapshot path with `controlled_production_runs` rows keyed to the immutable request hash and selection hash. | PARTIAL — the schema, uniqueness rule, and required-artifact list are tested; the proof file itself is only produced by a real run, which has not been performed. |
| **Publish/no-publish recommendation** | `final_production_outcome` combines the automated grade, editorial checklist, artifact completeness, and all eight gates into `publish` / `do_not_publish`. Each gate can independently block, a missing gate report fails closed, and the record states that nothing can be promoted in place. | PASS — deterministic test (parametrized `test_every_production_gate_can_independently_block_publication`, `test_editorial_approval_cannot_promote_a_failed_gate`, `test_a_missing_gate_report_fails_closed`) |
| **No full video purchased outside the contract** | `ExplainerRequest.controlled_production` is internal; `POST /api/explainer/generate` returns 403 if it is set. The production endpoint forbids extra fields, and the request validator rejects runtime, threshold, checkpoint, resume, and score-floor overrides plus any loosened policy. | PASS — deterministic test (`test_public_generate_endpoint_cannot_smuggle_a_controlled_production`, parametrized override/mutation tests, `test_a_loosened_policy_cannot_be_smuggled_into_a_request`) |

## Adversarial negatives

Every gate has at least one test that makes it *fail*, not only pass. The suite includes a
regenerated callback object, an opening asset edited after approval, a post-stretched narration
that lands in the runtime window, an encode that silently lost four seconds of narration, a stray
media file with no provenance, a byte-substituted file under a declared name, a non-faststart
remux, a truncated MP4, a single-worker "recovery", a recovery that reused no work, a tie-break
attempting to override a real score margin, a loosened policy object, and an editorial approval
placed on top of a failed gate.

One test found a real defect during development: the fast-start parser initially accepted a
truncated file whose `mdat` box declared more bytes than the file contained. The parser now
reports `truncated_file` instead.

## Boundary integration

| Boundary | Change | Test |
|---|---|---|
| Durable store | `controlled_production_runs` table, `enqueue_production_run` (idempotent per `production_id`, rejects a different immutable request under the same id), `get_production_run`, and the two new terminal statuses | `test_durable_production_status_transitions_are_terminal`, endpoint tests |
| Pipeline version hash | `longform_production.py` added to the tracked set, so a contract change invalidates queued `pipeline_version` values | `test_pipeline_version_hash_tracks_the_production_contract` |
| API | `POST /api/explainer/production`, `GET /api/explainer/production/{id}`, `ExplainerProductionRequest` with `extra="forbid"` | `test_production_endpoint_queues_one_run_for_the_stronger_structure`, `test_production_endpoint_refuses_a_batch_whose_pilot_failed`, `test_production_endpoint_refuses_a_pilot_without_a_frozen_opening`, `test_production_endpoint_surfaces_a_tie_break_to_the_frozen_selection`, `test_production_endpoint_reports_storage_unavailability_as_retryable_503` |
| Packaging | `longform_production` added to `pyproject.toml` py-modules | wheel build below |

## Validation run

- `python -m pytest -q`: **334 passed**, no failures or skips (230 before this PR, 104 added).
- `python -m py_compile` on every changed module: passed.
- `python -m build --wheel`: passed; `longform_production.py` is present in the wheel.
- `git diff --check`: passed.
- Fast-start inspection exercised against real `ffmpeg` output in both mux orders.

## Cost incurred and remaining uncertainty

- Provider cost incurred by this PR: **$0.00**. No image, motion, TTS, transcription, or judge
  call was made; every test is deterministic and offline apart from local `ffmpeg`.
- Remaining uncertainty is concentrated in the two `PARTIAL` rows: real cross-worker recovery and a
  real production storage proof require a live Postgres/Blob deployment and a paid render.

## Known limitations and non-goals

- **No 90-second video was produced.** The acceptance criteria that require a rendered artifact
  remain unproven by definition.
- The filler phrase list is deliberately narrow. It catches channel padding, not every weak
  sentence; the structural-filler rule and the editorial checklist carry the rest.
- "Unexplained artifact" is defined as a media file lacking recorded provenance. Perceptual
  glitches inside an otherwise-provenanced frame remain the rendered gate's and the human
  reviewer's responsibility, not this module's.
- Threshold calibration is still uncalibrated by default (unchanged from PR5). A production run
  cannot publish until an editor supplies a calibrated profile — PR8 does not relax this.
- The tie-break path is the single place a human influences structure selection. It is limited to
  an exact numeric tie and is recorded with reviewer identity and reason.

## Rollback path

Every change is additive. Reverting this commit removes `longform_production.py`, its test module,
the two API routes, the `controlled_production_runs` table helpers, and the `opening_freeze`
carry-through; no existing PR1–PR7 contract, route, or stored column changes behaviour. The new
table is created lazily by `ensure_production_schema`, so an un-reverted database simply retains an
unused empty table.

## No unrelated changes

The diff touches only: the new module and tests, the PR8 wiring in `app.py` and
`durable_execution.py`, the single `opening_freeze` return field in `explainer_pipeline.py`, the
version-hash tracked list, `pyproject.toml`, `.env.example`, and documentation.
