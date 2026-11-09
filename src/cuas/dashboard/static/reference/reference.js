// Reference page for the dashboard contract (docs/dashboard_contract.md). Plain JS, no libraries,
// nothing loaded from outside this server. It proves the stream works; it is not the dashboard.
"use strict";

const state = { profiles: [], run: null, frame: null, selected: null, basemap: null, cache: null };
const GRID_M = 500;
const ROAD_WIDTH = { motorway: 3, trunk: 2.5, primary: 2, secondary: 1.5, tertiary: 1 };
const SIMULATED = "Simulated scenario: fictional site";
const $ = (id) => document.getElementById(id);
const LEVEL_COLOUR = { red: "#ff5c5c", amber: "#ffb347", info: "#9aa" };
const esc = (text) => String(text).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

function connect() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${scheme}://${location.host}/ws`);
  socket.onmessage = (event) => receive(JSON.parse(event.data));
  socket.onclose = () => setTimeout(connect, 1000);
}

function receive(message) {
  if (message.type === "hello") {
    state.profiles = message.profiles;
    state.run = message.run;
    state.frame = message.frame;
    fillProfiles();
  } else if (message.type === "run") {
    state.run = message;
  } else if (message.type === "frame") {
    state.frame = message;
  }
  draw();
}

function fillProfiles() {
  $("profile").innerHTML = state.profiles
    .map((p) => `<option value="${esc(p.profile_id)}">${esc(p.venue)}</option>`).join("");
  fillScenarios();
}

function fillScenarios() {
  const profile = state.profiles.find((p) => p.profile_id === $("profile").value);
  $("scenario").innerHTML = (profile ? profile.scenarios : [])
    .map((s) => `<option value="${esc(s.scenario_id)}">${esc(s.scenario_id)}: ${esc(s.title)}</option>`).join("");
}

