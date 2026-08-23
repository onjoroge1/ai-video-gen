# PR 3 Validation — Evidence Asset and Continuity Compiler

This document is the merge disposition for PR 3 of `LONGFORM_BOLT_EXPLAINER_ROADMAP.md`.

## Requirement disposition

| Roadmap requirement | Disposition | Evidence |
|---|---|---|
| Two to four evidence states per opening beat | PASS — fail-closed compiler and tests | Every scene in the first 30 percent must compile two to four declared states; missing or excessive states reject before image purchase |
| Required/forbidden object-state specifications | PASS — schema, validator, and pixel verifier | Every state declares a visible before/after condition plus required and forbidden objects; incomplete or unchanged states reject |
| Distinct-source and reframe accounting | PASS — deterministic reports | Plans and rendered shot metrics report generated source assets, detail reframes, exact reuse, accepted assets, rejected assets, and verified-information shots separately |
| Continuity pack and stable IDs | PASS — fixtures | Alex identity, clothing, first-act location, Bolt identity, and opening object receive deterministic IDs that remain stable across recompilation |
| Deterministic character-reference inclusion | PASS — routing tests | References are ordered Alex, Bolt, then continuity source; pure-evidence states never receive the Bolt reference |
| Exact opening-object asset reuse | PASS — ID and SHA checks | The ending callback names the opening source asset and the renderer byte-copies it, then requires an identical SHA-256 digest |
| Reframes do not automatically claim new information | PASS — regression tests | Planning and fallback shots default to false; only the pixel verifier can award visible information, and unverified detail reframes reject |
| At least 70 percent of opening cuts add verified visible information | PASS — hard gate and adversarial ratio test | The opening asset gate computes the ratio from verifier-owned pixel results and blocks later visual purchase below 70 percent |
| At least two distinct state assets per opening beat unless detail verification passes | PASS — hard gate | Each opening beat requires two generated sources unless a declared detail reframe independently passes pixel verification |
| No pure-evidence asset contains Bolt | PASS — generation exclusion plus pixel rejection | Pure evidence omits the Bolt reference, adds Bolt to forbidden objects, and fails when the visual verifier reports Bolt present |
| Human identity, clothing, location, and opening object continuity | PASS — stable fixtures and fail-closed visual checks | Reference-conditioned generation is paired with explicit vision fields for face, clothing, location, and opening-object matching |
| Asset failures are explicit rejections | PASS — adversarial tests | Missing files, generation errors, invalid verifier output, absent required objects, forbidden objects, and continuity failures set `asset_status=rejected`; no filler/reframe substitution is allowed for long-form |
| Purchase only the opening before the rest | PASS — orchestration boundary | The opening tranche now stops at the scene boundary that reaches 45 seconds; the preview is capped at 45 seconds and later images wait for the opening evidence/readiness gate |
| Safe resume without repurchase | PASS — contract-version guard | Pre-PR3 checkpoints cannot reuse old slideshow assets; valid PR3 checkpoints can reuse generated images but every cached asset is reverified before acceptance |
| Reports downloadable from the product | PASS — API/UI tests | Evidence plan, evidence validation, and continuity pack are persisted in job metadata and exposed by dedicated API routes and UI buttons |

## Verification result

Commands:

```text
python -m py_compile explainer_pipeline.py longform_evidence.py longform_shots.py app.py
.venv/bin/pytest -q
.venv/bin/python -m build --wheel --sdist
git diff --check
```

Result at completion: **120 passed**; wheel and source distribution built successfully; no diff whitespace errors.

Controlled live provider schema check (synthetic image; no project asset transmitted):

- Anthropic vision accepted the target-image-plus-object-contract request;
- the response returned the exact required/forbidden object keys consumed by the validator;
- the required red square, absent blue circle, and visible-information checks passed;
- the parser produced `passed=true` and the measured call cost was $0.006635.

Compatibility stress test against the prior 90-second Moon mystery script:

- 17 scenes compiled into 35 declared evidence states;
- six opening beats compiled to two states each;
- 34 distinct generated source states and one exact callback reuse;
- eight pure-evidence states and zero pure-evidence states containing Bolt in the plan;
- the deterministic plan validation passed with no errors.

That old checkpoint predates the human-led PR 1 contract, so its zero Alex states are historical input, not evidence that a new PR 1/2 script satisfies the current human-led contract. PR3 correctly refuses to resume that checkpoint as verified evidence media.

## Fail-closed order

1. The final story and claim contracts pass.
2. Narration beats compile to evidence states and continuity IDs.
3. Measured narration timing is checked against state density before visual purchase.
4. Required character references must exist for every declared character state.
5. Each generated/reframed asset is inspected against its required pixels, forbidden pixels, and continuity references.
6. Rejected or unavailable verification remains an explicit rejected asset.
7. The first 45-second tranche must pass the evidence ratio and existing readiness gate before later images are generated.
8. All remaining states are revalidated before final rendering.

## Known limitations and non-goals

- This PR proves that the pipeline purchases and edits declared evidence states. It does not yet prove that the finished edit feels cinematic or uses story-role-prioritized motion; that is PR 4.
- Claude vision is a probabilistic pixel judge. The implementation fails closed on invalid/unavailable output and cross-checks exact object keys, but calibrated rendered-video judgment and seeded visual failures belong to PR 5.
- The first-45-second preview still uses the legacy readiness scorer and artifact filename. The blind sequential rendered-story judge, contact-sheet inspection, and frozen 39-point Moon rubric belong to PR 5.
- No paid provider pilot is claimed here. Controlled 45-second and 90-second acceptance renders belong to PRs 7 and 8.
- Reports are wired for durable artifact persistence, but Blob/Postgres durability, cross-worker execution, `/finished`, and recovery remain PR 6.
- The compiler can reject generated evidence and stop the job; automated repair/regeneration policy is intentionally not disguised as success and should be calibrated during the controlled pilots.

## Rollback

- Pre-PR 3 production baseline: `checkpoint/pre-pr3-main-aed31e8`

PR 3 can be reverted as one commit without reverting PRs 1–2 or the roadmap.
