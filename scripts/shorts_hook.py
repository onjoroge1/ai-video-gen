"""The first five seconds of a native Short: hook line rules, fast hook cuts, big word captions,
a music bed with hits, feed loudness, and the gate that checks all of it on the rendered file.

Why (Studio read, 2026-10-25): the Shorts feed keeps showing a Short only while most viewers stay.
Stayed-to-watch ran 75% on the Elephant's Foot teaser (1.3K views) and 17-31% on the Hanna and
hippo Shorts (8 and 17 views; the feed stopped after a handful). The teaser opened on a
contradiction resolved by 4.5 s, cut four times in six seconds, and played at -13 LUFS with music.
The native Shorts held one picture for about 4 s, carried voice only at about -23 LUFS, showed
three-word lower-third boxes, and two of them opened on a name-and-date preamble. Aspect ratio was
not the difference: the teaser was cropped from 16:9 stills.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

import make_teaser_short as mts

HOOK_WINDOW = 5.0        # the opening the package governs (s)
HOOK_HOLD = 1.3          # longest framing inside the opening (s)
HOOK_MIN_PART = 0.6      # shortest framing inside the opening (s)
SHOT_HOLD = 2.0          # longest framing after the opening (s): operator 10-26, "change the images every 2 sec"
SHOT_MIN_PART = 0.9
FIRST_CUT_MAX = 1.5      # the first picture change lands by this time (s)
HOOK_MIN_CUTS = 3        # picture changes inside the opening
HOOK_MAX_WORDS = 14       # the 72% Elephant's Foot opening is 13 words
TARGET_LUFS = -14.0      # what the Shorts feed plays at; the teaser that held 75% measured -13.2
LUFS_TOLERANCE = 1.0
TRUE_PEAK = -1.5
MUSIC_LUFS = -30.0       # the bed, before the final gain: about 14 dB under the voice
CAPTION_SIZE = 104
CAPTION_Y = 1150         # centre of the lower-middle: clear of the feed's bottom 17% and of the headline
CAPTION_MAX_WORDS = 2
CAPTION_MAX_CHARS = 16

# Throat-clearing before anything happens. Only true preambles are hard failures: our two best
# openings (72% and 58% stayed) begin "In 1996, a man stood beside the most dangerous thing at
# Chernobyl" and "In 1995 and 1996, 31 wolves were brought back", so a year or an "In ..." opener
# is a warning, not a failure. The three worst (17-31%) open on an anonymous person in a scene
# ("In Colombia, a fisherman felt something move...") and all three END on a question; every one
# of the five best ends on a statement.
_PREAMBLE = re.compile(r"^(this is|did you know|in this video|today we|let me tell you|imagine|"
                       r"the (summer|winter|spring|autumn|fall|year|day|night|morning) (after|before|of|when))\b", re.I)
_YEAR = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b")
_FULL_NAME = re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+(?:'s)?\b")
# Stakes words: danger, death, scale, a superlative, a reversal, or a famous named thing.
_STAKES = re.compile(r"\b(most|largest|biggest|deadliest|first|last|only|never|still|killed?|kills|died?|dead|"
                     r"dangerous|lethal|poison\w*|radioactive|exploded?|vanish\w*|disappear\w*|thousand|million|"
                     r"billion|\d[\d,]*|spilled|capsized|sank|collapsed|crash\w*|attack\w*|evacuat\w*|escaped?|"
                     r"bombs?|reactor|fuel|radiation|pythons?|snakes?|hippos?|toads?|wol(f|ves)|sharks?|"
                     r"chernobyl|yellowstone|escobar|everglades|hiroshima|titanic|wwii|war)\b", re.I)


EMPHASIS = re.compile(
    r"^(kill|kills|killed|dead|died|die|deadly|never|nothing|nobody|every|still|wait|lethal|"
    r"poison|poisonous|toxic|gone|vanished|disappeared|wrong|mistake|failed|exploded|explode|"
    r"evacuated|leave|left|buried|hidden|alive|live)$", re.I)


def hook_problems(text: str, last_line: str = "") -> list[str]:
    """Hard failures of the opening: line 1 too long, a throat-clearing preamble, no stakes in
    line 1, or a Short that ends on a question instead of a payoff."""
    problems = []
    words = text.split()
    if len(words) > HOOK_MAX_WORDS:
        problems.append(f"hook has {len(words)} words (max {HOOK_MAX_WORDS})")
    if _PREAMBLE.match(text.strip()):
        problems.append("hook opens on a scene-setting preamble")
    if not _STAKES.search(text):
        problems.append("hook names no stakes (danger, death, scale, a superlative, a reversal or a famous thing)")
    if last_line.strip().endswith("?"):
        problems.append("the last line is a question; end on the payoff (all three worst Shorts ended on a question)")
    return problems


def hook_warnings(text: str) -> list[str]:
    """Soft signals worth a look, not failures: a year or a person's name before the hook lands."""
    out = []
    if _YEAR.search(" ".join(text.split()[:6])):
        out.append("hook names a year in its first six words")
    if _FULL_NAME.search(text.strip()[1:]):
        out.append("hook names a person before the viewer has a reason to care")
    return out


