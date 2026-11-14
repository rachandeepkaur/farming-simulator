import Plant from "./Plants";
import { stageLabel } from "../sim/timeline";

const W = 1000;
const H = 560;
const GROUND = 300; // surface
const TOPSOIL = 360; // topsoil / subsoil boundary
const AQUIFER = 455; // top of the aquifer zone
const WT_BASE = 485; // water table at 0 cm change
const FIELD_X0 = 190;
const FIELD_X1 = 970;
const ROWS = 13;

// Accepts "#rrggbb" or "rgb(r,g,b)" so mixes can be chained.
const toRGB = (c) => (c.startsWith("#") ? c.slice(1).match(/\w\w/g).map((h) => parseInt(h, 16)) : c.match(/\d+/g).map(Number));
const mix = (a, b, t) => {
  const pa = toRGB(a);
  const pb = toRGB(b);
  return `rgb(${pa.map((v, i) => Math.round(v + (pb[i] - v) * t)).join(",")})`;
};

// Deterministic pseudo-random so rain/frost patterns don't jump between renders.
const rand = (i) => {
  const s = Math.sin(i * 127.1 + 311.7) * 43758.5453;
  return s - Math.floor(s);
};

function Sky({ frame }) {
  const { month, weather } = frame;
  const summer = Math.cos(((month - 7) / 12) * 2 * Math.PI) * 0.5 + 0.5; // 1 in July, 0 in January
  const wet = Math.min(1, weather.rain_mm / 90);
  const top = mix(mix("#7da7cf", "#4f9ee8", summer), "#6b7785", wet);
  const bottom = mix(mix("#d7e3ee", "#cfe8fb", summer), "#a9b2bc", wet);
  const sunY = 150 - summer * 95;
  const clouds = Math.min(6, Math.ceil(weather.rain_mm / 18));
  const drops = Math.min(90, Math.round(weather.rain_mm * 0.9));
  const heat = Math.min(1, weather.heat_days / 20);
  return (
    <g>
      <defs>
        <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={top} />
          <stop offset="1" stopColor={bottom} />
        </linearGradient>
        <radialGradient id="sunglow">
          <stop offset="0" stopColor="#fff3b0" stopOpacity="0.9" />
          <stop offset="1" stopColor="#ffd36b" stopOpacity="0" />
        </radialGradient>
      </defs>
      <rect x={0} y={0} width={W} height={GROUND} fill="url(#sky)" />
      <circle cx={760} cy={sunY} r={40 + heat * 40} fill="url(#sunglow)" opacity={1 - wet * 0.7} />
      <circle cx={760} cy={sunY} r={22} fill="#ffd96a" opacity={1 - wet * 0.8} />
      {heat > 0.2 && <rect x={0} y={GROUND - 70} width={W} height={70} fill="#ffb347" opacity={heat * 0.18} className="haze" />}
      {Array.from({ length: clouds }, (_, i) => {
        const cx = 120 + rand(i + month) * 760;
        const cy = 50 + rand(i * 3 + 1) * 70;
        const g = mix("#ffffff", "#7d8794", wet);
        return (
          <g key={i} className="cloud" style={{ animationDelay: `${-rand(i) * 20}s` }} fill={g} opacity={0.92}>
            <ellipse cx={cx} cy={cy} rx={46} ry={16} />
            <ellipse cx={cx - 22} cy={cy - 8} rx={22} ry={14} />
            <ellipse cx={cx + 16} cy={cy - 12} rx={26} ry={17} />
          </g>
        );
      })}
      {Array.from({ length: drops }, (_, i) => {
        const x = 20 + rand(i * 7 + month) * (W - 40);
        return (
          <line key={i} className="drop" x1={x} y1={0} x2={x - 3} y2={12} stroke="#d6e8ff" strokeWidth={1.4}
                style={{ animationDelay: `${rand(i) * 1.2}s`, animationDuration: `${0.7 + rand(i + 9) * 0.5}s` }} />
        );
      })}
    </g>
  );
}

