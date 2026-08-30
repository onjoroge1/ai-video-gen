from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"patch anchor missing: {path}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# 1) Deterministically fit a small directed-pilot TTS overrun instead of paying for another TTS.
p = Path("spec_pilot.py")
text = p.read_text(encoding="utf-8")
text = text.replace(
    "    audio_costs: list = []\n    image_costs: list = []\n",
    "    audio_costs: list = []\n    audio_transformations: list = []\n    image_costs: list = []\n",
    1,
)
old_gate = '''    if require_validation:\n        is_pilot = abs(win_start) <= 0.05 and abs(win_end - spec.target.pilot_end_sec) <= 0.05\n        if is_pilot and not (\n                spec.acceptance.pilot_runtime_min_sec <= spoken\n                <= spec.acceptance.pilot_runtime_max_sec):\n            raise RuntimeError(\n                f"measured pilot narration {spoken:.2f}s is outside "\n                f"{spec.acceptance.pilot_runtime_min_sec:.2f}-"\n                f"{spec.acceptance.pilot_runtime_max_sec:.2f}s; visual spending stopped")\n        if not is_pilot and abs(drift) > spec.acceptance.runtime_tolerance_sec:\n'''
new_gate = '''    if require_validation:\n        is_pilot = abs(win_start) <= 0.05 and abs(win_end - spec.target.pilot_end_sec) <= 0.05\n        # A small natural-TTS overrun is an audio-layout problem, not a reason to regenerate\n        # the approved narration or weaken the runtime gate.  Fit the already-paid audio with\n        # ffmpeg atempo, preserve pitch, then remeasure and enforce the exact same 43-47s gate.\n        # The 12% ceiling is deliberately narrow; larger misses still fail closed before images.\n        if (is_pilot and spoken > spec.acceptance.pilot_runtime_max_sec\n                and spoken <= spec.acceptance.pilot_runtime_max_sec * 1.12):\n            target_spoken = max(\n                spec.acceptance.pilot_runtime_min_sec + 0.5,\n                spec.acceptance.pilot_runtime_max_sec - 1.0,\n            )\n            speed_factor = spoken / target_spoken\n            original_spoken = spoken\n            if not 1.0 < speed_factor <= 1.12:\n                raise RuntimeError(\n                    f"measured pilot narration {spoken:.2f}s requires unsafe audio retime; "\n                    "visual spending stopped")\n            for (scene_index, scene), audio_path in zip(indexed_scenes, audio_paths):\n                before = ep._audio_dur(audio_path)\n                tmp_path = audio_path + ".runtime-fit.mp3"\n                ep._run_ffmpeg([\n                    ep._ffmpeg_bin(), "-nostdin", "-y", "-i", audio_path,\n                    "-filter:a", f"atempo={speed_factor:.6f}",\n                    "-c:a", "libmp3lame", "-q:a", "2", tmp_path,\n                ], timeout=120.0)\n                os.replace(tmp_path, audio_path)\n                after = ep._audio_dur(audio_path)\n                audio_transformations.append({\n                    "scene_id": scene.scene_id,\n                    "type": "atempo",\n                    "reason": "directed_pilot_runtime_fit",\n                    "speed_factor": round(speed_factor, 6),\n                    "original_runtime_sec": round(before, 3),\n                    "final_runtime_sec": round(after, 3),\n                })\n            spoken = sum(ep._audio_dur(path) for path in audio_paths)\n            drift = spoken - budget\n            log(f"Directed pilot audio runtime fit: {original_spoken:.2f}s → {spoken:.2f}s "\n                f"(atempo ×{speed_factor:.4f}; gate unchanged)")\n        if is_pilot and not (\n                spec.acceptance.pilot_runtime_min_sec <= spoken\n                <= spec.acceptance.pilot_runtime_max_sec):\n            raise RuntimeError(\n                f"measured pilot narration {spoken:.2f}s is outside "\n                f"{spec.acceptance.pilot_runtime_min_sec:.2f}-"\n                f"{spec.acceptance.pilot_runtime_max_sec:.2f}s; visual spending stopped")\n        if not is_pilot and abs(drift) > spec.acceptance.runtime_tolerance_sec:\n'''
if old_gate not in text:
    raise SystemExit("directed runtime gate anchor missing")
