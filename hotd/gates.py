"""Every deterministic check for a HotD episode, in one place, and all of them RAISE.

The previous flow printed its checks and relied on a human reading the log. That is how an
"EPISODE 3 -- THE STRATEGIC PICTURE" card reached the finished Episode 4 video: the reuse was
visible in the build output and nobody was required to act on it.

Rule of thumb encoded here: anything a machine can decide, a machine decides, and a violation stops
the build. Anything needing judgment (is the prose good, is the reading fair) stays with a human or
a model and is NOT pretended to be checked here.

    from hotd import gates
    gates.preflight(ep, script)      # before any render, before any spend
    gates.postflight(ep, report)     # on the finished mp4
"""
from __future__ import annotations
import re
import json
import os
import subprocess

# The permitted label vocabulary is a property of the EPISODE'S SPEC, not of the pipeline. S3E4's
# spec §1.5 mandates a closed set of six; S3E3's did not, and its shipped video legitimately uses
# compound labels. An episode overrides this via Episode.canon_labels.
CANON_LABELS = {"SHOW CONFIRMED", "STRONG SHOW INFERENCE", "BOOK ACCOUNT", "SHOW CHANGE",
                "INTERPRETATION", "FUTURE BOOK SPOILER"}
# The bare phrase "this video" used to be a marker, and it caught legitimate editorial prose: a spec
# whose own narration reads "this video will not reveal what later happens there" is making a spoiler
# DISCLOSURE, which is the opposite of a call to action. The markers below are promotional
# constructions only, so transparency about scope stays allowed and self-promotion still fails.
CTA_MARKERS = ("subscribe", "like and", "comment below", "comment section", "let me know in",
               "hit the bell", "watch this video", "share this video", "in this video",
               "on this channel", "our channel", "the video below", "link in the")
QUOTE_CHARS = '"“”'
CAPTION_MAX_WORDS = 5
WORD_BAND = (1600, 2200)          # generous outer band; the spec's own band is per-episode
WPM = 162.0                       # measured for OpenAI tts-1-hd voice "echo"


class GateFailure(Exception):
    """A deterministic check failed. The build must not continue."""


def _fail(name, detail):
    raise GateFailure(f"[{name}] {detail}")


# --------------------------------------------------------------------------- script gates
def script_labels(script, allowed=None):
    allowed = allowed or CANON_LABELS
    bad = {}
    for s in script["segments"]:
        if s["canon"] not in allowed:
            bad.setdefault(s["canon"], []).append(s["id"])
    if bad:
        _fail("canon-labels", "labels outside this episode's permitted set:\n" +
              "\n".join(f"  {k!r} on {v}" for k, v in bad.items()))


def script_quotes(script):
    hits = [s["id"] for s in script["segments"]
            if any(c in s["narration"] for c in QUOTE_CHARS)]
    if hits:
        _fail("quotation-marks", f"dialogue must be reported indirectly; found quotes in {hits}")


def script_captions(script):
    long = [(s["id"], s["caption"]) for s in script["segments"]
            if len(s["caption"].split()) > CAPTION_MAX_WORDS]
    if long:
        _fail("caption-length", f"captions over {CAPTION_MAX_WORDS} words: {long}")
    empty = [s["id"] for s in script["segments"] if not s["caption"].strip()]
    if empty:
        _fail("caption-missing", f"segments with no caption: {empty}")


def script_cta(script):
    hits = [(s["id"], m) for s in script["segments"] for m in CTA_MARKERS
            if m in s["narration"].lower()]
    if hits:
        _fail("call-to-action", f"no CTA or self-reference in narration: {hits}")


def script_words(script, band=WORD_BAND):
    n = sum(len(s["narration"].split()) for s in script["segments"])
    if not band[0] <= n <= band[1]:
        _fail("word-count", f"{n} words outside {band[0]}-{band[1]}")
    return n


def script_target_s(script, wpm=WPM, tol=2):
    """target_s must reflect the voice we actually use, not the spec's assumed reading speed."""
    off = []
    for s in script["segments"]:
        want = round(len(s["narration"].split()) / wpm * 60)
        if abs(want - s.get("target_s", 0)) > tol:
            off.append((s["id"], s.get("target_s"), want))
    if off:
        _fail("target-s", f"target_s must be round(words/{wpm:g}*60) +/-{tol}s; wrong: {off[:8]}")


