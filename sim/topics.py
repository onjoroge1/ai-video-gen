"""The simulation topic bank: what to build next, and why it is cheap.

WHY A MODULE AND NOT ONLY THE DATABASE
The `topics` table already exists, but it is shaped for the curiosity engine -- median_views,
competition, outlier, winning_titles -- because those topics are SCRAPED. Simulation topics are
authored, and the fields that decide whether one is worth building are entirely different: which
format invariant it uses, which physics solver it can reuse, and therefore what it costs. None of
those have a column, and inventing them as free text in `pattern` would make the bank unqueryable.

So the module is the source of truth (version controlled, reviewable in a diff, and readable with no
database connection -- which matters because Neon cold-connects block and `sim.build` must never
depend on that), and `sync()` pushes a projection into the table so the existing UI can queue and
mark them.

THE FIELD THAT ACTUALLY MATTERS IS `reuses`.
Every topic here is costed by what it can borrow. `boiling_c` in the water topic is a pure function
of pressure, so any topic about vapour pressure -- altitude, sweat, a kettle on Everest -- is
physics-free to build. A topic needing a new solver is not more expensive to render; it is more
expensive to get RIGHT, because the solver is where the verdicts come from and a wrong one
invalidates every beat at once.

COST NOTE ON `family`.
"every world" is the priciest shape we have: six unique environments means six plates and six clips
with no reuse, and CONTINUITY has to hold a subject together across totally different worlds. Every
family below except `parallel_world` fixes the world and varies something else -- one environment,
shared look, plates that can reference each other, roughly half the plate spend for the same runtime.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict

# The format invariant. This is the choice that determines the camera, the motion mode, and which
# datum rule applies -- not a genre label.
FAMILIES = {
    "parallel_world":   ("fix the subject and action, vary the WORLD",
                         "parallel_experiment_v1", "fixed datum"),
    "parallel_subject": ("fix the world, vary the SUBJECT",
                         "parallel_experiment_v1", "fixed datum"),
    "escalation":       ("fix the world and subject, turn one DIAL",
                         "grounded_human_escalation_v1", "datum ladder"),
    "scale":            ("fix everything, vary SIZE (square-cube law)",
                         "grounded_human_escalation_v1", "datum ladder"),
    "counterfactual":   ("change one CONSTANT of nature",
                         "parallel_experiment_v1", "fixed datum"),
    "threshold":        ("hunt the exact value where behaviour FLIPS",
                         "grounded_human_escalation_v1", "datum ladder"),
}

STATUSES = ("idea", "queued", "building", "shipped", "dropped")


@dataclass
class Topic:
    key: str
    question: str                 # the primary search query, verbatim
    family: str
    hook: str                     # the computed, counterintuitive result the video exists to deliver
    quantity: str                 # what is measured, and in what unit
    reuses: str = ""              # existing solver this can borrow; "" means a new one is needed
    datum: tuple = ()             # fixed-datum cues, for parallel formats
    datum_axis: str = ""          # ladder axis, for escalation formats
    beats: tuple = ()             # the conditions/steps, in intended screen order
    status: str = "idea"
    slug: str = ""                # renders/<slug> once built -- this is what closes the loop
    notes: str = ""

    @property
    def cheap(self):
        """A topic is cheap when it borrows a solver AND holds the world fixed."""
        return bool(self.reuses) and self.family != "parallel_world"


TOPICS = [
    # ---------------------------------------------------------------- shipped
    Topic("water_worlds", "What happens if you pour water on every planet", "parallel_world",
          "Only one of six worlds leaves a puddle, and Titan's atmosphere is thicker than Earth's",
          "phase state of water (liquid/vapour/solid)",
          reuses="simulations.water_every_world.physics.boiling_c",
          datum=("glass", "ground", "rim"),
          beats=("mars", "venus", "moon", "titan", "pluto", "earth"),
          status="shipped", slug="water_every_world"),
    Topic("fly_worlds", "Could you fly on other planets", "parallel_world",
          "Titan wins, not the lowest-gravity world: thick cold air at one seventh g",
          "lift per unit weight, rho/g relative to Earth",
          reuses="simulations.fly_every_world.physics.World.ease",
          datum=("ground", "wings"),
          beats=("mars", "earth", "venus", "titan", "moon"),
          status="shipped", slug="fly_every_world"),
    Topic("jump_worlds", "How high could you jump on other planets", "parallel_world",
          "On Comet 67P a normal standing jump exceeds escape velocity -- you never land",
          "jump height and escape velocity, metres and m/s",
          reuses="simulations.jump_every_world.physics",
          datum=("ground", "surface", "dust"),
          beats=("earth", "mars", "moon", "titan", "ceres", "comet"),
          status="shipped", slug="jump_every_world",
          notes="launch plates rewritten to satisfy the zero rule; not yet regenerated"),

    # ---------------------------------------------------------------- next up
    Topic("survives_fall", "What survives a fall from the same height", "parallel_subject",
          "An ant is unhurt and a horse is not, and the reason is that terminal velocity falls as "
          "the square root of mass over area -- small things simply cannot fall hard",
          "terminal velocity in m/s and impact energy per kg",
          reuses="",           # needs a drag solver; air density constants come from the fly topic
          datum=("ledge", "ground", "the edge"),
          beats=("ant", "mouse", "cat", "human", "horse"),
          status="building", slug="survives_the_fall",
          notes="Haldane's observation is the whole video: a mouse walks away, a horse splashes. "
                "One environment for all five plates, which is why it is cheap despite a new solver."),
    Topic("armstrong_limit", "How high can you go before your blood boils", "escalation",
          "19,000 m -- less than twice a passenger jet's cruising altitude -- water boils at 37 C",
          "altitude in metres against the boiling point of water at that pressure",
          reuses="simulations.water_every_world.physics.boiling_c",
          datum_axis="altitude_m",
          beats=("2400 hypoxia", "8000 death zone", "10000 cruising", "15000", "19000 Armstrong"),
          notes="Zero new physics: boiling_c is a pure function of pressure, so feeding it the "
                "barometric profile gives the Armstrong limit directly. Same spine as the water "
                "video applied to a body, which makes it a real sequel rather than a reskin."),
    Topic("crush_depth", "How deep can you go before the pressure kills you", "escalation",
          "The mirror of the Armstrong limit, and every plate is dark water -- the cheapest plate "
          "set we could generate",
          "depth in metres against ambient pressure in atmospheres",
          reuses="",           # pressure is linear in depth; trivial solver
          datum_axis="depth_m",
          beats=("40 narcosis", "60 oxygen toxicity", "100 lung squeeze", "300 HPNS",
                 "10935 Challenger Deep")),
    Topic("air_cooks_you", "How fast can you go before the air cooks you", "escalation",
          "Stagnation temperature rises with the square of Mach number: the SR-71's skin ran near "
          "300 C",
          "Mach number against stagnation temperature, T = T0(1 + 0.2 M^2)",
          reuses="", datum_axis="speed_ms",
          beats=("mach 1", "mach 2", "mach 3", "mach 5")),
    Topic("body_scale", "What if you were ten times bigger, or one centimetre tall", "scale",
          "At 10x scale bone stress rises linearly with length and the human femur fails around "
          "4-5x: you would break your own legs standing up. At 1 cm surface tension beats you and "
          "you could not climb out of a water droplet",
          "bone stress (L^3/L^2) and the surface-tension-to-weight ratio",
          reuses="", datum=("doorway", "coin", "hand", "the floor"),
          beats=("1 cm", "10 cm", "human", "3x", "10x"),
          notes="The square-cube law is the most under-used physics in pop science and it is one "
                "subject in one room on one dial, which is the cheapest shape in the bank."),
    Topic("moon_closer", "What if the Moon were half as far away", "counterfactual",
          "Tides scale as one over r cubed, so half the distance is eight times the tide; the Roche "
          "limit sits near 18,000 km",
          "tidal amplitude against orbital radius",
          reuses="simulations.jump_every_world.physics",
          datum=("shoreline", "the beach", "the horizon"),
          beats=("today", "half distance", "quarter", "Roche limit")),
    Topic("run_on_water", "How fast would you have to run to run on water", "threshold",
          "About 30 m/s for a human -- a basilisk lizard manages it at 1.5 m/s because the "
          "requirement scales with mass",
          "the speed at which slap-and-stroke impulse equals body weight",
          reuses="", datum=("the water surface", "the shore"),
          beats=("walking", "sprinting", "30 m/s", "the lizard")),
    Topic("balloons_lift", "How many balloons would it take to lift a person", "threshold",
          "About 4,000 -- absurd, exactly computable, and the number is the whole video",
          "net lift per balloon against body weight",
          reuses="", datum=("the ground", "his feet", "the pavement"),
          beats=("10", "100", "1000", "4000")),
]

BY_KEY = {t.key: t for t in TOPICS}


def pick(status=None, family=None, cheap_only=False):
    out = TOPICS
    if status:
        out = [t for t in out if t.status == status]
    if family:
        out = [t for t in out if t.family == family]
    if cheap_only:
        out = [t for t in out if t.cheap]
    return out


def table():
    """The bank as a readable board. Sorted so the cheap unbuilt ideas surface first."""
    rows = sorted(TOPICS, key=lambda t: (STATUSES.index(t.status), not t.cheap, t.key))
    w = max(len(t.key) for t in rows)
    L = [f"{'KEY'.ljust(w)}  {'STATUS':<9} {'FAMILY':<17} {'REUSE':<6} QUESTION"]
    for t in rows:
        L.append(f"{t.key.ljust(w)}  {t.status:<9} {t.family:<17} "
                 f"{('yes' if t.reuses else 'new'):<6} {t.question}")
    return "\n".join(L)


def sync(channel="sim"):
    """Project the bank into the existing `topics` table so the UI can queue and mark them.

    Best-effort by design: the bank must stay readable with no database, so a failure here is
    reported and swallowed rather than raised. The sim-specific fields go into a jsonb column added
    on demand -- squeezing `family` into `pattern` would make the bank unqueryable, which defeats the
    point of persisting it.
    """
    try:
        import db
        # DATABASE_URL lives in .env, which nothing in sim/ loads. Without this the sync reports
        # "db not enabled" while the credentials sit on disk -- the same silent-misconfiguration
        # shape that once failed 19 image generations with the key present the whole time.
        from hotd import load_env
        load_env()
    except Exception as e:
        return {"ok": False, "reason": f"db module unavailable: {e}"}
    if not db.db_enabled():
        return {"ok": False, "reason": "db not enabled (no DATABASE_URL in env or .env)"}
    conn = None
    try:
        conn = db._conn()
        if conn is None:
            return {"ok": False, "reason": "no connection"}
        cur = conn.cursor()
        cur.execute("ALTER TABLE topics ADD COLUMN IF NOT EXISTS sim_meta jsonb")
        cur.execute("ALTER TABLE topics ADD COLUMN IF NOT EXISTS render_slug text")
        import json
        n = 0
        for t in TOPICS:
            cur.execute(
                # `curiosity` is an INTEGER score column belonging to the scraped engine, not a
                # place for prose. The hook lives in sim_meta, which is why the jsonb column exists.
                """INSERT INTO topics (channel, question, suggested_title, status,
                                       sim_meta, render_slug)
                   VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (channel, question) DO UPDATE SET
                       sim_meta    = EXCLUDED.sim_meta,
                       render_slug = COALESCE(EXCLUDED.render_slug, topics.render_slug),
                       status      = EXCLUDED.status,
                       last_seen   = now()""",
                (channel, t.question, t.question, t.status,
                 json.dumps(asdict(t)), t.slug or None))
            n += 1
        conn.commit()
        return {"ok": True, "written": n}
    except Exception as e:
        return {"ok": False, "reason": str(e)}
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    print(table())
