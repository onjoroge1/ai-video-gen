"""Wan 2.2 self-hosted i2v on Runpod -- the fallback when fal is out of funds.

Three separate builds have stalled mid-clip on `User is locked. Reason: Exhausted balance`.
This provider routes those jobs to the self-hosted pod instead of failing them. Policy is
FALLBACK, not default: fal (Kling V3 Pro) stays primary while funded; Wan takes over when fal
locks, at ~$0.10/clip of pod time instead of $0.35 -- but ~8.5 min/clip serial instead of
~2-3 min concurrent, so a fully-Wan batch of 7 runs about an hour.

WHAT THE STOCK WRAPPER DOES NOT DO, AND THIS DOES:
  * PORTRAIT. Both stock workflows are landscape (WanImageToVideo 1280x720; the final pass
    ImageScale to 1920x1080). Every sim short is 1080x1920. The dims are plain node inputs,
    so they are patched per job like the seed -- generation at 720x1280, final upscale to
    1080x1920.
  * NEGATIVES. The stock negative node carries Wan's standard Chinese quality negative; our
    scene negatives (the goat bans, camera locks) are APPENDED to it, not substituted -- the
    stock text is doing real work.
  * LIFECYCLE inside a build: the pod starts lazily on the first Wan job and generate()'s
    caller stops it in a finally block. An unstopped pod bills $0.74/hr for nothing, which
    is the one mistake this module must make impossible.

Clip length: 81 frames -> 5.06s draft (16fps), 5.03s final (RIFE x2, 32fps). Both within a
frame of Kling's 5.04s, so sim/render.py's ping-pong arithmetic is untouched.

Env (in .env): RUNPOD_API_KEY, RUNPOD_POD_ID (pod may migrate -- the id is config, not code),
optional WAN_WRAPPER_DIR for the workflow JSONs.
"""
from __future__ import annotations
import json
import os
import time
import urllib.request
import uuid

WRAPPER_DIR = os.environ.get("WAN_WRAPPER_DIR",
                             os.path.expanduser("~/Documents/Wan2.2/local_wrapper"))
POD_ID = os.environ.get("RUNPOD_POD_ID", "eyph723c5tuta1")
# Runpod's proxy 403s the default urllib agent -- any custom UA passes. Documented gotcha.
UA = {"User-Agent": "sim-engine/1.0"}


def available():
    """Fallback is configured: key present and the workflow files exist."""
    from hotd import load_env
    load_env()
    return bool(os.environ.get("RUNPOD_API_KEY")) and \
        os.path.exists(os.path.join(WRAPPER_DIR, "workflow_api.json"))


def _base():
    return f"https://{POD_ID}-8188.proxy.runpod.net"


def _req(url, data=None, headers=None, timeout=30):
    h = dict(UA)
    h.update(headers or {})
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        h["Content-Type"] = "application/json"
    r = urllib.request.urlopen(urllib.request.Request(url, data=body, headers=h),
                               timeout=timeout)
    return r.read()


def _runpod(verb):
    key = os.environ["RUNPOD_API_KEY"]
    return _req(f"https://rest.runpod.io/v1/pods/{POD_ID}/{verb}", data={},
                headers={"Authorization": f"Bearer {key}"})


_started_here = False
# The pod is one GPU running jobs serially; the caller is a 4-thread pool. Without these locks,
# every thread that hits a fal balance error races ensure_up ("starting pod" x4) and the pod gets
# four concurrent readiness probes and four queued jobs it will crawl through. One start, one job
# at a time -- the queue lives on our side where the locks are visible.
import threading
_up_lock = threading.Lock()
_job_lock = threading.Lock()


def ensure_up(progress=print, timeout_s=360):
    """Start the pod if it is not answering; remember whether WE started it. Single-flight."""
    global _started_here
    with _up_lock:
        return _ensure_up_locked(progress, timeout_s)


