import { Link, NavLink } from "react-router-dom";
import { ArrowUpRight, Play } from "lucide-react";
import { useDashboardContext } from "@/hooks/useDashboardContext";
import { MODULES } from "./modules";

const navClass = ({ isActive }: { isActive: boolean }) => (isActive ? "on" : undefined);

/** App sidebar: module nav, the console trigger, and the run controls footer. */
export function Sidebar({
  open,
  onClose,
  onOpenSettings,
}: {
  open: boolean;
  onClose: () => void;
  onOpenSettings: () => void;
}) {
  const { sites, form, result, loading, run } = useDashboardContext();

  const current = sites.find((s) => s.site_id === (result?.site_id ?? form.site_id));

  return (
    <aside className={open ? "appwin__side open" : "appwin__side"}>
      <div className="appwin__brand-wrap">
        <button
          type="button"
          className="appwin__brand"
          aria-label="Open run settings"
          onClick={onOpenSettings}
        >
          <span className="mk" aria-hidden="true" />
          console
        </button>
      </div>

      <div className="appwin__grp">Modules</div>

      <nav className="appwin__nav" aria-label="Modules">
        {MODULES.map(({ to, label, n, Icon }) => (
          <NavLink key={to} to={to} end={to === "/dashboard"} className={navClass} onClick={onClose}>
            <span className="em">
              <Icon className="ic" size={15} aria-hidden="true" />
            </span>
            {label}
            <span className="n">{n}</span>
          </NavLink>
        ))}
      </nav>

      <div className="appwin__foot">
        <div className="appwin__status">
          <span className={result ? "dot on" : "dot"} />
          <span>{result ? `${result.site_id} · ${result.tech} · ${result.points.length} h` : loading ? "running…" : "idle"}</span>
        </div>
        <Link className="appwin__btn appwin__btn--ghost" to="/">
          <ArrowUpRight className="ic" size={14} aria-hidden="true" />
          Landing page
        </Link>
        <button type="button" className="appwin__btn appwin__btn--solid" onClick={run} disabled={loading}>
          <Play className="ic" size={13} aria-hidden="true" />
          {loading ? "Running…" : "Run forecast"}
        </button>
        {current && <span className="appwin__region">{current.region}</span>}
      </div>
    </aside>
  );
}
