"""LONG-FORM quiz GAME (landscape 16:9) — a separate format from the Shorts quiz.

Hypothesis being tested: the long-form audience (who CLICK a thumbnail to opt IN to playing) is a far
better trivia prospect than the Shorts feed-scroller (who swipes ~80% instantly). So this is a
play-along GAME, not a slideshow: a themed run of rounds EASY->EXPERT, with VARIED clue types (so it's
not the same shot over and over), ESCALATING POINTS (later rounds worth more), a running "top score"
ceiling, difficulty-tier CHAPTERS, and a final self-score GRADE with a "comment your rank" dare.

Reuses the resolution-agnostic primitives from quiz_pipeline (_dur/_still/_safe_image/_composite/_t/
_font) + explainer_pipeline (generate_tts/_animate_one/make_fallback_frame). Best-effort throughout.
"""
import os, subprocess, json
from PIL import Image, ImageDraw, ImageOps
import explainer_pipeline as ep
import quiz_pipeline as qp

FF, FP, MUSIC = qp.FF, qp.FP, qp.MUSIC
LW, LH, FPS = 1920, 1080, 30
NAVY, WHITE, CYAN, YEL, RED = qp.NAVY, qp.WHITE, qp.CYAN, qp.YEL, qp.RED
GREEN = (80, 200, 120)
_DIFF_COL = {"easy": (80, 200, 120), "medium": (245, 200, 70), "hard": (245, 150, 60), "expert": (240, 80, 80)}
_DIFF_PTS = {"easy": 10, "medium": 20, "hard": 30, "expert": 50}      # later/harder rounds = more points
_ROUND_VERB = {  # how Bolt asks the question per clue type (spoken)
    "silhouette": "Name it from the shadow.", "closeup": "Name it from this close-up.",
    "young": "Name the grown-up.", "detail": "Whose is this?"}


def _grade_tiers(max_score: int):
    """Self-score rank ladder from the max possible — the viewer tallies their own points and finds
    their rank. Returns [(min_points, RANK)] ascending."""
    return [(0, "ROOKIE"), (int(max_score * 0.40), "SHARP"),
            (int(max_score * 0.65), "EXPERT"), (int(max_score * 0.85), "GENIUS")]


_LFQ_SYSTEM = (
    "You are a YouTube LONG-FORM quiz writer. Bolt, a fun robot host, runs a play-along guessing GAME on "
    "one THEME for a viewer who CHOSE to play (so it can be a real challenge, not a 5-second short).\n"
    "Produce N rounds ordered EASY -> EXPERT. CRITICAL — VARY THE CLUE TYPE so it never feels like the "
    "same shot over and over; rotate across: 'silhouette' (bold black outline), 'closeup' (extreme "
    "close-up of the skin/fur/pattern/texture), 'young' (a BABY/juvenile — the viewer names the adult "
    "species), 'detail' (ONE distinctive body part in isolation — 'whose ___ is this?'). Spread the types "
    "so no type repeats more than twice in a row.\n"
    "AI-SAFE: no text, letters, numbers, logos, flags, maps or signs in any clue image (an image model "
    "garbles those). Each clue is a SINGLE image, guessable-but-challenging. Round 1 = easy but not "
    "trivially obvious (needs ~1s thought); the final rounds = genuinely hard or slightly deceptive.\n"
    "CONSISTENT REVEALS: every reveal is the subject centered on a clean SOLID colorful studio "
    "background (no habitat/scene). 'reaction' = a 2-4 word punch flavored by difficulty.\n"
    "Return ONLY JSON: {\"title\":\"clickable, e.g. 'Can You Name All 15 Animals? (Easy to Impossible)'\","
    "\"theme\":\"animals\",\"cold_open\":\"one high-energy spoken hook: tell the viewer to KEEP SCORE, "
    "promise it gets brutal by the end, no fluff\",\"outro\":\"a short spoken line daring them to comment "
    "their score and rank\",\"rounds\":[{\"n\":1,\"round_type\":\"silhouette|closeup|young|detail\","
    "\"difficulty\":\"easy|medium|hard|expert\",\"clue_visual\":\"a bold black silhouette of a "
    "flamingo\",\"reveal_visual\":\"a friendly 3D flamingo centered on a clean solid background\","
    "\"answer\":\"FLAMINGO\",\"reaction\":\"Too easy!\",\"fact\":\"one short fun fact\","
    "\"color\":\"gold|teal|lavender|coral|sky|mint|amber|rose\"}]}."
)


