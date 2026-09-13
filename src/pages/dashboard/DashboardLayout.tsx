import { Suspense, useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Menu, Play } from "lucide-react";
import { DashboardProvider, useDashboardContext } from "@/hooks/useDashboardContext";
import { Sidebar } from "./Sidebar";
import { ControlsDrawer } from "./ControlsDrawer";
import { ConsoleSummary } from "./ConsoleSummary";
import { MODULES } from "./modules";

const Spark = (
  <svg className="macbar__fav" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M12 3v4M12 17v4M3 12h4M17 12h4" />
    <path d="M12 7.5 13.6 11 17 12l-3.4 1L12 16.5 10.4 13 7 12l3.4-1z" />
  </svg>
);

function Shell() {
  const { pathname } = useLocation();
  const { run, loading, result, form } = useDashboardContext();
  const [navOpen, setNavOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  // Lock background scroll while the off-canvas nav is open.
  useEffect(() => {
    document.documentElement.style.overflow = navOpen ? "hidden" : "";
    return () => {
      document.documentElement.style.overflow = "";
    };
  }, [navOpen]);

  useEffect(() => {
    if (!navOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setNavOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [navOpen]);

  const def = MODULES.find((m) => m.to === pathname) ?? MODULES[0];
  const horizon = result?.points.length ?? form.horizon_h;
  const site = result?.site_id ?? form.site_id;
  const tech = result?.tech ?? form.tech;
  const title = def.bar ? def.bar({ tech, h: horizon }) : def.title;

  return (
    <div className="console-page">
      <div className="appwin">
        <div className="macbar">
          <span className="macbar__lights" aria-hidden="true">
            <i className="r" />
            <i className="y" />
            <i className="g" />
          </span>
          <span className="macbar__title">
            {Spark}
            <b>
              re-forecast — {horizon} h forecast · {site}
            </b>
          </span>
          <span className="macbar__tools">
            <button
              type="button"
              className="macbar__tool"
              aria-label="Open modules"
              aria-expanded={navOpen}
              onClick={() => setNavOpen(true)}
            >
              <Menu size={16} aria-hidden="true" />
            </button>
            <button type="button" className="macbar__tool" aria-label="Run forecast" onClick={run} disabled={loading}>
              <Play size={15} aria-hidden="true" />
            </button>
          </span>
        </div>

        <div className="appwin__grid">
          <Sidebar open={navOpen} onClose={() => setNavOpen(false)} onOpenSettings={() => setSettingsOpen(true)} />

          <div className="appwin__body">
            <div className="appwin__bar">
              <h1 className="appwin__bar-title">{title}</h1>
              <span className="appwin__bar-meta">{result?.model_version ?? "xgb-q"} · p10/p50/p90</span>
            </div>

            <ConsoleSummary />

            <main className="appwin__content" id="main-content">
              <Suspense
                fallback={
                  <div className="module__empty" role="status" aria-live="polite">
                    <span className="module__empty-k">loading</span>
                    <p>Loading module…</p>
                  </div>
                }
              >
                <Outlet />
              </Suspense>
            </main>
          </div>
        </div>

        {navOpen && <button type="button" className="console-scrim" aria-label="Close menu" onClick={() => setNavOpen(false)} />}

        <ControlsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      </div>
    </div>
  );
}

export default function DashboardLayout() {
  return (
    <DashboardProvider>
      <Shell />
    </DashboardProvider>
  );
}
