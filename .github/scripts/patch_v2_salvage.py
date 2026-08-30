from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"patch anchor missing in {path}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# Keep the durable lease comfortably below Vercel's 800-second function ceiling.
replace_once(
    "durable_execution.py",
    "import blob_compat\nimport _durable_execution_legacy as _legacy\n",
    "import blob_compat\n# A worker must become reclaimable before the hosting function ceiling.\n"
    "os.environ.setdefault(\"DURABLE_JOB_LEASE_SECONDS\", \"600\")\n"
    "import _durable_execution_legacy as _legacy\n",
)

# Expose only the opaque action's non-sensitive status summary to headless agents.
replace_once(
    "private_access.py",
    "_AGENT_ACTION_ID = re.compile(r\"^/api/agent/actions/act_[0-9a-f]{32}(?:/(?:execute|dispatch))?$\")",
    "_AGENT_ACTION_ID = re.compile(r\"^/api/agent/actions/act_[0-9a-f]{32}(?:/(?:execute|dispatch|public-status))?$\")",
)
replace_once(
    "private_access.py",
    "        if path.endswith((\"/execute\", \"/dispatch\")):\n            return method == \"POST\"\n        return method == \"GET\"",
    "        if path.endswith((\"/execute\", \"/dispatch\")):\n            return method == \"POST\"\n        return method == \"GET\"",
)

anchor = '''@app.post("/api/agent/actions/{action_id}/approve")\nasync def approve_agent_action'''
route = '''@app.get("/api/agent/actions/{action_id}/public-status")\nasync def get_agent_action_public_status(action_id: str):\n    \"\"\"Read-only, non-sensitive status for an opaque approved action id.\n\n    This intentionally omits the directed spec payload, credentials and claim-token digest.\n    It exists so an AI can monitor an operator-approved render without a second approval.\n    \"\"\"\n    try:\n        action = await asyncio.to_thread(agent_actions.repository().get, action_id)\n    except agent_actions.AgentActionError as exc:\n        raise _agent_action_http_error(exc) from exc\n    if not action:\n        raise HTTPException(status_code=404, detail="Agent action not found")\n    summary = agent_actions.public_action(action)\n    job_id = str(action.get("job_id") or "")\n    if job_id and _durable_execution_required():\n        try:\n            store, _ = _durable_components()\n            row = await asyncio.to_thread(store.get_job, job_id)\n            if row:\n                summary["job"] = {\n                    "id": row.get("id"),\n                    "status": row.get("status"),\n                    "error": row.get("error"),\n                    "spent_cost_usd": float(row.get("spent_cost_usd") or 0),\n                    "reserved_cost_usd": float(row.get("reserved_cost_usd") or 0),\n                    "max_cost_usd": float(row.get("max_cost_usd") or 0),\n                    "attempts": row.get("attempts"),\n                    "max_attempts": row.get("max_attempts"),\n                    "lease_expires_at": str(row.get("lease_expires_at") or ""),\n                    "updated_at": str(row.get("updated_at") or ""),\n                    "checkpoint_present": bool(row.get("checkpoint")),\n                    "result": row.get("result") or {},\n                }\n            import db\n            finished = await asyncio.to_thread(db.finished_video_get, job_id) or {}\n            if finished:\n                summary["finished_video"] = {\n                    "id": finished.get("id"),\n                    "title": finished.get("title"),\n                    "status": finished.get("status"),\n                    "video_url": finished.get("video_url"),\n                    "download_url": finished.get("download_url"),\n                    "metadata": finished.get("metadata") or {},\n                }\n        except durable_execution.StorageUnavailable:\n            summary["job_status_unavailable"] = True\n    return summary\n\n\n@app.post("/api/agent/actions/{action_id}/approve")\nasync def approve_agent_action'''
replace_once("app.py", anchor, route)
