import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getJSON } from "./api";
import FarmMap from "./components/FarmMap";
import FieldStage from "./components/FieldStage";

// One farm, run like a god sim (Hay Day x WorldBox). Every season Drex looks
// at each field and decides its actions: irrigate, fertilize (compost or
// synthetic), lime, spray, sow a cover crop. Code hands out the farm's limited
// resources. Animals turn crop residue into manure, manure and residue become
// compost, compost feeds the fields: a circular, sustainable farm that still
// has to produce.
const SPEEDS = [{ label: "1×", ms: 650, v: 1 }, { label: "2×", ms: 320, v: 2 }, { label: "4×", ms: 140, v: 4 }];
const MODEL_LABEL = { drex: "Drex", llm: "LLM", rules: "Rule-based stand-in" };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const CASH = ["processing_tomato", "winter_wheat", "safflower"];
const CROP_SHORT = { processing_tomato: "Tomato", winter_wheat: "Wheat", safflower: "Safflower", vetch_cover: "Vetch" };
const CROP_SW = { processing_tomato: "#d43f3f", winter_wheat: "#fbd34d", safflower: "#f59f22", vetch_cover: "#9d5ccf" };
const STEP_CM = 10;
const ACTION_ICON = { compost: "♻", synthetic: "🧪", lime: "🪨", spray_pests: "🐛", cover_crop: "🌱" };
const ACTION_LABEL = { compost: "Compost", synthetic: "Synthetic N", lime: "Lime", spray_pests: "Spray pests", cover_crop: "Cover crop" };
const MACHINE = { compost: "compost", synthetic: "synthetic", lime: "lime", spray_pests: "spray", cover_crop: "seed" };

const SCENARIOS = [
  { key: "replay", label: "Drought replay", note: "Real 2012-2021 NASA weather", preset: "Drought replay" },
  { key: "normal", label: "Normal years", note: "Average climate", preset: "Today" },
  { key: "dry", label: "Dry decade", note: "-30% rain, +0.5 °C", preset: "Dry decade" },
  { key: "heat", label: "Heat wave", note: "+2 °C summers", preset: "Hotter summers" },
  { key: "cut", label: "Water cutback", note: "Surface water at 60%", preset: "Drought replay", pool: 60 },
  { key: "acid", label: "Acid patch", note: "pH 5.3 on a 3×3 block", preset: "Today", acid: true },
  { key: "pests", label: "Pest outbreak", note: "Heavy pests on 8 fields", preset: "Today", pests: true },
  { key: "organic", label: "Go organic", note: "No synthetic N, 40 cows", preset: "Today", stock: { synthetic: 0 }, cows: 40 },
];

