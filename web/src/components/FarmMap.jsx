// Pixel-art world map: the Central Valley grid zooms down to one farm.
// Drawn on a canvas at art-pixel resolution and scaled up without smoothing.
// PNGs in /sprites replace the procedural shapes once they load.
import { useEffect, useRef } from "react";

export const PAL = {
  grass: "#6abe30", grass2: "#4b9a2a", grass3: "#8fd14f", road: "#eec39a", road2: "#d9a066",
  soil: "#8f563b", soil2: "#663931", crack: "#c9905a", dry: "#d9a066", water: "#5fcde4", water2: "#306082", foam: "#cbf1f5",
  wheatG: "#7cc04a", wheat: "#fbd34d", wheat2: "#e2a93b", tree: "#3f8f3a", tree2: "#2f6d2c", trunk: "#663931",
  tomLeaf: "#37803a", tomLeaf2: "#2a6a2e", tom: "#d43f3f", tomUnripe: "#e9a23b",
  saff: "#5f9e3a", saffF: "#f59f22", vetch: "#5aa548", vetch2: "#468c3a", vetchF: "#9d5ccf",
  roof: "#ac3232", roof2: "#7a2222", wall: "#f4e4c1", white: "#ffffff", silo: "#9badb7", silo2: "#6b7d88", ink: "#2b1d14",
  hill: "#c9a66b", hill2: "#b08850", sierra: "#8a8f98", snow: "#eef2f5", ocean: "#4a90c8",
};
export const STRAT_PX = { existing: "#2a78d6", cover_crop: "#1baf7a", drought_tolerant: "#eb6834" };
const FP = 24; // art px per field

const rnd = (s) => { const x = Math.sin(s * 9301 + 49297) * 233280; return x - Math.floor(x); };
const hash = (str) => { let h = 0; for (const c of str) h = (h * 31 + c.charCodeAt(0)) | 0; return Math.abs(h); };
function ell(g, cx, cy, rx, ry) { for (let y = -ry; y <= ry; y++) for (let x = -rx; x <= rx; x++) if ((x * x) / (rx * rx || 1) + (y * y) / (ry * ry || 1) <= 1) g.fillRect(cx + x, cy + y, 1, 1); }

// ------------------------------------------------------------ field tile
// key: crop|stage|water ; stage 0 seed,1 grow,2 ripe ; water 0 dry,1 normal,2 wet
export function drawFieldTile(g, fx, fy, seed, cropKey, progress, water, sprite) {
  const stage = cropKey == null ? -1 : progress < 0.35 ? 0 : progress < 0.7 ? 1 : 2;
  for (let y = 0; y < FP; y++) for (let x = 0; x < FP; x++) {
    const n = rnd(seed + x * 13 + y * 7);
    g.fillStyle = water === 0 ? (n < 0.2 ? PAL.crack : PAL.dry) : (n < 0.25 ? PAL.soil2 : PAL.soil);
    g.fillRect(fx + x, fy + y, 1, 1);
  }
  if (water === 0) { g.fillStyle = PAL.soil2; for (let i = 0; i < 6; i++) { let x = fx + 2 + Math.floor(rnd(seed + i) * 20), y = fy + 2 + Math.floor(rnd(seed + i * 3) * 18); for (let k = 0; k < 4; k++) { g.fillRect(x, y, 1, 1); x += rnd(seed + i + k) < 0.5 ? 1 : 0; y += 1; } } }
  if (sprite) {
    g.imageSmoothingEnabled = false;
    g.drawImage(sprite, fx, fy, FP, FP);
  } else if (stage < 0) { // fallow: furrows
    g.fillStyle = water === 0 ? PAL.crack : PAL.soil2; for (let y = 2; y < FP; y += 4) g.fillRect(fx + 1, fy + y, FP - 2, 1);
  } else if (cropKey === "processing_tomato") {
    for (let y = 1; y < FP - 1; y += 3) {
      g.fillStyle = stage === 0 ? PAL.soil2 : PAL.tomLeaf2; g.fillRect(fx + 1, fy + y + 1, FP - 2, 1);
      for (let x = 1; x < FP - 1; x += stage === 0 ? 3 : 1) { if (stage === 0) { g.fillStyle = PAL.wheatG; g.fillRect(fx + x, fy + y, 1, 1); } else { g.fillStyle = rnd(seed + x + y * 3) < 0.3 ? PAL.tomLeaf2 : PAL.tomLeaf; g.fillRect(fx + x, fy + y, 1, stage === 2 ? 2 : 1); } }
      if (stage === 2) for (let x = 2; x < FP - 2; x += 2) if (rnd(seed + x * 3 + y) < 0.5) { g.fillStyle = progress > 0.85 ? PAL.tom : PAL.tomUnripe; g.fillRect(fx + x, fy + y, 1, 1); }
    }
  } else if (cropKey === "winter_wheat") {
    for (let y = 0; y < FP; y++) for (let x = 0; x < FP; x++) {
      const n = rnd(seed + x * 17 + y * 5);
      if (stage === 0 && (x % 3 || n < 0.6)) continue;
      g.fillStyle = stage === 2 ? (n < 0.2 ? PAL.wheat2 : PAL.wheat) : (n < 0.25 ? PAL.grass2 : PAL.wheatG);
      if (n < 0.92) g.fillRect(fx + x, fy + y, 1, 1);
    }
    if (stage === 2) { g.fillStyle = PAL.wheat2; for (let x = 1; x < FP; x += 4) g.fillRect(fx + x, fy + 1, 1, FP - 2); }
  } else if (cropKey === "safflower") {
    for (let y = 1; y < FP; y += 3) for (let x = 1; x < FP - 1; x++) {
      const n = rnd(seed + x * 7 + y * 11);
      if (stage === 0 && n < 0.6) continue;
      g.fillStyle = n < 0.3 ? PAL.grass2 : PAL.saff; g.fillRect(fx + x, fy + y, 1, stage ? 2 : 1);
      if (stage === 2 && n > 0.72) { g.fillStyle = PAL.saffF; g.fillRect(fx + x, fy + y, 1, 1); }
    }
  } else if (cropKey === "vetch_cover") {
    for (let y = 0; y < FP; y++) for (let x = 0; x < FP; x++) {
      const n = rnd(seed + x * 19 + y * 3);
      if (stage === 0 && n < 0.55) continue;
      g.fillStyle = stage === 2 && n < 0.14 ? PAL.vetchF : (n < 0.3 ? PAL.vetch2 : PAL.vetch);
      if (n < 0.94) g.fillRect(fx + x, fy + y, 1, 1);
    }
  } else { // any other crop from the guides: generic rows
    g.fillStyle = PAL.grass2; for (let y = 2; y < FP; y += 3) g.fillRect(fx + 1, fy + y, FP - 2, stage ? 2 : 1);
  }
  if (water === 2) { g.fillStyle = PAL.water; for (let y = 3; y < FP; y += 6) g.fillRect(fx + 1, fy + y, FP - 2, 1); }
}

