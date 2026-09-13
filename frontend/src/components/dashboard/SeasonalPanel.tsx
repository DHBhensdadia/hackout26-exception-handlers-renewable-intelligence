import type { DerivedDashboard } from "@/hooks/useDashboard";

/** §05 — Module 3: seasonal pattern analysis (spec §9). */
export function SeasonalPanel({ derived }: { derived: DerivedDashboard }) {
  const { months, notes } = derived.seasonal;
  const max = Math.max(...months.map((m) => Math.max(m.gen, m.demand)), 1);

  return (
    <>
      <div className="seasonal">
        {months.map((m) => (
          <div className={`seasonal__col seasonal__col--${m.pattern}`} key={m.month}>
            <span className="seasonal__m">{m.month}</span>
            <div className="seasonal__bars" title={`${m.gen}% generation · ${m.demand}% demand index`}>
              <i className="sb sb--gen" style={{ height: `${(m.gen / max) * 100}%` }} />
              <i className="sb sb--dem" style={{ height: `${(m.demand / max) * 100}%` }} />
            </div>
            <span className="seasonal__v">{m.gen}%</span>
          </div>
        ))}
      </div>

      <div className="chart-legend">
        <span>
          <i className="sw" style={{ background: "var(--accent-2)", border: 0, height: 8 }} /> generation (% of potential)
        </span>
        <span>
          <i className="sw" style={{ background: "var(--text-muted)", border: 0, height: 8 }} /> demand index
        </span>
        <span>
          <i className="sw sw--line" style={{ color: "var(--c-green)" }} /> surplus month
        </span>
      </div>

      <div className="notes-grid">
        {notes.map((note) => (
          <div className="note-row" key={note.title}>
            <span className="note-row__k">{note.title}</span>
            <span className="note-row__v">{note.body}</span>
          </div>
        ))}
      </div>
    </>
  );
}
