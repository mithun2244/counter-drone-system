// Operator dashboard (design.md B1–B4) on the dashboard contract, version 1
// (docs/dashboard_contract.md). Plain JS, no libraries, nothing loaded from outside this server.
"use strict";

const state = {
  profiles: [], run: null, frame: null, models: null, frameWall: 0, basemap: null, display: null, ttis: new Map(), inside: new Set(),
  selected: null, lastCard: null, cue: null, cueTabs: new Map(), simShown: false, looks: [], source: null, sounds: [], results: new Map(), collapsed: false,
};
const COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
const STATIONARY_MPS = 0.5;  // below this ground speed a course means nothing
const $ = (id) => document.getElementById(id);
const MAX_SHOWN_PCT = 99;  // a confidence is never shown as certain
const pct = (p) => Math.min(MAX_SHOWN_PCT, Math.round(100 * p));
const simTag = () => { const tag = el("span", "sim", t("sim")); tag.title = t("simTitle"); return tag; };

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function clock(seconds) {  // simulated time as mm:ss.s
  const tenths = Math.round(seconds * 10);
  const m = Math.floor(tenths / 600);
  return `${String(m).padStart(2, "0")}:${((tenths - 600 * m) / 10).toFixed(1).padStart(4, "0")}`;
}

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
    state.models = message.models;
    setFrame(message.frame);
    fillProfiles();
  } else if (message.type === "run") {
    if (!state.run || state.run.run_id !== message.run_id) { setFrame(null); select(null); }
    state.run = message;
  } else if (message.type === "models") {
    state.models = message;
  } else if (message.type === "frame") {
    setFrame(message);
    refreshMedia();
  }
  render();
}

function setFrame(frame) {
  state.frame = frame;
  state.frameWall = performance.now();
  state.ttis = new Map(frame ? frame.alerts.map((a) => [a.alert_id, a.tti_s]) : []);
  state.inside = new Set(frame ? frame.alerts.filter((a) => a.approach === "inside").map((a) => a.alert_id) : []);
}

// --- top bar ---

function fillProfiles() {
  const keep = $("profile").value;
  $("profile").replaceChildren(...state.profiles.map((p) => new Option(p.venue, p.profile_id)));
  if (state.profiles.some((p) => p.profile_id === keep)) $("profile").value = keep;
  fillScenarios();
}

// The Scenario dropdown lists every scenario the server offers (site.yaml demo_scenarios), across
// venues; the site profile follows the scenario chosen, and choosing a profile picks its first.
function fillScenarios() {
  const keep = $("scenario").value;
  const choices = state.profiles.flatMap((p) => p.scenarios);
  $("scenario").replaceChildren(...choices
    .map((s) => new Option(`${s.scenario_id.toUpperCase()}: ${s.title}`, s.scenario_id)));
  if (choices.some((s) => s.scenario_id === keep)) $("scenario").value = keep;
  followScenario();
}

function followScenario() {
  const owner = state.profiles.find((p) => p.scenarios.some((s) => s.scenario_id === $("scenario").value));
  if (owner) $("profile").value = owner.profile_id;
}

function pickProfile() {
  const profile = state.profiles.find((p) => p.profile_id === $("profile").value);
  if (profile) $("scenario").value = profile.scenarios[0].scenario_id;
}

function scenarioTitle(run) {
  const choice = state.profiles.flatMap((p) => p.scenarios).find((s) => s.scenario_id === run.scenario_id);
  return choice ? choice.title : run.title;
}

