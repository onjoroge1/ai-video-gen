#!/usr/bin/env python3
"""One Wild Field Guide Short, end to end, with the house rules enforced (operator 2026-11-21).

    /opt/homebrew/bin/python3 scripts/produce_fg_short.py <job_dir> [stage ...] [options]

Stages (default: all, in order; each stops the run on a blocking failure):
  script   story rules on spec.json (deterministic checks + one Claude read, cached by script hash)
  build    make_native_short.py -> builder gate -> loudness.py (-14 LUFS) -> Claude reads frame 1
  meta     meta.json (title / description / tags): drafted by Claude if missing, always validated
  upload   Field Guide, private + scheduled 20:00Z (one Short a day), cover, synthetic flag,
           then the 20 Studio auto-translate languages (title + description)

Options:
  --at 2026-11-23T20:00:00Z   slot to use (default: next day with no scheduled Field Guide upload)
  --replace VIDEO_ID          take that upload's slot; after the new upload succeeds the old one is
                              set private with no schedule (kept, not deleted)
  --accept-draft              allow upload with Claude-drafted metadata nobody has approved
  --override RULE:reason      pass a blocking rule anyway; the reason is written to the report
  --dry-run                   do everything except upload / YouTube changes

Rules come from the Field Guide reads (jobs/yt/fg_shorts_story_read_2026-11-20.md and
memory): stayed-to-watch is decided by frame 1; viewers who stay leave at unresolved endings.
  R1 ending   (block) last 2 lines = concrete conclusion + what it means. No maybe / nobody
              knows / hedge / bare statistic / bare event.
  R2 frame 1  (block) the titled animal, large, bright, clearly visible above the caption band.
  R3 middle   (warn)  events/evidence leading to a "So..." deduction; at most 1 mechanism sentence.
  R4 line 1   (warn)  an impossibility, names the animal; line 2 escalates (<=5 s, no date rewind).
  R5 length   (block) 20-45 s (builder gate).
  Title       (block) names the animal, states the concrete impossible thing, <=70 chars,
              one trailing emoji, no hashtags, its noun is in line 1.
  Description (block) first sentence carries the keyword; 2 short paragraphs from the narration
              only; a comment question; exactly 3 hashtags ending #shorts.
  Tags        (block) 12-15 search-phrase tags, <=480 chars, include the animal, "animal facts",
              "wild field guide".
Reports land in <job_dir>/production.json; every upload is appended to jobs/yt/fg_production_log.json.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = "/opt/homebrew/bin/python3"
# The Shorts builder with the 11-18 creative standard lives on the shorts-hook worktree until merged;
# FG_SHORT_BUILDER overrides, the repo's make_native_short.py is the fallback.
_HOOK_BUILDER = os.path.expanduser("~/ai-video-gen-wt/shorts-hook/scripts/make_native_short.py")
BUILDER = os.environ.get("FG_SHORT_BUILDER") or (
    _HOOK_BUILDER if os.path.isfile(_HOOK_BUILDER) else os.path.join(ROOT, "scripts/make_native_short.py"))
LOUDNESS = os.path.join(ROOT, "scripts/fg_loudness.py")
LOCALIZE = os.path.join(ROOT, "scripts/fg_localize_short.py")
LOG = os.path.join(ROOT, "jobs/yt/fg_production_log.json")
MODEL = "claude-opus-5-5"
SLOT_HOUR_Z = 20  # 3 PM ET
HEDGES = re.compile(r"\b(maybe|perhaps|might|may have|nobody knows|no one knows|no one is sure|"
                    r"scientists (?:aren't|are not) sure|unclear|by one count|some say|could be|"
                    r"it's possible|remains a mystery|we may never know)\b", re.I)
WPS = 2.6  # spoken words per second (TTS measured ~2.6-2.9)
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿‍️⬀-⯿]+")

SCRIPT_RULES = """You judge a narrated YouTube Short (25-45 s, one line per picture) for the Wild Field Guide
channel against rules learned from our own retention data. Be strict and literal.

