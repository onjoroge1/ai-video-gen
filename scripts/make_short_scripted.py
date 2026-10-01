"""A Short with its own script, written from a delivered film's verified claims and pictures.

Not a clip of the film. The film opens on setup by engine contract; a Short is payoff-first:
the reversal in the first line, the fix and its one concrete number, the backfire in two beats,
then the question the film answers. Every factual line cites a claim id from the film's
research ledger, so no new research or fact-check is bought; the pictures are the film's own
accepted images where they survive, or new vertical frames drawn from the same state
descriptions in the same style when they do not.

    python3 scripts/make_short_scripted.py jobs/canetoad01 [--seconds 30] [--voice echo]
                                            [--speed 1.1] [--generate-images]

Writes <job>/short.mp4, <job>/short_package.json (script, claim ids, readiness metrics) and
<job>/short_audio.mp3. Costs: one text call, one TTS pass, one whisper pass, and only with
--generate-images (or when the film's images are gone) a vertical frame per line.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from make_teaser_short import (  # noqa: E402
    FPS, H, SAFE_BOTTOM, W, WHITE, YELLOW, _font, _run, _text_png, _wrap, _duration)
from media_binaries import ffmpeg as _ffmpeg_bin  # noqa: E402

TARGET_SECONDS = 30.0
WORDS_MIN, WORDS_MAX = 66, 88
PICTURE_SECONDS = 1.9          # a fresh picture at least this often
MIN_PICTURE_SECONDS = 1.1

_SCRIPT_SYSTEM = """You write 30-second vertical YouTube Shorts for a documentary channel about interventions that backfired. The Short is a payoff-first teaser for a finished film; it must be TRUE to the film's verified claims and nothing else.

Return ONLY JSON: {"lines": [{"text": "...", "role": "reversal|fix|backfire|question", "claim_ids": ["c01"], "picture": "state:s001:e01"}]}

