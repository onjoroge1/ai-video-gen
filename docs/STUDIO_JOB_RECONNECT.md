# Reconnect to a saved Studio job

Open `/studio/jobs/<job_id>` while signed in, or enter the ID in Explainer's
**Open saved job** form. Existing jobs, including `dec618fc`, use the same view.
New explainer submissions replace the address bar with this stable URL and show
a persistent-view link. Refreshing the URL reads the same job; it never submits,
dispatches, resumes, approves, or purchases another generation.

The page polls durable status and incremental events using short GET requests.
Transient request failures retry; terminal status stops polling after the event
backlog is drained. Spend and job cap come from the durable record. Provider
billing reconciliation remains distinct from the displayed job accounting.

**Load latest saved script** restores the current checkpoint into an isolated,
temporary read workspace. It bypasses the older process-local materialization
cache and deletes the temporary workspace after reading. The snapshot hash is
shown alongside narration and saved gate reports. Missing or unreadable artifacts
are not passes. “Ready for editorial review” requires both the durable
`awaiting_script_approval` status and a passing saved readiness report.

The job page and both API routes use the existing private Studio authentication.
No raw checkpoint URLs or request configuration are included in the status response.
The saved diagnostics remain private and can contain provider-derived script text.

Validation: `python3 -m pytest -q tests/test_studio_jobs.py
 tests/test_script_only_studio.py tests/test_private_access.py` and
`node tests/studio_job_ui.cjs`. The JavaScript harness exercises reconnect after a
network error, event cursor continuation, terminal status, failed gate display and
text-only rendering without provider calls. A deployed browser check is still needed.
