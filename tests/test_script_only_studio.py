from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_studio_sends_script_only_and_handles_the_approval_stop():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

    assert 'id="expl-script-only"' in html
    assert "stop_after_script: document.getElementById('expl-script-only').checked" in html
    assert "ev.type === 'script_approval_required'" in html
    assert "await showExplainerScript(job_id, true)" in html
    assert "Voice, images, motion, and rendering were not started." in html


def test_script_only_is_a_terminal_durable_status_not_a_retry():
    source = (ROOT / "app.py").read_text(encoding="utf-8")

    assert '"awaiting-script-approval" if awaiting_script' in source
    assert '"awaiting_script_approval" if awaiting_script' in source
    assert '"script_approval_required" if awaiting_script' in source
    assert source.count('"awaiting_script_approval",') >= 2


def test_script_is_checkpointed_before_the_intentional_stop():
    source = (ROOT / "explainer_pipeline.py").read_text(encoding="utf-8")
    stop = source.index("if stop_after_script:")
    raised = source.index("raise ScriptApprovalRequired", stop)
    block = source[stop:raised]

    assert '_save_script_checkpoint(' in block
    assert 'label="script-awaiting-approval"' in block