text = text.replace(old_gate, new_gate, 1)
text = text.replace(
    '             "voice": voice, "transformation": "none"},',
    '             "voice": voice, "transformation": "atempo" if audio_transformations else "none"},',
    1,
)
text = text.replace(
    '        "actual_audio_transformations": [],',
    '        "actual_audio_transformations": audio_transformations,',
    1,
)
p.write_text(text, encoding="utf-8")


# 2) Rearm exactly one already-approved directed pilot that failed only this pre-image audio gate.
p = Path("durable_execution.py")
text = p.read_text(encoding="utf-8")
anchor = '''    def ensure_pilot_schema(self) -> None:\n'''
method = '''    def rearm_next_directed_audio_runtime_failure(self) -> dict | None:\n        \"\"\"Requeue one approved directed pilot stopped at the pre-image audio runtime gate.\n\n        The immutable request, completed TTS stages, checkpoint and cost ceiling are untouched.\n        A generation event makes this a one-shot salvage so a persistent failure cannot loop.\n        \"\"\"\n        self.ensure_schema()\n        with self._tx() as (_, cur):\n            cur.execute(\"\"\"\n                SELECT j.* FROM generation_jobs j\n                WHERE j.status='error'\n                  AND j.error LIKE 'Directed pilot measured narration %visual spending stopped.'\n                  AND j.reserved_cost_usd=0\n                  AND j.spent_cost_usd < j.max_cost_usd\n                  AND j.checkpoint <> '{}'::jsonb\n                  AND EXISTS (\n                      SELECT 1 FROM agent_actions a\n                      WHERE a.job_id=j.id AND a.operation='directed_pilot'\n                  )\n                  AND NOT EXISTS (\n                      SELECT 1 FROM generation_events e\n                      WHERE e.job_id=j.id AND e.event_type='directed_audio_fit_rearmed'\n                  )\n                ORDER BY j.updated_at ASC\n                FOR UPDATE SKIP LOCKED LIMIT 1\n            \"\"\")\n            current = self._json_ready(self._row(cur, cur.fetchone()))\n            if not current:\n                return None\n            cur.execute(\"\"\"\n                UPDATE generation_jobs SET status='queued',error=NULL,\n                    max_attempts=GREATEST(max_attempts,attempts+2),\n                    lease_owner=NULL,lease_expires_at=NULL,updated_at=now()\n                WHERE id=%s RETURNING *\n            \"\"\", (current[\"id\"],))\n            row = self._json_ready(self._row(cur, cur.fetchone())) or {}\n            cur.execute(\"\"\"\n                INSERT INTO generation_events(job_id,event_type,data,details)\n                VALUES (%s,'directed_audio_fit_rearmed',\n                        'Approved directed pilot rearmed for bounded audio runtime fit',\n                        %s::jsonb)\n            \"\"\", (row[\"id\"], json.dumps({\n                \"prior_error\": current.get(\"error\"),\n                \"spent_cost_usd\": row.get(\"spent_cost_usd\"),\n                \"max_cost_usd\": row.get(\"max_cost_usd\"),\n            })))\n            return row\n\n'''
if anchor not in text:
    raise SystemExit("durable store anchor missing")
text = text.replace(anchor, method + anchor, 1)
p.write_text(text, encoding="utf-8")


# 3) Let the existing recovery cron perform the one-shot salvage automatically after deploy.
p = Path("app.py")
text = p.read_text(encoding="utf-8")
old_cron = '''@app.get("/api/cron/render-recovery")\nasync def render_recovery_cron():\n    try:\n        result = await _run_durable_explainer_worker()\n        store, blob = _durable_components()\n        cleanup = await asyncio.to_thread(durable_execution.cleanup_orphans, store, blob)\n        return {**result, "orphan_cleanup": cleanup}\n'''
new_cron = '''@app.get("/api/cron/render-recovery")\nasync def render_recovery_cron():\n    try:\n        store, blob = _durable_components()\n        audio_salvage = await asyncio.to_thread(store.rearm_next_directed_audio_runtime_failure)\n        result = await _run_durable_explainer_worker(\n            str(audio_salvage["id"]) if audio_salvage else None)\n        cleanup = await asyncio.to_thread(durable_execution.cleanup_orphans, store, blob)\n        return {**result, "directed_audio_salvage": audio_salvage or {},\n                "orphan_cleanup": cleanup}\n'''
if old_cron not in text:
    raise SystemExit("render recovery cron anchor missing")
text = text.replace(old_cron, new_cron, 1)
p.write_text(text, encoding="utf-8")