def script_ids_unique(script):
    seen, dup = set(), []
    for s in script["segments"]:
        if s["id"] in seen:
            dup.append(s["id"])
        seen.add(s["id"])
    if dup:
        _fail("duplicate-ids", f"segment ids repeat: {dup}")


# --------------------------------------------------------------------------- episode gates
def playlist_coverage(ep, script):
    ids = [s["id"] for s in script["segments"]]
    missing = [i for i in ids if i not in ep.playlists]
    if missing:
        _fail("playlist-missing", f"no shots for {missing}")
    unstated = [i for i in ids if i not in ep.seg_state]
    if unstated:
        _fail("rail-state-missing", f"no rail state for {unstated}")
    unknown = sorted({ep.seg_state[i] for i in ids} - set(ep.states))
    if unknown:
        _fail("rail-state-unknown", f"seg_state names a state that does not exist: {unknown}")


def playlist_openers(ep):
    """A segment's caption is drawn on its FIRST shot. Diagrams carry their own title and a stacked
    pair fills the frame, so neither can host a caption."""
    bad = [k for k, v in ep.playlists.items() if v and v[0][0] in ("full", "map", "cards")]
    if bad:
        _fail("playlist-opener", f"segments opening on a self-titled diagram or a card pair: {bad}")
    empty = [k for k, v in ep.playlists.items() if not v]
    if empty:
        _fail("playlist-empty", f"segments with no shots: {empty}")


MIN_ON_TOPIC = 0.75


def _windows(narration, weights, n):
    """Narration split into one slice per shot, proportional to that shot's screen time.

    TTS rate is near constant, so a word's position is a good proxy for when it is heard. Weights come
    from the beat planner; without them the split is even, which is what the fixed clock did.
    """
    words = re.findall(r"\S+", narration)
    if not words:
        return [""] * n
    w = weights if (weights and len(weights) == n and sum(weights) > 0) else [1.0] * n
    total, acc, out, prev = sum(w), 0.0, [], 0
    for x in w:
        acc += x
        cut = int(round(len(words) * acc / total))
        out.append(" ".join(words[prev:max(cut, prev + 1)]).lower())
        prev = cut
    return out


def shot_relevance(ep, script, subject_words, floor=MIN_ON_TOPIC, role_words=None):
    """Is the person on screen someone the narration is discussing WHILE they are on screen?

    This gate was written twice, and the first version measured the wrong thing. Scoring a shot
    against its whole segment reported 78% on a render whose images were visibly wrong, because a
    segment is ~20s covering 3-4 shots: the right cast in the right chapter still puts the wrong face
    on the wrong sentence. Scored against the words actually heard during each shot, the same render
    was 29%. The floor here applies to the per-window measure only.

    Only shots with a known subject are scored -- a diagram or a plate has no person to be wrong
    about.
    """
    if not subject_words:
        return None
    if role_words:                       # a portrait shown for "her Watch commander" is correct
        subject_words = {k: set(v) | set(role_words.get(k, ())) 
                         for k, v in list(subject_words.items()) + 
                         [(k, set()) for k in role_words if k not in subject_words]}
    seg = {s["id"]: s for s in script["segments"]}
    weights = getattr(ep, "shot_weights", None) or {}
    hit = miss = 0
    off = []
    for sid, shots in ep.playlists.items():
        s = seg.get(sid)
        if not s:
            continue
        wins = _windows(s.get("narration", ""), weights.get(sid), len(shots))
        for i, it in enumerate(shots):
            heard = wins[i] + " " + s.get("caption", "").lower()
            for name in (list(it[1]) if it[0] in ("cards", "figures") else [it[1]]):
                w = subject_words.get(name)
                if not w:
                    continue
                if any(x in heard for x in w):
                    hit += 1
                else:
                    miss += 1
                    off.append(f"{sid}#{i}:{name}")
    tot = hit + miss
    if not tot:
        return None
    rate = hit / tot
    if rate < floor:
        _fail("shot-relevance",
              f"only {hit}/{tot} ({rate:.0%}) of character shots show someone being discussed while "
              f"they are on screen; floor is {floor:.0%}. Worst: {off[:8]}")
    return {"on_topic": round(rate, 3), "scored": tot, "off_topic": off}


