import { stagger } from "@/lib/style";

const STATS: [string, string][] = [
  ["Capacity", "50 MW"],
  ["Horizon", "72 h"],
  ["p50 median", "18.6 MW"],
  ["80 % band", "7.2–27.7"],
];

const BARS: [number, number][] = [
  [12, 30], [18, 40], [26, 50], [34, 62], [42, 70], [34, 60], [24, 45], [16, 32],
  [10, 26], [6, 18], [4, 12], [2, 8], [1, 4], [1, 3], [1, 2], [1, 2],
];

const PILLS: { cls: string; label: string }[] = [
  { cls: "pill--ok", label: "Surplus 14:00–16:00 · charge storage" },
  { cls: "pill--warn", label: "Shortage 20:00–22:00 · hold backup" },
  { cls: "pill--info", label: "RR 87% of days exceed target" },
];

/**
 * The hero "forecast console" — a mac-framed window showing live-looking
 * dashboard content. Pure presentational mock (the real one lives in the
 * dashboard), but it uses the same app-win chrome as the reference site.
 */
export function HeroConsole() {
  return (
    <figure className="appwin" role="img" aria-label="re-forecast — 24 to 72 hour forecast console (demo)">
      <div className="macbar" aria-hidden="true">
        <span className="macbar__lights"><i className="r" /><i className="y" /><i className="g" /></span>
        <span className="macbar__title">re-forecast — 72 h forecast · GJ-SOLAR-CHARANKA</span>
        <span className="macbar__pad" />
      </div>

      <aside className="appwin__side" aria-hidden="true">
        <div className="appwin__brand">
          <span className="mark" /> console <span className="appwin__caret">▾</span>
        </div>
        <div className="appwin__grp">Modules</div>
        <nav className="appwin__nav">
          <span className="on"><span className="em">◎</span> Forecast</span>
          <span><span className="em">⇄</span> Balance</span>
          <span><span className="em">◔</span> Reliability</span>
          <span><span className="em">◎</span> Investment</span>
          <span><span className="em">◎</span> Demand</span>
          <span><span className="em">◈</span> Optimize</span>
        </nav>
      </aside>

      <div className="appwin__body" aria-hidden="true">
        <div className="appwin__bar">
          <span className="appwin__bar-l"><b>Solar forecast — next 72 h</b></span>
          <span className="mono appwin__model">xgb-q-0.1.0 · p10/p50/p90</span>
        </div>

        <div className="appwin__content">
          <div className="appwin__stats">
            {STATS.map(([k, v], i) => (
              <div key={k} className="appwin__stat" style={stagger(i)}>
                <div className="appwin__stat-k">{k}</div>
                <div className="appwin__stat-v">{v}</div>
              </div>
            ))}
          </div>

          <div className="appwin__chart">
            {BARS.map(([lo, hi], i) => (
              <div key={i} className="appwin__bar-col" style={stagger(i)}>
                <div className="appwin__bar-fill" style={{ bottom: `${lo}%`, top: `${100 - hi}%` }} />
                <div className="appwin__bar-line" style={{ bottom: `${lo}%` }} />
              </div>
            ))}
          </div>
          <div className="appwin__axis">
            <span>now +6h +12h +18h +24h +30h +36h +42h +48h +54h +60h +66h +72h</span>
          </div>

          <div className="appwin__pills">
            {PILLS.map((p, i) => (
              <span key={p.cls} className={`pill ${p.cls}`} style={stagger(i)}>
                {p.label}
              </span>
            ))}
          </div>
        </div>
      </div>
    </figure>
  );
}
