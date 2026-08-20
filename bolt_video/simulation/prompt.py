from .compiler import compile_simulation
from bolt_video.prompts.builder import PromptBuilder, PromptPriority


def build_simulation_prompt_block(title: str, mascot_name: str = "Bolt") -> str:
    spec = compile_simulation(title)
    rule = spec.rule
    rows = []
    for cp in spec.checkpoints:
        sign = "+" if cp.delta >= 0 else ""
        delta = format(cp.delta, "f")
        if "." in delta:
            delta = delta.rstrip("0").rstrip(".")
        rows.append(
            f"- {cp.label}: delta {sign}{delta} {rule.canonical_unit}; "
            f"TOTAL STATE = {cp.display}"
        )
    warnings = "\n".join(f"- {w}" for w in spec.warnings) or "- No special floor warning."
    return "\n" + (PromptBuilder("Write a simulation short from a code-compiled rule.")
        .add("Safety", "Use conservative, well-established science. Omit unsupported consequences; "
             "arithmetic correctness does not make a physical consequence authoritative.", PromptPriority.SAFETY)
        .add("Output contract", f"Every narration number and {mascot_name} image scale must match the "
             "TOTAL STATE. Never add a numeric checkpoint outside this contract.", PromptPriority.OUTPUT_CONTRACT)
        .add("Deterministic facts", "These figures were computed in code. Use them in order. Never "
             "recalculate, interpolate, or replace TOTAL STATE with delta.\n"
             f"Baseline: {rule.baseline} {rule.canonical_unit}. Direction: {rule.direction.value}.\n"
             + "\n".join(rows) + "\nScientific boundaries:\n" + warnings, PromptPriority.FACTS)
        .render())
