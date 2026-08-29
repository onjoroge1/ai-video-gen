"""Everything derived from narration must be re-derived in one place.

Three passes rewrite narration -- the fact-check, the runtime refit and the measured-audio
fit -- and each call site used to remember for itself which phrase repairs to re-run. All
three got it wrong at least once, and each was found and patched separately because the
knowledge of what depends on narration lived at the call sites instead of in one function.

This test fails if a new call site re-derives only part of it, which is how the bug
recurred three times.
"""

import re
from pathlib import Path

import explainer_pipeline as ep

SOURCE = Path(ep.__file__).read_text()
ENTRY = "rederive_narration_bindings"
REPAIRS = ("_repair_claim_phrases", "_repair_anchor_phrases")


def _entry_point_body() -> str:
    start = SOURCE.index(f"def {ENTRY}(")
    end = SOURCE.index("\ndef ", start + 10)
    return SOURCE[start:end]


def test_the_entry_point_re_derives_every_binding_type():
    body = _entry_point_body()

    for repair in REPAIRS:
        assert f"{repair}(script" in body, f"{ENTRY} must re-derive {repair}"


def test_no_call_site_repairs_bindings_directly():
    # Direct calls are legal ONLY inside the entry point. Anywhere else means a pass
    # re-derived some bindings and not others, which is the bug this replaced.
    body = _entry_point_body()
    outside = SOURCE.replace(body, "")

    stray = [
        line.strip()
        for line in outside.splitlines()
        if any(re.search(rf"(?<!def ){repair}\(script", line) for repair in REPAIRS)
    ]

    assert not stray, (
        "these call sites bypass "
        f"{ENTRY} and will re-derive only part of the bindings: {stray}"
    )


def test_every_pass_that_rewrites_narration_is_followed_by_the_entry_point():
    # The three rewriting passes, each of which invalidated bindings in a real run.
    for rewriter in ("_enforce_requested_runtime", "_fit_script_to_measured_audio"):
        assert rewriter in SOURCE
        after = SOURCE.split(rewriter)[-1]
        assert ENTRY in after[:2000], (
            f"{rewriter} rewrites narration; {ENTRY} must follow it before anything "
            "validates a phrase binding")
