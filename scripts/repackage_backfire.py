"""Apply the backfire packaging (title formula + FATAL ERROR thumbnail) to a finished film.

For a run that finished before this packaging existed, or to redo the packaging without
re-rendering. Reads the run directory's script and transcript, writes `thumbnail.jpg` and
`packaging.json` there, and prints the settled title. Never touches the video.

    python scripts/repackage_backfire.py jobs/<slug> [--force-engine]
"""
import argparse
import glob
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=False)


def _load_script(run_dir: Path) -> dict:
    for name in ("script.json", "_state.json"):
        path = run_dir / name
        if path.exists():
            data = json.loads(path.read_text())
            return data.get("script") if name == "_state.json" else data
    candidates = sorted(glob.glob(str(run_dir / "*.script")))
    if candidates:
        return json.loads(Path(candidates[0]).read_text())
    raise SystemExit(f"no script found in {run_dir}")


def _load_transcript(run_dir: Path, script: dict) -> str:
    for path in sorted(run_dir.glob("*.txt")):
        if path.name not in ("direction.txt", "run_error.txt"):
            text = path.read_text().strip()
            if text:
                return text
    return " ".join(str(s.get("narration") or "") for s in script.get("scenes") or [])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    parser.add_argument("--force-engine", action="store_true",
                        help="package even when the script's engine is outside the backfire set")
    parser.add_argument("--question", default="")
    parser.add_argument("--crossed-out", default="",
                        help="the living thing to cross out on the left, e.g. 'a grey wolf in snow'")
    parser.add_argument("--consequence", default="",
                        help="the crowded consequence scene on the right, e.g. 'elk herd on a bare riverbank'")
    args = parser.parse_args()
    run_dir = Path(args.run_dir).resolve()
    script = _load_script(run_dir)
    if args.force_engine:
        script = {**script, "_story_engine": "backfiring_solution"}
    import backfire_packaging as bp

    if not bp.applies(script, "landscape"):
        print(f"engine {script.get('_story_engine')!r} is outside {sorted(bp.ENGINES)}; "
              "pass --force-engine to package anyway")
        return 2
    transcript = _load_transcript(run_dir, script)
    question = args.question or script.get("_question") or script.get("title") or ""
    costs: list[float] = []
    log = lambda message: print(message, flush=True)
    title = bp.propose_title(script.get("title", ""), question, transcript, cost_sink=costs, log=log)
    settled = title or script.get("title", "")
    report: dict = {}
    pairs = None
    if args.crossed_out and args.consequence:
        pairs = [{"crossed_out_subject": args.crossed_out,
                  "crossed_out_scene": f"a large sharp close-up of {args.crossed_out}, facing the camera",
                  "consequence_subject": args.consequence,
                  "consequence_scene": f"a wide dramatic view of {args.consequence}"}]
    thumb = bp.generate_thumbnail(settled, question, transcript, str(run_dir), cost_sink=costs,
                                  report=report, log=log, pairs=pairs)
    payload = {"version": bp.VERSION, "script_title": script.get("title", ""), "title": settled,
               "title_changed": bool(title and title != script.get("title")),
               "thumbnail": thumb, "thumbnail_report": report,
               "cost_usd": round(sum(costs), 4)}
    path = bp.write_report(str(run_dir), payload)
    print(json.dumps(payload, indent=2))
    print("report:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