async function post(path, body) {
  const response = await fetch(path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const reply = await response.json();
  $("message").textContent = response.ok ? "" : reply.detail;
  return response.ok ? reply : null;
}

function startRun() {
  const body = {
    profile_id: $("profile").value,
    scenario_id: $("scenario").value,
    recorded_media: $("media").checked,
  };
  if ($("zoom").value !== "") body.zoom_per_station = Number($("zoom").value);
  post("/api/runs", body);
}

function draw() {
  const run = state.run;
  const frame = state.frame;
  $("run-title").textContent = run ? `${run.title} · ${run.venue} · ${run.state} · ${run.speed}x` : "idle";
  $("clock").textContent = frame ? `t = ${frame.t.toFixed(1)} s` : "";
  drawMap(run, frame);
  drawQueue(frame);
  drawStatus(frame);
}

function toScreen(site, canvas) {
  const b = site.bounds;
  const scale = Math.min(canvas.width / (b.max_x - b.min_x), canvas.height / (b.max_y - b.min_y));
  const left = (canvas.width - (b.max_x - b.min_x) * scale) / 2;  // centred
  const bottom = (canvas.height - (b.max_y - b.min_y) * scale) / 2;
  return {
    scale,
    at: (x, y) => [left + (x - b.min_x) * scale, canvas.height - bottom - (y - b.min_y) * scale],
  };
}

async function loadBasemap() {
  const response = await fetch("/api/basemap");  // 404: no basemap on this machine
  state.basemap = response.ok ? await response.json() : null;
  draw();
}

// One transform for everything: the basemap is already in site metres (docs/mapping.md).
function drawBackground(ctx, view, canvas, site) {
  if (!state.basemap) {
    drawGrid(ctx, view, site.bounds);
    return;
  }
  const key = `${canvas.width}x${canvas.height}`;
  if (!state.cache || state.cache.key !== key) {  // draw the map once, then copy it
    const layer = document.createElement("canvas");
    layer.width = canvas.width; layer.height = canvas.height;
    paintBasemap(layer.getContext("2d"), view, state.basemap);
    state.cache = { key, layer };
  }
  ctx.drawImage(state.cache.layer, 0, 0);
}

function path(ctx, view, line) {
  line.forEach(([x, y], i) => (i ? ctx.lineTo(...view.at(x, y)) : ctx.moveTo(...view.at(x, y))));
}

function fillAreas(ctx, view, areas, colour) {
  ctx.fillStyle = colour;
  for (const area of areas) {
    ctx.beginPath();
    for (const ring of area.rings) { path(ctx, view, ring); ctx.closePath(); }
    ctx.fill("evenodd");  // later rings are holes: islands in the sea
  }
}

function strokeLines(ctx, view, lines, colour, width) {
  ctx.strokeStyle = colour; ctx.lineWidth = width;
  for (const line of lines) { ctx.beginPath(); path(ctx, view, line); ctx.stroke(); }
}

function paintBasemap(ctx, view, map) {
  const b = map.bounds;
  const [x0, y0] = view.at(b.min_x, b.max_y);
  const [x1, y1] = view.at(b.max_x, b.min_y);
  ctx.fillStyle = "#2b3038"; ctx.fillRect(x0, y0, x1 - x0, y1 - y0);  // land
  fillAreas(ctx, view, map.sea, "#173149");
  fillAreas(ctx, view, map.water, "#1d3f5e");
  fillAreas(ctx, view, map.green, "#2f4535");
  ctx.setLineDash([4, 3]);
  strokeLines(ctx, view, map.rail, "#5a5f66", 1);
  ctx.setLineDash([]);
  for (const road of map.roads) strokeLines(ctx, view, [road.line], "#626873", ROAD_WIDTH[road.kind] || 1);
  strokeLines(ctx, view, map.coastline, "#4d7ea8", 1.5);
  ctx.lineWidth = 1;
}

function drawGrid(ctx, view, b) {
  ctx.strokeStyle = "#333a44"; ctx.lineWidth = 1;
  for (let x = Math.ceil(b.min_x / GRID_M) * GRID_M; x <= b.max_x; x += GRID_M) {
    ctx.beginPath(); path(ctx, view, [[x, b.min_y], [x, b.max_y]]); ctx.stroke();
  }
  for (let y = Math.ceil(b.min_y / GRID_M) * GRID_M; y <= b.max_y; y += GRID_M) {
    ctx.beginPath(); path(ctx, view, [[b.min_x, y], [b.max_x, y]]); ctx.stroke();
  }
}

function drawNotice(ctx, canvas) {  // always on: the map is real, the scenario is not
  const map = state.basemap;
  const notice = map ? map.notice : `${SIMULATED} · local grid ${GRID_M} m (no basemap)`;
  ctx.font = "bold 13px sans-serif";
  ctx.fillStyle = "rgba(0, 0, 0, 0.6)"; ctx.fillRect(8, 8, ctx.measureText(notice).width + 16, 24);
  ctx.fillStyle = "#ffd36b"; ctx.fillText(notice, 16, 25);
  ctx.font = "11px sans-serif";
  if (map) {
    const width = ctx.measureText(map.attribution).width;
    ctx.fillStyle = "rgba(0, 0, 0, 0.6)"; ctx.fillRect(canvas.width - width - 16, canvas.height - 20, width + 12, 16);
    ctx.fillStyle = "#ddd"; ctx.fillText(map.attribution, canvas.width - width - 10, canvas.height - 8);
  }
  ctx.font = "10px sans-serif";
}

function drawMap(run, frame) {
  const canvas = $("map");
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const site = run ? run.site : state.basemap;  // the basemap shares the site's bounds
  if (!site) { drawNotice(ctx, canvas); return; }
  const view = toScreen(site, canvas);
  drawBackground(ctx, view, canvas, site);
  if (!run) { drawNotice(ctx, canvas); return; }
  for (const zone of run.site.zones) {  // outermost first
    ctx.beginPath();
    path(ctx, view, zone.polygon);
    ctx.closePath();
    ctx.fillStyle = `rgba(80, 110, 160, ${0.08 + 0.2 * zone.weight})`;
    ctx.fill();
    const [lx, ly] = view.at(zone.polygon[0][0], zone.polygon[0][1]);
    ctx.fillStyle = "#cfd8e3";
    ctx.fillText(zone.label, lx + 4, ly - 4);
  }
  if (frame) for (const wedge of frame.pre_alerts) drawWedge(ctx, view, wedge);
  const heard = new Set(frame ? frame.pickets_heard.map((p) => p.picket_id) : []);
  for (const picket of run.site.pickets) {
    const [x, y] = view.at(picket.x, picket.y);
    ctx.fillStyle = heard.has(picket.picket_id) ? "#ffb347" : "#667";
    ctx.beginPath(); ctx.arc(x, y, heard.has(picket.picket_id) ? 6 : 3, 0, 2 * Math.PI); ctx.fill();
  }
  for (const station of run.site.stations) {
    const [x, y] = view.at(station.x, station.y);
    ctx.fillStyle = "#dde"; ctx.fillRect(x - 5, y - 5, 10, 10);
    ctx.fillText(station.station_id, x + 7, y + 4);
  }
  if (frame) for (const track of frame.tracks) drawTrack(ctx, view, track);
  drawScaleAndNorth(ctx, view, canvas);
  drawNotice(ctx, canvas);
}

function drawWedge(ctx, view, wedge) {
  const [x, y] = view.at(wedge.x, wedge.y);
  const reach = 2000 * view.scale;
  const toCanvas = (deg) => ((deg - 90) * Math.PI) / 180;  // azimuth clockwise from north
  ctx.fillStyle = "rgba(255, 179, 71, 0.18)";
  ctx.beginPath(); ctx.moveTo(x, y);
  ctx.arc(x, y, reach, toCanvas(wedge.bearing_deg - wedge.half_width_deg), toCanvas(wedge.bearing_deg + wedge.half_width_deg));
  ctx.closePath(); ctx.fill();
}

function drawTrack(ctx, view, track) {
  const colour = LEVEL_COLOUR[track.level] || "#888";
  ctx.strokeStyle = colour;
  ctx.beginPath();
  track.trail.forEach(([, x, y], i) => (i ? ctx.lineTo(...view.at(x, y)) : ctx.moveTo(...view.at(x, y))));
  ctx.stroke();
  const [x, y] = view.at(track.x, track.y);
  const [vx, vy] = view.at(track.x + 5 * track.vx, track.y + 5 * track.vy);
  ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(vx, vy); ctx.stroke();
  ctx.fillStyle = colour;
  ctx.beginPath(); ctx.arc(x, y, 4, 0, 2 * Math.PI); ctx.fill();
  ctx.fillText(`${track.track_id} ${track.level || track.status}`, x + 6, y - 6);  // never colour alone
}

function drawScaleAndNorth(ctx, view, canvas) {
  const metres = 1000;
  const length = metres * view.scale;
  ctx.strokeStyle = "#ddd"; ctx.fillStyle = "#ddd";
  ctx.beginPath(); ctx.moveTo(20, canvas.height - 20); ctx.lineTo(20 + length, canvas.height - 20); ctx.stroke();
  ctx.fillText(`${metres} m`, 20, canvas.height - 26);
  ctx.beginPath(); ctx.moveTo(canvas.width - 30, 50); ctx.lineTo(canvas.width - 30, 20); ctx.stroke();
  ctx.fillText("N", canvas.width - 34, 15);
}

function drawQueue(frame) {
  const items = frame ? frame.alerts : [];  // in the order sent: never re-sorted
  $("alerts").innerHTML = items.length ? items.map((a) => `
    <li class="${esc(a.level)}${a.alert_id === state.selected ? " selected" : ""}" data-alert="${esc(a.alert_id)}">
      <strong>${esc(a.level.toUpperCase())}</strong> ${esc(a.class_key)} ${(100 * a.confidence).toFixed(0)}%
      · TTI ${a.tti_s === null ? "none" : a.tti_s.toFixed(0) + " s"} · ${esc(a.zone_label || "")}
      <br>${esc(a.reasons.join(", "))}${a.label ? ` · labelled ${esc(a.label)}` : ""}
      · ${a.evidence_records} evidence records
      <br><button data-label="confirm">Confirm</button> <button data-label="dismiss">Dismiss</button>
      <button data-export>Export</button>
    </li>`).join("") : "<li>All clear</li>";
  if (frame) {
    for (const pre of frame.pre_alerts) {
      $("alerts").insertAdjacentHTML("beforeend", `<li class="amber">Engine heard, ${esc(pre.compass)}, unconfirmed (${esc(pre.sensor_id)})</li>`);
    }
  }
}

function drawStatus(frame) {
  if (!frame) { $("status").textContent = ""; return; }
  const faults = frame.sensors.filter((s) => !s.ok).map((s) => s.sensor_id);
  const coverage = frame.coverage ? `${frame.coverage.pct.toFixed(1)}%` : "not yet";
  $("status").innerHTML = `Coverage ${coverage}<br>Sensor faults: ${faults.length ? esc(faults.join(", ")) : "none"}<br>`
    + `Evidence head: ${frame.evidence_head ? frame.evidence_head.seq : "none"}`;
  $("banner").style.display = frame.coverage && frame.coverage.warning ? "block" : "none";
  $("banner").textContent = frame.coverage ? `Coverage ${frame.coverage.pct.toFixed(0)}%: reduced` : "";
}

async function act(button, alertId) {
  const path = `/api/alerts/${encodeURIComponent(alertId)}`;
  if (button.dataset.label) {
    const result = await post(`${path}/label`, { label: button.dataset.label });
    if (result) $("message").textContent = `${alertId} ${button.dataset.label}ed: record ${result.seq}`;
  } else {
    const result = await post(`${path}/export`, {});
    if (result) $("message").textContent = `${alertId} exported to ${result.path}`;
  }
}

function selectAlert(event) {
  const item = event.target.closest("li[data-alert]");
  if (!item || !state.frame || event.target.closest("button")) return;
  state.selected = item.dataset.alert;
  const card = state.frame.alerts.find((a) => a.alert_id === state.selected);
  const look = card && card.looks[0];
  if (look) {
    $("clip").src = look.clip_url;
    $("clip").currentTime = look.at_s;
    $("clip-note").textContent = `${look.source} at ${look.at_s.toFixed(1)} s`;
  } else {
    $("clip").removeAttribute("src");
    $("clip-note").textContent = "No recording for this alert.";
  }
  draw();
}

$("profile").addEventListener("change", fillScenarios);
$("go").addEventListener("click", startRun);
$("alerts").addEventListener("click", selectAlert);
$("alerts").addEventListener("pointerdown", (event) => {  // the queue is redrawn every frame
  const button = event.target.closest("button");
  const item = event.target.closest("li[data-alert]");
  if (button && item) act(button, item.dataset.alert);
});
document.querySelectorAll("[data-action]").forEach((b) =>
  b.addEventListener("click", () => post("/api/run/control", { action: b.dataset.action })));
document.querySelectorAll("[data-speed]").forEach((b) =>
  b.addEventListener("click", () => post("/api/run/control", { action: "speed", speed: Number(b.dataset.speed) })));
loadBasemap();
connect();
