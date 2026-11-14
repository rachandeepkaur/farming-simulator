// Strategy is categorical identity: reference palette slots 1-3, which
// validate all-pairs for colorblind separation. CSS custom properties, so
// light/dark swap in styles.css.

export const STRATEGY_ORDER = ["existing", "cover_crop", "drought_tolerant"];

export const STRATEGY_COLOR = {
  existing: "var(--series-1)",
  drought_tolerant: "var(--series-2)",
  cover_crop: "var(--series-3)",
};

// Short codes so strategy is never color-alone (timeline strip, tooltips).
export const STRATEGY_CODE = { existing: "E", cover_crop: "C", drought_tolerant: "D" };
