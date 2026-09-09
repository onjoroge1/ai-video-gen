"""Named narrative engines: how a causal story generates its momentum.

The contract in `causal_story` was derived from one reference video and then patched to admit a
second. That patch works — both `tool` and `verdict` are legal closes — but it flattens two
genuinely different story shapes into one contract with optional parts, and it left the validator
unable to say which shape a script was even trying to be.

An engine is that missing statement of intent. Each names a role sequence, so a script is checked
against the shape it chose rather than against a union of every shape observed so far.

The first two are not inventions. BACKFIRING_SOLUTION is the cobra-bounty reference and
ACCUMULATING_INDICTMENT is the famine reference — the same two videos the contract came from, now
distinguishable instead of merged.

One engine per video. A script that blends two produces the vocabulary-mixing failure already
measured on this pipeline: asked to satisfy two role systems at once, a planner returned duplicate
singletons and an escalation sequenced after its own reversal.
"""
from __future__ import annotations

from typing import Any

import causal_story as cs


BACKFIRING_SOLUTION = "backfiring_solution"
ACCUMULATING_INDICTMENT = "accumulating_indictment"
ALMOST_HAPPENED_PLAN = "almost_happened_plan"
ACCIDENTAL_INVENTION = "accidental_invention"
POWER_REVERSAL = "power_reversal"
REMOVED_KEYSTONE = "removed_keystone"


# REVEAL_DEADLINE_PCT: engines whose principle IS the reveal cannot state it in the first fifth.
# A counterfactual has to build the plan before it can show why the plan fails, so the mechanism
# lands past the midpoint by construction. Measured on an operator-written script whose reveal sits
# at 55% and which is good — every other check passes under backfiring_solution.
#
# This is per-engine, not a lowered global. The 0.20 default is measured from the two reference
# videos at 16.4% and 19.4%; engines built on those references keep it.
REVEAL_DEADLINE_PCT = 0.60

