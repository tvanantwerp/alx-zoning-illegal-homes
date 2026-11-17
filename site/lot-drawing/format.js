/** Number, thousands separators, fixed decimals. A missing value shows as a dash. */
export const fmt = (n, d = 0) =>
  n == null ? "–" : Number(n).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });

/** "1.5 ft" under 20, "25 ft" otherwise. */
export const ft = (n) => (n == null ? "–" : (n >= 20 ? fmt(n) : fmt(n, 1)) + " ft");

/** "8,000 sq ft". */
export const sqft = (n) => (n == null ? "–" : fmt(n) + " sq ft");

/** A fraction as a whole percent: 0.35 gives "35%". */
export const pct = (n) => (n == null ? "–" : Math.round(n * 100) + "%");

/** Makes text safe to put in HTML, including inside quoted attributes. */
export const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/** Formats a measured or required value by its unit: "ft", "sq ft" or "share". */
export function showValue(value, unit) {
  if (value == null) return "–";
  if (unit === "ft") return ft(value);
  if (unit === "sq ft") return sqft(value);
  if (unit === "share") return pct(value);
  return fmt(value, 1);
}
