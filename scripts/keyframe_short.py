"""Build a vertical keyframe Short end to end from one JSON spec: stills, narration, Kling clips,
captions, music, loop, MP4.

    python3 scripts/keyframe_short.py spec/<name>.json stills     # start/end stills per shot
    python3 scripts/keyframe_short.py spec/<name>.json narrate    # TTS per beat + word timing
    python3 scripts/keyframe_short.py spec/<name>.json clips      # Kling via fal, gated, per shot
    python3 scripts/keyframe_short.py spec/<name>.json regate     # re-judge downloaded clips, free
    python3 scripts/keyframe_short.py spec/<name>.json assemble   # captions, music, loop
    python3 scripts/keyframe_short.py spec/<name>.json status     # what exists, what it cost

Stages are idempotent: each skips work whose output already exists, so a partial run is never
paid for twice. `stills` and `narrate` are independent; `clips` needs both (a shot without an
explicit duration takes 5 s if the beat's narration fits, else 10 s); `assemble` needs all three.

BEATS AND SHOTS. A beat is one narration line and one caption. A beat holds one or more SHOTS,
each a start still, an end still and a motion prompt. The penguin review made the case: asking one
continuous generation to carry weeks of biological change (a lean bird enters the water, a plump
one climbs out) reads as a transformation, not as elapsed time, and compressing a 10 s take into a
6 s window plays a feeding at 1.7x. So a beat may cut between shots, and each shot contributes only
the window named by `use: [in, out]` at natural speed. A beat whose picture runs short holds its
last frame; one that runs long loses the tail of its last shot. Legacy specs that put start/end/
motion directly on the beat are treated as one shot fitted by time-remap, as before.

Rules carried over from the earlier builds:
  * an end still is drawn in image-edit mode from ITS OWN start still, never another shot's;
  * narration is measured with real TTS before any clip is bought (the only honest duration);
  * every clip is gated for real motion, a locked camera measured against the authored stills,
    and arrival at the end frame; a failure buys at most one more candidate under a hard USD cap;
  * captions sit in the Shorts safe zone; music has no tail fade; the Short closes by dissolving
    into its own first frame so it loops.

Paid calls: OpenAI images / TTS / Whisper, fal.ai Kling. The directed adapter's ALLOW_PAID is
flipped for this process only, on the operator's chat instruction.
"""
from __future__ import annotations
import concurrent.futures
import json
import os
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(usecwd=True))

import numpy as np                                             # noqa: E402
from PIL import Image                                          # noqa: E402
import fal_models                                              # noqa: E402
import explainer_pipeline as ep                                # noqa: E402
from bolt_seq.providers import directed_video as DV            # noqa: E402

W, H, FPS = 1080, 1920, 30
STILL_SIZE = "1024x1536"
PAD_AFTER_VO = 0.45           # seconds of picture after the last word of each beat
LOOP_XFADE = 0.5              # dissolve from the last clip into the first frame
MUSIC_DB = -19                # music under narration
MAX_CANDIDATES = 2
MAX_INFLIGHT = 2              # fal reserves worst-case cost per in-flight request; bursts lock the account