R1 ENDING (blocking): the last two lines must give a concrete conclusion that answers the question the
opening raised, plus what it means (a "So..." line, a callback that resolves line 1, or a plain meaning
line). FAIL if the Short ends on a hedge (maybe, nobody knows, by one count, scientists aren't sure), on
a bare statistic or side fact that answers nothing, or on a bare event with no meaning ("Not one crow
screamed."). Data: endings like that lose half the remaining viewers in the last seconds.
R3 MIDDLE (warning): the middle is events and evidence that lead to a "So..." deduction. FAIL if more
than one line explains a mechanism (immune system, physics, chemistry lecture) instead of showing what
happened.
R4 OPENING (warning): line 1 states an impossibility about a named animal (not just a fact or a
question). Line 2 escalates or raises the stakes; FAIL if line 2 rewinds to backstory, a date, or a
definition.
ACCURACY (blocking): FAIL if the ending claims more than the earlier lines support (overstated cause,
certainty the script itself undercuts).

Return ONLY JSON: {"R1": {"pass": bool, "why": str, "fix": str}, "R3": {...}, "R4": {...},
"ACCURACY": {...}}. "fix" is a concrete rewrite of the failing line(s) using only facts already in the
script, or "" when it passes."""

FRAME_RULES = """These are the first frames (0.3 s and 1.5 s) of a vertical YouTube Short titled {title!r}.
Its first line is {line1!r}. Viewers decide to stay from frame 1 (same script: 24% vs 63% stayed by the
opening picture alone). PASS only if the animal named in the title/first line is: clearly the subject,
large in frame (roughly a third of the height or more), well lit and readable on a phone, and not hidden
behind the caption band in the lower part. FAIL a dark subject on a dark background, a tiny subject, a
wrong or missing animal, or a frame where the titled object/act is not visible.
Return ONLY JSON: {{"pass": bool, "why": str}}"""

META_RULES = """Write YouTube metadata for this Wild Field Guide Short. Use ONLY facts in the narration.
Narration:
{narration}

Title rules: names the animal; states the concrete impossible thing from line 1 (a number, an act, an
object: "This Shark Was Born Before The USA Existed", "This Frog Freezes Solid For 7 Months. Then It
Hops Away"); Title Case; <=70 characters; ends with ONE fitting emoji; no hashtags; no clickbait the
narration doesn't pay off. Question titles are allowed but concrete statements test better.
Description: first sentence restates the impossible thing with the animal's common name (the search
keyword); 2 short paragraphs total from the narration (the second gives the payoff/meaning); then a
one-line comment question to the viewer starting a new paragraph ("... Tell us in the comments."); last
line exactly 3 hashtags: #<animal> #<one more topic tag> #shorts.
Tags: 12-15 search phrases people type (common name, plural, scientific name if in narration, "how/why"
questions, the phenomenon), always including "animal facts" and "wild field guide"; total under 450
characters.
Return ONLY JSON: {{"title": str, "description": str, "tags": [str], "animal": str}}"""


# ---------------------------------------------------------------- helpers
def claude(prompt: str, images: list[bytes] | None = None) -> dict:
    import anthropic
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                            "data": base64.standard_b64encode(b).decode()}}
               for b in images or []]
    content.append({"type": "text", "text": prompt})
    msg = anthropic.Anthropic().messages.create(
        model=MODEL, max_tokens=16000, messages=[{"role": "user", "content": content}],
        extra_body={"output_config": {"effort": "high"}})
    if msg.stop_reason == "refusal":
        raise SystemExit("Claude declined the request")
    text = "".join(b.text for b in msg.content if b.type == "text")
    found = re.search(r"\{.*\}", text, re.S)
    if not found:
        raise SystemExit(f"no JSON in Claude reply: {text[:300]}")
    return json.loads(found.group(0))


def load_env() -> None:
    path = os.path.join(ROOT, ".env")
    for line in open(path, encoding="utf-8"):
        m = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$", line)
        if m and m.group(1) not in os.environ:
            os.environ[m.group(1)] = m.group(2).strip().strip('"').strip("'")


def lines_of(job: str) -> list[str]:
    return [b["text"] for b in json.load(open(os.path.join(job, "spec.json")))["beats"]]


class Report:
    def __init__(self, job: str, overrides: dict[str, str]):
        self.path = os.path.join(job, "production.json")
        self.data = json.load(open(self.path)) if os.path.isfile(self.path) else {}
        self.overrides = overrides
        self.blocked: list[str] = []

    def rule(self, name: str, ok: bool, why: str, blocking: bool, fix: str = "") -> None:
        over = self.overrides.get(name)
        status = "pass" if ok else ("override" if over else ("FAIL" if blocking else "warn"))
        self.data.setdefault("rules", {})[name] = {"status": status, "why": why, "fix": fix,
                                                   **({"override": over} if over and not ok else {})}
        print(f"  {status:8} {name}: {why}" + (f"\n           fix: {fix}" if fix and not ok else ""))
        if status == "FAIL":
            self.blocked.append(name)

    def save(self) -> None:
        json.dump(self.data, open(self.path, "w"), indent=1, ensure_ascii=False)


# ---------------------------------------------------------------- stages
def stage_script(job: str, rep: Report) -> None:
    lines = lines_of(job)
    print(f"script: {len(lines)} lines, {sum(len(l.split()) for l in lines)} words")
    end = " ".join(lines[-2:])
    hedge = HEDGES.search(end)
    rep.rule("R1-hedge", not hedge, f"hedge word {hedge.group(0)!r} in the last 2 lines" if hedge
             else "no hedge words in the ending", True)
    l2 = lines[1] if len(lines) > 1 else ""
    l2_sec = len(l2.split()) / WPS
    rewind = re.search(r"\b(1[5-9]\d\d|20[0-2]\d)\b", l2)
    rep.rule("R4-line2", l2_sec <= 5.0 and not rewind,
             f"line 2 ~{l2_sec:.1f} s" + (f", date rewind {rewind.group(0)}" if rewind else ""), False)
    key = hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16]
    cache = rep.data.get("script_read", {})
    if cache.get("key") != key:
        numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(lines))
        cache = {"key": key, "read": claude(SCRIPT_RULES + "\n\nScript:\n" + numbered)}
        rep.data["script_read"] = cache
    read = cache["read"]
    for name, blocking in (("R1", True), ("ACCURACY", True), ("R3", False), ("R4", False)):
        r = read.get(name, {})
        rep.rule(name, bool(r.get("pass")), r.get("why", "?"), blocking, r.get("fix", ""))


def _build_json(job: str) -> dict:
    text = open(os.path.join(job, "build.log")).read()
    start = text.find("{")
    return json.loads(text[start:]) if start >= 0 else {}


def stage_build(job: str, rep: Report) -> None:
    short = os.path.join(job, "short.mp4")
    spec = os.path.join(job, "spec.json")
    fresh = os.path.isfile(short) and os.path.getmtime(short) > os.path.getmtime(spec)
    if not fresh:
        print("build: make_native_short.py (cached pictures and narration are reused)")
        with open(os.path.join(job, "build.log"), "w") as log:
            subprocess.run([PY, BUILDER, spec], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        result = _build_json(job)
        if result.get("gate_pass"):
            subprocess.run([PY, LOUDNESS, job], cwd=ROOT, check=True)
    result = _build_json(job)
    for name, (value, ok) in (result.get("gate") or {}).items():
        rep.rule(f"gate:{name}", bool(ok), str(value), True)
    if not os.path.isfile(short):
        rep.rule("built", False, "no short.mp4 (see build.log)", True)
        return
    pkg = json.load(open(os.path.join(job, "package.json")))
    lufs = (pkg.get("loudness") or {}).get("lufs")
    rep.rule("loudness", lufs is not None and abs(lufs + 14) <= 0.6, f"{lufs} LUFS (target -14)", True)
    dur = float(pkg.get("duration") or 0)
    rep.rule("R5-length", 20 <= dur <= 45, f"{dur:.1f} s", True)
    # R2: frame 1, read by Claude
    frames = []
    for at in ("0.3", "1.5"):
        out = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", at, "-i", short, "-frames:v", "1",
                              "-vf", "scale=540:-1", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
                             capture_output=True, check=True).stdout
        frames.append(out)
    meta = _meta(job)
    key = hashlib.sha256(b"".join(frames)).hexdigest()[:16]
    cache = rep.data.get("frame_read", {})
    if cache.get("key") != key:
        title = meta.get("title") or json.load(open(spec)).get("title", "")
        cache = {"key": key, "read": claude(FRAME_RULES.format(title=title, line1=lines_of(job)[0]), frames)}
        rep.data["frame_read"] = cache
    rep.rule("R2-frame1", bool(cache["read"].get("pass")), cache["read"].get("why", "?"), True)


def _meta(job: str) -> dict:
    path = os.path.join(job, "meta.json")
    return json.load(open(path)) if os.path.isfile(path) else {}


def stage_meta(job: str, rep: Report) -> dict:
    path = os.path.join(job, "meta.json")
    meta = _meta(job)
    if not meta:
        print("meta: drafting title/description/tags with Claude (review before upload)")
        narration = "\n".join(lines_of(job))
        meta = claude(META_RULES.format(narration=narration))
        meta["drafted_by"] = MODEL
        meta["approved"] = False
        json.dump(meta, open(path, "w"), indent=1, ensure_ascii=False)
    title, desc, tags = meta.get("title", ""), meta.get("description", ""), meta.get("tags", [])
    animal = (meta.get("animal") or "").lower()
    line1 = lines_of(job)[0].lower()
    emojis = EMOJI.findall(title)
    rep.rule("title-shape", len(title) <= 70 and "#" not in title and len(emojis) == 1
             and bool(EMOJI.search(title.rstrip()[-3:])),
             f"{len(title)} chars, {len(emojis)} emoji group(s), hashtags={'#' in title}", True)
    stem = animal.rstrip("s")
    rep.rule("title-animal", bool(stem) and stem in title.lower(), f"animal {animal!r} in title", True)
    rep.rule("title-matches-line1", bool(stem) and stem in line1,
             f"line 1 names the titled animal ({stem!r})", True)
    paras = [p for p in desc.split("\n\n") if p.strip()]
    hashtags = re.findall(r"#\w+", paras[-1]) if paras else []
    rep.rule("description-shape",
             len(paras) == 4 and "comment" in paras[-2].lower() and len(hashtags) == 3
             and hashtags[-1].lower() == "#shorts" and bool(stem) and stem in paras[0].lower().split(".")[0],
             f"{len(paras)} paragraphs (want 2 + question + hashtags), hashtags {hashtags}", True)
    low = [t.lower() for t in tags]
    rep.rule("tags", 12 <= len(tags) <= 15 and len(",".join(tags)) <= 480 and "animal facts" in low
             and "wild field guide" in low and any(stem in t for t in low),
             f"{len(tags)} tags, {len(','.join(tags))} chars", True)
    if meta.get("approved") is False:
        rep.data["meta_note"] = "drafted, not yet approved: set \"approved\": true in meta.json"
    return meta


def _yt():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from googleapiclient.discovery import build
    from youtube_upload import _creds
    return build("youtube", "v3", credentials=_creds("fieldguide"), cache_discovery=False)


def scheduled_days(yt) -> dict[str, str]:
    """{YYYY-MM-DD: video_id} for Field Guide uploads that are private with a future publishAt."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from youtube_upload import channel_uploads
    me = yt.channels().list(part="id", mine=True).execute()["items"][0]["id"]
    ids = [v["id"] for v in channel_uploads(yt, me) if v["privacy"] == "private"]
    out = {}
    for i in range(0, len(ids), 50):
        for item in yt.videos().list(part="status", id=",".join(ids[i:i + 50])).execute()["items"]:
            at = item["status"].get("publishAt")
            if at:
                out[at[:10]] = item["id"]
    return out


def stage_upload(job: str, rep: Report, args, meta: dict) -> None:
    if meta.get("approved") is False and not args.accept_draft:
        rep.rule("meta-approved", False, "meta.json is a draft; approve it or pass --accept-draft", True)
        return
    yt = _yt()
    old = None
    if args.replace:
        old = yt.videos().list(part="status,snippet", id=args.replace).execute()["items"][0]
        at = args.at or old["status"].get("publishAt")
        if not at:
            raise SystemExit(f"{args.replace} has no schedule; pass --at")
    elif args.at:
        at = args.at
    else:
        taken = scheduled_days(yt)
        day = dt.date.today() + dt.timedelta(days=1)
        while day.isoformat() in taken:
            day += dt.timedelta(days=1)
        at = f"{day.isoformat()}T{SLOT_HOUR_Z:02d}:00:00Z"
    print(f"upload: {meta['title']!r} -> {at}" + (f" (replacing {args.replace})" if old else ""))
    desc_file = os.path.join(job, "description.txt")
    open(desc_file, "w").write(meta["description"])
    cmd = [PY, "scripts/youtube_upload.py", "--video", os.path.join(job, "short.mp4"), "--title", meta["title"],
           "--description-file", desc_file, "--tags", ",".join(meta["tags"]), "--publish-at", at,
           "--channel", "fieldguide"]
    cover = os.path.join(job, "cover.jpg")
    if os.path.isfile(cover):
        cmd += ["--thumbnail", cover]
    if old:
        cmd += ["--allow-duplicate", f"replaces {args.replace} (rules fix, same slot)"]
    if args.dry_run:
        cmd.append("--dry-run")
    subprocess.run(cmd, cwd=ROOT, check=True)
    if args.dry_run:
        rep.data["upload"] = {"dry_run": True, "at": at}
        return
    ledger = json.load(open(os.path.join(ROOT, "jobs/yt/upload_ledger.json")))
    ledger = ledger if isinstance(ledger, list) else ledger.get("uploads", [])
    rel = os.path.relpath(os.path.join(job, "short.mp4"), ROOT)
    vid = [e for e in ledger if e.get("file") in (rel, os.path.join(job, "short.mp4"))][-1]["video_id"]
    if old:  # keep the old upload, private and unscheduled
        status = {k: v for k, v in old["status"].items() if k in (
            "privacyStatus", "embeddable", "license", "publicStatsViewable", "selfDeclaredMadeForKids",
            "containsSyntheticMedia")}
        status.update(privacyStatus="private", publishAt=None, containsSyntheticMedia=True)
        yt.videos().update(part="status", body={"id": args.replace, "status": status}).execute()
        print(f"  {args.replace} set private, unscheduled")
    time.sleep(60)  # YouTube needs the snippet before localizations
    subprocess.run([PY, LOCALIZE, vid, job], cwd=ROOT, check=False)
    rep.data["upload"] = {"video_id": vid, "at": at, "replaced": args.replace, "title": meta["title"]}
    log = json.load(open(LOG)) if os.path.isfile(LOG) else []
    log.append({"video_id": vid, "job": os.path.relpath(job, ROOT), "at": at, "title": meta["title"],
                "replaced": args.replace, "rules": rep.data.get("rules"),
                "uploaded": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
    json.dump(log, open(LOG, "w"), indent=1, ensure_ascii=False)
    print(f"  uploaded {vid}, scheduled {at}, 20 languages requested")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("job")
    p.add_argument("stages", nargs="*", default=["script", "build", "meta", "upload"],
                   choices=["script", "build", "meta", "upload"])
    p.add_argument("--at")
    p.add_argument("--replace")
    p.add_argument("--accept-draft", action="store_true")
    p.add_argument("--override", action="append", default=[], help="RULE:reason")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    load_env()
    job = os.path.abspath(args.job)
    rep = Report(job, dict(o.split(":", 1) for o in args.override))
    meta = {}
    for stage in args.stages:
        print(f"== {stage}")
        if stage == "script":
            stage_script(job, rep)
        elif stage == "build":
            stage_build(job, rep)
        elif stage == "meta":
            meta = stage_meta(job, rep)
        elif stage == "upload":
            if rep.blocked:
                print(f"upload refused: blocking rules failed {rep.blocked}")
                break
            stage_upload(job, rep, args, meta or stage_meta(job, rep))
        rep.save()
        if rep.blocked:
            print(f"STOP after {stage}: {', '.join(rep.blocked)} (report {rep.path})")
            return 1
    rep.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