async function* streamRun(body, signal) {
  const r = await fetch("/api/farm/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal });
  if (!r.ok) { let d = `HTTP ${r.status}`; try { d = (await r.json()).detail ?? d; } catch { /* not JSON */ } throw new Error(typeof d === "string" ? d : JSON.stringify(d)); }
  const reader = r.body.getReader(); const dec = new TextDecoder(); let buf = "";
  for (;;) { const { value, done } = await reader.read(); if (done) break; buf += dec.decode(value, { stream: true });
    let nl; while ((nl = buf.indexOf("\n")) >= 0) { const line = buf.slice(0, nl).trim(); buf = buf.slice(nl + 1); if (line) yield JSON.parse(line); } }
  if (buf.trim()) yield JSON.parse(buf);
}

const fmtMoney = (v) => (Math.abs(v) >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : `$${Math.round(v / 1000)}k`);

export default function App() {
  const [meta, setMeta] = useState(null);
  const [farm, setFarm] = useState(null);
  const [error, setError] = useState(null);
  const [model, setModel] = useState(null);
  const [scenario, setScenario] = useState("replay");
  const [preset, setPreset] = useState("Drought replay");
  const [rain, setRain] = useState(0);
  const [temp, setTemp] = useState(0);
  const [gw, setGw] = useState(0);
  const [prio, setPrio] = useState({ save_water: 0.5, income: 0.5, build_soil: 0.5 });
  const [poolPct, setPoolPct] = useState(100);
  const [supply, setSupply] = useState({});
  const [ph, setPh] = useState({});
  const [pests, setPests] = useState({});
  const [cropPlan, setCropPlan] = useState({});
  const [stock, setStock] = useState({ lime: 6, synthetic: 10, spray_pests: 10, cover_crop: 12 });
  const [cows, setCows] = useState(24);
  const [tool, setTool] = useState("inspect");
  const [paintCrop, setPaintCrop] = useState("winter_wheat");
  const [picked, setPicked] = useState([]);
  const [seasons, setSeasons] = useState([]);
  const [status, setStatus] = useState("loading");
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState(0);
  const [selected, setSelected] = useState(null);
  const [focus, setFocus] = useState(null);
  const [toast, setToast] = useState(null);
  const abortRef = useRef(null);
  const toastT = useRef(null);
  const mapApi = useRef(null);
  const say = (m) => { setToast(m); clearTimeout(toastT.current); toastT.current = setTimeout(() => setToast(null), 3200); };

  useEffect(() => {
    Promise.all([getJSON("/api/meta"), getJSON("/api/farm")])
      .then(([m, f]) => {
        setMeta(m); setFarm(f);
        setModel(m.models.drex ? "drex" : "rules");
        setSupply(Object.fromEntries(f.fields.map((x) => [x.id, f.default_supply_cm])));
        setPh(Object.fromEntries(f.fields.map((x) => [x.id, x.soil.ph ?? 7.0])));
      })
      .catch((e) => setError(`Can't reach the API (${e.message}). Start it with: uv run uvicorn server.app:app --port 8000`));
  }, []);

  const def = farm?.default_supply_cm ?? 40;
  const nF = farm?.fields.length ?? 36;
  const pool = def * nF * poolPct / 100;
  const allocated = Object.values(supply).reduce((a, b) => a + b, 0);
  const free = pool - allocated;

  // ---- run (debounced on every change); the farm keeps playing while it re-decides
  const run = useCallback(async (body) => {
    abortRef.current?.abort();
    const ctrl = new AbortController(); abortRef.current = ctrl;
    setStatus("running"); setError(null);
    const fresh = []; let first = true;
    try {
      for await (const msg of streamRun(body, ctrl.signal)) {
        if (msg.type === "season") { fresh.push(msg); if (first || fresh.length % 4 === 0) setSeasons([...fresh]); first = false; }
        else if (msg.type === "done") { setSeasons([...fresh]); setStatus("done"); say(`${MODEL_LABEL[body.model]} decided ${nF} fields × ${fresh.length} seasons (${(nF * fresh.length).toLocaleString()} decisions) in ${(msg.total_ms / 1000).toFixed(2)}s`); }
        else if (msg.type === "error") { setStatus("error"); setError(msg.message); }
      }
    } catch (e) { if (e.name !== "AbortError") { setStatus("error"); setError(e.message); } }
  }, [nF]);

  useEffect(() => {
    if (!meta || !farm || !model || !Object.keys(supply).length) return undefined;
    const t = setTimeout(() => {
      const body = { supply_cm: supply, ph, pests, crops: cropPlan, stock, cows, preset, rain_pct: rain, temp_delta_c: temp, gw_offset_cm_yr: gw, priorities: prio, model, years: 10 };
      if (model === "llm") {
        if (!window.confirm(`The LLM baseline is paid: about $${(meta.llm_usd_per_call * nF * 40).toFixed(2)} for this run (${nF * 40} calls). Run it?`)) { setModel(meta.models.drex ? "drex" : "rules"); return; }
        body.confirm_paid = true;
      }
      run(body);
    }, 450);
    return () => clearTimeout(t);
  }, [meta, farm, model, supply, ph, pests, cropPlan, stock, cows, preset, rain, temp, gw, prio, run, nF]);

  const nMonths = seasons.length * 3;
  useEffect(() => {
    if (!playing || !nMonths) return undefined;
    const t = setInterval(() => setIndex((i) => (i < nMonths - 1 ? i + 1 : status === "done" ? 0 : i)), SPEEDS[speed].ms);
    return () => clearInterval(t);
  }, [playing, nMonths, speed, status]);

  const i = Math.min(index, Math.max(0, nMonths - 1));
  const si = Math.floor(i / 3);
  const season = seasons[si];
  const month = season ? season.q * 3 + (i % 3) : 0; // 0-11
  const label = season ? `${MONTHS[month]} ${season.year}` : "…";
  const monthWx = season ? farm?.monthly?.[String(season.year)]?.[month] : null;

  const cropAt = useCallback((crop, m) => {
    const ms = meta?.crops?.[crop]?.months; if (!ms) return null;
    const k = ms.indexOf(m + 1); if (k < 0) return null;
    return { key: crop, progress: ms.length > 1 ? k / (ms.length - 1) : 1, first: k === 0, last: k === ms.length - 1 };
  }, [meta]);

  // ---- machines at the start of each season, harvesters at harvest months
  const lastI = useRef(-1);
  useEffect(() => {
    if (!season || lastI.current === i) return; lastI.current = i;
    const api = mapApi.current; if (!api) return;
    const jobs = [];
    if (i % 3 === 0) for (const [id, r] of Object.entries(season.cells)) for (const k of Object.keys(MACHINE)) if (r.actions[k]) jobs.push([MACHINE[k], id]);
    for (const [id, r] of Object.entries(season.cells)) { const c = cropAt(r.crop, month); if (c?.last) jobs.push(["harvest", id]); else if (c?.first) jobs.push(["plant", id]); }
    jobs.sort(() => Math.random() - 0.5).slice(0, Math.max(0, 9 - api.busy())).forEach(([k, id], n) => setTimeout(() => api.dispatch(k, id), n * 260));
  }, [i, season, month, cropAt]);

  // ---- what the map shows
  const fieldState = useMemo(() => {
    const st = {};
    if (!farm) return st;
    for (const f of farm.fields) {
      const r = season?.cells[f.id];
      const crop = r ? r.crop : cropPlan[f.id] || f.crop;
      const c = cropAt(crop, month);
      const badges = r ? Object.keys(ACTION_ICON).filter((k) => r.actions[k]).map((k) => ACTION_ICON[k]) : [];
      st[f.id] = { crop: c?.key ?? null, progress: c?.progress ?? 0, cover: !c && r?.actions.cover_crop,
        water: r ? (r.moisture / Math.max(1, r.cap) < 0.2 && !c ? 0 : r.irrigation_cm > 0 && c ? 2 : r.moisture / Math.max(1, r.cap) < 0.15 ? 0 : 1) : 1,
        irrigating: !!(r && c && r.irrigation_cm > 0), ph: r ? r.ph : ph[f.id], pests: r ? r.pests : pests[f.id] ?? 10,
        health: r && c ? r.health : null, supply: supply[f.id] ?? def, review: r?.review, stress: r && c && r.stress > 0.3, badges };
    }
    st.__weather = monthWx;
    return st;
  }, [farm, season, month, cropPlan, cropAt, ph, pests, supply, def, monthWx]);

  // ---- god tools
  const paint = useCallback((id) => {
    if (tool === "plant") { setCropPlan((p) => ({ ...p, [id]: paintCrop })); return; }
    if (tool !== "water_add" && tool !== "water_cut") return;
    setSupply((s) => {
      const cur = s[id] ?? def; const used = Object.values(s).reduce((a, b) => a + b, 0);
      if (tool === "water_add") { if (pool - used < STEP_CM - 1e-6) { say("No water left in the farm's pool. Cut another field or raise the supply."); return s; } return { ...s, [id]: Math.min(120, cur + STEP_CM) }; }
      return { ...s, [id]: Math.max(0, cur - STEP_CM) };
    });
  }, [tool, def, pool, paintCrop]);
  const setPool = (pct) => { const newPool = def * nF * pct / 100; const scale = allocated > 0 ? newPool / pool : 1; setPoolPct(pct);
    setSupply((s) => Object.fromEntries(Object.entries(s).map(([k, v]) => [k, Math.round(Math.min(120, v * scale) * 10) / 10]))); };
  const setPickedWater = (cm) => setSupply((s) => {
    const others = Object.entries(s).filter(([k]) => !picked.includes(k)).reduce((a, [, v]) => a + v, 0);
    const per = Math.max(0, Math.min(120, cm, (pool - others) / Math.max(1, picked.length)));
    if (per < cm - 0.5) say(`Only ${Math.round(per)} cm each fits in the farm's water pool.`);
    return { ...s, ...Object.fromEntries(picked.map((k) => [k, Math.round(per)])) };
  });
  const baseFarm = () => ({ ph: Object.fromEntries(farm.fields.map((x) => [x.id, x.soil.ph ?? 7.0])) });
  const resetFarm = () => { setPoolPct(100); setSupply(Object.fromEntries(farm.fields.map((x) => [x.id, def]))); setPh(baseFarm().ph); setPests({}); setCropPlan({});
    setStock({ lime: 6, synthetic: 10, spray_pests: 10, cover_crop: 12 }); setCows(24); setPicked([]); };
  const playScenario = (sc) => {
    const p = meta.presets[sc.preset];
    setScenario(sc.key); setPreset(sc.preset); setRain(p.rain_pct); setTemp(p.temp_delta_c); setGw(p.gw_offset_cm_yr);
    const ph0 = baseFarm().ph, pe = {};
    let block = [];
    if (sc.acid) { block = farm.fields.filter((f) => f.row >= 1 && f.row <= 3 && f.col <= 2).map((f) => f.id); block.forEach((k) => { ph0[k] = 5.3; }); }
    if (sc.pests) { block = farm.fields.filter((f) => f.row >= 3 && f.col >= 2 && f.col <= 5).map((f) => f.id); block.forEach((k) => { pe[k] = 85; }); }
    setPh(ph0); setPests(pe); setPicked(block);
    const pct = sc.pool ?? 100; setPoolPct(pct); setSupply(Object.fromEntries(farm.fields.map((x) => [x.id, def * pct / 100])));
    setStock({ lime: 6, synthetic: 10, spray_pests: 10, cover_crop: 12, ...(sc.stock || {}) }); setCows(sc.cows ?? 24);
    setIndex(0); setPlaying(true); say(`Scenario: ${sc.label}`);
  };

  if (error && !meta) return <div className="px-err"><div className="px-panel"><p className="px-title">Can't start</p><p>{error}</p></div></div>;
  if (!meta || !farm) return <div className="px-err"><div className="px-panel"><p className="px-title">Loading the farm…</p></div></div>;

  const F = season?.farm;
  const sc = F?.scores;
  const rec = selected && season?.cells[selected];
  const selField = selected && farm.fields.find((f) => f.id === selected);
  const avgPicked = (m, d0 = 0) => picked.reduce((a, k) => a + (m[k] ?? d0), 0) / Math.max(1, picked.length);
  const stageFrame = rec && {
    label, month: month + 1, year: rec.year, weather: monthWx || { ...rec.weather, rain_mm: rec.weather.rain_mm / 3 }, crop: cropAt(rec.crop, month), irrigation_cm: rec.irrigation_cm / 3,
    recharging: !cropAt(rec.crop, month) && (monthWx?.rain_mm ?? 0) >= 25, gw: F.aquifer_cm, soil: rec.soil,
  };

  return (
    <div className="px-app">
      <FarmMap farm={farm} fieldState={fieldState} selected={selected} picked={picked} tool={tool} speed={SPEEDS[speed].v} apiRef={mapApi}
               cows={cows} compost={F?.compost ?? 8}
               onPaint={paint} onSelect={(id) => setSelected(id)} onPick={(ids, add) => setPicked((p) => (add ? [...new Set([...p, ...ids])] : ids))} focus={focus} />

      <header className="px-panel px-top">
        <span className="px-logo">ROTATION ATLAS</span>
        <div className="px-res" title="Sustainability: soil, water from surface not aquifer, renewable inputs, waste recycled">🌍 {sc ? sc.sustainability : "–"}</div>
        <div className="px-res" title="Crop value per acre-inch of irrigation (illustrative prices)">⚙ {sc?.efficiency_usd_per_acre_in != null ? `$${sc.efficiency_usd_per_acre_in}/ac-in` : "–"}</div>
        <div className="px-res" title="Illustrative farm money">🪙 {F ? fmtMoney(F.coins) : "–"}</div>
        <div className="px-res" title="Unallocated surface water shares">💧 {Math.max(0, Math.round(free))}</div>
        <div className="px-res" title="Compost pile (loads) made from manure and crop residue">♻ {F ? F.compost.toFixed(0) : "–"}</div>
        <div className="px-res" title="Stock left this year: lime / synthetic N / pesticide / cover seed">🪨{F?.stock_left.lime ?? stock.lime} 🧪{F?.stock_left.synthetic ?? stock.synthetic} 🐛{F?.stock_left.spray_pests ?? stock.spray_pests} 🌱{F?.stock_left.cover_crop ?? stock.cover_crop}</div>
        <div className="px-res" title="Herd">🐄 {cows}</div>
        <span className="px-date">{label}</span>
        <div className="px-row">
          <button className="px-btn" onClick={() => setPlaying((p) => !p)} aria-label={playing ? "Pause" : "Play"}>{playing ? "❚❚" : "▶"}</button>
          {SPEEDS.map((s, k) => <button key={s.label} className={`px-btn ${speed === k ? "on" : ""}`} onClick={() => setSpeed(k)}>{s.label}</button>)}
        </div>
        <div className="px-row">
          {Object.entries(meta.models).filter(([, ok]) => ok).map(([m]) => (
            <button key={m} className={`px-btn ${model === m ? "on" : ""}`} onClick={() => setModel(m)}>{m === "rules" ? "Rules" : MODEL_LABEL[m]}</button>))}
        </div>
      </header>

      <aside className="px-panel px-tools">
        <p className="px-title">Scenarios</p>
        <div className="px-scen">
          {SCENARIOS.map((s) => <button key={s.key} className={`px-card-btn ${scenario === s.key ? "on" : ""}`} onClick={() => playScenario(s)}><b>{s.label}</b><span>{s.note}</span></button>)}
        </div>

        <p className="px-title">Tools</p>
        <div className="px-row">
          {[["inspect", "Inspect"], ["select", "Select area"], ["plant", "Plant"], ["water_add", "+ Water"], ["water_cut", "− Water"]].map(([k, l]) => (
            <button key={k} className={`px-btn ${tool === k ? "on" : ""}`} onClick={() => setTool(k)}>{l}</button>))}
        </div>
        {tool === "plant" && <div className="px-row" style={{ marginTop: 4 }}>{CASH.map((c) => (
          <button key={c} className={`px-btn sm ${paintCrop === c ? "on" : ""}`} onClick={() => setPaintCrop(c)}><i className="px-sw" style={{ background: CROP_SW[c] }} />{CROP_SHORT[c]}</button>))}</div>}
        <p className="px-hint">{{ inspect: "Click a field to open it. Drag to pan, scroll to zoom.", select: "Drag a box over fields (shift adds), then change them below.", plant: "Click or drag across fields to replant them.",
          water_add: `Click or drag: +${STEP_CM} cm/yr of water each.`, water_cut: `Click or drag: −${STEP_CM} cm/yr each.` }[tool]}</p>

        {picked.length > 0 && (
          <div className="px-selbox">
            <div className="px-row between"><b>{picked.length} field{picked.length > 1 ? "s" : ""} selected</b><button className="px-btn sm" onClick={() => setPicked([])}>Clear</button></div>
            <div className="px-lbl"><span>Water share each</span><span>{Math.round(avgPicked(supply, def))} cm/yr</span></div>
            <input type="range" min="0" max="100" step="5" value={Math.round(avgPicked(supply, def))} onChange={(e) => setPickedWater(+e.target.value)} />
            <div className="px-row">{CASH.map((c) => <button key={c} className="px-btn sm" onClick={() => setCropPlan((p) => ({ ...p, ...Object.fromEntries(picked.map((k) => [k, c])) }))}><i className="px-sw" style={{ background: CROP_SW[c] }} />{CROP_SHORT[c]}</button>)}</div>
            <div className="px-row" style={{ marginTop: 4 }}>
              <button className="px-btn sm" onClick={() => setPh((p) => ({ ...p, ...Object.fromEntries(picked.map((k) => [k, 5.3])) }))}>Acid soil (demo)</button>
              <button className="px-btn sm" onClick={() => setPests((p) => ({ ...p, ...Object.fromEntries(picked.map((k) => [k, 85])) }))}>Pest outbreak (demo)</button>
            </div>
          </div>
        )}

        <p className="px-title">Resources per year</p>
        <div className="px-lbl"><span>💧 Surface water</span><span>{poolPct}%</span></div>
        <input type="range" min="40" max="160" step="10" value={poolPct} onChange={(e) => setPool(+e.target.value)} />
        {[["lime", "🪨 Lime"], ["synthetic", "🧪 Synthetic N"], ["spray_pests", "🐛 Pesticide"], ["cover_crop", "🌱 Cover seed"]].map(([k, l]) => (
          <div key={k}><div className="px-lbl"><span>{l}</span><span>{stock[k]} fields</span></div>
            <input type="range" min="0" max="36" step="1" value={stock[k]} onChange={(e) => setStock((s) => ({ ...s, [k]: +e.target.value }))} /></div>))}
        <div className="px-lbl"><span>🐄 Herd</span><span>{cows} cows</span></div>
        <input type="range" min="0" max="80" step="4" value={cows} onChange={(e) => setCows(+e.target.value)} />
        <p className="px-hint">Cows eat crop residue and cover-crop grazing; manure and leftover residue become compost; {MODEL_LABEL[model]} can fertilize with compost instead of buying synthetic N.</p>

        <p className="px-title">Weather powers</p>
        <div className="px-lbl"><span>Rain</span><span>{rain > 0 ? "+" : ""}{rain}%</span></div>
        <input type="range" min="-50" max="50" step="5" value={rain} onChange={(e) => setRain(+e.target.value)} />
        <div className="px-lbl"><span>Heat</span><span>+{temp} °C</span></div>
        <input type="range" min="0" max="4" step="0.5" value={temp} onChange={(e) => setTemp(+e.target.value)} />
        <div className="px-lbl"><span>Aquifer trend</span><span>{gw > 0 ? "+" : ""}{gw} cm/yr</span></div>
        <input type="range" min="-3" max="3" step="0.5" value={gw} onChange={(e) => setGw(+e.target.value)} />

        <p className="px-title">Farmer wants</p>
        {[["save_water", "Save water"], ["income", "Income"], ["build_soil", "Build soil"]].map(([k, l]) => (
          <div key={k}><div className="px-lbl"><span>{l}</span><span>{Math.round(prio[k] * 100)}%</span></div>
            <input type="range" min="0" max="1" step="0.1" value={prio[k]} onChange={(e) => setPrio((p) => ({ ...p, [k]: +e.target.value }))} /></div>))}
        <button className="px-btn wide" onClick={resetFarm}>Reset farm</button>
      </aside>

      {selected && rec && (
        <aside className="px-panel px-card">
          <div className="px-row between"><p className="px-title">Field {selected} · {CROP_SHORT[rec.crop]} · {rec.season} {rec.year}</p><button className="px-btn" onClick={() => setSelected(null)}>×</button></div>
          <div className="px-stage"><FieldStage frame={stageFrame} meta={meta} /></div>
          <ActionCard rec={rec} model={MODEL_LABEL[model]} timing={season.timing} />
          <Gauges rec={rec} soilSrc={selField.soil.source} share={supply[selected] ?? def} />
        </aside>
      )}

      <footer className="px-panel px-bottom">
        {sc && <div className="px-scores">
          {[["soil", "Soil"], ["water", "Water from surface"], ["renewable_inputs", "Renewable inputs"], ["waste_recycled", "Waste recycled"]].map(([k, l]) => (
            <div key={k} className="px-score"><span>{l}</span><div className="px-bar"><i style={{ width: `${sc[k]}%`, background: sc[k] > 70 ? "#6abe30" : sc[k] > 40 ? "#fbd34d" : "#d03b3b" }} /></div><b>{sc[k]}</b></div>))}
        </div>}
        <div className="px-stat"><b>{F ? `${F.aquifer_cm > 0 ? "+" : ""}${F.aquifer_cm.toFixed(1)} cm` : "–"}</b><span>farm aquifer</span></div>
        <div className="px-stat"><b>{F ? `${F.feed_bought.toFixed(1)}` : "–"}</b><span>feed loads bought</span></div>
        <div className="px-stat"><b>{F ? Object.values(F.denied).reduce((a, b) => a + b, 0) : "–"}</b><span>requests over budget</span></div>
        <div className="px-stat"><b>{season ? `${season.timing.wall_ms.toFixed(0)} ms` : "–"}</b><span>{MODEL_LABEL[model]} · {nF} fields</span></div>
        {status === "running" && <span className="px-busy">re-deciding…</span>}
        <div className="px-row px-zoomrow">
          <button className="px-btn" onClick={() => setFocus({ kind: "in", t: Date.now() })} aria-label="Zoom in">+</button>
          <button className="px-btn" onClick={() => setFocus({ kind: "out", t: Date.now() })} aria-label="Zoom out">−</button>
          <button className="px-btn" onClick={() => setFocus({ kind: "farm", t: Date.now() })}>Fit farm</button>
        </div>
        <div className="px-strip" role="group" aria-label="Seasons">
          {seasons.map((s, k) => (
            <button key={k} className={`px-cell ${k === si ? "now" : ""}`} title={`${s.season} ${s.year}: sustainability ${s.farm.scores.sustainability}`}
                    style={{ background: s.farm.scores.sustainability > 80 ? "#6abe30" : s.farm.scores.sustainability > 60 ? "#fbd34d" : "#d03b3b", opacity: k > si ? 0.45 : 1 }}
                    onClick={() => { setIndex(k * 3); setPlaying(false); }}>{s.q === 0 ? String(s.year).slice(2) : ""}</button>))}
        </div>
        <p className="px-disclaimer">Illustrative what-if, not a forecast: prices, costs, herd and compost numbers are round illustrative values. Suggestions only; the farmer and advisor decide.
          {farm.fields.some((f) => f.soil.source === "estimate") ? " Soil is an estimate until scripts/build_farm.py pulls SSURGO." : ""}
          {meta.crops_placeholder ? " Crop facts are placeholders until the guide extraction runs." : ""}</p>
      </footer>

      {toast && <div className="px-toast">{toast}</div>}
      {error && <div className="px-toast err">{error}</div>}
    </div>
  );
}

function ActionCard({ rec, model, timing }) {
  const p = rec.probs || {};
  const irrP = p.irrigation || {};
  const pct = (v) => (v == null ? "" : ` · ${Math.round(v * 100)}%`);
  return (
    <section className="px-actions">
      <p className="px-sub2">{model} decided this season{timing ? ` (${timing.wall_ms.toFixed(0)} ms for all fields)` : ""}</p>
      <div className="px-act on"><span>💧 Irrigation</span><b>{rec.actions.irrigation} ({rec.irrigation_cm} cm){Object.keys(irrP).length ? pct(irrP[rec.actions.irrigation]) : ""}</b></div>
      {rec.pumped_cm > 0 && <div className="px-act warn"><span>⛽ Pumped from aquifer</span><b>{rec.pumped_cm} cm (share used up)</b></div>}
      <div className={`px-act ${rec.actions.compost || rec.actions.synthetic ? "on" : ""}`}><span>Fertilize</span><b>{rec.wanted.fertilize}{rec.actions.compost ? " ♻" : rec.actions.synthetic ? " 🧪" : ""}{pct(p.fertilize?.[rec.wanted.fertilize])}</b></div>
      {["lime", "spray_pests", "cover_crop"].map((k) => (
        <div key={k} className={`px-act ${rec.actions[k] ? "on" : ""}`}><span>{ACTION_ICON[k]} {ACTION_LABEL[k]}</span><b>{rec.wanted[k] ? (rec.actions[k] ? "yes" : "yes, but out of stock") : "no"}{pct(p[k])}</b></div>))}
      {rec.denied.length > 0 && <div className="px-act warn"><span>Over budget</span><b>{rec.denied.map((k) => ACTION_LABEL[k]).join(", ")}</b></div>}
      {rec.review && <div className="px-act warn"><span>⚑ Local review</span><b>borderline call</b></div>}
      {rec.hits.length > 0 && <div className="px-act warn"><span>Crop hurt by</span><b>{rec.hits.join(", ")}</b></div>}
      <div className="px-act"><span>This season</span><b>{rec.harvest_value ? `harvest ${fmtMoney(rec.harvest_value)} · ` : ""}cost {fmtMoney(rec.cost)}</b></div>
    </section>
  );
}

function Gauges({ rec, soilSrc, share }) {
  const g = [
    ["Soil water", rec.moisture / Math.max(1, rec.cap), `${rec.moisture}/${rec.cap} cm`],
    ["Soil pH", Math.min(1, Math.max(0, (rec.ph - 4.5) / 4)), rec.ph.toFixed(1), rec.ph < 6],
    ["Nitrogen", rec.n / 100, `${Math.round(rec.n)}`, rec.n < 30],
    ["Pests", rec.pests / 100, `${Math.round(rec.pests)}`, rec.pests > 55],
    ["Crop health", rec.health / 100, `${Math.round(rec.health)}`, rec.health < 50],
    ["Soil health", rec.soil / 100, `${Math.round(rec.soil)}`],
  ];
  return (
    <section className="px-gauges">
      {g.map(([l, v, t, bad]) => <div key={l} className="px-score"><span>{l}</span><div className="px-bar"><i style={{ width: `${Math.round(v * 100)}%`, background: bad ? "#d03b3b" : "#5fcde4" }} /></div><b>{t}</b></div>)}
      <p className="px-hint">Water share {Math.round(share)} cm/yr, {rec.share_left} cm left. {soilSrc === "estimate" ? "Soil values are estimates." : "Soil from SSURGO."}</p>
    </section>
  );
}
