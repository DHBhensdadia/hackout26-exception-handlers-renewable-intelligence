import type { SiteRecord } from "@/types";
import { fmt } from "@/lib/format";

/**
 * GET /sites — the registry table. "Genuinely unseen" sites (not in training
 * data) are highlighted; each row can load straight into the forecast.
 */
export function SitesTable({
  sites,
  onPick,
  activeId,
}: {
  sites: SiteRecord[];
  onPick: (site: SiteRecord) => void;
  activeId: string | null;
}) {
  return (
    <div className="itable" style={{ fontSize: ".84rem" }}>
      <div className="itable__head">
        <span>Site</span>
        <span>Tech</span>
        <span>Capacity</span>
        <span>Status</span>
        <span>Run</span>
      </div>
      {sites.map((s) => (
        <div
          key={s.site_id}
          className="itable__row"
          style={{
            cursor: "pointer",
            background: activeId === s.site_id ? "var(--surface-2)" : "transparent",
            display: "grid",
            gridTemplateColumns: "2.2fr .9fr 1fr .8fr .7fr",
            alignItems: "center",
            gap: ".6rem",
            padding: ".6rem .6rem",
            borderBottom: "1px solid var(--hairline)",
            transition: "background .2s",
          }}
          onClick={() => onPick(s)}
        >
          <span className="nm" style={{ display: "flex", alignItems: "center", gap: ".55rem", minWidth: 0 }}>
            <span className="dot" style={{
              width: 10, height: 10, borderRadius: 3, flex: "none",
              background: s.tech === "solar" ? "var(--c-amber)" : "var(--c-blue)",
            }} />
            <span style={{ minWidth: 0 }}>
              <span className="mono" style={{ color: "var(--text)", display: "block", fontSize: ".82rem" }}>{s.site_id}</span>
              <span style={{ color: "var(--text-muted)", display: "block", fontSize: ".72rem" }}>{s.name} · {s.region}</span>
            </span>
          </span>
          <span className="mono" style={{ color: "var(--text-secondary)", textTransform: "uppercase", fontSize: ".7rem", letterSpacing: ".04em" }}>{s.tech}</span>
          <span className="mono" style={{ color: "var(--text-secondary)" }}>{fmt(s.capacity_mw, 0)} MW</span>
          <span>
            {s.in_training_data ? (
              <span className="pill pill--ok">trained</span>
            ) : (
              <span className="pill pill--warn">unseen</span>
            )}
          </span>
          <button
            className="btn btn--sm"
            onClick={(e) => { e.stopPropagation(); onPick(s); }}
            style={{ padding: ".35rem .7rem", fontSize: ".74rem", justifySelf: "start" }}
          >
            Run →
          </button>
        </div>
      ))}
    </div>
  );
}