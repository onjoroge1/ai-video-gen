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

* `planner.yaml` — one case per dossier in `fixtures/`; asserts: valid JSON, `score_plan` >= 75
  (compiles, no duplicate roles, cited cold open, distinct facts per beat, enough events, the
  pre-incentive budget), the cold-open shape rules, event count within 20% of the runtime's need.
* `editor.yaml` — the delivered killer bees script with its repeats; asserts: every detected
  defect resolved and no new repeat, lengths held within 35%, no meta phrases.

Add a topic: copy its `research_dossier.json` into `fixtures/` and add a test. Compare models:
add a provider line (`openai:chat:<model>`). Keep the LLM-rubric assertion types out of here;
the point is that the gates, not a judge, decide.
