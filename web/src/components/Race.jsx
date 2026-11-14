import { useEffect, useRef, useState } from "react";

// Two columns, same farm season: Drex live, and the LLM live or replayed
// from the newest farm benchmark when no LLM key is configured.
async function* streamRun(body, signal) {
  const r = await fetch("/api/farm/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!r.ok) {
    let detail = `HTTP ${r.status}`;
    try { detail = (await r.json()).detail ?? detail; } catch { /* not JSON */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let nl;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (line) yield JSON.parse(line);
    }
  }
  if (buf.trim()) yield JSON.parse(buf);
}

const empty = { ms: 0, seasons: 0, done: false, note: "", error: "" };

export default function Race({ meta, settings, onClose }) {
  const [drex, setDrex] = useState(empty);
  const [llm, setLlm] = useState(empty);
  const settingsRef = useRef(settings);
  settingsRef.current = settings;

  useEffect(() => {
    const ctrl = new AbortController();
    let replayTimer;
    const body = settingsRef.current;

    async function live(model, setCol, extra = {}) {
      const t0 = performance.now();
      const clock = setInterval(() => setCol((c) => (c.done ? c : { ...c, ms: performance.now() - t0 })), 80);
      let seasons = 0;
      try {
        for await (const msg of streamRun({ ...body, model, years: 1, ...extra }, ctrl.signal)) {
          if (msg.type === "season") {
            seasons += 1;
            setCol((c) => ({ ...c, seasons, ms: performance.now() - t0 }));
          } else if (msg.type === "done") {
            setCol((c) => ({ ...c, seasons, ms: msg.total_ms || (performance.now() - t0), done: true }));
          } else if (msg.type === "error") {
            setCol((c) => ({ ...c, error: msg.message, done: true }));
          }
        }
        setCol((c) => ({ ...c, done: true, ms: c.ms || (performance.now() - t0) }));
      } catch (e) {
        if (e.name !== "AbortError") setCol((c) => ({ ...c, error: e.message, done: true }));
      } finally {
        clearInterval(clock);
      }
    }

    async function replay() {
      try {
        const r = await fetch("/api/farm/benchmark/latest", { signal: ctrl.signal });
        if (!r.ok) {
          setLlm({ ...empty, done: true, note: "replayed from benchmark", error: "No farm benchmark file yet." });
          return;
        }
        const bench = await r.json();
        const summary = bench.models?.llm;
        const per = summary?.wall_ms_per_season;
        if (per == null) {
          setLlm({ ...empty, done: true, note: "replayed from benchmark", error: "Latest benchmark has no LLM timing." });
          return;
        }
        const total = per * 4;
        const t0 = performance.now();
        replayTimer = setInterval(() => {
          const elapsed = performance.now() - t0;
          const ms = Math.min(total, elapsed);
          setLlm({
            ms, seasons: Math.min(4, per > 0 ? Math.floor(ms / per) : 4),
            done: ms >= total, note: "replayed from benchmark", error: "",
          });
          if (ms >= total) clearInterval(replayTimer);
        }, 50);
      } catch (e) {
        if (e.name !== "AbortError") setLlm({ ...empty, done: true, error: e.message, note: "replayed from benchmark" });
      }
    }

    if (meta.models.drex) live("drex", setDrex);
    else setDrex({ ...empty, done: true, error: "Drex is not configured." });

    if (meta.models.llm) live("llm", setLlm, { confirm_paid: true });
    else replay();

    return () => { ctrl.abort(); clearInterval(replayTimer); };
  }, [meta]);

  return (
    <div className="px-modal-back" onClick={onClose}>
      <div className="px-panel px-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Race">
        <div className="px-row between">
          <p className="px-title">Race · one year</p>
          <button className="px-btn" onClick={onClose}>×</button>
        </div>
        <p className="px-hint">Same farm settings, four seasons, 36 fields. Timers count wall time.</p>
        <div className="px-race">
          <Column title="Drex" col={drex} />
          <Column title="LLM" col={llm} />
        </div>
      </div>
    </div>
  );
}

function Column({ title, col }) {
  const secs = (col.ms / 1000).toFixed(2);
  return (
    <section className="px-race-col">
      <p className="px-title">{title}</p>
      <p className="px-race-time">{secs}s</p>
      <p className="px-hint">{col.seasons} season{col.seasons === 1 ? "" : "s"} decided</p>
      {col.note && <p className="px-hint">{col.note}</p>}
      {col.error && <p className="px-hint">{col.error}</p>}
      {col.done && !col.error && <p className="px-hint">finished</p>}
    </section>
  );
}
