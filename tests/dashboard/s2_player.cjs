const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const app = fs.readFileSync('src/cuas/dashboard/static/app/app.js', 'utf8');
const nodes = new Map();
let loads = 0, plays = 0;
const $ = id => {
  if (!nodes.has(id)) nodes.set(id, {hidden:false, duration:10, currentTime:0, style:{},
    classList:{toggle(){}}, pause(){}, play(){plays++; return Promise.resolve();},
    removeAttribute(){}, addEventListener(){}, set src(v){loads++; this.source=v;}});
  return nodes.get(id);
};
const context = vm.createContext({$, state:{run:{scenario_id:'s2',run_id:'r1'},collapsed:false},
  setTimeout:fn=>fn(), selectedCard:()=>({track_id:'manual'}), assert});
const source = app.slice(app.indexOf('const FADE_S'), app.indexOf('// --- drawing ---'));
vm.runInContext(source, context);
context.clip = {type:'SAMPLE', caption:'Svanström', parts:[{url:'a',start:0},{url:'b',start:0,end:4},{url:'c',start:2,end:9}]};
vm.runInContext(`
showParts(clip,false);
player.front.currentTime=9.5; nextPart({target:player.front,type:'timeupdate'});
player.front.currentTime=3.5; nextPart({target:player.front,type:'timeupdate'});
player.front.currentTime=8.5; nextPart({target:player.front,type:'timeupdate'});
assert.equal(player.ended,false);
player.front.currentTime=9; nextPart({target:player.front,type:'timeupdate'});
assert.equal(player.ended,true); assert.equal($('sample-end').hidden,false);
`, context);
const before = [loads,plays];
vm.runInContext('showParts(clip,false); showParts(clip,false);',context);
assert.deepEqual([loads,plays],before);
assert.equal($('standin-tag').textContent,'SAMPLE');
assert.equal($('standin-note').textContent,'Svanström');
vm.runInContext('replaySample(); assert.equal(player.ended,false); assert.equal(player.i,0);',context);
assert.equal(loads,before[0]+1); assert.equal(plays,before[1]+1);
vm.runInContext(`state.run.run_id='r2'; showParts(clip,false); assert.equal(player.i,0);`,context);
const heardHelper = app.slice(app.indexOf('function heardTrackId()'),app.indexOf('function render()'));
vm.runInContext(heardHelper + `
state.videoTrack='auto'; state.selected=null; assert.equal(heardTrackId(),'auto');
state.selected='alert'; assert.equal(heardTrackId(),'manual');
`,context);
const map = fs.readFileSync('src/cuas/dashboard/static/app/map.js','utf8');
const drawn = [];
Object.assign(context,{MAP:{heardColour:'yellow'},drawZones(){},drawSensors(){},drawZoom(){},drawTrack(){},
  drawWedge:(ctx,view,w,heard)=>drawn.push([w.sensor_id,!!heard]),labelWedge(){},heardText:()=>'',
  site:{zones:[]},frame:{pre_alerts:[{sensor_id:'unconfirmed'}],tracks:[
    {track_id:'auto',status:'confirmed',heard:[{sensor_id:'st1.acoustic'}]},
    {track_id:'manual',status:'confirmed',heard:[{sensor_id:'st2.acoustic'}]}]}});
vm.runInContext(map.slice(map.indexOf('function drawSite('),map.indexOf('// Picket:')) ,context);
vm.runInContext(`drawSite({}, {}, site, frame, {sectors:true,heardTrack:'auto'}, {});`,context);
assert.deepEqual(drawn,[['unconfirmed',false],['st1.acoustic',true]]);
drawn.length=0;
vm.runInContext(`drawSite({}, {}, site, frame, {sectors:true,heardTrack:'manual'}, {});`,context);
assert.deepEqual(drawn,[['unconfirmed',false],['st2.acoustic',true]]);
drawn.length=0;
vm.runInContext(`drawSite({}, {}, site, frame, {sectors:false,heardTrack:'auto'}, {});`,context);
assert.deepEqual(drawn,[]);
console.log('S2 once/replay, update stability, source caption, auto/manual wedge and toggle passed');
