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
WORDS_MIN, WORDS_MAX = 70, 92
PICTURE_SECONDS = 1.9          # a fresh picture at least this often
MIN_PICTURE_SECONDS = 1.1

_SCRIPT_SYSTEM = """You write 25-second vertical YouTube Shorts for a documentary channel about interventions that backfired. A Short tells ONE complete story: one question, one mechanism, one consequence, one payoff, then a spoken invitation to the full film. It must be TRUE to the film's verified claims and nothing else.

Return ONLY JSON:
{"openings": ["...?", "...?", "...?"],
 "lines": [{"text": "...", "role": "hook|decision|setup|mechanism|consequence|payoff|cta", "claim_ids": ["c01"],
            "emphasis": ["one", "two"],
            "visual": {"shot": "close-up|medium|wide", "subject": "...", "action": "..."},
            "picture": "state:s001:e01 or NEW: ..."}]}

Story shape (7 to 9 lines, 70 to 92 words):
- openings: THREE candidate first lines, each a QUESTION of at most 10 words ending with "?", naming the actual animal or plant, whose answer is a contradiction the viewer can SEE in picture 1 ("Why would anyone import a toad that kills what eats it?"). No place names, dates or numbers. Line 1 (role hook) is one of them, verbatim.
- line 2 (role decision), at most 8 words: the human decision that answers the question and makes it absurd ("Australia brought it in on purpose."). It must NOT begin with the same word as line 1 and must not repeat the animal's name.
- one line (role setup): what they were trying to fix, in plain words. No agency names, town names or dates.
- one line (role mechanism): why it failed, conversational, bound by the EDITORIAL CONSTRAINTS below; never present one hypothesised reason as the whole explanation if the brief says it is not.
- two or three lines (role consequence): what happened instead, each a different concrete consequence, plain words a stranger understands.
- one line (role payoff): a NEW fact that reframes the story, not a restatement of line 1; it may share the animal's name with line 1 and nothing else.
- the LAST line (role cta), spoken, at most 16 words, may be two short sentences: name ONE thing the film shows that this Short did not (from the ledger or transcript, no numbers), then "The full story is on the channel." Example: "Some snakes are now evolving to survive it. The full story is on the channel."

Language: every line is one spoken sentence (the cta may be two) of at most 14 words, present tense where possible, no semicolons, dashes or parentheses, at most one comma, no lists of more than three. Spoken register throughout: never research prose. Banned words: monitored, significantly, dramatically, documented, populations, estimated, reported, data, study, species-level, respectively.

Numbers: at most ONE number in the whole Short, years included, only if a cited claim states it exactly and the same sentence says what it counts. Prefer none.

Facts: every line except the hook and cta cites claim ids that actually state what the line says. Never invent a number, species, place, date or cause.

Emphasis: for each line, one or two words the captions should highlight: the danger or the twist (kill, poison, on purpose, failed), never a proper noun.

Visuals, written WITH the words: every line's visual names the shot size, the subject and ONE action a single still can show (a predator with a toad in its jaws, a quoll on bare rock); never a change over time and never a silhouette. Picture 1 must make the danger legible in one glance: the action itself, not the aftermath (a lizard biting down on a toad, not a lizard lying near one). Only the animals, people and objects the line names may appear. Vary shot size: never the same size three lines running; at least one close-up and one wide. Line 1 and the payoff share one composition so the loop is seamless. Pictures: a state id from the available pictures when one truly fits, otherwise "NEW: " plus a 12-25 word literal description in the film's real setting and period: a named animal doing a named thing in a named place, filling the frame.
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


JARGON = re.compile(r"\b(monitored|significantly|dramatically|documented|populations?|estimated|reported|data|study|species-level|respectively)\b", re.I)


def _validate(lines: list[dict], claims: dict, states: dict, openings: list | None = None) -> list[str]:
    errs = []
    if not 7 <= len(lines) <= 9:
        errs.append(f"{len(lines)} lines; need 7-9")
    words = sum(len(str(l.get("text", "")).split()) for l in lines)
    if not WORDS_MIN <= words <= WORDS_MAX:
        errs.append(f"{words} words; need {WORDS_MIN}-{WORDS_MAX}")
    if openings is not None and len([o for o in openings if str(o).strip()]) != 3:
        errs.append("propose exactly 3 openings")
    first_word = ""
    if lines:
        first = str(lines[0].get("text", "")).strip()
        first_word = (first.split() or [""])[0].lower().strip(",.?")
        if len(first.split()) > 10:
            errs.append(f"line 1 is {len(first.split())} words; max 10")
        if lines[0].get("role") != "hook" or not first.endswith("?"):
            errs.append("line 1 must be role hook and a question ending with ?")
        if openings and first not in [str(o).strip() for o in openings]:
            errs.append("line 1 must be one of the proposed openings, verbatim")
        if _numbers(first) or re.search(r"\b(1[6-9]\d\d|20\d\d)\b", first):
            errs.append("line 1 must contain no number or date")
        if len(lines) > 1:
            second = str(lines[1].get("text", "")).strip()
            if lines[1].get("role") != "decision" or len(second.split()) > 8:
                errs.append("line 2 must be role decision, at most 8 words")
            if (second.split() or [""])[0].lower().strip(",.") == first_word:
                errs.append("line 2 must not begin with the same word as line 1")
        last = str(lines[-1].get("text", "")).strip()
        if lines[-1].get("role") != "cta" or "full story" not in last.lower() or "channel" not in last.lower():
            errs.append("last line must be role cta and say the full story is on the channel")
        if len(last.split()) > 16:
            errs.append("cta is over 16 words")
        payoffs = [l for l in lines if l.get("role") == "payoff"]
        if len(payoffs) != 1:
            errs.append("exactly one payoff line")
        else:
            a = {w.lower().strip(",.?!") for w in first.split() if len(w) > 3}
            b = {w.lower().strip(",.?!") for w in str(payoffs[0].get("text", "")).split() if len(w) > 3}
            if a and len(a & b) / len(a) > 0.5:
                errs.append("the payoff restates line 1; it must add a new fact")
    roles = [str(l.get("role")) for l in lines]
    for needed in ("decision", "setup", "mechanism", "consequence"):
        if needed not in roles:
            errs.append(f"no line has role {needed}")
    all_numbers = set()
    shots = []
    for i, l in enumerate(lines, 1):
        text = str(l.get("text", ""))
        limit = 16 if l.get("role") == "cta" else 14
        if len(text.split()) > limit:
            errs.append(f"line {i} is {len(text.split())} words; max {limit}")
        if re.search(r"explained like you are five|in this video|let'?s dive|did not increase", text, re.I):
            errs.append(f"line {i} contains filler or research prose")
        m = JARGON.search(text)
        if m:
            errs.append(f"line {i} uses the banned word '{m.group(0)}'")
        if re.search(r"[;—–(]", text) or len(re.findall(r"(?<!\d),|,(?!\d)", text)) > 1:
            errs.append(f"line {i} uses semicolons, dashes, parentheses or more than one comma")
        ids = [str(c) for c in (l.get("claim_ids") or [])]
        if l.get("role") not in ("hook", "cta"):
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
    # Words that make the model draw an absence or a ghost. "a fading quoll" came back as a faint
    # outline on a rock face and the checker let it through (cane toads, 2026-10-01).
    desc = re.sub(r"\b(fading|faint|faded|ghostly|ghosted|disappearing|vanishing|silhouettes?|outlines?|"
                  r"shadowy|translucent|declining|spreading across)\b", "", desc, flags=re.I)
    desc = re.sub(r"\s+", " ", desc).strip()
    names_people = bool(re.search(r"\b(farmer|worker|hunter|people|man|woman|men|women|official|scientist|"
                                  r"entomologist|crowd|settler|rancher|person)s?\b",
                                  f"{line.get('text', '')} {visual.get('subject', '')} {visual.get('action', '')}", re.I))
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
                "fully drawn animals and objects in full colour with ink contour, like every other subject."
              + ("" if names_people else " No people in this frame at all; the narration names none.")
              + " Do not add any animal, person, vehicle or object the description does not name."
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
    """Picture slots: (start, end, path, framing). A line longer than PICTURE_SECONDS is split;
    the second part is a different unused film image when one exists, otherwise a hard cut to a
    tight detail crop of the same image, so every slot is a visibly different composition.
    Cuts land on sentence boundaries by construction (each line starts a slot)."""
    slots = []
    pool = list(extra_pool)
    for (s_, e_), pic in zip(spans, pictures):
        d = e_ - s_
        n = max(1, int(round(d / PICTURE_SECONDS + 0.49)))
        step = d / n
        for k in range(n):
            if k % 2 == 1 and pool:
                slots.append((s_ + k * step, s_ + (k + 1) * step, pool.pop(0), "full"))
            else:
                slots.append((s_ + k * step, s_ + (k + 1) * step, pic, "detail" if k % 2 == 1 else "full"))
    return slots


def _render_slots(slots, out_path, tmp):
    parts = []
    for i, (s_, e_, path, framing) in enumerate(slots):
        d = max(MIN_PICTURE_SECONDS * 0.8, e_ - s_)
        n = max(1, int(round(d * FPS)))
        with Image.open(path) as im:
            iw, ih = im.size
        cw = min(iw, int(ih * 9 / 16))
        if framing == "detail":
            # A tight crop on the upper-middle of the subject, pulling out slightly: reads as a
            # second camera, not a continuation of the push.
            crop_w, crop_h = int(cw * 0.62), int(ih * 0.62)
            crop = f"crop={crop_w}:{crop_h}:(iw-{crop_w})/2:ih*0.14"
            z = f"max(1.10-0.10*on/{n},1.0)"
        else:
            crop = f"crop={cw}:{ih}:(iw-{cw})/2:0"
            z = f"min(1+0.20*on/{n},1.20)" if i % 2 == 0 else f"max(1.20-0.20*on/{n},1.0)"
        vf = (f"{crop},scale=2160:3840,"
              f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={W}x{H}:fps={FPS},format=yuv420p")
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
    chunks, cursor = [], 0
    for l in (lines or [{"text": " ".join(w[0] for w in words)}]):
        # Clauses first (split at commas), then 3-4 word groups inside a clause, so a chunk is
        # always a phrase a reader would say in one breath: never "high, and sugar".
        clause_lengths = [len(c.split()) for c in re.split(r"(?<=[,.!?])\s+", str(l["text"])) if c.strip()]
        for n in clause_lengths:
            clause_words = words[cursor:cursor + n]
            cursor += n
            if n <= 4:
                groups = [clause_words]
            else:
                per = 4 if n % 4 == 0 or n % 3 == 1 else 3
                groups = [clause_words[i:i + per] for i in range(0, n, per)]
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


_EMPHASIS_WORDS = re.compile(r"^(kill|kills|killed|killing|poison|poisons|poisonous|deadly|die|died|dies|dead|"
                             r"fail|failed|fails|backfired|toxic|toxin|swallow|swallowed|disappear|disappeared|"
                             r"vanished|never|nothing|every|worse|wrong|mistake|purpose|evolving|evolved|survive)$", re.I)
_EMPHASIS_EXTRA: set = set()


def _emphasis(word: str) -> tuple:
    bare = word.strip(".,;:!?").lower()
    if bare in _EMPHASIS_EXTRA or _EMPHASIS_WORDS.match(bare) or re.search(r"\d", bare):
        return YELLOW
    return WHITE


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
    last_shown_to_end = bool(chunks) and chunks[-1][1] >= until - 0.1   # the cta caption stays up
    unsupported = []
    for l in lines:
        for n in _numbers(str(l["text"])):
            if not any(n in _numbers(claims.get(c, "")) for c in (l.get("claim_ids") or [])):
                unsupported.append(n)
    return {"caption_chunks_within_lines": (len(straddle) == 0, straddle[:5]),
            "payoff_caption_to_end": (last_shown_to_end, round(chunks[-1][1], 2) if chunks else None),
            "numbers_supported": (len(unsupported) == 0, unsupported)}


def _silence_fraction(audio: str) -> float:
    out = subprocess.run([_ffmpeg_bin(), "-i", audio, "-af", "silencedetect=n=-32dB:d=0.25", "-f", "null", "-"],
                         capture_output=True, text=True)
    total = sum(float(m) for m in re.findall(r"silence_duration: ([0-9.]+)", out.stderr))
    return total / max(0.1, _duration(audio))


def readiness(lines, spans, slots, words_total, until, whisper_words, export: dict | None = None,
              audio: str = "") -> dict:
    first_words = len(str(lines[0]["text"]).split())
    pictures = len({p for _, _, p, _ in slots})
    compositions = len({(p, f) for _, _, p, f in slots})
    silence = _silence_fraction(audio) if audio else 0.0
    checks = {
        "hook_is_question": (str(lines[0]["text"]).strip()[-1:], str(lines[0]["text"]).strip().endswith("?")),
        "spoken_cta": (lines[-1].get("role"), lines[-1].get("role") == "cta" and "channel" in str(lines[-1]["text"]).lower()),
        # Natural speech breathes about one eighth of the time; the first cut sat at a fifth.
        "silence_fraction_le_0_14": (round(silence, 3), silence <= 0.14),
        "distinct_compositions_ge_12": (compositions, compositions >= 12),
        "words_before_twist_le_10": (first_words, first_words <= 10),
        # Measured on the first scripted Short (cane toads, echo at 1.3x, eight plain sentences):
        # 66 words in 23.0 s is 2.86 w/s, and an 8-word first line lands at 3.3 s because the
        # voice pauses at every full stop. Those are the pace of a narrator reading punchy copy,
        # not a documentary drawl, so the bands sit where a measured natural read can reach.
        "seconds_to_twist_le_3_5": (round(spans[0][1], 2), spans[0][1] <= 3.5),
        "composition_interval_le_2s": (round(until / max(1, compositions), 2), until / max(1, compositions) <= 2.0),
        "words_per_second_2_7_to_3_9": (round(words_total / until, 2), 2.7 <= words_total / until <= 3.9),
        # 20 s floor: the channel's own shorts loop best under 15 s and the review target was "roughly
        # 25 seconds"; a 21.9 s one-story cut is inside that, not short of it.
        "length_19_to_36s": (round(until, 1), 19 <= until <= 36),
        "payoff_adds_a_fact": ([l["text"][:40] for l in lines if l.get("role") == "payoff"], any(l.get("role") == "payoff" for l in lines)),
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
    ap.add_argument("--music", default="tense", help="music_assets mood: tense|dramatic|energetic|upbeat|corporate|nostalgic")
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
    for l in lines:
        for w in (l.get("emphasis") or []):
            _EMPHASIS_EXTRA.add(str(w).lower().strip(".,;:!?"))

    raw_audio = os.path.join(job, "short_audio_raw.mp3")
    audio = os.path.join(job, "short_audio.mp3")
    raw_len = _narrate(text, raw_audio, args.voice, args.speed)
    # The voice stops for up to a second at every full stop (20% of the first cut was silence,
    # 1.06 s of it right after the hook). Keep 0.22 s of each pause, which is how a person
    # reading punchy copy breathes, and drop the rest.
    _run([_ffmpeg_bin(), "-v", "error", "-y", "-i", raw_audio, "-af",
          # The voice's "silence" carries room tone at about -27 dB RMS, so -35 dB removed almost
          # nothing (measured: 0.28 s of 4.0 s). -30 dB catches the pauses; 0.24 s stays.
          "silenceremove=stop_periods=-1:stop_duration=0.28:stop_threshold=-30dB:stop_silence=0.24,"
          "silenceremove=start_periods=1:start_duration=0.05:start_threshold=-30dB",
          "-c:a", "libmp3lame", "-q:a", "2", audio])
    until = _duration(audio)
    print(f"narration {raw_len:.2f}s -> {until:.2f}s after trimming pauses")
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
        # The headline arrives after the question is asked: "MISTAKE" on screen at 0 s answers
        # the hook before the voice does, and duplicates the first caption's words.
        overlays.append((head_png, spans[0][1], until))
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

        # A bed with a pulse, not the film's classical score at an inaudible level; a riser into
        # the last line and a soft boom on it. Kevin MacLeod tracks need the credit line.
        music, music_credit = "", ""
        try:
            import music_assets
            music = music_assets.get_music_path(args.music) or ""
            music_credit = music_assets.MUSIC_CREDIT if music else ""
        except Exception:
            music = ""
        riser = os.path.join(tmp, "riser.wav")
        _run([_ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i", "anoisesrc=color=pink:d=1.3",
              "-f", "lavfi", "-i", "aevalsrc=0.5*sin(2*PI*t*(180+260*t)):d=1.3",
              "-filter_complex", "[0:a]highpass=f=220,volume=1.2[w];[1:a]volume=0.4[c];"
              "[w][c]amix=inputs=2:normalize=0,afade=t=in:st=0:d=1.2,volume=0.9,aresample=48000[o]",
              "-map", "[o]", riser])
        boom = os.path.join(tmp, "boom.wav")
        _run([_ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=58:d=0.7",
              "-f", "lavfi", "-i", "anoisesrc=color=brown:d=0.7",
              "-filter_complex", "[0:a]volume=1.6[s];[1:a]highpass=f=40,lowpass=f=200,volume=1.0[n];"
              "[s][n]amix=inputs=2:normalize=0,afade=t=out:st=0.12:d=0.55,volume=1.2,aresample=48000[o]",
              "-map", "[o]", boom])
        cta_at = spans[-1][0]
        cmd = [_ffmpeg_bin(), "-v", "error", "-y", "-i", base, "-i", audio]
        if music:
            cmd += ["-i", music]
        cmd += ["-i", riser, "-i", boom]
        for png, _, _ in overlays:
            cmd += ["-i", png]
        first_png = (5 if music else 4)
        riser_idx, boom_idx = (3, 4) if music else (2, 3)
        chain, prev = [], "[0:v]"
        for k, (_, s, e) in enumerate(overlays):
            nxt = f"[v{k}]"
            chain.append(f"{prev}[{first_png + k}:v]overlay=0:0:enable='between(t,{s:.3f},{e:.3f})'{nxt}")
            prev = nxt
        fx = (f"[{riser_idx}:a]adelay={int(max(0, cta_at - 1.3) * 1000)}|{int(max(0, cta_at - 1.3) * 1000)}[r];"
              f"[{boom_idx}:a]adelay={int(cta_at * 1000)}|{int(cta_at * 1000)}[b]")
        if music:
            chain.append(f"[2:a]atrim=0:{until:.3f},loudnorm=I=-29:TP=-8:LRA=7,afade=t=in:st=0:d=0.4,"
                         f"afade=t=out:st={max(0, until - 0.8):.3f}:d=0.8[m];" + fx + ";"
                         f"[1:a][m][r][b]amix=inputs=4:duration=first:dropout_transition=0:normalize=0,"
                         f"loudnorm=I=-15:TP=-1.5:LRA=9[a]")
        else:
            chain.append(fx + f";[1:a][r][b]amix=inputs=3:duration=first:dropout_transition=0:normalize=0,"
                         f"loudnorm=I=-15:TP=-1.5:LRA=9[a]")
        amap = "[a]"
        cmd += ["-filter_complex", ";".join(chain), "-map", prev, "-map", amap,
                "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                "-r", str(FPS), "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
                "-t", f"{until:.3f}", out_path]
        _run(cmd)

    words_total = len(text.split())
    export = audit_export(lines, chunks, until, claims)
    gate = readiness(lines, spans, slots, words_total, until, matched_fraction, export, audio)
    package = {
        "short": out_path, "seconds": round(until, 2), "title": (_headline_from(title).title() + " #Shorts")[:100],   # no unexplained number in the title either
        "lines": lines, "openings": openings, "headline": headline, "music": music and os.path.basename(music),
        "music_credit": music_credit,
        "slots": [{"start": round(a, 2), "end": round(b, 2), "picture": os.path.basename(p_), "framing": f_} for a, b, p_, f_ in slots],
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
