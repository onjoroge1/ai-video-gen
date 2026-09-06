"""Two entailment boundaries, and the five cases that decide whether they work.

The sourcing validator used to be a word-set intersection: a narrated sentence passed if it shared
25% of its content words with the claim it cited. That did not merely reject good prose — it
actively rewarded narration that copied the ledger's vocabulary, which is where the lecture voice
came from. Measured on a real draft:

    "The reward paid for the metric, dead cobras, rather than actually reducing the wild
     cobra population."                                        -> PASS (10 shared words)
    "But it paid per corpse, not per empty field."             -> FAIL (0 shared words)
    "But the street cobras never thinned."                     -> PASS ("cobra", "the")

Wrong in both directions: faithful paraphrase rejected, topical coincidence accepted.

The replacement puts a factual EVENT between the research and the prose, and judges two boundaries
rather than one:

    RESEARCH CLAIMS  --(A: evidence entailment)-->  EVENT  --(B: narrative fidelity)-->  NARRATION

A alone is not enough. With only A you can bind a well-supported event and still narrate "hundreds
of secret farms sprang up behind mud-brick homes overnight" — inventing the poverty, the material,
the number, the secrecy and the timescale. The event is the factual ceiling for the prose.

The five cases below are the contract. A judge that passes 1, 2 and 5 while failing 3 and 4 has
replaced the old behaviour. One that passes everything has merely put a model where the word-count
used to be.
"""
import pytest

import claim_entailment as ce
import longform_research as lr


# --- the five adversarial cases ------------------------------------------------------------------
#
# Each is (claims, event, expected_verdict). They are data, not assertions, so the same set can be
# run against a stubbed judge for plumbing and against the live provider for judgement.

VERBATIM = (
    [{"claim_id": "c1", "claim": "The bounty paid a cash reward for every dead cobra handed in."}],
    "The bounty paid a cash reward for every dead cobra handed in.",
    "entailed",
)

PARAPHRASE = (
    [{"claim_id": "c1", "claim": "The bounty rewarded dead cobras rather than actually reducing "
                                 "the wild cobra population."}],
    # The exact sentence a measured draft produced, and the exact reason it was rejected: it shares
    # NO content words with the claim it faithfully expresses. A paraphrase that happens to reuse a
    # noun ("...not for fewer wild cobras") slips past the word-count and proves nothing.
    "But it paid per corpse, not per empty field.",
    "entailed",
)

TOPICAL_COINCIDENCE = (
    [{"claim_id": "c1", "claim": "The recorded cobra population in the district declined during "
                                 "the bounty period."}],
    "Residents operated cobra farms to collect the bounty.",
    "unsupported",
)

# The judge calls this `partially_entailed`, and it is right: the breeding IS supported, the number,
# the secrecy, the material and the timescale are not. Either verdict fails, which is the contract —
# what matters is that it does not pass and that it NAMES the four inventions.
EMBELLISHMENT = (
    [{"claim_id": "c1", "claim": "Residents bred cobras in order to claim the bounty."}],
    "Hundreds of secret cobra farms appeared behind mud-brick walls overnight.",
    "partially_entailed",
)

MULTI_CLAIM = (
    [{"claim_id": "c1", "claim": "The bounty was paid per rat tail submitted."},
     {"claim_id": "c2", "claim": "Officials observed living rats in the city without tails."}],
    "People were cutting the tails from rats and keeping the animals alive.",
    "entailed",
)

CASES = {
    "verbatim_support": VERBATIM,
    "faithful_paraphrase": PARAPHRASE,
    "topical_coincidence": TOPICAL_COINCIDENCE,
    "unsupported_embellishment": EMBELLISHMENT,
    "multi_claim_synthesis": MULTI_CLAIM,
}


# --- what the thing being replaced actually did --------------------------------------------------

def test_the_lexical_matcher_gets_the_two_decisive_cases_backwards():
    """The baseline this replaces, measured rather than described.

    Three of five come out right, but the two it gets wrong are the two that decide whether the
    writing can be good — and the one it gets right by luck shows the rule is not doing the work
    anyone thought it was:

        faithful_paraphrase       rejected   (0 shared words with a claim it faithfully states)
        topical_coincidence       accepted   (shares "cobra", asserts something else entirely)
        unsupported_embellishment rejected   -- correct, but only because it happens to share ONE
                                                word and the threshold needs two. Change the
                                                wording and it passes.

    If a later change reintroduces word-overlap as the test, this says which cases it silently
    started getting wrong again.
    """
    verdicts = {}
    for name, (claims, event, _expected) in CASES.items():
        verdicts[name] = any(lr._claim_matches_assertion(claim, event) for claim in claims)

    assert verdicts["verbatim_support"] is True
    assert verdicts["multi_claim_synthesis"] is True
    assert verdicts["faithful_paraphrase"] is False, "paraphrase now passes; the bias may be fixed"
    assert verdicts["topical_coincidence"] is True, "coincidence now fails; matcher may have changed"

    # Right for the wrong reason: one shared word against a threshold of two. Reword the
    # embellishment to share a second word and the old matcher waves it through.
    assert verdicts["unsupported_embellishment"] is False
    reworded = "Hundreds of secret cobra farms bred cobras behind mud-brick walls overnight."
    assert lr._claim_matches_assertion(EMBELLISHMENT[0][0], reworded) is True


