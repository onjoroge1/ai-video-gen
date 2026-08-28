"""The adapter must present exactly the surface the 27 call sites read.

Anthropic owns every script call, so a dead key stops the pipeline while OpenAI and fal sit
idle. This adapter lets those calls run on either provider without editing a call site. What it
must get right is narrow and specific: .content[0].text, .usage in Anthropic's token names, and
.stop_reason translated from finish_reason.

Tested against recorded response shapes — no API, no key, no spend.
"""

import pytest

from script_provider import (
    ANTHROPIC, OPENAI, OpenAIScriptClient, active_provider, reasoning_headroom,
    translate_response,
)


class _Msg:
    def __init__(self, content): self.content = content


class _Choice:
    def __init__(self, content, finish_reason="stop"):
        self.message = _Msg(content)
        self.finish_reason = finish_reason


class _Usage:
    def __init__(self, p, c): self.prompt_tokens = p; self.completion_tokens = c


class _Raw:
    def __init__(self, content, finish_reason="stop", usage=None):
        self.choices = [_Choice(content, finish_reason)]
        self.usage = usage


class _FakeCompletions:
    def __init__(self, raw): self.raw = raw; self.seen = None
    def create(self, **kwargs): self.seen = kwargs; return self.raw


class _FakeClient:
    def __init__(self, raw):
        self.chat = type("C", (), {"completions": _FakeCompletions(raw)})()


def test_provider_defaults_to_openai_and_anthropic_is_reachable(monkeypatch):
    """Default flipped to OpenAI on the operator's instruction.

    ~$300 went to Anthropic and its key then stopped authenticating. Anthropic must stay
    reachable by name -- the research call still needs its server-side web_search, and a
    one-word revert is the whole safety net if the OpenAI scripts disappoint at render scale.
    """
    monkeypatch.delenv("SCRIPT_PROVIDER", raising=False)
    assert active_provider() == OPENAI

    monkeypatch.setenv("SCRIPT_PROVIDER", "anthropic")
    assert active_provider() == ANTHROPIC, "the revert path must work"

    monkeypatch.setenv("SCRIPT_PROVIDER", "gemini")
    assert active_provider() == OPENAI, "an unknown provider falls back to the default"


def test_text_is_read_the_anthropic_way():
    out = translate_response(_Raw('{"scenes": []}'), model="gpt-5")

    assert out.content[0].text == '{"scenes": []}'


def test_token_counts_are_renamed_not_dropped():
    """The silent-$0.00 trap.

    _msg_cost reads input_tokens/output_tokens. Leaving OpenAI's names unmapped makes every run
    report zero cost, which reads as "the saving worked" rather than as a broken meter.
    """
    out = translate_response(_Raw("x", usage=_Usage(1200, 800)), model="gpt-5")

    assert out.usage.input_tokens == 1200
    assert out.usage.output_tokens == 800


def test_a_truncated_response_is_reported_as_max_tokens():
    # One call site checks this to tell "output was cut off" from "the model returned bad JSON".
    assert translate_response(_Raw("x", "length"), model="gpt-5").stop_reason == "max_tokens"
    assert translate_response(_Raw("x", "stop"), model="gpt-5").stop_reason == "end_turn"


def test_missing_usage_does_not_crash():
    out = translate_response(_Raw("x", usage=None), model="gpt-5")

    assert out.usage.input_tokens == 0


def test_system_becomes_a_message_and_max_tokens_is_renamed(monkeypatch):
    # max_tokens is renamed AND rescaled: the two providers do not mean the same thing by it,
    # so a bare rename hands most of the answer's budget to reasoning. See the budget test below.
    monkeypatch.delenv("OPENAI_SCRIPT_REASONING_HEADROOM", raising=False)
    client = OpenAIScriptClient(_FakeClient(_Raw("ok")))

    client.messages.create(model="claude-opus-4-8", max_tokens=4096,
                           system="be terse", messages=[{"role": "user", "content": "hi"}])

    sent = client.messages._client.chat.completions.seen
    assert sent["messages"][0] == {"role": "system", "content": "be terse"}
    assert sent["messages"][1] == {"role": "user", "content": "hi"}
    assert sent["max_completion_tokens"] == 4096 + reasoning_headroom()
    assert not sent["model"].startswith("claude"), "a Claude model name must not be forwarded"


def test_block_list_content_is_flattened():
    # Anthropic accepts a list of blocks as content; OpenAI wants a string.
    client = OpenAIScriptClient(_FakeClient(_Raw("ok")))

    client.messages.create(messages=[{"role": "user", "content": [
        {"type": "text", "text": "part one"}, {"type": "text", "text": "part two"}]}])

    assert client.messages._client.chat.completions.seen["messages"][0]["content"] == (
        "part one\npart two")


def test_images_survive_the_crossing():
    """The blind-grader trap.

    The quiz's vision QA call sends three base64 image blocks plus one line of text. The
    flattener kept text and recognised nothing else, so the images vanished and the grader
    answered a prompt describing pictures it never received. The renderer trusts that verdict
    enough to deepen a clue crop and to pay for a regenerated reveal, so a blind pass is worse
    than no pass.
    """
    client = OpenAIScriptClient(_FakeClient(_Raw("ok")))

    client.messages.create(messages=[{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "AAAA"}},
        {"type": "text", "text": 'Answer: "okapi".'}]}])

    content = client.messages._client.chat.completions.seen["messages"][0]["content"]
    assert isinstance(content, list), "an image message must not collapse to a bare string"
    assert content[0] == {"type": "image_url",
                          "image_url": {"url": "data:image/jpeg;base64,AAAA"}}
    assert {"type": "text", "text": 'Answer: "okapi".'} in content


