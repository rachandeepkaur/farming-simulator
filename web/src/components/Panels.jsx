import { STRATEGY_COLOR, STRATEGY_ORDER } from "../colors";
import { MONTHS } from "../sim/timeline";

export function DecisionCard({ frame, meta, modelLabel, yearTiming }) {
  const rec = frame.rec;
  const strat = meta.strategies[rec.strategy];
  const conf = rec.answers?.recommended_probs?.[rec.strategy];
  const supply = meta.constants.sustainable_supply_cm;
  return (
    <section className="card decision" aria-label={`Decision for ${frame.year}`}>
      <div className="card-head">
        <span className="eyebrow">{frame.year} decision</span>
        <span className="muted">{modelLabel}{yearTiming ? ` · ${yearTiming.wall_ms.toFixed(0)} ms` : ""}</span>
      </div>
      <div className="decision-title">
        <span className="swatch" style={{ background: STRATEGY_COLOR[rec.strategy] }} />
        {strat.label}
      </div>
      {conf != null && (
        <div className="conf" aria-label={`Confidence ${(conf * 100).toFixed(0)} percent`}>
          <div className="conf-bar"><div style={{ width: `${conf * 100}%` }} /></div>
          <span>{(conf * 100).toFixed(0)}% confident</span>
        </div>
      )}
      <p className="muted small">{strat.summary}</p>
      <h4>Irrigation each option needs this year</h4>
      <ul className="options">
        {STRATEGY_ORDER.map((s) => {
          const v = rec.irrigation_cm[s];
          const fits = v <= supply;
          return (
            <li key={s} className={s === rec.strategy ? "chosen" : ""}>
              <span className="swatch sm" style={{ background: STRATEGY_COLOR[s] }} />
              <span className="opt-name">{meta.strategies[s].label.replace(" rotation", "")}</span>
              <span className="opt-bar"><span style={{ width: `${Math.min(100, (v / (supply * 2)) * 100)}%`, background: STRATEGY_COLOR[s] }} /><i style={{ left: "50%" }} /></span>
              <span className={`opt-val ${fits ? "ok" : "over"}`}>{v.toFixed(0)} cm {fits ? "✓" : "✗"}</span>
            </li>
          );
        })}
      </ul>
      <p className="muted small">Dashed mark = {supply} cm sustainable supply. ✗ means the option draws down groundwater.</p>
      {rec.answers && (
        <div className="chips">
          <span className="chip">Frost risk: {rec.answers.frost_risk}</span>
          <span className="chip">Soil benefit: {rec.answers.soil_benefit.replace("_", " ")}</span>
          {rec.review && <span className="chip alert">⚑ Local review</span>}
        </div>
      )}
    </section>
  );
}

function Spark({ values, total, min, max, refValue }) {
  const w = 220, h = 44;
  const xs = (i) => (total > 1 ? (i / (total - 1)) * w : 0);
  const ys = (v) => h - ((v - min) / (max - min || 1)) * h;
  const d = values.map((v, i) => `${i ? "L" : "M"}${xs(i).toFixed(1)},${ys(v).toFixed(1)}`).join("");
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden>
      {refValue != null && <line x1={0} x2={w} y1={ys(refValue)} y2={ys(refValue)} className="spark-ref" />}
      <line x1={0} x2={w} y1={ys(0)} y2={ys(0)} className="spark-zero" />
      <path d={d} className="spark-line" />
      {values.length > 0 && <circle cx={xs(values.length - 1)} cy={ys(values[values.length - 1])} r={3} className="spark-dot" />}
    </svg>
  );
}

export function Gauges({ frames, index, meta }) {
  const f = frames[index];
  const upTo = frames.slice(0, index + 1);
  const gws = upTo.map((x) => x.gw);
  const allGw = frames.map((x) => x.gw).concat([0, meta.constants.stress_threshold_cm]);
  const yearFrames = frames.filter((x) => x.yearIndex === f.yearIndex && x.index <= index);
  const irrigated = yearFrames.reduce((a, x) => a + x.irrigation_cm, 0);
  const supply = meta.constants.sustainable_supply_cm;
  return (
    <section className="card gauges" aria-label="Field state">
      <div className="gauge">
        <div className="g-k">Groundwater storage</div>
        <div className="g-v">{f.gw > 0 ? "+" : ""}{f.gw.toFixed(1)}<small> cm since 2012</small></div>
        <Spark values={gws} total={frames.length} min={Math.min(...allGw)} max={Math.max(...allGw)}
               refValue={meta.constants.stress_threshold_cm} />
      </div>
      <div className="gauge">
        <div className="g-k">Soil health</div>
        <div className="g-v">{f.soil.toFixed(0)}<small>/100</small></div>
        <div className="meter"><div style={{ width: `${f.soil}%` }} /></div>
      </div>
      <div className="gauge">
        <div className="g-k">Irrigation so far in {f.year}</div>
        <div className="g-v">{irrigated.toFixed(0)}<small> of {supply} cm supply</small></div>
        <div className="meter water"><div style={{ width: `${Math.min(100, (irrigated / supply) * 100)}%` }} className={irrigated > supply ? "over" : ""} /></div>
      </div>
    </section>
  );
}

const ICON = { decision: "◆", crop: "✿", weather: "☁", water: "💧", alert: "⚑" };

