"""The turn by 45 seconds, ALLOCATED (explainer_pipeline._causal_word_budgets): the ladder
opening group is the 103-word target, the body gets the rest, no part-2 restatement scene."""
import copy

import pytest

import explainer_pipeline as ep
import opening_turn as ot
import story_compiler as sc
from runtime_planner import runtime_word_bounds
from turn_fixture import SAVED



# ── 2. the allocator ────────────────────────────────────────────────────────────────────────

def _beats(job):
    return [{"n": i + 1, "causal_role": b["causal_role"]} for i, b in enumerate(SAVED[job]["base_beats"])]


# (hook words, rows before the hinge). The critic's arithmetic for a 17-18-word frame was
# 25/25/26 and 37/38; aral-v2's 16-word frame and escobar's 13-word myth line leave a few more.
EXPECTED_ROWS = {"bees_v16": [25, 25, 26], "history-aral-sea-v2": [25, 26, 26],
                 "asian-carp": [37, 38], "escobar-hippos": [40, 40]}


@pytest.mark.parametrize("job", sorted(EXPECTED_ROWS))
def test_the_opening_group_is_the_turn_target_and_the_body_gets_the_rest(job):
    entry = SAVED[job]
    beats = _beats(job)
    total = runtime_word_bounds(300, len(beats))[0]
    before = ep._causal_word_budgets(beats, total, entry["engine"], entry["hook"])
    after = ep._causal_word_budgets(beats, total, entry["engine"], entry["hook"], turn_rule=True)
    mechanism = next(i for i, b in enumerate(beats) if b["causal_role"] == "mechanism")
    rows = [after[b["n"]] for b in beats[:mechanism] if b["causal_role"] != "hinge"]
    hinge = [after[b["n"]] for b in beats[:mechanism] if b["causal_role"] == "hinge"]
    assert rows == EXPECTED_ROWS[job] and hinge == [10]
    prefix = len(entry["hook"].split())
    assert prefix + sum(rows) + sum(hinge) == ot.TURN_TARGET_WORDS
    assert (prefix + sum(rows) + sum(hinge)) / ot.WORDS_PER_SECOND <= ot.TURN_TARGET_SEC
    freed = sum(before[b["n"]] for b in beats[:mechanism]) - sum(after[b["n"]] for b in beats[:mechanism])
    assert freed > 40
    assert (sum(after[b["n"]] for b in beats[mechanism:])
            - sum(before[b["n"]] for b in beats[mechanism:])) == freed
    assert sum(after.values()) == sum(before.values()), "the film's total is unchanged"
    slots, slot_budgets = sc.split_beats_into_slots(copy.deepcopy(beats), after)
    first_mechanism = next(i for i, s in enumerate(slots) if s["causal_role"] == "mechanism")
    assert all(int(s["beat_part"]) == 1 for s in slots[:first_mechanism]), "no part-2 restatement scene"


def test_the_allocator_is_unchanged_off_scope():
    entry = SAVED["bees_v16"]
    beats = _beats("bees_v16")
    total = runtime_word_bounds(300, len(beats))[0]
    assert ep._causal_word_budgets(beats, total, entry["engine"], entry["hook"]) == \
        ep._causal_word_budgets(beats, total, entry["engine"], entry["hook"], turn_rule=False)
    # The call site decides with opening_turn.stamp: hook mode, the reveal engines and short films
    # never get turn_rule=True.
    assert not ot.stamp("removed_keystone", 300, "")["applies"]
    assert not ot.stamp("mistaken_verdict", 300, "ladder")["applies"]
    assert not ot.stamp("removed_keystone", 180, "ladder")["applies"]
    # Below 225 s the 20% share is already under the target, so the cap would change nothing.
    short = runtime_word_bounds(200, 20)[0]
    assert ep._causal_word_budgets(beats, short, entry["engine"], entry["hook"], turn_rule=True) != {}


