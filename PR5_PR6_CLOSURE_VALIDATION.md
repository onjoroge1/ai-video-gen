# PR 5/6 Closure Validation — Long-Form Render Integrity

## Scope

This corrective PR closes the remaining per-shot character, evidence-reference, timing,
provenance, operator-acknowledgement, and rendered-gate gaps found after PRs 5 and 6. It does
not claim that the long-form system has completed a controlled paid pilot.

## Requirement disposition

| Requirement | Implementation | Verification |
|---|---|---|
| Useful Bolt is required, but Bolt is not pasted into every shot | Bolt is opted into individual compiled evidence states. At least one state must contain a concrete useful action; category-only placeholders are rejected. More than 35% of compiled states containing Bolt is rejected. | `test_bolt_is_opted_in_per_compiled_state_and_frequency_is_state_based`, `test_zero_or_over_budget_compiled_bolt_states_fail_before_assets`, `test_zero_bolt_never_receives_full_credit_and_is_a_hard_failure` |
| Bolt frequency is measured from visual states | `validate_evidence_plan` reports `compiled_visual_state_count`, `useful_bolt_state_count`, and `bolt_visual_state_ratio`; scene count cannot award this credit. | Phase 3 and Phase 5 tests above |
| Mystery→Standard fallback requires acknowledgement before visual spending | A hash-bound review artifact, API, durable statuses, resume rule, and visible Explainer-tab panel expose the fallback reason and require an identified operator to accept or reject it. | `test_pr1_to_pr3_story_format_fallback_is_hash_bound_and_explicit`, `test_pr5_fallback_pause_occurs_before_tts_or_visual_generation`, `test_pr5_story_format_review_endpoint_records_operator_acceptance`, DOM placement assertion |
| Missing measured word timing fails closed | Evidence-state shot compilation raises when measured timing is absent or cannot produce valid 1.5-second cuts. The real pipeline now prepares audio before its first timing validation; the former undefined-`audio_timing` crash is removed. | `test_longform_evidence_shots_fail_closed_without_measured_word_timings`, `test_pr5_measured_evidence_timing_cannot_run_before_audio_exists` |
| Actual audio transformations are recorded | Every final narration file gets a provider/model/voice/speed/operations/file-hash/cache ledger entry. `natural_speed` and `post_stretched` are derived from that ledger. Paused manifests copy the actual ledger instead of reporting a hardcoded state. | Phase 2 audio ledger tests and `test_pr6_paused_manifest_records_actual_audio_and_motion` |
| Exact provider/model request IDs are recorded | All Anthropic/OpenAI request sites use centralized model constants. Configured motion providers fail before spend if unknown. Successful motion states record the actual provider and model; paused/completed manifests expose the result. Every entry, Anthropic included, is labeled `request_identifier` — no entry claims a pinned snapshot. | `test_pr6_manifest_records_exact_request_model_ids_and_stability`, `test_pr6_manifest_rejects_unknown_motion_provider` |
| Threshold calibration is real and not pre-claimed | Default thresholds are labeled `provisional_uncalibrated` and cannot produce a publishable gate result. The calibration CLI requires typed, unique, balanced human labels, minimum balanced/class accuracy, and emits a hashed profile; a configured invalid or non-predictive profile fails closed. | `test_uncalibrated_thresholds_are_reported_and_cannot_publish`, calibration positive/negative/CLI tests |
| Evidence references and MIME handling fail safely | Pure-evidence generations do not inherit a continuity reference containing forbidden characters. Forbidden objects are repeated as a hard absence constraint. Verifier MIME is derived from bytes, not the filename extension. | Phase 3 reference, prompt, verifier, and MIME tests |
| Gate formatting and exception paths do not crash silently | The opening ratio uses safe f-string percentage formatting; verifier exceptions retain bounded diagnostic detail; paused/failed manifest state is atomically recorded. | `test_opening_gate_log_formats_ratio_without_percent_crash`, paused-manifest test |