function tree(g, x, y) { g.fillStyle = PAL.trunk; g.fillRect(x + 2, y + 4, 1, 3); g.fillStyle = PAL.tree2; ell(g, x + 2, y + 2, 3, 3); g.fillStyle = PAL.tree; ell(g, x + 2, y + 1, 2, 2); }
function house(g, x, y) { g.fillStyle = PAL.roof2; g.fillRect(x, y, 22, 3); g.fillStyle = PAL.roof; g.fillRect(x + 1, y + 3, 20, 5); g.fillStyle = PAL.wall; g.fillRect(x + 2, y + 8, 18, 9); g.fillStyle = PAL.soil; g.fillRect(x + 9, y + 12, 4, 5); g.fillStyle = PAL.water; g.fillRect(x + 4, y + 10, 3, 3); g.fillRect(x + 15, y + 10, 3, 3); g.fillStyle = PAL.ink; g.fillRect(x + 2, y + 17, 18, 1); }
function barn(g, x, y) { g.fillStyle = "#4a4f5a"; for (let i = 0; i < 6; i++) g.fillRect(x + 6 - i, y + i, 12 + 2 * i, 1); g.fillStyle = PAL.roof; g.fillRect(x, y + 6, 24, 13); g.fillStyle = PAL.white; g.fillRect(x + 8, y + 9, 8, 10); g.fillStyle = PAL.roof2; g.fillRect(x + 9, y + 10, 6, 9); g.fillStyle = PAL.white; for (let i = 0; i < 6; i++) { g.fillRect(x + 9 + i, y + 10 + i, 1, 1); g.fillRect(x + 14 - i, y + 10 + i, 1, 1); } }
function silo(g, x, y) { g.fillStyle = PAL.silo2; g.fillRect(x, y + 2, 8, 20); g.fillStyle = PAL.silo; g.fillRect(x + 1, y + 2, 6, 20); g.fillStyle = PAL.silo2; ell(g, x + 4, y + 2, 4, 2); g.fillStyle = PAL.ink; for (let i = 4; i < 20; i += 3) g.fillRect(x + 6, y + i, 1, 1); }
function well(g, x, y) { g.fillStyle = PAL.silo2; g.fillRect(x, y + 3, 7, 5); g.fillStyle = PAL.water2; g.fillRect(x + 1, y + 4, 5, 3); g.fillStyle = PAL.trunk; g.fillRect(x, y - 2, 1, 5); g.fillRect(x + 6, y - 2, 1, 5); g.fillStyle = PAL.roof; g.fillRect(x - 1, y - 3, 9, 2); }

