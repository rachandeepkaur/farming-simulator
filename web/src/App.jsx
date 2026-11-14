import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getJSON, streamSimulation } from "./api";
import FieldStage from "./components/FieldStage";
import { DecisionCard, EventLog, Gauges, MiniMap, SeasonTimeline } from "./components/Panels";
import { buildFrames } from "./sim/timeline";

// The demo runs on its own: the real 2012-2021 weather replay, balanced
// farmer priorities, one decision per year. No knobs to set.
const SCENARIO = "Drought replay";
const PRIORITIES = { save_water: 0.5, income: 0.5, build_soil: 0.5 };
const FEATURED = { lat: 36.45, lon: -119.95 }; // a San Joaquin Valley field southwest of Fresno
const SPEEDS = [
  { label: "1×", ms: 900 },
  { label: "2×", ms: 450 },
  { label: "4×", ms: 200 },
];
const MODEL_LABEL = { drex: "Drex", llm: "LLM", rules: "Rule-based stand-in" };

export default function App() {
  const [meta, setMeta] = useState(null);
  const [cells, setCells] = useState([]);
  const [fieldId, setFieldId] = useState(null);
  const [field, setField] = useState(null);
  const [records, setRecords] = useState([]);
  const [timing, setTiming] = useState({});
  const [model, setModel] = useState(null);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState(null);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState(0);
  const abortRef = useRef(null);

  useEffect(() => {
    Promise.all([getJSON("/api/meta"), getJSON("/api/cells")])
      .then(([m, c]) => {
        setMeta(m);
        setCells(c);
        setModel(m.models.drex ? "drex" : "rules");
        const near = c.reduce((best, x) =>
          (x.lat - FEATURED.lat) ** 2 + (x.lon - FEATURED.lon) ** 2 < (best.lat - FEATURED.lat) ** 2 + (best.lon - FEATURED.lon) ** 2 ? x : best);
        setFieldId(near.id);
      })
      .catch((e) => {
        setStatus("error");
        setError(`Can't reach the API (${e.message}). Start it with: uv run uvicorn server.app:app --port 8000`);
      });
  }, []);

  const runField = useCallback(async (id, mdl) => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setStatus("running");
    setError(null);
    setRecords([]);
    setTiming({});
    setIndex(0);
    setPlaying(true);
    try {
      const f = await getJSON(`/api/field/${id}`);
      if (ctrl.signal.aborted) return;
      setField(f);
      const body = { preset: SCENARIO, priorities: PRIORITIES, model: mdl, years: 10, cell_ids: [id] };
      for await (const msg of streamSimulation(body, ctrl.signal)) {
        if (msg.type === "year") {
          setRecords((r) => [...r, msg.cells[id]]);
          setTiming((t) => ({ ...t, [msg.year]: msg.timing }));
        } else if (msg.type === "done") setStatus("done");
        else if (msg.type === "error") { setStatus("error"); setError(msg.message); }
      }
    } catch (e) {
      if (e.name !== "AbortError") { setStatus("error"); setError(e.message); }
    }
  }, []);

  useEffect(() => {
    if (fieldId && model) runField(fieldId, model);
  }, [fieldId, model, runField]);

  const frames = useMemo(
    () => (meta && field ? buildFrames({ records, monthly: field.monthly, meta, modelLabel: MODEL_LABEL[model] }) : []),
    [records, field, meta, model],
  );

  // Autonomous playback: one month per tick; waits at the edge while years stream in.
  useEffect(() => {
    if (!playing || !frames.length) return undefined;
    const t = setInterval(() => {
      setIndex((i) => {
        if (i < frames.length - 1) return i + 1;
        if (status === "done") setPlaying(false);
        return i;
      });
    }, SPEEDS[speed].ms);
    return () => clearInterval(t);
  }, [playing, frames.length, speed, status]);

  if (status === "error" && !meta) return <div className="app"><p className="error pad">{error}</p></div>;
  if (!meta) return <div className="app"><p className="pad">Loading…</p></div>;

  const i = Math.min(index, Math.max(0, frames.length - 1));
  const frame = frames[i];
  const finished = status === "done" && i >= frames.length - 1;

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>Rotation Atlas</h1>
          <p className="sub">
            {field ? `Field ${field.id} near ${field.near} · ${field.lat.toFixed(2)}°N ${Math.abs(field.lon).toFixed(2)}°W` : "Choosing a field…"}
          </p>
        </div>
        <div className="run-info">
          <span className="pill">Real NASA weather, 2012–2021</span>
          <span className="pill">Decided by {MODEL_LABEL[model]}</span>
          {meta.models.drex && meta.models.rules && (
            <button type="button" className="pill btn" onClick={() => setModel(model === "drex" ? "rules" : "drex")}>
              Switch to {model === "drex" ? "rules" : "Drex"}
            </button>
          )}
        </div>
        <div className="transport">
          <button type="button" className="round" onClick={() => {
            if (finished) setIndex(0);
            setPlaying((p) => !p);
          }} aria-label={playing ? "Pause" : "Play"}>{playing && !finished ? "❚❚" : finished ? "↺" : "▶"}</button>
          <div className="seg" role="group" aria-label="Speed">
            {SPEEDS.map((s, k) => (
              <button key={s.label} type="button" aria-pressed={speed === k} onClick={() => setSpeed(k)}>{s.label}</button>
            ))}
          </div>
        </div>
      </header>

      {error && <p className="error pad">{error}</p>}

      <main className="grid">
        <div className="main-col">
          <FieldStage frame={frame} meta={meta} />
          {frame && <Gauges frames={frames} index={i} meta={meta} />}
          {frames.length > 0 && (
            <SeasonTimeline frames={frames} index={i} meta={meta}
                            onSeek={(k) => { setIndex(k); setPlaying(false); }} />
          )}
        </div>
        <aside className="side-col">
          {frame ? (
            <>
              <DecisionCard frame={frame} meta={meta} modelLabel={MODEL_LABEL[model]} yearTiming={timing[frame.year]} />
              <EventLog frames={frames} index={i} />
            </>
          ) : (
            <section className="card"><p className="muted">Deciding the first season…</p></section>
          )}
          <MiniMap cells={cells} meta={meta} selected={fieldId} onSelect={setFieldId} />
          <p className="disclaimer">
            Illustrative what-if, not a forecast.
            {field?.gw_source === "fallback" ? " Groundwater trend is a fallback estimate." : ""}
            {meta.crops_placeholder ? " Crop facts and growing calendars are placeholders until the guide extraction runs." : ""}
          </p>
        </aside>
      </main>
    </div>
  );
}
