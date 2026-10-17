#!/usr/bin/env python3
"""Build a list film from a spec (list_film.py documents the format).

    python3 scripts/make_list_film.py topics/lists/animals-nobody-can-stop.json --out jobs/list-animals
    python3 scripts/make_list_film.py <spec> --out <job> --check-only

Order of work:
1. Structural validation and the fidelity judge on every factual sentence against the claims it
   cites. Any failure stops the build before a single paid media call; the report is
   <out>/fidelity.json.
2. Narration, one line per beat, in the narrator's voice (cached).
3. Pictures: claim-matched from the entry's film, a named scene, or a new drawing (cached).
4. A countdown card before each entry, 16:9 Ken Burns shots no longer than 3.4 s, a chamber bed
   ducked under the voice, captions.srt, description.txt with chapters and sources, and
   run_result.json for upload_job.py.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import list_film as lf  # noqa: E402
import make_teaser_short as mts  # noqa: E402  (fonts, ffmpeg, tts helpers)

W, H, FPS = 1920, 1080, 30
YELLOW, WHITE, GREY = (255, 230, 0), (255, 255, 255), (200, 200, 200)
MOVES = ("push_in", "pull_out", "pan_right", "pan_left")


def _key(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()[:12]


def check(spec: dict, out: str) -> list[dict]:
    """The fidelity judge on every factual beat. Returns the failures (empty = pass)."""
    import claim_entailment as ce
    cache_path = os.path.join(out, "fidelity_cache.json")
    cache = json.load(open(cache_path)) if os.path.isfile(cache_path) else {}
    scripts, rows, failures, sink = {}, [], [], []
    for where, beat in lf.iter_beats(spec):
        if not beat.get("claims"):
            continue
        job = beat["job"]
        script = scripts.setdefault(job, lf.load_script(job))
        ceiling = lf.claim_ceiling(script, beat["claims"])
        verdict = ce.narration_fidelity(ceiling, beat["text"], cache=cache, cost_sink=sink)
        if ce.is_retryable(verdict):
            # An outage is not a verdict: stop, keep nothing, and say so.
            raise SystemExit(f"fidelity judge unavailable ({verdict.get('reason', '')[:120]}); nothing built")
        row = {"where": where, "text": beat["text"], "claims": beat["claims"], "passed": bool(verdict.get("passed")),
               "verdict": verdict.get("verdict"), "unsupported": verdict.get("unsupported_details") or [],
               "reason": verdict.get("reason", "")}
        rows.append(row)
        if not row["passed"]:
            failures.append(row)
    json.dump(cache, open(cache_path, "w"))
    json.dump({"passed": not failures, "checked": len(rows), "failures": failures, "rows": rows,
               "cost_usd": round(sum(x for x in sink if isinstance(x, (int, float))), 4)},
              open(os.path.join(out, "fidelity.json"), "w"), indent=1, ensure_ascii=False)
    return failures


def _picture(prompt: str, style: str, out: str) -> str:
    if os.path.isfile(out):
        return out
    from openai import OpenAI
    full = (f"{style.strip()} {prompt.strip().rstrip('.')}. Landscape 3:2 composition, one large subject, "
            "no text, letters, numbers, logos or watermarks. No gore. People are anonymous.")
    reply = OpenAI().images.generate(model="gpt-image-2", prompt=full, size="1536x1024", quality="high", n=1)
    with open(out, "wb") as handle:
        handle.write(base64.b64decode(reply.data[0].b64_json))
    return out


def _card(path: str, rank: int, label: str, place: str, background: str) -> str:
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps
    bg = ImageOps.fit(Image.open(background).convert("RGB"), (W, H))
    bg = ImageEnhance.Brightness(bg.filter(ImageFilter.GaussianBlur(14))).enhance(0.32)
    draw = ImageDraw.Draw(bg)
    for text, size, colour, y in ((f"#{rank}", 260, YELLOW, 250), (label.upper(), 120, WHITE, 560),
                                  (place, 58, GREY, 720)):
        if not text:
            continue
        font = mts._font(size)
        x = (W - draw.textlength(text, font=font)) / 2
        draw.text((x, y), text, font=font, fill=colour, stroke_width=max(4, size // 20), stroke_fill=(0, 0, 0))
    bg.save(path, quality=95)
    return path


def _shot_clip(shot: dict, index: int, tmp: str) -> str:
    from PIL import Image
    d = max(0.4, shot["end"] - shot["start"])
    n = max(1, int(round(d * FPS)))
    with Image.open(shot["image"]) as im:
        iw, ih = im.size
    cw, ch = (iw, int(iw * 9 / 16)) if iw / ih < 16 / 9 else (int(ih * 16 / 9), ih)
    if shot.get("variant", 0) % 3 == 1:            # a second look at the same picture: tighter, left
        cw, ch = int(cw * 0.8), int(ch * 0.8)
        x, y = 0, (ih - ch) // 2
    elif shot.get("variant", 0) % 3 == 2:          # third look: tighter, right
        cw, ch = int(cw * 0.8), int(ch * 0.8)
        x, y = iw - cw, (ih - ch) // 2
    else:
        x, y = (iw - cw) // 2, (ih - ch) // 2
    move = shot.get("move") or MOVES[index % len(MOVES)]
    z = {"push_in": f"min(1+0.06*on/{n},1.06)", "pull_out": f"max(1.06-0.06*on/{n},1)"}.get(move, "1.06")
    px = {"pan_right": f"(iw-iw/zoom)*on/{n}", "pan_left": f"(iw-iw/zoom)*(1-on/{n})"}.get(move, "iw/2-(iw/zoom/2)")
    clip = os.path.join(tmp, f"shot_{index:04d}.mp4")
    vf = (f"crop={cw}:{ch}:{x}:{y},scale=3840:2160,zoompan=z='{z}':x='{px}':y='ih/2-(ih/zoom/2)'"
          f":d={n}:s={W}x{H}:fps={FPS},format=yuv420p")
    mts._run([mts._ffmpeg_bin(), "-v", "error", "-y", "-loop", "1", "-i", shot["image"], "-t", f"{d:.3f}",
              "-vf", vf, "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-an", clip])
    return clip


def _join_audio(parts: list[tuple[str, object]], out: str) -> None:
    """Narration lines and silences in order, each resampled to one format, as one WAV track."""
    fmt = "aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo"
    cmd, chain, labels, inputs = [mts._ffmpeg_bin(), "-v", "error", "-y"], [], [], 0
    for k, (kind, value) in enumerate(parts):
        if kind == "file":
            cmd += ["-i", str(value)]
            chain.append(f"[{inputs}:a]{fmt}[p{k}]")
            inputs += 1
        else:
            chain.append(f"anullsrc=r=44100:cl=stereo,atrim=0:{float(value):.3f},{fmt}[p{k}]")
        labels.append(f"[p{k}]")
    chain.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[out]")
    graph = os.path.splitext(out)[0] + "_graph.txt"
    with open(graph, "w") as handle:
        handle.write(";".join(chain))
    mts._run(cmd + ["-filter_complex_script", graph, "-map", "[out]", out])


def _silence(seconds: float, out: str) -> str:
    mts._run([mts._ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i",
              f"anullsrc=r=44100:cl=stereo", "-t", f"{seconds:.3f}", "-c:a", "libmp3lame", "-q:a", "2", out])
    return out


def build(spec: dict, out: str) -> dict:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.expanduser("~/ai-video-gen-local"), ".env"))
    load_dotenv(os.path.join(ROOT, ".env"))
    voice = spec.get("voice") or mts.CTA_VOICE
    lines_dir, pics_dir = os.path.join(out, "lines"), os.path.join(out, "pictures")
    os.makedirs(lines_dir, exist_ok=True)
    os.makedirs(pics_dir, exist_ok=True)
    scripts, used = {}, set()

    # The running order: intro, then for each entry a card and its beats, then the outro.
    order = [("beat", "intro", b) for _, b in lf.iter_beats({"intro": spec.get("intro") or []})]
    for e in spec["entries"]:
        order.append(("card", e, None))
        order += [("beat", e, dict(b, job=b.get("job") or e["job"])) for b in e["beats"]]
        order.append(("gap", e, None))
    order += [("beat", "outro", b) for _, b in lf.iter_beats({"outro": spec.get("outro") or []})]

    audio_parts, shots, cues, entry_starts, drops, sources = [], [], [], [], [], []
    t, last_pictures = 0.0, []
    with tempfile.TemporaryDirectory(prefix="list_film_") as tmp:
        for kind, owner, beat in order:
            if kind == "gap":
                audio_parts.append(("silence", lf.ENTRY_GAP_SEC))
                shots.append({"start": t, "end": t + lf.ENTRY_GAP_SEC, "image": last_pictures[-1], "variant": 1})
                t += lf.ENTRY_GAP_SEC
                continue
            if kind == "card":
                e = owner
                script = scripts.setdefault(e["job"], lf.load_script(e["job"]))
                heroes = (lf.pick_pictures(e["job"], script, e["beats"][0].get("claims") or [], set(), want=1)
                          or lf.scene_pictures(e["job"], 0))
                if not heroes:      # a researched entry with no film pictures: its first drawn picture
                    first = next((b for b in e["beats"] if b.get("image")), None)
                    if not first:
                        raise SystemExit(f"entry #{e['rank']} has no film pictures: give its beats image prompts")
                    heroes = [_picture(first["image"], spec.get("style", ""), os.path.join(
                        pics_dir, f"new_{_key(spec.get('style', ''), first['image'])}.png"))]
                hero = heroes[0]
                card = _card(os.path.join(pics_dir, f"card_{e['rank']}.jpg"), e["rank"], e["label"],
                             e.get("place", ""), hero)
                audio_parts.append(("silence", lf.CARD_SEC))
                shots.append({"start": t, "end": t + lf.CARD_SEC, "image": card, "variant": 0, "move": "push_in"})
                entry_starts.append((f"#{e['rank']} {lf.chapter_label(e['label'])}", t))
                drops.append(t)
                t += lf.CARD_SEC
                continue
            line = os.path.join(lines_dir, f"line_{_key(voice, beat['text'])}.mp3")
            if not os.path.isfile(line):
                mts._spoken_cta(beat["text"], line, voice=voice)
            dur = mts._duration(line)
            job = beat.get("job")
            if beat.get("image"):
                pictures = [_picture(beat["image"], spec.get("style", ""),
                                     os.path.join(pics_dir, f"new_{_key(spec.get('style', ''), beat['image'])}.png"))]
            elif beat.get("scene") is not None and job:
                pictures = lf.scene_pictures(job, int(beat["scene"]))[:2]
            elif beat.get("claims") and job:
                script = scripts.setdefault(job, lf.load_script(job))
                pictures = lf.pick_pictures(job, script, beat["claims"], used,
                                            want=1 if dur <= lf.MAX_SHOT_SEC else 2)
            elif job:
                script = scripts.setdefault(job, lf.load_script(job))
                pictures = lf.any_pictures(job, script, used, want=1 if dur <= lf.MAX_SHOT_SEC else 2)
            else:
                pictures = []
            pictures = pictures or last_pictures[-1:] or []
            if not pictures:
                raise SystemExit(f"no picture for: {beat['text'][:60]} (give it an image or scene)")
            shots += lf.split_shots(t, t + dur + lf.BEAT_GAP_SEC, pictures)
            cues.append({"start": round(t, 3), "end": round(t + dur, 3), "text": beat["text"]})
            audio_parts.append(("file", os.path.abspath(line)))
            audio_parts.append(("silence", lf.BEAT_GAP_SEC))
            if beat.get("claims") and job:
                script = scripts.setdefault(job, lf.load_script(job))
                claims = {c["claim_id"]: c for c in script["_research_dossier"]["claims"]}
                for cid in beat["claims"]:
                    url = claims[cid].get("source_url")
                    if url and url not in sources:
                        sources.append(url)
            last_pictures = pictures
            t += dur + lf.BEAT_GAP_SEC
        total = round(t, 3)

        clips = [_shot_clip(s, i, tmp) for i, s in enumerate(shots)]
        with open(os.path.join(tmp, "clips.txt"), "w") as handle:
            handle.write("".join(f"file '{os.path.abspath(c)}'\n" for c in clips))
        base = os.path.join(tmp, "base.mp4")
        mts._run([mts._ffmpeg_bin(), "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i",
                  os.path.join(tmp, "clips.txt"), "-c", "copy", base])
        voice_track = os.path.join(tmp, "voice.wav")
        _join_audio(audio_parts, voice_track)
        film = os.path.join(out, "explainer.mp4")
        mix_cmd = [mts._ffmpeg_bin(), "-v", "error", "-y", "-i", base, "-i", voice_track]
        if not spec.get("no_music"):
            import illustrated_score
            bed, _meta = illustrated_score.render_score(out, spec["slug"], spec.get("engine") or "removed_keystone",
                                                        total)
            graph = illustrated_score.music_mix_filter(total, drops).replace("[0:a]", "[1:a]").replace("[1:a]atrim", "[2:a]atrim")
            mix_cmd += ["-i", bed, "-filter_complex", graph, "-map", "0:v", "-map", "[mix]"]
        else:
            mix_cmd += ["-map", "0:v", "-map", "1:a"]
        mix_cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", film]
        mts._run(mix_cmd)

    with open(os.path.join(out, "captions.srt"), "w", encoding="utf-8") as handle:
        handle.write(lf.srt(cues))
    chapter_lines = lf.chapters(entry_starts)
    description = "\n".join([spec.get("summary") or spec["question"], "",
                             "Every factual line in this film was checked against quoted passages from its sources.",
                             "", "⏱️ CHAPTERS", *chapter_lines, "", "📚 RESEARCH & SOURCES", *sources])
    with open(os.path.join(out, "description.txt"), "w", encoding="utf-8") as handle:
        handle.write(description + "\n")
    with open(os.path.join(out, "transcript.txt"), "w", encoding="utf-8") as handle:
        handle.write(" ".join(c["text"] for c in cues) + "\n")
    result = {"status": "done", "title": spec["title"], "format": "list_film", "runtime_sec": total,
              "entries": len(spec["entries"]), "shots": len(shots), "pictures": len({s["image"] for s in shots}),
              "longest_shot": round(max(s["end"] - s["start"] for s in shots), 2), "chapters": chapter_lines}
    json.dump(result, open(os.path.join(out, "run_result.json"), "w"), indent=1, ensure_ascii=False)
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("spec")
    ap.add_argument("--out", required=True)
    ap.add_argument("--check-only", action="store_true", help="validate and run the fidelity judge; no media")
    args = ap.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.expanduser("~/ai-video-gen-local"), ".env"))
    load_dotenv(os.path.join(ROOT, ".env"))
    spec = json.load(open(args.spec, encoding="utf-8"))
    os.makedirs(args.out, exist_ok=True)
    json.dump(spec, open(os.path.join(args.out, "spec.json"), "w"), indent=1, ensure_ascii=False)
    errors = lf.validate_spec(spec)
    if errors:
        print("\n".join(errors))
        return 2
    failures = check(spec, args.out)
    if failures:
        for f in failures:
            print(f"UNSUPPORTED {f['where']}: {f['text'][:80]} -- {', '.join(f['unsupported']) or f['reason']}")
        return 3
    print(f"fidelity: passed ({args.out}/fidelity.json)")
    if args.check_only:
        return 0
    print(json.dumps(build(spec, args.out), indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