async function post(path, body) {
  let response;
  try {
    response = await fetch(path, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
  } catch (error) {  // the server is unreachable: say so, and let callers reset their buttons
    $("message").textContent = String(error);
    return null;
  }
  const reply = await response.json().catch(() => ({ detail: response.statusText }));
  $("message").textContent = response.ok ? "" : reply.detail;
  return response.ok ? reply : null;
}

function startRun() {
  const body = { profile_id: $("profile").value, scenario_id: $("scenario").value, recorded_media: $("media").checked };
  if ($("zoom").value !== "") body.zoom_per_station = Number($("zoom").value);
  post("/api/runs", body);
}

function modelsText(models) {  // null: this server loads no models (a replay)
  if (!models) return "";
  const finished = models.steps.filter((s) => !["waiting", "loading"].includes(s.state)).length;
  if (models.state === "loading") {
    const step = models.steps.find((s) => s.state === "loading") || models.steps[finished] || {};
    return t("modelsLoading", { done: finished, total: models.steps.length, step: step.name || "" });
  }
  if (models.state === "ready") return t("modelsReady");
  const problems = models.steps.filter((s) => ["missing", "failed"].includes(s.state))
    .map((s) => t("modelProblem", { name: s.name, detail: s.detail }));
  return t("modelsFailed", { problems: problems.join("; ") });
}

function renderModels() {  // Start waits for the models; recorded media needs them ready
  const models = state.models;
  $("go").disabled = Boolean(models && models.state === "loading");
  $("media").disabled = Boolean(models && models.state !== "ready");
  if ($("media").disabled) $("media").checked = false;
  $("models").textContent = modelsText(models);
  $("models").classList.toggle("failed", Boolean(models && models.state === "failed"));
}

function renderTopBar() {
  renderModels();
  const run = state.run;
  const live = run && run.state !== "ended";
  $("start").hidden = Boolean(live);
  $("running").hidden = !run;
  if (!run) return;
  const ended = run.state === "ended" && run.ended_reason;
  $("run-title").textContent = `${scenarioTitle(run)} · ${run.venue} · ${ended ? t(`endedReason.${run.ended_reason}`) : t(`runState.${run.state}`)}`;
  $("run-title").classList.toggle("failed", run.ended_reason === "failed");
  $("stop").hidden = !live || !$("stop-confirm").hidden;
  if (!live) $("stop-confirm").hidden = true;
  $("clock").textContent = state.frame ? clock(state.frame.t) : "--:--.-";
  $("play-pause").textContent = run.state === "running" ? t("pause") : t("play");
  $("play-pause").disabled = !live;
  for (const b of document.querySelectorAll("[data-speed]")) {
    b.classList.toggle("on", Number(b.dataset.speed) === run.speed);
    b.disabled = !live;
  }
}

// --- alert queue (design.md B3, B4) ---

function makeCard(alertId) {
  const card = el("li", "card");
  card.dataset.alert = alertId;
  card.tabIndex = 0;
  const head = el("div", "head");
  head.append(el("span", "level"), el("span", "class"), el("span", "badge"), el("span", "tti"));
  const actions = el("div", "actions");
  for (const action of ["confirm", "dismiss", "export"]) {
    const button = el("button", "", t(action));
    button.dataset.action = action;
    actions.append(button);
  }
  card.append(head, el("div", "sub"), el("div", "reasons"), el("div", "meta"), actions, el("div", "result"));
  return card;
}

function fillCard(card, a) {
  card.className = `card ${a.level}${a.alert_id === state.selected ? " selected" : ""}`;
  const ended = !state.run || state.run.state === "ended";  // an ended run's evidence is closed
  for (const b of card.querySelectorAll("[data-action]")) b.disabled = ended || b.dataset.busy === "1";
  card.querySelector(".level").textContent = t(`level.${a.level}`);
  showBadge(card.querySelector(".badge"), state.frame ? cueOf((c) => c.alert_id === a.alert_id) : null);
  card.querySelector(".class").replaceChildren(`${t(`classKey.${a.class_key}`)} ${pct(a.confidence)}%`, simTag());
  const where = a.zone_label ? t(`approach.${a.approach}`, { zone: a.zone_label }) : t("approach.none");
  const seen = a.coasting ? t("coasting") : a.n_stations === 1 ? t("oneStation") : t("stations", { n: a.n_stations });
  card.querySelector(".sub").textContent = `${where} · ${seen}`;
  card.querySelector(".reasons").textContent = a.reasons.join(" · ");
  const meta = card.querySelector(".meta");
  meta.replaceChildren();
  if (a.label) meta.append(el("span", "label", t(`labelled.${a.label}`)), " · ");
  meta.append(recordsText(a.evidence_records));
}

function renderQueue() {
  const list = $("alerts");
  const alerts = state.frame ? state.frame.alerts : [];  // the server's ranking: never re-sorted
  const cards = new Map([...list.children].map((c) => [c.dataset.alert, c]));
  alerts.forEach((a, i) => {
    const card = cards.get(a.alert_id) || makeCard(a.alert_id);
    cards.delete(a.alert_id);
    fillCard(card, a);
    if (list.children[i] !== card) list.insertBefore(card, list.children[i] || null);  // keeps focus
  });
  for (const gone of cards.values()) gone.remove();
  const pre = state.frame ? state.frame.pre_alerts : [];
  $("pre-alerts").replaceChildren(...pre.map((p) => {
    const row = el("li", "pre", `${p.sensor_id.endsWith(".acoustic")
      ? t("micHeard", { direction: t(`compassWord.${p.compass}`) })
      : t("engineHeard", { compass: p.compass })} (${p.sensor_id})`);
    const badge = el("span", "badge");
    showBadge(badge, cueOf((c) => c.picket_id === p.sensor_id && !c.alert_id));
    row.append(badge);
    return row;
  }));
  const clear = state.frame && !alerts.length && !pre.length;
  $("all-clear").textContent = clear ? t("allClear", { clock: clock(state.frame.t) }) : "";
  if (!state.frame) $("all-clear").textContent = state.run ? t("waiting") : t("idle");
  tickTti();
}

function tickTti() {  // counts down between frames by `speed` per wall second
  const run = state.run;
  const elapsed = run && run.state === "running" ? (run.speed * (performance.now() - state.frameWall)) / 1000 : 0;
  for (const card of $("alerts").children) {
    const tti = state.ttis.get(card.dataset.alert);
    const node = card.querySelector(".tti");
    if (state.inside.has(card.dataset.alert)) { node.replaceChildren(el("span", "inside", t("insideZone"))); continue; }
    if (tti === null || tti === undefined) { node.replaceChildren(el("small", "", t("noTti"))); continue; }
    node.replaceChildren(`${Math.max(0, tti - elapsed).toFixed(0)} s `, el("small", "", t("tti")));
  }
}

// --- acoustic detections: heard, not placed (pre_alerts) ---

// Every acoustic event the map or an alert uses: unplaced sectors (the wedges), station
// microphone bearings matched to tracks, and each alert whose reasons say "engine heard"
// (sound evidence from a station microphone or a picket, control/classify.py).
function renderAcoustic() {
  const frame = state.frame;
  const pre = frame ? frame.pre_alerts : [];  // in the order sent
  const rows = pre.map((p) => {
    const values = { sensor: p.sensor_id.split(".")[0], direction: t(`compassWord.${p.compass}`), last: clock(p.last_t), n: p.reports };
    const row = el("li", "", t(p.reports === 1 ? "acousticRowOne" : "acousticRow", values));
    row.dataset.sector = p.sector_id;
    return row;
  });
  const placed = [];
  for (const tr of frame ? frame.tracks : []) {
    for (const h of tr.heard || []) {
      placed.push(el("li", "placed", t("acousticMic", { sensor: h.station_id, track: tr.track_id, direction: t(`compassWord.${h.compass}`), last: clock(h.t) })));
    }
  }
  for (const a of frame ? frame.alerts : []) {
    if (a.reasons.includes("engine heard")) placed.push(el("li", "placed", t("acousticAlert", { track: a.track_id, alert: a.alert_id })));
  }
  if (placed.length) rows.push(el("li", "note", t("acousticPlaced")), ...placed);
  $("acoustic").replaceChildren(...(rows.length ? rows : [el("li", "note", t("acousticNone"))]));
}

function recordsText(n) {  // 0: a live record is a moment away; a replayed stream keeps none
  if (n === 1) return t("oneRecord");
  if (n > 0) return t("records", { n });
  return state.frame && state.frame.evidence_head ? t("recordPending") : t("noEvidenceKept");
}

// --- system status (design.md B1, B4) ---

function renderStatus() {
  const frame = state.frame;
  const panel = $("status");
  panel.replaceChildren();
  const coverage = frame && frame.coverage;
  $("banner").hidden = !(coverage && coverage.warning);
  if (coverage) $("banner").textContent = t("coverageReduced", { pct: coverage.pct.toFixed(0) });
  if (!frame) return;
  panel.append(el("p", "", coverage ? `${t("coverage")} ${coverage.pct.toFixed(1)}%` : t("coverageNotYet")));
  panel.append(sensorTable(frame.sensors));
  const down = frame.sensors.filter((s) => !s.ok).map((s) => s.sensor_id);
  const faults = el("p", down.length ? "down" : "", down.length ? t("faults", { list: down.join(", ") }) : t("noFaults"));
  faults.append(simTag());  // simulated sensors never report a fault (docs/memory.md, mocks)
  const head = frame.evidence_head;
  panel.append(faults, el("p", "", head
    ? t("evidenceHead", { seq: head.seq, hash: head.record_hash.slice(0, 12) }) : t("noEvidence")));
  if (state.run && state.run.state === "ended") {
    panel.append(el("p", "copy", t("runFolder", { run: state.run.run_id })));
  }
}

function sensorTable(sensors) {
  const groups = new Map();
  for (const s of sensors) {
    const [unit, kind] = s.sensor_id.includes(".") ? s.sensor_id.split(".") : [t("pickets"), s.sensor_id];
    if (!groups.has(unit)) groups.set(unit, []);
    groups.get(unit).push({ ...s, kind });
  }
  const table = el("table");
  for (const [unit, list] of groups) {
    const row = table.insertRow();
    row.append(el("th", "", unit));
    const cell = row.insertCell();
    row.insertCell().append(simTag());  // every health value here comes from the simulator
    const allOk = list.every((s) => s.ok);
    if (unit === t("pickets") && allOk) {  // eight healthy pickets read as one line
      const lowest = Math.min(...list.map((s) => s.visibility));
      cell.append(t("picketsOk", { n: list.length, vis: lowest.toFixed(2) }));
      continue;
    }
    list.forEach((s, i) => {
      if (i) cell.append(" · ");
      cell.append(el("span", s.ok ? "" : "down",
        `${s.kind} ${s.ok ? t("sensorOk") : t("sensorDown")} ${s.visibility.toFixed(2)}`));
    });
  }
  return table;
}

// --- operator actions: labels and hand-off export (dashboard_contract.md) ---

async function act(button, alertId) {
  const action = button.dataset.action;
  button.dataset.busy = "1";
  button.disabled = true;
  button.textContent = t("saving");
  const path = `/api/alerts/${encodeURIComponent(alertId)}`;
  const reply = action === "export" ? await post(`${path}/export`, {}) : await post(`${path}/label`, { label: action });
  button.dataset.busy = "";
  button.textContent = t(action);
  button.disabled = !state.run || state.run.state === "ended";
  let lines;
  if (!reply) lines = [$("message").textContent];
  else if (action === "export") lines = [t("exported", { path: reply.path }), t("sha256", { hash: reply.sha256 })];
  else lines = [t("labelSaved", { label: t(`labelled.${action}`), seq: reply.seq })];
  state.results.set(alertId, { error: !reply, lines });  // the file's hash: the response is rounded, the file is not
  const card = button.closest(".card");
  if (card) showResult(card.querySelector(".result"), state.results.get(alertId));
  renderDetails();
}

function showResult(node, result) {
  node.className = result.error ? "result error" : "result";
  node.replaceChildren(...result.lines.map((line) => el("div", "copy", line)));
}

// --- selected alert: map ring, video over the map, details and evidence ---

function selectedCard() {
  return state.selected && state.frame ? state.frame.alerts.find((a) => a.alert_id === state.selected) : null;
}

function select(alertId) {
  state.selected = alertId;
  state.lastCard = selectedCard();
  state.source = null;
  const card = state.lastCard;
  refreshTabs(card ? card.looks : []);
  if (state.looks.length) loadSource(state.looks[0].source, true);
  else { $("clip").removeAttribute("src"); $("clip").load(); }
  showSounds(card ? card.sounds : []);
  $("details-panel").hidden = !alertId;
  $("video-overlay").hidden = !alertId;
}

const urls = (items) => items.map((i) => i.clip_url).join();

// Each frame: tabs and audio rows follow the alert, but the loaded clip is never reloaded, so the
// chosen source and playback survive updates. A tab click loads that source's newest clip.
function refreshMedia() {
  const card = selectedCard();
  if (!card) return;
  state.lastCard = card;
  refreshTabs(card.looks);
  const kept = state.looks.some((l) => l.source === state.source);
  if (state.looks.length && (!state.source || !kept) && $("clip").paused) loadSource(state.looks[0].source, false);
  if ($("audio").paused && urls(card.sounds) !== urls(state.sounds)) showSounds(card.sounds);
}

// --- real video for the camera tabs (config/display_clips.yaml, GET /api/display) ---

const LOOK_CAMERA = { rgb: "wide", zoom: "zoom" };

function displayTabs() {  // this run's scenario's clips; a scenario listed there has no Thermal tab
  return state.display && state.run ? state.display.scenarios[state.run.scenario_id] || null : null;
}

function displayClip(camera) {  // "wide" or "zoom"; null keeps the simulated view or the look clip
  const tabs = displayTabs();
  return tabs && tabs[camera] ? state.display.clips[tabs[camera]] : null;
}

function displayTabName(camera, station, clip) {
  return t(camera === "zoom" ? "displayZoomTab" : "displayWideTab", { station, kind: t(`displayKind.${clip.type}`) });
}

async function loadDisplay() {
  const response = await fetch("/api/display");
  state.display = response.ok ? await response.json() : null;
  render();
}

function lookName(look) {
  const [station, kind] = look.source.split(".");
  const clip = displayClip(LOOK_CAMERA[kind]);
  if (clip) return displayTabName(LOOK_CAMERA[kind], station, clip);
  const name = t(`lookKind.${kind}`);
  return `${station} ${name === `lookKind.${kind}` ? kind : name}`;
}

function refreshTabs(looks) {  // keyed by source; zoom first
  const shown = displayTabs() ? looks.filter((l) => !l.source.endsWith(".thermal")) : looks;
  state.looks = [...shown].sort((a, b) => b.source.endsWith(".zoom") - a.source.endsWith(".zoom"));
  const names = state.looks.map((l) => l.source).join();
  if (names !== [...$("looks").children].map((b) => b.dataset.source).join()) {
    $("looks").replaceChildren(...state.looks.map((look) => {
      const button = el("button", "", lookName(look));
      button.dataset.source = look.source;
      button.setAttribute("role", "tab");
      return button;
    }));
  }
  for (const b of $("looks").children) {
    const on = b.dataset.source === state.source;
    b.classList.toggle("on", on);
    b.setAttribute("aria-selected", String(on));
  }
  $("video-overlay").classList.toggle("empty", !state.source);
  $("clip-tag").hidden = !state.source;
  const none = state.run && state.run.recorded_media ? "noClipRecorded" : "noClip";
  if (!state.source) $("clip-note").textContent = state.looks.length ? "" : t(none);
}

function loadSource(source, autoplay) {  // the RGB / thermal / zoom tabs
  const look = state.looks.find((l) => l.source === source);
  if (!look) return;
  state.source = source;
  const clip = displayClip(LOOK_CAMERA[source.split(".")[1]]);
  $("clip").loop = Boolean(clip);
  $("clip").src = clip ? clip.url : `${look.clip_url}#t=${look.at_s}`;  // media fragment: start near the look
  $("clip-note").textContent = clip ? clip.caption : t("clipAt", { dataset: look.dataset || t("someDataset") });
  $("clip-tag").textContent = clip ? clip.type : "SAMPLE";
  refreshTabs(state.looks);
  if (autoplay) $("clip").play().catch(() => {});  // a blocked autoplay leaves the controls
}

function setCollapsed(collapsed) {
  state.collapsed = collapsed;
  $("video-overlay").classList.toggle("collapsed", collapsed);
  $("collapse").textContent = collapsed ? t("expand") : t("collapse");
  $("collapse").title = collapsed ? t("expandLabel") : t("collapseLabel");
  $("collapse").setAttribute("aria-expanded", String(!collapsed));
}

function trackFacts(track) {  // each value with its unit
  const speed = Math.hypot(track.vx, track.vy);
  const course = Math.round((((Math.atan2(track.vx, track.vy) * 180) / Math.PI) + 360) % 360) % 360;  // clockwise from north
  return {
    track: `${track.track_id} · ${track.status}`,
    position: t("positionValue", {
      x: Math.abs(track.x).toFixed(0), ew: track.x < 0 ? "W" : "E", y: Math.abs(track.y).toFixed(0), ns: track.y < 0 ? "S" : "N",
    }),
    altitude: t("altitudeValue", { z: track.z.toFixed(0) }),
    speed: t("speedValue", { ms: speed.toFixed(1), kmh: (speed * 3.6).toFixed(0) }),
    course: speed < STATIONARY_MPS ? t("stationary") : t("courseValue", { deg: course, compass: COMPASS[Math.round(course / 45) % 8] }),
    stations: String(track.n_stations),
    coasting: track.coasting ? t("coastingYes") : t("coastingNo"),
  };
}

function renderDetails() {
  if (!state.selected) return;
  const card = selectedCard() || state.lastCard;
  if (!card) { $("details").replaceChildren(el("p", "note", t("alertGone"))); $("evidence").replaceChildren(); return; }
  const track = state.frame ? state.frame.tracks.find((tr) => tr.track_id === card.track_id) : null;  // joined by track_id
  const facts = track ? trackFacts(track) : null;
  const where = card.zone_label ? t(`approach.${card.approach}`, { zone: card.zone_label }) : t("approach.none");
  const tti = card.approach === "inside" ? t("insideZone") : card.tti_s === null ? t("noTti") : `${t("tti")} ${card.tti_s.toFixed(0)} s`;
  const summary = el("p", `summary level ${card.level}`,
    `${t(`level.${card.level}`)} · ${t(`classKey.${card.class_key}`)} ${pct(card.confidence)}%`);
  summary.append(simTag(), ` · ${tti} · ${where}`);
  const table = el("table");
  const row = (key, value) => {
    const tr = table.insertRow();
    tr.append(el("th", "", t(`detail.${key}`)));
    const td = tr.insertCell();
    td.dataset.key = key;
    td.textContent = value;
    if (value.startsWith(t("unavailable"))) td.className = "unavailable";
  };
  row("track", facts ? facts.track : card.track_id);
  row("updated", state.frame ? clock(state.frame.t) : t("unavailable"));
  for (const key of ["position", "altitude", "speed", "course", "stations", "coasting"]) {
    row(key, facts ? facts[key] : t("noTrack", { id: card.track_id }));
  }
  $("details").replaceChildren(summary, table, el("p", "note", t("detailsNote")));
  if (!selectedCard()) $("details").append(el("p", "note", t("alertGone")));
  const evidence = [
    el("p", card.label ? "label" : "unavailable", card.label ? t(`labelled.${card.label}`) : t("noLabel")),
    el("p", "", recordsText(card.evidence_records)),
  ];
  const result = state.results.get(card.alert_id);
  if (result) { const node = el("div"); showResult(node, result); evidence.push(node); }
  $("evidence").replaceChildren(...evidence);
}

function showSounds(sounds) {
  stopAudio();
  state.sounds = sounds;
  $("sounds").replaceChildren(...(sounds.length ? sounds.map((s) => {
    const row = el("li", "", t("station", { id: s.station_id }));
    const label = t("playAudio", { dataset: s.dataset || t("someDataset") });
    const button = el("button", "", label);
    button.dataset.src = s.clip_url;
    button.dataset.label = label;
    row.append(button);
    return row;
  }) : [el("li", "note", t("noSound"))]));
}

function stopAudio() {
  $("audio").pause();
  $("audio").removeAttribute("src");
  for (const b of $("sounds").querySelectorAll("button")) b.textContent = b.dataset.label;
}

function playSound(button) {
  const playing = button.textContent === t("stopAudio");
  stopAudio();
  if (playing) return;
  $("audio").src = button.dataset.src;
  button.textContent = t("stopAudio");
  $("audio").play().catch((error) => { button.textContent = button.dataset.label; $("message").textContent = String(error); });
}

// --- big-drone camera cues: acoustic -> camera -> zoom, as a SIMULATED view (simview.js) ---

const STAGE_ORDER = { zoom: 0, camera: 1, acoustic: 2 };

function cueOf(match) {
  return state.frame ? (state.frame.cues || []).find(match) || null : null;
}

// A selected alert shows its own cue; with nothing selected the highest-priority cue opens by
// itself (alert rank, then stage, then first heard). Never changes what the operator selected.
function pickCue() {
  if (!state.frame) return null;
  if (state.selected) {
    const own = cueOf((c) => c.alert_id === state.selected);
    return own && { cue: own, auto: false };
  }
  const rank = new Map(state.frame.alerts.map((a, i) => [a.alert_id, i]));
  const cues = [...(state.frame.cues || [])].sort((a, b) =>
    (rank.get(a.alert_id) ?? Infinity) - (rank.get(b.alert_id) ?? Infinity)
    || STAGE_ORDER[a.stage] - STAGE_ORDER[b.stage] || a.heard_t - b.heard_t);
  return cues.length ? { cue: cues[0], auto: true } : null;
}

function showBadge(node, cue) {  // camera detected, but not the cue in the video panel
  const shown = cue && cue.stage !== "acoustic" && (!state.cue || state.cue.cue_id !== cue.cue_id);
  node.textContent = shown ? t("cameraDetected") : "";
  node.hidden = !shown;
}

function renderCue() {
  const pick = pickCue();
  const overlay = $("video-overlay");
  state.cue = pick ? pick.cue : null;
  overlay.classList.toggle("sim", Boolean(pick));
  if (!pick) {
    overlay.classList.remove("viewing", "standin");
    $("standin").pause();
    $("cue-note").textContent = "";
    if (state.simShown) { state.simShown = false; refreshTabs(state.looks); }
    overlay.hidden = !state.selected;
    return;
  }
  state.simShown = true;
  overlay.hidden = false;  // auto-open: shows the panel, selects nothing
  if (!$("clip").paused) $("clip").pause();
  const cue = pick.cue;
  const chosen = state.cueTabs.get(cue.cue_id);  // the operator's tab, else zoom once assigned
  const view = cue.views.find((v) => v.camera === chosen) || cue.views.find((v) => v.camera === "zoom") || cue.views[0];
  $("looks").replaceChildren(...cue.views.map((v) => {
    const clip = displayClip(v.camera);
    const name = clip ? displayTabName(v.camera, v.station_id, clip)
      : t(v.camera === "zoom" ? "simZoomTab" : "simWideTab", { station: v.station_id });
    const button = el("button", v === view ? "on" : "", name);
    button.dataset.cam = v.camera;
    button.setAttribute("role", "tab");
    button.setAttribute("aria-selected", String(v === view));
    return button;
  }));
  overlay.classList.toggle("viewing", Boolean(view));
  overlay.classList.remove("empty");
  $("clip-note").textContent = view
    ? t("cameraDetection", { t: clock(cue.detected_t), station: cue.detected_by })
    : t("acousticOnly", { deg: Math.round(cue.cue_bearing_deg) });
  $("cue-note").textContent = pick.auto ? t("autoFollow") : "";
  // A real clip for this tab, if the scenario has one: never a detection box on it. Otherwise,
  // or with no clip on this machine, the simulated view.
  const clip = view && displayClip(view.camera);
  overlay.classList.toggle("standin", Boolean(clip));
  if (clip) showDisplayClip(clip, view.camera === "zoom" && simTargetOutside(view));
  else $("standin").pause();
  if (view && !clip && !state.collapsed) drawSimView($("simview"), view);
}

// A zoom camera still slewing (target outside its field of view) dims the clip and says so.
function showDisplayClip(clip, slewing) {
  const video = $("standin");
  if (video.dataset.url !== clip.url) { video.dataset.url = clip.url; video.src = clip.url; }
  $("standin-tag").textContent = clip.type;
  $("standin-note").textContent = clip.caption;
  $("standin-box").classList.toggle("slewing", slewing);
  if (slewing || state.collapsed) video.pause();
  else video.play().catch(() => {});
}

// The clip loops; a short fade hides the jump from its last frame back to its first.
$("standin").addEventListener("timeupdate", ({ target: v }) => {
  v.style.opacity = v.currentTime < 0.2 || v.duration - v.currentTime < 0.4 ? 0 : 1;
});

// --- drawing ---

function render() {
  renderTopBar();
  renderCue();  // before the queue, so badges know which cue the panel shows
  renderQueue();
  renderStatus();
  renderAcoustic();
  renderDetails();
  const card = selectedCard();
  const o = $("video-overlay").getBoundingClientRect(), m = $("map").getBoundingClientRect();
  const avoid = $("video-overlay").hidden ? null : { x: o.left - m.left, y: o.top - m.top, w: o.width, h: o.height };
  drawMap($("map"), { run: state.run, frame: state.frame, basemap: state.basemap, selectedTrack: card && card.track_id,
    rays: $("rays").checked, sectors: $("sectors").checked, closeUp: $("close-up").checked, avoid });
}

async function loadBasemap() {
  const response = await fetch("/api/basemap");  // 404: no basemap on this machine, draw the grid
  state.basemap = response.ok ? await response.json() : null;
  render();
}

for (const node of document.querySelectorAll("[data-text]")) node.textContent = t(node.dataset.text);
document.title = t("title");
$("profile").addEventListener("change", pickProfile);
$("scenario").addEventListener("change", followScenario);
$("go").addEventListener("click", startRun);
$("rays").addEventListener("change", render);
$("sectors").addEventListener("change", render);
$("close-up").addEventListener("change", render);
$("alerts").addEventListener("click", (event) => {
  const card = event.target.closest(".card");
  if (!card) return;
  const button = event.target.closest("button[data-action]");
  if (button) { act(button, card.dataset.alert); return; }
  if (!event.target.closest(".result")) { select(card.dataset.alert); render(); }  // leave the hash selectable
});
$("alerts").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && event.target.classList.contains("card")) { select(event.target.dataset.alert); render(); }
});
$("looks").addEventListener("click", (event) => {
  const cam = event.target.closest("button[data-cam]");
  if (cam && state.cue) { state.cueTabs.set(state.cue.cue_id, cam.dataset.cam); render(); return; }
  const button = event.target.closest("button[data-source]");
  if (button) loadSource(button.dataset.source, true);
});
$("collapse").addEventListener("click", () => { setCollapsed(!state.collapsed); render(); });  // redraws a simulated view
setCollapsed(false);
$("sounds").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-src]");
  if (button) playSound(button);
});
$("audio").addEventListener("ended", stopAudio);
select(null);
$("play-pause").addEventListener("click", () =>
  post("/api/run/control", { action: state.run.state === "running" ? "pause" : "play" }));
function askStop(open) {  // the dashboard's own confirm, not a browser dialog
  $("stop-confirm").hidden = !open;
  renderTopBar();
  if (open) $("stop-no").focus();
}
$("stop").addEventListener("click", () => askStop(true));
$("stop-no").addEventListener("click", () => askStop(false));
$("stop-confirm").addEventListener("keydown", (event) => { if (event.key === "Escape") askStop(false); });
$("stop-yes").addEventListener("click", async () => {
  $("stop-yes").disabled = true;
  $("stop-yes").textContent = t("stopping");
  await post("/api/run/stop", {});
  $("stop-yes").disabled = false;
  $("stop-yes").textContent = t("stopYes");
  askStop(false);
});
for (const b of document.querySelectorAll("[data-speed]")) {
  b.addEventListener("click", () => post("/api/run/control", { action: "speed", speed: Number(b.dataset.speed) }));
}
new ResizeObserver(render).observe($("map"));
setInterval(tickTti, 100);
loadBasemap();
loadDisplay();
connect();
