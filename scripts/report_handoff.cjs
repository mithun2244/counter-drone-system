// Contract replay through the production camera state machine; no browser rendering.
const fs = require('node:fs');
const vm = require('node:vm');
const app = fs.readFileSync('src/cuas/dashboard/static/app/app.js', 'utf8');
const helper = app.slice(app.indexOf('const handoff ='), app.indexOf('function renderZoomOnly()'));
for (const run of JSON.parse(fs.readFileSync('runs/handoff-live.json', 'utf8'))) {
  const ctx = vm.createContext({});
  vm.runInContext(fs.readFileSync('src/cuas/dashboard/static/app/simview.js', 'utf8') + helper, ctx);
  let last;
  const rows = [];
  for (const frame of run.frames) {
    const cue = frame.cues.find(c => c.track_id === 'trk-1') || frame.cues[0];
    if (!cue) continue;
    const zoom = cue.views.find(v => v.camera === 'zoom');
    ctx.view = zoom;
    ctx.rgb = cue.current_rgb_t != null;
    ctx.key = `${run.run_id}:${cue.cue_id}:${cue.track_id}`;
    const mode = vm.runInContext('cameraHandoff(key, Boolean(view && !simTargetOutside(view)), rgb)', ctx);
    if (mode !== last || (frame.t >= 83.6 && frame.t <= 86.4)) {
      rows.push({t: frame.t, track: cue.track_id, mode, rgb_t: cue.current_rgb_t});
    }
    last = mode;
  }
  console.log(JSON.stringify({speed: run.speed, run: run.run_id, wall_s: run.wall_s, rows}));
}
