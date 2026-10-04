"use strict";
const SAMPLE = {"schema_version":1,"status":"draft","title":"An incentive changes a choice — template demo","flow":"motion_scene","aspect_ratio":"16:9","narration_script":"A reward changes the choice. The result is different.","reference_ids":[],"claim_ids":[],"provenance":"reelforge","shots":[{"id":"setup","start":0,"end":4,"narration":"A reward changes the choice.","visual":"One token moves between two labeled choices.","first_frame":"A token sits beside option A.","change":"The reward appears beside option B; the token moves toward it.","last_frame":"The token sits beside option B.","treatment":"motion_canvas","reference_ids":[],"claim_ids":[]},{"id":"payoff","start":4,"end":8,"narration":"The result is different.","visual":"The consequence panel fills as tokens arrive.","first_frame":"The consequence panel is empty.","change":"The chosen token enters the panel.","last_frame":"The panel contains the token.","treatment":"motion_canvas","reference_ids":[],"claim_ids":[]}]};
let board = structuredClone(SAMPLE);
const $ = id => document.getElementById(id);
const status = (text, error=false) => {$("status").textContent=text;$("status").className=error?"error":"";};
function check(raw) {
  if (!raw || raw.schema_version!==1 || raw.status!=="draft" || !Array.isArray(raw.shots) || !raw.shots.length || raw.shots.length>180) throw Error("Use a version-1 draft with 1–180 shots.");
  if (!["storyboard","stock_short","motion_scene","repurpose"].includes(raw.flow)) throw Error("Unknown production method.");
  if (!["9:16","16:9","1:1"].includes(raw.aspect_ratio)) throw Error("Unknown aspect ratio.");
  const ids=new Set();let end=0;
  for (const shot of raw.shots) {
    if(typeof shot.id!=="string" || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$/.test(shot.id) || ids.has(shot.id)) throw Error("Every shot needs a unique valid ID.");
    ids.add(shot.id);
    if(!Number.isFinite(shot.start)||!Number.isFinite(shot.end)||shot.start<0||shot.end<=shot.start||shot.end>86400||Math.abs(shot.start-end)>.001) throw Error(`${shot.id}: timeline must start at zero with positive durations and no gaps or overlaps.`);
    for(const key of ["narration","visual","first_frame","change","last_frame"]) if(typeof shot[key]!=="string"||!shot[key].trim()||shot[key].length>8000) throw Error(`${shot.id}: complete ${key}.`);
    end=shot.end;
  }
  if(typeof raw.title!=="string"||!raw.title.trim()||raw.title.length>200) throw Error("Enter a title of 1–200 characters.");
  const norm=x=>x.trim().split(/\s+/).join(" ");
  if(typeof raw.narration_script!=="string"||norm(raw.narration_script)!==norm(raw.shots.map(s=>s.narration).join(" "))) throw Error("The narration script must match the shots in order.");
  if(raw.flow==="stock_short"&&raw.aspect_ratio!=="9:16") throw Error("Stock / Hybrid Short requires 9:16.");
  if(raw.flow==="repurpose") {
    const s=raw.source;
    if(!s||!s.finished_video_id||![s.start,s.end,s.duration].every(Number.isFinite)||s.start<0||s.end<=s.start||s.end>s.duration||Math.abs(end-(s.end-s.start))>.001) throw Error("Add a valid finished-video source span in Advanced JSON, matching the storyboard duration.");
    if(s.content_type==="illustrated"&&s.layout!=="general") throw Error("Illustrated sources require general framing.");
  } else if(raw.source) throw Error("Remove the source span when leaving the repurpose flow.");
  return raw;
}
function sync(){
  board.title=$("title").value;board.flow=$("flow").value;board.aspect_ratio=$("aspect").value;
  board.narration_script=board.shots.map(s=>s.narration).join(" ");
  $("json").value=JSON.stringify(board,null,2);
  $("flow-note").textContent=board.flow==="repurpose"?"Repurposing requires a stored source ID, reviewed span and layout in Advanced JSON. No footage is uploaded or processed here.":"Use reference IDs for recurring subjects and claim IDs for evidence. These are references, not proof that a claim was verified.";
  try{check(board);status("Browser checks passed. Export and run the Python validator before handoff.");}catch(e){status(e.message,true);}
}
function render(){
  $("title").value=board.title;$("flow").value=board.flow;$("aspect").value=board.aspect_ratio;$("shots").replaceChildren();
  board.shots.forEach((shot,index)=>{
    const article=document.createElement("article");article.className="shot";
    const header=document.createElement("header");const title=document.createElement("strong");title.textContent=`${index+1}. ${shot.id}`;header.append(title);
    const remove=document.createElement("button");remove.textContent="Remove shot";remove.type="button";remove.onclick=()=>{if(board.shots.length===1){status("Keep at least one shot.",true);return;}board.shots.splice(index,1);render();};header.append(remove);article.append(header);
    const time=document.createElement("div");time.className="timing";
    for(const key of ["start","end"]){const label=document.createElement("label");label.textContent=`${key} (seconds)`;const input=document.createElement("input");input.type="number";input.min="0";input.max="86400";input.step="0.1";input.value=shot[key];input.oninput=()=>{shot[key]=input.valueAsNumber;sync();};label.append(input);time.append(label);}article.append(time);
    const fields=document.createElement("div");fields.className="fields";
    for(const [key,name] of [["narration","Narration"],["visual","What the viewer sees"],["first_frame","Before"],["change","Visible change"],["last_frame","After"]]){const label=document.createElement("label");label.textContent=name;if(key==="narration"||key==="visual")label.className="wide";const input=document.createElement("textarea");input.maxLength=8000;input.value=shot[key]||"";input.oninput=()=>{shot[key]=input.value;sync();};label.append(input);fields.append(label);}article.append(fields);$("shots").append(article);
  });sync();
}
for(const id of ["title","flow","aspect"])$(id).addEventListener("input",sync);
$("demo").onclick=()=>{if(!confirm("Replace the current draft with the example?"))return;board=structuredClone(SAMPLE);render();};
$("add").onclick=()=>{if(board.shots.length>=180){status("Maximum 180 shots.",true);return;}const start=board.shots.at(-1).end;board.shots.push({id:`shot-${crypto.randomUUID().slice(0,8)}`,start,end:start+3,narration:"",visual:"",first_frame:"",change:"",last_frame:"",treatment:"illustrated",reference_ids:[],claim_ids:[]});render();};
function load(text){if(text.length>1048576)throw Error("Maximum JSON size is 1 MiB.");let raw=JSON.parse(text);if(raw.storyboard)raw=raw.storyboard;check(raw);board=raw;render();}
$("file").onchange=async event=>{try{const file=event.target.files[0];if(!file)return;if(file.size>1048576)throw Error("Maximum JSON size is 1 MiB.");if(!confirm("Replace the current draft with this file?"))return;load(await file.text());}catch(e){status(e.message,true);}finally{event.target.value="";}};
$("apply").onclick=()=>{try{load($("json").value);}catch(e){status(e.message,true);}};
$("export").onclick=()=>{try{sync();check(board);const url=URL.createObjectURL(new Blob([JSON.stringify(board,null,2)+"\n"],{type:"application/json"}));const a=document.createElement("a");a.href=url;a.download="storyboard.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){status(e.message,true);}};
fetch("/video-engine-catalog.json",{credentials:"same-origin"}).then(r=>{if(!r.ok)throw Error("Catalog unavailable");return r.json();}).then(data=>{for(const item of data.capabilities){const card=document.createElement("article");card.className="engine";for(const [tag,text] of [["span",item.kind.replaceAll("_"," ")],["h2",item.label],["p",item.best_for],["p","Native production: not enabled"]]){const el=document.createElement(tag);el.textContent=text;card.append(el);}$("engines").append(card);}}).catch(e=>status(e.message,true));
render();
