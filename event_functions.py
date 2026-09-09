"""What a fact IS, kept separate from what a story DOES with it.

Measured on five Hanoi beat sheets with cached research and a real evidence judge: the planner's
factual events were stable and its causal roles were not. The endpoints never moved -- setup 5/5,
generalization 5/5 -- and every confusion sat inside mechanism / hinge / escalation:

    exploit_behavior     escalation 4   hinge 2   mechanism 1
    reveals_proxy_gap    mechanism 4    escalation 1
    inverted_end_state   reversal 5     escalation 1   hinge 1

That is not a flaky model. "Residents cut the tails off rats and released them" genuinely reveals
the proxy failure, genuinely turns the story, and genuinely escalates the consequences. Asking
which of the three it *is* has three defensible answers, so it got a different one each run, and
the rest of the story became structurally impossible from perfectly good facts.

So the planner is asked only what a fact is -- something decidable by looking at the fact -- and
the story roles are compiled from that. Three layers that were previously one `role` field:

    event function     what the fact is           planner, evidence-bound
    story role         what the story does        compiled, deterministic
    narration device   how it is said             expansion; hook, hinge, callback

`hinge` lives in the third layer now. It is a presentation device -- "Except there was a
problem." -- and it was never something an archive could evidence.

Two roles are DERIVED rather than assigned, because neither is a historical event:

  mechanism  is a relationship between the intervention and its goal, not something that happened.
             `changes_incentive` carries `incentive.rewarded_measure` and `incentive.actual_goal`,
             and the mechanism is the gap between them. Both halves are evidence-bound: measured,
             4 of 5 sheets already wrote the rewarded measure correctly and unprompted, while
             `actual_goal` is an imputation of intent -- exactly what the fidelity boundary flags
             in narration -- so it carries its own claim_refs or it does not count.

  reversal   is a comparison between the setup state and the state the exploit compounds into.
             It is NOT sourced from an "outcome" event, and this is measured rather than assumed:
             across five sheets the planner wrote seven phrasings of the ending and every one of
             them said the bounty produced tails without reducing the rat population. That is
             failure, not inversion. The archives record the failure; nobody in 1902 wrote down
             that living rats had become valuable. Farming them is the documented form of it, so
             the reversal is computed from `compounds_exploit` and both ends stay sourced.
"""
from __future__ import annotations

import re

# --- the intrinsic layer: what a fact is ------------------------------------------------------
ESTABLISHES_PROBLEM = "establishes_problem"
CHANGES_INCENTIVE = "changes_incentive"
APPARENT_SUCCESS = "apparent_success"
EXPLOIT_BEHAVIOR = "exploit_behavior"
COMPOUNDS_EXPLOIT = "compounds_exploit"
OUTCOME_STATE = "outcome_state"
CONTEXT = "context"
PARALLEL_CASE = "parallel_case"

# --- the almost_happened_plan family ------------------------------------------------------------
# A different shape, so different functions. Measured on "Why don't Americans eat hippo meat?", the
# planner had every one of these facts and filed them under the wrong roles: the Lacey Act, which is
# what actually killed the 1910 American Hippo Bill, arrived as an `escalation`; "the Bill never
# passed, and hippo meat never entered the U.S. diet" arrived as the closing `tool`; and the
# `mechanism` slot got "U.S. wildlife policy distinguishes legal from unsustainable harvesting" -- a
# policy generality, not a thing that happened. Same ambiguity backfiring_solution had before it was
# given a map.
PLAN_PROPOSED = "plan_proposed"
GAINS_BACKING = "gains_backing"
OPPOSITION_MOUNTS = "opposition_mounts"
COLLAPSE_CAUSE = "collapse_cause"
WORLD_WITHOUT_IT = "world_without_it"

# --- the removed_keystone family ----------------------------------------------------------------
# Nobody exploits anything in these. A species is added or taken away and the system re-sorts
# itself around the gap, so `changes_incentive` and `exploit_behavior` have no referents: Macquarie
# Island's cats were shot by a government programme that paid no reward, and asking that story for
# a rewarded measure made the compiler invent one.
#
# HIDDEN_LINK is the load-bearing one and it is a FACT, not a relationship to be computed. Every
# story of this shape turns on the same discovery -- what else the species was doing that nobody
# counted. The cats were also eating the rabbits. The stoats preferred birds to rabbits. The
# sparrows were eating insects, not only grain. Each of those is one sourceable sentence.
ESTABLISHES_BALANCE = "establishes_balance"
SPECIES_MOVED = "species_moved"
INTENDED_EFFECT = "intended_effect"
HIDDEN_LINK = "hidden_link"
POPULATION_RESPONDS = "population_responds"
SYSTEM_RESETTLES = "system_resettles"

