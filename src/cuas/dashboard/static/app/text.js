// Every string the operator sees (design.md B5), so another language can be added beside "en".
// The server's alert reasons stay English sentences (dashboard_contract.md, known limits).
"use strict";

const TEXT = {
  en: {
    title: "C-UAS operator dashboard",
    profile: "Site profile",
    scenario: "Scenario",
    recordedMedia: "Recorded media",
    zoomCameras: "Zoom cameras",
    zoomDefault: "default",
    start: "Start monitoring",
    play: "▶ Play",
    pause: "❚❚ Pause",
    rays: "Bearing rays",
    closeUp: "Close-up",
    idle: "Idle: pick a site profile and scenario",
    alertQueue: "Alert queue",
    status: "System status",
    clip: "Clip",
    allClear: "All clear · last check {clock}",
    waiting: "Waiting for the first frame",
    engineHeard: "Engine heard, {compass}, unconfirmed",
    level: { red: "RED", amber: "AMBER", info: "INFO" },
    classKey: { attack: "Attack drone", drone: "Drone", unclassified: "Unclassified" },
    approach: { inside: "Inside {zone}", heading_to: "Heading to {zone}", none: "No zone" },
    stations: "{n} stations",
    oneStation: "1 station",
    coasting: "coasting",
    tti: "TTI",
    noTti: "no TTI",
    labelled: { confirm: "Confirmed", dismiss: "Dismissed" },
    records: "{n} evidence records",
    oneRecord: "1 evidence record",
    coverage: "Coverage",
    coverageNotYet: "Coverage: waiting for the first figure",
    coverageReduced: "Coverage {pct}% — reduced",
    pickets: "Pickets",
    picketsOk: "{n} of {n} ✓ · visibility {vis}",
    sensorOk: "✓",
    sensorDown: "✗ down",
    faults: "Sensor faults: {list}",
    noFaults: "Sensor faults: none",
    evidenceHead: "Evidence head: record {seq} · {hash}",
    noEvidence: "Evidence head: none yet",
    runState: { running: "running", paused: "paused", ended: "ended" },
    runFolder: "Run folder: runs/{run}",
    simulated: "Simulated scenario: fictional site · local grid {grid} m (no basemap)",
    zoomTask: "zoom",
    heard: "{id} heard",
  },
};

const LANG = "en";

function t(key, values = {}) {
  const text = key.split(".").reduce((node, part) => node && node[part], TEXT[LANG]);
  if (typeof text !== "string") return key;
  return text.replace(/\{(\w+)\}/g, (_, name) => String(values[name] ?? ""));
}
