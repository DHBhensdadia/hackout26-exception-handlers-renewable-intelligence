import { useMemo, useState } from "react";
import { useDashboardContext } from "@/hooks/useDashboardContext";
import { fact } from "@/lib/format";

function hhmm(iso: string) {
  const d = new Date(iso);
  return `${String(d.getUTCHours()).padStart(2, "0")}:00`;
}

interface Run {
  state: "surplus" | "shortage";
  start: number;
  end: number;
}

/** Contiguous same-state runs across the balance hours. */
function runs(hours: { state: "surplus" | "shortage" }[]): Run[] {
  const out: Run[] = [];
  let i = 0;
  while (i < hours.length) {
    const state = hours[i].state;
    let j = i;
    while (j + 1 < hours.length && hours[j + 1].state === state) j++;
    out.push({ state, start: i, end: j });
    i = j + 1;
  }
  return out;
}

const longest = (all: Run[], state: Run["state"]) =>
  all.filter((r) => r.state === state).sort((a, b) => b.end - b.start - (a.end - a.start))[0] ?? null;

/**
 * Live console header: run KPIs, the horizon timeline (with surplus/shortage
 * windows) and the action chips. Everything reads from the active run, so it
 * re-renders on every forecast or site switch.
 */
export function ConsoleSummary() {
  const { result, derived } = useDashboardContext();
  const [tick, setTick] = useState<number | null>(null);

  const data = useMemo(() => {
    if (!result || !derived) return null;
    const pts = result.points;
    const n = pts.length;
    const p50 = pts.reduce((a, p) => a + p.p50_mw, 0) / n;
    const lo = Math.min(...pts.map((p) => p.p10_mw));
    const hi = Math.max(...pts.map((p) => p.p90_mw));
    const step = n > 1 ? 100 / (n - 1) : 100;
    const all = runs(derived.balance.hours);
    const ticks: number[] = [];
    for (let i = 0; i < n; i += 6) ticks.push(i);
    if (ticks[ticks.length - 1] !== n - 1) ticks.push(n - 1);
    return { pts, n, p50, lo, hi, step, all, ticks, surplus: longest(all, "surplus"), shortage: longest(all, "shortage") };
  }, [result, derived]);

  if (!data || !result || !derived) {
    return (
      <div className="csum" aria-hidden="true">
        <div className="csum__metrics">
          {["Capacity", "Horizon", "p50 median", "80 % band"].map((k) => (
            <div className="metric" key={k}>
              <span className="mk">{k}</span>
              <b>—</b>
            </div>
          ))}
        </div>
      </div>
    );
  }

  const { pts, n, p50, lo, hi, step, all, ticks, surplus, shortage } = data;
  const reli = derived.reliability;
  const active = tick ?? 0;
  const p = pts[active];
  const read = `${active === 0 ? "now" : `+${active} h`} · ${hhmm(p.valid_time_utc)} · p50 ${p.p50_mw.toFixed(1)} MW · p10–p90 ${p.p10_mw.toFixed(1)}–${p.p90_mw.toFixed(1)}`;

  return (
    <div className="csum">
      <div className="csum__metrics">
        <div className="metric">
          <span className="mk">Capacity</span>
          <b>{fact(result.capacity_mw)} MW</b>
        </div>
        <div className="metric">
          <span className="mk">Horizon</span>
          <b>{n} h</b>
        </div>
        <div className="metric">
          <span className="mk">p50 median</span>
          <b>{p50.toFixed(1)} MW</b>
          <span className="d">mean across horizon</span>
        </div>
        <div className="metric">
          <span className="mk">80 % band</span>
          <b>
            {lo.toFixed(1)}–{hi.toFixed(1)}
          </b>
          <span className="d">min p10 · max p90</span>
        </div>
      </div>

      <div className="hline">
        <div className="hline__rail">
          <span className="hline__now" style={{ left: "0%" }} aria-hidden="true" />
          {all.map((r, i) => (
            <span
              key={i}
              className={`hline__seg hline__seg--${r.state}`}
              style={{
                left: `${r.start * step}%`,
                width: `${Math.max(r.end - r.start, 0.6) * step}%`,
              }}
              title={`${r.state} · ${hhmm(pts[r.start].valid_time_utc)}–${hhmm(pts[r.end].valid_time_utc)}`}
            />
          ))}
        </div>
        <div className="hline__ticks">
          {ticks.map((i) => (
            <button
              key={i}
              type="button"
              className={i === active ? "hline__tick on" : "hline__tick"}
              style={{ left: `${i * step}%` }}
              onMouseEnter={() => setTick(i)}
              onFocus={() => setTick(i)}
              aria-label={`${i === 0 ? "now" : `plus ${i} hours`}, ${hhmm(pts[i].valid_time_utc)}, p50 ${pts[i].p50_mw.toFixed(1)} megawatts`}
            >
              {i === 0 ? "now" : `+${i}h`}
            </button>
          ))}
        </div>
        <p className="hline__read" aria-live="polite">
          {read}
        </p>
      </div>

      <div className="csum__chips">
        {surplus && (
          <span className="chip chip--ok">
            <i />
            Surplus {hhmm(pts[surplus.start].valid_time_utc)}–{hhmm(pts[surplus.end].valid_time_utc)} · charge storage
          </span>
        )}
        {shortage && (
          <span className="chip chip--warn">
            <i />
            Shortage {hhmm(pts[shortage.start].valid_time_utc)}–{hhmm(pts[shortage.end].valid_time_utc)} · hold backup
          </span>
        )}
        <span className={`chip chip--${reli.tone}`}>
          <i />
          <b>{reli.band}</b> risk · ≈{reli.expectedLossMwh} MWh at risk
        </span>
      </div>
    </div>
  );
}
