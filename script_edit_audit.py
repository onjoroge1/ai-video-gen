"""Private, replayable explanations of accepted and rejected script edits."""
from copy import deepcopy
import script_stages


def record(script, candidate, before, after, operation, accepted, reason):
    def prose(value):
        return {"title": value.get("title"), "hook": value.get("hook"),
                "cold_open": value.get("_cold_open"),
                "scenes": [{"scene": i, "narration": s.get("narration"), "event": s.get("event")}
                           for i, s in enumerate(value.get("scenes") or [], 1)]}
    original, proposed = prose(script), prose(candidate)
    from script_integrity import comparison
    row = {"operation": operation, "accepted": bool(accepted), "reason": reason,
           "before_sha256": script_stages.digest(original),
           "candidate_sha256": script_stages.digest(proposed),
           "before_report": deepcopy(before), "candidate_report": deepcopy(after),
           "comparison": comparison(before, after, original=script, candidate=candidate),
           "candidate": proposed}
    history = script.setdefault("_edit_audit", [])
    if row not in history:
        history.append(row)
    if accepted:
        candidate["_edit_audit"] = deepcopy(history)
    script_stages.save("script-edit-audit", {"operation": operation,
                       "before": row["before_sha256"], "candidate": row["candidate_sha256"]}, row)
