"""One script-generation provider behind the Anthropic call surface.

Anthropic owns every script call in this pipeline — 27 plain completions plus one that needs
its server-side web_search — so a dead or capped key stops the whole thing while OpenAI and fal
sit idle. This adapter lets the 27 run on either provider without touching a single call site:
it accepts `messages.create(...)` and returns an object exposing `.content[0].text`, `.usage`
and `.stop_reason`, which is all those callers read.

Deliberately shaped like the Anthropic client rather than introducing a neutral interface.
Renaming 28 call sites to a new abstraction is a large diff whose only payoff is aesthetic, and
every large diff in this file today has carried a bug. The adapter absorbs the difference in one
place instead.

The research call is NOT covered. It relies on `web_search_20260318`, a server-side tool with no
OpenAI equivalent in this shape, so it stays on Anthropic and `research_is_required()` lets an
operator-supplied script skip it entirely.

SCRIPT_PROVIDER=openai switches; anything else keeps Anthropic, so behaviour is unchanged until
someone opts in.
"""

from __future__ import annotations

import os
from typing import Any


ANTHROPIC = "anthropic"
OPENAI = "openai"


def active_provider() -> str:
    """Which provider script calls should use. Anthropic unless explicitly switched."""
    choice = (os.environ.get("SCRIPT_PROVIDER", "") or "").strip().lower()
    return OPENAI if choice == OPENAI else ANTHROPIC


def openai_script_model() -> str:
    return (os.environ.get("OPENAI_SCRIPT_MODEL", "") or "gpt-5").strip()


class _TextBlock:
    """Stands in for an Anthropic content block. Callers read `.text`."""

    __slots__ = ("text", "type")

    def __init__(self, text: str) -> None:
        self.text = text
        self.type = "text"


class _Usage:
    """Anthropic-named token counts, whatever the provider called them.

    _msg_cost reads input_tokens/output_tokens. Leaving OpenAI's prompt_tokens/completion_tokens
    unmapped would make getattr(usage, "input_tokens", 0) return 0 and every run would report a
    cost of $0.00 — which reads as "the saving worked" rather than as a broken meter.
    """

    __slots__ = ("input_tokens", "output_tokens")

    def __init__(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        self.input_tokens = int(input_tokens or 0)
        self.output_tokens = int(output_tokens or 0)


class _Response:
    """The subset of an Anthropic message the 27 call sites actually touch."""

    __slots__ = ("content", "usage", "stop_reason", "provider", "model")

    def __init__(self, text: str, usage: _Usage, stop_reason: str,
                 provider: str, model: str) -> None:
        self.content = [_TextBlock(text)]
        self.usage = usage
        self.stop_reason = stop_reason
        self.provider = provider
        self.model = model


def _flatten(content: Any) -> str:
    """Anthropic accepts a list of blocks as message content; OpenAI wants a string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            else:
                text = getattr(block, "text", None)
                if text:
                    parts.append(str(text))
        return "\n".join(part for part in parts if part)
    return str(content or "")


def translate_response(raw: Any, *, model: str) -> _Response:
    """An OpenAI chat completion, in the shape the Anthropic call sites expect."""
    choice = raw.choices[0]
    text = getattr(choice.message, "content", "") or ""
    usage = getattr(raw, "usage", None)
    # finish_reason "length" is OpenAI's way of saying max_tokens. One call site checks this to
    # detect a truncated JSON body, and a mistranslation there turns "output was cut off" into
    # "the model returned malformed JSON" — a misdiagnosis this codebase has paid for repeatedly.
    stop = "max_tokens" if getattr(choice, "finish_reason", "") == "length" else "end_turn"
    return _Response(
        text=text,
        usage=_Usage(getattr(usage, "prompt_tokens", 0) if usage else 0,
                     getattr(usage, "completion_tokens", 0) if usage else 0),
        stop_reason=stop,
        provider=OPENAI,
        model=model,
    )


class _OpenAIMessages:
    def __init__(self, client: Any) -> None:
        self._client = client

    def create(self, *, model: str = "", max_tokens: int = 1024, system: str = "",
               messages: list | None = None, **_ignored: Any) -> _Response:
        """Anthropic's signature, OpenAI underneath.

        `_ignored` swallows Anthropic-only kwargs (tools, betas, temperature shapes) rather than
        raising. The one call site that genuinely needs server-side search does not come through
        here — it stays on the native client — so silently dropping those is correct rather than
        lossy, and a TypeError would take down calls that never needed the feature.
        """
        target = openai_script_model() if not model or model.startswith("claude") else model
        payload = []
        if system:
            payload.append({"role": "system", "content": system})
        for message in messages or []:
            payload.append({
                "role": message.get("role", "user"),
                "content": _flatten(message.get("content")),
            })
        raw = self._client.chat.completions.create(
            model=target,
            messages=payload,
            max_completion_tokens=int(max_tokens),
        )
        return translate_response(raw, model=target)


def script_client(base: Any) -> Any:
    """An OpenAI client timed for SCRIPT generation, not for images and TTS.

    The pipeline's shared _openai() is built with timeout=90s and max_retries=0, which suits a
    TTS clip or one image. A script call carries max_tokens up to 20000 and reasons over a long
    prompt; all three of my first OpenAI harness runs died on APITimeoutError at 90 seconds.
    Reusing that client was in my own plan and it was wrong -- the settings belong to a
    different workload.

    Mirrors the Anthropic side instead: a long timeout and real retries, because one failed call
    aborts a render that has already paid for everything before it.
    """
    try:
        return base.with_options(
            timeout=float(os.environ.get("OPENAI_SCRIPT_TIMEOUT_SEC", "600")),
            max_retries=int(os.environ.get("OPENAI_SCRIPT_MAX_RETRIES", "4")),
        )
    except Exception:
        # with_options is the supported path; if a future SDK drops it, a slow client beats none.
        return base


class OpenAIScriptClient:
    """Exposes `.messages.create(...)`, so `_claude()` can return it unchanged."""

    def __init__(self, client: Any) -> None:
        self.messages = _OpenAIMessages(script_client(client))