# --- the unit of judgement is the claim SET, not one claim at a time ------------------------------

def test_the_judge_is_asked_about_all_claims_at_once():
    """An event can be supported only by several claims together.

    "Paid per tail" and "living rats seen without tails" each entail part of "people cut tails off
    and kept the animals alive". Judged one at a time, both come back unsupported and the event is
    rejected for being better evidenced than either claim alone.
    """
    seen = []

    def judge(payload):
        seen.append(payload)
        return {"verdict": "entailed", "unsupported_details": [], "reason": "both together"}

    claims, event, _ = MULTI_CLAIM
    result = ce.evidence_entailment(claims, event, judge=judge)

    assert len(seen) == 1, "the judge was called per claim instead of once per event"
    assert len(seen[0]["claims"]) == 2
    assert result["verdict"] == "entailed"


@pytest.mark.parametrize("verdict,ok", [("entailed", True), ("partially_entailed", False),
                                        ("unsupported", False), ("contradicted", False)])
def test_only_full_entailment_passes(verdict, ok):
    """`partially_entailed` is a fail. Half a fact is an unsourced fact."""
    claims, event, _ = VERBATIM
    result = ce.evidence_entailment(
        claims, event, judge=lambda _p: {"verdict": verdict, "unsupported_details": [],
                                         "reason": ""})
    assert result["passed"] is ok


def test_unsupported_details_survive_to_the_caller():
    """The repair pass needs to know WHICH detail is unsupported, not just that something is.

    claim_assertion_mismatch told the revision system nothing it could act on.
    """
    claims, event, _ = EMBELLISHMENT
    result = ce.evidence_entailment(
        claims, event,
        judge=lambda _p: {"verdict": "unsupported",
                          "unsupported_details": ["hundreds", "secret", "mud-brick", "overnight"],
                          "reason": "the claim states breeding, not scale or location"})
    assert result["passed"] is False
    assert "mud-brick" in result["unsupported_details"]
    assert result["reason"]


def test_an_unusable_judge_reply_fails_closed():
    """A malformed verdict is not a pass. Sourcing fails closed or it is not a contract."""
    claims, event, _ = VERBATIM
    for reply in ({}, {"verdict": "probably"}, None, {"verdict": ""}):
        result = ce.evidence_entailment(claims, event, judge=lambda _p, r=reply: r)
        assert result["passed"] is False


# --- boundary B: the event is the factual ceiling for the prose -----------------------------------

def test_narration_may_rephrase_the_event_freely():
    called = {}

    def judge(payload):
        called.update(payload)
        return {"verdict": "entailed", "unsupported_details": [], "reason": ""}

    result = ce.narration_fidelity(
        "Residents deliberately raised rats to collect bounty payments.",
        "Then somebody noticed: why hunt rats when you could breed them?",
        judge=judge)
    assert result["passed"] is True
    assert called["event"].startswith("Residents deliberately raised rats")
    assert "why hunt rats" in called["narration"]


def test_narration_that_invents_historical_detail_is_caught():
    """The failure mode boundary A cannot see: a well-sourced event, beautifully embellished."""
    result = ce.narration_fidelity(
        "Residents raised rats for the bounty.",
        "Behind the city's poorest mud-brick homes, hundreds of secret rat farms sprang up "
        "overnight.",
        judge=lambda _p: {"verdict": "unsupported",
                          "unsupported_details": ["poorest", "mud-brick", "hundreds", "secret",
                                                  "overnight"],
                          "reason": "the event states breeding only"})
    assert result["passed"] is False
    assert set(result["unsupported_details"]) >= {"hundreds", "overnight"}


# --- the cache is keyed on content, not on identifiers --------------------------------------------

def test_editing_a_claim_without_changing_its_id_misses_the_cache():
    """A repaired dossier can rewrite a claim and keep its ID.

    Keying on (claim_id, event) would inherit the old verdict for text nobody has judged — and
    durable resume makes that a stale PASS on a checkpoint, not just a stale value in memory.
    """
    original = [{"claim_id": "c1", "claim": "The bounty paid per rat tail."}]
    repaired = [{"claim_id": "c1", "claim": "The bounty paid per rat tail submitted before 1903."}]
    event = "People were paid for each tail they handed in."

    assert ce.cache_key(original, event) != ce.cache_key(repaired, event)


