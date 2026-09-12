import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Menu, Play } from "lucide-react";
import { DashboardProvider, useDashboardContext } from "@/hooks/useDashboardContext";
import { Sidebar } from "./Sidebar";
import { ControlsDrawer } from "./ControlsDrawer";

function Shell() {
  const { pathname } = useLocation();
  const { run, loading } = useDashboardContext();
  const [navOpen, setNavOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  // Route change closes the mobile nav.
  useEffect(() => {
    setNavOpen(false);
  }, [pathname]);

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

  return (
    <div className="shell">
      <Sidebar open={navOpen} onClose={() => setNavOpen(false)} onOpenSettings={() => setSettingsOpen(true)} />

      {navOpen && <button type="button" className="shell__scrim" aria-label="Close menu" onClick={() => setNavOpen(false)} />}

      <div className="shell__main">
        <div className="shell__bar">
          <button
            type="button"
            className="shell__icon-btn"
            aria-label="Open modules"
            aria-expanded={navOpen}
            onClick={() => setNavOpen(true)}
          >
            <Menu size={17} aria-hidden="true" />
          </button>
          <span className="shell__bar-title">console</span>
          <button type="button" className="shell__icon-btn" aria-label="Run forecast" onClick={run} disabled={loading}>
            <Play size={15} aria-hidden="true" />
          </button>
        </div>

        <main className="shell__content">
          <Outlet />
        </main>
      </div>

      <ControlsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
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
