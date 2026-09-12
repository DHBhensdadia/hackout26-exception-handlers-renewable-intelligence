/** Tiny number formatters shared by dashboard widgets. */
export function fact(v: number) {
  return v.toLocaleString("en", { maximumFractionDigits: 0 });
}
export function fmt(v: number, digits = 2) {
  return v.toLocaleString("en", { maximumFractionDigits: digits });
}
export function formatMw(v: number) {
  if (v >= 1000) return (v / 1000).toFixed(1) + " GW";
  return v.toFixed(1) + " MW";
}