EVENT_FUNCTIONS = (ESTABLISHES_PROBLEM, CHANGES_INCENTIVE, APPARENT_SUCCESS, EXPLOIT_BEHAVIOR,
                   COMPOUNDS_EXPLOIT, OUTCOME_STATE,
                   PLAN_PROPOSED, GAINS_BACKING, OPPOSITION_MOUNTS, COLLAPSE_CAUSE,
                   WORLD_WITHOUT_IT,
                   ESTABLISHES_BALANCE, SPECIES_MOVED, INTENDED_EFFECT, HIDDEN_LINK,
                   POPULATION_RESPONDS, SYSTEM_RESETTLES,
                   CONTEXT, PARALLEL_CASE)

# Deliberately NOT load-bearing. It reads like the natural home for the ending and it is a trap:
# what the archives actually hold is "the bounty produced tails and no fewer rats", which is the
# failure the intervention already implies, not a property of the world that inverted.
CONTEXTUAL_FUNCTIONS = (OUTCOME_STATE, CONTEXT, PARALLEL_CASE)

WHAT_EACH_FUNCTION_IS = {
    ESTABLISHES_PROBLEM: "the condition that made anyone act — the problem as it stood before "
                         "anybody intervened",
    CHANGES_INCENTIVE: "the moment a rule, price, bounty or policy made a behaviour pay. NOT any "
                       "official action: hiring crews to do the work directly changes no "
                       "incentive, and is context or an earlier failed attempt",
    APPARENT_SUCCESS: "the measured signal that the policy was working, on the policy's own terms",
    EXPLOIT_BEHAVIOR: "what people did once the reward could be earned without producing the "
                      "result — the first behaviour the rule paid for and nobody wanted",
    COMPOUNDS_EXPLOIT: "the exploit industrialised: done deliberately, at scale, or as a trade",
    OUTCOME_STATE: "how the episode ended, as recorded. Context only — a programme that failed is "
                   "not by itself the story's reversal",
    CONTEXT: "background a viewer needs that is not a step of the causal chain",
    PARALLEL_CASE: "the same failure in another place or domain, for the generalisation only",
    PLAN_PROPOSED: "the moment a specific plan was formally put forward — a bill, a filing, a "
                   "commissioned design. NOT the idea circulating: the proposal itself",
    GAINS_BACKING: "the first official signal it might really happen — a hearing, an endorsement, "
                   "a figure put on the record by someone with standing",
    OPPOSITION_MOUNTS: "the counter-force gathering: who stood against it and on what grounds",
    COLLAPSE_CAUSE: "the specific thing that killed it. An event, not a principle — a vote, a "
                    "competing law, a war, a death. If you cannot name what happened, this is "
                    "missing rather than abstract",
    WORLD_WITHOUT_IT: "what we live with because it did not happen, stated as record: the plan "
                      "failed and this is the world that followed",
    ESTABLISHES_BALANCE: "the state of the place before anyone moved a species — who was eating "
                         "whom, and what was being held in check",
    SPECIES_MOVED: "the moment a species was deliberately removed or introduced, and what it was "
                   "meant to achieve",
    INTENDED_EFFECT: "the target species responding as intended — the part that worked",
    HIDDEN_LINK: "what else that species was doing that nobody counted. This is the whole story: "
                 "the cats were also eating the rabbits; the stoats preferred birds to rabbits; "
                 "the sparrows ate insects and not only grain. One sourceable sentence about a "
                 "connection that existed before anyone acted on it",
    POPULATION_RESPONDS: "the population that was being held down, no longer held down — "
                         "measured, with numbers where the record has them",
    SYSTEM_RESETTLES: "what the place became. Not 'the programme failed' but the new state: what "
                      "now grows there, what no longer does, what it costs to keep",
}


class EngineFunctionMap:
    """One engine's contract: which functions it needs, and how they become story roles.

    Per engine on purpose. `backfiring_solution` is the only engine measured so far, and the four
    others still assign roles the old way -- a mapping written for a bounty story would quietly
    become the contract for an accidental invention, which has no incentive to change.
    """

    def __init__(self, engine_id, required, to_role, derived=(), role_meanings=None,
                 claim_kinds=None):
        self.engine_id = engine_id
        self.required = tuple(required)
        self.to_role = dict(to_role)
        self.derived = tuple(derived)
        # What each role MEANS here. The shared defaults describe a bounty that ran, so an engine
        # about a plan that never ran was being told its escalation should show "HOW people exploit
        # it, compounding" -- of a bill dying in committee, where nobody exploits anything. A role
        # name shared across engines does not make the job shared.
        self.role_meanings = dict(role_meanings or {})
        self.claim_kinds = dict(claim_kinds or {})

    def role_for(self, function: str) -> str:
        return self.to_role.get((function or "").strip().lower(), "")

    def missing(self, functions) -> list:
        present = {(f or "").strip().lower() for f in functions}
        return [f for f in self.required if f not in present]


