// Site map (design.md B2), drawn through one ENU-metres-to-screen transform
// (dashboard_contract.md, "The map"). Started from the reference page's drawing code, kept as a
// copy so the reference page stays an independent check of the contract.
"use strict";

const MAP = {
  grid: 500,
  rayLength: 3000,
  wedgeReach: 2000,
  scaleBar: 1000,
  sectorLabelAt: 0.5,  // wedge labels sit this share of the reach out along the centre line
  outsideLabelMin: 24,  // px: an uncovered strip at least this thick gets the outside-coverage label
  arrowSeconds: 5,
  closeUpMargin: 0.25,  // close-up: the outermost zone plus this share of its size on each side
  roadWidth: { motorway: 3, trunk: 2.5, primary: 2, secondary: 1.5, tertiary: 1 },
  heardColour: "#ffd84a",  // the selected track's "Last heard from" wedge and label
  colour: { red: "#ff5c5c", amber: "#ffb347", info: "#a3adb8", none: "#8b949e", accent: "#4d9fff" },
};
const mapCache = { basemap: null, key: null };

function toScreen(bounds, width, height) {
  const w = bounds.max_x - bounds.min_x;
  const h = bounds.max_y - bounds.min_y;
  const scale = Math.min(width / w, height / h);
  const left = (width - w * scale) / 2;  // centred, north up
  const bottom = (height - h * scale) / 2;
  const minX = bounds.min_x - left / scale;  // the whole pane in site metres: one uniform scale
  const minY = bounds.min_y - bottom / scale;
  return {
    scale,
    at: (x, y) => [left + (x - bounds.min_x) * scale, height - bottom - (y - bounds.min_y) * scale],
    visible: { min_x: minX, min_y: minY, max_x: minX + width / scale, max_y: minY + height / scale },
  };
}

function along(x, y, azimuthDeg, metres) {  // azimuth clockwise from north
  const a = (azimuthDeg * Math.PI) / 180;
  return [x + metres * Math.sin(a), y + metres * Math.cos(a)];
}

function tracePath(ctx, view, points) {
  points.forEach(([x, y], i) => (i ? ctx.lineTo(...view.at(x, y)) : ctx.moveTo(...view.at(x, y))));
}

function layer(width, height, ratio) {
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  return { canvas, ctx };
}

// Draws everything, in the contract's order. `scene`: run, frame, basemap, rays, sectors, closeUp,
// selectedTrack, avoid (the video overlay's box in canvas pixels, or null). The canvas fills the pane; the grid runs edge to edge under the basemap.
function drawMap(canvas, scene) {
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.fillStyle = "#121820";
  ctx.fillRect(0, 0, width, height);
  const { run, frame, basemap } = scene;
  const bounds = run ? viewBounds(run.site, scene.closeUp) : basemap && basemap.bounds;  // the same box
  if (bounds) {
    const view = toScreen(bounds, width, height);
    drawBackground(ctx, view, basemap, bounds, { width, height, ratio });
    if (run) drawSite(ctx, view, run.site, frame, scene, { width, height, ratio, avoid: scene.avoid });
    drawScaleAndNorth(ctx, view, width, height);
  }
  drawNotice(ctx, basemap, width, height);
}

function viewBounds(site, closeUp) {
  if (!closeUp) return site.bounds;
  const xs = site.zones[0].polygon.map((p) => p[0]);
  const ys = site.zones[0].polygon.map((p) => p[1]);
  const pad = MAP.closeUpMargin * Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys));
  return { min_x: Math.min(...xs) - pad, min_y: Math.min(...ys) - pad, max_x: Math.max(...xs) + pad, max_y: Math.max(...ys) + pad };
}

function drawBackground(ctx, view, basemap, bounds, size) {
  drawGrid(ctx, view, view.visible);  // edge to edge; the basemap's land covers it where there is map
  if (!basemap) return;
  const key = `${size.width}x${size.height}@${size.ratio}:${JSON.stringify(bounds)}`;
  if (mapCache.key !== key || mapCache.source !== basemap) {  // paint once, then copy
    const { canvas, ctx: paint } = layer(size.width, size.height, size.ratio);
    paintBasemap(paint, view, basemap);
    Object.assign(mapCache, { basemap: canvas, key, source: basemap });
  }
  ctx.drawImage(mapCache.basemap, 0, 0, size.width, size.height);
  labelOutside(ctx, view, basemap.bounds, size);
}

