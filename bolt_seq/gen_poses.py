"""Phase 2.1 step 1: locked Bolt pose library with a STRONG perceptual gate. Generates dive/tumble/
impact/exit_loop, rejecting anything that reads as waving/hovering/standing/floating/presenting.
Run: python3 bolt_seq/gen_poses.py"""
import os, sys, json, concurrent.futures as cf
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ); sys.path.insert(0, PROJ)
from dotenv import load_dotenv; load_dotenv(dotenv_path=os.path.join(os.getcwd(),".env"), override=True)
from bolt_seq import compiler as C

OUT = os.path.join(PROJ, "renders/bolt_cloud_experiment_package/phase2")
LIB = os.path.join(OUT, "bolt_pose_library"); os.makedirs(LIB, exist_ok=True)
def log(m): print(m, flush=True)
BASE = ("A small friendly toy-robot mascot, full body, centered, on a SOLID FLAT MAGENTA (#FF00FF) "
        f"background filling the whole frame. It has {C.POSE_IDENTITY}. Premium 3D cartoon render, "
        "dramatic dynamic lighting, no scenery, no ground. ")
POSES = {
 "dive_pose":  (BASE+"POSE: a HEAD-FIRST NOSE DIVE — the entire body pitched steeply DOWNWARD on a diagonal, "
   "visor/head aimed toward the bottom of the frame, arms swept back tight along the body like a speed "
   "skydiver, hover-base trailing UPWARD behind him, motion streaks. Clearly plummeting at high speed. "
   "It is NOT upright, NOT waving, NOT floating, NOT facing the camera flat.",
   "a fast head-first downward nose-dive, body pitched steeply down"),
 "tumble_pose":(BASE+"POSE: TUMBLING OUT OF CONTROL — the body rotated onto its side and partly upside-down, "
   "arms flailing asymmetrically at different angles, clearly off-balance, spinning and panicked. "
   "NOT upright, NOT a calm or waving pose.",
   "spinning/tumbling out of control, off-balance"),
 "impact_pose":(BASE+"POSE: the SQUASH FRAME at the instant of impact — body compressed and flattened "
   "vertically from hitting a soft surface, arms braced outward, bracing hard. A squash-and-stretch impact.",
   "a squashed bracing impact frame"),
 "exit_loop_pose":(BASE+"POSE: PLUMMETING head-first downward on a diagonal (a dive silhouette), arms out, "
   "still falling fast — to loop back to an opening dive. NOT upright, NOT waving.",
   "a downward diving plummet, matching an opening dive"),
}
def main():
    costs=[]
    def do(item):
        name,(prompt,want)=item
        return name, C.gen_pose(prompt, os.path.join(LIB,f"{name}.png"), name, want, tries=4, cost_sink=costs, log=log)
    rep={}
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        for name,res in ex.map(do, POSES.items()): rep[name]=res
    json.dump(rep, open(os.path.join(OUT,"pose_preflight_report.json"),"w"), indent=2)
    log("\n=== POSE LIBRARY ===")
    for n,r in rep.items():
        log(f"  {n}: {'PASS' if r['passed'] else 'BEST-EFFORT'} | {r['scores']} | reads='{r['reads_as']}'")
    log(f"cost ${sum(costs):.2f}")
if __name__ == "__main__":
    main()
