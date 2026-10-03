'use strict';
const jobId = decodeURIComponent(location.pathname.split('/').pop());
const base = '/api/studio/jobs/' + encodeURIComponent(jobId);
const el = id => document.getElementById(id);
let cursor = 0, artifactKey = null, lastSnapshot = null;
let pollTimer = null, resuming = false;
let savedArtifact = null, creatingRevision = false;
el('job').textContent = 'Job ' + jobId;
el('evidence').href = '/agent/research/' + encodeURIComponent(jobId);
async function get(url) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(url, {cache:'no-store', signal:controller.signal});
    if (!response.ok) throw new Error(response.status === 401 ? 'Sign in to Studio again, then reopen this job URL.' : `Request failed (${response.status}). Retry this page or load the saved script again.`);
    return await response.json();
  } finally { clearTimeout(timeout); }
}
function report(name, value) {
  const details = document.createElement('details');
  const heading = document.createElement('summary'); heading.textContent = name;
  const body = document.createElement('pre'); body.textContent = JSON.stringify(value, null, 2);
  details.append(heading, body); el('reports').append(details);
}
async function loadArtifacts() {
  el('load').disabled = true;
  try {
    const saved = await get(base + '/artifacts');
    savedArtifact = saved;
    el('script').replaceChildren(); el('reports').replaceChildren();
    const script = saved.script;
    const approved = lastSnapshot && lastSnapshot.status === 'awaiting_script_approval' && saved.approval_current === true;
    el('revision-actions').hidden = !(script && saved.content_sha256 && lastSnapshot && lastSnapshot.script_revision_eligible);
    el('render-action').hidden = !approved;
    el('artifact-status').textContent = (approved ? 'Ready for editorial review.' : script ? 'Saved draft — final approval not confirmed.' : 'No assembled script in this checkpoint yet.') +
      ' Source: ' + (saved.script_source || 'not available') +
      ' Checkpoint: ' + (saved.checkpoint_sha256 || 'not saved') +
      ((saved.unavailable || []).length ? ' Unreadable artifacts: ' + saved.unavailable.join(', ') : '');
    if (script) {
      const title = document.createElement('h3'); title.textContent = script.title || 'Saved draft'; el('script').append(title);
      for (const [index, scene] of (script.scenes || []).entries()) {
        const heading = document.createElement('h3'); heading.textContent = `Scene ${index + 1} · ${scene.causal_role || ''}`;
        const narration = document.createElement('p'); narration.textContent = scene.narration || '';
        el('script').append(heading, narration);
      }
      for (const key of ['_script_readiness','_final_retention_review','_final_factcheck_review','_grade','_hook_contract','_claim_validation','_script_integrity','_retention_validation','_factcheck_review','_cadence_review','_edit_audit']) {
        if (script[key] != null) report(key, script[key]);
      }
    }
    for (const [key, value] of Object.entries(saved.reports || {})) report(key, value);
    artifactKey = saved.checkpoint_sha256;
  } catch (error) { el('artifact-status').textContent = 'Saved script unavailable: ' + error.message; }
  finally { el('load').disabled = false; }
}
el('load').onclick = loadArtifacts;
async function createRevision(mode) {
  if (creatingRevision || !savedArtifact || !lastSnapshot || !lastSnapshot.script_revision_eligible) return;
  const cap = Number(el(mode === 'evaluate' ? 'evaluation-cap' : 'render-cap').value);
  if (!Number.isFinite(cap) || cap <= 0 || cap > 10) {
    el('revision-status').textContent = 'Enter a cost cap above $0 and at most $10.'; return;
  }
  creatingRevision = true;
  el('evaluate-script').disabled = el('render-script').disabled = true;
  try {
    const response = await fetch(base + '/script-revisions', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({mode, cost_ceiling_usd:cap,
        checkpoint_sha256:savedArtifact.checkpoint_sha256, content_sha256:savedArtifact.content_sha256})
    });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : `Request failed (${response.status}). Refresh this job.`);
    el('revision-status').textContent = 'Job created. Opening its progress…';
    // Enqueue is idempotent for this exact scope. Dispatch continues that job only.
    fetch(result.dispatch_url, {method:'POST', keepalive:true}).catch(() => {});
    location.assign(result.studio_url);
  } catch (error) { el('revision-status').textContent = error.message; }
  finally { creatingRevision = false; el('evaluate-script').disabled = el('render-script').disabled = false; }
}
el('evaluate-script').onclick = () => createRevision('evaluate');
el('render-script').onclick = () => createRevision('render');
el('resume').onclick = async () => {
  if (resuming || !lastSnapshot || !(lastSnapshot.provider_resumable || lastSnapshot.planning_review_resumable)) return;
  resuming = true; el('resume').disabled = true; clearTimeout(pollTimer);
  let resumeError = '';
  try {
    const response = await fetch(base + (lastSnapshot.planning_review_resumable ? '/resume-planning-review' : '/resume-provider'), {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({checkpoint_sha256:lastSnapshot.checkpoint_sha256})
    });
    if (!response.ok) throw new Error(`Resume was not accepted (${response.status}). Refresh the saved job and check its status.`);
    await response.json();
    el('resume').hidden = true;
    el('connection').textContent = 'Resuming the same job using saved work and the existing cap.';
    // Dispatch is a long-running request; the saved job remains the status source.
    fetch('/api/explainer/dispatch/' + encodeURIComponent(jobId), {method:'POST'}).catch(() => {});
  } catch (error) {
    resumeError = error.message;
  } finally {
    resuming = false; el('resume').disabled = false;
    await poll();
    if (resumeError) el('error').textContent = resumeError;
  }
};
async function poll() {
  let delay = 3000;
  try {
    const data = await get(base + '?after=' + cursor); lastSnapshot = data;
    el('resume').hidden = !(data.provider_resumable || data.planning_review_resumable);
    el('resume').textContent = data.planning_review_resumable ? 'Resume saved research — retry claim review' : 'Provider access restored — resume this job';
    el('question').textContent = data.question;
    el('status').textContent = (data.status || 'Unknown').replaceAll('_', ' ');
    el('error').textContent = data.error || '';
    el('cost').textContent = `Recorded spend: $${Number(data.spent_cost_usd || 0).toFixed(2)} / job cap $${Number(data.max_cost_usd || 0).toFixed(2)}`;
    for (const event of data.events || []) {
      if (event.seq <= cursor) continue;
      const line = document.createElement('pre'); line.textContent = typeof event.data === 'string' ? event.data : JSON.stringify(event.data);
      el('events').append(line); cursor = event.seq;
    }
    const backlog = (data.events || []).length === 500;
    el('connection').textContent = data.active ? 'Connected. Refreshing this URL reconnects to the same job.' : 'Saved job status. Viewing this page never restarts generation.';
    if (!data.active && data.checkpoint_sha256 && artifactKey !== data.checkpoint_sha256) await loadArtifacts();
    if (!data.active && !backlog) return;
    if (backlog) delay = 0;
  } catch (error) { el('connection').textContent = 'Connection interrupted: ' + error.message + ' Retrying…'; delay = 5000; }
  pollTimer = setTimeout(poll, delay);
}
poll();
