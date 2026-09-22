"""Use the existing Postgres leases/Blob credentials on a provisioned engine host.

python -m bolt_video.engines.worker --job-id engine-...  # once
python -m bolt_video.engines.worker --poll               # managed worker process
"""
import argparse
import json
import time
import uuid

from durable_execution import PostgresStore, BlobStore
from .jobs import JOB_KIND, PINS, run_claimed
from .runner import readiness


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id")
    parser.add_argument("--poll", action="store_true")
    args = parser.parse_args()
    # A generic worker must have all three runtimes before draining their shared
    # kind. A targeted one only needs the engine used by that exact request.
    store, blob = PostgresStore(), BlobStore()
    row = store.get_job(args.job_id) if args.job_id else None
    if args.job_id and (not row or row.get("kind") != JOB_KIND):
        parser.error("The requested engine job does not exist")
    engines = [row["request"]["request"]["engine"]] if row else PINS
    states = [readiness(engine) for engine in engines]
    if any(not s["ready_on_this_host"] for s in states):
        print(json.dumps({"ready": False, "engines": states}))
        return 1
    while True:
        job = store.claim(job_id=args.job_id, kind=JOB_KIND, worker_id="engine-" + uuid.uuid4().hex)
        if job:
            print(json.dumps(run_claimed(job, store, blob)), flush=True)
        if not args.poll:
            return 1 if job and store.get_job(job["id"])["status"] != "done" else 0
        time.sleep(10)


if __name__ == "__main__":
    raise SystemExit(main())
