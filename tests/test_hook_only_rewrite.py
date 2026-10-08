"""When the planner cannot reach the hook contract, a hook-only rewrite is asked for the sentence
alone (killer bees V10, 2026-10-07: the planner returned 48 twice and a hook naming Warwick Kerr
shipped with every other gate green)."""
import json
import explainer_pipeline as ep
import hook_patterns as hp

DOSSIER = {"claims": [
    {"claim_id": "c01", "claim": "In October 1957 a local beekeeper removed the queen excluders."},
    {"claim_id": "c02", "claim": "Twenty-six African queens escaped with small swarms."},
]}
KERR = "You watch Warwick Kerr bring African bees to Brazil for honey—then the boxes cannot hold them."


class _Fake:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0
        outer = self

        class _M:
            def create(self, **kwargs):
                outer.calls += 1
                text = json.dumps({"hook": outer.replies.pop(0)})
                return type("R", (), {"content": [type("C", (), {"text": text})()],
                                      "usage": type("U", (), {"input_tokens": 500, "output_tokens": 40})()})()
        self.messages = _M()


def test_best_of_three_is_kept_only_when_it_scores_higher(monkeypatch):
    hp.register_people(DOSSIER)
    fake = _Fake(["Warwick Kerr imported bees.",                                   # worse
                  "Your hive could face twenty-six escaped queens; nobody checked the excluders.",  # better
                  "irrelevant third"])
    monkeypatch.setattr(ep, "_claude", lambda: fake)
    monkeypatch.setattr(ep, "_msg_cost", lambda usage: 0.01)
    best, cost = ep._rewrite_hook_to_contract({"hook": KERR, "title": "t", "throughline": "x"}, DOSSIER, [])
    assert best.startswith("Your hive could face twenty-six")
    assert hp.score_hook(best)["score"] >= 70
    assert fake.calls == 2, "stops as soon as a candidate clears the contract"
    assert cost > 0


def test_a_rewrite_that_never_improves_leaves_the_hook_alone(monkeypatch):
    fake = _Fake(["Warwick Kerr imported bees.", "Kerr did it.", "The ministry acted."])
    monkeypatch.setattr(ep, "_claude", lambda: fake)
    monkeypatch.setattr(ep, "_msg_cost", lambda usage: 0.01)
    best, _ = ep._rewrite_hook_to_contract({"hook": KERR}, DOSSIER, [])
    assert best == KERR and fake.calls == 3


def test_an_over_long_winner_is_refused(monkeypatch):
    long = ("Your hive could face twenty-six escaped queens and nobody checked the excluders at all "
            "that whole long autumn season in Brazil")   # 22 words against a cap of 18
    fake = _Fake([long, long, long])
    monkeypatch.setattr(ep, "_claude", lambda: fake)
    monkeypatch.setattr(ep, "_msg_cost", lambda usage: 0.01)
    best, _ = ep._rewrite_hook_to_contract({"hook": KERR}, DOSSIER, [])
    assert best == KERR
