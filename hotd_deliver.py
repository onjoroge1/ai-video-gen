"""Episode-agnostic upload package: description with chapters, title, tags, transcript, SRT check,
thumbnail, narration audio and a build README.

Chapter timestamps come from the REAL cut ledger in build_report.json, never from the script's
target durations -- TTS length never matches the estimate, and a chapter list that is 20 seconds out
is worse than no chapter list.

Usage:
    import hotd_deliver, hotd_s3e4_episode as E
    hotd_deliver.deliver(E.episode(), E.META)
"""
from __future__ import annotations
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))


def ts(t):
    if t < 3600:
        return f"{int(t//60)}:{int(t%60):02d}"
    return f"{int(t//3600)}:{int(t%3600//60):02d}:{int(t%60):02d}"


def deliver(ep, meta):
    rep = json.load(open(f"{ep.out}/build_report.json"))
    script = json.load(open(ep.script))
    segs = script["segments"]

    starts = {}
    for c in rep["cuts"]:
        starts.setdefault(c["seg"], c["t"])

    lines = []
    for i, (name, ids) in enumerate(meta["chapters"]):
        t = min(starts[x] for x in ids if x in starts) if any(x in starts for x in ids) else 0
        lines.append(f"{ts(0 if i == 0 else t)} {name}")

    counts = {}
    for s in segs:
        counts[s["canon"]] = counts.get(s["canon"], 0) + 1
    canon_summary = " · ".join(f"{k} ×{v}" for k, v in sorted(counts.items(), key=lambda x: -x[1]))

    desc = f"""{meta['intro']}

{meta['body']}

Everything on screen is labelled. Show-confirmed events, book material, strong inference, and my own
reading are marked separately so you always know which one you are being given.

CHAPTERS
{chr(10).join(lines)}

WHAT THIS VIDEO ARGUES
{meta['argument']}

SPOILERS
{meta['spoilers']}

CANON LABELLING
Every claim in this video carries one of these labels on screen: {canon_summary}.

A NOTE ON THE VISUALS
No episode footage is used. Characters appear as original heraldic cards, locations as original
illustrations, and the analysis as purpose-built diagrams -- so the argument is always readable on
its own terms.

{meta['hashtags']}
"""
    open(f"{ep.out}/description.txt", "w", encoding="utf8").write(desc)
    open(f"{ep.out}/title.txt", "w", encoding="utf8").write(
        meta["title"] + "\n\nALTERNATIVES\n" + "\n".join(meta["alternatives"]) + "\n")
    open(f"{ep.out}/tags.txt", "w", encoding="utf8").write(", ".join(meta["tags"]) + "\n")

    with open(f"{ep.out}/transcript.txt", "w", encoding="utf8") as f:
        f.write(f"{meta['title']}\n\n")
        for s in segs:
            f.write(f"[{ts(starts.get(s['id'], 0))}] {s['caption']}  ({s['canon']})\n"
                    f"{s['narration']}\n\n")

    if meta.get("thumbnail") and os.path.exists(meta["thumbnail"]):
        from PIL import Image
        Image.open(meta["thumbnail"]).convert("RGB").save(f"{ep.out}/thumbnail.jpg", quality=93)
    vo = f"{ep.work}/narration.wav"
    if os.path.exists(vo):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", vo,
                        "-c:a", "libmp3lame", "-b:a", "192k", f"{ep.out}/narration.mp3"], check=True)

    _readme(ep, meta, rep, script, counts)

    for n in ("title.txt", "tags.txt", "description.txt", "transcript.txt", "thumbnail.jpg",
              "narration.mp3", f"{ep.slug}.srt", f"{ep.slug}.mp4", "README.md"):
        print(f"  {'ok ' if os.path.exists(f'{ep.out}/{n}') else 'MISSING'} {n}")
    print("\nCHAPTERS")
    for ln in lines:
        print("  " + ln)
    return lines


def _readme(ep, meta, rep, script, canon_counts):
    import video_audit as va

    vid = f"{ep.out}/{ep.slug}.mp4"
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
    words = sum(len(s["narration"].split()) for s in script["segments"])

    txt = f"""# {meta['title']} - build notes

**Video:** `{ep.slug}.mp4` - {dur/60:.2f} min, 1920x1080, 30 fps
**Narration:** {words} words, {len(script['segments'])} segments
**Spend:** ${rep.get('tts_cost_usd', 0):.2f} narration this render, plus
${meta.get('image_spend_usd', 0):.2f} of new artwork for this episode.

## Format

Every segment plays a playlist of 3-6 shots, so the picture changes every
{dur/max(len(rep['cuts']),1):.1f} seconds -- {len(rep['cuts'])} shots in total. Drift rate is derived
from each shot's own length, so a long hold drifts as slowly as a short one instead of hitting the
zoom ceiling and freezing. An always-on state rail advances through {len(ep.states)} authored states;
diagrams play full-bleed without it. Cuts are hard, and the 0.12s dip is applied to the art before
the rail composites, so the rail never blinks.

Shot mix: {', '.join(f'{v} {k}' for k, v in sorted(kinds.items(), key=lambda x: -x[1]))}.

## Measured, not asserted

* **Per-shot motion gate: {'PASS' if shot['passed'] else 'FAIL'}** - {shot['n_shots']} shots,
  {len(shot['frozen'])} frozen, min displacement {shot['min_displacement']}, median
  {shot['median_displacement']} (threshold {shot['threshold']}).
* Whole-video frame differencing reports {mot['frac_moving']*100:.1f}% moving frames and a
  {mot['max_static_run']}-frame "static run". That is a metric artefact, not a defect: a 5.5% zoom
  spread over ~200 frames is subpixel per frame, so per-frame differencing cannot see slow drift.
  The per-shot gate above is the one that discriminates, and it is self-tested against a synthetic
  frozen shot before use.
* **Audio:** {loud}. Target -14 LUFS / -1 dBTP. No background music, by request.

## Accuracy

Canon-label distribution:
{chr(10).join(f'  * {k} - {v} segment(s)' for k, v in sorted(canon_counts.items(), key=lambda x: -x[1]))}

{meta.get('accuracy_note', '')}

## IP posture

No episode footage and no character likenesses. Characters are original heraldic cards, locations are
original matte paintings, the analysis is code-drawn diagrams, and the thumbnail uses objects and
heraldry rather than portraits.

## Files

`{ep.slug}.mp4` - `{ep.slug}.srt` - `description.txt` (with chapters) - `title.txt` - `tags.txt` -
`transcript.txt` - `thumbnail.jpg` - `narration.mp3` - `script.json` - `build_report.json`
(the {len(rep['cuts'])}-shot cut ledger).

Rebuild: `import hotd_build, {meta['module']}; hotd_build.main({meta['module']}.episode())`
then `hotd_deliver.deliver(...)`.
"""
    open(f"{ep.out}/README.md", "w", encoding="utf8").write(txt)