def hook_shots(shots: list[dict], window: float = HOOK_WINDOW, hold: float = HOOK_HOLD,
               min_part: float = HOOK_MIN_PART) -> list[dict]:
    """Split every shot that starts inside the opening into short framings; the rest keep the
    normal hold. Repeats of one picture then get alternating wide and close windows."""
    out = []
    for shot in shots:
        if shot["start"] < window:
            out.extend(mts.split_long([shot], hold, min_part))
        else:
            out.extend(mts.split_long([shot], SHOT_HOLD, SHOT_MIN_PART))
    return out


def word_chunks(words: list[tuple], until: float, max_words: int = CAPTION_MAX_WORDS,
                max_chars: int = CAPTION_MAX_CHARS) -> list[tuple[float, float, list[str]]]:
    """One or two words per caption, never across a comma or sentence end; each caption stays up
    until the next one starts (or the narration ends)."""
    groups, cur = [], []
    for w in words:
        joined = " ".join([x[0] for x in cur] + [w[0]])
        if cur and (len(cur) >= max_words or len(joined) > max_chars):
            groups.append(cur); cur = []
        cur.append(w)
        if re.search(r"[,.;:!?]$", w[0]):
            groups.append(cur); cur = []
    if cur:
        groups.append(cur)
    out = []
    for i, g in enumerate(groups):
        start = float(g[0][1])
        end = float(groups[i + 1][0][1]) if i + 1 < len(groups) else until
        out.append((start, max(start + 0.05, min(end, until)), [x[0] for x in g]))
    return out


def caption_colour(word: str, extra: set) -> tuple:
    bare = word.strip(".,;:!?\"'").lower()
    if bare in extra or EMPHASIS.match(bare) or re.search(r"\d", bare):
        return mts.YELLOW
    return mts.WHITE


def caption_png(path: str, words: list[str], extra: set) -> None:
    probe = mts.ImageDraw.Draw(mts.Image.new("RGBA", (mts.W, mts.H)))
    size = CAPTION_SIZE
    text = " ".join(w.upper() for w in words)
    while size > 64 and probe.textlength(text + " ", font=mts._font(size)) > mts.W - 120:
        size -= 6
    mts._text_png(path, [[(w.upper().strip(",;:"), caption_colour(w, extra)) for w in words]],
                  size=size, y=CAPTION_Y, stroke=12)


def synth_boom(out: str) -> str:
    mts._run([mts._ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=55:d=0.8",
              "-f", "lavfi", "-i", "anoisesrc=color=brown:d=0.8",
              "-filter_complex", "[0:a]volume=1.6[s];[1:a]highpass=f=40,lowpass=f=220,volume=1.0[n];"
              "[s][n]amix=inputs=2:normalize=0,afade=t=out:st=0.10:d=0.65,volume=1.2,aresample=48000,"
              "aformat=channel_layouts=stereo[o]", "-map", "[o]", out])
    return out


def synth_riser(out: str, seconds: float = 1.3) -> str:
    mts._run([mts._ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i", f"anoisesrc=color=pink:d={seconds}",
              "-f", "lavfi", "-i", f"aevalsrc=0.5*sin(2*PI*t*(180+260*t)):d={seconds}",
              "-filter_complex", "[0:a]highpass=f=220,volume=1.2[w];[1:a]volume=0.4[c];"
              f"[w][c]amix=inputs=2:normalize=0,afade=t=in:st=0:d={seconds - 0.1},volume=0.9,"
              "aresample=48000,aformat=channel_layouts=stereo[o]", "-map", "[o]", out])
    return out


