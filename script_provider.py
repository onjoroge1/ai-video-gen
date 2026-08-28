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
    """Which provider script calls should use. OpenAI by default.

    Switched on the operator's instruction after ~$300 went to Anthropic and its key stopped
    authenticating outright. SCRIPT_PROVIDER=anthropic reverts, and the research call never came
    through here in the first place -- it still needs Anthropic's server-side web_search.

    The cost driver was never the per-call price. One script pass is under a cent either way; a
    RENDER re-runs the chain -- beat sheet, expansions, fact-check, multi-candidate grading,
    replan, refits -- so a failing render multiplies it 20-40x, and today had ~25 of those. The
    provider swap does far less for the bill than the pre-spend gates do.
    """
    choice = (os.environ.get("SCRIPT_PROVIDER", "") or "").strip().lower()
    return ANTHROPIC if choice == ANTHROPIC else OPENAI


def openai_script_model() -> str:
    """Default gpt-5.6-luna, measured against gpt-5 and gpt-5-mini on one script pass each.

                    time     cost      cadence   retention   evidence
      gpt-5.6-luna   442s   $0.009      27%        85/100     4 errors
      gpt-5         >600s   $0.016      36%         0/100     0 errors
      gpt-5-mini     931s   $0.265      50%        88/100     1 error

    gpt-5 wrote the best sentences and ignored the structural contract entirely. gpt-5-mini cost
    THIRTY TIMES luna and ran eight minutes slower -- the "mini" name means smaller weights, not
    cheaper output, and its reasoning tokens bill as output. Anyone reaching for it to save money
    would raise this build's script cost 33x. Luna was the only one near Anthropic on both price
    and speed while respecting the contract.

    All three cleared the 25% cadence bar that Anthropic's median (17%) cleared about a quarter
    of the time -- consistent across three models, so probably a real difference rather than noise.

    ONE SAMPLE EACH. A confirming batch was still running when this default was set, and luna's
    4 evidence join errors -- factual scenes with no source attached -- are the number to watch.
    If those prove systematic rather than a one-off, luna is wrong for an evidence-led format
    whatever its cadence looks like.
    """
    return (os.environ.get("OPENAI_SCRIPT_MODEL", "") or "gpt-5.6-luna").strip()


def reasoning_effort() -> str:
    """How hard the OpenAI model thinks before it writes. Low suits this workload.

    Every call here fills a fixed JSON schema from a long, prescriptive system prompt. That is
    instruction-following, not deduction, and reasoning tokens are billed as output and counted
    against the same budget as the answer.
    """
    return (os.environ.get("OPENAI_SCRIPT_REASONING_EFFORT", "") or "low").strip()


def reasoning_headroom() -> int:
    """Tokens added on top of a call site's max_tokens to pay for hidden reasoning.

    The two providers do not mean the same thing by a token budget. Anthropic's max_tokens caps
    the VISIBLE answer; OpenAI's max_completion_tokens caps reasoning AND the visible answer out
    of one pot. All 27 budgets here were sized against Anthropic's meaning, so forwarding them
    unchanged silently reassigns most of each one to thinking.

    Measured, not guessed: the quiz generator asks for 1800 and gpt-5 spent 1280 on reasoning at
    effort=low before writing anything — then hit the cap with an EMPTY body. The pipeline read
    that as "quiz generation failed" and aborted a render, which is how a saving turns into an
    outage. The visible answer was 537 tokens; the call site's 1800 was never the problem.
    """
    try:
        return max(0, int(os.environ.get("OPENAI_SCRIPT_REASONING_HEADROOM", "") or 4000))
    except ValueError:
        return 4000


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


def _image_part(block: dict) -> dict | None:
    """One Anthropic image block as OpenAI's image part, or None if it is not an image."""
    if block.get("type") != "image":
        return None
    source = block.get("source") or {}
    if source.get("type") == "base64":
        media_type = str(source.get("media_type") or "image/jpeg")
        data = str(source.get("data") or "")
        if not data:
            return None
        return {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{data}"}}
    url = str(source.get("url") or "")
    return {"type": "image_url", "image_url": {"url": url}} if url else None


def _content(content: Any) -> Any:
    """Message content in OpenAI's shape, keeping any images instead of dropping them.

    _flatten answers "what is the text of this message", which is the whole answer for the 26
    text-only script calls. It was the whole answer for all of them until the quiz's vision QA
    pass came through here: that call sends three base64 image blocks plus one line of text, and
    a block the flattener does not recognise simply vanishes. The grader then received a system
    prompt describing three images it could not see, and answered anyway — a JSON verdict on
    imaginary images, which the renderer trusts enough to deepen a clue crop and to pay for a
    regenerated reveal.

    A silently blind QA gate is worse than an absent one, so images become OpenAI content parts.
    Text-only content still returns a plain string: that is the shape 26 calls already send, and
    widening it for them would be churn with a chance of regression.
    """
    if not isinstance(content, list):
        return _flatten(content)
    images = [part for part in (_image_part(b) for b in content if isinstance(b, dict)) if part]
    if not images:
        return _flatten(content)
    text = _flatten(content)
    parts: list[dict] = list(images)
    if text:
        parts.append({"type": "text", "text": text})
    return parts


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
                "content": _content(message.get("content")),
            })
        # max_tokens is the call site's allowance for the ANSWER. OpenAI bills reasoning from the
        # same budget, so it is forwarded with headroom rather than as-is; see reasoning_headroom.
        budget = int(max_tokens) + reasoning_headroom()
        kwargs = {"model": target, "messages": payload, "max_completion_tokens": budget}
        effort = reasoning_effort()
        try:
            raw = self._client.chat.completions.create(reasoning_effort=effort, **kwargs)
        except Exception as exc:
            # A non-reasoning model rejects the parameter outright. Losing the call over a knob
            # that only ever lowered cost would be a worse trade than paying default effort.
            if "reasoning_effort" not in str(exc):
                raise
            raw = self._client.chat.completions.create(**kwargs)
        out = translate_response(raw, model=target)
        if out.stop_reason == "max_tokens" and not out.content[0].text.strip():
            # Empty-because-truncated is the failure this adapter is most likely to hit, and the
            # least legible: every caller feeds .text to a JSON parser, so it surfaces as "the
            # model returned malformed JSON" three layers away from the budget that caused it.
            raise RuntimeError(
                f"{target} spent its entire {budget}-token budget on reasoning and returned no "
                f"text (call site asked for {int(max_tokens)}). Raise "
                f"OPENAI_SCRIPT_REASONING_HEADROOM or lower OPENAI_SCRIPT_REASONING_EFFORT.")
        return out


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