function labelOutside(ctx, view, b, size) {  // each uncovered strip says what it is
  const [x0, y0] = view.at(b.min_x, b.max_y);
  const [x1, y1] = view.at(b.max_x, b.min_y);
  const text = t("outsideBasemap");
  ctx.font = "12px system-ui, sans-serif";
  ctx.fillStyle = "#6b7685";
  ctx.textAlign = "center";
  const mid = y0 + 0.75 * (y1 - y0);  // side labels low, clear of the video at upper right
  const strips = [  // thickness, centre, rotation: left, right, top, bottom of the basemap
    [x0, x0 / 2, mid, -Math.PI / 2], [size.width - x1, (x1 + size.width) / 2, mid, Math.PI / 2],
    [y0, size.width / 2, y0 / 2, 0], [size.height - y1, size.width / 2, (y1 + size.height) / 2, 0],
  ];
  for (const [thickness, cx, cy, angle] of strips) {
    if (thickness < MAP.outsideLabelMin) continue;
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(angle);
    ctx.fillText(text, 0, 4);
    ctx.restore();
  }
  ctx.textAlign = "start";
}

function fillAreas(ctx, view, areas, colour) {
  ctx.fillStyle = colour;
  for (const area of areas) {
    ctx.beginPath();
    for (const ring of area.rings) { tracePath(ctx, view, ring); ctx.closePath(); }
    ctx.fill("evenodd");  // later rings are holes
  }
}

function strokeLines(ctx, view, lines, colour, width) {
  ctx.strokeStyle = colour;
  ctx.lineWidth = width;
  for (const line of lines) { ctx.beginPath(); tracePath(ctx, view, line); ctx.stroke(); }
}

function paintBasemap(ctx, view, map) {
  const [x0, y0] = view.at(map.bounds.min_x, map.bounds.max_y);
  const [x1, y1] = view.at(map.bounds.max_x, map.bounds.min_y);
  ctx.fillStyle = "#262b33";  // land
  ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
  fillAreas(ctx, view, map.sea, "#14283c");
  fillAreas(ctx, view, map.water, "#1a3550");
  fillAreas(ctx, view, map.green, "#26392d");
  ctx.setLineDash([4, 3]);
  strokeLines(ctx, view, map.rail, "#545a62", 1);
  ctx.setLineDash([]);
  for (const road of map.roads) strokeLines(ctx, view, [road.line], "#4f5560", MAP.roadWidth[road.kind] || 1);
  strokeLines(ctx, view, map.coastline, "#3f6d94", 1.5);
  ctx.lineWidth = 1;
}

function drawGrid(ctx, view, b) {
  ctx.strokeStyle = "#2a313b";
  ctx.lineWidth = 1;
  for (let x = Math.ceil(b.min_x / MAP.grid) * MAP.grid; x <= b.max_x; x += MAP.grid) {
    ctx.beginPath(); tracePath(ctx, view, [[x, b.min_y], [x, b.max_y]]); ctx.stroke();
  }
  for (let y = Math.ceil(b.min_y / MAP.grid) * MAP.grid; y <= b.max_y; y += MAP.grid) {
    ctx.beginPath(); tracePath(ctx, view, [[b.min_x, y], [b.max_x, y]]); ctx.stroke();
  }
}

