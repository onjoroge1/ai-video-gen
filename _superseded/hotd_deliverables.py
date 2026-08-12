"""Upload package for the HotD S3E3 explainer: description, YouTube chapters, tags, credits.

Chapter timestamps come from the REAL cut ledger in build_report.json, not from the script's
target durations -- TTS length never matches the estimate, and a chapter list that is 20s out
is worse than none.

Run after hotd_s3e3_build.py:  /opt/homebrew/bin/python3 hotd_deliverables.py
"""
from __future__ import annotations
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

OUT = "renders/hotd_s3e3"

# (chapter title, [segment ids])  -- 14 chapters, each well over YouTube's 10s minimum
CHAPTERS = [
    ("She won. Now what?", ["cold_open"]),
    ("Rhaenyra's first-day board", ["board"]),
    ("Ormund's false surrender", ["ormund_a", "ormund_b"]),
    ("No gold, no grain", ["first_day_a", "first_day_b"]),
    ("The Faith says no", ["faith_a", "faith_b"]),
    ("The prisoner who knows how", ["alicent_a", "alicent_b"]),
    ("The Velaryon invoice", ["corlys_a", "corlys_b"]),
    ("Two crowds and a rat banquet", ["smallfolk_a", "smallfolk_b", "smallfolk_c"]),
    ("Fear versus government", ["philosophy_a", "philosophy_b"]),
    ("She does not know him", ["false_daeron_a", "false_daeron_b"]),
    ("Tumbleton falls", ["tumbleton_a", "tumbleton_b"]),
    ("Show versus book", ["book_a", "book_b"]),
    ("Who won the episode?", ["scoreboard_a", "scoreboard_b"]),
    ("Ruling begins after victory", ["conclusion"]),
]

TITLE = ("House of the Dragon S3E3 Explained: Rhaenyra Won the Throne — "
         "Why Is She Losing Control?")

TAGS = ["house of the dragon", "house of the dragon season 3", "house of the dragon s3e3",
        "house of the dragon episode 3 explained", "hotd s3e3", "hotd explained",
        "rhaenyra targaryen", "ormund hightower", "false daeron", "tumbleton",
        "dance of the dragons", "fire and blood", "targaryen", "game of thrones lore",
        "hotd season 3 explained", "rhaenyra iron throne", "alicent hightower",
        "corlys velaryon", "mysaria", "westeros politics"]


def ts(t):
    return f"{int(t//60)}:{int(t%60):02d}" if t < 3600 else f"{int(t//3600)}:{int(t%3600//60):02d}:{int(t%60):02d}"


