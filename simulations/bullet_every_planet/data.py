"""Simulation: what happens if you fire the same bullet on every planet.

Data only. Narration is §8's locked script, split at its own sentence boundaries; scene times and
overlay chips are §10's storyboard; `locked` is §6 verbatim; `motion` is the one thing that moves,
written from each scene's Visual + Required fields; `prohibited` is each scene's Prohibited list.
"""
from __future__ import annotations
import os

from sim.spec import Scene, Simulation

ROOT = os.path.dirname(os.path.abspath(__file__))

# §6 locked experiment parameters. Injected verbatim into EVERY i2v prompt, because the comparison is
# the product: if the launcher or camera changes between worlds, the video stops meaning anything.
LOCKED = {
    "projectile": "one small copper bullet",
    "direction": "always left to right",
    "launcher": "the same white-and-teal robotic launcher",
    "view": "fixed side-on",
    "angle": "flat, identical every shot",
}

STYLE = "Photoreal cinematic 3D render, dramatic planetary light, clean glowing trail, 9:16."

SCENES = [
    Scene(id="cold_open", image="09_pluto_return_payoff", seconds=2.3,
          narration="This bullet could circle Pluto, and come back toward Bolt.",
          onscreen="IT COMES BACK?",
          motion=("The glowing bullet completes a long curving orbit around the icy world and comes "
                  "back toward the small white robot, who turns his head to watch it approach; the "
                  "curved trail stays bright behind it"),
          prohibited=("impact", "explosion", "collision")),
    Scene(id="lock", image="00_setup_bolt_launcher", seconds=2.2,
          narration="But first: same projectile, same speed, same angle, on every planet.",
          onscreen="SAME SHOT",
          motion=("The small white robot presses a large round control pad once and the robotic "
                  "launcher powers up, its teal lights brightening in sequence; the bullet sits "
                  "ready at the muzzle"),
          prohibited=("robot holding a weapon", "robot chasing anything")),
    Scene(id="earth", image="01_earth_baseline", seconds=2.8,
          narration="Earth is the baseline. Gravity bends the path while air slows it down.",
          chips=("EARTH", "1.00g · AIR"),
          motion=("The bullet fires from the launcher and arcs left to right across the blue sky in "
                  "a familiar descending curve, its glowing trail thinning and fading as it slows"),
          prohibited=("windsock", "robot chasing the projectile")),
    Scene(id="venus", image="02_venus_dense_air", seconds=3.2,
          narration="Venus has almost Earth-like gravity, but its crushing atmosphere kills the speed fast.",
          chips=("VENUS", "0.90g · THICK AIR"),
          motion=("The bullet fires and immediately slows in the heavy orange haze, its glowing "
                  "trail compressing and dropping away steeply after a very short distance while "
                  "thick clouds churn slowly behind it")),
    Scene(id="mars", image="03_mars_long_arc", seconds=3.0,
          narration="Mars has weak gravity and thin air, so the arc stretches much farther.",
          chips=("MARS", "0.38g · THIN AIR"),
          motion=("The bullet fires and sails in a long shallow arc far across the red desert toward "
                  "distant cliffs, its glowing trail staying bright and stretching much farther than "
                  "before, fine dust drifting low over the ground")),
    Scene(id="mercury", image="04_mercury_farthest_rocky_world", seconds=3.0,
          narration="Mercury has almost no air and the same weak gravity. It wins the rocky worlds.",
          chips=("MERCURY", "0.38g · NO AIR"),
          motion=("The bullet fires and travels in an almost perfectly straight bright line across "
                  "the airless grey cratered plain, the trail undiminished all the way to the far "
                  "horizon under harsh sunlight")),
    Scene(id="ground_gone", image="05_jupiter_downward_hook", seconds=1.9,
          narration="Then the ground disappears.",
          onscreen="NO SURFACE",
          motion=("Vast banded orange cloud tops roll and churn slowly below the platform while the "
                  "bullet hangs at the start of its arc, the great storm turning beneath it"),
          prohibited=("solid ground", "rocky surface", "impact")),
    Scene(id="jupiter", image="05_jupiter_downward_hook", seconds=3.2,
          narration="Jupiter's stronger gravity hooks the shot down into the clouds.",
          chips=("JUPITER", "2.53g · NO SURFACE"),
          motion=("The bullet fires and its glowing trail hooks sharply downward, curving hard into "
                  "the churning orange cloud bands and disappearing into the deep red storm below"),
          prohibited=("solid ground", "impact", "landing")),
    Scene(id="saturn", image="06_saturn_longer_cloud_descent", seconds=2.4,
          narration="Saturn, Uranus and Neptune change the curve,",
          chips=("SATURN", "1.07g · NO SURFACE"),
          motion=("The bullet fires and traces a broad sweeping arc that bends gradually down into "
                  "the pale swirling cloud tops, the ringed planet hanging still behind it"),
          prohibited=("solid ground", "impact")),
    # Visual beat, no narration: §8's script names three ice/gas giants in one sentence, and the
    # script is locked. Rather than rewrite it, Uranus gets a silent 1.5s beat between the two
    # clauses -- which also tightens the outcome cadence the spec gates on.
    Scene(id="uranus", image="07_uranus_haze_descent", seconds=1.3,
          narration="",
          chips=("URANUS", "0.89g · NO SURFACE"),
          motion=("The bullet fires and its glowing trail bends gently downward into the pale "
                  "blue-green haze, thin banded cloud drifting slowly across the frame"),
          prohibited=("solid ground", "impact")),
    Scene(id="neptune", image="08_neptune_wind_bend", seconds=2.6,
          narration="but none gives the bullet a surface to hit.",
          chips=("NEPTUNE", "1.14g · NO SURFACE"),
          motion=("The bullet fires and its trail is bent sideways and downward by ferocious winds, "
                  "curving into the deep blue storm bands which streak past below it"),
          prohibited=("solid ground", "impact")),
    Scene(id="pluto_setup", image="09_pluto_return_payoff", seconds=3.0,
          narration="Now the dwarf-planet bonus: Pluto. Almost no air. Tiny gravity. A curved horizon.",
          chips=("PLUTO", "0.06g · ALMOST NO AIR"),
          motion=("The bullet fires low and flat across the pale icy surface, its bright trail "
                  "running far ahead and beginning to follow the tight curve of the small world's "
                  "horizon, stars steady overhead")),
    # Split so no shot exceeds the spec's 3.3s outcome cap. The split point preserves BOTH §7
    # required qualification phrases intact: "at the right speed, altitude and angle" and
    # "could theoretically". Neither may be broken across a cut.
    Scene(id="pluto_orbit_a", image="09_pluto_return_payoff", seconds=2.3,
          narration="At the right speed, altitude and angle,",
          chips=("PLUTO", "THEORETICAL ORBIT"),
          onscreen="COULD THEORETICALLY",
          motion=("The glowing bullet races low across the curved icy horizon, its bright trail "
                  "bending to follow the small world's curvature far into the distance"),
          prohibited=("impact", "explosion")),
    Scene(id="pluto_orbit_b", image="09_pluto_return_payoff", seconds=3.3,
          narration="the bullet could theoretically enter a low orbit and circle back toward where it started.",
          motion=("The glowing bullet completes a full orbit around the small icy world and returns "
                  "into frame from behind the small white robot, the complete circular trail glowing "
                  "all the way around the horizon as he turns to watch"),
          prohibited=("impact", "explosion")),
    Scene(id="resolution_a", image="00_setup_bolt_launcher", seconds=1.6,
          narration="Same shot. Different world.",
          onscreen="SAME SHOT. DIFFERENT WORLD.",
          motion=("The row of planet icons above the small white robot lights up one after another "
                  "in sequence, teal panel lights pulsing softly"),
          prohibited=("robot holding a weapon",)),
    Scene(id="resolution_b", image="01_earth_baseline", seconds=2.4,
          narration="Gravity and atmosphere decide everything.",
          motion=("The bullet arcs left to right across the blue sky one more time, the glowing "
                  "trail drawing the familiar Earth baseline curve"),
          prohibited=("robot holding a weapon",)),
]