function drawSite(ctx, view, site, frame, scene, size) {
  ctx.font = "12px system-ui, sans-serif";
  drawZones(ctx, view, site.zones);
  if (!frame) { drawSensors(ctx, view, site, null); return; }
  if (frame.coverage && frame.coverage.warning) drawCoverageLoss(ctx, view, site, frame.coverage, size);
  if (scene.sectors) for (const wedge of frame.pre_alerts) drawWedge(ctx, view, wedge);  // this frame's only
  const selected = frame.tracks.find((track) => track.track_id === scene.selectedTrack);
  // Only the backend's match; a server started before `heard` existed sends none.
  const heard = (selected && selected.status === "confirmed" && selected.heard) || [];
  for (const wedge of heard) drawWedge(ctx, view, wedge, true);
  drawSensors(ctx, view, site, frame);
  if (scene.rays) drawRays(ctx, view, site, frame.rays);
  drawZoom(ctx, view, site, frame);
  for (const track of frame.tracks) drawTrack(ctx, view, track, track.track_id === scene.selectedTrack);
  const placed = [];  // label boxes already drawn this frame
  if (scene.sectors) for (const wedge of frame.pre_alerts) labelWedge(ctx, view, wedge, size, placed);
  for (const wedge of heard) labelWedge(ctx, view, wedge, size, placed, heardText(wedge), MAP.heardColour);
}

// Picket: "pk4 · Engine heard south-east · Unconfirmed". Station microphone: "st3 · heard east ·
// Acoustic warning · Camera unconfirmed"; the backend drops a microphone sector a camera track explains.
function sectorText(wedge) {
  const key = wedge.sensor_id.endsWith(".acoustic") ? "micSectorLabel" : "sectorLabel";
  return t(key, { sensor: wedge.sensor_id.split(".")[0], direction: t(`compassWord.${wedge.compass}`) });
}

function heardText(wedge) {  // "Last heard from st3 · east · 01:23.4"
  return t("heardLabel", { sensor: wedge.station_id, direction: t(`compassWord.${wedge.compass}`), t: clock(wedge.t) });
}

function labelWedge(ctx, view, wedge, size, placed, text = sectorText(wedge), colour = "#ffcf7a") {
  const [mx, my] = view.at(...along(wedge.x, wedge.y, wedge.bearing_deg, MAP.sectorLabelAt * MAP.wedgeReach));
  ctx.font = "700 12px system-ui, sans-serif";
  const w = ctx.measureText(text).width;
  let x = Math.min(Math.max(mx - w / 2, 6), size.width - w - 6);  // kept on the pane
  let y = Math.min(Math.max(my, 18), size.height - 26);
  const a = size.avoid;  // the video overlay: keep labels to its left
  if (a && x < a.x + a.w && a.x < x + w + 8 && y - 13 < a.y + a.h && a.y < y + 5) x = Math.max(6, a.x - w - 12);
  const hits = (yy) => placed.some((r) => x < r.x + r.w + 8 && r.x < x + w + 8 && Math.abs(r.y - yy) < 20);
  for (let tries = 0; tries < placed.length && hits(y); tries++) y -= 20;  // step clear of earlier labels
  placed.push({ x, y, w });
  ctx.fillStyle = "rgba(0, 0, 0, 0.6)";
  ctx.fillRect(x - 4, y - 13, w + 8, 18);
  ctx.fillStyle = colour;
  ctx.fillText(text, x, y);
  ctx.font = "12px system-ui, sans-serif";
}

function drawZones(ctx, view, zones) {
  for (const zone of zones) {  // outermost first, so the critical zone ends on top
    ctx.beginPath();
    tracePath(ctx, view, zone.polygon);
    ctx.closePath();
    ctx.fillStyle = `rgba(77, 159, 255, ${0.06 + 0.2 * zone.weight})`;
    ctx.fill();
    ctx.strokeStyle = "rgba(160, 200, 255, 0.5)";
    ctx.stroke();
    const [lx, ly] = view.at(Math.min(...zone.polygon.map((p) => p[0])), Math.max(...zone.polygon.map((p) => p[1])));
    ctx.fillStyle = "#cfe0f5";
    ctx.fillText(zone.label, lx + 4, ly + 14);  // inside the top-left corner, clear of the stations
  }
}

