# Writer evals (promptfoo)

The pipeline's own prompts, rendered from cached research dossiers by `prompts.py`, sent to the
script model, and judged by the pipeline's own deterministic gates in `asserts.py`. Nothing is
rendered; a full run costs well under a dollar. Use it before and after any change to
`story_compiler.factual_plan_prompt`, the cold-open rules, or `script_editor._SYSTEM`.

    cd /Users/obadiah/ai-video-gen-local
    set -a; source <(grep -E '^OPENAI_API_KEY=' .env); set +a
    export PROMPTFOO_PYTHON=/opt/homebrew/bin/python3
    npx promptfoo@latest eval -c evals/promptfoo/planner.yaml
    npx promptfoo@latest eval -c evals/promptfoo/editor.yaml
    npx promptfoo@latest view

* `planner.yaml` — one case per dossier in `fixtures/`, planned with the LADDER opening the
  pipeline uses (`OPENING_MODE` default); asserts: valid JSON, `score_plan` >= 75 (compiles, no
  duplicate roles, distinct facts per beat, enough events, the pre-incentive budget), the turn-by-45
  feasibility (`opening_turn.plan_feasibility`: consequence cited from the dossier, at most three
  narrated beats before the mechanism, a floor inside the 103-word target), event count within
  20% of the runtime's need. The carp, escobar (myth) and Aral (state_programme) dossiers are the
  three films whose consequence was planned as the mechanism's event.
* `editor.yaml` — the delivered killer bees script with its repeats; asserts: every detected
  defect resolved and no new repeat, lengths held within 35%, no meta phrases.

Add a topic: copy its `research_dossier.json` into `fixtures/` and add a test. Compare models:
add a provider line (`openai:chat:<model>`). Keep the LLM-rubric assertion types out of here;
the point is that the gates, not a judge, decide.

## story_reviewer.yaml (story-contract lane)

The lane's reviewer compares lionfish v1 (`narration_lionfish_v1.txt`, the compiled catalogue) with
v2 (`narration_lionfish_v2.txt`, the Carlson / full-freezer rewrite) in both orders, on a neutral
brief. `asserts.py:reviewer_prefers` passes only when it prefers v2 and gives at least two reasons
whose quotations are verbatim in v2. The prompt is `story_contract.compare_prompt`, so the eval
exercises the lane's own rubric. A reviewer that cannot separate these two is not ready to gate
anything (docs/STORY_CONTRACT_LANE.md). `dossier_lionfish_v2.json` is the cached dossier the lane's
tests and dry run use. About $0.005 on gpt-5.6-luna.