SIM = Simulation(
    slug="bullet_every_planet",
    title="What If You Fired the Same Bullet on Every Planet?",
    root=ROOT, scenes=SCENES, locked=LOCKED, style=STYLE,
    # §8 sets 175-185 wpm. Measured at speed 1.0 this voice delivers ~137 wpm, which ran the
    # 41s script to 56s and pushed 9 of 16 scenes past the 3.3s outcome cap.
    # The spec is internally inconsistent: 149 locked words at its own 175-185 wpm is 48-51s of
    # speech, against a claimed ~41s and a 39-43s band. Hitting the RUNTIME band requires ~218 wpm.
    # Runtime wins -- it is the platform constraint and the band is stated twice in the spec.
    # Natural delivery, matching explainer_pipeline (tts-1-hd / echo at 1.0). The previous 1.42 was
    # chasing a runtime band the spec itself cannot satisfy: 149 words at its own stated 175-185 wpm
    # is 48-51s of speech against a claimed 41s. Rushing the read to hit an impossible number was
    # the wrong trade -- the delivery is what the viewer actually experiences.
    # 1.0 reads at ~166 wpm and runs 58.5s; 1.08 sits inside the spec's own 175-185 wpm band and
    # still sounds unhurried. The 36-43s runtime band is simply not reachable with 149 words at any
    # natural delivery -- that is a defect in the spec, not something to fix by rushing the read.
    speed=1.08,
    pad_s=0.16,
    target_s=(36.0, 43.0),
    meta={
        "title": "What If You Fired the Same Bullet on Every Planet?",
        "hashtags": "#space #physics #science #planets #simulation",
        "tags": ["space", "physics", "planets", "gravity", "atmosphere", "simulation",
                 "science shorts", "solar system", "what if"],
    })