BACKFIRING_SOLUTION = EngineFunctionMap(
    "backfiring_solution",
    required=(ESTABLISHES_PROBLEM, CHANGES_INCENTIVE, APPARENT_SUCCESS, EXPLOIT_BEHAVIOR,
              COMPOUNDS_EXPLOIT),
    to_role={ESTABLISHES_PROBLEM: "setup",
             # compounds_exploit is BOTH the last escalation and the state the story inverts into.
             # It is re-roled to reversal rather than copied, so one event never occupies two
             # required roles -- the duplicate detector is right to call that a missing role.
             COMPOUNDS_EXPLOIT: "reversal",
             CHANGES_INCENTIVE: "intervention",
             APPARENT_SUCCESS: "false_resolution",
             EXPLOIT_BEHAVIOR: "escalation",
             PARALLEL_CASE: "generalization",
             # Named explicitly so a contextual beat cannot keep a causal role. The pacing `role`
             # enum and the causal one overlap on mechanism, escalation and reversal, so a beat
             # left unassigned inherits a causal role from the pacing field -- measured: a
             # `context` beat arrived labelled `mechanism` and occupied the slot.
             OUTCOME_STATE: "context", CONTEXT: "context"},
    derived=("mechanism", "reversal"))

# No derived roles. In backfiring_solution the mechanism has to be COMPUTED because "what pays is
# not what was wanted" is a relationship nobody recorded. Here the mechanism is a thing that
# happened -- the Lacey Act passed, the war came, the sponsor died -- so it is sourced like any
# other event, and inventing a derivation for it would manufacture the problem the map exists to
# avoid. The asymmetry is the point: derive only what the archives cannot state.
ALMOST_HAPPENED_PLAN = EngineFunctionMap(
    "almost_happened_plan",
    required=(ESTABLISHES_PROBLEM, PLAN_PROPOSED, GAINS_BACKING, COLLAPSE_CAUSE,
              WORLD_WITHOUT_IT),
    to_role={ESTABLISHES_PROBLEM: "setup",
             PLAN_PROPOSED: "intervention",
             GAINS_BACKING: "false_resolution",
             OPPOSITION_MOUNTS: "escalation",
             COLLAPSE_CAUSE: "mechanism",
             WORLD_WITHOUT_IT: "reversal",
             PARALLEL_CASE: "generalization",
             OUTCOME_STATE: "context", CONTEXT: "context"},
    role_meanings={
        "setup": "the pressure that made anyone propose something",
        "intervention": "the plan formally put on the table",
        "false_resolution": "the moment it looked like it would really happen",
        "escalation": "the opposition gathering against it",
        "mechanism": "the specific thing that killed it",
        "reversal": "the world we live in because it did not happen",
        "tool": "hands back a reusable lens"})

# No derived roles, for the same reason as almost_happened_plan: HIDDEN_LINK is a fact somebody
# recorded, not a relationship the compiler has to compute from two halves.
REMOVED_KEYSTONE = EngineFunctionMap(
    "removed_keystone",
    required=(ESTABLISHES_BALANCE, SPECIES_MOVED, HIDDEN_LINK, POPULATION_RESPONDS,
              SYSTEM_RESETTLES),
    to_role={ESTABLISHES_BALANCE: "setup",
             SPECIES_MOVED: "intervention",
             INTENDED_EFFECT: "false_resolution",
             HIDDEN_LINK: "mechanism",
             POPULATION_RESPONDS: "escalation",
             SYSTEM_RESETTLES: "reversal",
             PARALLEL_CASE: "generalization",
             OUTCOME_STATE: "context", CONTEXT: "context"},
    # A food-web relationship can establish the prior ecology and explain the aftermath.
    # Its use as setup does not turn a mechanism-labelled source into an historical event.
    # Boundary A must still establish that the particular setup follows from that source.
    claim_kinds={"setup": ("event", "context", "outcome", "mechanism")},
    role_meanings={
        "setup": "who was eating whom before anyone intervened",
        "intervention": "the species deliberately removed or introduced",
        "false_resolution": "the target responding as intended — the part that worked",
        "mechanism": "what else that species was doing that nobody counted",
        "escalation": "the population no longer held down, surging",
        "reversal": "what the place became",
        "tool": "hands back a reusable lens"})

MAPS = {engine.engine_id: engine
        for engine in (BACKFIRING_SOLUTION, ALMOST_HAPPENED_PLAN, REMOVED_KEYSTONE)}


def map_for(engine_id: str) -> EngineFunctionMap | None:
    """The function contract for this engine, or None where roles are still model-assigned."""
    return MAPS.get((engine_id or "").strip().lower())


# --- the reversal test -------------------------------------------------------------------------
# "The bounty produced huge tail counts but made no dent in the rat population" is the sentence
# every one of five sheets reached for, and it is not a reversal: its subject is the programme and
# its predicate is that the programme did not work. A reversal is about the SETUP's subject, and
# says that something is now true of it which was false before.
_MERE_FAILURE = re.compile(
    r"\b(?:made no (?:dent|reduction|difference)|did not (?:fall|drop|decline|work|reduce)|"
    r"no reduction|failed to (?:reduce|eliminate|control|solve)|without reducing|"
    r"never (?:fell|dropped|declined)|was (?:abandoned|cancelled|scrapped|ended))\b", re.I)