def test_text_only_content_keeps_its_string_shape():
    # 26 of the 27 calls send text. Widening their shape would be churn with a chance of
    # regression, so only a message that actually carries an image changes form.
    client = OpenAIScriptClient(_FakeClient(_Raw("ok")))

    client.messages.create(messages=[{"role": "user", "content": [{"type": "text", "text": "hi"}]}])

    assert client.messages._client.chat.completions.seen["messages"][0]["content"] == "hi"


def test_anthropic_only_kwargs_do_not_raise():
    """Dropping them is correct, not lossy.

    The single call needing server-side web_search stays on the native client, so a call
    arriving here with tools= never depended on them — and raising would break calls that
    never wanted the feature.
    """
    client = OpenAIScriptClient(_FakeClient(_Raw("ok")))

    client.messages.create(messages=[{"role": "user", "content": "hi"}],
                           tools=[{"type": "web_search_20260318"}], betas=["x"])

    assert "tools" not in client.messages._client.chat.completions.seen


def test_the_answer_budget_is_not_spent_on_reasoning(monkeypatch):
    """The outage this adapter was built to prevent, caused by the adapter.

    Anthropic's max_tokens caps the visible answer; OpenAI's max_completion_tokens caps hidden
    reasoning AND the answer together. Forwarded unchanged, the quiz generator's 1800 went 1280
    to reasoning and returned an empty body, and the render aborted with "quiz generation
    failed" -- a capped Claude key swapped for a silently broken OpenAI path.
    """
    monkeypatch.delenv("OPENAI_SCRIPT_REASONING_HEADROOM", raising=False)
    client = OpenAIScriptClient(_FakeClient(_Raw("ok")))

    client.messages.create(max_tokens=1800, messages=[{"role": "user", "content": "hi"}])

    sent = client.messages._client.chat.completions.seen
    assert sent["max_completion_tokens"] == 1800 + reasoning_headroom()
    assert sent["max_completion_tokens"] > 1800, "the answer must not compete with the reasoning"


def test_truncated_empty_output_names_its_own_cause(monkeypatch):
    """Every caller feeds .text straight to a JSON parser, so an empty body arrives as "the
    model returned malformed JSON" three layers from the budget that caused it. That misdiagnosis
    cost a render here already."""
    monkeypatch.delenv("OPENAI_SCRIPT_REASONING_HEADROOM", raising=False)
    client = OpenAIScriptClient(_FakeClient(_Raw("", finish_reason="length")))

    with pytest.raises(RuntimeError, match="reasoning"):
        client.messages.create(max_tokens=450, messages=[{"role": "user", "content": "hi"}])


def test_truncated_but_non_empty_output_still_returns(monkeypatch):
    # A cut-off body is the call site's to judge -- one of them reads stop_reason to tell a
    # truncation from bad JSON. Only a body with nothing in it is unambiguously the budget.
    monkeypatch.delenv("OPENAI_SCRIPT_REASONING_HEADROOM", raising=False)
    client = OpenAIScriptClient(_FakeClient(_Raw('{"items": [', finish_reason="length")))

    out = client.messages.create(messages=[{"role": "user", "content": "hi"}])

    assert out.stop_reason == "max_tokens"
    assert out.content[0].text == '{"items": ['


def test_a_model_that_rejects_reasoning_effort_still_runs():
    """Dropping to default effort beats losing the call over a knob that only lowered cost."""
    class _PickyCompletions(_FakeCompletions):
        def create(self, **kwargs):
            if "reasoning_effort" in kwargs:
                raise TypeError("unexpected keyword argument 'reasoning_effort'")
            return super().create(**kwargs)

    client = OpenAIScriptClient(_FakeClient(_Raw("ok")))
    client.messages._client.chat.completions = _PickyCompletions(_Raw("ok"))

    out = client.messages.create(messages=[{"role": "user", "content": "hi"}])

    assert out.content[0].text == "ok"
    assert "reasoning_effort" not in client.messages._client.chat.completions.seen


def test_claude_returns_the_right_client_for_the_provider(monkeypatch):
    """_claude() is the single switch. Both paths must expose messages.create."""
    import explainer_pipeline as ep

    # Constructing either client only needs a key to exist, not to be valid -- pytest does not
    # load .env, so supply placeholders rather than skipping the assertion that matters.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("SCRIPT_PROVIDER", raising=False)
    assert isinstance(ep._claude(), OpenAIScriptClient), "default is now OpenAI"
    assert hasattr(ep._claude().messages, "create")

    monkeypatch.setenv("SCRIPT_PROVIDER", "anthropic")
    assert type(ep._claude()).__name__ == "Anthropic", "the revert path must reach Anthropic"


def test_cost_uses_the_rates_of_the_provider_that_ran(monkeypatch):
    """Billing an OpenAI run at Opus rates overstates the saving that motivated the switch.

    That is the kind of wrong number nobody questions, because it flatters the decision. The
    counts arrive either way -- the adapter renames them -- but the price does not carry over.
    """
    import explainer_pipeline as ep

    class _U:
        input_tokens = 1_000_000
        output_tokens = 1_000_000

    monkeypatch.setenv("SCRIPT_PROVIDER", "anthropic")
    anthropic_cost = ep._msg_cost(_U())

    monkeypatch.delenv("SCRIPT_PROVIDER", raising=False)
    openai_cost = ep._msg_cost(_U())

    assert anthropic_cost > 0 and openai_cost > 0, "a zero cost hides spend rather than saving it"
    assert openai_cost != anthropic_cost, "both providers billed at one rate table"