def caption_changes_picture(ep, script):
    """A segment's caption is drawn on its first shot, so the picture must change there.

    The pool cursor only forbids repeats WITHIN a segment, so it can hand a block's next segment the
    very shot it just ended on. The caption then swaps under a frame that never moves, which reads as
    a subtitle glitch rather than a new beat.
    """
    ids = [s["id"] for s in script["segments"] if s["id"] in ep.playlists]
    bad = [b for a, b in zip(ids, ids[1:])
           if ep.playlists[a] and ep.playlists[b] and ep.playlists[a][-1] == ep.playlists[b][0]]
    if bad:
        _fail("caption-static", f"segments whose first shot repeats the previous segment's last: {bad}")


def assets_resolve(ep):
    """Resolve every asset a playlist names, before rendering and before spending anything."""
    missing = []
    for sid, shots in ep.playlists.items():
        for it in shots:
            # a portrait comes from the supplied library, not the generated asset index, so only its
            # background plate is checked here
            names = [] if it[0] in ("figure", "figures") else (
                [it[1]] if isinstance(it[1], str) else list(it[1]))
            if it[0] in ("card", "cards", "figure", "figures"):
                names.append(it[-1])
            for n in names:
                if n not in ep.index():
                    missing.append((sid, n))
    if missing:
        _fail("asset-missing", f"{len(missing)} unresolved asset(s): {missing[:10]}")


def no_foreign_diagrams(ep):
    """Diagrams are titled with their episode number, so borrowing one from an earlier pack puts the
    wrong episode on screen. Locations, maps and heraldry are episode-neutral and travel freely.

    This is the check that would have caught the leaked Episode 3 strategic-picture card.
    """
    if getattr(ep, "allow_foreign_graphics", False):
        return
    own = os.path.abspath(ep.packs[-1])
    leaked = []
    for sid, shots in ep.playlists.items():
        for it in shots:
            names = [it[1]] if isinstance(it[1], str) else list(it[1])
            for n in names:
                if "graphic" in n and n in ep.index():
                    p = os.path.abspath(ep.asset(n))
                    if not p.startswith(own):
                        leaked.append((sid, n))
    if leaked:
        _fail("foreign-diagram",
              "episode-labelled diagram borrowed from an earlier pack (it will show the wrong "
              f"episode number on screen): {leaked}")


def shadowing_direction(ep):
    """When two packs define the same stem, the CURRENT episode must win. Getting this backwards
    silently shipped the previous episode's stale status cards."""
    own = os.path.abspath(ep.packs[-1])
    ep.index()
    wrong = [(n, win) for n, shadowed, win in ep.shadowed
             if os.path.abspath(shadowed).startswith(own)]
    if wrong:
        _fail("shadow-direction",
              f"an earlier pack overrode this episode's own asset: {[n for n, _ in wrong]}")
    return [n for n, _, _ in ep.shadowed]


def chapters_named(ep, script, block_of):
    """Every segment must land in exactly one chapter. Two models are supported: explicit
    chapter_groups [(title, [ids])], or one chapter per storyboard block via chapter_titles."""
    ids = [s["id"] for s in script["segments"]]
    if ep.chapter_groups:
        covered = [i for _, group in ep.chapter_groups for i in group]
        missing = [i for i in ids if i not in covered]
        if missing:
            _fail("chapter-unassigned", f"segments in no chapter: {missing}")
        dupes = sorted({i for i in covered if covered.count(i) > 1})
        if dupes:
            _fail("chapter-double", f"segments in more than one chapter: {dupes}")
        return
    blocks = {block_of(i) for i in ids}
    if None in blocks:
        _fail("block-unmapped",
              f"segments not mapped to any block: {[i for i in ids if block_of(i) is None]}")
    unnamed = sorted(b for b in blocks if b not in (ep.chapter_titles or {}))
    if unnamed:
        _fail("chapter-unnamed", f"blocks with no chapter title: {unnamed}")