// ------------------------------------------------------------- component
export default function FarmMap({ farm, fieldState, selected, picked, tool, onPaint, onSelect, onPick, focus, apiRef, speed = 1, cows = 0, compost = 0 }) {
  const ref = useRef(null);
  const live = useRef({});
  live.current = { fieldState, selected, picked, tool, onPaint, onSelect, onPick, speed, cows, compost };
  const eng = useRef(null);
  const spritesRef = useRef({});
  const spriteEpoch = useRef(0);

  useEffect(() => {
    const names = ["cow", "sheep", "chicken", "tractor", "sprayer", "harvester", "compost",
      "processing_tomato_0", "processing_tomato_1", "processing_tomato_2",
      "winter_wheat_0", "winter_wheat_1", "winter_wheat_2",
      "safflower_0", "safflower_1", "safflower_2",
      "vetch_cover_0", "vetch_cover_1", "vetch_cover_2"];
    for (const name of names) {
      const img = new Image();
      img.onload = () => { spritesRef.current[name] = img; spriteEpoch.current += 1; };
      img.src = `/sprites/${name}.png`;
    }
  }, []);

  // build world once
  useEffect(() => {
    if (!farm) return undefined;
    const cv = ref.current, ctx = cv.getContext("2d");
    const lat0 = farm.center[0], lon0 = farm.center[1];
    const KX = 111320 * Math.cos((lat0 * Math.PI) / 180), KY = 110540;
    const proj = (lat, lon) => [(lon - lon0) * KX, -(lat - lat0) * KY];

    // farm layer
    const rects = {};
    farm.fields.forEach((f) => { const [w, s, e, n] = f.bbox; const [x0, y0] = proj(n, w), [x1, y1] = proj(s, e); rects[f.id] = { x: x0, y: y0, w: x1 - x0, h: y1 - y0, f }; });
    const R = Object.values(rects), mppF = R[0].w / FP, M = 44;
    const fx0 = Math.min(...R.map((r) => r.x)) - M * mppF, fy0 = Math.min(...R.map((r) => r.y)) - M * mppF;
    const fx1 = Math.max(...R.map((r) => r.x + r.w)) + M * mppF, fy1 = Math.max(...R.map((r) => r.y + r.h)) + M * mppF;
    const FW = Math.ceil((fx1 - fx0) / mppF), FH = Math.ceil((fy1 - fy0) / mppF);
    const fcv = document.createElement("canvas"); fcv.width = FW; fcv.height = FH;
    const fg = fcv.getContext("2d");
    fg.imageSmoothingEnabled = false;
    const toF = (x, y) => [Math.round((x - fx0) / mppF), Math.round((y - fy0) / mppF)];
    for (let y = 0; y < FH; y++) for (let x = 0; x < FW; x++) { const r = rnd(x * 57 + y * 131); fg.fillStyle = r < 0.06 ? PAL.grass2 : r > 0.96 ? PAL.grass3 : PAL.grass; fg.fillRect(x, y, 1, 1); }
    for (let y = 0; y < FH; y++) { const cx = 10 + Math.round(2 * Math.sin(y / 14)); fg.fillStyle = PAL.road2; fg.fillRect(cx - 2, y, 1, 1); fg.fillRect(cx + 9, y, 1, 1); for (let x = cx - 1; x < cx + 9; x++) { fg.fillStyle = rnd(x * 5 + y * 3) < 0.08 ? PAL.foam : x < cx + 1 || x > cx + 6 ? PAL.water2 : PAL.water; fg.fillRect(x, y, 1, 1); } }
    for (let x = 24; x < FW - 4; x += 7) { tree(fg, x, 4 + Math.round(rnd(x) * 3)); tree(fg, x + 3, FH - 12 + Math.round(rnd(x + 1) * 3)); }
    const bx = FW - M + 8, by = 12;
    house(fg, bx, by); barn(fg, bx, by + 26); silo(fg, bx + 27, by + 24); well(fg, bx + 28, by + 6);
    fg.fillStyle = PAL.road; fg.fillRect(M - 6, by + 21, FW - M, 2);
    fg.fillStyle = PAL.water2; ell(fg, bx + 14, FH - 30, 11, 6); fg.fillStyle = PAL.water; ell(fg, bx + 14, FH - 30, 9, 4);
    // pasture with a fence (the herd lives here), compost pad by the barn
    const pas = { x0: bx - 4, y0: by + 54, x1: FW - 5, y1: FH - 44 };
    fg.fillStyle = PAL.grass3; fg.fillRect(pas.x0, pas.y0, pas.x1 - pas.x0, pas.y1 - pas.y0);
    for (let y = pas.y0; y < pas.y1; y++) for (let x = pas.x0; x < pas.x1; x++) if (rnd(x * 7 + y * 13) < 0.08) { fg.fillStyle = PAL.grass2; fg.fillRect(x, y, 1, 1); }
    fg.fillStyle = PAL.trunk; for (let x = pas.x0; x <= pas.x1; x += 3) { fg.fillRect(x, pas.y0, 1, 2); fg.fillRect(x, pas.y1, 1, 2); }
    fg.fillRect(pas.x0, pas.y0, pas.x1 - pas.x0, 1); fg.fillRect(pas.x0, pas.y1, pas.x1 - pas.x0, 1);
    for (let y = pas.y0; y <= pas.y1; y += 3) { fg.fillRect(pas.x0, y, 1, 2); fg.fillRect(pas.x1, y, 1, 2); }
    fg.fillStyle = "#b9a58a"; fg.fillRect(bx + 26, by + 46, 12, 6);
    const compostAt = [bx + 32, by + 49];
    R.forEach((r) => { const [x, y] = toF(r.x, r.y); fg.fillStyle = PAL.road; fg.fillRect(x - 2, y - 2, FP + 4, FP + 4); });
    const tileKey = {};

    const herd = Array.from({ length: 40 }, (_, k) => ({ x: pas.x0 + 4 + rnd(k) * (pas.x1 - pas.x0 - 8), y: pas.y0 + 4 + rnd(k + 50) * (pas.y1 - pas.y0 - 8), tx: 0, ty: 0, t: 0, kind: k % 4 === 3 ? "sheep" : "cow" }));
    const hens = Array.from({ length: 6 }, (_, k) => ({ x: bx + 4 + k * 3, y: by + 23, tx: 0, ty: 0, t: 0 }));
    eng.current = { cv, ctx, proj, fcv, fg, fb: { x0: fx0, y0: fy0, mpp: mppF, W: FW, H: FH }, rects, toF, tileKey, agents: [], parts: [], pas, herd, hens, compostAt,
      barn: [bx + 12, by + 46], roadY: by + 22, cam: { x: fx0 + FW * mppF / 2, y: fy0 + FH * mppF / 2, s: 0.05, tx: null } };
    const E = eng.current;
    const resize = () => { cv.width = cv.clientWidth * devicePixelRatio; cv.height = cv.clientHeight * devicePixelRatio; };
    resize(); addEventListener("resize", resize);

    E.flyTo = (x, y, s, ms = 1600) => { E.cam.tx = { x0: E.cam.x, y0: E.cam.y, s0: E.cam.s, x, y, s, t0: performance.now(), ms }; };
    // fit the farm into the space left between the tool panel (left), top bar and footer
    E.flyFarm = (ms) => { const L = 290, T = 64, B = 205, availW = cv.clientWidth - L - 20, availH = cv.clientHeight - T - B;
      const s = Math.min(availW / (FW * mppF), availH / (FH * mppF)) * 0.97;
      const cx = fx0 + FW * mppF / 2 - (L - 20) / 2 / s, cy = fy0 + FH * mppF / 2 - (T - B) / 2 / s; E.flyTo(cx, cy, s, ms); };
    E.flyFarm(1); const t = setTimeout(() => E.flyFarm(1), 50);
    // ---- farm machines: drive from the barn along the farm road, work the field, drive back
    E.dispatch = (kind, id, onDone) => {
      const r = rects[id]; if (!r) return;
      const [x, y] = toF(r.x, r.y); const [bx0, by0] = kind === "compost" ? E.compostAt : E.barn; const ry = E.roadY;
      const work = [];
      for (let k = 0; k < 4; k++) { const yy = y + 3 + k * 6; work.push(k % 2 ? [x + FP - 3, yy, 1] : [x + 2, yy, 1], k % 2 ? [x + 2, yy, 1] : [x + FP - 3, yy, 1]); }
      const path = [[bx0, by0, 0], [bx0, ry, 0], [x - 2, ry, 0], [x - 2, y + 3, 0], ...work, [x - 2, y + FP - 3, 0], [x - 2, ry, 0], [bx0, ry, 0], [bx0, by0, 0]];
      E.agents.push({ kind, id, path, i: 0, x: bx0, y: by0, done: onDone, dir: 1 });
    };
    if (apiRef) apiRef.current = { dispatch: (...a) => E.dispatch(...a), busy: () => E.agents.length };

    // ---- interaction (box select with the select tool)
    const s2w = (px, py) => [(px - cv.clientWidth / 2) / E.cam.s + E.cam.x, (py - cv.clientHeight / 2) / E.cam.s + E.cam.y];
    const fieldAt = (px, py) => { const [x, y] = s2w(px, py); for (const id in rects) { const r = rects[id]; if (x >= r.x && x < r.x + r.w && y >= r.y && y < r.y + r.h) return id; } return null; };
    let drag = null;
    const pos = (e) => { const b = cv.getBoundingClientRect(); return [e.clientX - b.left, e.clientY - b.top]; };
    const down = (e) => { const [px, py] = pos(e); const id = fieldAt(px, py); const L = live.current;
      if (L.tool === "select" && !e.shiftKey) { drag = { box: true, x0: px, y0: py, x1: px, y1: py }; E.box = drag; return; }
      if (L.tool !== "inspect" && id && !e.shiftKey) { drag = { paint: true, done: new Set([id]) }; L.onPaint(id, true); return; }
      drag = { x: px, y: py, cx: E.cam.x, cy: E.cam.y, moved: false }; };
    const move = (e) => { const [px, py] = pos(e); E.hover = fieldAt(px, py); if (!drag) return;
      if (drag.box) { drag.x1 = px; drag.y1 = py; return; }
      if (drag.paint) { if (E.hover && !drag.done.has(E.hover)) { drag.done.add(E.hover); live.current.onPaint(E.hover, false); } return; }
      const dx = px - drag.x, dy = py - drag.y; if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true; E.cam.tx = null; E.cam.x = drag.cx - dx / E.cam.s; E.cam.y = drag.cy - dy / E.cam.s; };
    const up = (e) => {
      if (drag && drag.box) { const [ax, ay] = s2w(Math.min(drag.x0, drag.x1), Math.min(drag.y0, drag.y1)); const [bx2, by2] = s2w(Math.max(drag.x0, drag.x1), Math.max(drag.y0, drag.y1));
        let ids = Object.keys(rects).filter((k) => { const r = rects[k]; return r.x < bx2 && r.x + r.w > ax && r.y < by2 && r.y + r.h > ay; });
        if (Math.abs(drag.x1 - drag.x0) + Math.abs(drag.y1 - drag.y0) < 4) { const id = fieldAt(drag.x0, drag.y0); ids = id ? [id] : []; }
        live.current.onPick(ids, e.shiftKey); drag = null; E.box = null; return; }
      if (drag && !drag.paint && !drag.moved) { const [px, py] = pos(e); const id = fieldAt(px, py); if (id) live.current.onSelect(id); } drag = null; };
    const wheel = (e) => { e.preventDefault(); E.cam.tx = null; const [px, py] = pos(e); const [wx, wy] = s2w(px, py); E.cam.s = Math.min(3, Math.max(0.0004, E.cam.s * Math.exp(-e.deltaY * 0.0015))); const [nx, ny] = s2w(px, py); E.cam.x += wx - nx; E.cam.y += wy - ny; };
    cv.addEventListener("mousedown", down); addEventListener("mousemove", move); addEventListener("mouseup", up); cv.addEventListener("wheel", wheel, { passive: false });

    // ---- render loop
    let raf, tPrev = performance.now();
    const drops = Array.from({ length: 160 }, (_, i) => ({ x: rnd(i), y: rnd(i + 99), v: 0.6 + rnd(i + 7) * 0.6 }));
    const frame = (t) => {
      const dt = (t - tPrev) / 1000; tPrev = t;
      const cam = E.cam, d = devicePixelRatio, L = live.current;
      if (cam.tx) { const k = Math.min(1, (t - cam.tx.t0) / cam.tx.ms), e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
        cam.s = Math.exp(Math.log(cam.tx.s0) + (Math.log(cam.tx.s) - Math.log(cam.tx.s0)) * e); cam.x = cam.tx.x0 + (cam.tx.x - cam.tx.x0) * e; cam.y = cam.tx.y0 + (cam.tx.y - cam.tx.y0) * e; if (k >= 1) cam.tx = null; }
      const w2s = (x, y) => [((x - cam.x) * cam.s + cv.clientWidth / 2) * d, ((y - cam.y) * cam.s + cv.clientHeight / 2) * d];
      // refresh changed field tiles
      const FS = L.fieldState || {};
      if (E.spriteEpoch !== spriteEpoch.current) { E.spriteEpoch = spriteEpoch.current; for (const id in tileKey) delete tileKey[id]; }
      for (const id in rects) { const st = FS[id] || {}; const stageN = st.crop ? (st.progress < 0.35 ? 0 : st.progress < 0.7 ? 1 : 2) : (st.cover ? 1 : null);
        const spriteName = st.crop ? `${st.crop}_${stageN}` : (st.cover ? "vetch_cover_1" : null);
        const key = `${st.crop ?? "-"}|${st.crop ? stageN + (st.progress > 0.85 ? "r" : "") : ""}|${st.water ?? 1}|${st.ph != null && st.ph < 6 ? "acid" : ""}|${st.pests > 55 ? "bugs" : ""}|${st.cover ? "cover" : ""}|${spriteName && spritesRef.current[spriteName] ? "s" : ""}`;
        if (tileKey[id] !== key) { tileKey[id] = key; const [x, y] = toF(rects[id].x, rects[id].y); drawFieldTile(fg, x, y, hash(id), st.crop ?? (st.cover ? "vetch_cover" : null), st.crop ? st.progress ?? 0 : 0.6, st.water ?? 1, spriteName ? spritesRef.current[spriteName] : null);
          if (st.pests > 55) { for (let k = 0; k < 14; k++) { fg.fillStyle = k % 3 ? "#2b1d14" : "#7a3d12"; fg.fillRect(x + 1 + Math.floor(rnd(hash(id) * 11 + k) * (FP - 2)), y + 1 + Math.floor(rnd(hash(id) * 5 + k * 7) * (FP - 2)), 1, 1); } }
          if (st.ph != null && st.ph < 6) { for (let k = 0; k < 40; k++) { fg.fillStyle = rnd(hash(id) + k) < 0.5 ? "#d8d26a" : "#b9b45a"; fg.fillRect(x + Math.floor(rnd(hash(id) * 7 + k) * FP), y + Math.floor(rnd(hash(id) * 3 + k * 5) * FP), 1, 1); } } } }
      ctx.imageSmoothingEnabled = false;
      const scF = mppF * cam.s * d;
      // close in, the land around the farm is grass; far out, the valley map fades in
      ctx.fillStyle = PAL.grass; ctx.fillRect(0, 0, cv.width, cv.height);
      const [sx, sy] = w2s(fx0, fy0); ctx.drawImage(fcv, sx, sy, FW * scF, FH * scF);
      // overlays
      const fpx = FP * scF;
      if (fpx > 8) for (const id in rects) {
        const r = rects[id], st = FS[id] || {}; const [x, y] = w2s(r.x, r.y); const w = r.w * cam.s * d, h = r.h * cam.s * d;
        if (st.health != null && st.crop && w > 26) { const hb = Math.max(3, w / 18); ctx.fillStyle = "rgba(43,29,20,.7)"; ctx.fillRect(x + 3 * d, y + 3 * d, w - 6 * d, hb);
          ctx.fillStyle = st.health > 70 ? "#6abe30" : st.health > 40 ? "#fbd34d" : "#d03b3b"; ctx.fillRect(x + 3 * d, y + 3 * d, (w - 6 * d) * st.health / 100, hb); }
        if (st.badges && st.badges.length && w > 40) { const bs = Math.min(18, w / 5) * 1; st.badges.forEach((b, k) => { ctx.fillStyle = "rgba(255,246,220,.92)"; ctx.fillRect(x + w - (k + 1) * (bs + 2 * d) - 2 * d, y + h - bs - 4 * d, bs, bs); ctx.font = `${Math.round(bs * 0.75)}px sans-serif`; ctx.fillText(b, x + w - (k + 1) * (bs + 2 * d) - 2 * d + bs * 0.1, y + h - 4 * d - bs * 0.2); }); }
        if (st.stress) { ctx.fillStyle = "rgba(208,59,59,0.22)"; ctx.fillRect(x, y, w, h); }
        if ((st.review || st.stress) && w > 18 && Math.floor(t / 500) % 2 === 0) { const s = Math.min(w, h) * 0.2; ctx.fillStyle = "#fff"; ctx.strokeStyle = "#d03b3b"; ctx.lineWidth = 2 * d; ctx.beginPath(); ctx.moveTo(x + w * 0.2, y + h * 0.2 - s); ctx.lineTo(x + w * 0.2 + s, y + h * 0.2 + s * 0.8); ctx.lineTo(x + w * 0.2 - s, y + h * 0.2 + s * 0.8); ctx.closePath(); ctx.fill(); ctx.stroke(); ctx.fillStyle = "#d03b3b"; ctx.fillRect(x + w * 0.2 - s * 0.08, y + h * 0.2 - s * 0.45, s * 0.16, s * 0.75); }
        if (st.irrigating && w > 30) { ctx.strokeStyle = "rgba(203,241,245,.8)"; ctx.lineWidth = 2 * d; const ph3 = (t / 400) % (Math.PI * 2);
          for (let k = 0; k < 2; k++) { const cx = x + w * (0.3 + 0.4 * k), cy = y + h * 0.55; ctx.beginPath(); ctx.arc(cx, cy, w * 0.18, ph3 + k, ph3 + k + 1.2); ctx.stroke(); } }
        if (st.irrigating && w > 30) { ctx.fillStyle = PAL.foam; for (let i = 0; i < 4; i++) { const k = Math.floor(t / 180 + i * 7 + hash(id)); ctx.fillRect(x + w * rnd(k), y + h * rnd(k * 3 + 1), 3 * d, 3 * d); } }
        if (w > 70 && st.supply != null) { ctx.font = `${Math.round(Math.min(14, w / 9)) * d}px "VT323", monospace`; const label = `${Math.round(st.supply)}cm`; const tw = ctx.measureText(label).width; ctx.fillStyle = "rgba(43,29,20,.75)"; ctx.fillRect(x + 4 * d, y + h - 18 * d, tw + 6 * d, 14 * d); ctx.fillStyle = PAL.foam; ctx.fillText(label, x + 7 * d, y + h - 7 * d); }
      }
      if (L.selected && rects[L.selected]) { const r = rects[L.selected]; const [x, y] = w2s(r.x, r.y); ctx.strokeStyle = Math.floor(t / 250) % 2 ? "#fff" : "#ffd76a"; ctx.lineWidth = 4 * d; ctx.strokeRect(x - 3 * d, y - 3 * d, r.w * cam.s * d + 6 * d, r.h * cam.s * d + 6 * d); }
      if (E.hover && rects[E.hover] && L.tool !== "inspect") { const r = rects[E.hover]; const [x, y] = w2s(r.x, r.y); ctx.strokeStyle = "#fff"; ctx.setLineDash([6 * d, 4 * d]); ctx.lineWidth = 2 * d; ctx.strokeRect(x, y, r.w * cam.s * d, r.h * cam.s * d); ctx.setLineDash([]); }
      // picked fields (area selection)
      if (L.picked && L.picked.length) { ctx.setLineDash([5 * d, 3 * d]); ctx.lineWidth = 3 * d; ctx.strokeStyle = "#ffd76a";
        for (const id of L.picked) { const r = rects[id]; if (!r) continue; const [x, y] = w2s(r.x, r.y); ctx.strokeRect(x + 2 * d, y + 2 * d, r.w * cam.s * d - 4 * d, r.h * cam.s * d - 4 * d); }
        ctx.setLineDash([]); }
      if (E.box) { const b = E.box; ctx.fillStyle = "rgba(255,215,106,0.18)"; ctx.strokeStyle = "#ffd76a"; ctx.lineWidth = 2 * d;
        ctx.fillRect(Math.min(b.x0, b.x1) * d, Math.min(b.y0, b.y1) * d, Math.abs(b.x1 - b.x0) * d, Math.abs(b.y1 - b.y0) * d);
        ctx.strokeRect(Math.min(b.x0, b.x1) * d, Math.min(b.y0, b.y1) * d, Math.abs(b.x1 - b.x0) * d, Math.abs(b.y1 - b.y0) * d); }
      const a2s = (ax, ay) => w2s(fx0 + ax * mppF, fy0 + ay * mppF);
      // compost pile grows with the farm's compost
      { const loads = L.compost || 0; const pile = spritesRef.current.compost;
        if (pile) { const s = Math.min(18, 8 + loads / 5) * scF; const [cx2, cy2] = a2s(E.compostAt[0] - 4, E.compostAt[1] - 6); ctx.drawImage(pile, cx2, cy2, s, s); }
        else { const ph2 = Math.min(6, 1 + loads / 7); const [cx2, cy2] = a2s(E.compostAt[0] - 5, E.compostAt[1] - ph2);
          for (let k = 0; k < ph2; k++) { ctx.fillStyle = k % 2 ? "#6b4a2b" : "#8a6238"; ctx.fillRect(cx2 + k * scF, cy2 + k * scF, (10 - 2 * k) * scF, scF); } } }
      // herd and hens wander
      const nCow = Math.min(E.herd.length, Math.round((L.cows || 0) / 2));
      const wander = (a, x0, y0, x1, y1) => { a.t -= dt; if (a.t <= 0) { a.tx = x0 + Math.random() * (x1 - x0); a.ty = y0 + Math.random() * (y1 - y0); a.t = 2 + Math.random() * 5; }
        const dx = a.tx - a.x, dy = a.ty - a.y, dd = Math.hypot(dx, dy); if (dd > 0.5) { a.x += dx / dd * dt * 2.5; a.y += dy / dd * dt * 2.5; a.dir = dx > 0 ? 1 : -1; } };
      for (let k = 0; k < nCow; k++) { const a = E.herd[k]; wander(a, E.pas.x0 + 3, E.pas.y0 + 3, E.pas.x1 - 6, E.pas.y1 - 5);
        const [ax, ay] = a2s(a.x, a.y); const u = scF; const animal = spritesRef.current[a.kind];
        if (animal) { const w = 8 * u; ctx.save(); if (a.dir < 0) { ctx.translate(ax + w, ay); ctx.scale(-1, 1); ctx.drawImage(animal, 0, 0, w, w); } else ctx.drawImage(animal, ax, ay, w, w); ctx.restore(); }
        else { const f2 = (cx, cy, w2, h2, c) => { ctx.fillStyle = c; ctx.fillRect(ax + (a.dir > 0 ? cx : 6 - cx - w2) * u, ay + cy * u, w2 * u, h2 * u); };
          if (a.kind === "sheep") { f2(0, 0, 4, 3, "#f4f4f0"); f2(4, 1, 2, 2, "#2b1d14"); f2(1, 3, 1, 1, "#2b1d14"); f2(3, 3, 1, 1, "#2b1d14"); }
          else { f2(0, 0, 5, 3, "#ffffff"); f2(1, 0, 2, 1, "#2b1d14"); f2(3, 1, 1, 2, "#2b1d14"); f2(5, 0, 2, 2, "#e8b4a0"); f2(0, 3, 1, 1, "#2b1d14"); f2(4, 3, 1, 1, "#2b1d14"); } } }
      for (const a of E.hens) { wander(a, E.barn[0] - 10, E.roadY - 4, E.barn[0] + 10, E.roadY + 2); const [ax, ay] = a2s(a.x, a.y); const hen = spritesRef.current.chicken;
        if (hen) { const w = 6 * scF; ctx.save(); if (a.dir < 0) { ctx.translate(ax + w, ay); ctx.scale(-1, 1); ctx.drawImage(hen, 0, 0, w, w); } else ctx.drawImage(hen, ax, ay, w, w); ctx.restore(); }
        else { ctx.fillStyle = "#fff"; ctx.fillRect(ax, ay, 2 * scF, 2 * scF); ctx.fillStyle = "#d43f3f"; ctx.fillRect(ax + (a.dir > 0 ? 2 : -1) * scF, ay, scF, scF); } }
      // machines
      const spd = 34 * (L.speed || 1);
      E.agents = E.agents.filter((a) => {
        let budget = spd * dt;
        while (budget > 0 && a.i < a.path.length) { const [tx, ty, wk] = a.path[a.i]; const dx = tx - a.x, dy = ty - a.y, dist = Math.hypot(dx, dy);
          a.working = !!wk && a.i > 0 && a.path[a.i - 1][2];
          if (dist <= budget) { a.x = tx; a.y = ty; a.i++; budget -= dist; } else { a.x += (dx / dist) * budget; a.y += (dy / dist) * budget; budget = 0; }
          if (Math.abs(dx) > 0.01) a.dir = dx > 0 ? 1 : -1; }
        if (a.working && Math.random() < 0.9) for (let k = 0; k < 3; k++) E.parts.push({ x: a.x - a.dir * 3 + (Math.random() - 0.5) * 6, y: a.y + (Math.random() - 0.5) * 6, vx: (Math.random() - 0.5) * 6, vy: -4 - Math.random() * 6, life: 0.7, kind: a.kind });
        if (a.i >= a.path.length) { a.done && a.done(); return false; }
        return true; });
      E.parts = E.parts.filter((p) => (p.life -= dt) > 0);
      for (const p of E.parts) { p.x += p.vx * dt; p.y += p.vy * dt; const [px2, py2] = a2s(p.x, p.y); ctx.globalAlpha = Math.max(0, p.life / 0.7);
        ctx.fillStyle = { lime: "#ffffff", harvest: "#e2c25a", water: "#5fcde4", spray: "#9be36a", compost: "#5a3a22", synthetic: "#cfe6ff", seed: "#c9a24a", plant: "#a07040" }[p.kind] || "#a07040"; ctx.fillRect(px2, py2, Math.max(2, scF * 0.9), Math.max(2, scF * 0.9)); }
      ctx.globalAlpha = 1;
      for (const a of E.agents) {
        const u = scF; const [ax, ay] = a2s(a.x - 4, a.y - 3);
        const machineName = a.kind === "spray" ? "sprayer" : a.kind === "harvest" ? "harvester" : "tractor";
        const machine = spritesRef.current[machineName];
        if (machine) { const w = 12 * u; ctx.save(); if (a.dir < 0) { ctx.translate(ax + w, ay); ctx.scale(-1, 1); ctx.drawImage(machine, 0, 0, w, w); } else ctx.drawImage(machine, ax, ay, w, w); ctx.restore(); }
        else { const px = (cx, cy, w, h, c) => { ctx.fillStyle = c; ctx.fillRect(ax + (a.dir > 0 ? cx : 8 - cx - w) * u, ay + cy * u, w * u, h * u); };
          if (a.kind === "lime" || a.kind === "spray" || a.kind === "synthetic") { px(0, 1, 5, 3, a.kind === "spray" ? "#3e8e3e" : "#3b6fb6"); px(1, 0, 3, 1, "#dfe7f2"); px(5, 2, 3, 2, "#2d7d32"); px(6, 0, 2, 2, "#cfe6ff"); px(-3, 2, 3, 1, "#9badb7"); }
          else if (a.kind === "compost") { px(0, 1, 5, 3, "#6b4a2b"); px(0, 0, 5, 1, "#3a2414"); px(5, 2, 3, 2, "#c43c2c"); px(6, 0, 2, 2, "#cfe6ff"); }
          else if (a.kind === "harvest") { px(1, 0, 6, 4, "#c43c2c"); px(6, 0, 2, 2, "#cfe6ff"); px(-2, 1, 3, 3, "#e8c040"); }
          else { px(1, 1, 5, 3, "#2d8a3a"); px(5, 0, 2, 2, "#cfe6ff"); px(-1, 2, 2, 1, "#8f563b"); }
          px(1, 4, 2, 2, "#1d1d1d"); px(5, 4, 2, 2, "#1d1d1d"); }
      }
      // weather
      const W = L.fieldState?.__weather;
      if (W && W.rain_mm > 20 && scF > 0.5) { const n = Math.min(drops.length, Math.round(W.rain_mm * 1.2)); ctx.strokeStyle = "rgba(203,241,245,.7)"; ctx.lineWidth = 2 * d; ctx.beginPath(); for (let i = 0; i < n; i++) { const p = drops[i]; p.y += p.v * dt * 1.2; p.x -= dt * 0.15; if (p.y > 1) { p.y = 0; p.x = rnd(i + t) * 1.2; } if (p.x < 0) p.x += 1.2; const x = p.x * cv.width, y = p.y * cv.height; ctx.moveTo(x, y); ctx.lineTo(x - 4 * d, y + 12 * d); } ctx.stroke(); }
      if (W && W.heat_days > 8 && scF > 0.5) { ctx.fillStyle = `rgba(255,120,40,${Math.min(0.16, W.heat_days / 160)})`; ctx.fillRect(0, 0, cv.width, cv.height); }
      if (W && W.frost_days > 3 && scF > 0.5) { ctx.fillStyle = `rgba(230,242,255,${Math.min(0.25, W.frost_days / 50)})`; ctx.fillRect(0, 0, cv.width, cv.height); }
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => { cancelAnimationFrame(raf); clearTimeout(t); removeEventListener("resize", resize); removeEventListener("mousemove", move); removeEventListener("mouseup", up); cv.removeEventListener("mousedown", down); cv.removeEventListener("wheel", wheel); };
  }, [farm]);

  // external camera commands
  useEffect(() => { if (!focus || !eng.current) return; if (focus.kind === "farm") eng.current.flyFarm(900);
    if (focus.kind === "in" || focus.kind === "out") { const c = eng.current.cam; eng.current.flyTo(c.x, c.y, focus.kind === "in" ? Math.min(3, c.s * 2) : Math.max(0.0004, c.s / 2), 300); } }, [focus]);

  return <canvas ref={ref} className={`world ${tool !== "inspect" ? "painting" : ""}`} />;
}
