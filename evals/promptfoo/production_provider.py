"""Opt-in Promptfoo adapter using ReelForge's production script-provider routing.

Interface: https://www.promptfoo.dev/docs/providers/python/
One bounded provider request per evaluation case; no research or media calls.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def call_api(prompt, options, context):
    if os.environ.get("REELFORGE_PAID_EVAL") != "1":
        return {"error": "Paid evaluation disabled; set REELFORGE_PAID_EVAL=1 explicitly"}
    import explainer_pipeline as ep
    try:
        messages = json.loads(prompt)
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        messages = [m for m in messages if m["role"] != "system"]
        response = ep._claude().messages.create(model=ep.ANTHROPIC_MODEL, max_tokens=12000,
            system=system, messages=messages)
        if getattr(response, "stop_reason", None) in {"max_tokens", "pause_turn"}:
            return {"error": "Incomplete provider response"}
        return {"output": "".join(getattr(b, "text", "") for b in response.content),
                "tokenUsage": {"prompt": response.usage.input_tokens,
                               "completion": response.usage.output_tokens,
                               "total": response.usage.input_tokens + response.usage.output_tokens}}
    except Exception as exc:
        return {"error": "Production provider evaluation failed: " + type(exc).__name__}