# --------------------------------------------------------------------------- render gates
# Normalised boxes of the STATIC overlay per shot kind, taken from the render geometry
# (hotd.render CARD_W/CARD_Y, PAIR_W/PAIR_Y1/PAIR_Y2, CONTENT_W). These regions are meant to be
# motionless, so they are excluded when asking whether the shot moves.
# NOTE: these are for a LEFT content column (rail on the right). shots_move() mirrors them when the
# episode puts the rail on the left, or the gate would measure the wrong half of the frame.
_STATIC_BOX = {
    "card":  [(0.017, 0.143, 0.548, 0.673)],
    # the framed portrait panel plus the left rail are both intentionally motionless
    "figure": [(0.571, 0.231, 0.854, 0.824), (0.0, 0.0, 0.45, 1.0)],
    # An ensemble spans the whole picture area, so only the plate around it can move. The box has to
    # reach past the panels to the name plates and status pills below them (measured: static content
    # ends near y=0.87 for a two-up), or the gate marks deliberately-still type as a frozen shot.
    "figures": [(0.465, 0.235, 0.955, 0.885), (0.0, 0.0, 0.45, 1.0)],
    "cards": [(0.070, 0.051, 0.496, 0.480), (0.070, 0.505, 0.496, 0.935)],
}


def _mirror(boxes):
    return [(1.0 - x1, y0, 1.0 - x0, y1) for (x0, y0, x1, y1) in boxes]


def shots_move(video, frames, min_displacement=3.0, kinds=None, rail_side="right"):
    """No SHOT may be a still. Uses per-shot displacement, not per-frame differencing: a 5.5% zoom
    over 200 frames is subpixel per frame, so frame differencing cannot tell drift from a freeze.

    When `kinds` is given, the static overlay region for that shot kind is excluded, so the gate
    measures the part of the frame that is supposed to move.
    """
    import video_audit as va
    exclude = None
    if kinds:
        exclude = []
        for k in kinds:
            b = _STATIC_BOX.get(k, [])
            # the figure box already includes the left rail, so it is authored per side
            if rail_side == "left" and k in ("card", "cards"):
                b = _mirror(b)
            exclude.append(b)
    r = va.shot_motion_gate(video, frames, min_displacement=min_displacement, exclude=exclude)
    if not r["passed"]:
        _fail("frozen-shot",
              f"{len(r['frozen'])} shot(s) do not move: "
              f"{[(s['shot'], s['displacement']) for s in r['frozen'][:8]]}")
    return r


def loudness(video, target=-14.0, tol=1.5):
    m = subprocess.run(["ffmpeg", "-hide_banner", "-i", video, "-af",
                        "loudnorm=print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    try:
        j = json.loads(m[m.rfind("{"):m.rfind("}") + 1])
        i = float(j["input_i"])
        tp = float(j["input_tp"])
    except Exception as e:
        _fail("loudness", f"could not measure loudness: {e}")
    if abs(i - target) > tol:
        _fail("loudness", f"integrated {i} LUFS is more than {tol} from target {target}")
    if tp > -0.5:
        _fail("true-peak", f"true peak {tp} dBTP risks clipping")
    return {"integrated_lufs": i, "true_peak_dbtp": tp}


def duration(video, band_min):
    d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "csv=p=0", video], capture_output=True, text=True).stdout)
    lo, hi = band_min
    if not lo * 60 <= d <= hi * 60:
        _fail("duration", f"{d/60:.2f} min outside the {lo}-{hi} min target")
    return d


