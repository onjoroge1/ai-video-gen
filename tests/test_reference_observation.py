"""The judged half of ingestion: what it must never do.

`observed` is not a report anybody reads once — it becomes context that shapes every video
generated from its reference. So the failure that matters is not "the pass errored", it is "the
pass returned something plausible that nobody measured". These tests pin the two properties that
prevent it: it fails to EMPTY, and it cannot widen the corpus vocabulary.
"""
import importlib.util
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import reference_corpus as rc  # noqa: E402


def _module():
    spec = importlib.util.spec_from_file_location(
        "ingest_reference", ROOT / "scripts" / "ingest_reference.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    """Ten seconds of synthetic video, so these tests need no reference binary present."""
    path = tmp_path_factory.mktemp("clip") / "clip.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi",
                    "-i", "testsrc=size=180x320:rate=10:duration=10",
                    "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def _fake_pipeline(reply, raises=None):
    """Stand in for explainer_pipeline, which observe() imports lazily inside the call."""
    module = types.ModuleType("explainer_pipeline")
    module.ANTHROPIC_MODEL = "test-model"
    module._msg_cost = lambda usage: 0.01
    module._parse_script_json = lambda raw: (reply, 0.0)

    class _Messages:
        def create(self, **kwargs):
            if raises:
                raise raises
            return types.SimpleNamespace(
                content=[types.SimpleNamespace(text="{}")], usage=None)

    module._claude = lambda: types.SimpleNamespace(messages=_Messages())
    return module


def test_blocks_pair_each_frame_with_the_words_spoken_over_it(clip):
    """The fields being judged are relations between what is said and what is shown."""
    module = _module()
    cues = [(1.0, "first"), (2.0, "still first"), (6.0, "second half")]
    blocks = module.sample_blocks(clip, cues, 2, Path(str(clip.parent)))

    assert len(blocks) == 2
    assert blocks[0][2] == "first still first"
    assert blocks[1][2] == "second half"
    assert all(frame.exists() for _, frame, _ in blocks)


def test_every_cue_lands_in_exactly_one_block(clip):
    """Half-open blocks. Overlapping ones would show the model the same line twice and read as
    emphasis; a gap would silently drop narration from the judgement."""
    module = _module()
    cues = [(round(index * 0.7, 2), f"cue{index}") for index in range(14)]
    blocks = module.sample_blocks(clip, cues, 4, Path(str(clip.parent)))

    seen = " ".join(text for _, _, text in blocks).split()
    assert sorted(seen) == sorted(text for _, text in cues)


def test_an_unavailable_model_yields_no_observations(clip, monkeypatch):
    """Fails to EMPTY, never to partial. An absent judgement is recoverable; an invented one is
    context that propagates into every video built from this reference."""
    module = _module()
    monkeypatch.setitem(sys.modules, "explainer_pipeline",
                        _fake_pipeline(None, raises=RuntimeError("no key")))
    assert module.observe(clip, [(1.0, "x")], 2) == {}


def test_a_non_dict_reply_yields_no_observations(clip, monkeypatch):
    module = _module()
    monkeypatch.setitem(sys.modules, "explainer_pipeline", _fake_pipeline(["not", "a", "dict"]))
    assert module.observe(clip, [(1.0, "x")], 2) == {}


def test_invented_keys_cannot_widen_the_corpus_vocabulary(clip, monkeypatch):
    """An `observed` block with different keys per reference is not a corpus."""
    module = _module()
    reply = {field: f"value for {field}" for field in rc.OBSERVED_FIELDS}
    reply["music_bpm"] = 120
    reply["confidence"] = "high"
    monkeypatch.setitem(sys.modules, "explainer_pipeline", _fake_pipeline(reply))

    observed = module.observe(clip, [(1.0, "x")], 2)
    assert set(observed) == set(rc.OBSERVED_FIELDS)
    assert "music_bpm" not in observed


def test_blank_and_missing_fields_are_dropped_not_stored_empty(clip, monkeypatch):
    """A field present as "" would read as a judgement that the trait is absent."""
    module = _module()
    reply = {rc.OBSERVED_FIELDS[0]: "a real hook", rc.OBSERVED_FIELDS[1]: "   "}
    monkeypatch.setitem(sys.modules, "explainer_pipeline", _fake_pipeline(reply))

    observed = module.observe(clip, [(1.0, "x")], 2)
    assert observed == {rc.OBSERVED_FIELDS[0]: "a real hook"}


def test_observations_reach_the_draft_and_stay_out_of_measured(clip):
    module = _module()
    observed = {"hook_type": "cold question over a still"}
    draft, measured = module.build_draft(clip, "synthetic", "backfiring_solution",
                                         [(0.5, "Hello.")], observed)

    assert draft["observed"] == observed
    assert not set(measured) & set(rc.OBSERVED_FIELDS), "a judged field leaked into measured"


def test_a_draft_without_the_pass_still_has_the_key(clip):
    """Present and empty rather than absent, so every reference has one shape."""
    draft, _ = _module().build_draft(clip, "synthetic", "backfiring_solution", [(0.5, "Hello.")])
    assert draft["observed"] == {}
