import { ArrowLeftRight, CircleDollarSign, ShieldCheck, Sparkles, Target, Zap } from "lucide-react";
import { stagger } from "@/lib/style";

const STATS: [string, string][] = [
  ["Capacity", "50 MW"],
  ["Horizon", "72 h"],
  ["p50 median", "18.6 MW"],
  ["80 % band", "7.2–27.7"],
];

/** Thirteen hourly checkpoints across the 72 h horizon. */
const TICKS = Array.from({ length: 13 }, (_, i) => (i === 0 ? "now" : `+${i * 6}h`));

/** Surplus / shortage windows drawn on the rail, in tick units (0–12). */
const SEGMENTS: { tone: "ok" | "warn"; start: number; end: number }[] = [
  { tone: "ok", start: 0, end: 2 },
  { tone: "warn", start: 4, end: 5 },
  { tone: "ok", start: 6, end: 8 },
  { tone: "warn", start: 9, end: 10 },
  { tone: "ok", start: 11, end: 12 },
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
          <span className="on"><span className="em"><Target className="ic" aria-hidden="true" /></span> Forecast</span>
          <span><span className="em"><ArrowLeftRight className="ic" aria-hidden="true" /></span> Balance</span>
          <span><span className="em"><ShieldCheck className="ic" aria-hidden="true" /></span> Reliability</span>
          <span><span className="em"><CircleDollarSign className="ic" aria-hidden="true" /></span> Investment</span>
          <span><span className="em"><Zap className="ic" aria-hidden="true" /></span> Demand</span>
          <span><span className="em"><Sparkles className="ic" aria-hidden="true" /></span> Optimize</span>
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

          <div className="hc-line">
            <div className="hc-line__rail">
              <span className="hc-line__now" />
              {SEGMENTS.map((s, i) => (
                <span
                  key={i}
                  className={`hc-line__seg hc-line__seg--${s.tone}`}
                  style={stagger(i, {
                    left: `${(s.start / 12) * 100}%`,
                    width: `${((s.end - s.start) / 12) * 100}%`,
                  })}
                />
              ))}
            </div>
            <div className="hc-line__ticks">
              {TICKS.map((t, i) => (
                <span key={t} style={{ left: `${(i / 12) * 100}%` }}>{t}</span>
              ))}
            </div>
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