def _ffprobe_dur(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    return float(out or 0)


class Short:
    def __init__(self, spec_path):
        self.spec = json.load(open(spec_path))
        self.name = self.spec["name"]
        self.dir = os.path.join(ROOT, "renders", self.name)
        self.stills = os.path.join(self.dir, "stills")
        self.audio = os.path.join(self.dir, "audio")
        self.clips = os.path.join(self.dir, "clips")
        self.build = os.path.join(self.dir, "build")
        for d in (self.stills, self.audio, self.clips, self.build):
            os.makedirs(d, exist_ok=True)
        self.ledger_path = os.path.join(self.dir, "ledger.json")
        self.ledger = json.load(open(self.ledger_path)) if os.path.exists(self.ledger_path) else {"usd": {}, "clips": {}}

    # ── beats and shots ────────────────────────────────────────────────────────────────────────
    def shots(self, beat):
        """The shots of a beat. A legacy beat (start/end/motion on the beat itself) is one shot
        fitted by remap; a beat with `shots` cuts between them at natural speed."""
        if beat.get("shots"):
            return [dict(s, beat=beat["id"], fit="cut") for s in beat["shots"]]
        return [{"id": beat["id"], "beat": beat["id"], "start": beat["start"], "end": beat["end"],
                 "motion": beat["motion"], "fit": "remap"}]

    def all_shots(self):
        return [s for b in self.spec["beats"] for s in self.shots(b)]

    # ── bookkeeping ────────────────────────────────────────────────────────────────────────────
    def spend(self, key, usd):
        # `stills` and `narrate` may run in two processes at once; merge the on-disk spend first so
        # one stage's save cannot erase the other's.
        if os.path.exists(self.ledger_path):
            disk = json.load(open(self.ledger_path)).get("usd", {})
            for k, v in disk.items():
                if k != key:
                    self.ledger["usd"][k] = v
        self.ledger["usd"][key] = round(self.ledger["usd"].get(key, 0.0) + float(usd), 4)
        self.save()

    def total(self):
        return round(sum(self.ledger["usd"].values()), 2)

    def save(self):
        json.dump(self.ledger, open(self.ledger_path, "w"), indent=2)

    def still(self, shot_id, which):
        return os.path.join(self.stills, f"{shot_id}_{which}.png")

    # ── stage: stills ──────────────────────────────────────────────────────────────────────────
    def stage_stills(self, only=None):
        style, end_rule = self.spec["style"], self.spec["end_rule"]
        shots = [s for s in self.all_shots() if not only or s["id"] in only]
        print(f"[stills] {len(shots) * 2} at {STILL_SIZE}, estimate ${len(shots) * (ep._COST_IMG_BASE + ep._COST_IMG_HOST):.2f}")

        def gen(s, which, refs):
            out = self.still(s["id"], which)
            if os.path.exists(out) and os.path.getsize(out) > 0:
                return f"  skip  {s['id']} {which}"
            prompt = style + s[which] + (end_rule if which == "end" else "")
            costs = []
            ep.generate_image(prompt, out, reference_paths=refs, cost_sink=costs, size=STILL_SIZE)
            self.spend("stills", costs[-1])
            return f"  done  {s['id']} {which}  ${costs[-1]:.3f}"

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            for line in pool.map(lambda s: gen(s, "start", None), shots):
                print(line, flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            for line in pool.map(lambda s: gen(s, "end", [self.still(s["id"], "start")]), shots):
                print(line, flush=True)

    # ── stage: narrate ─────────────────────────────────────────────────────────────────────────
    def stage_narrate(self):
        voice = self.spec.get("voice", "onyx")
        for b in self.spec["beats"]:
            mp3 = os.path.join(self.audio, f"{b['id']}.mp3")
            meta = os.path.join(self.audio, f"{b['id']}.json")
            if os.path.exists(meta):
                print(f"  skip  {b['id']} narration ({json.load(open(meta))['duration']:.2f}s)"); continue
            ep.generate_tts(b["vo"], mp3, voice=voice)
            self.spend("tts", len(b["vo"]) * ep._RATE_TTS_CHAR)
            dur = float(ep._audio_dur(mp3))
            try:
                words = ep.transcribe_words(mp3)
                self.spend("whisper", 0.006)
            except Exception as exc:
                words = []; print(f"  (word timing unavailable for {b['id']}: {str(exc)[:80]})")
            json.dump({"duration": dur, "words": words, "text": b["vo"]}, open(meta, "w"), indent=1)
            print(f"  done  {b['id']} narration {dur:.2f}s  ({len(b['vo'].split())} words)", flush=True)
        total = sum(json.load(open(os.path.join(self.audio, f"{b['id']}.json")))["duration"] for b in self.spec["beats"])
        print(f"[narrate] total spoken {total:.1f}s + pads {PAD_AFTER_VO * len(self.spec['beats']):.1f}s")

    def beat_seconds(self, b):
        """Picture time this beat needs, and the Kling duration (5 or 10) that would cover it alone."""
        meta = os.path.join(self.audio, f"{b['id']}.json")
        need = float(json.load(open(meta))["duration"]) + PAD_AFTER_VO
        return need, (5 if need <= 5.0 else 10)

    def shot_seconds(self, beat, shot):
        if shot.get("duration"):
            return int(shot["duration"])
        return self.beat_seconds(beat)[1]

    # ── stage: clips ───────────────────────────────────────────────────────────────────────────
    def clip_spec(self, shot, seconds):
        return {"model": self.spec.get("model", "kling-v3-pro"), "prompt": shot["motion"],
                "negative_prompt": self.spec["negative"], "duration": seconds,
                "generate_audio": False, "cfg_scale": 0.5, "aspect_ratio": "9:16", "resolution": None,
                "seed_image": self.still(shot["id"], "start"), "end_image": self.still(shot["id"], "end")}

    def stage_clips(self, only=None):
        model = self.spec.get("model", "kling-v3-pro")
        cap = float(self.spec.get("hard_cap_usd", 8.0))
        plan = [(b, s, self.shot_seconds(b, s)) for b in self.spec["beats"] for s in self.shots(b)
                if not only or s["id"] in only]
        est = sum(fal_models.estimate_clip_usd(model, sec) for _, _, sec in plan)
        print(f"[clips] {fal_models.resolve(model)}; plan " +
              ", ".join(f"{s['id']}:{sec}s" for _, s, sec in plan) + f"; estimate ${est:.2f}; cap ${cap:.2f}; spent ${self.total():.2f}")
        DV.ALLOW_PAID = True
        adapter = DV.FalKlingAdapter()
        pending = []

        def drain():
            """Poll, download, conform and gate every in-flight job, then clear the list."""
            for s, job, cand in pending:
                raw = os.path.join(self.clips, f"{s['id']}_c{cand['n']}.raw.mp4")
                conformed = os.path.join(self.clips, f"{s['id']}_c{cand['n']}.mp4")
                try:
                    adapter.poll_and_download(job, raw, timeout=900)
                    DV._normalize_media(raw, conformed)
                    result = gate(conformed, self.still(s["id"], "start"), self.still(s["id"], "end"))
                except Exception as exc:
                    result = {"accepted": False, "reasons": [f"provider/gate error: {exc}"[:200]]}
                cand.update({"conformed": conformed, "gate": result, "done_at": time.time()})
                if result["accepted"]:
                    self.ledger["clips"][s["id"]]["accepted"] = conformed
                self.save()
                print(f"  {'PASS' if result['accepted'] else 'FAIL'}  {s['id']} c{cand['n']}  {'; '.join(result.get('reasons') or ['ok'])}", flush=True)
            pending.clear()

        for b, s, seconds in plan:
            rec = self.ledger["clips"].setdefault(s["id"], {"candidates": [], "accepted": None, "seconds": seconds, "beat": b["id"]})
            if rec["accepted"]:
                print(f"  skip  {s['id']} accepted"); continue
            if len(rec["candidates"]) >= MAX_CANDIDATES:
                print(f"  stop  {s['id']} has {MAX_CANDIDATES} candidates, none accepted"); continue
            cost = fal_models.estimate_clip_usd(model, seconds)
            if self.total() + cost > cap:
                print(f"  CAP   {s['id']}: ${self.total():.2f} + ${cost:.2f} > ${cap:.2f}"); continue
            # fal reserves a worst-case cost per IN-FLIGHT request against the balance, so a burst
            # of submissions locks the account with "Exhausted balance" while money remains
            # (measured: three accepted, the fourth refused, on a balance above $11). Cap the
            # in-flight count, and on a refusal let the running jobs settle and try once more.
            if len(pending) >= MAX_INFLIGHT:
                drain()
            job = None
            for attempt in (1, 2):
                try:
                    job = adapter.submit(self.clip_spec(s, seconds), timeout=60)
                    break
                except DV.DirectedVideoFailure as exc:
                    if attempt == 1 and pending:
                        print(f"  wait  {s['id']}: {str(exc)[:80]}... letting {len(pending)} in-flight job(s) settle", flush=True)
                        drain(); time.sleep(5)
                        continue
                    # A balance or quota refusal at submit bills nothing and buys nothing. Stop the
                    # stage cleanly and leave the plan resumable: the next run picks up every shot
                    # that has no accepted candidate.
                    print(f"  STOP  {s['id']}: {exc}\n[clips] provider refused; nothing billed for this shot. "
                          f"Top up and re-run the clips stage to resume.", flush=True)
            if job is None:
                break
            self.spend("clips", cost)
            cand = {"n": len(rec["candidates"]) + 1, "request_id": job["request_id"], "endpoint": job["endpoint"],
                    "payload": job["submitted_payload_sanitized"], "usd": cost, "submitted_at": time.time()}
            rec["candidates"].append(cand); self.save()
            pending.append((s, job, cand))
            print(f"  sent  {s['id']} c{cand['n']} {seconds}s  {job['request_id']}  ${cost:.2f}", flush=True)
        drain()
        acc = [k for k, v in self.ledger["clips"].items() if v["accepted"]]
        print(f"[clips] accepted {len(acc)}/{len(self.all_shots())}; spent ${self.total():.2f}")

    def stage_regate(self):
        """Re-judge every downloaded candidate with the current gates. Free."""
        for s in self.all_shots():
            rec = self.ledger["clips"].get(s["id"])
            if not rec:
                continue
            rec["accepted"] = None
            for cand in rec["candidates"]:
                if not cand.get("conformed") or not os.path.exists(cand["conformed"]):
                    continue
                cand["gate"] = gate(cand["conformed"], self.still(s["id"], "start"), self.still(s["id"], "end"))
                cand["gate"]["regated_at"] = time.time()
                if cand["gate"]["accepted"] and not rec["accepted"]:
                    rec["accepted"] = cand["conformed"]
                print(f"  {'PASS' if cand['gate']['accepted'] else 'FAIL'}  {s['id']} c{cand['n']}  {'; '.join(cand['gate']['reasons'] or ['ok'])}")
        self.save()
        acc = [k for k, v in self.ledger["clips"].items() if v["accepted"]]
        print(f"[regate] accepted {len(acc)}/{len(self.all_shots())}")

    # ── stage: assemble ────────────────────────────────────────────────────────────────────────
    def _beat_picture(self, b, need, seg):
        """Render one beat's picture to `seg`, exactly `need` seconds, caption burned in."""
        shots = self.shots(b)
        parts = []
        for i, s in enumerate(shots):
            clip = self.ledger["clips"][s["id"]]["accepted"]
            part = os.path.join(self.build, f"{s['id']}_part.mp4")
            clip_dur = _ffprobe_dur(clip)
            if s["fit"] == "remap":
                # Legacy single-shot beat: fit the whole take to the window by time-remap (up to
                # ~1.8x on Kling's slow directed motion), never by trimming from the start, so the
                # paid-for end frame is reached.
                filt = (f"setpts=PTS*{need / clip_dur:.5f},fps={FPS}" if clip_dur > need + 0.05
                        else f"tpad=stop_mode=clone:stop_duration=12,trim=0:{need:.3f},setpts=PTS-STARTPTS,fps={FPS}")
                filt += f",trim=0:{need:.3f},setpts=PTS-STARTPTS"
            else:
                # Cut: the shot contributes only its `use` window at natural speed.
                lo, hi = (s.get("use") or [0, clip_dur])
                hi = min(float(hi), clip_dur)
                filt = f"trim={float(lo):.3f}:{hi:.3f},setpts=PTS-STARTPTS,fps={FPS}"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip, "-vf", filt, "-an",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", part], check=True)
            parts.append(part)
        lst = os.path.join(self.build, f"{b['id']}_parts.txt")
        open(lst, "w").write("".join(f"file '{p}'\n" for p in parts))
        joined = os.path.join(self.build, f"{b['id']}_joined.mp4")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", joined], check=True)
        cap_png = os.path.join(self.build, f"{b['id']}_caption.png")
        # The caption font has no middle-dot glyph; separators become a comma before drawing.
        caption = b["caption"].replace(" · ", ", ").replace("·", ",")
        ep._make_caption_png(caption, W, H, cap_png, style_mode="educational")
        # Hold the last frame if the shots run short of the narration; trim if they run long.
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", joined, "-i", cap_png, "-filter_complex",
                        f"[0:v]tpad=stop_mode=clone:stop_duration=12,trim=0:{need:.3f},setpts=PTS-STARTPTS,fps={FPS}[v];"
                        f"[v][1:v]overlay=0:0:format=auto,format=yuv420p[o]",
                        "-map", "[o]", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", seg], check=True)
        return seg

    def stage_assemble(self):
        beats = self.spec["beats"]
        missing = [s["id"] for s in self.all_shots() if not self.ledger["clips"].get(s["id"], {}).get("accepted")]
        if missing:
            raise SystemExit(f"assemble: no accepted clip for {missing}")
        segs, audio_parts, t = [], [], 0.0
        for b in beats:
            need, _ = self.beat_seconds(b)
            segs.append(self._beat_picture(b, need, os.path.join(self.build, f"{b['id']}_seg.mp4")))
            audio_parts.append((os.path.join(self.audio, f"{b['id']}.mp3"), t))
            t += need
        total = t
        lst = os.path.join(self.build, "segs.txt")
        open(lst, "w").write("".join(f"file '{s}'\n" for s in segs))
        body = os.path.join(self.build, "body.mp4")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", body], check=True)
        video = os.path.join(self.build, "video.mp4")
        # A loop is an editorial choice, not a Shorts law. Nature Story sets loop=false when
        # dissolving the ending back to frame one would reverse offspring age, chronology, or a
        # one-way state change. Legacy specs retain the old behavior because the default is True.
        if self.spec.get("loop", True):
            first = os.path.join(self.build, "first_frame.png")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", segs[0], "-frames:v", "1", first], check=True)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", body, "-loop", "1", "-t", f"{LOOP_XFADE:.2f}", "-i", first,
                            "-filter_complex", f"[0:v]settb=AVTB,fps={FPS}[a];[1:v]settb=AVTB,fps={FPS},format=yuv420p[f];"
                                               f"[a][f]xfade=transition=fade:duration={LOOP_XFADE}:offset={total - LOOP_XFADE:.3f}[o]",
                            "-map", "[o]", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", video], check=True)
        else:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", body, "-c:v", "copy",
                            "-movflags", "+faststart", video], check=True)
        inputs, filt, mixes = [], [], []
        for i, (mp3, start) in enumerate(audio_parts):
            inputs += ["-i", mp3]
            filt.append(f"[{i}:a]adelay={int(start * 1000)}|{int(start * 1000)}[n{i}]")
            mixes.append(f"[n{i}]")
        music = music_path(self.spec.get("music_mood", "nostalgic"))
        n = len(audio_parts)
        if music:
            inputs += ["-i", music]
            filt.append(f"[{n}:a]atrim=0:{total:.3f},afade=t=in:d=0.6,volume={MUSIC_DB}dB[m]")
            mixes.append("[m]")
        filt.append("".join(mixes) + f"amix=inputs={len(mixes)}:normalize=0:duration=longest,atrim=0:{total:.3f}[a]")
        mixed = os.path.join(self.build, "mix.m4a")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filt), "-map", "[a]",
                        "-c:a", "aac", "-b:a", "192k", mixed], check=True)
        final = os.path.join(self.dir, f"{self.name}_short.mp4")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-i", mixed, "-map", "0:v", "-map", "1:a",
                        "-c:v", "copy", "-c:a", "copy", "-shortest", "-movflags", "+faststart", final], check=True)
        srt = os.path.join(self.dir, f"{self.name}_captions.srt")
        with open(srt, "w") as f:
            tt = 0.0
            for i, b in enumerate(beats, 1):
                need, _ = self.beat_seconds(b)
                f.write(f"{i}\n{ep._srt_ts(tt)} --> {ep._srt_ts(tt + need)}\n{b['vo']}\n\n"); tt += need
        print(f"[assemble] {final}  {_ffprobe_dur(final):.1f}s  music={'yes' if music else 'NO'}  total spend ${self.total():.2f}")
        return final

    def stage_status(self):
        for b in self.spec["beats"]:
            n = os.path.exists(os.path.join(self.audio, f"{b['id']}.json"))
            for s in self.shots(b):
                st = all(os.path.exists(self.still(s["id"], w)) for w in ("start", "end"))
                c = bool(self.ledger["clips"].get(s["id"], {}).get("accepted"))
                print(f"  {b['id']}/{s['id']}  stills={'ok' if st else '--'}  narration={'ok' if n else '--'}  clip={'ok' if c else '--'}")
        print(f"spend: {self.ledger['usd']}  total ${self.total():.2f}")