def rail_text_fits(ep):
    """No rail chip may have its role text truncated on screen.

    The board clips a chip's role to whatever space the tag pill leaves, and then says nothing. A
    finished video shipped with "Watching ab...", "Three co..." and "Worth more tha..." in the rail
    before anyone noticed. Re-deriving the chip geometry here would just create a second copy of the
    arithmetic to drift out of step -- two attempts at that both disagreed with the actual frame -- so
    this wraps board_pipeline._chip and records when its OWN truncation branch fires.
    """
    import tempfile

    import board_pipeline as bp

    clipped, orig, tw = [], bp._chip, bp._tw

    def spy(d, x, y, w, h, accent, c, changed):
        role = c.get("role", "")
        if role:
            pill_left = x + w - 12
            if c.get("tag"):
                pill_left -= tw(d, c["tag"], bp._F(bp._ARIAL_B, 16)) + 20
            if tw(d, role, bp._F(bp._ARIAL, 17)) > pill_left - 12 - (x + 22):
                clipped.append((spy.state, c["name"], role, c.get("tag")))
        return orig(d, x, y, w, h, accent, c, changed)

    # The state TITLE is not clipped, it simply runs out of the rail panel and over the picture. A
    # title 257px past the edge collided with the caption. _track returns the x it advanced to, so
    # wrapping it measures the real drawn width -- letter tracking included -- instead of estimating.
    titles, real_track = [], bp._track

    def track_spy(d, xy, text, fnt, fill, tr=0):
        end = real_track(d, xy, text, fnt, fill, tr)
        if text == spy.state_title and end > spy.rx:
            titles.append((spy.state, text, int(end - spy.rx)))
        return end

    bp._chip, bp._track = spy, track_spy
    try:
        tmp = tempfile.mkdtemp()
        RAIL_W = 688
        rail_x0 = 26 if getattr(ep, "rail_side", "right") == "left" else 1206
        for name, st in ep.states.items():
            spy.state = name
            spy.state_title = st.get("title", "STATE OF THE WAR")
            spy.rx = rail_x0 + RAIL_W - 40
            bp.render_board(st, os.path.join(tmp, "b.png"), 1920, 1080,
                            side=getattr(ep, "rail_side", "right"))
    finally:
        bp._chip, bp._track = orig, real_track
    if titles:
        _fail("rail-title", f"{len(titles)} rail title(s) overflow the panel into the picture; "
                            f"shorten them: " +
              "; ".join(f"[{n}] {t!r} +{x}px" for n, t, x in titles))
    if clipped:
        _fail("rail-text", f"{len(clipped)} rail chip role(s) are truncated on screen; shorten the "
                           f"role or the tag: " +
              "; ".join(f"[{s}] {n} role={r!r} tag={t!r}" for s, n, r, t in clipped[:8]))
    return {"chips_checked": sum(len(st[k]["chips"]) for st in ep.states.values()
                                 for k in ("left", "right"))}


def package_complete(out, slug):
    want = ["title.txt", "tags.txt", "description.txt", "transcript.txt", "thumbnail.jpg",
            "narration.mp3", f"{slug}.srt", f"{slug}.mp4", "README.md"]
    missing = [n for n in want if not os.path.exists(os.path.join(out, n))]
    if missing:
        _fail("package", f"missing deliverables: {missing}")


# --------------------------------------------------------------------------- entry points
def preflight(ep, script, block_of=None, word_band=WORD_BAND, strict_target_s=True,
              subject_words=None, role_words=None):
    """Everything checkable before a single frame is rendered or a single cent is spent."""
    script_ids_unique(script)
    script_labels(script, getattr(ep, "canon_labels", None))
    script_quotes(script)
    script_captions(script)
    script_cta(script)
    n = script_words(script, word_band)
    if strict_target_s:
        script_target_s(script)
    playlist_coverage(ep, script)
    playlist_openers(ep)
    caption_changes_picture(ep, script)
    assets_resolve(ep)
    no_foreign_diagrams(ep)
    rel = shot_relevance(ep, script, subject_words, role_words=role_words)
    rail = rail_text_fits(ep)
    shadowed = shadowing_direction(ep)
    if block_of is not None:
        chapters_named(ep, script, block_of)
    return {"words": n, "segments": len(script["segments"]),
            "shots": sum(len(v) for v in ep.playlists.values()),
            "shot_relevance": rel and rel["on_topic"],
            "rail_chips": rail["chips_checked"],
            "shadowed_by_this_episode": shadowed}


def postflight(ep, report, duration_band_min=None, check_package=False):
    """Everything checkable on the finished MP4.

    check_package is OFF by default: postflight runs before packaging, so demanding
    description.txt/README.md here fails every build. Call package_gate() after deliver().
    """
    video = os.path.join(ep.out, f"{ep.slug}.mp4")
    frames = [c["frames"] for c in report["cuts"]]
    kinds = [c.get("kind") for c in report["cuts"]]
    out = {"motion": shots_move(video, frames, kinds=kinds,
                                rail_side=getattr(ep, "rail_side", "right")),
           "audio": loudness(video)}
    if duration_band_min:
        out["duration_s"] = duration(video, duration_band_min)
    if check_package:
        package_complete(ep.out, ep.slug)
    return out


def package_gate(ep):
    """Run AFTER deliver(): the deliverables exist only once packaging has happened."""
    package_complete(ep.out, ep.slug)
    return True
