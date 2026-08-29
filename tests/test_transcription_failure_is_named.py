"""A failed transcription call must not look like narration that was never spoken.

transcribe_words swallowed every exception into []. The long-form timing gate reads that
empty list and reports "Visual beat phrase is not present in measured speech" -- a content
failure -- so a transient Whisper error aborted a run that had already paid for its TTS
while blaming the script. Re-transcribing the same file by hand matched perfectly.
"""

import pytest

import explainer_pipeline as ep


def _boom(*args, **kwargs):
    raise RuntimeError("connection reset")


def test_a_failed_call_raises_under_strict(monkeypatch):
    monkeypatch.setattr(ep, "_retry", _boom)

    with pytest.raises(ep.TranscriptionUnavailable) as caught:
        ep.transcribe_words("/tmp/scene_05.mp3", strict=True)

    # The message must name the real cause, not the symptom.
    assert "scene_05.mp3" in str(caught.value)
    assert "connection reset" in str(caught.value)


def test_captions_still_degrade_gracefully(monkeypatch):
    # Karaoke captions have always tolerated missing timings; that path must not start raising.
    monkeypatch.setattr(ep, "_retry", _boom)

    assert ep.transcribe_words("/tmp/scene_05.mp3") == []


def test_audio_that_genuinely_transcribes_to_nothing_is_not_an_error(monkeypatch):
    # The distinction being drawn: a successful call returning no words is empty, not failed.
    monkeypatch.setattr(ep, "_retry", lambda *a, **k: type("R", (), {"words": []})())

    assert ep.transcribe_words("/tmp/scene_05.mp3", strict=True) == []
