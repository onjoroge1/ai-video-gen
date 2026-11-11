"""Turn a script_engine Short into a native-Short spec, ready for review before any spend.

    python3 scripts/short_from_engine.py --title "Why Do Wombats Poop Cubes?" --out jobs/premise_shorts/wombat
    python3 scripts/short_from_engine.py --handoff handoff.json --out jobs/premise_shorts/wombat

The script is written in the operator's separate repo (github.com/onjoroge1/script_engine). Its
README asks callers to run its command line and read back one JSON handoff, never import it, so
its keys, venv and transcripts stay there. Point SCRIPT_ENGINE_DIR (or --engine) at the checkout.

This side adds what the handoff lacks: picture prompts. One Claude call writes, per script line,
1-3 picture prompts with the word each picture opens on, in our painted style, naming the real
animal in every prompt (an unnamed prompt drew an elephant for moss, 11-07) and never as "no X".
The first picture moves (fal clip) and holds for open_hold_sec. Nothing is voiced or drawn here:
the spec is written for the operator to read, then make_native_short.py builds it.

A handoff that needs review (failing style checks or unsupported claims) stops here unless
--accept is given; the reasons are printed and saved with the spec.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.path.expanduser("~/ai-video-gen-local"))
MODEL = "claude-opus-5-5"
WORDS_PER_SEC = 3.4          # the echo voice: 119 words in 35.0 s on the published ant Short
SEC_PER_PICTURE = 1.5        # picture budget up front (11-07: 14-18 pictures in 50 s failed the hold gate)
OPEN_HOLD_SEC = 3.0          # 11-10 test: the moving first shot stays up through line 1
MAX_EST_HOLD = 2.2           # planned seconds per picture; the builder's limit is 2.8 s and the
                             # word-rate estimate ran 10% short on the ant Short (28 vs 30.9 s)
STYLE = ("Richly detailed painted documentary illustration, natural colours, soft natural light, visible "
         "brushwork, clearly a painting and never a photograph, no signature, no collage, {setting}.")

SYSTEM = """You plan the pictures for a 9:16 narrated animal Short. Each script line is voiced as one
line; you give it 1-3 painted pictures. Rules:
- Every prompt names the real animal in full with its look (e.g. "a carpenter ant, a large shiny
  black-and-brown ant with a big head and strong jaws"), even close-ups: an image model given an
  unnamed subject draws the wrong animal.
- Never describe something as absent ("no birds", "empty of ants"): the model draws it anyway.
  Name what IS in the frame.
- The picture shows what the words at that moment say, literally. One subject, big in frame.
- Picture 1 of each line has no "from". Each later picture has "from": one word copied exactly from
  that line, appearing after the previous picture's word, where the picture should appear.
- Aim for about one picture per 1.5 seconds of speech (the seconds are given per line).
- Line 1 has exactly ONE picture: the titled animal doing the line's act, close and filling the
  frame, with a "motion": one sentence of slow, physically plausible movement, camera still. It
  stays on screen for the first 3 seconds, so a second picture in line 1 would never be seen.
- No picture may cover more than 2.2 seconds of speech (except line 1's moving picture).
- No text, labels or captions in any picture. No people's faces.
Also give: setting (a short phrase for the shared background, e.g. "the dim green understory of a
Thai tropical rainforest"), headline (two words for the on-screen label, e.g. "ZOMBIE|ANT"), up to
20 search tags (specific to broad), and a two-sentence description of the facts the Short states."""


def run_engine(title: str, engine: Path, out: Path) -> dict:
    """Run the engine's CLI from its own folder (it loads its own .env) and read the handoff."""
    py = engine / ".venv" / "bin" / "python"
    if not py.exists():
        raise SystemExit(f"no engine venv at {py}: set up the checkout first (see its README)")
    subprocess.run([str(py), "scribe.py", "generate", title, "--format", "shorts", "--out", str(out)],
                   cwd=engine, check=True)
    return json.loads(out.read_text())


def review_problems(handoff: dict) -> list[str]:
    if handoff.get("handoff_version") != 1:
        return [f"unknown handoff_version {handoff.get('handoff_version')!r} (this bridge reads 1)"]
    problems = list(handoff.get("review_reasons") or [])
    for fact in handoff.get("flagged_facts") or []:
        problems.append(f"claim {fact.get('n', fact.get('number', '?'))}: {fact.get('claim', '')} "
                        f"[{fact.get('status', '')}]")
    if handoff.get("review_needed") and not problems:
        problems.append("engine marked review_needed")
    return problems


def _norm(word: str) -> str:
    return re.sub(r"[^\w'-]", "", word).lower()


def est_seconds(text: str) -> float:
    return len(text.split()) / WORDS_PER_SEC


def check_plan(lines: list[str], plan: list[dict]) -> list[str]:
    """Same rules the builder enforces at build time, caught before any money is spent."""
    errors = []
    if len(plan) != len(lines):
        return [f"plan has {len(plan)} lines, script has {len(lines)}"]
    for i, (text, row) in enumerate(zip(lines, plan), 1):
        pics = row.get("pictures") or []
        if not pics:
            errors.append(f"line {i}: no pictures")
            continue
        if pics[0].get("from"):
            errors.append(f"line {i}: picture 1 must not have 'from'")
        words, k = [_norm(w) for w in text.split()], 0
        for pic in pics[1:]:
            want = _norm(str(pic.get("from") or ""))
            while k < len(words) and words[k] != want:
                k += 1
            if not want or k >= len(words):
                errors.append(f"line {i}: cue word {pic.get('from')!r} not found in order in {text!r}")
                break
            k += 1
        if i == 1 and len(pics) > 1 and est_seconds(text) <= OPEN_HOLD_SEC + 0.5:
            errors.append(f"line 1: {len(pics)} pictures, but the {OPEN_HOLD_SEC:.0f} s moving hold covers the line; use one")
        elif i > 1 and est_seconds(text) / len(pics) > MAX_EST_HOLD:
            errors.append(f"line {i}: {len(pics)} picture(s) for ~{est_seconds(text):.1f} s; needs "
                          f"{int(est_seconds(text) // MAX_EST_HOLD) + 1}")
        for pic in pics:
            if re.search(r"\bno (?:\w+ )?(?:animals?|birds?|people|ants?|fish)\b", pic.get("image", ""), re.I):
                errors.append(f"line {i}: prompt describes an absence: {pic['image'][:60]!r}")
    if not plan[0]["pictures"][0].get("motion"):
        errors.append("line 1 picture 1 needs a motion line")
    return errors


def plan_pictures(handoff: dict) -> dict:
    import anthropic
    from pydantic import BaseModel, ConfigDict, Field
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    class Picture(BaseModel):
        image: str
        from_: str | None = Field(default=None, alias="from")
        motion: str | None = None
        model_config = ConfigDict(populate_by_name=True)

    class Line(BaseModel):
        pictures: list[Picture]

    class Plan(BaseModel):
        setting: str
        headline: str
        tags: list[str]
        description: str
        lines: list[Line]

    lines = handoff["lines"]
    listing = "\n".join(f"{i}. ({est_seconds(t):.1f} s) {t}" for i, t in enumerate(lines, 1))
    ask = f"Title: {handoff['title']}\n\nScript, one voiced line each:\n{listing}"
    client, errors = anthropic.Anthropic(), []
    for _ in range(2):
        content = ask + (("\n\nYour last plan broke these rules; fix them:\n" + "\n".join(errors)) if errors else "")
        r = client.messages.parse(model=MODEL, max_tokens=16000, system=SYSTEM, output_config={"effort": "high"},
                                  messages=[{"role": "user", "content": content}], output_format=Plan)
        if r.parsed_output is None:
            raise RuntimeError(f"picture plan returned no result (stop_reason={r.stop_reason})")
        plan = r.parsed_output.model_dump(by_alias=True, exclude_none=True)
        errors = check_plan(lines, plan["lines"])
        if not errors:
            plan["cost_usd"] = round((r.usage.input_tokens * 4 + r.usage.output_tokens * 20) / 1e6, 3)
            return plan
    raise SystemExit("picture plan still breaks the rules:\n" + "\n".join(errors))


def to_spec(handoff: dict, plan: dict, slot: str = "") -> dict:
    beats = [{"text": text, "pictures": row["pictures"]} for text, row in zip(handoff["lines"], plan["lines"])]
    tags = [t for t in plan["tags"] if t.lower() != "shorts"][:19] + ["shorts"]
    return {
        "title": handoff["title"], "headline": plan["headline"],
        "style": STYLE.format(setting=plan["setting"].strip().rstrip(".")),
        "cta": "", "voice": "echo", "package": "hook", "max_duration": 60,
        "end_card": [["FOLLOW"], ["FOR", "MORE"]], "end_card_hold": 1.5,
        "open_hold_sec": OPEN_HOLD_SEC,
        "description": plan["description"], "tags": tags,
        **({"proposed_slot": slot} if slot else {}),
        "beats": beats,
        "script_engine": {"run_id": handoff.get("run_id"), "run_dir": handoff.get("run_dir"),
                          "facts": (handoff.get("files") or {}).get("facts"), "model": handoff.get("model"),
                          "words": handoff.get("words"), "seconds": handoff.get("seconds"),
                          "fact_counts": handoff.get("fact_counts"), "fact_notes": handoff.get("fact_notes")},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--title", help="have the engine write this Short (runs its CLI; costs its API calls)")
    src.add_argument("--handoff", help="an existing handoff JSON (scribe.py generate/export --out)")
    ap.add_argument("--out", required=True, help="the Short's job folder; spec.json is written here")
    ap.add_argument("--engine", default=os.environ.get("SCRIPT_ENGINE_DIR", os.path.expanduser("~/script_engine")))
    ap.add_argument("--accept", action="store_true", help="continue although the engine flagged the script")
    ap.add_argument("--slot", default="", help="proposed publish time, RFC3339 UTC (recorded only)")
    args = ap.parse_args(argv)

    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    if (out / "spec.json").exists():
        raise SystemExit(f"{out / 'spec.json'} exists; pick a new folder (cached pictures key on prompts)")
    handoff_path = out / "handoff.json"
    if args.title:
        handoff = run_engine(args.title, Path(args.engine).expanduser(), handoff_path)
    else:
        handoff = json.loads(Path(args.handoff).read_text())
        handoff_path.write_text(json.dumps(handoff, indent=2, ensure_ascii=False) + "\n")
    if handoff.get("format") not in (None, "shorts"):
        raise SystemExit(f"handoff format is {handoff.get('format')!r}, not shorts")

    problems = review_problems(handoff)
    if problems:
        (out / "review.txt").write_text("\n".join(problems) + "\n")
        print("Engine flagged this script:\n  " + "\n  ".join(problems))
        if not args.accept:
            print(f"Stopped before planning pictures. Fix it in the engine, or rerun with --accept. ({out / 'review.txt'})")
            return 2

    plan = plan_pictures(handoff)
    spec = to_spec(handoff, plan, args.slot)
    (out / "spec.json").write_text(json.dumps(spec, indent=1, ensure_ascii=False) + "\n")
    secs = sum(len(t.split()) for t in handoff["lines"]) / WORDS_PER_SEC
    pictures = sum(len(b["pictures"]) for b in spec["beats"])
    print(f"Spec: {out / 'spec.json'}\n  {len(spec['beats'])} lines, ~{secs:.0f} s, {pictures} pictures "
          f"(~${pictures * 0.17:.2f} to draw, + $0.28 motion), plan ${plan['cost_usd']:.2f}\n"
          f"  Review the lines and prompts, then: python3 scripts/make_native_short.py {out / 'spec.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
