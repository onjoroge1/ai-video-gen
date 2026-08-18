"""Cut a shorter video out of a finished long-form render, reusing the stills and audio already paid for.

Usage:
    python3 tools/story_cut.py <job_dir> --scenes 0-19 --out mystery.mp4
    python3 tools/story_cut.py <job_dir> --beats anomaly,credential,false_belief,seal,reversal
    python3 tools/story_cut.py <job_dir> --list

Why this works at zero cost: the finished explainer.mp4 already carries the burned-in captions, the
Ken Burns moves and the music mix, and captions.srt has one cue per scene -- so a cut on a cue
boundary is a cut on a scene boundary, and the narration never clips mid-word. Nothing is
regenerated; no image, TTS or i2v call is made.

Why cut on BEATS rather than by time: the story engine persists a _role per scene, so
"anomaly -> reversal" is a complete arc (a concrete anomaly, the belief it breaks, and the evidence
that breaks it) rather than an arbitrary first-N-seconds slice. Cutting mid-beat gives you a video
that stops rather than one that ends.

Contiguity is enforced: assembling non-adjacent beats produces jump cuts in both picture and voice,
and the result reads as a trailer, not a story. Ask for a contiguous span or the tool refuses.
"""
import json
import os
import subprocess
import sys


def _sec(t):
    h, m, rest = t.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def load(job):
    """(scenes, roles, cues) for a finished job dir."""
    st = json.load(open(os.path.join(job, "_state.json")))
    scenes = (st.get("script") or {}).get("scenes") or []
    roles = [(s.get("_role") or "").strip() for s in scenes]
    cues = []
    for block in open(os.path.join(job, "captions.srt")).read().strip().split("\n\n"):
        lines = block.strip().split("\n")
        if len(lines) >= 2 and "-->" in lines[1]:
            a, z = lines[1].split(" --> ")
            cues.append((_sec(a), _sec(z)))
    if len(cues) != len(scenes):
        # Never guess an alignment: a mismatch means a cut would land mid-sentence.
        raise SystemExit(f"srt/scene mismatch ({len(cues)} cues vs {len(scenes)} scenes) -- refusing "
                         "to cut, because the boundaries can no longer be trusted")
    return scenes, roles, cues


def runs(roles):
    out = []
    for i, r in enumerate(roles):
        if out and out[-1][0] == r:
            out[-1][1].append(i)
        else:
            out.append([r, [i]])
    return out


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    job = argv[1]
    scenes, roles, cues = load(job)
    src = os.path.join(job, "explainer.mp4")

    if "--list" in argv or len(argv) == 2:
        print(f"  {len(scenes)} scenes · {cues[-1][1]:.1f}s\n")
        print(f"  {'beat':18s} {'scenes':>9} {'start':>7} {'end':>7} {'dur':>7}")
        for r, idxs in runs(roles):
            a, z = cues[idxs[0]][0], cues[idxs[-1]][1]
            print(f"  {r or '?':18s} {idxs[0]:3d}-{idxs[-1]:<3d} {a:7.1f} {z:7.1f} {z - a:6.1f}s")
        return 0

    if "--scenes" in argv:
        lo, hi = (int(x) for x in argv[argv.index("--scenes") + 1].split("-"))
    elif "--beats" in argv:
        want = [b.strip() for b in argv[argv.index("--beats") + 1].split(",") if b.strip()]
        idxs = [i for i, r in enumerate(roles) if r in want]
        if not idxs:
            raise SystemExit(f"no scenes carry any of {want}")
        lo, hi = min(idxs), max(idxs)
        # Enforced, not warned: a gap means the requested beats are not adjacent, and stitching them
        # would cut the voice mid-thought at every seam.
        if sorted(idxs) != list(range(lo, hi + 1)):
            gaps = sorted(set(range(lo, hi + 1)) - set(idxs))
            raise SystemExit(f"those beats are not contiguous (scenes {gaps} sit between them). "
                             "Cutting them together would jump-cut the narration -- widen the "
                             "selection or use --scenes explicitly.")
    else:
        raise SystemExit("need --scenes lo-hi or --beats a,b,c (or --list)")

    lo, hi = max(0, lo), min(len(scenes) - 1, hi)
    start, end = cues[lo][0], cues[hi][1]
    out = argv[argv.index("--out") + 1] if "--out" in argv else \
        os.path.join(job, f"cut_{lo:02d}_{hi:02d}.mp4")

    print(f"  scenes {lo}-{hi} · beats {sorted({roles[i] for i in range(lo, hi + 1)})}")
    print(f"  {start:.1f}s -> {end:.1f}s  ({end - start:.1f}s)")
    # Re-encode rather than stream-copy: -c copy snaps to the nearest keyframe, which would drift the
    # cut off the scene boundary and clip the narration. Re-encoding is free and frame-accurate.
    cmd = ["ffmpeg", "-nostdin", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", src,
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-1500:])
        raise SystemExit(f"ffmpeg failed ({r.returncode})")
    sz = os.path.getsize(out) / 1e6
    print(f"  wrote {out}  ({sz:.0f} MB)")

    # Ship the cut's OWN captions. The job's captions.srt covers all 64 scenes on the full timeline,
    # so uploading it against a 110s cut would desync immediately and then run past the end. Rebase
    # every cue to the cut's zero and drop the ones outside it.
    def _ts(x):
        ms = int(round(x * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

    srt_out = os.path.splitext(out)[0] + ".srt"
    with open(srt_out, "w") as fh:
        for n, i in enumerate(range(lo, hi + 1), 1):
            a, z = cues[i][0] - start, cues[i][1] - start
            fh.write(f"{n}\n{_ts(max(0.0, a))} --> {_ts(z)}\n"
                     f"{(scenes[i].get('narration') or '').strip()}\n\n")
    print(f"  wrote {srt_out}  ({hi - lo + 1} cues, rebased to 0)")

    print("\n  narration in this cut:")
    for i in range(lo, min(hi + 1, lo + 4)):
        print(f"    {scenes[i].get('narration','')[:96]}")
    if hi - lo > 4:
        print(f"    ... ({hi - lo - 3} more)")
        print(f"    {scenes[hi].get('narration','')[:96]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
