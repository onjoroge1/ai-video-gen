"""Build the five-minute Hippo V4 contract while preserving the accepted 0:00–0:45 bytes."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import directed_longform as dl  # noqa: E402


PILOT = ROOT / "spec" / "hippo_illustrated_story_v4.json"
OUTPUT = ROOT / "spec" / "hippo_illustrated_story_v4_full_5m.json"


BEATS = [
    {
        "scene_id": "s6_two_crises", "start_sec": 45.0, "end_sec": 77.5,
        "world_id": "historical_1910", "story_role": "two real crises",
        "claim_ids": ["F01", "F04"],
        "narration": (
            "So why did serious people consider it? Start with two real problems. Working families "
            "were furious about rising meat prices. Louisiana's waterways were clogged by water "
            "hyacinth, an imported plant that spread into floating mats, slowed boats, and resisted "
            "removal. Representative Robert Broussard saw expensive protein, unwanted vegetation, "
            "and miles of warm wet habitat. On paper, they seemed to click together: feed the weeds "
            "to a giant animal, then feed the animal to America."
        ),
        "visuals": [
            "working family counts coins beside a nearly empty 1910 market basket",
            "butcher changes a blank price tile as customers react",
            "macro ledger of household food costs with coins and wrapped parcels",
            "busy street crowd studies a butcher window",
            "Louisiana skiff trapped behind a wall of water hyacinth",
            "overhead bayou map filling with green plant mats",
            "fisher pulls an oar through tangled invasive plants",
            "workers drag heavy wet hyacinth onto a barge",
            "Broussard studies two problem photographs on his desk",
            "split tableau of costly food and blocked waterways",
            "two puzzle-piece diagrams approach each other without touching",
            "hippo-shaped marker lands between meat ledger and bayou map",
            "absurd machine diagram links weeds, hippo, and dinner plate",
        ],
    },
    {
        "scene_id": "s7_the_pitch", "start_sec": 77.5, "end_sec": 115.0,
        "world_id": "historical_1910", "story_role": "seductive congressional pitch",
        "claim_ids": ["F01", "F02", "F03", "F05"],
        "narration": (
            "In March 1910, Broussard brought House Resolution 23261 before the House Agriculture "
            "Committee. It asked for two hundred fifty thousand dollars to import useful wild "
            "animals. Hippos were the star: put them in Louisiana and Florida, let them consume the "
            "plant, and turn their enormous bodies into affordable meat. Supporters softened the "
            "shock with a brilliant nickname—lake cow bacon. The phrase made a dangerous African "
            "megaherbivore sound like something that already belonged beside eggs at breakfast."
        ),
        "visuals": [
            "motion through a 1910 corridor toward Broussard carrying a bill folder",
            "close portrait of Broussard placing the proposal on a committee desk",
            "top-down document composition with exact title area left blank",
            "committee members lean toward a large Gulf Coast map",
            "period money appropriation diagram with stacks of coins",
            "cargo ship route arcs from Africa toward the Gulf Coast",
            "hippos step from a transport illustration into Louisiana wetlands",
            "Florida and Louisiana highlighted on a relief map",
            "plant mat transforms into a hippo silhouette in a visual equation",
            "covered breakfast plate receives a hypothetical bacon package",
            "newspaper illustrator sketches the friendly lake-cow nickname",
            "visual joke of a hippo squeezed into a pastoral cattle engraving",
            "serious witness points to a waterfront-farm model",
            "committee clerk compares animal scale to a human silhouette",
            "breakfast table normalizes the impossible package in alternate history",
        ],
    },
    {
        "scene_id": "s8_bigger_plan", "start_sec": 115.0, "end_sec": 145.0,
        "world_id": "historical_1910", "story_role": "national ambition escalation",
        "claim_ids": ["F01", "F05"],
        "narration": (
            "And the plan did not stop at hippos. Witnesses imagined a redesigned American food "
            "system stocked with animals from around the world: antelope on family farms, African "
            "buffalo in the West, yaks in the Rockies, even rhinoceroses in the Southwest. To "
            "supporters, disgust was just habit wearing a costume. Cattle had once been foreign too. "
            "If Americans learned to call a hippo a lake cow, perhaps taste and commerce would do "
            "the rest. For a country anxious about food, it was a seductive promise: no sacrifice, "
            "only abundance."
        ),
        "visuals": [
            "large United States map unfolds across the committee wall",
            "antelope icons populate tidy eastern farm plots",
            "African buffalo silhouettes spread across a western range",
            "yak caravan appears along snowy Rocky Mountain ridges",
            "rhinoceros proposal marker rests over a desert landscape",
            "committee room becomes a visual menagerie around Broussard",
            "family farm engraving morphs into an exotic animal collage",
            "cattle portrait and hippo portrait hang as parallel imports",
            "skeptical diner faces two covered plates in a visual joke",
            "merchant imagines refrigerated railcars carrying new products",
            "bright abundance board crowds with impossible animal choices",
            "Broussard stands before the completed continental redesign",
        ],
    },
    {
        "scene_id": "s9_two_questions", "start_sec": 145.0, "end_sec": 180.0,
        "world_id": "historical_1910", "story_role": "committee challenge and reversal",
        "claim_ids": ["F06", "F07"],
        "narration": (
            "Then the committee reached two practical questions. Could hippos be contained on "
            "ordinary farms? And would they actually live on water hyacinth? Broussard's witnesses "
            "answered yes. That completed the machine: plant becomes hippo; hippo becomes meat; two "
            "problems disappear. But modern biology flips the diagram. Hippos spend daylight in "
            "water, yet usually leave it at night to graze grass, sometimes traveling miles. Water "
            "hyacinth is about ninety-five percent water. A herd could chew enormous bulk and still "
            "go searching on land for real fuel."
        ),
        "visuals": [
            "motion across a silent committee table toward two blank question cards",
            "close-up of a lawmaker pointing toward a farm fence model",
            "second lawmaker lifts a jar of water hyacinth",
            "witness confidently checks yes on two blank boxes",
            "clean promise diagram shows plant turning into hippo",
            "same diagram continues from hippo to covered dinner plate",
            "bright promise board rotates toward a darker evidence side",
            "daytime hippos rest shoulder-deep in water",
            "night cutaway shows hippos climbing onto a grassy bank",
            "overhead tracking diagram traces a long grazing route",
            "macro cross-section of watery hyacinth stems",
            "balance scale compares huge wet plant bulk with little energy",
            "hungry herd leaves a plant-choked channel for pasture",
            "committee promise diagram fractures along the diet assumption",
        ],
    },
    {
        "scene_id": "s10_new_problem", "start_sec": 180.0, "end_sec": 220.0,
        "world_id": "counterfactual_gulf", "story_role": "informed alternate-America consequence",
        "claim_ids": ["F06", "F07"],
        "narration": (
            "Now picture the first Louisiana herd after the novelty fades. The animals do not stay "
            "politely inside a carpet of weeds. They climb banks, cross roads, enter crops, and move "
            "toward new waterways. An adult hippo is territorial, immensely powerful, and dangerous "
            "around boats and shorelines. A cattle fence is not proof against an animal weighing "
            "several thousand pounds. Their waste also carries nutrients from land into water, where "
            "concentrated inputs can alter algae, oxygen, fish, and water quality. The proposed cure "
            "could become a second invasive problem—mobile, breeding, and much harder to remove than "
            "a floating plant."
        ),
        "visuals": [
            "counterfactual Louisiana herd leaves the bayou after sunset",
            "low bank view of hippos climbing toward a grassy field",
            "farmer's lantern reveals tracks through a crop row",
            "night road headlights stop before a hippo crossing",
            "wide aerial shows several waterways connected by grazing paths",
            "massive hippo leans against a cattle-scale fence",
            "broken fence rail lies beside deep muddy footprints",
            "small skiff rounds a bend toward a territorial animal",
            "shoreline family retreats from an unexpected hippo",
            "map markers spread outward from the first ranch",
            "cross-section shows nutrients moving from grassland into river",
            "microscope-inspired view of algae increasing in green water",
            "fish silhouettes gather near a low-oxygen warning zone",
            "plant problem card gains a second moving hippo problem card",
            "maintenance crew faces both weeds and a breached enclosure",
            "alternate-America emergency map fills with connected incidents",
        ],
    },
    {
        "scene_id": "s11_colombia", "start_sec": 220.0, "end_sec": 265.0,
        "world_id": "modern_evidence", "story_role": "real-world analogue",
        "claim_ids": ["F08", "F09"],
        "narration": (
            "That is an informed counterfactual, not a prediction. But Colombia has run part of the "
            "experiment. In the 1980s, Pablo Escobar imported four hippos for a private zoo. After "
            "his death, the animals were difficult to capture, so they remained. They bred. Some "
            "left the estate, and descendants spread through the Magdalena River basin. Scientists "
            "have documented rapid growth and warned about disturbed habitat, changed water "
            "chemistry, conflict with people, and pressure on native species. Colombia has tried "
            "sterilization, relocation, confinement, and plans for euthanasia—each costly, difficult, "
            "or politically painful. Four founders needed only warm water, grass, room, and time."
        ),
        "visuals": [
            "motion match cut from fictional Louisiana water to Colombia river basin",
            "1980s estate gate opens toward a private zoo lake",
            "four hippos stand as distinct founders in a wide landscape",
            "abandoned enclosure remains after people and other animals leave",
            "mother and calf establish a new family group",
            "young hippo follows a river channel beyond the estate",
            "satellite-style basin map lights up downstream locations",
            "timeline multiplies four silhouettes into many generations",
            "scientists collect water samples from a small boat",
            "laboratory vials compare clearer and nutrient-rich water",
            "native wildlife shares a narrowing riverbank",
            "local road user watches a hippo emerge at dusk",
            "veterinary team prepares a field sterilization procedure without gore",
            "transport crate and crane show the scale of relocation",
            "reinforced confinement paddock requires heavy infrastructure",
            "public meeting divides over difficult management choices",
            "four icons sit beside the sprawling river network they began",
        ],
    },
    {
        "scene_id": "s12_decision", "start_sec": 265.0, "end_sec": 287.5,
        "world_id": "historical_1910", "story_role": "documented congressional outcome",
        "claim_ids": ["F11"],
        "narration": (
            "Back in Washington, the committee remained unconvinced and shelved the proposal. "
            "There was no dramatic national vote, and no documented near-miss by a handful of "
            "ballots. The real ending was quieter: practical questions went unanswered, priorities "
            "changed, and the folder stopped moving. That anticlimax may be the point. History is not "
            "only made by heroic rescues. Sometimes a strange future disappears because skeptical "
            "people refuse to turn a confident idea into infrastructure."
        ),
        "visuals": [
            "committee members exchange skeptical looks after testimony",
            "empty witness chair faces unanswered question cards",
            "clerk closes the H.R. 23261 folder",
            "wide committee room empties without a vote",
            "bill folder enters an archive shelf instead of a ballot box",
            "newspaper fantasy of victory dissolves before printing",
            "unused Louisiana ranch blueprint gathers dust",
            "ordinary bayou remains without hippo infrastructure",
            "quiet archive corridor holds the future that stopped",
        ],
    },
    {
        "scene_id": "s13_final_callback", "start_sec": 287.5, "end_sec": 300.0,
        "world_id": "counterfactual_gulf", "story_role": "opening callback and final meaning",
        "claim_ids": [],
        "narration": (
            "Return to the ordinary burger from the opening. Hippo meat was never the impossible "
            "part. The impossible promise was importing a powerful animal and receiving only the "
            "benefit. Our world is shaped by plans that worked—and by the weird futures that never "
            "made it off the page."
        ),
        "visuals": [
            "ordinary cookout burger returns in an exact thematic callback",
            "ghosted lake-cow package appears beside it then fades",
            "bayou ranch and grocery aisle collapse into blueprint lines",
            "archived proposal page closes over the alternate timeline",
            "wide real American cookout continues without the imagined product",
        ],
    },
]


COMPOSITIONS = (
    "wide establishing", "tight human close-up", "over-shoulder", "macro insert",
    "high overhead", "low-angle environmental", "symmetrical diagram", "deep three-quarter",
    "telephoto reaction", "oblique tabletop", "water-level", "graphic split-frame",
)


EVIDENCE = [
    ("F01", "Robert F. Broussard introduced a federal hippo-import proposal in 1910.",
     "https://history.house.gov/People/Detail/9939", "Use proposed or introduced; never nearly passed."),
    ("F02", "H.R. 23261 was discussed by the House Agriculture Committee in March 1910.",
     "https://babel.hathitrust.org/cgi/pt?id=nyp.33433008733986&seq=341&view=1up",
     "Preserve the document number and historical setting."),
    ("F03", "The proposal sought a 250,000-dollar federal appropriation.",
     "https://www.smithsonianmag.com/history/how-the-us-almost-became-a-nation-of-hippo-ranchers-180982244/",
     "Do not add a time-sensitive modern conversion in narration."),
    ("F04", "Meat-price anxiety and invasive water hyacinth drove the public pitch.",
     "https://www.smithsonianmag.com/history/how-the-us-almost-became-a-nation-of-hippo-ranchers-180982244/",
     "Describe them as important pressures, not the only national concerns."),
    ("F05", "Lake cow bacon was promotional language associated with the proposal.",
     "https://www.smithsonianmag.com/history/how-the-us-almost-became-a-nation-of-hippo-ranchers-180982244/",
     "All branded packages are clearly counterfactual illustrations."),
    ("F06", "Hippos usually leave water at night to graze grass.",
     "https://animals.sandiegozoo.org/animals/hippo",
     "Do not claim hippos never consume aquatic plants."),
    ("F07", "Water hyacinth is roughly 95 percent water and poor primary feed.",
     "https://www.smithsonianmag.com/history/how-the-us-almost-became-a-nation-of-hippo-ranchers-180982244/",
     "Present this as modern evidence unavailable to the witnesses."),
    ("F08", "Colombia's invasive hippos descended from four imported animals and dispersed.",
     "https://doi.org/10.1017/S0030605318001588",
     "Use Colombia as an analogue, never proof of an identical Louisiana outcome."),
    ("F09", "Research documents growth and ecological-management concerns in Colombia.",
     "https://pmc.ncbi.nlm.nih.gov/articles/PMC10106455/",
     "Avoid unsupported live population counts."),
    ("F11", "The committee did not advance the proposal.",
     "https://www.smithsonianmag.com/history/how-the-us-almost-became-a-nation-of-hippo-ranchers-180982244/",
     "Explicitly reject the near-passage legend."),
]


def build() -> dict:
    pilot = json.loads(PILOT.read_text(encoding="utf-8"))
    payload = copy.deepcopy(pilot)
    payload["project_id"] = "hippo-illustrated-story-v4-full-5m"
    payload["title"] = "What If America Had Adopted Hippo Meat? — Full Illustrated History"
    payload["target"].update({"duration_sec": 300.0, "max_cost_usd": 7.0})
    payload["acceptance"].update({
        "runtime_tolerance_sec": 12.0,
        "max_unique_master_assets": 117,
        "planned_bolt_appearances": 2,
    })
    payload["worlds"] = [
        *pilot["worlds"],
        {
            "world_id": "historical_1910", "start_sec": 45.0, "end_sec": 180.0,
            "base_prompt": (
                "Premium editorial illustrated history grounded in 1910 materials, clothing and "
                "architecture; cinematic depth, tactile ink and paper, varied camera scales, no fake archive."),
            "on_screen_label": "GENERATED ILLUSTRATION — 1910",
        },
        {
            "world_id": "counterfactual_gulf", "start_sec": 180.0, "end_sec": 220.0,
            "base_prompt": (
                "Cinematic alternate-history Gulf Coast simulation, plausible ecology and infrastructure, "
                "premium editorial realism, consequences visibly hypothetical, no disaster sensationalism."),
            "on_screen_label": "COUNTERFACTUAL SIMULATION",
        },
        {
            "world_id": "modern_evidence", "start_sec": 220.0, "end_sec": 265.0,
            "base_prompt": (
                "Modern Colombia evidence sequence in premium editorial illustration, specific river ecology, "
                "research and management work, respectful documentary framing, no fake news footage."),
            "on_screen_label": "MODERN COLOMBIA — ILLUSTRATED EVIDENCE",
        },
        {
            "world_id": "historical_1910", "start_sec": 265.0, "end_sec": 287.5,
            "base_prompt": (
                "Premium editorial illustrated history grounded in 1910 materials, clothing and "
                "architecture; cinematic depth, tactile ink and paper, varied camera scales, no fake archive."),
            "on_screen_label": "GENERATED ILLUSTRATION — 1910",
        },
        {
            "world_id": "counterfactual_gulf", "start_sec": 287.5, "end_sec": 300.0,
            "base_prompt": (
                "Cinematic alternate-history Gulf Coast simulation, plausible ecology and infrastructure, "
                "premium editorial realism, consequences visibly hypothetical, no disaster sensationalism."),
            "on_screen_label": "COUNTERFACTUAL SIMULATION",
        },
    ]
    payload["narration"].extend({key: value for key, value in beat.items() if key != "visuals"}
                                for beat in BEATS)
    payload["evidence"] = [
        {"claim_id": claim_id, "claim": claim, "source_uri": uri,
         "qualification": qualification,
         "license": "citation-only factual source; no source media reused"}
        for claim_id, claim, uri, qualification in EVIDENCE
    ]

    beat_by_time = {beat["start_sec"]: beat for beat in BEATS}
    continuation = []
    cursor = 45.0
    shot_index = 19
    motion_starts = {90.0, 150.0, 220.0}
    while cursor < 300.0 - 0.001:
        beat = next(item for item in BEATS
                    if item["start_sec"] <= cursor < item["end_sec"])
        duration = 5.0 if cursor in motion_starts else 2.5
        end = min(cursor + duration, beat["end_sec"])
        local_index = int(round((cursor - beat["start_sec"]) / 2.5))
        visual = beat["visuals"][local_index % len(beat["visuals"])]
        composition = COMPOSITIONS[(shot_index - 19) % len(COMPOSITIONS)]
        motion = cursor in motion_starts
        continuation.append({
            "shot_id": f"v4f_{shot_index:03d}",
            "start_sec": cursor, "end_sec": end,
            "visual": visual,
            "mode": "Full motion" if motion else "Still",
            "world_id": beat["world_id"], "scene_id": beat["scene_id"],
            "asset_key": f"v4f_master_{shot_index:03d}",
            "asset_prompt": (
                f"{composition} composition: {visual}. Materially distinct subject, camera position, "
                "foreground and background from adjacent shots; no generated readable text."),
            "transformation": (
                "five-second semantic motion with natural subject action and camera travel"
                if motion else f"2.5-second {composition} editorial hold with restrained camera path"),
            "claim_ids": list(beat["claim_ids"]), "reference_ids": [],
            "overlay_text": (
                "TWO QUESTIONS CHANGE THE STORY" if cursor == 145.0 else
                "COLOMBIA RAN PART OF THE EXPERIMENT" if cursor == 220.0 else
                "THE COMMITTEE SHELVED IT" if cursor == 265.0 else ""),
            "labels": (["full_motion", "causal_turn"] if motion else []),
        })
        cursor = end
        shot_index += 1
    payload["shots"].extend(continuation)
    payload["prohibited_claims"].extend([
        "Do not state that the proposal passed committee or came within a few votes.",
        "Do not claim Colombia proves Louisiana would have produced an identical outcome.",
        "Do not state a current Colombia population count without a newly verified source.",
        "Do not present generated historical or Colombia imagery as archival footage.",
    ])
    report = dl.validate_directed_spec(payload)
    if not report["valid"]:
        raise RuntimeError(json.dumps(report["issues"], indent=2))
    return report["normalized_spec"]


if __name__ == "__main__":
    contract = build()
    OUTPUT.write_text(json.dumps(contract, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report = dl.validate_directed_spec(contract)
    remaining = dl.window_cost_estimate(contract, 45.0, 300.0)
    print(json.dumps({
        "output": str(OUTPUT.relative_to(ROOT)),
        "spec_sha256": report["spec_sha256"],
        "shots": report["shot_count"],
        "unique_masters": report["cost_estimate"]["unique_master_assets"],
        "full_estimate": report["cost_estimate"]["estimated_total_usd"],
        "remaining_estimate": remaining["estimated_total_usd"],
    }, indent=2))