def _ensure_up_locked(progress, timeout_s):
    global _started_here
    try:
        _req(f"{_base()}/system_stats", timeout=10)
        return True
    except Exception:
        pass
    progress("  wan: starting pod (2-4 min)")
    try:
        _runpod("start")
        _started_here = True
    except Exception as e:
        # Read the body: Runpod's 500s carry the actual reason. The one that matters is the host
        # GPU being reclaimed while the pod was stopped -- the fix is the console's "Automatically
        # migrate" (new pod id -> update RUNPOD_POD_ID in .env), not a retry loop here.
        detail = ""
        if hasattr(e, "read"):
            try:
                detail = json.loads(e.read().decode()).get("error", "")
            except Exception:
                pass
        if "not enough free GPUs" in detail:
            progress("  wan: HOST GPU RECLAIMED -- use Runpod console 'Automatically migrate', "
                     "then update RUNPOD_POD_ID in .env")
        else:
            progress(f"  wan: pod start failed: {detail or str(e)[:120]}")
        return False
    return _wait_ready(progress, timeout_s)


# node classes every workflow needs; RIFE only exists in the finals graph but its presence
# proves the custom-node install finished, which is the actual thing being tested
_REQUIRED_NODES = ("WanImageToVideo", "CreateVideo", "RIFE VFI")


def _wait_ready(progress=print, timeout_s=900):
    """Ready means PROVISIONED AND STABLE, not merely answering.

    Runpod wipes the container disk on stop, so every start re-runs the template's init:
    /system_stats returns 200 as soon as base ComfyUI is up, minutes before custom nodes finish
    installing -- and the init restarts ComfyUI when it finishes, killing whatever job was
    submitted into the gap. That is exactly how a draft batch died six-for-six on a pod that had
    generated perfectly the day before (fresh CREATE runs init before the proxy goes live; a
    RESTART does not). So: require the workflow's node classes to exist in /object_info, then
    require the server to stay up for a further 60s -- long enough to be on the far side of the
    init's restart."""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            info = json.loads(_req(f"{_base()}/object_info", timeout=30))
            missing = [n for n in _REQUIRED_NODES if n not in info]
            if missing:
                progress(f"  wan: provisioning ({', '.join(missing)} not installed yet)")
                time.sleep(30)
                continue
        except Exception:
            time.sleep(15)
            continue
        stable_t = time.time()
        ok = True
        while time.time() - stable_t < 60:
            time.sleep(12)
            try:
                _req(f"{_base()}/system_stats", timeout=10)
            except Exception:
                ok = False
                break                      # init restarted the server; go back to waiting
        if ok:
            progress(f"  wan: ready ({time.time()-t0:.0f}s)")
            return True
    progress("  wan: pod did not become ready in time")
    return False


def shutdown(progress=print):
    """Stop the pod IF this process started it. Callers put this in a finally block."""
    global _started_here
    if _started_here:
        try:
            _runpod("stop")
            progress("  wan: pod stopped")
        except Exception as e:
            progress(f"  wan: POD STOP FAILED -- stop it in the console or pay $0.74/hr: {e}")
        _started_here = False
# The pod is one GPU running jobs serially; the caller is a 4-thread pool. Without these locks,
# every thread that hits a fal balance error races ensure_up ("starting pod" x4) and the pod gets
# four concurrent readiness probes and four queued jobs it will crawl through. One start, one job
# at a time -- the queue lives on our side where the locks are visible.
import threading
_up_lock = threading.Lock()
_job_lock = threading.Lock()


