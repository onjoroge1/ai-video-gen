"""Parsing an operator's spec document into a renderable script.

When the operator writes the narration, the beat sheet and the research dossier both disappear
-- the words exist and the operator owns the facts. What a supplied narration cannot skip is
per-scene image prompts, so these are composed from the spec's own world templates rather than
generated, which keeps the path free of the script provider entirely.
"""

import pytest

import user_directed as ud

SPEC = "spec/hippo_bacon_video_generation_spec.md"


@pytest.fixture(scope="module")
def parsed():
    return ud.parse_spec(SPEC)


def test_the_real_spec_parses_into_scenes(parsed):
    assert len(parsed.scenes) > 30, "the narration should split into many scenes"
    assert 1270 <= parsed.words <= 1330, (
        f"{parsed.words} words is outside the spec's own 1270-1330 target")


def test_a_heading_cannot_swallow_the_page():
    """The bug this caught on the real document.

    With (.+?) under DOTALL the heading pattern spanned sections looking for any blockquote, so
    '### Primary title' captured the page and the PINNED COMMENT became the historical image
    prompt. Every 1910 scene would have rendered from a YouTube comment.
    """
    prompts = ud.extract_base_prompts(open(SPEC, encoding="utf-8").read())

    assert prompts["historical_1910"].startswith("Cinematic 1910")
    assert prompts["alternate_2026"].startswith("Photoreal modern Louisiana")
    assert "lake cow bacon" not in prompts["historical_1910"].lower(), (
        "the pinned comment leaked into an image prompt")


def test_the_closing_callback_returns_to_the_supermarket(parsed):
    """The last scene must not be rendered in a 1910 palette.

    The film opens and closes on the same grocery case; that callback is the whole ending. A
    world range that runs 1910 to the credits would render the final shelf in tobacco brown.
    """
    assert parsed.scenes[-1].world == "alternate_2026"
    assert parsed.scenes[0].world == "alternate_2026"


def test_every_scene_has_an_image_prompt(parsed):
    # Nothing renders without one, and this path has no model to invent them.
    for scene in parsed.scenes:
        assert scene.image_prompt.strip(), f"scene {scene.index + 1} has no image prompt"
        assert len(scene.image_prompt) > 40, f"scene {scene.index + 1} prompt is a stub"


def test_scenes_never_split_a_sentence():
    """Anchor phrases are matched against measured speech downstream.

    Five separate causes of anchor mismatch were fixed in this codebase; a scene boundary
    mid-sentence would manufacture a sixth.
    """
    chunks = ud.split_into_scenes(
        "One two three four five. Six seven eight nine ten. Eleven twelve thirteen.")

    for chunk in chunks:
        assert chunk.strip()[-1] in ".!?", f"scene ends mid-sentence: {chunk!r}"


def test_a_document_without_narration_sections_fails_loudly():
    import tempfile, pathlib
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as handle:
        handle.write("# Some doc\n\nNo timed sections here.\n")
        path = handle.name

    with pytest.raises(ValueError, match="No narration sections"):
        ud.parse_spec(path)

    pathlib.Path(path).unlink()


def test_json_artifact_carries_the_script(tmp_path, parsed):
    out = tmp_path / "spec.json"
    payload = ud.to_json(parsed, out)

    assert out.exists()
    assert payload["scene_count"] == len(parsed.scenes)
    assert payload["script"]["scenes"][0]["narration"]
    assert payload["script"]["_operator_supplied"] is True


def test_shot_plan_drives_a_two_to_three_second_visual_cadence():
    """The spec's shot table is the retention contract; parsing must preserve its density.

    The first pilot generated one image per narration scene -- four states across 45 seconds,
    a change every ten seconds. The spec's own section 9 specifies fifteen. This asserts the
    parser recovers that table and that no single shot is allowed to hold long enough to read
    as a slideshow, which is the failure the operator caught by watching.
    """
    spec_text = open(SPEC, encoding="utf-8").read()
    shots = ud.extract_shot_plan(spec_text)

    assert len(shots) >= 15, f"expected the spec's 15-shot table, parsed {len(shots)}"

    holds = [shot["end_sec"] - shot["start_sec"] for shot in shots]
    assert max(holds) <= 4.0, f"a {max(holds)}s hold is a slideshow, not a cut"
    assert min(holds) >= 1.5, f"a {min(holds)}s flash is below the readable floor"

    # Contiguous: a gap between shots is dead air on the picture track.
    for earlier, later in zip(shots, shots[1:]):
        assert later["start_sec"] <= earlier["end_sec"], (
            f"gap between {earlier['end_sec']}s and {later['start_sec']}s")