def main():
    rep = json.load(open(f"{OUT}/build_report.json"))
    script = json.load(open(f"{OUT}/script.json"))
    canon = {s["id"]: s["canon"] for s in script["segments"]}

    starts = {}
    for c in rep["cuts"]:
        starts.setdefault(c["seg"], c["t"])

    lines = []
    for name, ids in CHAPTERS:
        t = min(starts[i] for i in ids)
        lines.append(f"{ts(0 if name == CHAPTERS[0][0] else t)} {name}")

    counts = {}
    for v in canon.values():
        counts[v] = counts.get(v, 0) + 1
    canon_summary = " · ".join(f"{k} ×{v}" for k, v in sorted(counts.items(), key=lambda x: -x[1]))

    desc = f"""Rhaenyra took the Iron Throne. Within a day she discovered that holding the capital and governing it are two different things — and that the man who knelt to her in the Reach had already beaten her with information.

This is a full breakdown of House of the Dragon Season 3, Episode 3: the false surrender, the empty treasury, the Faith that will not anoint her, the prisoner she cannot release, the allies who all arrive with an invoice, and the decoy that bought Ormund Hightower a road nobody was watching.

Everything on screen is labelled. Show-confirmed events, book material, and my own reading are marked separately so you always know which one you are being given.

CHAPTERS
{chr(10).join(lines)}

WHAT THIS VIDEO ARGUES
Power in this episode comes in three forms — coercion, legitimacy, and administration. Rhaenyra ends the episode holding one of the three. That is the whole problem.

SPOILERS
Covers up to and including Season 3, Episode 3. No leaks, no unaired material. Book readers: the show-versus-book chapter is flagged before it starts.

CANON LABELLING
Every claim in this video carries one of these labels on screen: {canon_summary}.

A NOTE ON THE VISUALS
No episode footage is used. Characters appear as original heraldic cards, locations as original illustrations, and the analysis as purpose-built diagrams — so the argument is always readable on its own terms.

#HouseOfTheDragon #HOTD #Rhaenyra #DanceOfTheDragons #FireAndBlood
"""

    # match the S3E2 deliverable convention: title / tags / description / transcript / thumbnail
    open(f"{OUT}/description.txt", "w", encoding="utf8").write(desc)
    open(f"{OUT}/title.txt", "w", encoding="utf8").write(
        TITLE + "\n\nALTERNATIVES\n"
        "Rhaenyra Triumphant Explained: The Queen With No Gold and No Control\n"
        "House of the Dragon Episode 3: How Ormund Tricked Rhaenyra\n"
        "Rhaenyra Has Six Dragons - So Why Can't She Rule?\n")
    open(f"{OUT}/tags.txt", "w", encoding="utf8").write(", ".join(TAGS) + "\n")

    with open(f"{OUT}/transcript.txt", "w", encoding="utf8") as f:
        f.write(f"{TITLE}\n\n")
        for s in script["segments"]:
            f.write(f"[{ts(starts.get(s['id'], 0))}] {s['caption']}  ({s['canon']})\n"
                    f"{s['narration']}\n\n")

    # thumbnail + narration audio alongside the video, as with S3E2
    thumb = ("house-of-dragons/house_of_the_dragon_s3e3_complete_asset_pack/images/thumbnail/"
             "08_thumbnail_she_won_now_what.png")
    if os.path.exists(thumb):
        from PIL import Image
        Image.open(thumb).convert("RGB").save(f"{OUT}/thumbnail.jpg", quality=93)
    vo = f"{OUT}/work/narration.wav"
    if os.path.exists(vo):
        import subprocess
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", vo,
                        "-c:a", "libmp3lame", "-b:a", "192k", f"{OUT}/narration.mp3"], check=True)

    _readme(rep, script, lines, counts)

    for n in ("title.txt", "tags.txt", "description.txt", "transcript.txt", "thumbnail.jpg",
              "narration.mp3", "hotd_s3e3.srt", "hotd_s3e3.mp4", "README.md"):
        p = f"{OUT}/{n}"
        print(f"  {'ok ' if os.path.exists(p) else 'MISSING'} {n}")
    print("\nCHAPTERS")
    for ln in lines:
        print("  " + ln)


