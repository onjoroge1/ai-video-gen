"""Run one illustrated long-form film on this machine, outside the studio server.

The studio's public route (`/api/explainer/generate`) runs the same pipeline in-process but
always with the module's $25 ceiling. This launcher exists so a laptop run can carry a tighter
ceiling, a stable output directory, and a log file that survives the process.

Usage:
    python scripts/run_illustrated_local.py --question "..." --direction-file direction.txt \
        --out jobs/<slug> --duration 300 --max-cost 12

Resume a stopped run with the same --out and --resume.

The story-contract lane (docs/STORY_CONTRACT_LANE.md) runs beside the compiled one:
    python scripts/run_illustrated_local.py --lane story_contract --question "..." \
        --out jobs/<slug> --dossier jobs/<other>/research_dossier.json --stop-after script
It stops for the contract (copy contract.json to contract.approved.json) and for the exact
narration (--approve-narration <sha256>), then segments it and resumes the existing pipeline.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=False)


def _add_ledger(summary: dict, out: Path) -> None:
    # Spend across EVERY launch of this job, from the per-call ledger. actual_cost counts only
    # the last launch's sinks, which on V13 (eight launches) understated the job's real spend.
    try:
        import usage_ledger
        spend = usage_ledger.summarize(str(out / usage_ledger.LEDGER_FILENAME))
        summary["ledger_total_usd"] = spend["total_usd"]
        summary["ledger_by_provider"] = spend["by_provider"]
        summary["ledger_by_kind"] = spend["by_kind"]
    except Exception:  # noqa: BLE001 - accounting never fails the run record
        pass


def _add_turn(summary: dict, out: Path) -> None:
    # Where the first consequence ended, and late_turn when it missed the 45-second limit after
    # its one revision (opening_turn). Reported, never a degraded reason (operator, 2026-10-14).
    # Read from the checkpoint when the pipeline stopped before returning (OpeningBelowB).
    if summary.get("opening_turn") is not None:
        return
    try:
        import opening_turn
        state = json.loads((out / "_state.json").read_text())
        summary.update(opening_turn.run_result_fields(state.get("script") or {})
                       or {"opening_turn": None, "late_turn": None})
    except Exception:  # noqa: BLE001 - a report field never fails the run record
        pass


def _run_story_contract_lane(args, out: Path, direction: str, log):
    """The lane's pre-media stages. Returns an exit code when it stops for the operator, or None
    once the approved narration is segmented into <out>/_state.json for the pipeline to resume."""
    import shutil
    import story_contract as sc
    import usage_ledger
    usage_ledger.set_job_dir(str(out))
    pack = None
    if args.source_pack:
        import source_pack
        pack = source_pack.load_pack(args.source_pack)
    dossier_path = Path(args.dossier).resolve() if args.dossier else out / "research_dossier.json"
    if dossier_path.is_file():
        dossier = json.loads(dossier_path.read_text())
        log(f"story_contract: dossier {dossier_path} ({len(dossier.get('claims') or [])} claims; "
            "no research bought)")
        if dossier_path != out / "research_dossier.json":
            shutil.copyfile(dossier_path, out / "research_dossier.json")
    else:
        import explainer_pipeline as ep
        log("story_contract: no cached dossier; running the existing research")
        dossier = ep.generate_research_dossier(args.question, duration_sec=args.duration,
                                               source_pack=pack, log=log)
        (out / "research_dossier.json").write_text(json.dumps(dossier, indent=1, ensure_ascii=False))
    lane = sc.LaneRun(question=args.question, output_dir=str(out), duration_sec=args.duration,
                      direction=direction, dossier=dossier, pack=pack, log=log)

    def stop(status: str, message: str, path: str = "", details: dict | None = None, code: int = 0):
        result = {"status": status, "lane": sc.LANE, "stop_reason": message, "approval_path": path,
                  "details": details or {}, "repair_passes_used": lane.budget.used(),
                  "repair_passes_max": lane.budget.maximum}
        _add_ledger(result, out)
        (out / "run_result.json").write_text(json.dumps(result, indent=2, default=str))
        log(f"story_contract: {status}: {message}")
        log(f"story_contract: spend so far ${result.get('ledger_total_usd', 0):.4f} "
            f"{json.dumps(result.get('ledger_by_provider') or {})}")
        return code

    try:
        record = lane.run(stop_after=args.stop_after, approve_narration=args.approve_narration)
        state = lane.segment(record)
    except sc.LaneStop as exc:
        return stop(exc.status, str(exc), exc.path, exc.details,
                    code=3 if isinstance(exc, sc.ContractInvalid) else 0)
    state_path = out / "_state.json"
    if state_path.is_file():
        try:
            prior = json.loads(state_path.read_text()).get("script") or {}
        except ValueError:
            prior = {}
        meta = prior.get("_story_contract_lane") or {}
        if meta.get("approved_narration_sha256") != record["sha256"]:
            backup = out / f"_state.pre_story_contract_{time.strftime('%Y%m%d_%H%M%S')}.json"
            shutil.copyfile(state_path, backup)
            log(f"story_contract: kept the previous checkpoint as {backup.name}")
        else:
            log("story_contract: checkpoint already holds this approved narration; resuming it")
            return None
    state_path.write_text(json.dumps(state, ensure_ascii=False))
    log(f"story_contract: segmented {len(state['script']['scenes'])} scenes (words unchanged) -> "
        f"{state_path}; resuming the pipeline on the approved narration")
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", required=True)
    parser.add_argument("--direction-file", default="")
    parser.add_argument("--out", required=True)
    parser.add_argument("--duration", type=int, default=300)
    parser.add_argument("--voice", default="echo")
    parser.add_argument("--max-cost", type=float, default=12.0)
    parser.add_argument("--topic-channel", default="")
    parser.add_argument("--motion-mode", default="stills")   # motion returns once the scripts hold (2026-10-02)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--engine", default="",
                        help="pin the story engine for this run, e.g. accumulating_indictment "
                             "(story_engines.ENGINES); empty lets the selector choose")
    parser.add_argument("--opening", choices=("ladder", "myth", "witness"), default="ladder",
                        help="ladder: the human-first frame; myth: the myth-buster opening "
                             "(\"You'd think ...\", bust, danger, question, then the story); "
                             "witness: the myth opening with the scale in the bust and one "
                             "documented person's moment in place of the danger")
    parser.add_argument("--no-synthesis", action="store_true",
                        help="plan no recap (synthesis) scene before the close")
    parser.add_argument("--music", action="store_true",
                        help="add the locally composed chamber score (ILLUSTRATED_MUSIC=1)")
    parser.add_argument("--palette", choices=("plates", "natural"), default="plates",
                        help="plates: each story role on its own coloured paper stock; natural: "
                             "true-to-life colour with the role carried by light (World, 2026-10-21)")
    parser.add_argument("--music-mix", choices=("ducked", "ambient_pad"), default="ducked",
                        help="ducked: the score ducks under the voice; ambient_pad: a low, steady "
                             "blurred bed with no ducking (World, 2026-10-21)")
    parser.add_argument("--packaging", choices=("world", "history"), default="world",
                        help="title and thumbnail style: world (FATAL ERROR backfire packaging for "
                             "backfire engines) or history (Bolt Explains History)")
    parser.add_argument("--source-pack", default="",
                        help="slug (topics/source_packs/<slug>.json) or path of an operator source pack: "
                             "primary documents research fetches itself and quotes verbatim (source_pack.py)")
    parser.add_argument("--stop-after", choices=("plan", "contract", "script"), default="",
                        help="plan: write plan.json/plan_for_approval.md and stop (copy to "
                             "plan.approved.json to approve); script: stop after the narration. "
                             "story_contract lane: contract (= plan) stops at the story contract, "
                             "script at the narration for approval")
    parser.add_argument("--lane", choices=("compiled", "story_contract"), default="compiled",
                        help="compiled: the engine lane (default, unchanged); story_contract: the "
                             "contract-first lane beside it (story_contract.py)")
    parser.add_argument("--dossier", default="",
                        help="story_contract lane: a cached research_dossier.json to plan from (no "
                             "research spend); default <out>/research_dossier.json, else research runs")
    parser.add_argument("--approve-narration", default="",
                        help="story_contract lane: approve the narration with this exact sha256")
    args = parser.parse_args()

    if args.engine:
        os.environ["STORY_ENGINE"] = args.engine
    if args.opening in ("myth", "witness"):
        os.environ["OPENING_HOOK"] = args.opening
    if args.no_synthesis:
        os.environ["SYNTHESIS_DEVICE"] = "off"
    if args.music:
        os.environ["ILLUSTRATED_MUSIC"] = "1"
    if args.palette == "natural":
        os.environ["ILLUSTRATED_PALETTE"] = "natural"
    if args.music_mix == "ambient_pad":
        os.environ["MUSIC_MIX"] = "ambient_pad"
    if args.packaging == "history":
        os.environ["PACKAGING_STYLE"] = "history"
    if args.source_pack:
        import source_pack
        if source_pack.load_pack(args.source_pack) is None:     # fail before any paid call
            parser.error(f"--source-pack {args.source_pack!r}: no such pack")
        os.environ["SOURCE_PACK"] = args.source_pack
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    # The exact command, so a rescue can resume with the same flags (scripts/rescue_script.py).
    if not args.resume:
        import shlex
        (out / "run_command.txt").write_text(" ".join(shlex.quote(a) for a in [sys.executable] + sys.argv) + "\n")
    log_path = out / "run.log"
    direction = Path(args.direction_file).read_text() if args.direction_file else ""

    from provider_readiness import illustrated_provider_readiness
    readiness = illustrated_provider_readiness()
    if not readiness["configured"]:
        print("providers not configured:", readiness["missing_configuration"])
        return 2

    import explainer_pipeline as ep

    def log(msg: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        line = f"[{stamp}] {msg}"
        print(line, flush=True)
        with open(log_path, "a") as handle:
            handle.write(line + "\n")

    log(f"launch question={args.question!r} duration={args.duration} cap=${args.max_cost:.2f} "
        f"resume={args.resume} out={out}" + (f" lane={args.lane}" if args.lane != "compiled" else ""))
    if args.lane == "story_contract":
        stopped = _run_story_contract_lane(args, out, direction, log)
        if stopped is not None:
            return stopped
        args.resume = True        # continue from the segmented _state.json
    elif args.stop_after == "contract":
        parser.error("--stop-after contract is for --lane story_contract (use plan)")
    started = time.time()
    try:
        result = ep.run_explainer_pipeline(
            question=args.question,
            output_dir=str(out),
            duration_sec=args.duration,
            voice=args.voice,
            style="engaging and scientific",
            fact_check=True,
            video_format="landscape",
            max_cost_usd=args.max_cost,
            resume=args.resume,
            i2v=True,
            motion_mode=args.motion_mode,
            operator_direction=direction,
            story_format="standard_explainer",
            visual_style="illustrated_story",
            topic_channel=args.topic_channel,
            stop_after_plan=args.stop_after == "plan",
            stop_after_script=args.stop_after == "script",
            progress_cb=log,
        )
    except Exception as exc:  # the log file is the record; the exception text is the headline
        log(f"FAILED after {time.time() - started:.0f}s: {type(exc).__name__}: {exc}")
        (out / "run_error.txt").write_text(f"{type(exc).__name__}: {exc}\n")
        if isinstance(exc, ep.OpeningBelowB):
            # A deliberate stop, not a crash: say so in the run result, with the report that
            # prices the options. The exception still propagates, so the run reads as stopped.
            stopped = {"status": "stopped_opening_below_b", "stop_reason": str(exc),
                       "opening_retry_report_path": exc.report_path,
                       "opening_retry": ep._opening_retry_result(exc.decision)}
            _add_ledger(stopped, out)
            _add_turn(stopped, out)
            (out / "run_result.json").write_text(json.dumps(stopped, indent=2, default=str))
        raise
    summary = {k: result.get(k) for k in (
        "status", "output_path", "title", "hook", "scene_count", "duration_sec", "est_cost",
        "actual_cost", "degraded_reasons", "thumbnail_path", "transcript_path", "srt_path",
        "description_path", "technical_status", "automated_grade_status", "rendered_contract_path",
        "storyboard_path", "generation_manifest_path", "opening_retry", "opening_turn",
        "late_turn")}
    _add_ledger(summary, out)
    _add_turn(summary, out)
    (out / "run_result.json").write_text(json.dumps(summary, indent=2, default=str))
    log(f"DONE in {time.time() - started:.0f}s: {json.dumps(summary, default=str)[:600]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
