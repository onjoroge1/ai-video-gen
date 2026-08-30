from __future__ import annotations

import json
import shutil
from pathlib import Path

import quiz_pipeline as qp


out = Path("quiz_pilot_output")
out.mkdir(exist_ok=True)
result = qp.run_quiz_pipeline(
    category="wild animals",
    output_dir=str(out),
    n_items=3,
    voice="echo",
    operator_direction=(
        "Render the controlled three-round retention test. Preserve the current Quiz V2.2 "
        "visual treatment, Luckiest Guy typography, habitat clues, Bolt reveal reactions, "
        "and the seamless loop. Use exactly three broadly recognizable wild animals ordered "
        "MEDIUM, HARD, EXPERT. Difficulty must come from plausible confusables and pose, not "
        "from obscure species. Keep all narration inside the 2.4-second search windows."
    ),
    progress_cb=print,
)
Path("quiz_pilot_result.json").write_text(
    json.dumps(result, indent=2, default=str), encoding="utf-8"
)
primary = Path(result["output_path"])
if not primary.is_file() or primary.stat().st_size == 0:
    raise SystemExit(f"primary quiz video missing: {primary}")
packaged = out / "three_animal_pacing_pilot.mp4"
if primary.resolve() != packaged.resolve():
    shutil.copy2(primary, packaged)

summary = {
    "primary": str(primary),
    "packaged": str(packaged),
    "title": result.get("title"),
    "duration_sec": result.get("duration_sec"),
    "actual_cost": result.get("actual_cost"),
    "scene_count": result.get("scene_count"),
    "items": len((result.get("script") or {}).get("items") or []),
    "primary_variant": result.get("primary_variant"),
}
print(json.dumps(summary, indent=2, default=str))
