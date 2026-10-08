"""Per-call provider spend, appended to the job directory, summed across every launch.

Before this, the only spend record was `run_result.json["actual_cost"]`, which summed the cost
sinks of the LAST launch: V13 (2026-10-08) took eight launches and reported $11.64, and nobody
could say where the Anthropic credit went. Every Anthropic message, image generation and TTS call
now appends one JSON line to `<job>/usage_ledger.jsonl` with the model, the caller, the token
counts and the dollar figure at that model's rate, so a job's spend is a sum, not an estimate.

Writing never raises: accounting must not fail the render it is accounting for.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import defaultdict

LEDGER_FILENAME = "usage_ledger.jsonl"

# USD per million tokens (input, output). Cache writes bill at 1.25x input, cache reads at 0.1x.
# Anthropic first-party rates as of 2026-10-06; unknown models fall back to the Opus 4.8 rate so
# an unpriced model is over- rather than under-counted.
ANTHROPIC_RATES = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4-5": (1.0, 5.0),
}
_FALLBACK_RATE = ANTHROPIC_RATES["claude-opus-4-8"]
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10

_state = {"path": "", "launch": ""}
_lock = threading.Lock()


def set_job_dir(output_dir: str) -> None:
    """Point the ledger at a job directory and start a new launch id."""
    _state["path"] = os.path.join(output_dir, LEDGER_FILENAME) if output_dir else ""
    _state["launch"] = time.strftime("%Y%m%dT%H%M%S")


def current_path() -> str:
    return _state["path"]


def anthropic_cost(model: str, usage) -> float:
    """USD for one Anthropic message at its own model's rate, cache tokens included."""
    rate_in, rate_out = ANTHROPIC_RATES.get(str(model or ""), _FALLBACK_RATE)
    get = (usage.get if isinstance(usage, dict) else lambda k, d=0: getattr(usage, k, d))
    tokens_in = get("input_tokens", 0) or 0
    tokens_out = get("output_tokens", 0) or 0
    cache_write = get("cache_creation_input_tokens", 0) or 0
    cache_read = get("cache_read_input_tokens", 0) or 0
    return (tokens_in * rate_in + cache_write * rate_in * CACHE_WRITE_MULTIPLIER
            + cache_read * rate_in * CACHE_READ_MULTIPLIER + tokens_out * rate_out) / 1_000_000


def record(provider: str, kind: str, cost_usd: float, *, model: str = "", caller: str = "",
           usage=None, extra: dict | None = None) -> None:
    """Append one line. Silently does nothing without a job directory."""
    path = _state["path"]
    if not path:
        return
    get = ((usage.get if isinstance(usage, dict) else (lambda k, d=0: getattr(usage, k, d)))
           if usage is not None else (lambda k, d=0: d))
    row = {
        "t": round(time.time(), 3), "launch": _state["launch"], "provider": provider,
        "kind": kind, "model": model, "caller": caller,
        "input_tokens": get("input_tokens", 0) or 0,
        "output_tokens": get("output_tokens", 0) or 0,
        "cache_write_tokens": get("cache_creation_input_tokens", 0) or 0,
        "cache_read_tokens": get("cache_read_input_tokens", 0) or 0,
        "cost_usd": round(float(cost_usd or 0.0), 6),
    }
    if extra:
        row.update(extra)
    try:
        with _lock, open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:          # noqa: BLE001 - accounting never fails the render
        pass


def caller_name(depth: int = 2) -> str:
    """The function that made the provider call, skipping this module and the wrapper."""
    try:
        frame = sys._getframe(depth)
        for _ in range(4):
            if frame is None:
                break
            name = frame.f_code.co_name
            module = frame.f_globals.get("__name__", "")
            if module not in (__name__,) and name not in ("create", "_metered_create", "<lambda>"):
                return f"{module}.{name}"
            frame = frame.f_back
    except Exception:          # noqa: BLE001
        pass
    return ""


# Marks where a user message's cacheable prefix ends (two INVISIBLE SEPARATOR characters). Only
# the real Anthropic client acts on it; see split_cache_marker.
CACHE_SPLIT = "⁣⁣"


def split_cache_marker(kwargs: dict) -> dict:
    """Turn a string user message containing CACHE_SPLIT into [prefix block with cache_control,
    rest block]. Messages without the marker are returned unchanged."""
    messages = kwargs.get("messages")
    if not isinstance(messages, list):
        return kwargs
    changed = []
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str) and CACHE_SPLIT in content:
            prefix, rest = content.split(CACHE_SPLIT, 1)
            blocks = [{"type": "text", "text": prefix, "cache_control": {"type": "ephemeral"}}]
            if rest:
                blocks.append({"type": "text", "text": rest})
            changed.append({**message, "content": blocks})
        else:
            changed.append(message)
    return {**kwargs, "messages": changed}


class MeteredMessages:
    """Wraps a client's `.messages` so every `.create` is recorded. Everything else passes through."""

    def __init__(self, inner):
        self._inner = inner

    def create(self, *args, **kwargs):
        kwargs = split_cache_marker(kwargs)
        response = self._inner.create(*args, **kwargs)
        try:
            model = str(kwargs.get("model") or getattr(response, "model", "") or "")
            usage = getattr(response, "usage", None)
            record("anthropic", "message", anthropic_cost(model, usage) if usage is not None else 0.0,
                   model=model, caller=caller_name(2), usage=usage)
        except Exception:      # noqa: BLE001
            pass
        return response

    def __getattr__(self, name):
        return getattr(self._inner, name)


def meter(client):
    """Return the client with `.messages.create` recorded. Never raises."""
    try:
        client.messages = MeteredMessages(client.messages)
    except Exception:          # noqa: BLE001
        pass
    return client


def read(path: str) -> list[dict]:
    rows = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
    except OSError:
        pass
    return rows


def summarize(path: str) -> dict:
    """Totals by provider, kind, model, caller and launch, across every launch of the job."""
    rows = read(path)
    out = {"total_usd": 0.0, "calls": len(rows), "by_provider": defaultdict(float),
           "by_kind": defaultdict(float), "by_model": defaultdict(float),
           "by_caller": defaultdict(float), "by_launch": defaultdict(float),
           "calls_by_caller": defaultdict(int), "cache_read_tokens": 0, "cache_write_tokens": 0}
    for row in rows:
        cost = float(row.get("cost_usd") or 0.0)
        out["total_usd"] += cost
        out["by_provider"][row.get("provider", "")] += cost
        out["by_kind"][row.get("kind", "")] += cost
        out["by_model"][row.get("model", "")] += cost
        out["by_caller"][row.get("caller", "")] += cost
        out["by_launch"][row.get("launch", "")] += cost
        out["calls_by_caller"][row.get("caller", "")] += 1
        out["cache_read_tokens"] += int(row.get("cache_read_tokens") or 0)
        out["cache_write_tokens"] += int(row.get("cache_write_tokens") or 0)
    for key in ("by_provider", "by_kind", "by_model", "by_caller", "by_launch"):
        out[key] = {k: round(v, 4) for k, v in sorted(out[key].items(), key=lambda kv: -kv[1])}
    out["calls_by_caller"] = dict(out["calls_by_caller"])
    out["total_usd"] = round(out["total_usd"], 4)
    return out