// Coverage reduced (design.md B4, A10): grey what fewer than 2 stations reach, inside the site.
function drawCoverageLoss(ctx, view, site, coverage, size) {
  const { canvas, ctx: grey } = layer(size.width, size.height, size.ratio);
  grey.beginPath();
  tracePath(grey, view, site.zones[0].polygon);
  grey.closePath();
  grey.fillStyle = "rgba(20, 22, 26, 0.6)";
  grey.fill();
  grey.globalCompositeOperation = "destination-out";  // cut out every pair's overlap
  const circles = site.stations
    .filter((s) => coverage.reach_m[s.station_id] > 0)
    .map((s) => [...view.at(s.x, s.y), coverage.reach_m[s.station_id] * view.scale]);
  circles.forEach((a, i) => circles.slice(i + 1).forEach((b) => {
    grey.save();
    grey.beginPath(); grey.arc(...a, 0, 2 * Math.PI); grey.clip();
    grey.beginPath(); grey.arc(...b, 0, 2 * Math.PI); grey.fill();
    grey.restore();
  }));
  ctx.drawImage(canvas, 0, 0, size.width, size.height);
}

// Solid: an unconfirmed pre_alert. Heard: the selected track's matched bearing, dashed, unfilled.
function drawWedge(ctx, view, wedge, heard = false) {
  const [x, y] = view.at(wedge.x, wedge.y);
  const toCanvas = (deg) => ((deg - 90) * Math.PI) / 180;
  ctx.save();
  ctx.fillStyle = "rgba(255, 179, 71, 0.2)";
  ctx.strokeStyle = heard ? MAP.heardColour : "rgba(255, 179, 71, 0.6)";
  if (heard) { ctx.lineWidth = 2; ctx.setLineDash([8, 5]); }
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.arc(x, y, MAP.wedgeReach * view.scale,
    toCanvas(wedge.bearing_deg - wedge.half_width_deg), toCanvas(wedge.bearing_deg + wedge.half_width_deg));
  ctx.closePath();
  if (!heard) ctx.fill();
  ctx.stroke();
  ctx.restore();
}

function drawSensors(ctx, view, site, frame) {
  const heard = new Set(frame ? frame.pickets_heard.map((p) => p.picket_id) : []);
  const flashOn = frame ? Math.round(frame.t / 0.4) % 2 === 0 : false;  // alternates each frame
  for (const picket of site.pickets) {
    const [x, y] = view.at(picket.x, picket.y);
    const lit = heard.has(picket.picket_id);
    ctx.fillStyle = lit && flashOn ? MAP.colour.amber : lit ? "#7a5520" : "#6e7681";
    ctx.beginPath(); ctx.arc(x, y, lit ? 7 : 3.5, 0, 2 * Math.PI); ctx.fill();
    if (lit) { ctx.fillStyle = MAP.colour.amber; ctx.fillText(t("heard", { id: picket.picket_id }), x + 9, y + 4); }
  }
  const down = new Set(frame ? frame.sensors.filter((s) => !s.ok).map((s) => s.sensor_id.split(".")[0]) : []);
  for (const station of site.stations) {
    const [x, y] = view.at(station.x, station.y);
    const fault = down.has(station.station_id);
    ctx.fillStyle = fault ? "#59606a" : "#e6edf3";
    ctx.fillRect(x - 6, y - 6, 12, 12);
    ctx.fillStyle = fault ? "#ff8a8a" : "#e6edf3";
    ctx.fillText(fault ? `${station.station_id} ${t("sensorDown")}` : station.station_id, x + 9, y + 4);
  }
}

function drawRays(ctx, view, site, rays) {
  const stations = Object.fromEntries(site.stations.map((s) => [s.station_id, s]));
  ctx.strokeStyle = "rgba(121, 192, 255, 0.55)";
  ctx.lineWidth = 1;
  for (const ray of rays) {
    const s = stations[ray.station_id];
    if (!s) continue;
    ctx.setLineDash(ray.sensor === "acoustic" ? [6, 4] : []);
    ctx.beginPath();
    tracePath(ctx, view, [[s.x, s.y], along(s.x, s.y, ray.azimuth_deg, MAP.rayLength)]);
    ctx.stroke();
  }
  ctx.setLineDash([]);
}

