"""The adapter must present exactly the surface the 27 call sites read.

Anthropic owns every script call, so a dead key stops the pipeline while OpenAI and fal sit
idle. This adapter lets those calls run on either provider without editing a call site. What it
must get right is narrow and specific: .content[0].text, .usage in Anthropic's token names, and
.stop_reason translated from finish_reason.

Tested against recorded response shapes — no API, no key, no spend.
"""

import pytest

from script_provider import (
    ANTHROPIC, OPENAI, OpenAIScriptClient, active_provider, translate_response,
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


def test_provider_defaults_to_anthropic(monkeypatch):
    # Behaviour must not change until someone opts in.
    monkeypatch.delenv("SCRIPT_PROVIDER", raising=False)
    assert active_provider() == ANTHROPIC
    monkeypatch.setenv("SCRIPT_PROVIDER", "openai")
    assert active_provider() == OPENAI
    monkeypatch.setenv("SCRIPT_PROVIDER", "gemini")
    assert active_provider() == ANTHROPIC, "an unknown provider must not silently switch"


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


def test_system_becomes_a_message_and_max_tokens_is_renamed():
    client = OpenAIScriptClient(_FakeClient(_Raw("ok")))

    client.messages.create(model="claude-opus-4-8", max_tokens=4096,
                           system="be terse", messages=[{"role": "user", "content": "hi"}])

    sent = client.messages._client.chat.completions.seen
    assert sent["messages"][0] == {"role": "system", "content": "be terse"}
    assert sent["messages"][1] == {"role": "user", "content": "hi"}
    assert sent["max_completion_tokens"] == 4096
    assert not sent["model"].startswith("claude"), "a Claude model name must not be forwarded"


def test_block_list_content_is_flattened():
    # Anthropic accepts a list of blocks as content; OpenAI wants a string.
    client = OpenAIScriptClient(_FakeClient(_Raw("ok")))

    client.messages.create(messages=[{"role": "user", "content": [
        {"type": "text", "text": "part one"}, {"type": "text", "text": "part two"}]}])

    assert client.messages._client.chat.completions.seen["messages"][0]["content"] == (
        "part one\npart two")


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
