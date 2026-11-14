// Turns the yearly simulation (one decision per year) plus real monthly
// weather into month-by-month frames for the field view.
//
// The yearly model is the source of truth: groundwater and soil hit the
// model's values at the end of every year. Within a year we spread the
// change over the months it happens in (pumping months for a drawdown,
// rainy months for a rise), and spread the year's irrigation over the
// months a crop is growing, weighted by heat. That monthly path is a
// visual interpolation, not a separate model.

export const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const SOIL_START = 50;

export function stageLabel(progress, last) {
  if (last) return "Harvest";
  if (progress === 0) return "Planting";
  if (progress < 0.35) return "Seedling";
  if (progress < 0.65) return "Growing";
  return "Flowering";
}

function cropInMonth(meta, strategy, month, altIndex) {
  const s = meta.strategies[strategy];
  const keys = s.pattern === "alternate" ? [s.crops[altIndex % s.crops.length]] : s.crops;
  for (const key of keys) {
    const months = meta.crops[key].months;
    const i = months.indexOf(month);
    if (i >= 0) {
      return { key, progress: months.length > 1 ? i / (months.length - 1) : 1, first: i === 0, last: i === months.length - 1 };
    }
  }
  return null;
}

function spread(total, weights) {
  const sum = weights.reduce((a, b) => a + b, 0);
  if (sum <= 0) return weights.map(() => total / weights.length);
  return weights.map((w) => (total * w) / sum);
}

export function buildFrames({ records, monthly, meta, modelLabel }) {
  const frames = [];
  let gw = 0;
  let soil = SOIL_START;
  let prevStrategy = null;
  let altIndex = 0;
  const supply = meta.constants.sustainable_supply_cm;

  records.forEach((rec, yi) => {
    const strat = meta.strategies[rec.strategy];
    altIndex = strat.pattern === "alternate" && rec.strategy === prevStrategy ? altIndex + 1 : 0;
    const weather = monthly[String(rec.year)] ?? Array(12).fill(null);

    const crops = Array.from({ length: 12 }, (_, i) => cropInMonth(meta, rec.strategy, i + 1, altIndex));
    // Monthly crop water demand rises steeply with heat (a rough ET proxy:
    // ~2 cm in a 15 °C month, ~11 cm in a 38 °C month). Irrigation goes to
    // months where a crop is growing and demand exceeds that month's rain.
    const demand = crops.map((c, i) => (c ? 0.06 * Math.max(0, (weather[i]?.tmax_c ?? 20) - 5) ** 1.5 : 0));
    const heatW = demand.map((d, i) => Math.max(0, d - (weather[i]?.rain_mm ?? 0) / 10));
    const irrigation = spread(rec.irrigation_cm[rec.strategy], heatW.some((w) => w > 0) ? heatW : demand);
    const rainW = weather.map((w) => w?.rain_mm ?? 0);

    const dGw = rec.groundwater_cm - gw;
    const gwSteps = spread(dGw, dGw < 0 && heatW.some((w) => w > 0) ? heatW : rainW);
    const dSoil = rec.soil_score - soil;
    const yearCropKeys = [...new Set(crops.filter(Boolean).map((c) => c.key))];

    let pumpingAnnounced = false;
    for (let m = 0; m < 12; m++) {
      const w = weather[m] ?? { rain_mm: 0, tmax_c: 20, frost_days: 0, heat_days: 0 };
      const crop = crops[m];
      gw += gwSteps[m];
      soil += dSoil / 12;
      const events = [];

      if (m === 0) {
        const conf = rec.answers?.recommended_probs?.[rec.strategy];
        events.push({
          kind: "decision",
          text: `${modelLabel} chose ${strat.label.toLowerCase()}${yearCropKeys.length ? ` (${yearCropKeys.map((k) => meta.crops[k].name).join(" + ")})` : ""}${conf != null ? `, ${(conf * 100).toFixed(0)}% confident` : ""}.`,
        });
        if (rec.decision_failed) events.push({ kind: "alert", text: `Decision failed (${rec.error}); kept last year's plan.` });
        if (rec.review && !rec.stress) events.push({ kind: "alert", text: "Borderline call: flagged for a local advisor." });
      }
      if (crop?.first) events.push({ kind: "crop", text: `Planted ${meta.crops[crop.key].name.toLowerCase()}.` });
      if (crop?.last) events.push({ kind: "crop", text: `Harvested ${meta.crops[crop.key].name.toLowerCase()}.` });
      if (w.rain_mm >= 80) events.push({ kind: "weather", text: `Heavy rain: ${w.rain_mm.toFixed(0)} mm this month.` });
      if (m <= 2 && w.rain_mm < 5) events.push({ kind: "weather", text: `Dry winter month: ${w.rain_mm.toFixed(0)} mm of rain.` });
      if (w.frost_days >= 3) {
        const tender = crop && meta.crops[crop.key].frost_tolerance === "low";
        events.push({ kind: tender ? "alert" : "weather", text: `${w.frost_days} frost nights${tender ? `: risk to ${meta.crops[crop.key].name.toLowerCase()}` : ""}.` });
      }
      if (w.heat_days >= 12) events.push({ kind: "weather", text: `${w.heat_days} days above 35 °C.` });
      if (irrigation[m] > 0.5 && !pumpingAnnounced) {
        pumpingAnnounced = true;
        const total = rec.irrigation_cm[rec.strategy];
        events.push({
          kind: total > supply ? "alert" : "water",
          text: `Well pumping starts: ${total.toFixed(0)} cm needed this year${total > supply ? `, ${(total - supply).toFixed(0)} cm over the sustainable supply` : ""}.`,
        });
      }
      if (m === 11 && rec.stress) events.push({ kind: "alert", text: "Groundwater below the stress threshold: flagged for review." });

      frames.push({
        index: frames.length,
        yearIndex: yi,
        year: rec.year,
        month: m + 1,
        label: `${MONTHS[m]} ${rec.year}`,
        rec,
        strategy: rec.strategy,
        crop,
        weather: w,
        irrigation_cm: irrigation[m],
        recharging: !crop && w.rain_mm >= 25,
        gw,
        soil,
        events,
      });
    }
    gw = rec.groundwater_cm; // snap to the model at year end
    soil = rec.soil_score;
    prevStrategy = rec.strategy;
  });
  return frames;
}
