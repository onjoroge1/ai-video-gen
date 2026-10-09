"""The verifier demands the opening object only from a frame whose prompt asked for it.

Measured 2026-09-22 on the first live 300s run that bought images: a state whose prompt asked
for "yellow locusts" and "grain" was held to "a single sparrow above a grain field" because
"grain" is a substring of that label. Drawn three times from a sparrow-less prompt, rejected
three times, and the run stopped with four accepted opening frames beside it.
"""
import explainer_pipeline as ep

PACK = {"opening_object": {"label": "a single sparrow above a grain field"}}


def _state(*required):
    return {"required_objects": list(required)}


def test_the_head_words_name_the_object_not_its_setting():
    assert ep._opening_object_head_words("a single sparrow above a grain field") == ["sparrow"]
    assert ep._opening_object_head_words("a single kudzu seedling in a nursery flat") == [
        "kudzu", "seedling"]
    assert ep._opening_object_head_words("cobra farms everywhere") == ["cobra", "farms",
                                                                        "everywhere"]
    assert ep._opening_object_head_words("the coin") == ["coin"]


def test_a_setting_word_does_not_summon_the_object():
    assert not ep._opening_object_wanted(_state("yellow locusts", "grain"), PACK)
    assert not ep._opening_object_wanted(_state("grain field", "a farmer"), PACK)
    assert not ep._opening_object_wanted(_state("a single grain stalk"), PACK)


def test_naming_the_object_does():
    assert ep._opening_object_wanted(_state("warm coral sparrow", "grain stalk"), PACK)
    assert ep._opening_object_wanted(_state("rows of grain", "a single sparrow above a grain field"), PACK)
    assert ep._opening_object_wanted(_state("two sparrows on a wire"), PACK), "plural still names it"
    assert ep._opening_object_wanted(_state("the single sparrow above a grain field at dusk"), PACK)


def test_no_label_or_no_required_objects_expects_nothing():
    assert not ep._opening_object_wanted(_state("sparrow"), {})
    assert not ep._opening_object_wanted(_state(), PACK)
    assert not ep._opening_object_wanted({"required_objects": ["", None]}, PACK)


def test_the_run_9_states_are_judged_as_their_prompts_asked():
    """The five opening states from run a4cb0679, verbatim required_objects."""
    states = {
        "e01": ["rows of grain", "a single sparrow above a grain field"],
        "e02": ["warm coral sparrow", "grain stalk"],
        "e03": ["warm coral sparrow", "yellow insect"],
        "e04": ["yellow locusts", "grain"],
        "e05": ["stripped grain patch", "full grain"],
    }
    wanted = {k: ep._opening_object_wanted(_state(*v), PACK) for k, v in states.items()}
    assert wanted == {"e01": True, "e02": True, "e03": True, "e04": False, "e05": False}