def test_the_supporting_quote_is_part_of_the_key():
    """Same claim text, re-verified against a different page passage, is a different basis."""
    a = [{"claim_id": "c1", "claim": "Paid per tail.", "support_quote": "a bounty of one cent"}]
    b = [{"claim_id": "c1", "claim": "Paid per tail.", "support_quote": "rewards were offered"}]
    assert ce.cache_key(a, "People were paid per tail.") != ce.cache_key(b, "People were paid per tail.")


def test_the_contract_version_invalidates_every_cached_verdict():
    """Changing what entailment MEANS must not silently reuse verdicts from the old meaning."""
    claims, event, _ = VERBATIM
    before = ce.cache_key(claims, event)
    assert ce.ENTAILMENT_CONTRACT_VERSION in before or before != ce.cache_key(
        claims, event, contract_version="something-else")


def test_claim_order_does_not_change_the_key():
    """The judgement is about the set, so the key must be too, or a reorder re-buys the call."""
    a = [{"claim_id": "c1", "claim": "One."}, {"claim_id": "c2", "claim": "Two."}]
    assert ce.cache_key(a, "E") == ce.cache_key(list(reversed(a)), "E")


def test_a_cached_verdict_is_not_re_bought():
    calls = []
    cache: dict = {}
    claims, event, _ = VERBATIM

    def judge(payload):
        calls.append(payload)
        return {"verdict": "entailed", "unsupported_details": [], "reason": ""}

    for _ in range(3):
        ce.evidence_entailment(claims, event, judge=judge, cache=cache)
    assert len(calls) == 1


# --- the live judge -------------------------------------------------------------------------------

@pytest.mark.entailment_live
@pytest.mark.parametrize("name", sorted(CASES))
def test_the_live_judge_decides_the_five_cases_correctly(name):
    """The test that says whether this actually works. Opt-in: it calls a paid provider.

        python3 -m pytest -m entailment_live tests/test_claim_entailment.py

    A judge that passes all five has not replaced the word-count, it has hidden it.
    """
    claims, event, expected = CASES[name]
    result = ce.evidence_entailment(claims, event)
    assert result["verdict"] == expected, result.get("reason")


# --- an outage is not a finding ------------------------------------------------------------------

def test_a_provider_failure_is_unavailable_not_unsupported():
    """Ten identical `unsupported` rows once read exactly like a substantive sourcing result.

    They were the fail-closed default from an out-of-credit provider, and they were nearly reported
    as evidence that the citations were bad. "Unsupported" means the evidence does not support the
    claim. "Unavailable" means nobody looked. Only one of those should send a rewrite pass.
    """
    def boom(_payload):
        raise RuntimeError("credit balance is too low")

    claims, event, _ = VERBATIM
    result = ce.evidence_entailment(claims, event, judge=boom)
    assert result["verdict"] == "unavailable"
    assert result["passed"] is False
    assert ce.is_retryable(result) is True
    assert "provider_unavailable" in result["reason"]


def test_a_malformed_reply_is_invalid_response_not_unsupported():
    claims, event, _ = VERBATIM
    result = ce.evidence_entailment(claims, event, judge=lambda _p: {"verdict": "probably"})
    assert result["verdict"] == "invalid_response"
    assert ce.is_retryable(result) is True


def test_a_real_semantic_failure_is_not_retryable():
    """The distinction is only useful if a genuine finding does NOT ask to be retried."""
    claims, event, _ = TOPICAL_COINCIDENCE
    result = ce.evidence_entailment(
        claims, event, judge=lambda _p: {"verdict": "unsupported", "unsupported_details": ["x"],
                                         "reason": "different subject"})
    assert ce.is_retryable(result) is False
    assert ce.repair_instruction(result)


def test_an_outage_verdict_is_never_cached():
    """A credit outage must not freeze into a stored verdict a later resume reads as decided."""
    cache: dict = {}
    claims, event, _ = VERBATIM
    calls = []

    def flaky(_payload):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("out of credit")
        return {"verdict": "entailed", "unsupported_details": [], "reason": ""}

    first = ce.evidence_entailment(claims, event, judge=flaky, cache=cache)
    second = ce.evidence_entailment(claims, event, judge=flaky, cache=cache)
    assert first["verdict"] == "unavailable"
    assert second["verdict"] == "entailed", "the outage was cached and never re-asked"


def test_the_repair_instruction_preserves_the_core_and_names_the_inventions():
    result = {"verdict": "partially_entailed", "passed": False,
              "supported_core": "Residents bred cobras for the bounty.",
              "unsupported_details": ["hundreds of farms", "overnight"], "reason": ""}
    text = ce.repair_instruction(result)
    assert "PRESERVE" in text and "Residents bred cobras" in text
    assert "hundreds of farms" in text and "overnight" in text
    assert "Do not add any new factual detail" in text
    # The instruction that stops a sourcing repair from drifting back to ledger voice.
    assert "own vocabulary" in text