# ── gates (as calibrated on the Four Pests and dinosaur clips) ─────────────────────────────────
def _gray_frames(path, w=192, h=340):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"scale={w}:{h}", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    n = len(raw) // (w * h)
    return np.frombuffer(raw[: n * w * h], dtype=np.uint8).reshape(n, h, w).astype(np.int16)


def _shift(a, b, axis):
    pa, pb = a.mean(axis=axis), b.mean(axis=axis)
    pa, pb = pa - pa.mean(), pb - pb.mean()
    return int(np.argmax(np.correlate(pa, pb, mode="full")) - (len(pb) - 1))


def _still_gray(path, w, h):
    return np.asarray(Image.open(path).convert("L").resize((w, h)), dtype=np.float32)


def gate(path, start_png, end_png):
    g = _gray_frames(path)
    d = np.abs(np.diff(g, axis=0))
    motion = {"frames": int(len(g)), "per_frame_mean": round(float(d.mean(axis=(1, 2)).mean()), 2),
              "local_frac": round(float((d.max(axis=(1, 2)) > 30).mean()), 2)}
    gf = _gray_frames(path, 240, 426).astype(np.float32)
    s, e = _still_gray(start_png, 240, 426), _still_gray(end_png, 240, 426)
    first = (_shift(gf[0], s, 0), _shift(gf[0], s, 1)); last = (_shift(gf[-1], e, 0), _shift(gf[-1], e, 1))
    drift = {"dx": last[0] - first[0], "dy": last[1] - first[1]}
    s2, e2 = _still_gray(start_png, 192, 340), _still_gray(end_png, 192, 340)
    to_end, to_start = float(np.abs(g[-1] - e2).mean()), float(np.abs(g[-1] - s2).mean())
    baseline = float(np.abs(s2 - e2).mean())
    arrival = {"last_to_end": round(to_end, 2), "last_to_start": round(to_start, 2), "still_gap": round(baseline, 2),
               "arrived": bool(to_end < to_start) if baseline > 4 else True}
    # A clip whose last frame has clearly travelled from the start still to the end still has
    # moved, even when the change is spatially small or slow (hatchlings curling up to sleep).
    margin = to_start - to_end
    arrival["margin_frac"] = round(margin / baseline, 2) if baseline > 4 else None
    strong_arrival = baseline > 4 and margin >= 0.3 * baseline
    reasons = []
    if not (motion["per_frame_mean"] >= 0.45 or motion["local_frac"] >= 0.55 or strong_arrival):
        reasons.append(f"near-still: mean {motion['per_frame_mean']} local {motion['local_frac']} "
                       f"arrival margin {arrival['margin_frac']}")
    if abs(drift["dx"]) > 6 or abs(drift["dy"]) > 6:
        reasons.append(f"camera drift dx={drift['dx']} dy={drift['dy']}")
    if not arrival["arrived"]:
        reasons.append(f"did not arrive at end frame ({arrival['last_to_end']} vs {arrival['last_to_start']})")
    return {"motion": motion, "drift": drift, "arrival": arrival, "accepted": not reasons, "reasons": reasons}


