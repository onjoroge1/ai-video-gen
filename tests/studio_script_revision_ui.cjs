// Spending begins only with an explicit action bound to the displayed artifact and cap.
const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
function element() { return {textContent:'',value:'3',children:[],append(...v){this.children.push(...v)},replaceChildren(){this.children=[]}}; }
(async () => {
  const elements = new Map(), requests = [], redirects = [];
  const context = {
    document:{getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id)},createElement:element},
    location:{pathname:'/studio/jobs/parent',assign:url=>redirects.push(url)},
    AbortController, setTimeout:()=>1, clearTimeout:()=>{}, console,
    async fetch(url, options) {
      requests.push({url, options});
      if (url.endsWith('?after=0')) return {ok:true,json:async()=>({status:'awaiting_script_approval',active:false,
        checkpoint_sha256:'checkpoint',script_revision_eligible:true,events:[]})};
      if (url.endsWith('/artifacts')) return {ok:true,json:async()=>({checkpoint_sha256:'checkpoint',content_sha256:'words',approval_current:true,
        script:{title:'Saved title',scenes:[{narration:'Approved words.'}],_script_readiness:{passed:true}},reports:{}})};
      if (url.endsWith('/script-revisions')) return {ok:true,json:async()=>({studio_url:'/studio/jobs/child',dispatch_url:'/dispatch/child'})};
      return {ok:true};
    }
  };
  vm.runInNewContext(readFileSync('static/studio-job.js','utf8'),context);
  const settle=()=>new Promise(resolve=>setImmediate(resolve));
  await settle();
  assert.equal(requests.length,2); // reading the page never starts a job
  assert.equal(elements.get('revision-actions').hidden,false);
  assert.equal(elements.get('render-action').hidden,false);
  context.document.getElementById('evaluation-cap').value='0';
  await elements.get('evaluate-script').onclick();
  assert.equal(requests.length,2);
  elements.get('evaluation-cap').value='2.50';
  const first=elements.get('evaluate-script').onclick();
  const duplicate=elements.get('evaluate-script').onclick();
  await Promise.all([first,duplicate]);
  const posted=requests.filter(r=>r.url.endsWith('/script-revisions'));
  assert.equal(posted.length,1);
  assert.deepEqual(JSON.parse(posted[0].options.body),{mode:'evaluate',cost_ceiling_usd:2.5,checkpoint_sha256:'checkpoint',content_sha256:'words'});
  assert.deepEqual(redirects,['/studio/jobs/child']);
  assert.equal(requests.at(-1).url,'/dispatch/child');
  context.document.getElementById('redraft-cap').value='5';
  await elements.get('redraft-script').onclick();
  const redraft=requests.filter(r=>r.url.endsWith('/script-revisions')).at(-1);
  assert.deepEqual(JSON.parse(redraft.options.body),{mode:'redraft',cost_ceiling_usd:5,checkpoint_sha256:'checkpoint',content_sha256:'words'});
  console.log('Studio revision action, cap, artifact binding and duplicate-click checks passed');
})().catch(error=>{console.error(error);process.exitCode=1});
