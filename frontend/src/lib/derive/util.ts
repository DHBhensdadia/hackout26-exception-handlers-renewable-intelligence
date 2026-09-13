/** Shared deterministic helpers for the dashboard's derived models. */

/** FNV-1a hash mapped to 0..1 — stable per string, so a site always derives the same model. */
export function hash01(str: string): number {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 4294967296;
}

export function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

export function round(v: number, digits = 1): number {
  const f = 10 ** digits;
  return Math.round(v * f) / f;
}

/** 1 crore = 10,000,000 */
export const CR = 1e7;

/** Typical 24 h demand shape (index = UTC hour). */
export const DEMAND_CURVE = [62, 58, 55, 53, 52, 53, 56, 62, 70, 78, 86, 92, 95, 93, 90, 88, 90, 92, 88, 82, 74, 68, 64, 61];

/** Format an ISO hour as "12 Sep 18:00 UTC". */
export function hourLabel(iso: string): string {
  const d = new Date(iso);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  return `${d.getUTCDate()} ${d.toLocaleString("en", { month: "short" })} ${hh}:00 UTC`;
}