def music_path(mood):
    """The repo's checksum-verified track for a mood, with a direct verified download as the
    fallback when get_music_path cannot reach Postgres."""
    import music_assets as ma
    try:
        p = ma.get_music_path(mood)
        if p:
            return p
    except Exception as exc:
        print(f"  music via get_music_path failed ({str(exc)[:80]}); downloading directly")
    cfg = ma.MUSIC_ASSETS[mood]
    dest = os.path.join(ROOT, "renders", "_music", cfg["filename"])
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if not ma._valid_audio(ma.Path(dest), cfg["sha256"]):
        import requests
        with requests.get(cfg["object_url"], timeout=(10, 90), stream=True, headers={"User-Agent": "ReelForge/1.0"}) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        if not ma._valid_audio(ma.Path(dest), cfg["sha256"]):
            print("  music download failed checksum; assembling without music"); return None
    return dest


if __name__ == "__main__":
    spec_path, stage = sys.argv[1], sys.argv[2]
    only = set(sys.argv[3].split(",")) if len(sys.argv) > 3 else None     # e.g. stills b2a,b5b
    s = Short(spec_path)
    if stage == "stills":
        s.stage_stills(only)
    elif stage == "clips":
        s.stage_clips(only)
    else:
        {"narrate": s.stage_narrate, "regate": s.stage_regate,
         "assemble": s.stage_assemble, "status": s.stage_status}[stage]()
