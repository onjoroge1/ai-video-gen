"""Bounded adapters. Credentials stay in the parent; engines receive only local files."""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from .jobs import EngineRequest, PINS


def repo_root() -> Path:
    return Path(os.environ.get("REELFORGE_ENGINE_ROOT") or Path(__file__).resolve().parents[2]).resolve()


def check_disk(path: Path, input_bytes: int):
    # PNG sequences and intermediate encodes need additional headroom.
    if shutil.disk_usage(path).free < input_bytes + 3 * 1024**3:
        raise ValueError("Insufficient scratch space: reserve inputs plus 3 GiB")


def command(args: list[str], *, cwd: Path | None = None, timeout=240, env=None) -> str:
    """Bound process trees, including upstream subprocesses; do not expose logs in HTTP."""
    with tempfile_log() as stdout, tempfile_log() as stderr:
        process = subprocess.Popen(args, cwd=cwd, env=env, stdout=stdout, stderr=stderr,
                                   start_new_session=True)
        try:
            process.wait(timeout=timeout)
        except BaseException:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise
        if process.returncode:
            stderr.seek(0)
            detail = stderr.read(4000).decode(errors="replace")
            raise RuntimeError(f"Local engine process failed ({process.returncode}): {detail}")
        stdout.seek(0)
        return stdout.read(256 * 1024).decode(errors="replace")


def tempfile_log():
    import tempfile
    return tempfile.TemporaryFile()


def probe(path: str | Path) -> dict:
    data = json.loads(command(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], timeout=30))
    duration = float(data.get("format", {}).get("duration", 0))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Input has no finite positive duration")
    video = next((x for x in data["streams"] if x.get("codec_type") == "video"), {})
    audio = next((x for x in data["streams"] if x.get("codec_type") == "audio"), {})
    return {"duration_sec": duration, "video": video, "audio": audio}


def inspect_inputs(request: EngineRequest, paths: dict) -> float:
    source = probe(paths["source"]) if "source" in paths else None
    if source and not source["audio"]:
        raise ValueError("The narration/source video has no audio stream")
    if source and (not source["video"] or source["duration_sec"] > 3600):
        raise ValueError("Source must be a video no longer than one hour")
    if request.engine == "openshorts":
        if request.end_sec > source["duration_sec"] + 0.001:
            raise ValueError("Requested span exceeds the actual source duration")
        return request.end_sec - request.start_sec
    if request.engine == "moneyprinterturbo":
        if source["duration_sec"] > 90:
            raise ValueError("Stock assembly is limited to 90 seconds of existing narration")
        total = 0
        for i in range(len(request.material_video_ids)):
            media = probe(paths[f"material-{i}"])
            video = media["video"]
            if not video or min(video.get("width", 0), video.get("height", 0)) < 480:
                raise ValueError("Stock material must be a video at least 480px in each dimension")
            if media["duration_sec"] > 300:
                raise ValueError("Use material clips no longer than five minutes")
            total += media["duration_sec"]
        if total + 0.001 < source["duration_sec"]:
            raise ValueError("Not enough supplied footage to cover the narration without recycling")
        return source["duration_sec"]
    duration = request.storyboard.shots[-1].end
    if source and abs(source["duration_sec"] - duration) > 0.15:
        raise ValueError("Motion storyboard must match the existing narration duration")
    return duration


def clean_environment(home: Path) -> dict:
    # No DB, Blob, LLM, OAuth, gallery or publishing credentials cross this boundary.
    result = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "SYSTEMROOT") if k in os.environ}
    result.update(HOME=str(home), TMPDIR=str(home), PYTHONNOUSERSITE="1", PYTHONUNBUFFERED="1",
                  FFMPEG_ENCODER="x264", AUDIO_NORMALIZE="0", HF_HUB_OFFLINE="1")
    return result


def readiness(engine: str) -> dict:
    root = repo_root()
    missing = [name for name in ("ffmpeg", "ffprobe") if not shutil.which(name)]
    if engine == "motion_canvas":
        project = root / "integrations/motion-canvas"
        if not shutil.which("node"): missing.append("node")
        for name in ("@motion-canvas/core", "@motion-canvas/2d", "playwright"):
            p = project / "node_modules" / name / "package.json"
            if not p.is_file():
                missing.append(name)
            elif name != "playwright" and json.loads(p.read_text()).get("version") != PINS[engine]:
                missing.append(name + " revision mismatch")
        if not missing:
            try:
                command(["node", "render-job.mjs", "--check"], cwd=project, timeout=25,
                        env=clean_environment(Path(os.environ.get("TMPDIR", "/tmp"))))
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                missing.append("Chromium renderer")
    else:
        target = root / "integrations/video_engines/runtime" / engine
        python = target / (".venv" if engine == "moneyprinterturbo" else ".reelforge-venv") / "bin/python"
        if not python.is_file(): missing.append("isolated Python runtime")
        if not (target / ".git").is_dir():
            missing.append("pinned checkout")
        else:
            try:
                if command(["git", "rev-parse", "HEAD"], cwd=target, timeout=10).strip() != PINS[engine]:
                    missing.append("revision mismatch")
                if command(["git", "status", "--porcelain", "--untracked-files=no"], cwd=target, timeout=10).strip():
                    missing.append("modified upstream source")
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                missing.append("checkout verification")
    return {"engine": engine, "ready_on_this_host": not missing, "missing": missing,
            "scope": "local_media_only", "provider_budget_usd": 0}


