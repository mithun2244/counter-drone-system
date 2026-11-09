// Operator dashboard (design.md B1–B4) on the dashboard contract, version 1
// (docs/dashboard_contract.md). Plain JS, no libraries, nothing loaded from outside this server.
"use strict";

const state = {
  profiles: [], run: null, frame: null, frameWall: 0, basemap: null, ttis: new Map(),
  selected: null, looks: [], sounds: [],
};
const $ = (id) => document.getElementById(id);

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
    setFrame(message.frame);
    fillProfiles();
  } else if (message.type === "run") {
    if (!state.run || state.run.run_id !== message.run_id) { setFrame(null); select(null); }
    state.run = message;
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
}

// --- top bar ---

function fillProfiles() {
  const keep = $("profile").value;
  $("profile").replaceChildren(...state.profiles.map((p) => new Option(p.venue, p.profile_id)));
  if (state.profiles.some((p) => p.profile_id === keep)) $("profile").value = keep;
  fillScenarios();
}

function fillScenarios() {
  const profile = state.profiles.find((p) => p.profile_id === $("profile").value);
  $("scenario").replaceChildren(...(profile ? profile.scenarios : [])
    .map((s) => new Option(`${s.scenario_id.toUpperCase()}: ${s.title}`, s.scenario_id)));
}