function drawZoom(ctx, view, site, frame) {
  const stations = Object.fromEntries(site.stations.map((s) => [s.station_id, s]));
  const tracks = Object.fromEntries(frame.tracks.map((tr) => [tr.track_id, tr]));
  ctx.strokeStyle = "#d2a8ff";
  ctx.setLineDash([2, 3]);
  for (const task of frame.zoom) {
    const s = stations[task.station_id];
    if (!s) continue;
    const target = tracks[task.track_id];
    const end = target ? [target.x, target.y] : along(s.x, s.y, task.azimuth_deg, MAP.wedgeReach);
    ctx.beginPath(); tracePath(ctx, view, [[s.x, s.y], end]); ctx.stroke();
    const [mx, my] = view.at((s.x + end[0]) / 2, (s.y + end[1]) / 2);
    ctx.fillStyle = "#d2a8ff";
    ctx.fillText(t("zoomTask"), mx + 4, my - 4);
  }
  ctx.setLineDash([]);
}

function drawTrack(ctx, view, track, selected) {
  const colour = MAP.colour[track.level] || MAP.colour.none;
  ctx.strokeStyle = colour;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  tracePath(ctx, view, track.trail.map(([, x, y]) => [x, y]));  // the trail as sent, never appended
  ctx.stroke();
  const [x, y] = view.at(track.x, track.y);
  ctx.beginPath();
  tracePath(ctx, view, [[track.x, track.y],
    [track.x + MAP.arrowSeconds * track.vx, track.y + MAP.arrowSeconds * track.vy]]);
  ctx.stroke();
  ctx.beginPath(); ctx.arc(x, y, 5, 0, 2 * Math.PI);
  if (track.coasting) { ctx.stroke(); } else { ctx.fillStyle = colour; ctx.fill(); }
  if (selected) {
    ctx.strokeStyle = MAP.colour.accent; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(x, y, 11, 0, 2 * Math.PI); ctx.stroke();
  }
  ctx.lineWidth = 1;
  const level = track.level ? t(`level.${track.level}`) : track.status;  // never colour alone
  ctx.fillStyle = colour;
  ctx.fillText(`${track.track_id} ${level}${track.coasting ? ` · ${t("coasting")}` : ""}`, x + 8, y - 8);
}

function drawScaleAndNorth(ctx, view, width, height) {
  const length = MAP.scaleBar * view.scale;
  ctx.fillStyle = "rgba(0, 0, 0, 0.65)";  // a backing box, like the attribution's
  ctx.fillRect(8, height - 56, length + 16, 30);
  ctx.strokeStyle = "#e6edf3"; ctx.fillStyle = "#e6edf3"; ctx.lineWidth = 2;
  ctx.font = "12px system-ui, sans-serif";
  ctx.beginPath(); ctx.moveTo(16, height - 34); ctx.lineTo(16 + length, height - 34); ctx.stroke();
  ctx.fillText(`${MAP.scaleBar} m`, 16, height - 40);
  ctx.beginPath(); ctx.moveTo(24, 86); ctx.lineTo(24, 56); ctx.stroke();  // top left, under the notice:
  ctx.beginPath(); ctx.moveTo(18, 64); ctx.lineTo(24, 56); ctx.lineTo(30, 64); ctx.stroke();  // the video sits top right
  ctx.fillText("N", 20, 52);
  ctx.lineWidth = 1;
}

function drawNotice(ctx, basemap, width, height) {  // always on: the map is real, the scenario is not
  const notice = basemap ? basemap.notice : t("simulated", { grid: MAP.grid });
  ctx.font = "700 13px system-ui, sans-serif";
  ctx.fillStyle = "rgba(0, 0, 0, 0.65)";
  ctx.fillRect(8, 8, ctx.measureText(notice).width + 16, 24);
  ctx.fillStyle = "#ffd36b";
  ctx.fillText(notice, 16, 25);
  if (!basemap) return;
  ctx.font = "11px system-ui, sans-serif";
  const text = basemap.attribution;  // the ODbL licence requires it
  const w = ctx.measureText(text).width;
  ctx.fillStyle = "rgba(0, 0, 0, 0.65)";
  ctx.fillRect(width - w - 16, height - 20, w + 12, 16);
  ctx.fillStyle = "#e6edf3";
  ctx.fillText(text, width - w - 10, height - 8);
}
