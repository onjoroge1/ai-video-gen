"""End-to-end: a PLAIN-LANGUAGE idea → validated topic → deterministic animatic + all reports, with NO
topic-specific core code. This is the real proof the engine takes future ideas, not only handcrafted
fixtures. Usage:
  python3 -m bolt_seq.run_idea "What if gravity doubled for ten seconds?"          # compile + render
  python3 -m bolt_seq.run_idea "..." --plan-only                                   # compile + gates only
"""
import os, sys, json, re
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(PROJ, ".env"), override=True)
from bolt_seq import idea_compiler as IC, orchestrator as O


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:40] or "idea"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    plan_only = "--plan-only" in sys.argv
    idea_text = args[0] if args else "What if gravity doubled for ten seconds?"
    idea = {"idea": idea_text, "duration_target": 20, "character": "Bolt", "style": "high-retention science Short"}
    slug = slugify(idea_text)
    out = os.path.join(PROJ, "renders", "bolt_seq", slug)
    cost = []
    print(f"=== COMPILING IDEA → {slug} ===", flush=True)
    res = IC.compile(idea, out_dir=out, cost=cost, log=print)
    print(json.dumps({"gate_ok": res["gate_ok"], "attempts": res["attempts"],
                      "facts": res["facts"].get("gate"), "cost": round(sum(cost), 3)}, indent=2))
    if not res["gate_ok"]:
        print("COMPILE GATE FAILED — not rendering. See _validate/ reports.")
        vr = res.get("validation", {})
        print("continuity:", json.dumps(vr.get("continuity", {}).get("provenance_problems"), default=str))
        print("semantic hard:", vr.get("semantic_audit", {}).get("hard_failures"))
        return
    if plan_only:
        print("PLAN-ONLY: topic gate-valid; skipping render.")
        return
    print("=== RENDERING (deterministic, no paid video) ===", flush=True)
    summary = O.build(slug, topic_obj=res["topic"], render=True, out_dir=out, log=print)
    summary["compile_cost"] = round(sum(cost), 3)
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