def mix(voice: str, total: float, out: str, tmp: str, music: str = "", hits: list[float] = (),
        risers_to: list[float] = ()) -> dict:
    """Voice (compressed, levelled), a music bed under it, a low hit on each time in `hits`, a
    riser ending on each time in `risers_to`; then one fixed gain to the feed's loudness."""
    from make_short_scripted import _loudnorm_linear
    voice_n, _ = _loudnorm_linear(
        voice, os.path.join(tmp, "voice_n.wav"), -16.0, -1.5,
        pre_filter="acompressor=threshold=-24dB:ratio=3:attack=4:release=90:makeup=2:knee=6,"
                   "alimiter=limit=0.24:attack=3:release=40:level=false")
    inputs, chain, labels = [voice_n], [], ["[0:a]"]
    if music:
        bed, _ = _loudnorm_linear(music, os.path.join(tmp, "music_n.wav"), MUSIC_LUFS, -3.0,
                                  extra=f"atrim=0:{total:.3f},afade=t=in:st=0:d=0.05,"
                                        f"afade=t=out:st={max(0, total - 1.0):.3f}:d=1.0")
        inputs.append(bed)
        labels.append(f"[{len(inputs) - 1}:a]")
    boom = synth_boom(os.path.join(tmp, "boom.wav")) if hits else ""
    riser = synth_riser(os.path.join(tmp, "riser.wav")) if risers_to else ""
    for k, t in enumerate(hits):
        inputs.append(boom)
        ms = int(max(0.0, t) * 1000)
        chain.append(f"[{len(inputs) - 1}:a]volume=0.45,adelay={ms}|{ms}[h{k}]")
        labels.append(f"[h{k}]")
    for k, t in enumerate(risers_to):
        inputs.append(riser)
        ms = int(max(0.0, t - 1.3) * 1000)
        chain.append(f"[{len(inputs) - 1}:a]volume=0.22,adelay={ms}|{ms}[r{k}]")
        labels.append(f"[r{k}]")
    chain.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=first:dropout_transition=0:normalize=0[m]")
    raw = os.path.join(tmp, "mix_raw.wav")
    cmd = [mts._ffmpeg_bin(), "-v", "error", "-y"]
    for p in inputs:
        cmd += ["-i", p]
    cmd += ["-filter_complex", ";".join(chain), "-map", "[m]", "-t", f"{total:.3f}", raw]
    mts._run(cmd)
    # A fixed gain lifts the peaks with the speech: +1.6 dBFS on the first trial. The limiter
    # after it holds them under the true-peak line, costing about 0.3 LU.
    final, mode = _loudnorm_linear(raw, out, TARGET_LUFS + 0.3, TRUE_PEAK,
                                   extra="alimiter=limit=0.70:attack=2:release=60:level=false")
    return {"path": final, "norm": mode}


