import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { ArrowIcon } from "./ui";

const NAV_LINKS: { to: string; label: string }[] = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/dashboard", label: "Forecast" },
  { to: "#", label: "Approach" },
  { to: "#", label: "Research" },
];

export function SiteHeader() {
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  const isActive = (to: string) =>
    pathname === to || (to !== "/" && pathname.startsWith(to + "/"));

  return (
    <header className={open ? "nav open" : "nav"} id="nav">
      <div className="nav__inner">
        <Link to="/" className="brand" aria-label="re-forecast home">
          re-forecast
        </Link>
        <nav className="nav__links" aria-label="Primary">
          {NAV_LINKS.map((l) => (
            <Link
              key={l.label}
              to={l.to}
              className={isActive(l.to) ? "active" : undefined}
            >
              {l.label}
            </Link>
          ))}
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

/**
 * Floating pill nav that slides in from the top after a few scrolls —
 * mirrors the reference site's secondary pinned navigation.
 */
export function NavPill() {
  const { pathname } = useLocation();
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const onScroll = () => {
      const y = window.scrollY || window.pageYOffset;
      const sh = y > 520;
      if (sh && !shown) setShown(true);
      else if (!sh && shown) setShown(false);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [shown]);

  useEffect(() => {
    setShown(false);
  }, [pathname]);

  const isActive = (to: string) => pathname === to;

  return (
    <div className={`navpill${shown ? " show" : ""}`} id="navpill" aria-label="Pinned navigation">
      <Link to="/" className="navpill__brand">
        re-forecast
      </Link>
      <nav className="navpill__links" aria-label="Primary">
        <Link to="/dashboard" className={isActive("/dashboard") ? "active" : undefined}>
          Dashboard
        </Link>
        <Link to="/dashboard" className={isActive("/dashboard") ? "active" : undefined}>
          Forecast
        </Link>
      </nav>
      <Link to="/dashboard" className="btn-arrow" aria-label="Open dashboard">
        <ArrowIcon />
        <span className="text" style={{ lineHeight: 1 }}>
          Launch
        </span>
      </Link>
    </div>
  );
}