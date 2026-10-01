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
WORDS_MIN, WORDS_MAX = 66, 84
PICTURE_SECONDS = 1.9          # a fresh picture at least this often
MIN_PICTURE_SECONDS = 1.1

_SCRIPT_SYSTEM = """You write 25-second vertical YouTube Shorts for a documentary channel about interventions that backfired. A Short tells ONE complete story: one question (what went wrong), one mechanism, one consequence, one payoff. It is not a tour of the research and not a trailer. It must be TRUE to the film's verified claims and nothing else.

Return ONLY JSON:
{"openings": ["...", "...", "..."],
 "lines": [{"text": "...", "role": "hook|setup|mechanism|consequence|payoff", "claim_ids": ["c01"],
            "visual": {"shot": "close-up|medium|wide", "subject": "...", "action": "..."},
            "picture": "state:s001:e01 or NEW: ..."}]}

Story shape (6 to 8 lines, 66 to 84 words; under 66 the Short runs short of 22 seconds):
- openings: THREE candidate first lines, each at most 9 words, each a direct contradiction the viewer can SEE in one picture: the thing itself doing the surprising thing ("This toad can kill anything that eats it."). Name the actual animal or plant (toad, wolf, vine), never an epithet ("this beetle killer", "this pest control"). Not a summary of the premise, no place names, no dates, no numbers. Then write the Short using the strongest one as line 1 (role hook).
- line 2 (role hook): the human decision that makes line 1 absurd, at most 8 words ("Australia brought it in on purpose.").
- one line (role setup): what they were trying to fix, in plain words. No agency names, no town names, no dates unless a date IS the story.
- one line (role mechanism): why it failed, conversational ("But the crop rescue failed."), never research prose ("did not increase significantly"). Follow the EDITORIAL CONSTRAINTS below exactly; never present one hypothesised reason as the whole explanation if the brief says it is not.
- two or three lines (role consequence): what happened instead, each a different concrete consequence.
- the LAST line (role payoff): finishes the story in one plain declarative sentence that returns to the subject of line 1, so the last picture can return to the opening composition. It is not a question and asserts nothing new.

Language: every line is one spoken sentence of at most 14 words, present tense where possible, no semicolons, dashes or parentheses, at most one comma, no lists of more than three. No throat-clearing. Spoken register throughout.

Numbers: at most ONE number in the whole Short, years included, and only if a cited claim states it exactly and the same sentence says what it counts. Prefer none. A number the viewer cannot place is noise.

Facts: every line except the payoff cites claim ids from the ledger that actually state what the line says. Never invent a number, species, place, date or cause.

Visuals, written WITH the words: every line's visual names the shot size, the subject and ONE action that a single still can show (a predator with a toad in its jaws, a quoll on bare gorge rock, a toad under tall cane); never a change over time ("declining", "disappearing", "spreading", "fading") and never a silhouette or outline, and the picture must demonstrate that exact sentence and never contradict it (never show the toad reaching a beetle under a line that says the beetles were out of reach). Vary shot size: never the same size three lines running; use at least one close-up and one wide. People appear only when the line is about people acting. Line 1 and the payoff share the same composition. Pictures: a state id from the available pictures when one truly fits, otherwise "NEW: " plus a 12-25 word description of one illustrated moment in the film's real setting and period, literal, never symbolic: a named animal doing a named thing in a named place, filling the frame. Never "silhouettes", "outlines", "montage", "across the continent" or any wording that cannot be one solid drawing.
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
    brief = open(os.path.join(job, "direction.txt"), encoding="utf-8").read() if os.path.isfile(os.path.join(job, "direction.txt")) else ""
    cautions = [m.strip() for m in re.findall(r"(?:Do not say|Never say|Separate documented|Scope impacts|No unsupported|Reconcile)[^.]*\.", brief)]
    pack = plan.get("continuity_pack") or {}
    location = str((pack.get("first_act_location") or {}).get("label") or "")
    years = sorted(set(re.findall(r"\b(1[6-9]\d\d|20\d\d)\b", transcript)))
    era = f"{years[0]}s" if years else ""
    setting = ", ".join(x for x in (location, era) if x)
    return title, script.get("hook") or "", transcript, claims, states, setting, cautions


SHOTS = ("close-up", "medium", "wide")


def _numbers(text: str) -> set:
    return {t.replace(",", "") for t in re.findall(r"\$?\d[\d,]*(?:\.\d+)?%?", text)}


def _validate(lines: list[dict], claims: dict, states: dict, openings: list | None = None) -> list[str]:
    errs = []
    if not 6 <= len(lines) <= 8:
        errs.append(f"{len(lines)} lines; need 6-8")
    words = sum(len(str(l.get("text", "")).split()) for l in lines)
    if not WORDS_MIN <= words <= WORDS_MAX:
        errs.append(f"{words} words; need {WORDS_MIN}-{WORDS_MAX}")
    if openings is not None and len([o for o in openings if str(o).strip()]) != 3:
        errs.append("propose exactly 3 openings")
    if lines:
        first = str(lines[0].get("text", "")).strip()
        if len(first.split()) > 9:
            errs.append(f"line 1 is {len(first.split())} words; max 9")
        if lines[0].get("role") != "hook":
            errs.append("line 1 must have role hook")
        if openings and first not in [str(o).strip() for o in openings]:
            errs.append("line 1 must be one of the proposed openings, verbatim")
        if _numbers(first) or re.search(r"\b(1[6-9]\d\d|20\d\d)\b", first):
            errs.append("line 1 must contain no number or date")
        if len(lines) > 1 and lines[1].get("role") == "hook" and len(str(lines[1].get("text", "")).split()) > 8:
            errs.append("line 2 is over 8 words")
        last = str(lines[-1].get("text", "")).strip()
        if lines[-1].get("role") != "payoff" or last.endswith("?") or not last.endswith((".", "!")):
            errs.append("last line must be role payoff: a complete declarative sentence, not a question")
    roles = [str(l.get("role")) for l in lines]
    for needed in ("setup", "mechanism", "consequence"):
        if needed not in roles:
            errs.append(f"no line has role {needed}")
    all_numbers = set()
    shots = []
    for i, l in enumerate(lines, 1):
        text = str(l.get("text", ""))
        if len(text.split()) > 14:
            errs.append(f"line {i} is {len(text.split())} words; max 14")
        if re.search(r"explained like you are five|in this video|let'?s dive|did not increase significantly", text, re.I):
            errs.append(f"line {i} contains filler or research prose")
        if re.search(r"[;—–(]", text) or len(re.findall(r"(?<!\d),|,(?!\d)", text)) > 1:
            errs.append(f"line {i} uses semicolons, dashes, parentheses or more than one comma")
        ids = [str(c) for c in (l.get("claim_ids") or [])]
        if l.get("role") != "payoff":
            if not ids:
                errs.append(f"line {i} cites no claim")
            for cid in ids:
                if cid not in claims:
                    errs.append(f"line {i} cites unknown claim {cid}")
        nums = _numbers(text)
        all_numbers |= nums
        for n in nums:
            if not any(n in _numbers(claims.get(cid, "")) for cid in ids):
                errs.append(f"line {i} states the number {n} that none of its cited claims states")
        visual = l.get("visual") if isinstance(l.get("visual"), dict) else {}
        shot = str(visual.get("shot", "")).strip().lower()
        if shot not in SHOTS or not str(visual.get("subject", "")).strip() or not str(visual.get("action", "")).strip():
            errs.append(f"line {i} needs visual.shot (close-up|medium|wide), visual.subject and visual.action")
        shots.append(shot)
        pic = str(l.get("picture") or "").strip()
        if not pic:
            errs.append(f"line {i} names no picture")
        elif not pic.startswith("NEW:") and states and pic not in states:
            errs.append(f"line {i} names unknown picture {pic}")
    if len(all_numbers) > 1:
        errs.append(f"{len(all_numbers)} different numbers ({', '.join(sorted(all_numbers))}); at most one")
    if shots and ("close-up" not in shots or "wide" not in shots):
        errs.append("use at least one close-up and one wide shot")
    for i in range(2, len(shots)):
        if shots[i] == shots[i - 1] == shots[i - 2] and shots[i]:
            errs.append(f"lines {i - 1}-{i + 1} are all {shots[i]} shots; vary the size")
            break
    return errs


def write_script(title: str, hook: str, transcript: str, claims: dict, states: dict,
                 cost_sink: list, cautions: list[str] | None = None) -> tuple[list[dict], list[str]]:
    import explainer_pipeline as ep
    ledger = "\n".join(f"{cid}: {text}" for cid, text in list(claims.items())[:60])
    pictures = "\n".join(f"{sid}: {s['visual']} (shows: {', '.join(s['objects'][:3])})"
                         for sid, s in states.items()) or "(none on disk: describe every picture as NEW: ...)"
    constraints = "\n".join(f"- {c}" for c in (cautions or [])) or "- (none)"
    user = (f'FILM TITLE: "{title}"\nFILM HOOK: {hook}\n\nEDITORIAL CONSTRAINTS from the film brief (binding):\n{constraints}\n\n'
            f'TRANSCRIPT (for tone and order only; cite claims, not this):\n'
            f'{transcript[:3500]}\n\nCLAIM LEDGER (the only facts you may state):\n{ledger}\n\n'
            f'AVAILABLE PICTURES:\n{pictures}\n\nWrite the Short.')
    errors: list[str] = []
    lines: list[dict] = []
    openings: list[str] = []
    for attempt in range(4):
        prompt = user + (f"\n\nYOUR PREVIOUS DRAFT FAILED THESE CHECKS; fix every one:\n- " + "\n- ".join(errors)
                         + f"\n\nPrevious draft: {json.dumps(lines)}" if errors else "")
        response = ep._claude().messages.create(model=ep.ANTHROPIC_MODEL, max_tokens=1600,
                                                system=_SCRIPT_SYSTEM,
                                                messages=[{"role": "user", "content": prompt}])
        cost_sink.append(ep._msg_cost(response.usage))
        parsed, _ = ep._parse_script_json(response.content[0].text)
        lines = [l for l in ((parsed or {}).get("lines") or []) if isinstance(l, dict)]
        openings = [str(o) for o in ((parsed or {}).get("openings") or [])]
        errors = _validate(lines, claims, states, openings)
        if not errors:
            return lines, openings
        print(f"  script draft {attempt + 1} failed: {'; '.join(errors)}")
    raise SystemExit("the Short script did not pass its checks after 4 drafts: " + "; ".join(errors))


def _narrate(text: str, out_path: str, voice: str, speed: float) -> float:
    import explainer_pipeline as ep
    resp = ep._openai().audio.speech.create(model=ep.TTS_MODEL, voice=voice, input=text,
                                            speed=speed, response_format="mp3")
    with open(out_path, "wb") as handle:
        handle.write(resp.content)
    return _duration(out_path)


def align_words(script_text: str, whisper: list) -> list:
    """Give every SCRIPT word a (start, end) from whisper's words, by sequence alignment.

    Whisper does not return the script verbatim: on the second cane toad build it merged
    "sugar cane" into "sugarcane" and dropped an initial "The", 66 words for 68, and chunking
    by running count then drifted across sentence ends ("swallow it Australia"). Aligning on
    normalised tokens with difflib pins each script word to its spoken moment; a script word
    with no match takes the midpoint of its neighbours. Captions then show the script's own
    words with whisper's timing.
    """
    import difflib
    norm = lambda w: re.sub(r"[^a-z0-9]", "", w.lower())
    sw = script_text.split()
    a = [norm(w) for w in sw]
    b = [norm(w[0]) for w in whisper]
    timing: list = [None] * len(sw)
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                timing[i1 + k] = (float(whisper[j1 + k][1]), float(whisper[j1 + k][2]))
        elif tag == "replace" and (i2 - i1) and (j2 - j1):
            # e.g. "sugar cane" <-> "sugarcane": share the replaced whisper span across the
            # replaced script words in proportion.
            s0, e0 = float(whisper[j1][1]), float(whisper[j2 - 1][2])
            n = i2 - i1
            for k in range(n):
                timing[i1 + k] = (s0 + (e0 - s0) * k / n, s0 + (e0 - s0) * (k + 1) / n)
    # Fill the rest from neighbours.
    for i in range(len(sw)):
        if timing[i] is None:
            prev_end = next((timing[j][1] for j in range(i - 1, -1, -1) if timing[j]), 0.0)
            next_start = next((timing[j][0] for j in range(i + 1, len(sw)) if timing[j]), prev_end + 0.3)
            timing[i] = (prev_end, max(prev_end + 0.05, next_start))
    matched = sum(1 for t in timing if t) and sum(
        1 for tag, i1, i2, _, _ in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
        if tag == "equal" for _ in range(i2 - i1))
    return [(sw[i], timing[i][0], timing[i][1]) for i in range(len(sw))], matched / max(1, len(sw))


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
                 cost_sink: list, generate: bool, setting: str = "", feedback: str = "") -> str:
    import explainer_pipeline as ep
    pic = str(line.get("picture") or "")
    if not pic.startswith("NEW:") and states.get(pic, {}).get("path") and not generate:
        return states[pic]["path"]
    desc = pic[4:].strip() if pic.startswith("NEW:") else (states.get(pic) or {}).get("visual") or str(line["text"])
    objects = (states.get(pic) or {}).get("objects") or []
    visual = line.get("visual") if isinstance(line.get("visual"), dict) else {}
    if visual:
        desc = (f"{visual.get('shot', 'medium')} shot of {visual.get('subject', '')}: {visual.get('action', '')}. "
                f"{desc}")
    out_dir = os.path.join(job, "short_images")
    os.makedirs(out_dir, exist_ok=True)
    import hashlib
    # Cache by WHAT is drawn, not by line position: a redraft moves lines around, and a picture
    # cached under line_03 for one script is the wrong picture for the next script's line 3.
    key = hashlib.sha1((desc + "|" + "|".join(objects) + "|" + setting + "|" + feedback).encode()).hexdigest()[:10]
    out = os.path.join(out_dir, f"pic_{key}.jpg")
    if os.path.isfile(out):
        return out
    # Every new frame is pinned to the film's place and period. Without this the model drew
    # "toads entering Gordonvale" as an ancient city gate with robed crowds (cane toads, 2026-10-01).
    prompt = (f"Vertical 9:16 illustrated frame for a phone screen. {desc}. The named subject is the "
              f"dominant element, large and in focus, never a faint outline or background figure. "
              + (f"Setting: {setting}; the clothing, buildings, tools and landscape must belong to "
                 f"that real place and period, nothing ancient, biblical, fantasy or symbolic. " if setting else "")
              + (f"It must clearly show: {', '.join(objects)}. " if objects else "")
              + "Subject centred in the middle third of the frame, large and readable at phone size. "
              + "No silhouettes, outlines, ghosted figures, montages, maps or charts: real, solid, "
                "fully drawn animals and objects."
              + (f" A PREVIOUS ATTEMPT WAS REJECTED because: {feedback}. Fix exactly that." if feedback else "")
              + style_suffix)
    ep.generate_image(prompt, out, cost_sink=cost_sink, size="1024x1536")
    return out


def _check_picture(path: str, line: dict, states: dict, cost_sink: list, setting: str = "") -> dict:
    """A light vision check that the drawn frame shows what the line says; cheap, not a gate."""
    import base64
    import explainer_pipeline as ep
    pic = str(line.get("picture") or "")
    visual = line.get("visual") if isinstance(line.get("visual"), dict) else {}
    # Judge the VISUAL BEAT the line asked for, not the whole sentence. "Large predators
    # swallowed toads, and some declined dramatically" has a drawable half and an undrawable
    # half; a frame of a predator swallowing a toad was being rejected for not showing the
    # decline (cane toads, 2026-10-01, two redraws each on two lines).
    if visual.get("subject"):
        wanted = [f"{visual.get('shot', 'medium')} shot: {visual['subject']} — {visual.get('action', '')}"]
    else:
        wanted = (states.get(pic) or {}).get("objects") or [pic[4:].strip() if pic.startswith("NEW:") else line["text"]]
    data = base64.b64encode(open(path, "rb").read()).decode()
    try:
        r = ep._claude().messages.create(model=ep.ANTHROPIC_MODEL, max_tokens=120,
            system='Answer ONLY JSON: {"ok": true|false, "reason": "..."}',
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}},
                {"type": "text", "text": f"This frame was commissioned to show: {'; '.join(map(str, wanted))}. The narration spoken over it is: \"{line['text']}\". Judge the commissioned beat, not the whole sentence: does the image clearly show that subject doing that action as the DOMINANT element of the frame, large, solid and in focus (not a faint outline, silhouette, background figure or small detail while a farm, workers or a landscape fill the picture), literal rather than symbolic, with no text or labels? Separately, does anything in the image CONTRADICT the narration (show the opposite of what the sentence says)? Answer ok=true only if the beat is shown and nothing contradicts the narration; a still cannot show a change over time, so do not reject it for failing to show a decline, a spread or a disappearance." + (f" The setting must read as {setting}: answer ok=false if the clothing, architecture or landscape belong to another era or region." if setting else "")}]}])
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


def _caption_chunks(words: list, until: float, lines: list[dict] | None = None, size: int = 3):
    """Caption chunks of 2-4 words that never cross a sentence boundary.

    The first cut ("FOR BEETLES BUT", "AND DIED SOME") chunked the whisper stream every three
    words regardless of where sentences ended, so a chunk read as a phrase that was never said.
    Chunks are formed inside each scripted line; a trailing single word joins the chunk before it.
    """
    counts = [len(str(l["text"]).split()) for l in (lines or [])] or [len(words)]
    chunks, cursor = [], 0
    for n in counts:
        line_words = words[cursor:cursor + n]
        cursor += n
        groups = [line_words[i:i + size] for i in range(0, len(line_words), size)]
        if len(groups) > 1 and len(groups[-1]) == 1:
            groups[-2] = groups[-2] + groups[-1]
            groups.pop()
        for g in groups:
            if g:
                chunks.append([w for w in g])
    out = []
    for i, group in enumerate(chunks):
        start = float(group[0][1])
        # The last caption stays up through the audio tail; a payoff that vanishes before the
        # sound ends reads as a cut-off.
        end = float(chunks[i + 1][0][1]) if i + 1 < len(chunks) else until
        out.append((start, min(end, until), [w[0] for w in group]))
    return out


def _emphasis(word: str) -> tuple:
    bare = word.strip(".,;:!?")
    return YELLOW if (re.search(r"\d", bare) or (bare[:1].isupper() and len(bare) > 3)) else WHITE


def _headline_from(title: str) -> str:
    """The on-screen headline carries no number the Short does not explain: "The 101-Cane-Toad
    Mistake" reads THE CANE TOAD MISTAKE. The film's title keeps its number; the thumbnail
    grammar is FATAL ERROR either way."""
    head = re.sub(r"\s+That\s.*$", "", title, flags=re.I)
    head = re.sub(r"\$?\d[\d,.]*[kKmMbB]?[-\s]*", "", head)
    return re.sub(r"\s+", " ", head.replace("-", " ")).strip().upper()


def audit_export(lines: list[dict], chunks: list, until: float, claims: dict) -> dict:
    """Checks on what was actually rendered: caption chunks never straddle a sentence, the payoff
    caption is on screen to the end, and no number reaches the screen unless a cited claim states
    it. An approved script alone would not catch a chunk like "THAN 80 HOW"."""
    norm = lambda t: re.sub(r"[^a-z0-9%$ ]", "", t.lower())
    line_words = [norm(str(l["text"])).split() for l in lines]
    straddle = []
    cursor, li = 0, 0
    for _, _, group in chunks:
        g = [norm(w) for w in group]
        while li < len(line_words) and cursor >= len(line_words[li]):
            li += 1; cursor = 0
        if li < len(line_words) and line_words[li][cursor:cursor + len(g)] == g:
            cursor += len(g)
        else:
            straddle.append(" ".join(group))
            cursor += len(g)
    last_shown_to_end = bool(chunks) and chunks[-1][1] >= until - 0.1
    unsupported = []
    for l in lines:
        for n in _numbers(str(l["text"])):
            if not any(n in _numbers(claims.get(c, "")) for c in (l.get("claim_ids") or [])):
                unsupported.append(n)
    return {"caption_chunks_within_lines": (len(straddle) == 0, straddle[:5]),
            "payoff_caption_to_end": (last_shown_to_end, round(chunks[-1][1], 2) if chunks else None),
            "numbers_supported": (len(unsupported) == 0, unsupported)}


def readiness(lines, spans, slots, words_total, until, whisper_words, export: dict | None = None) -> dict:
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
        # 20 s floor: the channel's own shorts loop best under 15 s and the review target was "roughly
        # 25 seconds"; a 21.9 s one-story cut is inside that, not short of it.
        "length_20_to_36s": (round(until, 1), 20 <= until <= 36),
        "payoff_complete": (str(lines[-1]["text"]).strip()[-1:], lines[-1].get("role") == "payoff" and not str(lines[-1]["text"]).strip().endswith("?")),
        "caption_word_coverage_ge_0_9": (round(whisper_words, 2), whisper_words >= 0.9),
        "distinct_pictures_ge_6": (pictures, pictures >= 6),
        "shot_variety": (sorted({str((l.get("visual") or {}).get("shot", "")) for l in lines}),
                         {"close-up", "wide"} <= {str((l.get("visual") or {}).get("shot", "")) for l in lines}),
    }
    for key, (ok, detail) in (export or {}).items():
        checks[key] = (detail, ok)
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
    ap.add_argument("--headline", default="", help="override the on-screen headline")
    ap.add_argument("--reuse-script", action="store_true",
                    help="keep the lines in short_package.json instead of writing new ones")
    args = ap.parse_args()
    job = os.path.abspath(args.job)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    import explainer_pipeline as ep
    import illustrated_story
    costs: list[float] = []
    title, hook, transcript, claims, states, setting, cautions = _load(job)
    have_images = any(s["path"] for s in states.values())
    generate = args.generate_images or not have_images
    print(f"{title} | {len(claims)} verified claims | {sum(1 for s in states.values() if s['path'])} pictures on disk"
          + (" | drawing new vertical frames" if generate else ""))

    prior = os.path.join(job, "short_package.json")
    openings: list[str] = []
    if args.reuse_script and os.path.isfile(prior):
        prev = json.load(open(prior))
        lines, openings = prev["lines"], prev.get("openings") or []
        print(f"reusing the {len(lines)} approved lines from short_package.json")
    else:
        lines, openings = write_script(title, hook, transcript, claims, states, costs, cautions)
        print("openings proposed:", " | ".join(openings))
    text = " ".join(str(l["text"]).strip() for l in lines)
    print("script:", text)

    audio = os.path.join(job, "short_audio.mp3")
    until = _narrate(text, audio, args.voice, args.speed)
    whisper = ep.transcribe_words(audio)
    words, matched_fraction = align_words(text, whisper) if whisper else ([], 0.0)
    spans = _line_spans(lines, words) if words else []
    if not spans:
        raise SystemExit("whisper returned no word timings; cannot sync captions")
    spans[-1] = (spans[-1][0], until)

    style = illustrated_story.visual_style_suffix(" Vertical portrait composition, subject in the middle third.")
    pictures, checks = [], []
    for i, line in enumerate(lines):
        path = _picture_for(line, states, job, i, style, costs, generate, setting)
        verdict = _check_picture(path, line, states, costs, setting) if generate else {"ok": True, "reason": "film asset, already verified"}
        for attempt in range(2):
            if verdict.get("ok") is not False or not generate:
                break
            reason = str(verdict.get("reason", ""))[:220]
            print(f"  redrawing picture {i + 1} ({attempt + 1}/2): {reason[:100]}")
            path = _picture_for(line, states, job, i, style, costs, generate, setting, feedback=reason)
            verdict = _check_picture(path, line, states, costs, setting)
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
        headline = args.headline.upper() if args.headline else _headline_from(title)
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
        cap_y = H - SAFE_BOTTOM - 210
        chunks = _caption_chunks(words, until, lines)
        for i, (s, e, group) in enumerate(chunks):
            png = os.path.join(tmp, f"cap_{i:03d}.png")
            # Shrink until the chunk fits inside the frame with margins; never let a pill overflow.
            size = 84
            while size > 52 and probe.textlength(" ".join(w.upper() for w in group) + " ", font=_font(size)) > W - 150:
                size -= 6
            _text_png(png, [[(w.upper(), _emphasis(w)) for w in group]], size=size, y=cap_y, stroke=9, pill=True)
            overlays.append((png, s, e))
        # The story finishes on screen. The long-form invitation is a small overlay above the
        # captions during the payoff line, not a card that replaces the last tenth of the Short.
        end_png = os.path.join(tmp, "end.png")
        _text_png(end_png, [[("FULL", YELLOW), ("STORY", YELLOW), ("ON", WHITE), ("THE", WHITE), ("CHANNEL", WHITE)]],
                  size=46, y=cap_y - 125, stroke=6, pill=True)
        overlays.append((end_png, spans[-1][0], until))

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
    export = audit_export(lines, chunks, until, claims)
    gate = readiness(lines, spans, slots, words_total, until, matched_fraction, export)
    package = {
        "short": out_path, "seconds": round(until, 2), "title": (re.sub(r"\s+That\s.*$", "", title, flags=re.I) + " #Shorts")[:100],
        "lines": lines, "openings": openings, "headline": headline,
        "captions": [{"start": round(s_, 2), "end": round(e_, 2), "text": " ".join(g)} for s_, e_, g in chunks],
        "words": words_total, "pictures": pictures, "picture_checks": checks,
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
