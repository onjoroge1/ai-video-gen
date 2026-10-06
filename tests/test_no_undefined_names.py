"""No module reaches a name that does not exist in its scope.

The length top-up referenced a `script` local that the chunked writer does not have. Python
raises NameError only when the line runs, the top-up is wrapped in a broad except so length is
never worth a crash, and the result was a log line saying "top-up unavailable" while two lanes
wrote 438 and 473 words against a 700-word floor. The guard had silently disabled the fix it
was guarding, and nothing failed.

A pipeline this long cannot rely on a line being reached to find out whether its names exist.
"""
import builtins
import os
import symtable

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULES = [
    "explainer_pipeline.py", "backfire_packaging.py", "longform_research.py",
    "hook_patterns.py", "story_template.py", "illustrated_story.py",
    "claim_entailment.py", "story_compiler.py", "causal_story.py",
    "story_fact_model.py", "story_planner.py",
]
BUILTINS = set(dir(builtins))


def _undefined(path):
    with open(path) as handle:
        source = handle.read()
    top = symtable.symtable(source, path, "exec")
    module_globals = {s.get_name() for s in top.get_symbols()}
    found = []

    def walk(table, enclosing):
        # Only names the enclosing scopes BIND count as available. The first version carried
        # every symbol an enclosing table merely referenced, so a `log(...)` call inside a
        # function with no `log` parameter passed because other functions take one -- and the
        # NameError it raised at runtime was swallowed by a broad except for a full day.
        local = {s.get_name() for s in table.get_symbols()
                 if s.is_assigned() or s.is_parameter() or s.is_imported()}
        for sym in table.get_symbols():
            name = sym.get_name()
            if not sym.is_referenced():
                continue
            if (sym.is_parameter() or sym.is_assigned() or sym.is_imported()
                    or sym.is_global() or sym.is_free()
                    or name in module_globals or name in BUILTINS or name in enclosing):
                continue
            found.append(f"{table.get_name()}: {name}")
        for child in table.get_children():
            walk(child, enclosing | local)

    walk(top, set())
    return found


@pytest.mark.parametrize("module", MODULES)
def test_every_name_a_module_reads_exists_somewhere(module):
    path = os.path.join(ROOT, module)
    if not os.path.exists(path):
        pytest.skip(f"{module} is not in this checkout")
    missing = _undefined(path)
    assert not missing, f"{module} reads names that are never bound: {missing}"
