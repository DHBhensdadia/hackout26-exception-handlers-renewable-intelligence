import { useEffect, useRef, useState } from "react";
import { Link, NavLink } from "react-router-dom";
import { ArrowUpRight, Check, ChevronDown, Play, SlidersHorizontal } from "lucide-react";
import { useDashboardContext } from "@/hooks/useDashboardContext";
import { MODULES } from "./modules";

const navClass = ({ isActive }: { isActive: boolean }) => (isActive ? "mod on" : "mod");

/** Left console sidebar: app/site switcher, module nav, and the run footer. */
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
    <aside className={open ? "sidebar open" : "sidebar"}>
      <div className="sidebar__head" ref={head}>
        <button
          type="button"
          className="switcher"
          aria-haspopup="menu"
          aria-expanded={menu}
          onClick={() => setMenu((m) => !m)}
        >
          <span className="switcher__logo" aria-hidden="true" />
          <span className="switcher__label">console</span>
          <ChevronDown className="switcher__chev" size={16} aria-hidden="true" />
        </button>

        {menu && (
          <div className="switcher__menu" role="menu">
            <span className="switcher__menu-cap">Registered sites</span>
            {sites.map((s) => {
              const on = s.site_id === (result?.site_id ?? form.site_id);
              return (
                <button
                  key={s.site_id}
                  type="button"
                  role="menuitemradio"
                  aria-checked={on}
                  className={on ? "switcher__item on" : "switcher__item"}
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
            <Link to="/" className="switcher__item" role="menuitem">
              <span className="tid">Landing page</span>
              <ArrowUpRight size={14} aria-hidden="true" />
            </Link>
          </div>
        )}
      </div>

      <div className="sidebar__cap">Modules</div>

      <nav className="sidebar__nav" aria-label="Modules">
        {MODULES.map(({ to, label, n, Icon }) => (
          <NavLink key={to} to={to} end={to === "/dashboard"} className={navClass} onClick={onClose}>
            <Icon size={16} strokeWidth={1.6} aria-hidden="true" />
            <span>{label}</span>
            <span className="n">{n}</span>
          </NavLink>
        ))}
      </nav>

      <div className="sidebar__foot">
        <div className="runline">
          <span className={result ? "dot on" : "dot"} />
          <span>{result ? `${result.site_id} · ${result.tech} · ${result.points.length} h` : loading ? "running…" : "idle"}</span>
        </div>
        <button type="button" className="sidebar__ctrl" onClick={onOpenSettings}>
          <SlidersHorizontal size={15} aria-hidden="true" />
          Run settings
        </button>
        <button type="button" className="sidebar__run" onClick={run} disabled={loading}>
          <Play size={14} aria-hidden="true" />
          {loading ? "Running…" : "Run forecast"}
        </button>
        {current && <span className="sidebar__note">{current.region}</span>}
      </div>
    </aside>
  );
}