def _patch(wf, image_name, prompt, negative, seed, W, H, draft):
    """Patch the stock workflow: image, prompt, seed -- plus the parts the stock patcher
    skips: portrait dimensions and our appended negatives."""
    for node in wf.values():
        ct = node.get("class_type")
        ins = node.get("inputs", {})
        if ct == "LoadImage":
            ins["image"] = image_name
        elif ct == "CLIPTextEncode" and ins.get("text") == "PLACEHOLDER_POSITIVE_PROMPT":
            ins["text"] = prompt
        elif ct == "CLIPTextEncode" and "PLACEHOLDER" not in str(ins.get("text", "")):
            if negative:
                ins["text"] = str(ins.get("text", "")) + ", " + negative
        elif ct == "KSamplerAdvanced":
            ins["noise_seed"] = seed
        elif ct == "WanImageToVideo":
            # generate portrait natively; 720x1280 keeps the model's trained pixel budget
            ins["width"], ins["height"] = (W, H) if not draft else (W, H)
        elif ct == "ImageScale":
            # the final pass's 2x upscale target -- portrait, not the stock 1920x1080
            ins["width"], ins["height"] = (1080, 1920)
    return wf


def generate(image_path, prompt, out_mp4, negative="", draft=False, seed=None,
             progress=print, poll_timeout_s=1500):
    """One clip through the pod. Blocking; jobs queue serially server-side.
    Returns (ok, err). The caller owns ensure_up()/shutdown()."""
    import random
    try:
        with _job_lock:                      # serial pod, serial submissions
            return _generate_inner(image_path, prompt, out_mp4, negative, draft, seed,
                                   progress, poll_timeout_s)
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:140]}"


def _generate_inner(image_path, prompt, out_mp4, negative="", draft=False, seed=None,
                    progress=print, poll_timeout_s=1500):
    import random
    wf_file = "workflow_draft.json" if draft else "workflow_api.json"
    wf = json.loads(open(os.path.join(WRAPPER_DIR, wf_file)).read())

    # multipart upload without extra deps
    name = os.path.basename(image_path)
    boundary = uuid.uuid4().hex
    with open(image_path, "rb") as f:
        img = f.read()
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; "
            f"filename=\"{name}\"\r\nContent-Type: image/png\r\n\r\n").encode() + img + \
           (f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\n"
            f"true\r\n--{boundary}--\r\n").encode()
    up = urllib.request.Request(f"{_base()}/upload/image", data=body, headers={
        **UA, "Content-Type": f"multipart/form-data; boundary={boundary}"})
    stored = json.loads(urllib.request.urlopen(up, timeout=120).read()).get("name", name)

    wf = _patch(wf, stored, prompt, negative, seed or random.randint(0, 2 ** 48),
                720, 1280, draft)
    resp = json.loads(_req(f"{_base()}/prompt",
                           {"prompt": wf, "client_id": uuid.uuid4().hex}, timeout=60))
    pid = resp["prompt_id"]

    t0 = time.time()
    dead_polls = 0
    while time.time() - t0 < poll_timeout_s:
        time.sleep(15)
        try:
            hist = json.loads(_req(f"{_base()}/history/{pid}", timeout=30))
            dead_polls = 0
        except Exception:
            # A slow job still answers /history; a crashed ComfyUI answers nothing. Ten straight
            # dead polls (~2.5 min) is a crash, not patience -- and the first finals batch spent
            # 30 minutes politely waiting on a corpse before its next upload hit the 502.
            dead_polls += 1
            if dead_polls >= 10:
                return False, "comfyui stopped answering (crashed mid-job? check pod logs)"
            continue
        entry = hist.get(pid) or {}
        outs = entry.get("outputs") or {}
        vids = [v for o in outs.values() for v in (o.get("videos") or o.get("images") or [])
                if str(v.get("filename", "")).endswith(".mp4")]
        if vids:
            v = vids[0]
            data = _req(f"{_base()}/view?filename={urllib.parse.quote(v['filename'])}"
                        f"&subfolder={urllib.parse.quote(v.get('subfolder', ''))}&type=output",
                        timeout=300)
            open(out_mp4, "wb").write(data)
            return True, None
        if entry.get("status", {}).get("status_str") == "error":
            return False, f"comfyui error for {pid}"
    return False, f"wan timeout after {poll_timeout_s}s"


import urllib.parse  # noqa: E402  (used in generate)
