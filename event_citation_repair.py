"""One bounded, citation-only edit against existing verified primary-story passages."""
from copy import deepcopy
import json


def repair(beats, concerns, claims, question, *, cost_sink=None):
    import explainer_pipeline as ep
    ids = {row["beat_id"] for row in concerns[:4]}
    response = ep._claude().messages.create(
        model=ep.ANTHROPIC_MODEL, max_tokens=1800,
        system="Repair event citations only. Use the exact source passages, never background knowledge.",
        messages=[{"role": "user", "content": json.dumps({
            "question": question, "concerns": concerns[:4],
            "beats": [b for b in beats if b.get("beat_id") in ids],
            "claims": claims,
            "instruction": "Return {edits:[{beat_id,claim_refs}]}. Keep event text unchanged. "
                "Choose existing claims whose quotations jointly support EVERY detail. "
                "Do not replace event text, actors, dates, roles or engine. If no supporting "
                "combination exists, return no edit. At most four edits."}, ensure_ascii=False)}])
    cost = ep._msg_cost(response.usage)
    if cost_sink is not None:
        cost_sink.append(cost)
    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text[text.find("{"):text.rfind("}") + 1]
    try:
        edits = json.loads(text)["edits"]
        if not isinstance(edits, list) or len(edits) > 4:
            return beats, cost
        result = deepcopy(beats)
        by_id = {b["beat_id"]: b for b in result}
        seen = set()
        for edit in edits:
            bid, refs = edit.get("beat_id"), edit.get("claim_refs")
            if (set(edit) != {"beat_id", "claim_refs"} or bid not in ids or bid in seen
                    or not isinstance(refs, list) or not refs
                    or not all(isinstance(r, str) and r in claims for r in refs)):
                return beats, cost
            seen.add(bid)
            by_id[bid]["event"]["claim_refs"] = list(dict.fromkeys(refs))
        return result, cost
    except (ValueError, KeyError, TypeError, AttributeError):
        return beats, cost
