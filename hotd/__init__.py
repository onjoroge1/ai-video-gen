"""HotD explainer pipeline: one place to build an episode.

Engine modules are episode-agnostic; per-episode data lives in episodes/ and hotd_<slug>_data.py.

Loading .env happens HERE, once, for every entry point. The old per-episode scripts each carried
their own copy of the loader; consolidating removed the duplication and, briefly, removed the loading
too -- nineteen image generations failed with KeyError: 'OPENAI_API_KEY' before this was put back.
The cap and retry behaved correctly through that, so nothing was spent, but the lesson is that a
cross-cutting concern belongs at the package boundary rather than in each caller.
"""
from __future__ import annotations
import os

_ENV_LOADED = False


def load_env(path=".env"):
    """Idempotently put .env into os.environ without overriding anything already set."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for cand in (path, os.path.join(here, path)):
        if os.path.exists(cand):
            for line in open(cand, encoding="utf8"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())
            return


load_env()
