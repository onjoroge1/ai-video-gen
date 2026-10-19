# Rescue a failed script by revision

Operator rule, 2026-10-19. When the pipeline's script fails a gate before any media is bought (claim
ledger, storyboard, or a grade under the bar), revise the failed script. Don't rewrite it.

1. `python3 scripts/rescue_script.py report jobs/<job>`: the blocking errors next to the scenes they
   name, the grader's notes, and the storyboard check, using the launch flags in run_command.txt.
2. Write a short edits.json. Make the smallest edit for each error:
   - cut the unsupported detail, or move the line to the scene whose event covers it;
   - delete each line the grader names as a repeat;
   - repair, rather than delete, a broken sentence that a later scene refers back to.
3. `apply`, then `check` (storyboard, claims, dossier, retention contract, grade ×3, bar 78).
4. **Hard gates first.** Gate-fixing rounds are cheap; keep going until every hard gate passes.
5. **Then up to three grade rounds,** each cutting only what the grader names. Add few new words:
   a new sentence can repeat an idea elsewhere and cost more than it fixes.
6. `diff` shows the operator what changed. Over a third of the sentences is a rewrite, not a revision.
7. Still under the bar after three grade rounds: the operator either accepts the script (72 or more)
   or approves a restructure outline. Never a silent full rewrite.
8. `install` stamps the opening turn, sets the failure file aside (otherwise resume restores it),
   writes _state.json, and prints the resume command.

**Why.** The pythons rescue rewrote nearly every line on the planner's outline while chasing gate
codes. It graded 79 and read as inconsistent: a crammed opening, the answer before the question, a
side-story section. On the same failure, a revision passed every hard gate with 14% of sentences
changed (grade 68 to 72).