function Ground({ frame, meta }) {
  const { crop, soil, gw, irrigation_cm, weather, recharging } = frame;
  const topsoil = mix("#cdb28a", "#5a3a22", Math.max(0, Math.min(1, soil / 100)));
  const frost = Math.min(1, weather.frost_days / 10);
  const wt = Math.max(AQUIFER + 6, Math.min(H - 8, WT_BASE - gw * 1.1));
  const pumping = irrigation_cm > 0.5;
  const rows = Array.from({ length: ROWS }, (_, i) => FIELD_X0 + 20 + (i * (FIELD_X1 - FIELD_X0 - 40)) / (ROWS - 1));
  const rootDepth = crop && !crop.last
    ? (meta.crops[crop.key].root_depth_cm / 300) * (AQUIFER - GROUND - 20) * Math.max(0.15, crop.progress)
    : 0;

  return (
    <g>
      {/* soil profile */}
      <rect x={0} y={GROUND} width={W} height={TOPSOIL - GROUND} fill={topsoil} />
      <rect x={0} y={TOPSOIL} width={W} height={AQUIFER - TOPSOIL} fill="#9c7b58" />
      <rect x={0} y={AQUIFER} width={W} height={H - AQUIFER} fill="#cdb995" />
      <g opacity={0.35}>
        {Array.from({ length: 140 }, (_, i) => (
          <circle key={i} cx={rand(i) * W} cy={AQUIFER + 4 + rand(i + 50) * (H - AQUIFER - 8)} r={1.3} fill="#8a744f" />
        ))}
      </g>
      {/* groundwater */}
      <rect x={0} y={wt} width={W} height={H - wt} fill="#3b82d6" opacity={0.55} className="water" />
      <line x1={0} x2={W} y1={wt} y2={wt} stroke="#1f5fae" strokeWidth={2} />
      <line x1={0} x2={W} y1={WT_BASE} y2={WT_BASE} stroke="#ffffff" strokeOpacity={0.7} strokeDasharray="6 5" />
      <text x={W - 12} y={WT_BASE - 6} textAnchor="end" className="stage-note">2012 level</text>

      {/* recharge from rain on bare ground */}
      {recharging && Array.from({ length: 10 }, (_, i) => {
        const x = FIELD_X0 + 40 + i * 72;
        return <line key={i} className="seep" x1={x} y1={GROUND + 6} x2={x} y2={wt - 4} stroke="#6fb3ff" strokeWidth={2}
                     strokeDasharray="4 10" style={{ animationDelay: `${rand(i) * 1}s` }} />;
      })}

      {/* roots */}
      {rootDepth > 0 && rows.map((x, i) => (
        <path key={i} d={`M${x},${GROUND} q-6,${rootDepth * 0.4} 0,${rootDepth * 0.7} t2,${rootDepth * 0.3}`}
              stroke="#e8d6b0" strokeOpacity={0.55} strokeWidth={1.4} fill="none" />
      ))}

      {/* surface + frost */}
      <rect x={FIELD_X0} y={GROUND - 4} width={FIELD_X1 - FIELD_X0} height={6} fill={mix("#6b4a2b", topsoil, 0.4)} />
      {frost > 0 && <rect x={0} y={GROUND - 5} width={W} height={7} fill="#e6f2ff" opacity={frost * 0.85} />}

      {/* the well */}
      <rect x={92} y={GROUND - 54} width={36} height={24} rx={4} fill="#5d6873" />
      <rect x={104} y={GROUND - 30} width={12} height={wt - GROUND + 40} fill="#7d8894" />
      <rect x={107} y={GROUND - 30} width={6} height={wt - GROUND + 40} fill="#4c565f" />
      <path d={`M128,${GROUND - 44} H${FIELD_X0 + 6} V${GROUND - 6}`} fill="none" stroke="#7d8894" strokeWidth={6} />
      {pumping && (
        <>
          <path className="flow" d={`M110,${wt + 4} V${GROUND - 44} H${FIELD_X0 + 6} V${GROUND - 6}`} fill="none"
                stroke="#5fb0ff" strokeWidth={3} strokeDasharray="6 8" />
          <path className="flow" d={`M${FIELD_X0},${GROUND - 1} H${FIELD_X1}`} stroke="#5fb0ff" strokeWidth={2}
                strokeDasharray="3 9" fill="none" />
        </>
      )}
      <text x={110} y={GROUND - 62} textAnchor="middle" className="stage-label">Well</text>

      {/* crops */}
      {rows.map((x, i) => <Plant key={i} crop={crop} x={x} y={GROUND - 2} />)}

      {/* layer labels */}
      <text x={12} y={GROUND + 22} className="stage-label">Topsoil · health {soil.toFixed(0)}/100</text>
      <text x={12} y={TOPSOIL + 22} className="stage-label">Subsoil</text>
      <text x={12} y={AQUIFER + 22} className="stage-label">Aquifer</text>
      <text x={12} y={H - 12} className="stage-label">
        Storage {gw > 0 ? "+" : ""}{gw.toFixed(1)} cm since 2012
      </text>
    </g>
  );
}

export default function FieldStage({ frame, meta }) {
  if (!frame) return <div className="stage-empty">Preparing the field…</div>;
  const { crop, weather, irrigation_cm } = frame;
  const cropName = crop ? meta.crops[crop.key].name : "Bare field (fallow)";
  return (
    <div className="stage">
      <svg viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label={`${frame.label}: ${cropName}${crop ? `, ${stageLabel(crop.progress, crop.last)}` : ""}. Rain ${weather.rain_mm.toFixed(0)} mm.`}>
        <Sky frame={frame} />
        <Ground frame={frame} meta={meta} />
      </svg>
      <div className="stage-hud">
        <div className="hud-date">{frame.label}</div>
        <div className="hud-crop">
          {cropName}{crop && <span className="hud-stage">{stageLabel(crop.progress, crop.last)}</span>}
        </div>
        <div className="hud-weather">
          <span>Rain {weather.rain_mm.toFixed(0)} mm</span>
          <span>High {weather.tmax_c.toFixed(0)} °C</span>
          {weather.frost_days > 0 && <span>{weather.frost_days} frost nights</span>}
          {weather.heat_days > 0 && <span>{weather.heat_days} days &gt; 35 °C</span>}
          {irrigation_cm > 0.5 && <span className="hud-water">Irrigating {irrigation_cm.toFixed(1)} cm</span>}
        </div>
      </div>
    </div>
  );
}