def loudness(path: str) -> dict:
    """Integrated loudness and true peak of the finished file, measured the way the gate judges it."""
    log = subprocess.run([mts._ffmpeg_bin(), "-hide_banner", "-i", path, "-af", "ebur128=peak=true",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    summary = log[log.rfind("Summary:"):]
    i = re.search(r"I:\s+(-?[\d.]+) LUFS", summary)
    tp = re.search(r"Peak:\s+(-?[\d.]+) dBFS", summary)
    return {"lufs": float(i.group(1)) if i else None, "true_peak": float(tp.group(1)) if tp else None}


def hook_sheet(video: str, out_sheet: str, out_cover: str) -> None:
    """The first three seconds at 2 fps on one strip, and frame 0 as the cover the Shorts tab shows."""
    mts._run([mts._ffmpeg_bin(), "-v", "error", "-y", "-t", "3.4", "-i", video,
              "-vf", "fps=2,scale=270:-1,tile=7x1", "-frames:v", "1", out_sheet])
    mts._run([mts._ffmpeg_bin(), "-v", "error", "-y", "-i", video, "-frames:v", "1", "-q:v", "2", out_cover])


MOVING_HOLD = 5.0         # longest a moving (image-to-video) shot may stay up (s)
MOVING_FIRST_CUT = 3.5    # with a moving first shot, the first change may land this late (s)


def gate(hook_text: str, shots: list[dict], captions: list, level: dict, duration: float,
         last_line: str = "", hold_max: float = SHOT_HOLD, max_duration: float = 45.0) -> dict:
    """Every check as (measured, passed). The film-side checks (claims, pictures) stay with the
    operator's review of the contact sheet; these are the opening's mechanics.

    A shot carrying "motion" (an image-to-video clip, 10-29) already moves, so it may hold up to
    MOVING_HOLD, and a moving first shot lets the first cut land by MOVING_FIRST_CUT with one cut
    fewer in the opening."""
    starts = sorted(s["start"] for s in shots)
    cuts = [t for t in starts if 0 < t <= HOOK_WINDOW]
    first_cut = cuts[0] if cuts else None
    opens_moving = any(s.get("motion") and s["start"] <= 0.01 for s in shots)
    first_max = MOVING_FIRST_CUT if opens_moving else FIRST_CUT_MAX
    min_cuts = HOOK_MIN_CUTS - 1 if opens_moving else HOOK_MIN_CUTS
    holds = [s["end"] - s["start"] for s in shots if not s.get("motion")] or [0.0]
    moving = [s["end"] - s["start"] for s in shots if s.get("motion")]
    if moving and max(moving) > MOVING_HOLD:
        holds.append(max(moving))
    lufs, tp = level.get("lufs"), level.get("true_peak")
    problems = hook_problems(hook_text, last_line)
    return {
        "hook_rules": (problems or "ok", not problems),
        "hook_warnings": (hook_warnings(hook_text) or "none", True),
        "first_cut_le_1_5s": (first_cut, first_cut is not None and first_cut <= first_max),
        "cuts_in_first_5s_ge_3": (len(cuts), len(cuts) >= min_cuts),
        "longest_hold_le_2s": (round(max(holds), 2), max(holds) <= hold_max + 0.05),
        "caption_words_le_2": (max(len(c[2]) for c in captions), max(len(c[2]) for c in captions) <= CAPTION_MAX_WORDS),
        "loudness_minus14_pm1": (lufs, lufs is not None and abs(lufs - TARGET_LUFS) <= LUFS_TOLERANCE),
        "true_peak_le_minus1": (tp, tp is not None and tp <= -1.0),
        "duration_20_to_45s": (round(duration, 2), 20.0 <= duration <= max_duration),
    }


def gate_passed(checks: dict) -> bool:
    return all(ok for _, ok in checks.values())


def words_for_line(mp3: str, text: str, offset: float) -> tuple[list[tuple], float]:
    """Script words with whisper timings for one voiced line, cached beside the audio."""
    cache = mp3[:-4] + ".words.json"
    if os.path.isfile(cache):
        raw = json.load(open(cache, encoding="utf-8"))
    else:
        import explainer_pipeline as ep
        raw = [list(w) for w in ep.transcribe_words(mp3, strict=True)]
        with open(cache, "w", encoding="utf-8") as handle:
            json.dump(raw, handle)
    from make_short_scripted import align_words
    words, matched = align_words(text, [tuple(w) for w in raw])
    return [(w, s + offset, e + offset) for w, s, e in words], matched


# ---- Subject-centred framing for drawn pictures (2026-10-26) --------------------------------
# candidate_windows() scores 9:16 windows by edge density, which was written for film stills. On
# the pictures drawn for a Short (one large subject on a simple background) it slides the window
# toward splashes, foliage and paper grain and away from the smooth subject: the hippo Short's
# last shot showed a body with no head. These pictures are drawn with the subject in the middle,
# so the window is centred on the subject instead, found as the region least like the border.

def subject_box(image_path: str) -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1) of the main subject in source pixels.

    Asked of the vision model once per picture and cached beside it (pic.subject.json): a cent a
    picture against the 17 cents the picture cost. The pixel heuristic (difference from the
    border colour) is the fallback when the call fails; on these torn-paper pictures it mistakes
    the whole illustration for the subject, so it is only a fallback."""
    cache = os.path.splitext(image_path)[0] + ".subject.json"
    if os.path.isfile(cache):
        box = json.load(open(cache, encoding="utf-8")).get("box")
        if box:
            return tuple(box)
    with mts.Image.open(image_path) as im:
        iw, ih = im.size
    box = None
    try:
        import base64
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.expanduser("~/ai-video-gen-local"), ".env"))
        import explainer_pipeline as ep
        # A full 1024x1536 PNG (3-3.7 MB) fails the upload as a connection error; the box comes
        # back as fractions, so a small JPEG answers the same question.
        import io
        buf = io.BytesIO()
        with mts.Image.open(image_path) as im:
            small = im.convert("RGB")
            small.thumbnail((512, 768))
            small.save(buf, "JPEG", quality=85)
        data = base64.b64encode(buf.getvalue()).decode()
        r = ep._claude().messages.create(
            model=ep.ANTHROPIC_MODEL, max_tokens=120,
            system='Answer ONLY JSON: {"subject": "<three words>", "box": [x0, y0, x1, y1]} with the box as '
                   'fractions 0-1 of the image width and height.',
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}},
                {"type": "text", "text": "This picture was drawn for a vertical phone video with ONE main subject. Give the "
                 "tight bounding box of that main subject (the whole animal, person or object, including its head). Ignore "
                 "paper margins, background scenery and small secondary things."}]}])
        parsed, _ = ep._parse_script_json(r.content[0].text)
        f = [float(v) for v in parsed["box"]]
        if 0 <= f[0] < f[2] <= 1 and 0 <= f[1] < f[3] <= 1 and (f[2] - f[0]) * (f[3] - f[1]) >= 0.02:
            box = (int(f[0] * iw), int(f[1] * ih), int(f[2] * iw), int(f[3] * ih))
            with open(cache, "w", encoding="utf-8") as handle:
                json.dump({"box": box, "subject": parsed.get("subject", ""), "source": "vision"}, handle)
    except Exception as exc:
        print(f"subject_box: vision call failed for {os.path.basename(image_path)} ({type(exc).__name__}: {exc}); "
              "using the pixel fallback", file=sys.stderr)
        box = None
    return box or _subject_box_pixels(image_path)


def _subject_box_pixels(image_path: str) -> tuple[int, int, int, int]:
    """Fallback: the largest region that differs from the border colour, weighted to the middle."""
    import numpy as np
    with mts.Image.open(image_path) as im:
        iw, ih = im.size
        small = np.asarray(im.convert("RGB").resize((iw // 8, ih // 8)), dtype=np.float32)
    h, w, _ = small.shape
    m = max(2, min(h, w) // 12)
    border = np.concatenate([small[:m].reshape(-1, 3), small[-m:].reshape(-1, 3),
                             small[:, :m].reshape(-1, 3), small[:, -m:].reshape(-1, 3)])
    diff = np.sqrt(((small - np.median(border, axis=0)) ** 2).sum(axis=2))
    yy, xx = np.mgrid[0:h, 0:w]
    centre_weight = 1.0 - 0.5 * (((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2) / 2
    sal = diff * centre_weight
    keep = sal >= np.percentile(sal, 80)

    def largest_run(profile):
        # The longest stretch of rows/columns that hold a real share of the salient pixels: a
        # noisy edge or a second small object is its own shorter run and is left out.
        on = profile >= 0.25 * profile.max()
        best, cur = (0, 0), None
        for i, v in enumerate(list(on) + [False]):
            if v and cur is None:
                cur = i
            elif not v and cur is not None:
                if i - cur > best[1] - best[0]:
                    best = (cur, i)
                cur = None
        return best

    y0, y1 = largest_run(keep.sum(axis=1).astype(float))
    x0, x1 = largest_run(keep[y0:y1].sum(axis=0).astype(float))
    if (x1 - x0) * (y1 - y0) < 20:
        return (iw // 4, ih // 4, 3 * iw // 4, 3 * ih // 4)
    return (int(x0 * 8), int(y0 * 8), int(min(iw, x1 * 8)), int(min(ih, y1 * 8)))


def subject_windows(image_path: str) -> dict:
    """A wide and a close 9:16 window, both centred on the subject (the close one on the upper
    part of it, where a head or the key object usually is), clamped to the picture."""
    with mts.Image.open(image_path) as im:
        iw, ih = im.size
    x0, y0, x1, y1 = subject_box(image_path)
    cx, cy = (x0 + x1) / 2, y0 + 0.4 * (y1 - y0)

    def window(ch: int):
        cw = min(iw, int(ch * 9 / 16))
        ch = min(ih, ch)
        x = int(min(max(0, cx - cw / 2), iw - cw))
        y = int(min(max(0, cy - ch / 2), ih - ch))
        return (x, y, cw, ch)

    wide = window(ih)
    # The close window still holds the whole subject when it can: never tighter than the subject.
    close_h = max(int(ih * mts.CLOSE), int((y1 - y0) * 1.15), int((x1 - x0) * 16 / 9 * 1.1))
    close = window(min(ih, close_h))
    return {"wide": wide, "close": close, "subject": (x0, y0, x1, y1)}


DRIFT_SPEED = 0.03        # camera drift as a share of the wide window's width per second
PICTURE_HOLD = 2.8        # longest one drawing stays up when every line has its own pictures (s)


def picture_cuts(words: list[tuple], line_start: float, starts_at: list[str | None]) -> list[float]:
    """Absolute start time of each picture in one line. starts_at[0] is None (the line's first
    picture opens with the line); every later entry names the word that picture opens on, found
    after the previous one, so a picture lands on the words it shows."""
    cuts, k = [line_start], 0
    for word in starts_at[1:]:
        want = re.sub(r"[^\w'-]", "", str(word)).lower()
        while k < len(words) and re.sub(r"[^\w'-]", "", words[k][0]).lower() != want:
            k += 1
        if k >= len(words):
            raise ValueError(f"picture cue word {word!r} not found in the line (in order)")
        # A hair before the word, so the picture is up as the word is heard.
        cuts.append(max(cuts[-1] + 0.3, words[k][1] - 0.08))
        k += 1
    return cuts


def frame_drawn(shots: list[dict]) -> list[dict]:
    """Window and camera path for every shot of a native Short. Each picture gets one slow drift
    at constant speed, centred on its subject, across all of that picture's time on screen; the
    direction alternates by line (by picture when shots carry no line), never inside a picture.
    A repeat of one picture still alternates the wide and close windows. The operator rejected the
    push-in/pull-out zoom (10-26), a pan reversed on every cut (10-27), and the eased start-stop of
    each move as jerky (10-28): a documentary camera drifts at one speed and cuts on the move."""
    cache, out, runs, i = {}, [], [], 0
    while i < len(shots):
        j = i
        while j + 1 < len(shots) and shots[j + 1]["image"] == shots[i]["image"]:
            j += 1
        runs.append((i, j))
        i = j + 1
    for k, (i, j) in enumerate(runs):
        img = shots[i]["image"]
        if img not in cache:
            with mts.Image.open(img) as im:
                cache[img] = (subject_windows(img), im.size[0])
        win, iw = cache[img]
        wx, _, wcw, _ = win["wide"]
        t0, t1 = shots[i]["start"], shots[j]["end"]
        travel = min(DRIFT_SPEED * wcw * (t1 - t0), iw - wcw)
        # The path is centred on the subject and shifted, when needed, to keep the wide window inside.
        lo, hi = wcw / 2, iw - wcw / 2
        centre = min(max(wx + wcw / 2, lo + travel / 2), hi - travel / 2)
        order = shots[i].get("beat", k)
        direction = 1 if order % 2 == 0 else -1
        for run, shot in enumerate(shots[i:j + 1]):
            out.append(dict(shot, window=win["close" if run % 2 else "wide"], move="drift",
                            subject=win["subject"],
                            path={"t0": t0, "dur": t1 - t0, "centre": centre, "travel": travel,
                                  "direction": direction}))
    return out


def drift_x(path: dict, t: float, cw: float, iw: int) -> float:
    """Left edge of a window of width cw at time t on the picture's constant-speed drift."""
    u = min(max((t - path["t0"]) / max(path["dur"], 1e-6), 0.0), 1.0)
    cx = path["centre"] + path["direction"] * path["travel"] * (u - 0.5)
    return min(max(cx - cw / 2, 0.0), iw - cw)


def render_drawn(shots: list[dict], out_path: str, tmp: str) -> None:
    """Render frame_drawn shots frame by frame with a sub-pixel affine crop of each picture, so a
    slow drift glides instead of stepping a whole pixel at a time (ffmpeg's crop rounds x)."""
    from PIL import Image
    W, H, fps = mts.W, mts.H, mts.FPS
    total = shots[-1]["end"]
    n = int(round(total * fps))
    pictures = {}
    cmd = [mts._ffmpeg_bin(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "medium",
           "-crf", "16", "-pix_fmt", "yuv420p", "-an", out_path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    k = 0
    try:
        for f in range(n):
            t = f / fps
            while k + 1 < len(shots) and t >= shots[k]["end"]:
                k += 1
            shot = shots[k]
            if shot["image"] not in pictures:
                pictures[shot["image"]] = Image.open(shot["image"]).convert("RGB")
            im = pictures[shot["image"]]
            _, y, cw, ch = shot["window"]
            x = drift_x(shot["path"], t, cw, im.size[0])
            frame = im.transform((W, H), Image.AFFINE, (cw / W, 0, x, 0, ch / H, y),
                                 resample=Image.BICUBIC)
            proc.stdin.write(frame.tobytes())
    finally:
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg failed while encoding the drawn shots")


# ---- A moving shot: one drawing animated by an image-to-video model (2026-10-29) ---------------
# Breakout Shorts in our lanes move from frame 1 (scout of 685 Shorts, 10-29); ours opened on a
# still. A picture may carry "motion": "<camera/subject movement>"; its shot then plays a short
# clip generated from that same drawing instead of the drift.
MOTION_MODEL = "kling-v2.1-standard"       # $0.28 per 5 s clip (fal price page, verified 2026-07)
MOTION_SECONDS = 5


def animate_picture(image_path: str, motion: str, model: str = MOTION_MODEL) -> str:
    """The clip for one drawing, generated once and cached beside it."""
    import base64
    import hashlib
    import io
    import time
    import requests
    import fal_models
    endpoint = fal_models.resolve(model)
    key = hashlib.sha256(f"{endpoint}|{motion}".encode()).hexdigest()[:12]
    out = os.path.splitext(image_path)[0] + f".motion_{key}.mp4"
    if os.path.isfile(out) and os.path.getsize(out) > 0:
        return out
    fal_key = os.environ.get("FAL_KEY", "").strip()
    if not fal_key:
        raise RuntimeError("FAL_KEY is not set: a moving shot needs the fal image-to-video provider")
    buf = io.BytesIO()
    with mts.Image.open(image_path) as im:
        im.convert("RGB").save(buf, "JPEG", quality=92)
    uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    body = fal_models.build_i2v_body(endpoint, prompt=motion, image_url=uri, seconds=MOTION_SECONDS,
                                     aspect_ratio="9:16", audio=False)
    hdr = {"Authorization": f"Key {fal_key}"}
    sub = requests.post(f"https://queue.fal.run/{endpoint}", headers=hdr, json=body, timeout=60)
    if sub.status_code not in (200, 201):
        raise RuntimeError(f"fal submit {sub.status_code}: {sub.text[:160]}")
    job = sub.json()
    for _ in range(80):
        time.sleep(6)
        state = requests.get(job["status_url"], headers=hdr, timeout=30).json().get("status")
        if state == "COMPLETED":
            break
        if state in ("FAILED", "ERROR"):
            raise RuntimeError(f"fal job {state}")
    else:
        raise RuntimeError("fal timeout")
    result = requests.get(job["response_url"], headers=hdr, timeout=30).json()
    url = (result.get("video") or {}).get("url")
    if not url:
        raise RuntimeError(f"fal returned no video: {str(result)[:160]}")
    with open(out, "wb") as handle:
        handle.write(requests.get(url, timeout=120).content)
    with open(os.path.join(os.path.dirname(image_path), "picture_costs.jsonl"), "a", encoding="utf-8") as ledger:
        ledger.write(json.dumps({"clip": os.path.basename(out), "model": endpoint,
                                 "usd": fal_models.estimate_clip_usd(endpoint, MOTION_SECONDS)}) + "\n")
    return out


def overlay_moving(base: str, shots: list[dict], out_path: str) -> str:
    """`base` with each moving shot's clip laid over its own time span (cropped to fill 9:16)."""
    moving = [s for s in shots if s.get("motion_clip")]
    if not moving:
        return base
    cmd = [mts._ffmpeg_bin(), "-v", "error", "-y", "-i", base]
    chain, prev = [], "[0:v]"
    for k, s in enumerate(moving):
        cmd += ["-i", s["motion_clip"]]
        t0, t1 = s["start"], s["end"]
        chain.append(f"[{k + 1}:v]scale={mts.W}:{mts.H}:force_original_aspect_ratio=increase,"
                     f"crop={mts.W}:{mts.H},fps={mts.FPS},setpts=PTS-STARTPTS+{t0:.3f}/TB[m{k}]")
        chain.append(f"{prev}[m{k}]overlay=0:0:eof_action=pass:enable='between(t,{t0:.3f},{t1:.3f})'[v{k}]")
        prev = f"[v{k}]"
    cmd += ["-filter_complex", ";".join(chain), "-map", prev, "-c:v", "libx264", "-preset", "medium",
            "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(mts.FPS), out_path]
    mts._run(cmd)
    return out_path
