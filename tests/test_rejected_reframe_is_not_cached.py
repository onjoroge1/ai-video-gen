"""A crop the verifier rejected must not survive as a paid asset.

`_detail_reframe_earns_it` writes a deterministic centre crop to the state's own path, verifies it,
and returns False when it does not earn its information. False means "generate a real image for
this state instead", and the caller's fallthrough does that — unless a file is already sitting at
`state_path`:

    cached = (asset_resume_allowed and os.path.isfile(state_path)
              and os.path.getsize(state_path) > 0)
    if not cached:
        generate_image(...)

`asset_resume_allowed` is False on a fresh run (explainer_pipeline.py:9316) and True only on a
resume (:9391). So on a resumed run the crop this function just rejected makes `cached` true,
generation is skipped entirely, and the refused crop is handed back to `verify_evidence_asset` as
though it had been bought — a second, non-deterministic verdict then decides whether it ships.
"""
import os

from PIL import Image

import explainer_pipeline as ep


def _source(tmp_path):
    path = tmp_path / "master.jpg"
    Image.new("RGB", (1536, 1024), (40, 70, 110)).save(path)
    return str(path)


def _state():
    return {"state_id": "state:s001:e02", "asset_id": "asset:s001:e02",
            "required_objects": ["a beetle"], "forbidden_objects": [],
            "state_before": "intact", "state_after": "bored"}


def test_a_rejected_crop_is_deleted_not_left_behind(monkeypatch, tmp_path):
    state_path = str(tmp_path / "state.jpg")
    monkeypatch.setattr(ep, "verify_evidence_asset",
                        lambda *a, **k: {"passed": False, "reasons": ["no beetle is readable"]})

    earned = ep._detail_reframe_earns_it(
        _source(tmp_path), state_path, _state(), {}, [], False)

    assert earned is False
    assert not os.path.exists(state_path), (
        "the rejected crop is still on disk; a resumed run would treat it as a paid asset")


def test_an_accepted_crop_is_kept(monkeypatch, tmp_path):
    state_path = str(tmp_path / "state.jpg")
    monkeypatch.setattr(ep, "verify_evidence_asset",
                        lambda *a, **k: {"passed": True, "visible_information": True})

    earned = ep._detail_reframe_earns_it(
        _source(tmp_path), state_path, _state(), {}, [], False)

    assert earned is True
    assert os.path.isfile(state_path) and os.path.getsize(state_path) > 0
    assert ep._last_reframe_verification[0]["passed"] is True


def test_the_resume_fallthrough_can_no_longer_serve_a_rejected_crop(monkeypatch, tmp_path):
    """The condition that made this dangerous, asserted directly.

    This is the caller's own expression. With the crop deleted it evaluates False even under
    `asset_resume_allowed`, so the state falls through to real generation as intended.
    """
    state_path = str(tmp_path / "state.jpg")
    monkeypatch.setattr(ep, "verify_evidence_asset", lambda *a, **k: {"passed": False})
    ep._detail_reframe_earns_it(_source(tmp_path), state_path, _state(), {}, [], False)

    asset_resume_allowed = True
    cached = (asset_resume_allowed and os.path.isfile(state_path)
              and os.path.getsize(state_path) > 0)
    assert cached is False


def test_a_missing_source_never_writes_anything(tmp_path):
    state_path = str(tmp_path / "state.jpg")
    assert ep._detail_reframe_earns_it("", state_path, _state(), {}, [], False) is False
    assert not os.path.exists(state_path)


def test_deletion_failure_is_not_fatal(monkeypatch, tmp_path):
    """A read-only or already-swept file must not take the render down with it."""
    state_path = str(tmp_path / "state.jpg")
    monkeypatch.setattr(ep, "verify_evidence_asset", lambda *a, **k: {"passed": False})

    def _boom(_path):
        raise OSError("read-only filesystem")
    monkeypatch.setattr(ep.os, "remove", _boom)

    assert ep._detail_reframe_earns_it(
        _source(tmp_path), state_path, _state(), {}, [], False) is False
