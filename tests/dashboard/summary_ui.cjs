const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const app = fs.readFileSync('src/cuas/dashboard/static/app/app.js','utf8');
const downloads = [];
const node = text => ({textContent:text,children:[],hidden:false,pause(){},click(){if(this.download)downloads.push({href:this.href,name:this.download});},
  append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;}});
const nodes = new Map();
const $ = id => {if(!nodes.has(id)) nodes.set(id,node(''));return nodes.get(id);};
const state = {run:{scenario_id:'s2',ended_reason:'completed'},summary:null};
let drawn;
const ctx = vm.createContext({state,$,el:(tag,cls,text)=>node(text),clock:String,
  scenarioTitle:()=> 'S2',pauseParts(){},stopAudio(){}, drawMap:(canvas,scene)=>{drawn=scene;},assert});
vm.runInContext(app.slice(app.indexOf('function renderRunSummary()'),app.indexOf('function render()')),ctx);
const texts = () => {const all=[]; const visit=n=>{if(n.textContent)all.push(n.textContent);n.children?.forEach(visit);};visit($('run-summary'));return all.join(' ');};
state.summary={run_id:'s2',elapsed_s:120,active_alerts:0,unique_alert_tracks:1,evidence_records:4,latest_detection:null};
vm.runInContext('renderRunSummary()',ctx);
assert.match(texts(),/Run complete/);assert.match(texts(),/No active alerts at end/);
assert.match(texts(),/No detections recorded/);assert.match(texts(),/Unique tracks that raised alerts: 1/);
assert.match(texts(),/Evidence records: 4/);assert.equal($('video-overlay').hidden,true);
assert.equal(drawn.frame,null);
state.run.ended_reason='stopped'; state.summary.latest_detection={t:90,sensor:'st1.rgb',track_id:'trk-1',position:{x:1,y:2,z:3,t:89}};
vm.runInContext('renderRunSummary()',ctx);
assert.match(texts(),/Run stopped/); assert.match(texts(),/Classification: Unavailable/);
assert.match(texts(),/89.*Historical/); assert.equal(drawn.historical.t,89);
state.summary.latest_detection={t:109.8,sensor:'st1.thermal',track_id:null};
state.summary.last_position={x:-65,y:135,z:121,t:113,track_id:'trk-6'};
vm.runInContext('renderRunSummary()',ctx);
assert.match(texts(),/association to latest detection unavailable/);assert.equal(drawn.historical.track_id,'trk-6');
console.log('Completed/stopped/no-detection summary rendering and historical pin passed');

// Exercise the production Blob/download action and the previously silent missing-API failure.
(async () => {
  let savedBlob;
  Object.assign(ctx, {Blob, URL:{createObjectURL:blob=>{savedBlob=blob;return 'blob:summary';}, revokeObjectURL(){}}, setTimeout:fn=>fn()});
  $('run-summary').children.find(n=>n.textContent==='Export run summary').onclick();
  assert.equal(downloads.length,1);
  assert.deepEqual(JSON.parse(await savedBlob.text()),state.summary);
  assert.equal(downloads[0].name, 's2-summary.json');
  let requested;
  state.run.run_id='run-1';state.summary=null;state.summaryRequest=null;
  Object.assign(ctx,{render(){},fetch:async url=>{requested=url;return {ok:false,status:404,text:async()=>'{"detail":"Not Found"}'};}});
  vm.runInContext(app.slice(app.indexOf('async function loadRunSummary()'),app.indexOf('function renderRunSummary()')),ctx);
  await vm.runInContext('loadRunSummary()',ctx);
  assert.equal(requested,'/api/run/summary?run_id=run-1');
  assert.match(state.summary.error,/HTTP 404/);assert.match(state.summary.error,/Restart the dashboard server/);
  vm.runInContext('renderRunSummary()',ctx);
  const retry=$('run-summary').children.find(n=>n.textContent==='Retry summary');assert.ok(retry);
  ctx.fetch=async()=>({ok:true,json:async()=>({run_id:'run-1',evidence_records:10})});
  retry.onclick();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(state.summary.evidence_records,10);
  console.log('Summary JSON download, run-scoped URL, actionable HTTP error and explicit retry passed');
  if (process.argv[2]) {
    const live = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
    state.run={run_id:live.run_id,scenario_id:live.scenario_id,ended_reason:live.ended_reason};
    state.summary=live;ctx.scenarioTitle=()=>live.scenario;
    vm.runInContext('renderRunSummary()',ctx);
    assert.match(texts(),new RegExp(`Evidence records: ${live.evidence_records}`));
    assert.match(texts(),new RegExp(`Unique tracks that raised alerts: ${live.unique_alert_tracks}`));
    assert.equal(drawn.historical,live.latest_detection?.position || live.last_position);
    $('run-summary').children.find(n=>n.textContent==='Export run summary').onclick();
    assert.deepEqual(JSON.parse(await savedBlob.text()),live);
    assert.equal(downloads.at(-1).name,`${live.run_id}-summary.json`);
    console.log(`Live response ${live.run_id}: production summary rendering, historical pin data and JSON download passed`);
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
