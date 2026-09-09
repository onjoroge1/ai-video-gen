"""Suite-wide guard against reaching a live, billed image-to-video provider.

Every other paid boundary in this suite is mocked per test, and the language boundary even has a
named tripwire -- `unexpected_provider` raises "Unexpected live language-provider boundary". Motion
had no such guard, because until now no test could reach it: the illustrated lane forced stills and
the long-form lanes leave I2V_PROVIDER unset in CI.

That stopped being true the moment the illustrated lane was allowed to buy motion. `_animate_one`
posts to the provider and polls for up to 360 seconds, and app.py's `load_dotenv(override=True)`
means a developer's real FAL_KEY is loaded into any local test run -- so an unmocked motion path is
a test suite that submits billed generation jobs and then waits six minutes for them.

`_animate_one` is the guarded seam because it is the one that makes the request. Everything above it
(`animate_scene`, the selection and budget logic, the fallback bookkeeping) still runs, so tests
exercise the real motion path and only the network call is refused. A test that genuinely wants to
drive a provider branch marks itself `@pytest.mark.live_motion` and mocks the transport itself.
"""
import pytest
import ipaddress
import socket

import explainer_pipeline


@pytest.fixture(autouse=True)
def _no_external_network(request, monkeypatch):
    """Default tests replace providers; an accidental live call must fail before sending data."""
    if request.node.get_closest_marker("entailment_live"):
        return  # separately opt-in and skipped by default below
    original = socket.socket.connect
    original_ex = socket.socket.connect_ex

    def check(address):
        if isinstance(address, tuple):
            host = address[0]
            try:
                local = ipaddress.ip_address(host).is_loopback
            except ValueError:
                local = host == "localhost"
            if not local:
                raise AssertionError("External network is disabled in offline tests; mock the provider boundary")

    def connect(sock, address):
        check(address)
        return original(sock, address)

    def connect_ex(sock, address):
        check(address)
        return original_ex(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live_motion: test drives the raw image-to-video provider call and mocks its transport "
        "itself; exempts it from the no-billed-provider guard")
    config.addinivalue_line(
        "markers",
        "entailment_live: test calls the real language provider to judge entailment; opt in with "
        "-m entailment_live, since it costs money and is not deterministic")


@pytest.fixture(autouse=True)
def _no_billed_motion_provider(request, monkeypatch):
    if request.node.get_closest_marker("live_motion"):
        return

    def _refuse(provider, image_path, prompt, out_mp4, *args, **kwargs):
        raise AssertionError(
            f"Unexpected live image-to-video provider boundary ({provider!r}). Mock "
            "explainer_pipeline.animate_scene (or _animate_one) in this test, or mark it "
            "@pytest.mark.live_motion if it means to drive the provider branch.")

    monkeypatch.setattr(explainer_pipeline, "_animate_one", _refuse)


def pytest_collection_modifyitems(config, items):
    """Skip the live entailment cases unless they are asked for by marker.

    They are the tests that say whether the judge actually works, so they must exist and be easy to
    run -- but they call a paid provider and a model's judgement is not reproducible, so they
    cannot gate an ordinary suite run.
    """
    if "entailment_live" in (config.getoption("-m") or ""):
        return
    skip = pytest.mark.skip(reason="live provider; run with -m entailment_live")
    for item in items:
        if "entailment_live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def spoken_markers_on(monkeypatch):
    """Run this test with the spoken "Step one." openers restored.

    The device is off by default (see causal_story.speaks_chapter_markers) but it is a flag, not a
    deletion: the corpus references all speak their numbers, and the machinery that places one
    correctly -- after the hook on scene 1, alone on later openers, never duplicated, idempotent --
    is worth keeping under test. These are the tests that specify it.
    """
    monkeypatch.setenv("SPOKEN_CHAPTER_MARKERS", "1")
