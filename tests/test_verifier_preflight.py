"""Prove the judge can answer before buying pictures for it to judge.

Images come from OpenAI; the verifier that decides whether they show what they claim comes from
Anthropic. The two fail independently, so the expensive half can keep succeeding long after the
half that makes its output usable has stopped.

Measured three times on this lane. Once it cost 73 images bought against a judge that could not
answer, then five states dropped and a 43-second hold. Once it killed a run at the last evidence
state after 25 minutes of generation.
"""
import pytest

import explainer_pipeline as ep


class _Boom:
    def __init__(self, exc):
        self.exc = exc
        self.calls = 0

    def create(self, **_):
        self.calls += 1
        raise self.exc


class _Fine:
    def __init__(self):
        self.calls = 0
        self.kwargs = None

    def create(self, **call):
        self.calls += 1
        self.kwargs = call
        return object()


def _install(monkeypatch, messages):
    monkeypatch.setattr(ep, "_claude",
                        lambda: type("C", (), {"messages": messages})())
    return messages


def test_an_exhausted_balance_stops_the_run_before_a_single_image(monkeypatch):
    """Fail closed and name the provider. This is a technical precondition, not a quality gate."""
    _install(monkeypatch, _Boom(RuntimeError(
        "Error code: 400 - {'message': 'Your credit balance is too low to access the "
        "Anthropic API.'}")))
    with pytest.raises(RuntimeError) as caught:
        ep._preflight_verifier_credit(log=lambda *_: None)
    message = str(caught.value)
    assert "before any image was bought" in message
    assert "Anthropic" in message
    # It must say what to do, because the fix is the operator's and the work is recoverable.
    assert "cached" in message


def test_a_transient_failure_does_not_kill_a_paid_script(monkeypatch):
    """A network blip must not discard research and a script that are already paid for.

    The per-asset verifier still fails closed if the judge really is gone, so continuing here
    risks nothing except one wasted image -- against throwing away the whole run for a timeout.
    """
    _install(monkeypatch, _Boom(TimeoutError("connection reset")))
    noted = []
    ep._preflight_verifier_credit(log=noted.append)
    assert noted and "preflight" in noted[0]


def test_a_healthy_verifier_is_silent_and_cheap(monkeypatch):
    """One token. Anything more and the check costs more than it saves."""
    messages = _install(monkeypatch, _Fine())
    noted = []
    ep._preflight_verifier_credit(log=noted.append)
    assert messages.calls == 1
    assert messages.kwargs["max_tokens"] == 1
    assert noted == [], "a working verifier should say nothing"


def test_the_check_runs_before_the_image_loop():
    """Placement is the whole point: after it, the money is already spent."""
    import inspect
    source = inspect.getsource(ep.run_explainer_pipeline)
    preflight = source.index("_preflight_verifier_credit(")
    images = source.index('img_dir = os.path.join(output_dir, "images")')
    assert preflight < images, "the preflight must precede the image directory being prepared"


def test_the_check_runs_once_per_scene_not_only_once_per_run():
    """A 95-state render spends for half an hour after the opening preflight passes.

    Measured: a run cleared the preflight and exhausted the balance 1601 seconds later, partway
    through its states. Checking per scene cannot PREDICT exhaustion -- the API exposes no balance,
    only a 400 once it is gone -- but it changes the order of discovery, failing before a scene's
    images are generated rather than after.
    """
    import inspect
    source = inspect.getsource(ep.run_explainer_pipeline)
    assert source.count("_preflight_verifier_credit(") >= 2, \
        "expected an opening preflight AND a per-scene check"
    assert "_preflight_verifier_credit(log, scene_index=i)" in source


def test_an_exhausted_balance_mid_run_says_how_far_it_got(monkeypatch):
    """The operator needs to know whether to top up a little or a lot, and what survived."""
    _install(monkeypatch, _Boom(RuntimeError(
        "Error code: 400 - {'message': 'Your credit balance is too low.'}")))
    with pytest.raises(RuntimeError) as caught:
        ep._preflight_verifier_credit(log=lambda *_: None, scene_index=14)
    message = str(caught.value)
    assert "after 14 scene(s)" in message
    assert "cached" in message


def test_the_opening_preflight_still_reads_as_before_any_spend(monkeypatch):
    _install(monkeypatch, _Boom(RuntimeError("credit balance is too low")))
    with pytest.raises(RuntimeError) as caught:
        ep._preflight_verifier_credit(log=lambda *_: None)
    assert "before any image was bought" in str(caught.value)
