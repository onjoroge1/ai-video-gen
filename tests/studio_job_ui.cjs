// Offline behavior checks: retries, event cursor, terminal artifacts, and safe text rendering.
const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = readFileSync('static/studio-job.js', 'utf8');
function element() { return {textContent:'', children:[], append(...v){this.children.push(...v)},replaceChildren(){this.children=[]}}; }
(async () => {
 const elements = new Map(), scheduled=[], urls=[];
 const responses=[new Error('offline'), {id:'job-1',status:'rendering',active:true,events:[{seq:1,data:'working'}]},
 {id:'job-1',status:'error',active:false,error:'gate failed',checkpoint_sha256:'new',events:[{seq:2,data:'blocked'}]},
 {checkpoint_sha256:'new',script:{title:'<script>unsafe</script>',scenes:[{narration:'saved words'}],_script_readiness:{passed:false}},reports:{claims:{passed:false}}}];
 const context={document:{getElementById(id){if(!elements.has(id)) elements.set(id,element());return elements.get(id)},createElement:element},
 location:{pathname:'/studio/jobs/job-1'},AbortController, console,
 setTimeout(fn,ms){if(ms!==20000) scheduled.push(fn);return 1},clearTimeout(){},
 async fetch(url,options){urls.push(url); assert.equal(options.cache,'no-store'); assert.equal(options.method,undefined);const data=responses.shift();if(data instanceof Error)throw data;return {ok:true,json:async()=>data}}};
 vm.runInNewContext(source,context);
 const settle=()=>new Promise(resolve=>setImmediate(resolve));
 await settle(); assert.match(elements.get('connection').textContent,/interrupted/);
 scheduled.shift()(); await settle(); assert.equal(elements.get('events').children.length,1);
 scheduled.shift()(); await settle();
 assert.equal(scheduled.length,0);assert.equal(urls.at(-2),'/api/studio/jobs/job-1?after=1');
 assert.equal(elements.get('status').textContent,'error');assert.match(elements.get('artifact-status').textContent,/approval not confirmed/);
 assert.equal(elements.get('script').children[0].textContent,'<script>unsafe</script>');
 assert.equal(elements.get('events').children.length,2);
 console.log('Studio UI retry, cursor, terminal artifacts and text rendering passed');
})().catch(error=>{console.error(error);process.exitCode=1});