def render(request: EngineRequest, paths: dict, output: Path):
    state = readiness(request.engine)
    if not state["ready_on_this_host"]:
        raise RuntimeError("Engine is not installed on this worker: " + ", ".join(state["missing"]))
    root, work = repo_root(), output.parent
    input_file = work / "engine-input.json"
    input_file.write_text(json.dumps({"request": request.model_dump(mode="json"), "paths": paths}))
    env = clean_environment(work)
    if request.engine == "motion_canvas":
        project = root / "integrations/motion-canvas"
        # Use the preinstalled browser in the isolated project, not a download at render time.
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(project / ".browsers")
        command(["node", str(project / "render-job.mjs"), str(input_file), str(work / "frames")],
                cwd=project, env=env, timeout=360)
        frame_files = sorted((work / "frames/job").glob("*.png"))
        count = round(request.storyboard.shots[-1].end * 24)
        if len(frame_files) != count or [p.stem for p in frame_files] != [f"{i:06}" for i in range(count)]:
            raise ValueError("Motion render is missing frames or has the wrong frame range")
        args = ["ffmpeg", "-v", "error", "-y", "-framerate", "24", "-i", str(work / "frames/job/%06d.png")]
        if "source" in paths: args += ["-i", paths["source"], "-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac"]
        args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", str(count / 24), "-movflags", "+faststart", str(output)]
        command(args, env=env)
    else:
        target = root / "integrations/video_engines/runtime" / request.engine
        python = target / (".venv" if request.engine == "moneyprinterturbo" else ".reelforge-venv") / "bin/python"
        command([str(python), str(Path(__file__).with_name("python_worker.py")), str(target), str(input_file), str(output)],
                cwd=work, env=env, timeout=360)


def verify_output(output: Path, request: EngineRequest, duration: float) -> dict:
    data = probe(output)
    video = data["video"]
    if video.get("codec_name") != "h264" or video.get("pix_fmt") != "yuv420p":
        raise ValueError("Output must be browser-safe H.264 yuv420p")
    ratio = 9 / 16 if request.aspect_ratio == "9:16" else 16 / 9
    if not video.get("height") or abs(video["width"] / video["height"] - ratio) > 0.005:
        raise ValueError("Output aspect ratio does not match the immutable job")
    if abs(data["duration_sec"] - duration) > 0.2:
        raise ValueError("Output does not cover the requested narration/span")
    if not request.silent and data["audio"].get("codec_name") != "aac":
        raise ValueError("Output lost its required AAC narration")
    command(["ffmpeg", "-v", "error", "-xerror", "-i", str(output), "-f", "null", "-"], timeout=120)
    return {"duration_sec": data["duration_sec"], "width": video["width"], "height": video["height"],
            "audio_present": bool(data["audio"]), "decoded": True}


def copy_captions(source: str, output: Path, request: EngineRequest, duration: float):
    """Rebase and clip the existing captions; never fabricate a transcript."""
    text = Path(source).read_text(encoding="utf-8-sig")
    if len(text) > 2 * 1024 * 1024:
        raise ValueError("Caption file is too large")
    pattern = re.compile(r"^(\d{2,}):(\d{2}):(\d{2})[,.](\d{3})$")
    def sec(t):
        m = pattern.fullmatch(t.strip())
        if not m: raise ValueError("Malformed source SRT timestamp")
        h, minute, s, ms = map(int, m.groups())
        if minute >= 60 or s >= 60: raise ValueError("Invalid SRT timestamp")
        return h * 3600 + minute * 60 + s + ms / 1000
    def stamp(t):
        ms = round(t * 1000)
        return f"{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}"
    offset = request.start_sec if request.engine == "openshorts" else 0
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        if not block.strip(): continue
        lines = block.splitlines()
        if len(lines) < 3 or not lines[0].strip().isdigit() or " --> " not in lines[1]:
            raise ValueError("Malformed source SRT cue")
        a, b = lines[1].split(" --> ", 1)
        raw_a, raw_b = sec(a), sec(b)
        if raw_b <= raw_a: raise ValueError("SRT cue has nonpositive duration")
        start, end = max(0, raw_a - offset), min(duration, raw_b - offset)
        if end > start:
            cues.append(f"{len(cues)+1}\n{stamp(start)} --> {stamp(end)}\n" + "\n".join(lines[2:]))
    output.write_text("\n\n".join(cues) + "\n", encoding="utf-8")


def thumbnail(video: Path, output: Path):
    command(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-frames:v", "1", "-vf", "scale=360:-2", str(output)], timeout=30)
