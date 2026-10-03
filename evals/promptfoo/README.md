# Writer evaluations

`planner.yaml` and `editor.yaml` now use `production_provider.py`, which invokes the same
`explainer_pipeline._claude()` routing and model configuration as Studio. Configure the same
script-provider environment as the deployment. Each case makes one writing request bounded at 12,000
output tokens. Editor acceptance also runs the production source and integrity validators,
which can make additional bounded judge calls. These evaluations are paid and are not subject
to a Studio job's dollar ceiling.
No research, voice, images, or video generation runs.

```bash
export REELFORGE_PAID_EVAL=1
export PROMPTFOO_PYTHON=$(command -v python3)
npx promptfoo eval -c evals/promptfoo/planner.yaml
npx promptfoo eval -c evals/promptfoo/editor.yaml
```

The adapter refuses provider calls unless explicitly enabled. Use an installed, reviewed
Promptfoo version. Offline verification does not establish live writing quality.

Planner assertions are **deterministic preflight**, not semantic evidence approval or final
script readiness. They cover JSON, score >=75, cold-open shape and event count. Editor assertions
use the production edit transaction and require semantic acceptance; defect counts, length
and meta phrases alone cannot pass an edit. Prompts include the reference-informed cadence brief;
full Studio orchestration, source validation and final readiness remain separate tests.

CI runs `tests/test_script_flow_recovery.py` through the normal pytest suite. It reproduces
duplicate durable requests, source snapshot recovery, selected-attempt diagnosis, worker yields
at plan/expansion checkpoints, citation-only repair and stale/failed final gates. These fixtures
are offline; no API secrets or paid evaluations are needed on a pull request.

Add representative dossiers to `fixtures/` for opt-in provider comparisons. Keep source passages,
verification status and scope. Do not infer measured viewer retention from an evaluation score.

## Meaning and continuity regression cases

`integrity.yaml` runs nine cases from the dec618fc investigation, including corrected
counterexamples. It uses `script_integrity`'s production prompt and validates both the
response schema and exact expected error-code set. It does not generate research or media.
This is a paid opt-in evaluation through the existing production provider adapter:

```sh
REELFORGE_PAID_EVAL=1 npx promptfoo eval -c evals/promptfoo/integrity.yaml
```

Offline tests validate plumbing and fixtures; live classification quality remains
unverified until this evaluation or an authenticated Studio test is actually run.
