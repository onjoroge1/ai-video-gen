"""Harvest the verified S3E5 script from the workflow output, then build the episode.

Kept separate from hotd/ because the workflow output path is session-scoped: the package must not
depend on it. This is the glue that hands a finished script to `hotd build`.
"""
from __future__ import annotations
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

WF = ("/private/tmp/claude-501/-Users-obadiah-Documents-video/"
      "bd858536-957a-436f-9610-e8cc07662830/tasks/wwa2fu2gj.output")
OUT = "renders/hotd_s3e5"


def harvest():
    raw = json.load(open(WF))
    res = raw.get("result") or {}
    sc = res.get("script") or {}
    segs = sc.get("segments")
    if not segs:
        raise SystemExit("workflow produced no script")
    words = sum(len(s["narration"].split()) for s in segs)
    os.makedirs(OUT, exist_ok=True)
    json.dump({"title": sc.get("title", ""), "total_words": words, "segments": segs,
               "changelog": sc.get("changelog", []),
               "verification": [{"lens": v.get("lens"), "pass": v.get("pass"),
                                 "failures": len(v.get("failures") or [])}
                                for v in (res.get("verdicts") or [])],
               "blockers": res.get("blockers", [])},
              open(f"{OUT}/script.json", "w"), indent=2, ensure_ascii=False)
    json.dump({"judge": res.get("judge"), "audit": res.get("audit"),
               "verdicts": res.get("verdicts"), "drafts": res.get("drafts")},
              open(f"{OUT}/script_review.json", "w"), indent=2, ensure_ascii=False)
    print(f"harvested: {len(segs)} segments, {words} words")
    for v in (res.get("verdicts") or []):
        print(f"  verify {v.get('lens','?'):26s} pass={v.get('pass')} "
              f"failures={len(v.get('failures') or [])}")
    bl = res.get("blockers") or []
    print(f"  blockers: {len(bl)}")
    for b in bl[:8]:
        print(f"    [{b.get('segment_id')}] {str(b.get('problem'))[:120]}")
    return len(segs), words, len(bl)


if __name__ == "__main__":
    harvest()
