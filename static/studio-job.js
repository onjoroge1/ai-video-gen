'use strict';
const jobId = decodeURIComponent(location.pathname.split('/').pop());
const base = '/api/studio/jobs/' + encodeURIComponent(jobId);
const el = id => document.getElementById(id);
let cursor = 0, artifactKey = null, lastSnapshot = null;
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
    el('script').replaceChildren(); el('reports').replaceChildren();
    const script = saved.script;
    const ready = script && script._script_readiness;
    const approved = lastSnapshot && lastSnapshot.status === 'awaiting_script_approval' && ready && ready.passed;
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
      for (const key of ['_script_readiness','_grade','_claim_validation','_script_integrity','_retention_validation','_factcheck_review','_cadence_review']) {
        if (script[key] != null) report(key, script[key]);
      }
    }
    for (const [key, value] of Object.entries(saved.reports || {})) report(key, value);
    artifactKey = saved.checkpoint_sha256;
  } catch (error) { el('artifact-status').textContent = 'Saved script unavailable: ' + error.message; }
  finally { el('load').disabled = false; }
}
el('load').onclick = loadArtifacts;
async function poll() {
  let delay = 3000;
  try {
    const data = await get(base + '?after=' + cursor); lastSnapshot = data;
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
  setTimeout(poll, delay);
}
poll();
