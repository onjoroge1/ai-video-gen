import sys, re, os; sys.path.insert(0,'/Users/obadiah/Documents/video')
os.chdir('/Users/obadiah/Documents/video')
import seo, json

PRETTY = {"hook": "the hook", "hook_a": "the hook", "hook_b": "the hook", "verdict": "The verdict",
          "moon": "The Moon", "67p": "Comet 67P", "comet": "Comet 67P", "iss": "The ISS"}


def scene_cuts(d):
    """(scene id, start seconds) from the RENDER's own record, in play order."""
    rep = json.load(open(f"{d}/build_report.json"))
    if rep.get("cuts") and isinstance(rep["cuts"][0], dict) and "seg" in rep["cuts"][0]:
        seen, out = set(), []
        for cut in rep["cuts"]:
            if cut["seg"] not in seen:
                seen.add(cut["seg"]); out.append((cut["seg"], cut["t"]))
        return out
    tbl = json.load(open(f"{d}/scene_table.json"))
    rows = tbl if isinstance(tbl, list) else (tbl.get("scenes") or tbl.get("rows") or [])
    return [(r["id"], r["start"]) for r in rows]

SRC = {
 "water_every_world": dict(
   pq="What happens if you pour water on every planet",
   answer="On five of six worlds it never stays liquid -- and the reason is one line on a phase diagram, not temperature.",
   surprise="Only One World Lets You Keep The Puddle",
   subject="Water In Space",
   hybrid="Why Only One World Lets You Pour A Glass Of Water",
   chap={"Mars":"Why water boils and freezes on Mars","Venus":"What happens to water on Venus",
         "The Moon":"Why water cannot stay liquid on the Moon","Titan":"Why water freezes solid on Titan",
         "hook_a":"What happens when you pour water in space","hook_b":"What happens when you pour water in space",
         "mars":"Why water boils and freezes on Mars","venus":"What happens to water on Venus",
         "moon":"Why water cannot stay liquid on the Moon","titan":"Why water freezes solid on Titan",
         "pluto":"How ice sublimes on Pluto","earth":"Why Earth can have liquid water",
         "verdict":"Which worlds can hold liquid water","Pluto":"How ice sublimes on Pluto","Earth":"Why Earth can have liquid water",
         "The verdict":"Which worlds can hold liquid water"},
   q=["Why can't water stay liquid on Mars","What is the triple point of water",
      "Why does water boil and freeze at the same time","What is the boiling point of water on Venus",
      "Can there be liquid water on Titan","Why does ice sublime instead of melting",
      "Which planets could have liquid water on the surface"],
   src=["NIST Chemistry WebBook -- water phase data: https://webbook.nist.gov/chemistry/",
        "NASA Planetary Fact Sheet -- surface pressure and temperature: https://nssdc.gsfc.nasa.gov/planetary/factsheet/"],
   tags=["#space","#physics","#solarsystem"]),
 "fly_every_world": dict(
   pq="Could you fly on other planets",
   answer="On one moon a human with strapped-on wings could genuinely take off -- and it is not the one with the lowest gravity.",
   surprise="On Titan You Could Actually Fly By Flapping",
   subject="Flight",
   hybrid="Why Humans Could Fly On Titan But Never On Mars",
   chap={"hook":"Could a human fly on another planet","mars":"Why you cannot fly on Mars",
         "earth":"Why humans cannot fly on Earth","venus":"Flying in the atmosphere of Venus",
         "titan":"Why you could fly on Titan","moon":"Why rotors do nothing on the Moon",
         "verdict":"Which world is easiest to fly on"},
   q=["Could a human fly on Titan","Why can't humans fly on Earth","How does air density affect lift",
      "Why is it impossible to fly on Mars","Does low gravity make flying easier",
      "What is the lift equation","Which world is easiest to fly on"],
   src=["NASA Glenn -- lift and the lift equation: https://www.grc.nasa.gov/www/k-12/airplane/lifteq.html",
        "NASA Planetary Fact Sheet -- gravity and atmospheric density: https://nssdc.gsfc.nasa.gov/planetary/factsheet/"],
   tags=["#space","#physics","#titan"]),
 "jump_every_world": dict(
   pq="How high could you jump on other planets",
   answer="Your ordinary standing jump would take you off some worlds entirely -- you would never come back down.",
   surprise="On One World Your Normal Jump Never Comes Back Down",
   subject="Gravity",
   hybrid="The Worlds Where Your Jump Becomes An Escape",
   chap={"hook":"How high could you jump on another world","earth":"How high a human can jump on Earth",
         "mars":"How high you could jump on Mars","moon":"How high you could jump on the Moon",
         "titan":"How high you could jump on Titan","ceres":"Could you jump off Ceres",
         "67p":"Jumping off Comet 67P and never landing","verdict":"Where your jump becomes escape velocity"},
   q=["How high could you jump on the Moon","Could you jump off an asteroid","What is escape velocity",
      "How high can a human jump on Mars","Why does low gravity let you jump higher",
      "Could you jump off Ceres","How does surface gravity change jump height"],
   src=["NASA Planetary Fact Sheet -- surface gravity and escape velocity: https://nssdc.gsfc.nasa.gov/planetary/factsheet/",
        "NASA JPL Small-Body Database -- asteroid and comet parameters: https://ssd.jpl.nasa.gov/"],
   tags=["#space","#physics","#gravity"]),
}
CTA = "New physics simulation every week -- subscribe so you don't miss the next world."
DISC = "Every verdict in this video is computed from published planetary data, not asserted. The numbers above are the actual model inputs. Visuals are AI-generated depictions of the simulated result."

for slug, c in SRC.items():
    d = f"renders/{slug}"
    old = open(f"{d}/description.txt").read()
    title = open(f"{d}/title.txt").read().split("\n")[0].strip()
    # keep the verified physics table and the real timestamps
    tbl = old.split("THE NUMBERS",1)
    tail = tbl[1] if len(tbl)>1 else ""
    for stop in ("QUESTIONS ANSWERED","CHAPTERS","SOURCES"):
        tail = tail.split(stop)[0]
    table = ("THE NUMBERS" + tail.rstrip()) if len(tbl)>1 else ""
    body = old.split("\n\n",1)[1].split("THE NUMBERS")[0].strip() if "THE NUMBERS" in old else ""
    chaps = []
    for cid, t in scene_cuts(d):
        lab = c["chap"].get(cid) or seo.searchable_chapter(
            PRETTY.get(cid, cid.replace("_", " ").title()),
            {"fly_every_world": "Flying on", "jump_every_world": "Jumping on"}.get(slug, ""))
        if chaps and chaps[-1].endswith(lab):
            continue                      # two cuts inside one beat is one chapter
        chaps.append(f"{int(t)//60}:{int(t)%60:02d} {lab}")
    text, gate = seo.build_description(c["pq"], c["answer"], body, table, c["q"], chaps,
                                       c["src"], c["tags"], CTA, DISC)
    open(f"{d}/description.txt","w").write(text+"\n")
    vs = seo.title_variants(c["pq"]+"?", c["subject"], c["surprise"], hybrid=c["hybrid"])
    open(f"{d}/title.txt","w").write(seo.build_title_file(title, vs)+"\n")
    tags=[x.strip() for x in open(f"{d}/tags.txt").read().split(",")]
    tr = seo.tag_field(tags, c["pq"])
    open(f"{d}/tags.txt","w").write(tr["field"]+"\n")
    print(f"--- {slug}"); print(seo.report(seo.check_title(title), gate, tr))
