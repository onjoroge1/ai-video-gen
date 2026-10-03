const {readFileSync}=require('node:fs');
const vm=require('node:vm'), assert=require('node:assert/strict');
const source=readFileSync('static/studio-job.js','utf8');
const element=()=>({textContent:'',children:[],append(...v){this.children.push(...v)},replaceChildren(){this.children=[]}});
(async()=>{
 const elements=new Map(), calls=[], timers=[];
 const blocked={status:'provider_blocked',active:false,provider_resumable:true,
   checkpoint_sha256:'a'.repeat(64),events:[]};
 const replies=[blocked,{checkpoint_sha256:blocked.checkpoint_sha256,script:null},
   {job_id:'job-1',resuming:true},{status:'processing',active:true,provider_resumable:false,events:[]}];
 const context={document:{getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id)},createElement:element},
  location:{pathname:'/studio/jobs/job-1'},AbortController,console,
  setTimeout(fn,ms){if(ms!==20000)timers.push(fn);return 1},clearTimeout(){},
  async fetch(url,opts){calls.push({url,opts});
    if(url==='/api/explainer/dispatch/job-1')return {ok:true,json:async()=>({})};
    return {ok:true,json:async()=>replies.shift()};}};
 vm.runInNewContext(source,context);
 await new Promise(r=>setImmediate(r));
 assert.equal(elements.get('resume').hidden,false);
 assert.equal(calls.filter(c=>c.opts.method==='POST').length,0,'viewing cannot resume');
 await Promise.all([elements.get('resume').onclick(),elements.get('resume').onclick()]);
 const posts=calls.filter(c=>c.opts.method==='POST');
 assert.equal(posts.length,2,'one resume plus one dispatch despite double click');
 assert.equal(posts[0].url,'/api/studio/jobs/job-1/resume-provider');
 assert.deepEqual(JSON.parse(posts[0].opts.body),{checkpoint_sha256:'a'.repeat(64)});
 assert.equal(elements.get('resume').hidden,true);
 assert.equal(elements.get('status').textContent,'processing');
 assert.equal(timers.length,1,'processing schedules the next poll');
 console.log('Studio explicit resume, double-click guard, checkpoint binding and processing polling passed');
})().catch(e=>{console.error(e);process.exitCode=1});
