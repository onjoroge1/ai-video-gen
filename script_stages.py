"""Job-local semantic results. Provider replay alone cannot freeze mutable evidence.

Records are content addressed and checkpointed before consumers run. Corruption is a
recovery error, never permission to silently buy another result. No cache outside a job.
"""
from copy import deepcopy
from functools import wraps
import hashlib
import inspect
import json
from pathlib import Path

VERSION = 1


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


class RecoveryError(ValueError):
    pass


def location(name, inputs):
    from durable_execution import current
    runtime = current()
    identity = {"version": VERSION, "stage": name, "inputs": inputs}
    key = digest(identity)
    return ((Path(runtime.output_dir) / "script_stages" / name / (key + ".json"))
            if runtime else None), runtime, key


def load(name, inputs):
    path, _, key = location(name, inputs)
    if path is None or not path.exists():
        return None
    try:
        record = json.loads(path.read_text())
        if (record["input_hash"] != key or record["stage"] != name
                or record["output_hash"] != digest(record["output"])):
            raise ValueError("identity mismatch")
        return deepcopy(record["output"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RecoveryError(f"Cannot restore completed script stage {name}") from exc


def save(name, inputs, output):
    path, runtime, key = location(name, inputs)
    if path is None:
        return
    record = {"version": VERSION, "stage": name, "input_hash": key,
              "output_hash": digest(output), "output": output}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False, allow_nan=False))
    temporary.replace(path)
    runtime.checkpoint("script-stage-" + name)


def cached(name, context=lambda: {}, cache_if=lambda result: True):
    """Save only completed calls; interrupted calls replay their durable provider stages."""
    def decorate(fn):
        signature = inspect.signature(fn)
        @wraps(fn)
        def wrapped(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            inputs = {k: v for k, v in bound.arguments.items() if k not in {"cost_sink", "log"}}
            inputs = {"arguments": deepcopy(inputs), "context": context()}
            saved = load(name, inputs)
            if saved is not None:
                return deepcopy(saved["result"])
            result = fn(*args, **kwargs)
            if cache_if(result):
                save(name, inputs, {"result": result})
            return result
        return wrapped
    return decorate
