"""A two-sentence hook is a hook-shape defect: repaired in place, never a reason to replan.

Yellowstone (2026-09-30): the direction's own opening line, "Yellowstone killed its last wolves
to protect the elk. Then the elk ate the park." (15 words, 2 sentences), passed the word budget,
so the hook repair never fired and MULTI_SENTENCE_HOOK triggered a full replan of a draft that
had cleared research, spine and ledger.
"""
import explainer_pipeline as ep


def test_two_sentence_hook_is_a_hook_only_block():
    assert ep._only_hook_length_blocks(
        {"passed": False, "errors": [{"code": "MULTI_SENTENCE_HOOK"}]},
        ["MULTI_SENTENCE_HOOK: the hook is 2 sentences against a 1-sentence budget"])
    assert not ep._only_hook_length_blocks(
        {"passed": False, "errors": [{"code": "MULTI_SENTENCE_HOOK"}, {"code": "NO_CALLBACK"}]}, [])


def test_two_sentence_hook_is_joined_deterministically_when_the_model_is_unavailable(monkeypatch):
    class _Boom:
        class messages:
            @staticmethod
            def create(**_):
                raise RuntimeError("no provider in tests")
    monkeypatch.setattr(ep, "_claude", lambda: _Boom)
    hook = "Yellowstone killed its last wolves to protect the elk. Then the elk ate the park."
    script = {"hook": hook, "title": "Yellowstone wolves",
              "scenes": [{"narration": hook + " Explained like you are five."}]}
    out, cost = ep._ensure_hook_fits_budget(script)
    assert out["hook"] == "Yellowstone killed its last wolves to protect the elk — then the elk ate the park."
    assert out["scenes"][0]["narration"].startswith(out["hook"])
    assert cost == 0.0


def test_one_sentence_hook_within_budget_is_untouched():
    script = {"hook": "Australia imported this animal to kill beetles.", "scenes": []}
    assert ep._ensure_hook_fits_budget(script) == (script, 0.0)
