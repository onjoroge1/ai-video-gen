"""The myth-buster opening (OPENING_HOOK=myth): opt-in, and the default ladder is unchanged."""
import hook_patterns as hp


def test_myth_lines_count_as_the_frame_only_in_myth_mode(monkeypatch):
    line = "You'd think killer bees carry deadlier venom."
    monkeypatch.delenv("OPENING_HOOK", raising=False)
    assert not hp.frame_names_role(line)
    monkeypatch.setenv("OPENING_HOOK", "myth")
    assert hp.frame_names_role(line)
    assert hp.score_hook(line, ladder=True)["score"] == 100
    # A myth line that narrates an event is still not a frame.
    assert not hp.frame_names_role("You'd think the queens escaped by accident.")
    # The ordinary frame keeps working in myth mode.
    assert hp.frame_names_role("Imagine you're a beekeeper in Brazil, trying to fill jars.")


def test_the_rules_switch_with_the_mode(monkeypatch):
    monkeypatch.delenv("OPENING_HOOK", raising=False)
    assert hp.opening_rules() == hp.OPENING_RULES and hp.frame_rules() == hp.FRAME_RULES
    assert hp.opening_writer_rules() == hp.OPENING_WRITER_RULES
    assert hp.opening_body_rule() == hp.OPENING_BODY_RULE
    monkeypatch.setenv("OPENING_HOOK", "myth")
    assert "MYTH-BUSTER OPENING" in hp.opening_rules() and "THE MYTH LINE" in hp.frame_rules()
    assert "the bust" in hp.opening_writer_rules() and "ANSWERS the opening's question" in hp.opening_body_rule()
    assert "never 'people believe'" in hp.opening_rules()
