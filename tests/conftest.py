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

import explainer_pipeline


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live_motion: test drives the raw image-to-video provider call and mocks its transport "
        "itself; exempts it from the no-billed-provider guard")


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
