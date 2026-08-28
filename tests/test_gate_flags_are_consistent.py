"""A condition checked in two places must read its flag in both.

Seven times in one session a validation was enforced at two points in the pipeline while only
one of them consulted the flag that governs it. Each instance cost a full render, and always in
the worst order: the escape hatch appears to work, the run proceeds and pays for TTS or images,
and then the sibling check -- dozens or hundreds of lines later -- aborts on the same fact.

  claim ledger        post-fact-check honoured CLAIM_LEDGER_HARD; post-refit did not
  evidence plan       pre-TTS honoured DIAGNOSTIC_RENDER; post-measured-audio did not
  runtime             the gate honoured RUNTIME_HARD; the two rewrite passes serving it did not
  story/claim         the post-TTS check honoured neither flag
  measured rewrite    the post-rewrite check honoured neither flag
  editorial review    the review gate honoured DIAGNOSTIC_RENDER; the freeze check after it did not
  resume checkpoint   the run proceeded past an error it then could not reload

Every one was found by a failed render rather than by a test. This is that test.
"""

import re
from pathlib import Path

import explainer_pipeline as ep

SOURCE = Path(ep.__file__).read_text()
LINES = SOURCE.splitlines()

# Every helper, found with: grep -oE "def _[a-z_]*(hard|enforced|render)\(\)".
# My first list omitted _script_gate_hard and _hook_dryrun_hard, and the scanner reported a
# correctly-guarded raise as a violation. A detector with an incomplete vocabulary produces
# false alarms, which is how detectors get switched off.
FLAG_HELPERS = (
    "_diagnostic_render", "_claim_ledger_hard", "_longform_retention_hard",
    "_runtime_is_enforced", "_script_gate_hard", "_hook_dryrun_hard",
)

# Validators whose result is used to abort. Each is checked at several points because the data
# it reads changes between them -- that is legitimate. What is not legitimate is the copies
# disagreeing about whether an operator can wave the failure through.
GUARDED_VALIDATORS = (
    "validate_claim_joins",
    "validate_evidence_plan",
    "validate_longform_story",
    "validate_evidence_timing",
)

LOOKAHEAD = 30     # lines below a validator call in which a raise belongs to it

# The guard is the span from the validator call to the raise -- NOT a fixed lookback. A fixed
# window reaches backwards past the start of the block and can pick up a flag belonging to the
# PREVIOUS check, reporting an unguarded raise as guarded. That is a false negative in a
# detector whose whole job is finding unguarded raises, and my own self-test caught it.


def _raise_sites_for(validator: str) -> list[tuple[int, bool]]:
    """(line_number, reads_a_flag) for each abort guarded by this validator's result."""
    sites: list[tuple[int, bool]] = []
    for index, line in enumerate(LINES):
        if f"{validator}(" not in line or line.lstrip().startswith(("def ", "#")):
            continue
        window = LINES[index:index + LOOKAHEAD]
        for offset, candidate in enumerate(window):
            if not re.match(r"\s*raise\s+\w*Error", candidate):
                continue
            guard = "\n".join(LINES[index:index + offset + 1])
            sites.append((index + offset + 1, any(h in guard for h in FLAG_HELPERS)))
            break
    return sites


def test_every_flag_helper_is_actually_used():
    # A helper nothing calls is a flag that silently does nothing.
    for helper in FLAG_HELPERS:
        assert SOURCE.count(f"{helper}()") >= 2, (
            f"{helper} is defined but never read — the flag it exposes does nothing")


def test_a_validator_guarded_by_a_flag_is_guarded_everywhere():
    """The seven-instance bug, as an assertion.

    If ANY abort on a validator's result consults a flag, they all must. A run allowed past the
    first check and killed by the second has spent money to reach a contradiction.
    """
    inconsistent = []
    for validator in GUARDED_VALIDATORS:
        sites = _raise_sites_for(validator)
        if len(sites) < 2:
            continue
        flagged = [line for line, has_flag in sites if has_flag]
        bare = [line for line, has_flag in sites if not has_flag]
        if flagged and bare:
            inconsistent.append(
                f"{validator}: flag-aware at lines {flagged}, unguarded at lines {bare}")

    assert not inconsistent, (
        "A condition is enforced at several points but only some of them honour its flag. "
        "The unguarded copy will abort a run the flag already let through, after it has paid:\n  "
        + "\n  ".join(inconsistent))


def test_the_detector_would_catch_a_reintroduced_twin():
    """Guard the guard. A detector that cannot fail is worse than no detector.

    Six of my own checks this session passed against broken code, so this test proves the
    scanner reacts to the pattern it exists to find rather than merely returning an empty list.
    """
    flagged_raise = '''
        report = validate_claim_joins(script, dossier)
        if not report.get("passed") and _claim_ledger_hard():
            raise ValueError("guarded")
'''
    bare_raise = '''
        report = validate_claim_joins(script, dossier)
        if not report.get("passed"):
            raise ValueError("unguarded")
'''
    global LINES
    original = LINES
    try:
        LINES = (flagged_raise + bare_raise).splitlines()
        sites = _raise_sites_for("validate_claim_joins")
        assert len(sites) == 2, f"scanner found {len(sites)} raise sites, expected 2"
        assert {has_flag for _line, has_flag in sites} == {True, False}, (
            "scanner failed to tell a flag-guarded abort from a bare one")
    finally:
        LINES = original
