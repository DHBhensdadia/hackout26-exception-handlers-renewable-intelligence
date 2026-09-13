import { useEffect, useRef, useState } from "react";
import { Link, NavLink } from "react-router-dom";
import { ArrowUpRight, Check, ChevronDown, Play, SlidersHorizontal } from "lucide-react";
import { useDashboardContext } from "@/hooks/useDashboardContext";
import { MODULES } from "./modules";

const navClass = ({ isActive }: { isActive: boolean }) => (isActive ? "on" : undefined);

/** App sidebar: site switcher, module nav, and the run controls footer. */
export function Sidebar({
  open,
  onClose,
  onOpenSettings,
}: {
  open: boolean;
  onClose: () => void;
  onOpenSettings: () => void;
}) {
  const { sites, form, pickSite, result, loading, run } = useDashboardContext();
  const [menu, setMenu] = useState(false);
  const head = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menu) return;
    const onDoc = (e: MouseEvent) => {
      if (head.current && !head.current.contains(e.target as Node)) setMenu(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [menu]);

  const current = sites.find((s) => s.site_id === (result?.site_id ?? form.site_id));

  return (
    <aside className={open ? "appwin__side open" : "appwin__side"}>
      <div className="appwin__brand-wrap" ref={head}>
        <button
          type="button"
          className="appwin__brand"
          aria-haspopup="menu"
          aria-expanded={menu}
          onClick={() => setMenu((m) => !m)}
        >
          <span className="mk" aria-hidden="true" />
          console
          <ChevronDown className={menu ? "cv cv--open" : "cv"} size={15} aria-hidden="true" />
        </button>

        {menu && (
          <div className="appwin__menu" role="menu">
            <span className="appwin__menu-cap">Registered sites</span>
            {sites.map((s) => {
              const on = s.site_id === (result?.site_id ?? form.site_id);
              return (
                <button
                  key={s.site_id}
                  type="button"
                  role="menuitemradio"
                  aria-checked={on}
                  onClick={() => {
                    pickSite(s);
                    setMenu(false);
                    onClose();
                  }}
                >
                  <span className="tid">{s.site_id}</span>
                  {on && <Check size={14} aria-hidden="true" />}
                </button>
              );
            })}
            <Link to="/" role="menuitem">
              <span className="tid">Landing page</span>
              <ArrowUpRight size={14} aria-hidden="true" />
            </Link>
          </div>
        )}
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
        <button type="button" className="appwin__btn appwin__btn--ghost" onClick={onOpenSettings}>
          <SlidersHorizontal className="ic" size={14} aria-hidden="true" />
          Run settings
        </button>
        <button type="button" className="appwin__btn appwin__btn--solid" onClick={run} disabled={loading}>
          <Play className="ic" size={13} aria-hidden="true" />
          {loading ? "Running…" : "Run forecast"}
        </button>
        {current && <span className="appwin__region">{current.region}</span>}
      </div>
    </aside>
  );
}
