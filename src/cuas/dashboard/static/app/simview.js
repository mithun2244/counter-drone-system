// SIMULATED camera view for big-drone cues (dashboard_contract.md, `cues`): drawn on a canvas
// from what the server sends, never from footage. A dark thermal-style frame, the camera
// pointed where the view says, the target a bright dot at its reported direction, sized by
// range. Plain JS, no libraries.
"use strict";

const SIMVIEW = {
  aspect: 0.62,            // height / width of the frame
  maxHeightVh: 32,         // like the recorded clip
  minDotPx: 1.5,           // a target too small to resolve still shows as a point
  glowFactor: 2.5,         // glow radius as a multiple of the dot radius
  crosshairGapPx: 8,
  crosshairArmPx: 18,
  edgeMarginPx: 10,
  sky: ["#06080b", "#11151b"],
  ground: ["#191c20", "#0d0f12"],
  target: "#fff6d8",
  overlay: "#d7e3ef",
  label: "#ffd84a",
  scanlineEveryPx: 3,
};

function angleOff(a, b) {  // smallest signed turn from b to a, degrees
  return ((a - b + 540) % 360) - 180;
}

function sizeSimCanvas(canvas) {
  const width = canvas.clientWidth || 400;
  const height = Math.min(width * SIMVIEW.aspect, (window.innerHeight * SIMVIEW.maxHeightVh) / 100);
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  canvas.style.height = `${height}px`;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w: width, h: height };
}

function drawSimBackground(ctx, w, h, horizonY) {
  const sky = ctx.createLinearGradient(0, 0, 0, Math.max(1, horizonY));
  sky.addColorStop(0, SIMVIEW.sky[0]);
  sky.addColorStop(1, SIMVIEW.sky[1]);
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, w, h);
  if (horizonY < h) {
    const ground = ctx.createLinearGradient(0, Math.max(0, horizonY), 0, h);
    ground.addColorStop(0, SIMVIEW.ground[0]);
    ground.addColorStop(1, SIMVIEW.ground[1]);
    ctx.fillStyle = ground;
    ctx.fillRect(0, Math.max(0, horizonY), w, h);
  }
  ctx.fillStyle = "rgba(255,255,255,0.025)";  // faint scanlines, thermal-monitor style
  for (let y = 0; y < h; y += SIMVIEW.scanlineEveryPx) ctx.fillRect(0, y, w, 1);
}

function drawSimTarget(ctx, w, h, view, pxPerDeg) {
  const dx = angleOff(view.seen_azimuth_deg, view.pointing_azimuth_deg) * pxPerDeg;
  const dy = -(view.seen_elevation_deg - view.pointing_elevation_deg) * pxPerDeg;
  let x = w / 2 + dx, y = h / 2 + dy;
  const m = SIMVIEW.edgeMarginPx;
  const outside = x < m || x > w - m || y < m || y > h - m;
  // A zoom camera still slewing has no target in frame: draw nothing. Clamping the dot to the
  // edge drew a close target (wide in a 2-degree view) as a large blob in the corner.
  if (outside && view.camera === "zoom") return true;
  x = Math.min(w - m, Math.max(m, x));
  y = Math.min(h - m, Math.max(m, y));
  const spanDeg = view.range_m ? (view.drawn_span_m / view.range_m) * (180 / Math.PI) : 0;
  const r = Math.max(SIMVIEW.minDotPx, (spanDeg * pxPerDeg) / 2);
  const glow = ctx.createRadialGradient(x, y, 0, x, y, r * SIMVIEW.glowFactor);
  glow.addColorStop(0, "rgba(255,246,216,0.9)");
  glow.addColorStop(1, "rgba(255,246,216,0)");
  ctx.fillStyle = glow;
  ctx.beginPath(); ctx.arc(x, y, r * SIMVIEW.glowFactor, 0, 2 * Math.PI); ctx.fill();
  ctx.fillStyle = SIMVIEW.target;
  ctx.beginPath(); ctx.arc(x, y, r, 0, 2 * Math.PI); ctx.fill();
  return outside;
}

function drawCrosshair(ctx, w, h) {
  const g = SIMVIEW.crosshairGapPx, a = SIMVIEW.crosshairArmPx, cx = w / 2, cy = h / 2;
  ctx.strokeStyle = "rgba(215,227,239,0.75)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(cx - g - a, cy); ctx.lineTo(cx - g, cy); ctx.moveTo(cx + g, cy); ctx.lineTo(cx + g + a, cy);
  ctx.moveTo(cx, cy - g - a); ctx.lineTo(cx, cy - g); ctx.moveTo(cx, cy + g); ctx.lineTo(cx, cy + g + a);
  ctx.stroke();
}

function drawSimText(ctx, w, h, view, outside) {
  ctx.font = "600 12px system-ui, sans-serif";
  ctx.textBaseline = "top";
  ctx.fillStyle = SIMVIEW.overlay;
  const camera = t(view.camera === "zoom" ? "simZoomName" : "simWideName");
  ctx.fillText(`${view.station_id} ${camera} · ${Math.round(view.pointing_azimuth_deg)}° · FOV ${view.fov_deg.toFixed(view.fov_deg < 10 ? 1 : 0)}°`, 8, 8);
  const range = view.range_m ? t("simRange", { km: (view.range_m / 1000).toFixed(2) }) : t("simRangeUnknown");
  ctx.fillText(range, 8, 26);  // its own line: never overlaps the camera line in a narrow panel
  if (outside && view.camera !== "zoom") ctx.fillText(t("simOutside"), 8, 44);
  ctx.textAlign = "center";
  if (outside && view.camera === "zoom") ctx.fillText(t("simSlewing"), w / 2, h / 2 + 34);
  ctx.fillStyle = "rgba(0,0,0,0.65)";
  ctx.fillRect(0, h - 24, w, 24);
  ctx.fillStyle = SIMVIEW.label;
  ctx.font = "700 12px system-ui, sans-serif";
  ctx.textBaseline = "middle";
  ctx.fillText(t("simLabel"), w / 2, h - 12);
  ctx.textAlign = "left";
}

function drawSimView(canvas, view) {
  const { ctx, w, h } = sizeSimCanvas(canvas);
  const pxPerDeg = w / view.fov_deg;
  const horizonY = h / 2 + view.pointing_elevation_deg * pxPerDeg;  // elevation 0 on screen
  drawSimBackground(ctx, w, h, horizonY);
  const outside = drawSimTarget(ctx, w, h, view, pxPerDeg);
  drawCrosshair(ctx, w, h);
  drawSimText(ctx, w, h, view, outside);
}