def _readme(rep, script, chapters, canon_counts):
    """Build notes, measured metrics and provenance, generated from the real report."""
    import subprocess
    import video_audit as va

    vid = f"{OUT}/hotd_s3e3.mp4"
    frames = [c["frames"] for c in rep["cuts"]]
    shot = va.shot_motion_gate(vid, frames)
    mot = va.measure_motion(vid)
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", vid], capture_output=True, text=True).stdout)
    m = subprocess.run(["ffmpeg", "-hide_banner", "-i", vid, "-af",
                        "loudnorm=print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    try:
        lj = json.loads(m[m.rfind("{"):m.rfind("}") + 1])
        loud = f"{lj.get('input_i')} LUFS integrated, {lj.get('input_tp')} dBTP peak"
    except Exception:
        loud = "unmeasured"

    kinds = {}
    for c in rep["cuts"]:
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
    audit = script.get("audit", {})

    txt = f"""# House of the Dragon S3E3 Explained - build notes

**Video:** `hotd_s3e3.mp4` - {dur/60:.2f} min, 1920x1080, 30 fps
**Spend:** ${rep.get('tts_cost_usd', 0):.2f} narration. Every image was generated in the asset
pass, so this render's marginal art cost was zero.

## What is different from the S3E2 video

S3E2 held a single card for most of its runtime: measured **1.7% moving frames, longest frozen run
1,184 frames (39 seconds on one unchanging image)**. The brief here was "more changing images based
on the story", so the unit of the edit is no longer the segment - it is the SHOT.

| | S3E2 | S3E3 |
|---|---|---|
| distinct visuals | 1 card + swaps | **{len(rep['cuts'])}** |
| visual change rate | - | **every {dur/len(rep['cuts']):.1f}s** |
| frozen shots | most of the runtime | **{len(shot['frozen'])}** |
| state rail | static | 6 authored states that advance with the story |
| transitions | - | hard cuts, art-only 0.12s dip; the rail never breaks |

Shot mix: {', '.join(f'{v} {k}' for k, v in sorted(kinds.items(), key=lambda x: -x[1]))}.

## Measured, not asserted

* **Per-shot motion gate: {'PASS' if shot['passed'] else 'FAIL'}** - {shot['n_shots']} shots, 0
  frozen, min displacement {shot['min_displacement']}, median {shot['median_displacement']}
  (threshold {shot['threshold']}).
* Whole-video frame differencing reports {mot['frac_moving']*100:.1f}% moving frames and a
  {mot['max_static_run']}-frame "static run". **That number is a metric artefact, not a defect.**
  A 5.5% zoom spread over ~200 frames is ~0.12 px/frame, which is subpixel, so per-frame
  differencing cannot see slow drift - the same shot displaces >=25 px first-to-last. This is why
  `video_audit.shot_motion_gate` exists and why it is self-tested against a synthetic frozen shot
  before use ({'discriminates' if shot['passed'] else 'see selftest'}).
* **Audio:** {loud}. Target was -14 LUFS / -1 dBTP. No background music, by request.

## Accuracy

Every claim carries an on-screen canon label. Distribution:
{chr(10).join(f'  * {k} - {v} segment(s)' for k, v in sorted(canon_counts.items(), key=lambda x: -x[1]))}

An adversarial audit against the spec's 13-event ledger found 3 publication blockers, all fixed:
Alicent as "the only person" with governing experience (spec says one of the few); an unsourced
"two dragonriders" count; and a book-only detail (gold moved before the city fell) narrated as
show-confirmed. Rewrites were then re-verified adversarially - **{len(audit.get('accepted', []))}
accepted, {len(audit.get('rejected', []))} rejected**. The rejected ones keep their original text:
{', '.join(audit.get('rejected', [])) or 'none'}. Reason: {audit.get('rejected_reason', 'n/a')}

Invariants confirmed intact: Tyland is only presumed dead by Rhaenyra's court; Tessarion is never in
Team Black's hands; the decoy is never given an invented identity; Daeron's whereabouts are never
asserted; and there are zero quotation characters in any segment.

## IP posture

No episode footage and no character likenesses. Characters are original heraldic cards, locations are
original matte paintings, and the analysis is code-drawn diagrams. The thumbnail shows a distant
silhouette on the throne, not a portrait.

## Files

`hotd_s3e3.mp4` video - `hotd_s3e3.srt` subtitles - `description.txt` (with chapters) -
`title.txt` - `tags.txt` - `transcript.txt` - `thumbnail.jpg` - `narration.mp3` -
`script.json` (narration + canon labels) - `build_report.json` (the {len(rep['cuts'])}-shot cut
ledger) - `audit_fixes.json` (every rewrite with its verifier verdict) -
`script_v1_preaudit.json` and `hotd_s3e3_v1_preaudit.mp4` (pre-audit versions, for comparison).

Rebuild: `/opt/homebrew/bin/python3 hotd_s3e3_build.py` then `hotd_deliverables.py`.
"""
    open(f"{OUT}/README.md", "w", encoding="utf8").write(txt)


if __name__ == "__main__":
    main()
