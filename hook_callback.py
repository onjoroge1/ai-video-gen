"""Evidence-bound opening promises and closing payoffs for causal explainers."""
import json

VERSION = "hook_callback_v1"
FIELDS = ("viewer_question", "supported_answer", "contrast", "callback_image", "closing_question")
GRADE_GUIDANCE = (
    "\nAssess hook and ending together from the spoken narration: is the opening specific "
    "and understandable, does its contrast create a concrete question, does the story "
    "actually answer it, and does the callback add meaning rather than repeat the same "
    "question or summarize? A question is not automatically better than a statement. "
    "Do not reward invented specificity, unsupported timeframes or an unanswered tease. "
    "Judge the first 30 seconds for orientation and progress toward the promised answer. "
    "These scores are editorial estimates, not measured audience retention.\n")
BRIEF = """
PLAN THE HOOK AND ENDING AS A PAIR, not two independent slogans.
For an intervention story, prefer one natural question contrasting the intended
beneficiary with a specific unexpected consequence. Name the subject; keep the
existing hook word limit. Specificity must come from evidence, not invented scenes,
actors, numbers, timeframes, motives or universal claims. Do not force contrast when
the evidence has none. Avoid generic 'you won't believe', guru advice and clickbait.
The next lines orient the listener and introduce the mechanism early; do not conceal
basic context merely to delay the answer. A question's factual premise still needs evidence.
Plan the supported answer before writing the question. Let the events earn that answer.
At the close, return to the same concrete image with its meaning changed by the answer.
An optional final question extends the insight to the viewer; do not just repeat the
opening question, recap the whole script, or introduce an unsupported moral or cause.
For example, IF the evidence supports it: 'How did a plan to save New Zealand's sheep
put kiwi chicks on the menu?' can close with 'What else are you putting on the menu?'
after explaining why the introduced hunters also preyed on native birds. This is a
structural example, not evidence or a template to copy onto unrelated topics. The
opening asks how it happened; the ending applies the answer. No invented timelines.
Keep the selected engine's closing role and the concrete opening-object callback.
"""


def contract(plan):
    value = plan.get("hook_contract") or plan.get("_hook_contract") or {}
    if not isinstance(value, dict):
        return {}
    return {k: value[k].strip() for k in FIELDS if isinstance(value.get(k), str) and value[k].strip()}


def expansion_direction(plan):
    pair = contract(plan)
    if not pair:
        return ""
    return ("\nOPENING/CLOSING WRITING PLAN (not additional evidence):\n"
            + json.dumps(pair, ensure_ascii=False)
            + "\nFulfil this promise through the assigned events. The supported_answer is a "
              "writing target, never permission to exceed the claim ledger. Preserve the "
              "opening's subject when a local edit changes its wording. Only the ending batch "
              "writes the callback; other batches advance the answer without repeating the hook.\n")