Hard rules:
- 6 to 9 lines, 68 to 84 words in total. Every line is one spoken sentence of at most 14 words. Plain, concrete, present-tense where possible. Short clauses that read fast aloud: no semicolons, no dashes, no parentheses, at most one comma per line, no lists of more than three items. No throat-clearing ("explained like you are five", "in this video", "let's dive in").
- Line 1 is the REVERSAL in at most 9 words: who did what, and the opposite of what they wanted. It must make a viewer who has never heard of the story stop scrolling.
- Lines 2-3 (role fix): what they were trying to fix and the one most concrete number from the claims.
- Lines 4-7 (role backfire): the backfire in two or three beats, each a different consequence, with numbers only if a claim states them.
- The LAST line (role question) is a question the full film answers, ending with "?", asserting no new fact.
- Every line except the question cites at least one claim id from the ledger; a cited claim must actually state what the line says. Never invent a number, species, place or date.
- Each line names ONE picture: a state id from the available pictures that shows that moment. Prefer different pictures for consecutive lines. If no listed picture fits, write instead a 12-25 word description of one illustrated moment (same world, same style) prefixed "NEW: ". A NEW picture must show the LITERAL subject of its line: the actual animals, plants, crops, places or objects the line names, in the story's real setting and period. Never allegory, metaphor, symbols, instruments, maps, charts, generic figures or portraits; people appear only when the line is about people doing something.
"""


def _load(job: str):
    rr = json.load(open(os.path.join(job, "run_result.json"))) if os.path.isfile(os.path.join(job, "run_result.json")) else {}
    dossier = json.load(open(os.path.join(job, "research_dossier.json")))
    plan = json.load(open(os.path.join(job, "evidence_asset_plan.json")))
    transcript = open(os.path.join(job, "transcript.txt"), encoding="utf-8").read() if os.path.isfile(os.path.join(job, "transcript.txt")) else ""
    state = json.load(open(os.path.join(job, "_state.json")))
    script = state.get("script") or {}
    claims = {}
    for c in dossier.get("claims") or []:
        cid = str(c.get("claim_id") or "").strip()
        if cid and (c.get("quote_verified") or c.get("support_provenance")):
            claims[cid] = str(c.get("claim") or "").strip()
    states = {}
    for sc in plan.get("scenes") or []:
        for st in sc.get("states") or []:
            if st.get("asset_status") not in ("accepted", "reused_exact"):
                continue
            path = st.get("asset_path") or ""
            for cand in (path, path.replace("/images/", "/images_keep/")):
                if cand and os.path.isfile(cand):
                    path = cand
                    break
            else:
                path = ""
            states[st["state_id"]] = {"visual": st.get("visual") or st.get("state_after") or "",
                                      "objects": st.get("required_objects") or [], "path": path,
                                      "scene": sc.get("scene_index")}
    title = rr.get("title") or script.get("title") or os.path.basename(job)
    return title, script.get("hook") or "", transcript, claims, states


def _validate(lines: list[dict], claims: dict, states: dict) -> list[str]:
    errs = []
    if not 6 <= len(lines) <= 9:
        errs.append(f"{len(lines)} lines; need 6-9")
    words = sum(len(str(l.get("text", "")).split()) for l in lines)
    if not WORDS_MIN <= words <= WORDS_MAX:
        errs.append(f"{words} words; need {WORDS_MIN}-{WORDS_MAX}")
    if lines:
        first = str(lines[0].get("text", ""))
        if len(first.split()) > 9:
            errs.append(f"line 1 is {len(first.split())} words; max 9")
        if lines[0].get("role") != "reversal":
            errs.append("line 1 must have role reversal")
        last = str(lines[-1].get("text", "")).strip()
        if not last.endswith("?") or lines[-1].get("role") != "question":
            errs.append("last line must be a question ending with ?")
    for i, l in enumerate(lines, 1):
        text = str(l.get("text", ""))
        if len(text.split()) > 14:
            errs.append(f"line {i} is {len(text.split())} words; max 14")
        if re.search(r"explained like you are five|in this video|let'?s dive", text, re.I):
            errs.append(f"line {i} contains filler")
        if re.search(r"[;—–(]", text) or len(re.findall(r"(?<!\d),|,(?!\d)", text)) > 1:
            errs.append(f"line {i} uses semicolons, dashes, parentheses or more than one comma")
        ids = [str(c) for c in (l.get("claim_ids") or [])]
        if l.get("role") != "question":
            if not ids:
                errs.append(f"line {i} cites no claim")
            for cid in ids:
                if cid not in claims:
                    errs.append(f"line {i} cites unknown claim {cid}")
        pic = str(l.get("picture") or "").strip()
        if not pic:
            errs.append(f"line {i} names no picture")
        elif not pic.startswith("NEW:") and states and pic not in states:
            errs.append(f"line {i} names unknown picture {pic}")
    return errs


def write_script(title: str, hook: str, transcript: str, claims: dict, states: dict,
                 cost_sink: list) -> list[dict]:
    import explainer_pipeline as ep
    ledger = "\n".join(f"{cid}: {text}" for cid, text in list(claims.items())[:60])
    pictures = "\n".join(f"{sid}: {s['visual']} (shows: {', '.join(s['objects'][:3])})"
                         for sid, s in states.items()) or "(none on disk: describe every picture as NEW: ...)"
    user = (f'FILM TITLE: "{title}"\nFILM HOOK: {hook}\n\nTRANSCRIPT (for tone and order only; cite claims, not this):\n'
            f'{transcript[:3500]}\n\nCLAIM LEDGER (the only facts you may state):\n{ledger}\n\n'
            f'AVAILABLE PICTURES:\n{pictures}\n\nWrite the Short.')
    errors: list[str] = []
    lines: list[dict] = []
    for attempt in range(3):
        prompt = user + (f"\n\nYOUR PREVIOUS DRAFT FAILED THESE CHECKS; fix every one:\n- " + "\n- ".join(errors)
                         + f"\n\nPrevious draft: {json.dumps(lines)}" if errors else "")
        response = ep._claude().messages.create(model=ep.ANTHROPIC_MODEL, max_tokens=1600,
                                                system=_SCRIPT_SYSTEM,
                                                messages=[{"role": "user", "content": prompt}])
        cost_sink.append(ep._msg_cost(response.usage))
        parsed, _ = ep._parse_script_json(response.content[0].text)
        lines = [l for l in ((parsed or {}).get("lines") or []) if isinstance(l, dict)]
        errors = _validate(lines, claims, states)
        if not errors:
            return lines
        print(f"  script draft {attempt + 1} failed: {'; '.join(errors)}")
    raise SystemExit("the Short script did not pass its checks after 3 drafts: " + "; ".join(errors))


def _narrate(text: str, out_path: str, voice: str, speed: float) -> float:
    import explainer_pipeline as ep
    resp = ep._openai().audio.speech.create(model=ep.TTS_MODEL, voice=voice, input=text,
                                            speed=speed, response_format="mp3")
    with open(out_path, "wb") as handle:
        handle.write(resp.content)
    return _duration(out_path)


def _line_spans(lines: list[dict], words: list) -> list[tuple[float, float]]:
    """(start, end) per line from whisper word timings, matched by running word count."""
    counts = [len(str(l["text"]).split()) for l in lines]
    spans, cursor = [], 0
    for n in counts:
        chunk = words[cursor:cursor + n]
        cursor += n
        if chunk:
            spans.append((float(chunk[0][1]), float(chunk[-1][2])))
        else:
            spans.append((spans[-1][1] if spans else 0.0, spans[-1][1] if spans else 0.0))
    # Close gaps: each line owns the audio until the next line starts.
    out = []
    for i, (s, e) in enumerate(spans):
        nxt = spans[i + 1][0] if i + 1 < len(spans) else e
        out.append((s if i else 0.0, max(e, nxt)))
    return out


def _picture_for(line: dict, states: dict, job: str, index: int, style_suffix: str,
                 cost_sink: list, generate: bool) -> str:
    import explainer_pipeline as ep
    pic = str(line.get("picture") or "")
    if not pic.startswith("NEW:") and states.get(pic, {}).get("path") and not generate:
        return states[pic]["path"]
    desc = pic[4:].strip() if pic.startswith("NEW:") else (states.get(pic) or {}).get("visual") or str(line["text"])
    objects = (states.get(pic) or {}).get("objects") or []
    out_dir = os.path.join(job, "short_images")
    os.makedirs(out_dir, exist_ok=True)
    import hashlib
    # Cache by WHAT is drawn, not by line position: a redraft moves lines around, and a picture
    # cached under line_03 for one script is the wrong picture for the next script's line 3.
    key = hashlib.sha1((desc + "|" + "|".join(objects)).encode()).hexdigest()[:10]
    out = os.path.join(out_dir, f"pic_{key}.jpg")
    if os.path.isfile(out):
        return out
    prompt = (f"Vertical 9:16 illustrated frame for a phone screen. {desc}. "
              + (f"It must clearly show: {', '.join(objects)}. " if objects else "")
              + "Subject centred in the middle third of the frame, large and readable at phone size."
              + style_suffix)
    ep.generate_image(prompt, out, cost_sink=cost_sink, size="1024x1536")
    return out


def _check_picture(path: str, line: dict, states: dict, cost_sink: list) -> dict:
    """A light vision check that the drawn frame shows what the line says; cheap, not a gate."""
    import base64
    import explainer_pipeline as ep
    pic = str(line.get("picture") or "")
    wanted = (states.get(pic) or {}).get("objects") or [pic[4:].strip() if pic.startswith("NEW:") else line["text"]]
    data = base64.b64encode(open(path, "rb").read()).decode()
    try:
        r = ep._claude().messages.create(model=ep.ANTHROPIC_MODEL, max_tokens=120,
            system='Answer ONLY JSON: {"ok": true|false, "reason": "..."}',
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}},
                {"type": "text", "text": f"The narration for this frame is: \"{line['text']}\". Does the image literally depict that line's subject (the actual animals, places or objects it names, not a symbol or allegory), and clearly show: {'; '.join(map(str, wanted))}? No text or labels should be present. Answer ok=false if the picture is symbolic, generic, or about something else."}]}])
        cost_sink.append(ep._msg_cost(r.usage))
        parsed, _ = ep._parse_script_json(r.content[0].text)
        return parsed if isinstance(parsed, dict) else {"ok": None, "reason": "unparsed"}
    except Exception as exc:
        return {"ok": None, "reason": f"{type(exc).__name__}"}


def _slots(spans, pictures, extra_pool):
    """Picture slots: each line's picture, split so no picture holds longer than PICTURE_SECONDS;
    the second half of a long line borrows the next unused extra picture when one exists."""
    slots = []
    pool = list(extra_pool)
    for (s, e), pic in zip(spans, pictures):
        d = e - s
        n = max(1, int(round(d / PICTURE_SECONDS + 0.49)))
        step = d / n
        for k in range(n):
            use = pic
            if k % 2 == 1 and pool:
                use = pool.pop(0)
            slots.append((s + k * step, s + (k + 1) * step, use, k))
    return slots


def _render_slots(slots, out_path, tmp):
    parts = []
    moves = ("push", "pan_l", "pan_r", "pull")
    for i, (s, e, path, k) in enumerate(slots):
        d = max(MIN_PICTURE_SECONDS * 0.8, e - s)
        n = max(1, int(round(d * FPS)))
        with Image.open(path) as im:
            iw, ih = im.size
        cw = min(iw, int(ih * 9 / 16))
        move = moves[i % len(moves)]
        z = f"min(1+0.14*on/{n},1.14)" if move in ("push",) else (f"max(1.14-0.14*on/{n},1.0)" if move == "pull" else "1.08")
        x = "iw/2-(iw/zoom/2)"
        if move == "pan_l":
            x = f"(iw-iw/zoom)*(1-on/{n})"
        elif move == "pan_r":
            x = f"(iw-iw/zoom)*on/{n}"
        vf = (f"crop={cw}:{ih}:(iw-{cw})/2:0,scale=2160:3840,"
              f"zoompan=z='{z}':x='{x}':y='ih/2-(ih/zoom/2)':d={n}:s={W}x{H}:fps={FPS},format=yuv420p")
        clip = os.path.join(tmp, f"slot_{i:03d}.mp4")
        _run([_ffmpeg_bin(), "-v", "error", "-y", "-loop", "1", "-i", path, "-t", f"{d:.3f}",
              "-vf", vf, "-r", str(FPS), "-an", clip])
        parts.append(clip)
    with open(os.path.join(tmp, "concat.txt"), "w") as handle:
        handle.write("".join(f"file '{p}'\n" for p in parts))
    _run([_ffmpeg_bin(), "-v", "error", "-y", "-f", "concat", "-safe", "0",
          "-i", os.path.join(tmp, "concat.txt"), "-c", "copy", out_path])


def _caption_chunks(words: list, until: float, size: int = 3):
    chunks = []
    for i in range(0, len(words), size):
        group = words[i:i + size]
        start, end = float(group[0][1]), float(group[-1][2])
        if i + size < len(words):
            end = float(words[i + size][1])          # hold until the next chunk begins
        chunks.append((start, min(end, until), [w[0] for w in group]))
    return chunks


def _emphasis(word: str) -> tuple:
    bare = word.strip(".,;:!?")
    return YELLOW if (re.search(r"\d", bare) or (bare[:1].isupper() and len(bare) > 3)) else WHITE


def readiness(lines, spans, slots, words_total, until, whisper_words) -> dict:
    first_words = len(str(lines[0]["text"]).split())
    pictures = len({p for _, _, p, _ in slots})
    checks = {
        "words_before_twist_le_9": (first_words, first_words <= 9),
        # Measured on the first scripted Short (cane toads, echo at 1.3x, eight plain sentences):
        # 66 words in 23.0 s is 2.86 w/s, and an 8-word first line lands at 3.3 s because the
        # voice pauses at every full stop. Those are the pace of a narrator reading punchy copy,
        # not a documentary drawl, so the bands sit where a measured natural read can reach.
        "seconds_to_twist_le_3_5": (round(spans[0][1], 2), spans[0][1] <= 3.5),
        "new_picture_interval_le_2s": (round(until / max(1, len(slots)), 2), until / max(1, len(slots)) <= 2.0),
        "words_per_second_2_7_to_3_9": (round(words_total / until, 2), 2.7 <= words_total / until <= 3.9),
        "length_22_to_36s": (round(until, 1), 22 <= until <= 36),
        "closing_question": (str(lines[-1]["text"]).strip().endswith("?"), str(lines[-1]["text"]).strip().endswith("?")),
        "caption_word_coverage_ge_0_9": (round(len(whisper_words) / max(1, words_total), 2), len(whisper_words) / max(1, words_total) >= 0.9),
        "distinct_pictures_ge_8": (pictures, pictures >= 8),
    }
    return {"checks": {k: {"value": v, "pass": ok} for k, (v, ok) in checks.items()},
            "passed": all(ok for _, ok in checks.values()),
            "fails": [k for k, (_, ok) in checks.items() if not ok]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("job")
    ap.add_argument("--seconds", type=float, default=TARGET_SECONDS)
    ap.add_argument("--voice", default="echo")
    ap.add_argument("--speed", type=float, default=1.3)
    ap.add_argument("--generate-images", action="store_true")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    job = os.path.abspath(args.job)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    import explainer_pipeline as ep
    import illustrated_story
    costs: list[float] = []
    title, hook, transcript, claims, states = _load(job)
    have_images = any(s["path"] for s in states.values())
    generate = args.generate_images or not have_images
    print(f"{title} | {len(claims)} verified claims | {sum(1 for s in states.values() if s['path'])} pictures on disk"
          + (" | drawing new vertical frames" if generate else ""))

    lines = write_script(title, hook, transcript, claims, states, costs)
    text = " ".join(str(l["text"]).strip() for l in lines)
    print("script:", text)

    audio = os.path.join(job, "short_audio.mp3")
    until = _narrate(text, audio, args.voice, args.speed)
    words = ep.transcribe_words(audio)
    spans = _line_spans(lines, words) if words else []
    if not spans:
        raise SystemExit("whisper returned no word timings; cannot sync captions")
    spans[-1] = (spans[-1][0], until)

    style = illustrated_story.visual_style_suffix(" Vertical portrait composition, subject in the middle third.")
    pictures, checks = [], []
    for i, line in enumerate(lines):
        path = _picture_for(line, states, job, i, style, costs, generate)
        verdict = _check_picture(path, line, states, costs) if generate else {"ok": True, "reason": "film asset, already verified"}
        if verdict.get("ok") is False and generate:
            print(f"  redrawing picture {i + 1}: {verdict.get('reason', '')[:100]}")
            os.remove(path)
            path = _picture_for(line, states, job, i, style, costs, generate)
            verdict = _check_picture(path, line, states, costs)
        pictures.append(path)
        checks.append(verdict)
    # Extra pictures for long lines: unused film images, else nothing.
    used = set(pictures)
    extra = [s["path"] for s in states.values() if s["path"] and s["path"] not in used]
    slots = _slots(spans, pictures, extra)

    out_path = args.out or os.path.join(job, "short.mp4")
    with tempfile.TemporaryDirectory(prefix="short_") as tmp:
        base = os.path.join(tmp, "base.mp4")
        _render_slots(slots, base, tmp)
        overlays = []
        head_png = os.path.join(tmp, "head.png")
        headline = re.sub(r"\s+That\s.*$", "", title, flags=re.I).upper()
        probe = ImageDraw.Draw(Image.new("RGBA", (W, H)))
        size = 84
        for cand in (92, 84, 76, 70):
            if len(_wrap(probe, headline, _font(cand), W - 140)) <= 2:
                size = cand
                break
        head_lines = [[(w, YELLOW if li == 0 else WHITE) for w in line.split()]
                      for li, line in enumerate(_wrap(probe, headline, _font(size), W - 140)[:2])]
        _text_png(head_png, head_lines, size=size, y=140, stroke=10)
        overlays.append((head_png, 0.0, until))
        cap_y = H - SAFE_BOTTOM - 300
        end_at = max(0.0, until - 2.2)
        for i, (s, e, group) in enumerate(_caption_chunks(words, until)):
            if s >= end_at:
                break
            png = os.path.join(tmp, f"cap_{i:03d}.png")
            # Shrink until the chunk fits inside the frame with margins; never let a pill overflow.
            size = 84
            while size > 52 and probe.textlength(" ".join(w.upper() for w in group) + " ", font=_font(size)) > W - 150:
                size -= 6
            _text_png(png, [[(w.upper(), _emphasis(w)) for w in group]], size=size, y=cap_y, stroke=9, pill=True)
            overlays.append((png, s, min(e, end_at)))
        end_png = os.path.join(tmp, "end.png")
        _text_png(end_png, [[("WATCH", YELLOW), ("THE", YELLOW), ("FULL", YELLOW), ("STORY", YELLOW)]],
                  size=88, y=cap_y - 20, stroke=10, pill=True)
        overlays.append((end_png, end_at, until))

        music = ""
        mdir = os.path.join(job, "music")
        if os.path.isdir(mdir):
            wavs = [os.path.join(mdir, f) for f in os.listdir(mdir) if f.endswith(".wav")]
            music = wavs[0] if wavs else ""
        cmd = [_ffmpeg_bin(), "-v", "error", "-y", "-i", base, "-i", audio]
        if music:
            cmd += ["-i", music]
        for png, _, _ in overlays:
            cmd += ["-i", png]
        first_png = 3 if music else 2
        chain, prev = [], "[0:v]"
        for k, (_, s, e) in enumerate(overlays):
            nxt = f"[v{k}]"
            chain.append(f"{prev}[{first_png + k}:v]overlay=0:0:enable='between(t,{s:.3f},{e:.3f})'{nxt}")
            prev = nxt
        if music:
            chain.append(f"[2:a]atrim=0:{until:.3f},volume=0.16,afade=t=out:st={max(0, until - 1.2):.3f}:d=1.2[m];"
                         f"[1:a][m]amix=inputs=2:duration=first:dropout_transition=0,loudnorm=I=-15:TP=-1.5:LRA=9[a]")
            amap = "[a]"
        else:
            chain.append(f"[1:a]loudnorm=I=-15:TP=-1.5:LRA=9[a]")
            amap = "[a]"
        cmd += ["-filter_complex", ";".join(chain), "-map", prev, "-map", amap,
                "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                "-r", str(FPS), "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
                "-t", f"{until:.3f}", out_path]
        _run(cmd)

    words_total = len(text.split())
    gate = readiness(lines, spans, slots, words_total, until, words)
    package = {
        "short": out_path, "seconds": round(until, 2), "title": (re.sub(r"\s+That\s.*$", "", title, flags=re.I) + " #Shorts")[:100],
        "lines": lines, "words": words_total, "pictures": pictures, "picture_checks": checks,
        "readiness": gate, "cost_usd": round(sum(costs), 4), "voice": args.voice, "speed": args.speed,
        "source_title": title, "mode": "scripted" + ("+generated-images" if generate else ""),
    }
    with open(os.path.join(job, "short_package.json"), "w", encoding="utf-8") as handle:
        json.dump(package, handle, indent=1, ensure_ascii=False)
    print(json.dumps({"short": out_path, "seconds": package["seconds"], "words": words_total,
                      "readiness_passed": gate["passed"], "fails": gate["fails"],
                      "cost_usd": package["cost_usd"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