# Each engine states the roles it requires, in the order they must appear. Roles outside `required`
# are optional; `repeatable` may occur more than once. `closing` is the terminal role, which is the
# distinction the one-size contract could not express: a lens close hands the opening object back
# as a question, an indictment close restates the opening claim now that it is proved.
ENGINES: dict[str, dict[str, Any]] = {
    REMOVED_KEYSTONE: {
        "name": "The Removed Keystone",
        # Not a backfiring incentive. Nobody exploits anything here: a species is added or taken
        # away and the system re-sorts itself around the gap. Measured on Macquarie Island, where
        # backfiring_solution was selected because it was the only mapped engine, and its contract
        # made the compiler invent "the reward was paid for the count of cats killed" for a
        # government eradication that paid no reward. The evidence boundary refused it, correctly.
        "premise": ("A species is removed or introduced and the ECOSYSTEM re-sorts itself. "
                    "NOBODY exploits anything and no reward is paid: the harm comes from what "
                    "the species was quietly doing, not from how people responded to a rule."),
        "reference": "macquarie-island cat eradication",
        "sequence": (cs.SETUP, cs.INTERVENTION, cs.FALSE_RESOLUTION, cs.HINGE, cs.MECHANISM,
                     cs.ESCALATION, cs.REVERSAL, cs.GENERALIZATION, cs.TOOL),
        "required": (cs.SETUP, cs.INTERVENTION, cs.MECHANISM, cs.ESCALATION, cs.REVERSAL, cs.TOOL),
        "closing": cs.TOOL,
        # A cascade runs once. See causal_story's THIN_CHAIN: two escalations is right for a
        # spiral, where each round of exploitation invites the next, and wrong here.
        "min_escalations": 1,
        "audience_before": "removing the pest fixes the problem",
        "audience_after": "the pest was holding something else down",
    },
    BACKFIRING_SOLUTION: {
        "name": "The Backfiring Solution",
        # The deciding word is PEOPLE. Both this and removed_keystone answer to "a reasonable fix
        # made things worse", so the premises have to differ on the thing that actually separates
        # them, or the selector is choosing between two true descriptions. Macquarie was picked as
        # backfiring_solution on the old wording, and the compiler then invented a bounty for a
        # government cull that paid nobody.
        "premise": ("PEOPLE respond to a reward, quota or rule and produce more of what it was "
                    "meant to remove. There must be an incentive somebody exploits."),
        "reference": "cobra-bounty video",
        "sequence": (cs.SETUP, cs.INTERVENTION, cs.FALSE_RESOLUTION, cs.HINGE, cs.MECHANISM,
                     cs.ESCALATION, cs.REVERSAL, cs.GENERALIZATION, cs.TOOL),
        "required": (cs.SETUP, cs.INTERVENTION, cs.FALSE_RESOLUTION, cs.HINGE, cs.MECHANISM,
                     cs.ESCALATION, cs.REVERSAL, cs.TOOL),
        "closing": cs.TOOL,
        "audience_before": "the fix sounds sensible",
        "audience_after": "the fix was the cause",
    },
    ACCUMULATING_INDICTMENT: {
        "name": "The Accumulating Indictment",
        "premise": "A system produces the same harm repeatedly until the pattern is the verdict.",
        "reference": "Indian famine video",
        # Read off the reference, not written from memory: the profitability claim lands BEFORE
        # the system that produced it is described. That ordering is the engine's signature — the
        # story shows a working arrangement first and only then explains what it was doing to the
        # people inside it. Writing this sequence from intuition put intervention first and the
        # reference fixture rejected it, which is what the fixture is for. No generalization
        # either: the counterfactual carries the argument, which is why the close is a verdict.
        "sequence": (cs.SETUP, cs.FALSE_RESOLUTION, cs.INTERVENTION, cs.MECHANISM, cs.HINGE,
                     cs.ESCALATION, cs.REVERSAL, cs.VERDICT),
        "required": (cs.SETUP, cs.INTERVENTION, cs.MECHANISM, cs.ESCALATION, cs.REVERSAL,
                     cs.VERDICT),
        "closing": cs.VERDICT,
        "audience_before": "the harm looks like misfortune",
        "audience_after": "the harm was policy",
    },
    ALMOST_HAPPENED_PLAN: {
        "name": "The Almost-Happened Plan",
        "premise": "A serious proposal to reshape the world came close and then collapsed.",
        "reference": "1910 American hippo-import proposal",
        # Read off the reference, not written from memory — the same correction the famine fixture
        # forced on the indictment engine. An almost-happened plan runs the SAME milestone order as
        # a backfiring solution, because it is one that never got the chance to backfire: the plan
        # is pitched, it enjoys its false victory, a hinge stops it, and only then does the story
        # reveal why it would have failed. What differs is WHEN the principle can land, not the
        # order it lands in — hence the reveal deadline below rather than a reshuffled sequence.
        "sequence": (cs.SETUP, cs.INTERVENTION, cs.FALSE_RESOLUTION, cs.HINGE, cs.MECHANISM,
                     cs.ESCALATION, cs.REVERSAL, cs.GENERALIZATION, cs.TOOL),
        "required": (cs.SETUP, cs.INTERVENTION, cs.MECHANISM, cs.ESCALATION, cs.REVERSAL,
                     cs.TOOL),
        "closing": cs.TOOL,
        "mechanism_deadline_pct": REVEAL_DEADLINE_PCT,
        "audience_before": "the world could only be as it is",
        "audience_after": "it nearly went another way",
    },
    ACCIDENTAL_INVENTION: {
        "name": "The Accidental Invention",
        "premise": "A failure observed carefully becomes the thing nobody was looking for.",
        # The hinge here is the anomaly rather than a broken promise, so a false resolution is
        # optional: many of these stories have no moment of apparent success to break.
        "sequence": (cs.SETUP, cs.INTERVENTION, cs.HINGE, cs.MECHANISM, cs.ESCALATION,
                     cs.REVERSAL, cs.GENERALIZATION, cs.TOOL),
        "required": (cs.SETUP, cs.INTERVENTION, cs.HINGE, cs.MECHANISM, cs.ESCALATION,
                     cs.REVERSAL, cs.TOOL),
        "closing": cs.TOOL,
        "mechanism_deadline_pct": REVEAL_DEADLINE_PCT,
        "audience_before": "the discovery looks inevitable",
        "audience_after": "it turned on someone noticing",
    },
    POWER_REVERSAL: {
        "name": "The Power Reversal",
        "premise": "An underestimated actor holds an advantage the dominant one cannot see.",
        "sequence": (cs.SETUP, cs.FALSE_RESOLUTION, cs.INTERVENTION, cs.MECHANISM, cs.HINGE,
                     cs.ESCALATION, cs.REVERSAL, cs.VERDICT),
        "required": (cs.SETUP, cs.FALSE_RESOLUTION, cs.MECHANISM, cs.HINGE, cs.ESCALATION,
                     cs.REVERSAL, cs.VERDICT),
        "closing": cs.VERDICT,
        "audience_before": "the outcome looks settled",
        "audience_after": "the weaker side held the real advantage",
    },
}

