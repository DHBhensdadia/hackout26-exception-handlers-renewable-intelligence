/** Tiny number formatters shared by dashboard widgets. */
const GROUPED = new Intl.NumberFormat("en", { maximumFractionDigits: 0 });

export function fact(v: number) {
  return GROUPED.format(v);
}

export function fmt(v: number, digits = 2) {
  return v.toLocaleString("en", { maximumFractionDigits: digits });
}