"""Resume illustrated FFmpeg work by content, independently of temporary paths."""
from functools import wraps, lru_cache
import inspect
import os

from durable_execution import current, canonical_hash, file_sha256


@lru_cache(maxsize=8)
def _renderer_version(source):
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
        if not runtime or not runtime.cache_local_renders:
            return function(*args, **kwargs)
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        values = dict(bound.arguments)
        output = values.pop("output_path", None) or values.pop("out")
        values.pop("tmp_dir", None)
        if "result" in values:
            # Per-scene logs, replay flags and QA timestamps do not change rendered pixels.
            values["result"] = {key: values["result"].get(key)
                                for key in ("img", "alt_img", "aud", "evidence_assets")}
        request = {"renderer": function.__name__,
                   "version": _renderer_version(inspect.getfile(function)),
                   "inputs": _content_identity(values)}
        key = "render:" + canonical_hash(request)[:32]

        def encode(_key):
            function(*args, **kwargs)
            return {}, 0.0

        runtime.paid_file(stage_key=key, provider="ffmpeg", request=request,
                          estimated_cost=0, output_path=output, operation=encode)

    return render
