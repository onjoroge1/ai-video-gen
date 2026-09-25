# Dinosaurs Fed Their Babies. We Found the Nursery. — vertical Short

**Status:** in production from `spec/dino_parents_short.json` through `scripts/keyframe_short.py`.
Every factual line is a research candidate until the claim ledger accepts it; the narration was
written to stay inside what the fossil record is generally read to support, and to hedge where
the reading is an inference.

**Lane:** nature explainer (the "how animals feed their young" tier), not World or History: there
is no human intervention in this story. **Format:** 9:16, six clips, ~40 s, Kling 3 Pro start+end
frame conditioning, one caption per beat in the safe zone, `onyx` narration, "nostalgic" bed, no
tail fade, dissolve back into the first frame to loop.

**Hook / title split.** Thumbnail shows the nest with the adult's head lowered over hatching eggs
and bakes only the word NURSERY. Title carries the setup: *Dinosaurs Fed Their Babies. We Found
the Nursery.* Neither resolves the other.

## Beats

| # | Caption | Narration | Start → end frame | Reads silent as |
|---|---|---|---|---|
| 1 | MONTANA · LATE CRETACEOUS | Seventy-six million years ago, a mother came back to the nest. | Adult Maiasaura over an intact clutch in a nesting colony → the eggs cracking, hatchlings emerging | A big animal tending a nest |
| 2 | HATCHED HELPLESS | Dinosaurs laid eggs. And in this nest, the babies hatched helpless. | One cracked egg → the hatchling's head and forelimb out of the shell | Birth from an egg |
| 3 | THE FOOD CAME TO THEM | Maiasaura hatchlings had worn teeth but legs too weak to leave the nest. So the food came to them. The mother carried in plants, and the nest became a nursery. | Adult's head enters with ferns over six begging hatchlings → hatchlings chewing, adult withdrawn | The parent delivered food |
| 4 | NOT A THIEF · A PARENT | In the Gobi Desert, a feathered oviraptor was found sitting on its eggs, arms spread over them like a bird. Scientists had named it the egg thief. It was the parent. | Feathered oviraptorid beside a ring of eggs → settled on the clutch, arms spread | Brooding |
| 5 | NOT EVERY PARENT STAYED | Not every dinosaur stayed. In Argentina, giant sauropods laid eggs by the thousand and walked away. | Titanosaur in the foreground of an egg-covered plain → tiny on the horizon, eggs left behind | Abandonment as strategy |
| 6 | THE OLDEST NURSERY | Birds are their living descendants. Watch a hen settle on her chicks, and you are watching a habit older than the birds themselves. | Six hatchlings awake beside the adult's flank at dusk → curled asleep against it | Care, then the loop |

## Claim ledger

| # | Claim | Where | Notes |
|---|---|---|---|
| C1 | Maiasaura nesting colonies are known from the Two Medicine Formation, Montana ("Egg Mountain"), Late Cretaceous, roughly 76 million years ago. | VO 1, caption 1 | Horner & Makela 1979 is the origin paper. The "seventy-six million" figure needs a dated source for the Two Medicine horizon; if the accepted date differs, change the number in the narration and re-record beat 1. |
| C2 | Dinosaurs reproduced by laying eggs; hatchlings of Maiasaura were small (tens of centimetres). | VO 2 | Uncontroversial. |
| C3 | Maiasaura nestlings show tooth wear alongside incompletely ossified limb joints, read as evidence that they stayed in the nest while eating, implying food was brought to them. | VO 3 | This is the interpretive heart of the Short. The narration says "the food came to them" and "the mother carried in plants", which states the inference as a conclusion. If the ledger rates the parental-provisioning reading as contested, soften to "the evidence suggests food was brought to them" and re-record beat 3. |
| C4 | An oviraptorid (Citipati) skeleton was found in the Gobi in a brooding posture over its clutch, arms spread over the eggs. | VO 4, clip 4 | Norell et al. 1995 (Nature). "Feathered" is supported for oviraptorids generally; the brooding specimen itself does not preserve feathers, so the visual asserts feathers on phylogenetic grounds. |
| C5 | The name Oviraptor ("egg thief") came from the 1920s reading that the animal was raiding Protoceratops eggs; the eggs were later shown to be its own kind. | VO 4 | Osborn 1924 naming; reinterpretation with the 1990s embryo find. VO says "scientists had named it the egg thief", which is accurate for the genus name even though the brooding specimen is Citipati. Acceptable simplification? Flag for the editor. |
| C6 | Titanosaur nesting grounds at Auca Mahuevo, Argentina, preserve thousands of eggs, some with embryos; no evidence of parental care at the site. | VO 5, clip 5 | Chiappe et al. 1998. "Walked away" is the standard reading (no adult remains, no brooding traces) but it is an absence-of-evidence argument; the VO says "walked away" plainly. Acceptable for a contrast beat, flag for the editor. |
| C7 | Birds are living dinosaurs; brooding and nest care in birds and crocodilians brackets the behaviour as ancestral. | VO 6 | The last line "a habit older than the birds themselves" rests on the bracket argument plus C3/C4. |

Numbers in the narration: one (C1's date). Everything else is qualitative on purpose.

## Cost plan

| Item | Count | Unit | Subtotal |
|---|---|---|---|
| Stills, start + end | 12 | ~$0.05 | ~$0.58 |
| Narration + Whisper timing | 6 | ~$0.02 | ~$0.10 |
| Kling 3 Pro clips (5 s or 10 s, decided by the measured narration) | 6 | $0.56 / $1.12 | $3.36 – $6.72 |
| **First-pass total** | | | **~$4 – $7.40** |

Hard cap $10.00, at most two candidates per clip. The ledger at `renders/dino_parents/ledger.json`
records actual spend per stage and every fal request id.
