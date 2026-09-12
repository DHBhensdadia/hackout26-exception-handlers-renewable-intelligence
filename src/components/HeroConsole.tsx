/**
 * The hero "forecast console" — a mac-framed window showing live-looking
 * dashboard content. Pure presentational mock (the real one lives in the
 * dashboard), but it uses the same app-win chrome as the reference site.
 */
export function HeroConsole() {
  return (
    <div className="appwin" aria-label="re-forecast — 24–72 hour forecast console (demo)">
      <div className="macbar" aria-hidden="true">
        <span className="macbar__lights"><i className="r" /><i className="y" /><i className="g" /></span>
        <span className="macbar__title">re-forecast — 72 h forecast · GJ-SOLAR-CHARANKA</span>
        <span className="macbar__pad" />
      </div>

      <aside className="appwin__side">
        <div className="appwin__brand">
          <span className="mark" /> console <span style={{ marginLeft: "auto", color: "var(--text-muted)" }}>▾</span>
        </div>
        <div className="appwin__grp">Modules</div>
        <nav className="appwin__nav">
          <a className="on"><span className="em">◎</span> Forecast</a>
          <a><span className="em">⇄</span> Balance</a>
          <a><span className="em">◔</span> Reliability</a>
          <a><span className="em">◎</span> Investment</a>
          <a><span className="em">◎</span> Demand</a>
          <a><span className="em">◈</span> Optimize</a>
        </nav>
      </aside>

      <div className="appwin__body">
        <div className="appwin__bar">
          <span className="appwin__bar-l"><b>Solar forecast — next 72 h</b></span>
          <span className="mono" style={{ fontSize: ".72rem" }}>xgb-q-0.1.0 · p10/p50/p90</span>
        </div>

        <div style={{ padding: "18px 24px 24px", display: "grid", gap: 16 }}>
          {/* Stat chips */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 10 }}>
            {[
              ["Capacity", "50 MW"],
              ["Horizon", "72 h"],
              ["p50 median", "18.6 MW"],
              ["80 % band", "7.2–27.7"],
            ].map(([k, v]) => (
              <div key={k} style={{ border: "1px solid var(--hairline)", borderRadius: 10, padding: "10px 12px", background: "var(--bg-elevated)" }}>
                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{k}</div>
                <div style={{ fontSize: 18, fontWeight: 700, fontFamily: "var(--font-display)", color: "var(--text)", letterSpacing: "-0.02em" }}>{v}</div>
              </div>
            ))}
          </div>

          {/* Mock band chart (pure divs, no SVG dependence for the hero) */}
          <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 120 }}>
            {[
              [12, 30], [18, 40], [26, 50], [34, 62], [42, 70], [34, 60], [24, 45], [16, 32],
              [10, 26], [6, 18], [4, 12], [2, 8], [1, 4], [1, 3], [1, 2], [1, 2],
            ].map(([lo, hi], i) => (
              <div key={i} style={{ flex: 1, position: "relative", background: "var(--surface-2)", borderRadius: "3px 3px 0 0" }}>
                <div style={{
                  position: "absolute", left: 0, right: 0,
                  bottom: `${lo}%`, top: `${100 - hi}%`,
                  background: "linear-gradient(180deg, rgba(94,106,210,.85), rgba(94,106,210,.25))",
                  borderRadius: "3px 3px 0 0",
                }} />
                <div style={{
                  position: "absolute", left: 0, right: 0, bottom: `${lo}%`,
                  height: 2, background: "var(--accent-2)",
                }} />
              </div>
            ))}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)" }}>
            <span>now +6h +12h +18h +24h +30h +36h +42h +48h +54h +60h +66h +72h</span>
          </div>

          {/* Alerts strip */}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <span className="pill pill--ok">Surplus 14:00–16:00 · charge storage</span>
            <span className="pill pill--warn">Shortage 20:00–22:00 · hold backup</span>
            <span className="pill pill--info">RR 87% of days exceed target</span>
          </div>
        </div>
      </div>
    </div>
  );
}