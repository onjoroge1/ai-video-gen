"""Spend recorded when the provider answers, not when the attempt succeeds.

Every cost figure in this pipeline was previously published at the end of the function that spent
it -- `_generate_script_chunked` accumulates a local `cost` and sets `_script_cost_usd` in its
return dict. So an attempt that raises reports nothing. Measured on four Hanoi beat-sheet runs
that each bought a planner call and a set of entailment judgements: `recorded cost=$0.0000`, four
times. The spend was real and the ledger was empty, because the ledger only existed on the
success path.

That is tolerable while failures are rare and cheap. It stops being tolerable the moment the plan
is to run five sampled attempts per architectural change: a change that improves stability by
tripling planning spend and a change that improves it for free look identical in the report.

A ledger is a list of charges, appended as each provider result comes back. It is deliberately
list-compatible -- `append` and iteration behave as they do for the plain `list` that every
`cost_sink` parameter in the pipeline accepts today -- so it can be passed anywhere a sink is
taken. Untagged appends land under "unattributed" rather than being refused; a partial attribution
is still worth more than a zero.

Charging is opt-in per call site (see `explainer_pipeline._charge`) precisely BECAUSE it is
list-compatible: a function that both appends to its sink and returns its own total would be
double-counted by the several callers that add `_script_cost_usd` to `sum(cost_sink)`.
"""
from __future__ import annotations

import json
import os
import tempfile

# Named here rather than as string literals at each call site, so a stage cannot quietly split in
# two under a typo and report half its spend.
RESEARCH = "research"
ENGINE_SELECT = "engine_select"
BEAT_SHEET = "beat_sheet"
CAUSAL_SPINE = "causal_spine"
BOUNDARY_A = "boundary_a_evidence"
BOUNDARY_B = "boundary_b_fidelity"
EXPANSION = "expansion"
GRADE = "grade"
FACTCHECK = "factcheck"
RUNTIME_REFIT = "runtime_refit"
HOOK_REPAIR = "hook_repair"
UNATTRIBUTED = "unattributed"

# The stages whose spend `explainer_pipeline` also reports in `script["_script_cost_usd"]`. A
# caller holding both must add only what is NOT in here, or the script is paid for twice. Note
# what is absent: an untagged append is by definition not attributable to script generation, so
# UNATTRIBUTED is additive -- treating it as already-counted silently erases real spend.
SCRIPT_STAGES = (ENGINE_SELECT, BEAT_SHEET, CAUSAL_SPINE, BOUNDARY_A, BOUNDARY_B, EXPANSION)


class StageCostSink(list):
    """Collect a call's usage and immediately persist each response in the attempt ledger.

    The returned subtotal is for the script's own accounting. Plain legacy list sinks are not
    forwarded to, because their callers add that subtotal separately.
    """

    def __init__(self, ledger=None, stage=BOUNDARY_A):
        super().__init__()
        self.ledger = ledger if isinstance(ledger, CostLedger) else None
        self.stage = stage

    def append(self, amount):
        amount = float(amount or 0)
        super().append(amount)
        if self.ledger is not None:
            self.ledger.charge(self.stage, amount)


class CostLedger:
    """A list of charges that can stand in for a `cost_sink` list.

    `path`, when given, is rewritten after every charge. An attempt killed mid-run -- which is how
    the expensive ones tend to end -- still leaves its spend on disk.
    """

    def __init__(self, path: str | None = None):
        self.entries: list[dict] = []
        self.path = path

    def charge(self, stage: str, amount, detail: str = "") -> float:
        amount = round(float(amount or 0.0), 6)
        if amount:
            self.entries.append({"stage": stage or UNATTRIBUTED, "usd": amount,
                                 "detail": str(detail)[:200]})
            self._flush()
        return amount

    # --- list compatibility, so any cost_sink parameter accepts this -------------------------
    def append(self, amount) -> None:
        self.charge(UNATTRIBUTED, amount)

    def __iter__(self):
        return iter(entry["usd"] for entry in self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def __bool__(self) -> bool:
        return True          # a ledger is a sink even before anything is charged to it

    # --- reporting ----------------------------------------------------------------------------
    def total(self) -> float:
        return round(sum(entry["usd"] for entry in self.entries), 6)

    def by_stage(self) -> dict:
        out: dict[str, float] = {}
        for entry in self.entries:
            out[entry["stage"]] = round(out.get(entry["stage"], 0.0) + entry["usd"], 6)
        return out

    def script_stage_total(self) -> float:
        """What this ledger already holds of `_script_cost_usd`, so a caller can add the rest."""
        return round(sum(usd for stage, usd in self.by_stage().items()
                         if stage in SCRIPT_STAGES), 6)

    def report(self) -> dict:
        return {"total_usd": self.total(), "by_stage": self.by_stage(),
                "charges": len(self.entries),
                "basis": "pipeline usage estimates recorded per provider result; "
                         "not a provider billing ledger"}

    def table(self) -> str:
        rows = self.by_stage()
        if not rows:
            return "No spend recorded."
        width = max(len(stage) for stage in rows)
        lines = [f"  {stage:<{width}}  ${usd:>8.4f}"
                 for stage, usd in sorted(rows.items(), key=lambda kv: -kv[1])]
        lines.append(f"  {'-' * width}  {'-' * 9}")
        lines.append(f"  {'attempt total':<{width}}  ${self.total():>8.4f}")
        return "\n".join(lines)

    def _flush(self) -> None:
        if not self.path:
            return
        # Written whole through a temp file: a ledger truncated by a kill is worse than a stale one.
        directory = os.path.dirname(os.path.abspath(self.path)) or "."
        os.makedirs(directory, exist_ok=True)
        handle = tempfile.NamedTemporaryFile("w", dir=directory, delete=False, encoding="utf-8")
        try:
            json.dump({**self.report(), "entries": self.entries}, handle, indent=1)
            handle.close()
            os.replace(handle.name, self.path)
        except Exception:
            try:
                os.unlink(handle.name)
            except OSError:
                pass
            raise