export function EventLog({ frames, index }) {
  const items = [];
  for (let i = index; i >= 0 && items.length < 9; i--) {
    for (const e of [...frames[i].events].reverse()) {
      if (items.length < 9) items.push({ ...e, label: frames[i].label, key: `${i}-${e.text}` });
    }
  }
  return (
    <section className="card log" aria-label="What happened" aria-live="polite">
      <div className="card-head"><span className="eyebrow">Field log</span></div>
      <ol>
        {items.map((e) => (
          <li key={e.key} className={`ev-${e.kind}`}>
            <span className="ev-icon" aria-hidden>{ICON[e.kind]}</span>
            <span className="ev-when">{e.label}</span>
            <span className="ev-text">{e.text}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

const SHORT = { processing_tomato: "Tomato", vetch_cover: "Vetch", winter_wheat: "Wheat", safflower: "Safflower" };

export function SeasonTimeline({ frames, index, onSeek, meta }) {
  const years = [...new Set(frames.map((f) => f.year))];
  // Contiguous crop blocks for labels.
  const blocks = [];
  frames.forEach((f, i) => {
    const key = f.crop?.key ?? null;
    const last = blocks[blocks.length - 1];
    if (last && last.key === key) last.end = i;
    else blocks.push({ key, start: i, end: i });
  });
  const n = frames.length;
  return (
    <section className="card timeline" aria-label="Season timeline">
      <div className="card-head">
        <span className="eyebrow">Ten seasons</span>
        <span className="muted small">Click any month to jump there</span>
      </div>
      <div className="tl">
        <div className="tl-row tl-strategy" style={{ gridTemplateColumns: `repeat(${n}, 1fr)` }}>
          {frames.map((f, i) => (
            <button key={i} type="button" className={`tl-cell${i === index ? " now" : ""}${i > index ? " future" : ""}`}
                    style={{ background: STRATEGY_COLOR[f.strategy] }} onClick={() => onSeek(i)}
                    title={`${f.label}: ${meta.strategies[f.strategy].label}`} aria-label={`Jump to ${f.label}`} />
          ))}
        </div>
        <div className="tl-row tl-crops" style={{ gridTemplateColumns: `repeat(${n}, 1fr)` }}>
          {blocks.map((b) => (
            <div key={b.start} className={`tl-block${b.key ? "" : " bare"}${b.start > index ? " future" : ""}`}
                 style={{ gridColumn: `${b.start + 1} / ${b.end + 2}` }} title={b.key ? meta.crops[b.key].name : "Bare"}>
              {b.key ? (b.end - b.start >= 3 ? SHORT[b.key] : SHORT[b.key][0]) : (b.end - b.start >= 3 ? "bare" : "")}
            </div>
          ))}
        </div>
        <div className="tl-years" style={{ gridTemplateColumns: `repeat(${years.length}, 1fr)` }}>
          {years.map((y) => <span key={y}>{y}</span>)}
        </div>
        <div className="tl-playhead" style={{ left: `${((index + 0.5) / n) * 100}%` }} />
      </div>
      <div className="tl-legend">
        {STRATEGY_ORDER.map((s) => (
          <span key={s}><span className="swatch sm" style={{ background: STRATEGY_COLOR[s] }} />{meta.strategies[s].label}</span>
        ))}
        <span className="muted small">Bottom row: crop in the ground ({MONTHS[0]}–{MONTHS[11]} each year)</span>
      </div>
    </section>
  );
}

export function MiniMap({ cells, meta, selected, onSelect }) {
  const lons = meta.valley_polygon.map((p) => p[0]);
  const lats = meta.valley_polygon.map((p) => p[1]);
  const west = Math.min(...lons), east = Math.max(...lons), south = Math.min(...lats), north = Math.max(...lats);
  const k = Math.cos((((north + south) / 2) * Math.PI) / 180);
  const W = 160, scale = W / ((east - west) * k), H = (north - south) * scale;
  const x = (lon) => (lon - west) * k * scale;
  const y = (lat) => (north - lat) * scale;
  const sel = cells.find((c) => c.id === selected);
  return (
    <section className="card minimap" aria-label="Choose a field">
      <div className="card-head"><span className="eyebrow">Field</span></div>
      <svg viewBox={`-4 -4 ${W + 8} ${H + 8}`} className="mm">
        {cells.map((c) => {
          const [w, s, e, n] = c.bbox;
          return (
            <rect key={c.id} x={x(w)} y={y(n)} width={x(e) - x(w) - 0.4} height={y(s) - y(n) - 0.4}
                  className={`mm-cell${c.id === selected ? " sel" : ""}`} onClick={() => onSelect(c.id)}>
              <title>{c.id}</title>
            </rect>
          );
        })}
        {meta.cities.map((ct) => (
          <g key={ct.name} pointerEvents="none">
            <circle cx={x(ct.lon)} cy={y(ct.lat)} r={1.6} className="mm-city" />
            <text x={x(ct.lon) + 4} y={y(ct.lat) + 3} className="mm-label">{ct.name}</text>
          </g>
        ))}
        {sel && <circle cx={x(sel.lon)} cy={y(sel.lat)} r={7} className="mm-ring" />}
      </svg>
      <p className="muted small">Click anywhere in the valley to simulate another field.</p>
    </section>
  );
}