DEFAULT_ENGINE = BACKFIRING_SOLUTION


def get(engine_id: str, *, compiled: bool = False) -> dict:
    """Look up an engine, falling back to the default rather than raising.

    A planner naming an engine that does not exist is a labelling mistake, not a reason to lose a
    script that may otherwise be sound; validation against the default will report what is wrong.
    """
    engine = ENGINES.get(str(engine_id or "").strip().lower()) or ENGINES[DEFAULT_ENGINE]
    if compiled and str(engine_id).strip().lower() == BACKFIRING_SOLUTION:
        return dict(engine, compiled_compounding=True)
    return engine


def resolve_id(engine_id: str) -> str:
    key = str(engine_id or "").strip().lower()
    return key if key in ENGINES else DEFAULT_ENGINE


def catalogue(only: list[str] | tuple[str, ...] | None = None) -> str:
    """The engines as prompt text, so the selector and the validator cannot disagree.

    `only` narrows the list to specific engine ids. The selector uses it to hide engines whose
    required beats cannot fit the requested runtime: offering an engine that is arithmetically
    impossible invites the model to pick it, and a preference expressed in prose has already been
    measured losing to the model's read of which story shape fits the topic.
    """
    allowed = [engine_id for engine_id in ENGINES if engine_id in set(only)] if only else None
    blocks = []
    for engine_id, engine in ENGINES.items():
        if allowed is not None and engine_id not in allowed:
            continue
        blocks.append(
            f"{engine_id}: {engine['name']} — {engine['premise']}\n"
            f"    beats in order: {' -> '.join(engine['sequence'])}\n"
            f"    required: {', '.join(engine['required'])}\n"
            f"    audience believes at the start: {engine['audience_before']}\n"
            f"    audience understands at the end: {engine['audience_after']}")
    return "\n".join(blocks)


def expected_order(engine_id: str) -> list[str]:
    return list(get(engine_id)["sequence"])


def closing_role(engine_id: str) -> str:
    return get(engine_id)["closing"]


def minimum_beats(engine: dict | None) -> int:
    """The fewest beats this engine can tell its story in.

    Every required role needs a beat of its own. Escalation is the exception: it is the one
    required role the contract expects to repeat, so it costs MIN_ESCALATIONS beats rather than
    one. Generalization repeats too but is never required, so it costs nothing here.

    This is the number the scene planner has always computed inline. It lives here because the
    runtime check below needs the same figure, and a feasibility gate that disagreed with the
    planner about how many beats an engine needs would pass plans the planner then breaks.
    """
    if not engine:
        return 0
    return (len(set(engine.get("required") or ()) - {cs.ESCALATION}) + cs.MIN_ESCALATIONS
            - int(bool(engine.get("compiled_compounding"))))


def mechanism_deadline_pct(engine: dict | None, default: float) -> float:
    """Where this engine's principle must land, as a fraction of runtime.

    Engines derived from the reference videos keep the measured default. A reveal-structured
    engine declares its own, because demanding an early principle from a story whose principle is
    the ending would reject the story rather than improve it.
    """
    return float((engine or {}).get("mechanism_deadline_pct") or default)
