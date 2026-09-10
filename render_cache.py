"""Resume illustrated FFmpeg work by content, independently of temporary paths."""
from functools import wraps, lru_cache
import inspect
import os
from pathlib import Path
import tempfile

from durable_execution import current, canonical_hash, file_sha256, CooperativeYield

# Pixel/timing contract from PR108. Storage-only changes must keep its existing
# stage identities. Bump this when encoding, overlays or timing change; hashing
# the entire pipeline made unrelated research/cleanup edits invalidate all video.
ILLUSTRATED_RENDER_VERSION = "5db0f3871aabd7f27795d8151f0ecec55cb009a42e43902e841df5f560bb1201"


@lru_cache(maxsize=8)
def _renderer_version(source):
    if Path(source).name == "explainer_pipeline.py":
        return ILLUSTRATED_RENDER_VERSION
    return file_sha256(source)


def _content_identity(value):
    if isinstance(value, dict):
        return {str(key): _content_identity(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_content_identity(item) for item in value]
    if isinstance(value, (str, os.PathLike)):
        path = os.fspath(value)
        if len(path) < 4096 and os.path.isfile(path):
            return {"file_sha256": file_sha256(path)}
    return value


def durable_render(function):
    """Reuse deterministic renders through the existing ledger with zero provider spend.

    Inner shot/concat calls are cached too, so a long scene or assembly can make progress
    across windows. Rendered media stays outside the control-state tarball.
    """
    signature = inspect.signature(function)

    @wraps(function)
    def render(*args, **kwargs):
        runtime = current()
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        output_name = "output_path" if "output_path" in bound.arguments else "out"
        output = os.path.abspath(bound.arguments[output_name])
        started = False

        def encode(_key=None):
            nonlocal started
            started = True
            # Only this invocation owns this directory. Nested renders commit their
            # durable objects before returning; captions, shot beds, concat audio
            # and partial outputs are removed on success, failure AND worker yield.
            # Inputs and the caller's finished output live outside this scope.
            with tempfile.TemporaryDirectory(prefix="render_", dir=os.path.dirname(output)) as work:
                scoped = signature.bind(*args, **kwargs)
                scoped.apply_defaults()
                scoped.arguments[output_name] = os.path.join(work, os.path.basename(output))
                if "tmp_dir" in scoped.arguments:
                    scoped.arguments["tmp_dir"] = work
                function(*scoped.args, **scoped.kwargs)
                os.replace(scoped.arguments[output_name], output)
            return {}, 0.0

        if not runtime or not runtime.cache_local_renders:
            encode()
            return
        values = dict(bound.arguments)
        values.pop(output_name)
        values.pop("tmp_dir", None)
        if "result" in values:
            # Per-scene logs, replay flags and QA timestamps do not change rendered pixels.
            values["result"] = {key: values["result"].get(key)
                                for key in ("img", "alt_img", "aud", "evidence_assets")}
        request = {"renderer": function.__name__,
                   "version": _renderer_version(inspect.getfile(function)),
                   "inputs": _content_identity(values)}
        key = "render:" + canonical_hash(request)[:32]

        try:
            runtime.paid_file(stage_key=key, provider="ffmpeg", request=request,
                              estimated_cost=0, output_path=output, operation=encode)
        except CooperativeYield:
            if started:
                # A nested render may yield after its parent stage was opened.
                # No provider outcome is ambiguous: resume these zero-cost parents
                # from their already committed children in the next worker.
                runtime.store.fail_stage(runtime.job_id, key, "Local render yielded", retryable=True)
            raise

    return render