## PR 1–PR 6 regression matrix

| Phase | Contract covered | Test module |
|---|---|---|
| PR 1 | Human-led story, character objective, Bolt role budget, format controls | `tests/test_human_led_story_phase1.py`, closure matrix |
| PR 2 | Sourced claims, measured natural-speed narration, transformation ledger | `tests/test_longform_research_phase2.py`, `tests/test_audio_timing_phase2.py` |
| PR 3 | Evidence-state compiler, per-state cast, references, callback, asset verification | `tests/test_longform_evidence_phase3.py` |
| PR 4 | Motion modes, semantic selection/alignment, strict floors, frozen opening | `tests/test_longform_motion_phase4.py`, `tests/test_longform_shots.py` |
| PR 5 | Animatic/rendered pixels, Bolt rendered credit, 39-point regression, calibration, human pause | `tests/test_longform_rendered_gate_phase5.py`, closure matrix |
| PR 6 | Durable storage/status/resume, artifact exposure, manifests | `tests/test_durable_execution_phase6.py`, `tests/test_durable_routes_phase6.py`, closure matrix |

## Validation run

- `python -m pytest -q`: **199 passed**, no failures or skips.
- `python -m py_compile ...`: passed for every changed Python module and the calibration CLI.
- Extracted inline JavaScript from `static/index.html` and ran `node --check -`: passed.
- `python -m build --wheel --sdist`: passed.
- `git diff --check`: passed.

## Provider identifier verification

- **Corrected after review.** `claude-opus-4-8` is the complete canonical ID for that model, but a
  canonical ID is not a *pinned snapshot*: current-generation Anthropic IDs carry no date suffix,
  and no dated snapshot of this model exists to pin to (dated snapshots exist only for older
  generations, e.g. `claude-opus-4-5-20251101`). The manifest previously labelled this entry
  `pinned_snapshot`, which overstated its provenance; it is now `request_identifier`, matching
  every other entry. See the
  [model ID and versioning guide](https://platform.claude.com/docs/en/about-claude/models/model-ids-and-versions).
- OpenAI's current [pricing/model catalog](https://platform.openai.com/pricing) lists
  `gpt-image-2` and `sora-2`; its [Audio API reference](https://platform.openai.com/docs/api-reference/audio)
  lists `tts-1-hd` and `whisper-1`.
- Google's current [Gemini API Veo guide](https://ai.google.dev/gemini-api/docs/veo) lists
  `veo-3.1-fast-generate-preview` for the Gemini API.
- fal publishes the configured
  [Kling 2.1 Standard](https://fal.ai/models/fal-ai/kling-video/v2.1/standard/image-to-video)
  and [Kling v3 Pro](https://fal.ai/models/fal-ai/kling-video/v3/pro/image-to-video)
  endpoint IDs.

## Honest release limits

- No calibrated threshold dataset or production profile is included. Until an editor supplies one
  through `LONGFORM_GATE_CALIBRATION_PROFILE`, the rendered gate is intentionally non-publishable.
- No paid 45-second Standard/Mystery render was performed in this PR. Provider behavior, model
  output quality, and end-to-end visual storytelling remain unverified by a real pilot.
- No live cross-worker Neon/Blob recovery run was performed. Durable behavior is covered by the
  repository's deterministic tests, not a production deployment exercise.
- A real browser visual pass could not run in this workspace because no Chrome binary is available.
  The shipped JavaScript, DOM tab placement, API routes, and acknowledgement endpoint were checked
  deterministically; visual layout is not claimed as browser-verified.
- `claude-opus-4-8` is an undated request identifier, not a pinned snapshot. Observable behavior
  behind it can change without the recorded identifier changing, so the manifest records what was
  requested, never a guarantee of what served it.

## Merge disposition

The code is suitable for review as a PR 5/6 closure patch. It is not evidence that PR 7's paid
pilot has passed, and it must not be described as a calibrated or production-proven 85/100 system.