async function post(path, body) {
  const response = await fetch(path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const reply = await response.json().catch(() => ({ detail: response.statusText }));
  $("message").textContent = response.ok ? "" : reply.detail;
  return response.ok ? reply : null;
}

function startRun() {
  const body = { profile_id: $("profile").value, scenario_id: $("scenario").value, recorded_media: $("media").checked };
  if ($("zoom").value !== "") body.zoom_per_station = Number($("zoom").value);
  post("/api/runs", body);
}

function renderTopBar() {
  const run = state.run;
  const live = run && run.state !== "ended";
  $("start").hidden = Boolean(live);
  $("running").hidden = !run;
  if (!run) return;
  $("run-title").textContent = `${run.title} · ${run.venue} · ${t(`runState.${run.state}`)}`;
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
  head.append(el("span", "level"), el("span", "class"), el("span", "tti"));
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
  card.querySelector(".class").textContent = `${t(`classKey.${a.class_key}`)} ${Math.round(100 * a.confidence)}%`;
  const where = a.zone_label ? t(`approach.${a.approach}`, { zone: a.zone_label }) : t("approach.none");
  const seen = a.coasting ? t("coasting") : a.n_stations === 1 ? t("oneStation") : t("stations", { n: a.n_stations });
  card.querySelector(".sub").textContent = `${where} · ${seen}`;
  card.querySelector(".reasons").textContent = a.reasons.join(" · ");
  const meta = card.querySelector(".meta");
  meta.replaceChildren();
  if (a.label) meta.append(el("span", "label", t(`labelled.${a.label}`)), " · ");
  meta.append(a.evidence_records === 1 ? t("oneRecord") : t("records", { n: a.evidence_records }));
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
  $("pre-alerts").replaceChildren(...pre.map((p) =>
    el("li", "pre", `${t("engineHeard", { compass: p.compass })} (${p.sensor_id})`)));
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
    if (tti === null || tti === undefined) { node.replaceChildren(el("small", "", t("noTti"))); continue; }
    node.replaceChildren(`${Math.max(0, tti - elapsed).toFixed(0)} s `, el("small", "", t("tti")));
  }
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

// --- drawing ---

// --- operator actions: labels and hand-off export (dashboard_contract.md) ---

async function act(button, alertId) {
  const action = button.dataset.action;
  const result = button.closest(".card").querySelector(".result");
  button.dataset.busy = "1";
  button.disabled = true;
  button.textContent = t("saving");
  const path = `/api/alerts/${encodeURIComponent(alertId)}`;
  const reply = action === "export" ? await post(`${path}/export`, {}) : await post(`${path}/label`, { label: action });
  button.dataset.busy = "";
  button.textContent = t(action);
  button.disabled = !state.run || state.run.state === "ended";
  result.className = reply ? "result" : "result error";
  if (!reply) { result.textContent = $("message").textContent; return; }
  if (action === "export") {  // the saved file and its hash: the response is rounded, the file is not
    result.replaceChildren(el("div", "copy", t("exported", { path: reply.path })),
      el("div", "copy", t("sha256", { hash: reply.sha256 })));
  } else {
    result.textContent = t("labelSaved", { label: t(`labelled.${action}`), seq: reply.seq });
  }
}

// --- selected alert: map ring, clip and recorded audio ---

function selectedCard() {
  return state.selected && state.frame ? state.frame.alerts.find((a) => a.alert_id === state.selected) : null;
}

function select(alertId) {
  state.selected = alertId;
  const card = selectedCard();
  showLooks(card ? card.looks : [], true);
  showSounds(card ? card.sounds : []);
  if (alertId) return;
  $("clip-note").textContent = t("pickAlert");
  $("sounds").replaceChildren();  // nothing selected: no "no audio for this alert" yet
}

const urls = (items) => items.map((i) => i.clip_url).join();

function refreshMedia() {  // recordings can join an alert after it was selected: never mid-play
  const card = selectedCard();
  if (!card) return;
  if ($("clip").paused && urls(card.looks) !== urls(state.looks)) showLooks(card.looks, false);
  if ($("audio").paused && urls(card.sounds) !== urls(state.sounds)) showSounds(card.sounds);
}

function lookName(look) {
  const [station, kind] = look.source.split(".");
  const name = t(`lookKind.${kind}`);
  return `${station} ${name === `lookKind.${kind}` ? kind : name}`;
}

function showLooks(looks, autoplay) {
  const current = state.looks[Number($("looks").dataset.index)];
  state.looks = [...looks].sort((a, b) => b.source.endsWith(".zoom") - a.source.endsWith(".zoom"));  // zoom first
  $("looks").replaceChildren(...state.looks.map((look, i) => {
    const button = el("button", "", lookName(look));
    button.dataset.index = i;
    return button;
  }));
  const keep = current ? state.looks.findIndex((l) => l.source === current.source) : -1;
  if (state.looks.length) { playLook(Math.max(keep, 0), autoplay); return; }
  $("looks").dataset.index = "";
  $("clip").removeAttribute("src");
  $("clip").load();
  $("clip-note").textContent = t("noClip");
}

function playLook(index, autoplay) {  // the RGB / thermal / zoom toggle
  const look = state.looks[index];
  $("looks").dataset.index = index;
  for (const b of $("looks").children) b.classList.toggle("on", Number(b.dataset.index) === index);
  $("clip").src = `${look.clip_url}#t=${look.at_s}`;  // media fragment: start near the look
  $("clip-note").textContent = t("clipAt", { source: look.source, at: look.at_s.toFixed(1) });
  if (autoplay) $("clip").play().catch(() => {});  // a blocked autoplay leaves the controls
}

function showSounds(sounds) {
  stopAudio();
  state.sounds = sounds;
  $("sounds").replaceChildren(...(sounds.length ? sounds.map((s) => {
    const row = el("li", "", t("station", { id: s.station_id }));
    const button = el("button", "", t("playAudio"));
    button.dataset.src = s.clip_url;
    row.append(button);
    return row;
  }) : [el("li", "note", t("noSound"))]));
}

function stopAudio() {
  $("audio").pause();
  $("audio").removeAttribute("src");
  for (const b of $("sounds").querySelectorAll("button")) b.textContent = t("playAudio");
}

function playSound(button) {
  const playing = button.textContent === t("stopAudio");
  stopAudio();
  if (playing) return;
  $("audio").src = button.dataset.src;
  button.textContent = t("stopAudio");
  $("audio").play().catch((error) => { button.textContent = t("playAudio"); $("message").textContent = String(error); });
}

// --- drawing ---

function render() {
  renderTopBar();
  renderQueue();
  renderStatus();
  const card = selectedCard();
  drawMap($("map"), { run: state.run, frame: state.frame, basemap: state.basemap, selectedTrack: card && card.track_id,
    rays: $("rays").checked, closeUp: $("close-up").checked });
}

async function loadBasemap() {
  const response = await fetch("/api/basemap");  // 404: no basemap on this machine, draw the grid
  state.basemap = response.ok ? await response.json() : null;
  render();
}

for (const node of document.querySelectorAll("[data-text]")) node.textContent = t(node.dataset.text);
document.title = t("title");
$("profile").addEventListener("change", fillScenarios);
$("go").addEventListener("click", startRun);
$("rays").addEventListener("change", render);
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
  const button = event.target.closest("button");
  if (button) playLook(Number(button.dataset.index), true);
});
$("sounds").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-src]");
  if (button) playSound(button);
});
$("audio").addEventListener("ended", stopAudio);
select(null);
$("play-pause").addEventListener("click", () =>
  post("/api/run/control", { action: state.run.state === "running" ? "pause" : "play" }));
for (const b of document.querySelectorAll("[data-speed]")) {
  b.addEventListener("click", () => post("/api/run/control", { action: "speed", speed: Number(b.dataset.speed) }));
}
new ResizeObserver(render).observe($("map"));
setInterval(tickTti, 100);
loadBasemap();
connect();