def generate_longform_quiz(theme: str, n_rounds: int = 12, cost_sink=None, operator_direction: str = "") -> dict:
    """LLM long-form quiz for `theme`: varied round types, EASY->EXPERT. Adds per-round points (by
    difficulty, so later=more), max_score + grade tiers. Best-effort ({} on failure)."""
    try:
        r = ep._claude().messages.create(model="claude-opus-4-8", max_tokens=4000, system=_LFQ_SYSTEM,
            messages=[{"role": "user", "content": f"Theme: {theme}. Make {n_rounds} rounds. Return JSON."
                       + ep._operator_block(operator_direction)}])
        if cost_sink is not None:
            cost_sink.append(ep._msg_cost(r.usage))
        q, _ = ep._parse_script_json(r.content[0].text)
        rounds = [it for it in (q.get("rounds") or []) if isinstance(it, dict)
                  and ep._s(it.get("answer")).strip() and ep._s(it.get("clue_visual")).strip()][:n_rounds]
        if not rounds:
            return {}
        for i, it in enumerate(rounds, 1):
            it["n"] = i
            it["difficulty"] = (ep._s(it.get("difficulty")).lower() or "medium")
            if it["difficulty"] not in _DIFF_PTS:
                it["difficulty"] = "medium"
            it["points"] = _DIFF_PTS[it["difficulty"]]
        q["rounds"] = rounds
        q["items"] = rounds                       # alias so qp.factcheck_quiz (reads .items) works unchanged
        q["max_score"] = sum(it["points"] for it in rounds)
        q["grade_tiers"] = _grade_tiers(q["max_score"])
        return q
    except Exception as e:
        print(f"[lfquiz] generate failed: {e}")
        return {}


# ── landscape render helpers ───────────────────────────────────────────────────────
def _lf_fit(src, out, mode="fit", bg=NAVY):
    im = Image.open(src).convert("RGB")
    (ImageOps.pad(im, (LW, LH), color=bg) if mode == "pad" else ImageOps.fit(im, (LW, LH))).save(out)


def _pill(d, box, fill, outline=None, w=0, radius=26):
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=w)


