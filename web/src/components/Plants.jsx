// Simple 2D crop illustrations, drawn upward from the ground at (x, y).
// `p` is growth progress 0..1. Placeholders until the Firefly crop art
// (task 12) arrives; each crop keeps a distinct silhouette so the field
// reads without color.

const LEAF = "#4f9a3c";
const LEAF_DARK = "#3a7a2c";

function Tomato({ x, y, p }) {
  const h = 14 + 46 * p;
  const w = 10 + 26 * p;
  return (
    <g>
      <line x1={x} y1={y} x2={x} y2={y - h} stroke={LEAF_DARK} strokeWidth={2} />
      <ellipse cx={x} cy={y - h * 0.62} rx={w / 2} ry={h * 0.42} fill={LEAF} />
      <ellipse cx={x - w * 0.25} cy={y - h * 0.35} rx={w * 0.32} ry={h * 0.22} fill={LEAF_DARK} />
      {p > 0.55 && [[-0.25, 0.45], [0.2, 0.55], [0.05, 0.3], [0.3, 0.32]].map(([dx, dy], i) => (
        <circle key={i} cx={x + dx * w} cy={y - h * dy} r={2.2 + 2 * p} fill={p > 0.75 ? "#d8382c" : "#e9a23b"} />
      ))}
    </g>
  );
}

function Wheat({ x, y, p }) {
  const h = 12 + 58 * p;
  const ripe = p > 0.7;
  const stem = ripe ? "#c9a24a" : "#6aa84f";
  return (
    <g>
      {[-6, -2, 2, 6].map((dx, i) => (
        <g key={i}>
          <line x1={x + dx * 0.5} y1={y} x2={x + dx} y2={y - h + (i % 2) * 6} stroke={stem} strokeWidth={1.6} />
          {p > 0.45 && <ellipse cx={x + dx} cy={y - h + (i % 2) * 6 - 5} rx={2.2} ry={6} fill={ripe ? "#e0b84f" : "#8cbf5a"} />}
        </g>
      ))}
    </g>
  );
}

function Vetch({ x, y, p }) {
  const w = 12 + 26 * p;
  const h = 6 + 18 * p;
  return (
    <g>
      <ellipse cx={x} cy={y - h / 2} rx={w / 2} ry={h / 2} fill="#5aa046" />
      <ellipse cx={x + w * 0.2} cy={y - h * 0.65} rx={w * 0.3} ry={h * 0.35} fill={LEAF_DARK} />
      {p > 0.5 && [[-0.3, 0.7], [0.1, 0.9], [0.35, 0.6]].map(([dx, dy], i) => (
        <circle key={i} cx={x + dx * w} cy={y - h * dy} r={2.4} fill="#8b6cc9" />
      ))}
    </g>
  );
}

function Safflower({ x, y, p }) {
  const h = 14 + 62 * p;
  const head = p > 0.9 ? "#a2763f" : p > 0.55 ? "#f2a33a" : "#7fb85a";
  return (
    <g>
      <line x1={x} y1={y} x2={x} y2={y - h} stroke={LEAF_DARK} strokeWidth={2} />
      {[0.3, 0.55].map((f, i) => (
        <g key={i}>
          <line x1={x} y1={y - h * f} x2={x + (i ? -9 : 9)} y2={y - h * f - 7} stroke={LEAF} strokeWidth={3} strokeLinecap="round" />
        </g>
      ))}
      {p > 0.35 && (
        <>
          <line x1={x} y1={y - h * 0.75} x2={x + 7} y2={y - h * 0.88} stroke={LEAF_DARK} strokeWidth={1.5} />
          <circle cx={x} cy={y - h} r={3 + 3 * p} fill={head} />
          <circle cx={x + 7} cy={y - h * 0.88} r={2 + 2 * p} fill={head} />
        </>
      )}
    </g>
  );
}

function Stubble({ x, y }) {
  return (
    <g stroke="#b99a5b" strokeWidth={1.6}>
      {[-5, -1, 3, 6].map((dx, i) => <line key={i} x1={x + dx} y1={y} x2={x + dx + 1} y2={y - 6 - (i % 2) * 3} />)}
    </g>
  );
}

const GLYPH = { processing_tomato: Tomato, winter_wheat: Wheat, vetch_cover: Vetch, safflower: Safflower };

export default function Plant({ crop, x, y }) {
  if (!crop) return null;
  if (crop.last) return <Stubble x={x} y={y} />;
  const G = GLYPH[crop.key];
  return G ? <G x={x} y={y} p={Math.max(0.05, crop.progress)} /> : null;
}
