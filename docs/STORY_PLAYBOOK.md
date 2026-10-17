# Story Playbook: the middle and the ending

> Operator, 2026-10-17: the opening works and stays as it is. After it, the scripts meander.
> This playbook covers everything after the opening, with the human story as the spine.
> Code: `story_shape.py` (writer rules, advisory checks, a CLI), the grader's story and ending
> axes, and the storyboard's advisory warnings.
> Companion docs: `docs/FATAL_THUMBNAIL_PLAYBOOK.md` (packaging) and the witness opening in
> `hook_patterns.py` (unchanged).

## The opening stays

Keep these as they are:
- the myth line;
- the reveal with the scale;
- the documented person at the moment the consequence reached them;
- the question, once;
- the viewer's role.

The rules below begin at scene 2.

## What went wrong after the opening (Chernobyl, 886 words)

| Where | What the script did | What it did to the viewer |
|---|---|---|
| 4% → 90% | The witness who moved back appeared once and returned only as "a hundred people still live inside the zone" | They lost the person they were following |
| 28% | How every other RBMK reactor was modified (a beta coefficient) | A side road that answers a question nobody asked |
| 35–45% | Evacuation counts: 116,000, then 220,000, then 350,000 | A run of statistics with no turn |
| 43, 46, 60, 86% | "So how many, all told?" "So what keeps that reason alive?" | Questions answered in the next breath hold no tension |
| 48% | The real answer (half-lives) only begins | Half the runtime was spent before the payoff started |
| 66–86% | The arch and the drone strike | A different question: is it contained? |
| 97% | "When a fix promises safety, ask what it switches off" | The close answers a moral question, not the title |

The script also had 12 sentences opening with "So" and 61 numbers, about one every 14 words. Every
scene was joined to the one before it, but they didn't build: the chain read as "and then", not
"but therefore".

The two films made since show the rules working. Demon Core: the answer comes in one plain sentence
at 62%, Slotin returns at the turns, and the close is a bookend. Its endings graded 82–85, and
`story_shape` finds nothing. Elephant's Foot has a midpoint paradox (drying should calm the fuel
but seems to wake it); its one finding is that Korneyev does not return in the middle.

## The middle

1. **One question, held open, getting sharper.**
   - Every scene answers part of the title question and leaves a sharper version of it.
   - A scene that serves a different question is a side story; cut it at the plan stage.
2. **Keep the human story.**
   - The documented person from the opening, or the viewer's role, returns at the turn in the middle and again in the close.
   - They do only what the sources say. Viewers follow a person, not a ledger.
3. **One midpoint turn.**
   - Between 40% and 60%, something flips what the viewer believes: a false relief ("built to last a century… then a drone hit it"), a paradox, or a reversal.
   - The engines' apparent-success and false-resolution roles exist for this.
4. **Real questions only.** At most two questions after the opening. Never one the next sentence simply answers.
5. **Vary the joints.** "So" opens at most one scene in four. But, Still, Then, Even, Until, Only and That also join.
6. **One number per sentence, at human scale.**
   - A thirty-year half-life is "her grandchildren's grandchildren".
   - Dates are settings, not figures.
7. **Emotional variety.** Dread, then hope, then worse, then resolution. One grave tone throughout reads as a lecture.

## The ending

1. **By the start of the final third,** say the answer to the title question in one plain sentence.
2. **The close returns to the opening person or object with a changed meaning,** then stops.
   - Korneyev's photograph: "No one can get that close to the part that's waking up."
   - The screwdriver: "Afterwards, a quarter of a mile. Before, the width of a screwdriver."
3. **No general lesson, no advice to the viewer, and no recap of your own.** An engine's synthesis row, when the sheet has one, is the only re-walk.
4. **Later, a bridge.** The end screen and the Short point to the next related film; that is session watch time.

## Where it lives in the pipeline

- **Writer:**
  - `story_shape.writer_rules(is_last)` is appended to every batch of the chunked writer on the causal lane.
  - The middle rules go to every batch; the ending rules go to the batch that holds the close.
  - The opening rules are untouched.
- **Grader** (`_SCRIPT_GRADE_SYSTEM`):
  - The story axis now asks for one question held open, a midpoint turn and the human story.
  - The ending axis asks for the answer in one sentence, a bookend, and no lesson.
  - The 78 bar is unchanged; it now measures these things.
- **Storyboard warnings** (`story_shape.findings`): advisory, so a film is never stopped for its cadence. Every finding is logged:
  - `BODY_QUESTIONS`
  - `SO_CADENCE`
  - `NUMBER_DENSE`
  - `HUMAN_THREAD_DROPPED`
  - `MIDPOINT_TURN_MISSING`
  - `LESSON_CLOSE`
- **Hand-written scripts:** run `python3 story_shape.py jobs/<job>/_state.json` before resuming. It prints the same findings.

## Checking it against viewers

The 72-hour retention reads show where viewers leave. A drop that lines up with a side story or a
statistics run confirms the rule; trim the scene in Studio when it is self-contained. Record each
finding in the retention log (git-ignored; the repository is public).