def _lf_overlay(path, round_label=None, difficulty=None, points=None, score=None, question=None,
                cd_left=None, answer=None, got_pts=None, grade=None, chapter=None):
    """One landscape (1920x1080) overlay PNG. Clue is the hero in the middle band; text lives in the
    top (~0-150px) and bottom (~890-1080px) bands so it never covers the clue."""
    im = Image.new("RGBA", (LW, LH), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    if chapter:                                              # full-frame chapter/tier title card
        _pill(d, [0, 0, LW, LH], (*NAVY, 235), radius=0)
        _pill(d, [LW//2-520, LH//2-120, LW//2+520, LH//2+120], (*CYAN, 255), radius=40)
        qp._t(d, (LW//2, LH//2), chapter.upper(), 110, NAVY, stroke=0)
        im.save(path); return
    if grade:                                                # self-score rank ladder
        _pill(d, [0, 0, LW, LH], (*NAVY, 238), radius=0)
        qp._t(d, (LW//2, 130), "ADD UP YOUR SCORE", 96, CYAN, stroke=8)
        qp._t(d, (LW//2, 235), f"OUT OF {grade['max']} POINTS", 54, WHITE, stroke=5)
        tiers = grade["tiers"]; y = 350
        for lo, rank in tiers:
            col = {"ROOKIE": WHITE, "SHARP": (120, 200, 255), "EXPERT": YEL, "GENIUS": (255, 170, 60)}.get(rank, WHITE)
            qp._t(d, (LW//2, y), f"{lo}+   {rank}", 78, col, stroke=6); y += 118
        qp._t(d, (LW//2, LH-90), "COMMENT YOUR SCORE + RANK BELOW", 60, YEL, stroke=6)
        im.save(path); return
    # LEFT cluster: round label + difficulty (difficulty placed dynamically right after the label so
    # they never collide with the RIGHT cluster). RIGHT cluster: score (far right) + points (left of it).
    rl_end = 50
    if round_label:
        rl_w = int(qp._font(60).getlength(round_label)) + 44
        _pill(d, [50, 34, 50 + rl_w, 138], (*NAVY, 255))
        qp._t(d, (72, 86), round_label, 60, WHITE, anchor="lm", stroke=6)
        rl_end = 50 + rl_w
    if difficulty:
        dc = _DIFF_COL.get(difficulty.lower(), YEL); lbl = difficulty.upper()
        bw = int(qp._font(50).getlength(lbl)) + 70; bx0 = rl_end + 24
        _pill(d, [bx0, 44, bx0 + bw, 128], (*dc, 255)); qp._t(d, (bx0 + bw//2, 86), lbl, 50, WHITE, stroke=5)
    top_x0 = LW - 50
    if score is not None:                                   # running MAX-possible ceiling (far right)
        lbl = f"TOP {score}"; bw = int(qp._font(58).getlength(lbl)) + 70
        top_x0 = LW - 50 - bw
        _pill(d, [top_x0, 34, LW - 50, 138], (*RED, 255)); qp._t(d, (top_x0 + bw//2, 86), lbl, 58, WHITE, stroke=5)
    if points is not None:                                   # points at stake, just left of the score
        lbl = f"WORTH {points}"; bw = int(qp._font(52).getlength(lbl)) + 70; wx1 = top_x0 - 24
        _pill(d, [wx1 - bw, 40, wx1, 132], (*YEL, 255)); qp._t(d, (wx1 - bw//2, 86), lbl, 52, NAVY, stroke=0)
    if question:
        bw = int(qp._font(72).getlength(question)) + 120
        _pill(d, [LW//2 - bw//2, LH-186, LW//2 + bw//2, LH-70], (*NAVY, 255), outline=(*CYAN, 255), w=5)
        qp._t(d, (LW//2, LH-128), question, 72, WHITE, stroke=6)
    if cd_left is not None:                                  # 3-segment timer bar across the bottom
        segw = (LW - 600) // 3; y0 = LH - 56
        for k in range(3):
            x0 = 300 + k*segw + 8; col = CYAN if k < cd_left else (60, 66, 84)
            _pill(d, [x0, y0, x0 + segw - 16, y0 + 40], (*col, 255), outline=(*NAVY, 255), w=4, radius=14)
    if answer:
        big = answer.upper() + "!"; bw = int(qp._font(104).getlength(big)) + 140
        _pill(d, [LW//2 - bw//2, LH-230, LW//2 + bw//2, LH-96], (*NAVY, 255), outline=(*CYAN, 255), w=6)
        qp._t(d, (LW//2, LH-163), big, 104, CYAN, stroke=8)
        if got_pts is not None:
            qp._t(d, (LW//2, LH-56), f"+{got_pts} IF YOU GOT IT", 54, GREEN, stroke=5)
    im.save(path)


def _lf_motion(clean_img, textpng, out, d, motion, i2v_sink=None):
    """Landscape Kling-animated hero clip (cold open / outro), text overlaid; Ken-Burns fallback."""
    raw = out + ".raw.mp4"
    try:
        if os.path.exists(raw): os.remove(raw)
    except OSError: pass
    ok = False
    try:
        ok, _, _ = ep._animate_one("fal", clean_img, motion, raw, LW, LH, 5)
    except Exception:
        ok = False
    was_i2v = bool(ok) and os.path.exists(raw)
    if i2v_sink is not None:
        i2v_sink.append(was_i2v)
    if not was_i2v:
        subprocess.run([FF, "-y", "-loop", "1", "-i", clean_img, "-t", f"{d}", "-vf",
            f"scale=2200:-1,zoompan=z='min(zoom+0.0009,1.2)':d={int(d*FPS)}:s={LW}x{LH},fps={FPS},format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", raw], capture_output=True)
    # The i2v (Kling) raw is ~5s, but the narration slot `d` can be longer (cold-open/outro VO). Freeze
    # the last frame (tpad) to fill the FULL d so the clip length == the audio offset accounting — else
    # the video ends up shorter than the audio and everything drifts out of sync.
    raw_dur = qp._dur(raw) or d
    pad = max(0.0, d - raw_dur)
    subprocess.run([FF, "-y", "-i", raw, "-i", textpng, "-filter_complex",
        f"[0:v]scale={LW}:{LH}:force_original_aspect_ratio=increase,crop={LW}:{LH},"
        f"tpad=stop_mode=clone:stop_duration={pad:.3f},fps={FPS}[v];"
        "[v][1:v]overlay=0:0,format=yuv420p[o]", "-map", "[o]", "-an", "-t", f"{d}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", out], capture_output=True)
    return d


STY_L = " Polished 3D cartoon, vibrant, high production value, landscape 16:9, no text or letters."
CDN = 0.9                                                     # per-tick; 0.9*3 = 2.7s countdown
_NUMWORD = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
            "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen"]


def run_longform_quiz_pipeline(theme: str, output_dir: str, n_rounds: int = 12, voice: str = "echo",
                               progress_cb=None, quiz: dict | None = None, operator_direction: str = "") -> dict:
    """Render a landscape long-form quiz GAME. Returns an explainer-shaped dict so the app's save path
    consumes it unchanged. Pass `quiz` to render a pre-generated (e.g. audited) quiz instead of
    generating fresh — it must carry rounds[] (with n/difficulty/points), max_score, grade_tiers."""
    def log(m):
        if progress_cb: progress_cb(m)
    output_dir = os.path.abspath(output_dir)   # absolute so ffmpeg concat lists never double the path
    os.makedirs(output_dir, exist_ok=True)
    A = output_dir; costs = []
    if quiz is None:
        log("stage:Writing quiz...")
        quiz = generate_longform_quiz(theme, n_rounds, cost_sink=costs, operator_direction=operator_direction)
        if not quiz or not quiz.get("rounds"):
            raise RuntimeError("long-form quiz generation failed")
        quiz, fixes = qp.factcheck_quiz(quiz, cost_sink=costs)     # reads quiz['items'] (aliased to rounds)
        if fixes: log(f"Fact-check corrected {len(fixes)} answer(s)")
    else:
        log("stage:Rendering pre-generated quiz...")
        quiz.setdefault("items", quiz.get("rounds"))
    rounds = quiz["rounds"]; title = ep._s(quiz.get("title")) or f"Can You Name All {len(rounds)} {theme}?"
    max_score = quiz["max_score"]; tiers = quiz["grade_tiers"]
    log(f"Long-form quiz: \"{title}\" — {len(rounds)} rounds, max {max_score} pts")

    mascot = [ep.MASCOT_REF] if os.path.exists(ep.MASCOT_REF) else None
    BOLT = ("Use the attached reference image: keep Bolt the rounded matte-white robot with mint-green "
            "accents. ")
    navy_base = f"{A}/_navy.png"; Image.new("RGB", (LW, LH), NAVY).save(navy_base)

    log("stage:Generating images & voiceover...")
    _safe = qp._safe_image
    _safe(BOLT + "Bolt on a colorful glowing game-show quiz stage, arms wide presenting, big glowing "
          "question marks, spotlights and confetti, energetic." + STY_L, f"{A}/open.png", "1536x1024", costs,
          reference_paths=mascot)
    _safe(BOLT + "Bolt cheering with two thumbs up on the game-show stage, confetti bursting, "
          "celebratory." + STY_L, f"{A}/outro.png", "1536x1024", costs, reference_paths=mascot)
    _lf_fit(f"{A}/open.png", f"{A}/open_b.png", "fit"); _lf_fit(f"{A}/outro.png", f"{A}/outro_b.png", "fit")

    clips = []; audio = []; caps = []; chapters = []; t = 0.0; i2v_flags = []

    def _tts(txt, name):
        p = f"{A}/{name}.mp3"; ep.generate_tts(txt, p, voice=voice); return p

    # COLD OPEN
    cold = ep._s(quiz.get("cold_open")) or f"How many {theme} can you name? Keep score — it gets brutal."
    n_open = _tts(cold, "n_open")
    _lf_overlay(f"{A}/open_t.png", round_label="KEEP SCORE!", score=max_score)
    od = qp._dur(n_open) + 0.5
    _lf_motion(f"{A}/open_b.png", f"{A}/open_t.png", f"{A}/c00.mp4", od,
               "the robot host sweeps an arm to present the game, confetti drifts, lights pulse", i2v_sink=i2v_flags)
    clips.append(f"{A}/c00.mp4"); audio.append((n_open, t, "narr")); caps.append((t, qp._dur(n_open), cold))
    chapters.append((0.0, "Intro")); t += od

    run_possible = 0
    prev_diff = None
    for it in rounds:
        i = it["n"]; diff = it["difficulty"]; pts = it["points"]; run_possible += pts
        rtype = ep._s(it.get("round_type")).lower() if ep._s(it.get("round_type")).lower() in _ROUND_VERB else "silhouette"
        col = qp._COLORS.get(ep._s(it.get("color")).strip().lower(), (40, 90, 140))
        # CHAPTER card at each new difficulty tier
        if diff != prev_diff:
            _lf_overlay(f"{A}/ch{i}.png", chapter=f"{diff} round")
            qp._composite(navy_base, f"{A}/ch{i}.png", f"{A}/ch{i}_c.png")
            qp._still(f"{A}/ch{i}_c.png", f"{A}/cch{i}.mp4", 1.4)
            clips.append(f"{A}/cch{i}.mp4"); chapters.append((t, f"{diff.title()} Round")); t += 1.4
            prev_diff = diff
        # CLUE + QUESTION
        clue = f"{A}/clue{i}.png"; rev = f"{A}/rev{i}.png"
        if qp.is_silhouette_clue(it.get("clue_visual"), rtype):
            # "name it from the shadow" → a TRUE black silhouette (else the vibrant style gives it away);
            # pad the frame with the same bright bg so it reads as one seamless panel
            col = qp.make_silhouette_clue(ep._s(it.get("clue_visual")), clue, "1536x1024", costs, idx=i)
        else:
            _safe(ep._s(it.get("clue_visual")) + ", centered with margin on a flat bright background, bold "
                  "clean shape, no text." + STY_L, clue, "1536x1024", costs)
        _safe(ep._s(it.get("reveal_visual")) + ", centered on a clean solid background, appealing, sharp." + STY_L,
              rev, "1536x1024", costs, fallback_label=ep._s(it.get("answer")))
        _lf_fit(clue, f"{A}/clue{i}_b.png", "pad", bg=col); _lf_fit(rev, f"{A}/rev{i}_b.png", "fit")
        qtxt = f"Round {_NUMWORD[i] if i < len(_NUMWORD) else i}. {_ROUND_VERB[rtype]}"
        n_q = _tts(qtxt, f"n_q{i}")
        _lf_overlay(f"{A}/q{i}_t.png", round_label=f"ROUND {i}", difficulty=diff, points=pts,
                    score=run_possible, question="WHAT IS IT?")
        qp._composite(f"{A}/clue{i}_b.png", f"{A}/q{i}_t.png", f"{A}/q{i}.png")
        dq = qp._dur(n_q) + 0.4
        qp._still(f"{A}/q{i}.png", f"{A}/cq{i}.mp4", dq); clips.append(f"{A}/cq{i}.mp4")
        audio.append((n_q, t, "narr")); caps.append((t, qp._dur(n_q), qtxt)); t += dq
        # COUNTDOWN (over the clue)
        audio.append(("CD", t, "cd"))
        for k in (3, 2, 1):
            _lf_overlay(f"{A}/cd{i}_{k}_t.png", round_label=f"ROUND {i}", difficulty=diff, points=pts,
                        score=run_possible, cd_left=k)
            qp._composite(f"{A}/clue{i}_b.png", f"{A}/cd{i}_{k}_t.png", f"{A}/cd{i}_{k}.png")
            qp._still(f"{A}/cd{i}_{k}.png", f"{A}/ccd{i}_{k}.mp4", CDN); clips.append(f"{A}/ccd{i}_{k}.mp4")
        t += CDN * 3
        # REVEAL
        react = ep._s(it.get("reaction")) or "Nice!"; ans = ep._s(it.get("answer"))
        rtxt = f"{ans}! {react}"; n_r = _tts(rtxt, f"n_r{i}")
        _lf_overlay(f"{A}/r{i}_t.png", answer=ans, got_pts=pts, score=run_possible)
        qp._composite(f"{A}/rev{i}_b.png", f"{A}/r{i}_t.png", f"{A}/r{i}.png")
        dr = qp._dur(n_r) + 0.5
        qp._still(f"{A}/r{i}.png", f"{A}/cr{i}.mp4", dr); clips.append(f"{A}/cr{i}.mp4")
        audio.append((n_r, t, "narr")); audio.append(("DING", t, "ding")); caps.append((t, qp._dur(n_r), rtxt)); t += dr

    # GRADE (self-score rank ladder)
    gtxt = "Now add up your points. How did you rank?"
    n_g = _tts(gtxt, "n_grade")
    _lf_overlay(f"{A}/grade_t.png", grade={"max": max_score, "tiers": tiers})
    qp._composite(navy_base, f"{A}/grade_t.png", f"{A}/grade_c.png")
    dg = qp._dur(n_g) + 2.6                                    # hold so viewers can read + tally
    qp._still(f"{A}/grade_c.png", f"{A}/cgrade.mp4", dg); clips.append(f"{A}/cgrade.mp4")
    audio.append((n_g, t, "narr")); caps.append((t, qp._dur(n_g), gtxt)); chapters.append((t, "Your Rank")); t += dg

    # OUTRO
    outro = ep._s(quiz.get("outro")) or "Drop your score in the comments — and subscribe for a new quiz."
    n_o = _tts(outro, "n_outro")
    _lf_overlay(f"{A}/outro_t.png", round_label="YOUR SCORE?", question="COMMENT IT BELOW")
    oo = qp._dur(n_o) + 0.5
    _lf_motion(f"{A}/outro_b.png", f"{A}/outro_t.png", f"{A}/c99.mp4", oo,
               "the robot host cheers with a thumbs up, confetti bursts", i2v_sink=i2v_flags)
    clips.append(f"{A}/c99.mp4"); audio.append((n_o, t, "narr")); caps.append((t, qp._dur(n_o), outro)); t += oo
    TOTAL = t

    # captions/transcript (deterministic from the narration timeline)
    def _srt_ts(s):
        s = max(0.0, s); h = int(s//3600); m = int((s % 3600)//60); sec = int(s % 60); ms = int(round((s-int(s))*1000))
        if ms == 1000: sec += 1; ms = 0
        return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"
    srt_path = f"{A}/captions.srt"; transcript_path = f"{A}/transcript.txt"
    try:
        cs = sorted(caps, key=lambda c: c[0])
        with open(srt_path, "w") as f:
            for n, (st, du, txt) in enumerate(cs, 1):
                f.write(f"{n}\n{_srt_ts(st)} --> {_srt_ts(st+max(0.7, du))}\n{txt.strip()}\n\n")
        open(transcript_path, "w").write(" ".join(c[2].strip() for c in cs) + "\n")
    except Exception as e:
        log(f"caption write skipped: {e}"); srt_path = transcript_path = None

    log("stage:Assembling final video...")
    lst = f"{A}/list.txt"; open(lst, "w").write("".join(f"file '{c}'\n" for c in clips))
    vsil = f"{A}/video_silent.mp4"
    subprocess.run([FF, "-y", "-f", "concat", "-safe", "0", "-i", lst, "-an", "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30", vsil], capture_output=True)
    cdsfx = f"{A}/cdsfx.wav"
    subprocess.run([FF, "-y", "-filter_complex",
        "sine=1000:d=0.06,adelay=0|0[a];sine=1000:d=0.06,adelay=900|900[b];sine=1300:d=0.09,adelay=1800|1800[c];"
        "[a][b][c]amix=inputs=3:normalize=0,volume=2,atrim=0:2.7[o]", "-map", "[o]", cdsfx], capture_output=True)
    ding = f"{A}/ding.wav"
    subprocess.run([FF, "-y", "-filter_complex", "sine=1600:d=0.25,volume=1.5[o]", "-map", "[o]", ding], capture_output=True)
    ins = []; parts = []; idx = 0
    for f, off, kind in audio:
        src = cdsfx if kind == "cd" else (ding if kind == "ding" else f)
        ins += ["-i", src]; ms = int(off*1000); vol = 1.0 if kind == "narr" else 0.7
        parts.append(f"[{idx}:a]adelay={ms}|{ms},volume={vol}[s{idx}]"); idx += 1
    mus = idx; music_ok = os.path.exists(MUSIC)
    if music_ok:
        ins += ["-stream_loop", "-1", "-i", MUSIC]
        parts.append(f"[{mus}:a]atrim=0:{TOTAL},volume=0.09,afade=t=out:st={max(0,TOTAL-1.3):.2f}:d=1.3[mus]")
    mix = "".join(f"[s{i}]" for i in range(idx)) + ("[mus]" if music_ok else "")
    parts.append(f"{mix}amix=inputs={idx+(1 if music_ok else 0)}:normalize=0,alimiter=limit=0.95,loudnorm=I=-12:TP=-1.5,aresample=48000[aout]")   # target -12: single-pass undershoots ~2 LU -> lands ~-14
    faud = f"{A}/full_audio.m4a"
    subprocess.run([FF, "-y", *ins, "-filter_complex", ";".join(parts), "-map", "[aout]", "-t", f"{TOTAL}",
                    "-c:a", "aac", "-b:a", "192k", faud], capture_output=True)
    out_mp4 = os.path.join(output_dir, "explainer.mp4")
    subprocess.run([FF, "-y", "-i", vsil, "-i", faud, "-c:v", "copy", "-c:a", "aac", "-shortest",
                    "-movflags", "+faststart", out_mp4], capture_output=True)

    log("stage:Writing description...")
    description_path = _lf_desc(title, theme, rounds, max_score, tiers, chapters, A, cost_sink=costs)
    cost = round(sum(costs), 3)
    _n_fb = i2v_flags.count(False)
    _deg = ([f"{_n_fb} of {len(i2v_flags)} hero clips (cold-open/outro) fell back to a static Ken-Burns still"]
            if _n_fb else [])
    if not os.path.exists(out_mp4):
        _deg = ["final video file was not produced — assembly failed"] + _deg
    log(f"Complete — long-form quiz assembled · {len(rounds)} rounds · {TOTAL:.0f}s · ${cost}"
        + (f" · {_n_fb} static fallback(s)" if _n_fb else ""))
    return {"output_path": out_mp4, "title": title, "category": theme, "scene_count": len(clips),
            "duration_sec": round(qp._dur(out_mp4), 1), "video_format": "landscape",
            "items": [{"answer": r.get("answer"), "fact": r.get("fact")} for r in rounds],
            "script": quiz, "hook": ep._s(quiz.get("cold_open")),
            "srt_path": srt_path, "transcript_path": transcript_path, "description_path": description_path,
            "status": ("degraded" if _deg else "ok"), "degraded_reasons": _deg,
            "actual_cost": cost, "est_cost": cost}


def _lf_desc(title, theme, rounds, max_score, tiers, chapters, out_dir, cost_sink=None) -> str:
    """Long-form quiz description: hook + how-to-score + CHAPTERS + rank tiers + comment CTA + tags."""
    try:
        def ts(s):
            m = int(s // 60); sec = int(s % 60); return f"{m}:{sec:02d}"
        chap_lines = "\n".join(f"{ts(cs)} {tt}" for cs, tt in chapters)
        tier_lines = "\n".join(f"{lo}+ points → {rank}" for lo, rank in tiers)
        answers = ", ".join(ep._s(r.get("answer")) for r in rounds)
        usr = (f'Title: "{title}". Theme: {theme}. {len(rounds)} rounds, max {max_score} points, easy to '
               f'expert. Answers (for the TAGS only, do NOT list them in the body): {answers}.\n'
               "Write ONLY a JSON object: {\"body\":\"2 short paragraphs — para 1 dares the viewer to play "
               "and KEEP SCORE and warns it gets brutal; para 2 explains harder rounds are worth more "
               "points and to comment their score+rank. Do NOT reveal answers.\",\"hashtags\":[5-6 without "
               "#],\"tags\":[15-18: 5 exact-premise, 5 challenge/content + the theme, 3 subject-category, "
               "2-4 LONG-FORM format tags like 'quiz game','trivia challenge','guess the animal' — NOT "
               "'shorts']}.")
        r = ep._claude().messages.create(model="claude-opus-4-8", max_tokens=1600,
            system="You are a YouTube long-form quiz packaging editor. Vivid, direct 2nd-person, no fluff.",
            messages=[{"role": "user", "content": usr}])
        if cost_sink is not None:
            cost_sink.append(ep._msg_cost(r.usage))
        o, _ = ep._parse_script_json(r.content[0].text)
        parts = [ep._s(o.get("body")).strip() or f"How many {theme} can you name? Play along and keep score."]
        parts.append("⏱️ CHAPTERS\n" + chap_lines)
        parts.append("🏆 YOUR RANK\n" + tier_lines)
        parts.append("Comment your score and rank below — and subscribe for a new quiz.")
        hashtags = [ep._s(h).strip().lstrip("#").strip() for h in (o.get("hashtags") or []) if ep._s(h).strip()]
        if hashtags: parts.append(" ".join("#" + h.replace(" ", "") for h in hashtags[:6]))
        tags = [ep._s(x).strip() for x in (o.get("tags") or []) if ep._s(x).strip()]
        if tags: parts.append("Tags: " + ", ".join(tags[:18]))
        parts.append(ep._DESC_DISCLOSURE)
        path = os.path.join(out_dir, "description.txt")
        open(path, "w").write("\n\n".join(parts) + "\n")
        return path
    except Exception as e:
        print(f"[lfquiz] desc skipped: {e}")
        return ""

