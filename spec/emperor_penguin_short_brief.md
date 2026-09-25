# Why This Penguin Leaves Her Only Egg — Nature channel Short, revision 2, for approval

**Status:** revised after review on 2026-09-24. No clip has been bought. Paid so far: narration
timing in the intended voice, and the two storyboard-test still pairs the review asked for
(about 25 cents in all). Story payload `spec/emperor_penguin_story.json`, render spec
`spec/emperor_penguin_short.json`.

## What changed, and why

- **The accusation is gone.** The first draft claimed "the lists file her under the worst parents".
  Read in full, the two lists do not make that accusation of the mother: one describes the father
  and a rolling egg, the other presents her trip as strategy. The channel contract now names
  "invented reputations" as an exclusion, and the story is compiled to a new sibling engine,
  `strange_behaviour`, whose premise is that the behaviour merely looks like abandonment and
  whose function map has no verdict-shaped function at all. It cannot be satisfied by inventing a
  reputation. The engine, its fact map, its score row and its tests shipped with this revision.
- **The 1949 detour is gone.** The opening already puts the egg on his feet, so "the bird on the
  egg was the father" was not a reveal. The freed time carries the complication the review
  named: a chick that hatches before she returns, and what the father can do about it.
- **Shots, not takes.** Each beat is now one or more shots cut at natural speed, each
  contributing only a named window. No shot asks one generation to carry weeks of change. The
  assembler was rewritten for this; the earlier remap behaviour is kept only for the two older
  Shorts that were built on it.
- **Three source gates.** Every claim below carries `found`, `read`, or `confirms exact claim`.
  Offline validation checks the story's shape; it says nothing about truth, and the two are now
  kept apart in the channel contract.

**One question under the whole video:** *Why does she leave her only egg?*

## 1. Hooks

1. **An emperor penguin hands over her only egg, and leaves for about two months.** (selected)
2. Dad keeps the egg. Mum leaves. And that is the only way this chick eats.
3. The most famous father in nature only has the job because his mate walked away.
4. One egg, one parent, and a two-month walk to the nearest food.
5. She lays it, hands it over, and goes. Watch what happens if the chick hatches first.

**Selected: hook 1**, as the review proposed: the behaviour stated flat, the animal named in the
first three words, and no verdict claimed for anyone. Hook 5 is the runner-up because it points
at the middle complication, but it promises a conditional the viewer has no reason to care about
yet.

## 2. Narration

**105 words · 33.7 s spoken (onyx, measured) · 37.7 s with picture pads**

> An emperor penguin hands over her only egg, and leaves for about two months.
>
> Dad keeps it warm on his feet. But he can't go hunting with it.
>
> So she heads to sea to feed.
>
> Meanwhile, he hasn't eaten for months.
>
> And if the chick hatches before she gets back?
>
> He can briefly feed it a milk-like substance made in his throat.
>
> Then she returns with food and takes over keeping the chick warm. Dad finally gets to eat.
>
> For the chick's first weeks, they take turns. One keeps it warm; the other finds food.
>
> She didn't abandon the family. She came back with dinner.

This is the review's script with two tiny changes for the voice: the ellipsis after "egg" is a
comma, and the colon in the turn-taking line is a full stop, both because the TTS paused too
long on them. "Hands over" replaces "rolls it onto her mate's feet", so no generator is invited to
draw a loose egg on open ice; the transfer is shown with the egg already on his feet.

## 3. Beat and shot table

Measured narration plus a 0.45 s pad per beat. Every shot is a 5-second Kling 3 Pro generation
cut to the window shown, at natural speed. A beat whose shots run short holds its last frame; one
that runs long loses the tail of its last shot. Captions never precede the line that earns them.

