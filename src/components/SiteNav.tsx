import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { ArrowIcon } from "./ui";

const NAV_LINKS: { to: string; label: string }[] = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/dashboard/forecast", label: "Forecast" },
  { to: "/#flow", label: "Approach" },
  { to: "/#modules", label: "Modules" },
];

export function SiteHeader({ hidden = false }: { hidden?: boolean }) {
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(() => typeof window !== "undefined" && window.scrollY > 24);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const isActive = (to: string) => {
    if (to.includes("#") || to.includes("?")) return false;
    return pathname === to;
  };

  return (
    <header className={["nav", open && "open", scrolled && "nav--scrolled", hidden && "nav--hidden"].filter(Boolean).join(" ")} id="nav">
      <div className="nav__inner">
        <Link to="/" className="brand" aria-label="re-forecast home">
          re-forecast
        </Link>
        <nav className="nav__links" aria-label="Primary">
          {NAV_LINKS.map((l) => {
            const active = isActive(l.to);
            return (
              <Link
                key={l.label}
                to={l.to}
                className={active ? "active" : undefined}
                aria-current={active ? "page" : undefined}
                onClick={() => setOpen(false)}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>
        <div className="nav__cta">
          <Link to="/dashboard" className="btn-arrow" aria-label="Open dashboard">
            <ArrowIcon />
            <span className="text" style={{ lineHeight: 1 }}>
              Launch dashboard
            </span>
          </Link>
          <button
            className="nav__toggle"
            aria-label="Menu"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
          >
            <span></span>
            <span></span>
            <span></span>
          </button>
        </div>
      </div>
    </header>
  );
}
