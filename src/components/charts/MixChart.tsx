const fmt = (v: number) => {
  if (v >= 100) return v.toFixed(1);
  return v.toFixed(2);
};

/**
 * Simple horizontal stacked bar — solar vs wind share of the 72 h energy mix.
 * Renders as an SVG donut when `donut` is true (portfolio summary), or as a
 * two-tone stacked bar otherwise.
 */
export function MixBar({
  solar, wind, total,
}: {
  solar: number;
  wind: number;
  total: number;
}) {
  const sPct = total === 0 ? 0 : (solar / total) * 100;
  const wPct = total === 0 ? 0 : (wind / total) * 100;
  return (
    <div>
      <div style={{
        display: "flex", height: 12, borderRadius: 999, overflow: "hidden", background: "var(--surface-2)",
      }}>
        <div style={{ width: `${sPct}%`, background: "var(--c-amber)" }} title={`Solar ${fmt(solar)} MW`} />
        <div style={{ width: `${wPct}%`, background: "var(--c-blue)" }} title={`Wind ${fmt(wind)} MW`} />
      </div>
      <div style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 12, marginTop: 8 }}>
        <span style={{ color: "var(--c-amber)" }}>■</span> Solar {fmt(solar)} MW ({(total ? (solar / total) * 100 : 0).toFixed(0)}%)
        {"  "}
        <span style={{ color: "var(--c-blue)" }}>■</span> Wind {fmt(wind)} MW ({(total ? (wind / total) * 100 : 0).toFixed(0)}%)
      </div>
    </div>
  );
}

/** Tiny sparkline for table rows / inline cues. */
export function Sparkline({
  values,
  width = 54,
  height = 16,
}: {
  values: number[];
  width?: number;
  height?: number;
}) {
  const n = Math.max(2, values.length);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const pts = values
    .map((v, i) => `${(i / (n - 1)) * width},${height - 2 - ((v - min) / range) * (height - 4)}`)
    .join(" ");
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="spark" aria-hidden="true">
      <polyline
        points={pts}
        fill="none"
        stroke="var(--text-muted)"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** Vertical bar group (used by the balance / demand comparison). */
export function Bars({
  data,
  height = 110,
  color = "var(--accent)",
  labelFmt = (v: number) => v.toFixed(1),
}: {
  data: number[];
  height?: number;
  color?: string;
  labelFmt?: (v: number) => string;
}) {
  const max = Math.max(...data, 1);
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 7, height, width: "100%" }}>
      {data.map((v, i) => (
        <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", flex: 1, gap: 6, height: "100%", justifyContent: "flex-end" }}>
          <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
            {labelFmt(v)}
          </span>
          <div
            title={`${labelFmt(v)} MW`}
            style={{
              width: "100%",
              background: v > 0 ? color : "var(--surface-2)",
              borderRadius: "4px 4px 0 0",
              height: `${Math.max(3, (v / max) * (height - 24))}px`,
            }}
          />
        </div>
      ))}
    </div>
  );
}