| # | Time | Narration (measured) | Shots (window used) | On-screen text | Viewer learns |
|---|---|---|---|---|---|
| 1 | 0:00–0:05.3 | An emperor penguin hands over her only egg, and leaves for about two months. (4.8 s) | **1a** close, low: egg already on his feet, his belly fold settles over it (2.7 s) · **1b** medium: she turns and walks away (2.6 s) | HER ONLY EGG | The behaviour, and the protected position of the egg |
| 2 | 0:05.3–0:09.6 | Dad keeps it warm on his feet. But he can't go hunting with it. (3.9 s) | **2a** tight: the egg under the fold, warm-lit, he shifts his weight (2.2 s) · **2b** medium-wide: the huddle, backs to the wind (2.2 s) | HE CAN'T HUNT WITH IT | The constraint |
| 3 | 0:09.6–0:11.8 | So she heads to sea to feed. (1.8 s) | **3a** underwater, looking up at the ice: she surges into a shoal (2.2 s) | SHE FEEDS AT SEA | The function, stated early |
| 4 | 0:11.8–0:14.7 | Meanwhile, he hasn't eaten for months. (2.4 s) | **4a** night, faint aurora, snow streams past him at the huddle's edge (2.8 s) | MONTHS WITHOUT FOOD | His cost |
| 5 | 0:14.7–0:17.9 | And if the chick hatches before she gets back? (2.8 s) | **5a** tight: eggshell fragment on his feet, the chick's head pushes out and opens its beak (3.2 s) | IF IT HATCHES FIRST? | The complication |
| 6 | 0:17.9–0:22.3 | He can briefly feed it a milk-like substance made in his throat. (4.0 s) | **6a** close, side: beak to beak, restrained, nothing visible passes (4.4 s) | A MILK-LIKE SUBSTANCE | The documented backup |
| 7 | 0:22.3–0:28.3 | Then she returns with food and takes over keeping the chick warm. Dad finally gets to eat. (5.5 s) | **7a** she walks up, bill to bill (2.0 s) · **7b** chick under her fold, fed (2.0 s) · **7c** he walks toward the open water (2.0 s) | SHE'S BACK | The outcome: return, exchange |
| 8 | 0:28.3–0:34.0 | For the chick's first weeks, they take turns. One keeps it warm; the other finds food. (5.3 s) | **8a** a plump adult arrives, the chick shuffles onto its feet (3.0 s) · **8b** wide, ice edge: one adult walks to the water (2.6 s) | THEY TAKE TURNS | Alternation, bounded to the first weeks |
| 9 | 0:34.0–0:37.7 | She didn't abandon the family. She came back with dinner. (3.3 s) | **9a** warm light: she feeds the chick, beak to beak. Dissolve to 1a. | BACK WITH DINNER | The reframe; loop |

Cadence: a change of action or framing at roughly 0, 2.7, 5.3, 7.5, 9.6, 11.8, 14.7, 17.9, 22.3,
24.3, 26.3, 28.3, 31.3 and 34 seconds, with the two feeding shots left to breathe.

**Storyboard test, done.** The review asked for the protected-egg close-up and the feeding
close-up before the batch. Both pairs are drawn (2a and 6a) and are in the chat with this brief;
the chick's scale and position under the fold follow the Mawson station photograph the review
pointed to.

## 4. Source map with the three gates

| Claim in narration | Status | Source |
|---|---|---|
| One egg, transferred to the male's feet, covered by his skin fold; she leaves to feed for about two months | **confirms exact claim** | [Australian Antarctic Program, breeding cycle](https://www.antarctica.gov.au/about-antarctica/animals/penguins/emperor-penguin/breeding-cycle/): the female "gives the egg to her partner who carefully puts it on his feet"; [Wikipedia, Emperor penguin](https://en.wikipedia.org/wiki/Emperor_penguin): "transfers the egg to the male and then returns to the sea for two months to feed" |
| He keeps it warm on his feet and cannot hunt while holding it | **confirms exact claim** | AAP breeding cycle (incubation on the feet through winter; males fast for the incubation) |
| "He hasn't eaten for months" by hatching | **confirms exact claim** | AAP: "by the time the chicks appear, their fathers have fasted for 4 months"; Wikipedia: about 120 days since arriving at the colony. The narration no longer stacks "two months" against "four months", per the review. |
| If the chick hatches before she returns, he can briefly feed it a milk-like secretion made in his throat | **read; confirms** | Wikipedia: "a curd-like substance composed of 59% protein and 28% lipid, which is secreted by a gland in his oesophagus"; the review cites the [WWF-Australia research-team account](https://wwf.org.au/blogs/return-of-the-emperors/) for the same. "Milk-like", not milk; "briefly", because it is a bridge to her return. |
| She returns with food and takes over; he goes to sea to eat | **confirms exact claim** | AAP: females return in July; the mother feeds the chick and the father departs to feed |
| For the chick's first weeks they take turns | **confirms exact claim** | AAP: the parents alternate brooding and foraging for about 40 to 50 days before the chicks gather in crèches. "First weeks" is deliberately looser than "40 to 50 days". |
| "She didn't abandon the family" | framing, no claim of record | Attributes nothing to anyone; it answers the viewer's own first reading. |

Nothing in the narration is a number except "two months" and "months". No colony-specific
distances or temperatures. No motive or feeling is attributed to either bird.

## 5. Weakest sentence, revised once

"For the chick's first weeks, they take turns: one keeps it warm; the other finds food" was the
review's own line, and its colon made the voice pause as if a new sentence had started, which
read as a list. It is now two sentences with the same words. Nothing else in the script was
weaker than that, which is the point of a script built one problem at a time.

## 6. Cost if approved

| Item | Count | Unit | Subtotal |
|---|---|---|---|
| Stills, start + end | 14 shots, 2 pairs already drawn | ~$0.05 | ~$1.15 more |
| Kling 3 Pro, 5 s shots | 14 | $0.56 | $7.84 |
| Narration + timing | done | | $0.05 |
| **First pass** | | | **~$9.05** |

The $10 cap leaves one re-roll. With fourteen shots, two re-rolls is the realistic reserve; I
recommend the cap at $12 for this Short.
