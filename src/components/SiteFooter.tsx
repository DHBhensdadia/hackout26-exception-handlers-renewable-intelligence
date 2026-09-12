import { Link } from "react-router-dom";

export function SiteFooter() {
  const year = new Date().getFullYear();
  return (
    <footer className="footer">
      <div className="wrap">
        <div className="footer__top">
          <div className="footer__brand">
            <Link to="/" className="brand">
              re-forecast
            </Link>
            <p>
              Renewable energy intelligence &amp; decision support — forecast solar
              and wind 24–72 hours ahead, then use that forecast to plan.
            </p>
            <div className="footer__social" aria-label="re-forecast on social media">
              <a href="#" aria-label="re-forecast on LinkedIn">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-2-2 2 2 0 0 0-2 2v7h-4v-7a6 6 0 0 1 6-6z" />
                  <rect width="4" height="12" x="2" y="9" />
                  <circle cx="4" cy="4" r="2" />
                </svg>
              </a>
              <a href="#" aria-label="re-forecast on X">
                <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                  <path d="M17.53 3h3.06l-6.69 7.64L21.75 21h-6.16l-4.83-6.31L5.24 21H2.18l7.16-8.17L2.25 3h6.32l4.36 5.77L17.53 3Zm-1.07 16.17h1.7L7.62 4.74H5.8l10.66 14.43Z" />
                </svg>
              </a>
              <a href="#" aria-label="re-forecast on GitHub">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 4 5 4 5 4c-.3 1.15-.3 2.35 0 3.5A5.4 5.4 0 0 0 4 11c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4" />
                  <path d="M9 18c-4.51 2-5-2-7-2" />
                </svg>
              </a>
            </div>
          </div>
          <div className="footer__col">
            <h4>Product</h4>
            <Link to="/dashboard">Forecast Dashboard</Link>
            <Link to="/dashboard">Site Registry</Link>
            <Link to="#models">Models</Link>
            <Link to="#approach">Approach</Link>
          </div>
          <div className="footer__col">
            <h4>Platform</h4>
            <Link to="#horizons">Planning Horizons</Link>
            <Link to="#modules">Seven Modules</Link>
            <Link to="#mvp">MVP Phases</Link>
            <Link to="#stack">Tech Stack</Link>
          </div>
          <div className="footer__col">
            <h4>Company</h4>
            <Link to="/dashboard">Dashboard</Link>
            <Link to="/#approach">About</Link>
            <Link to="/#modules">Capabilities</Link>
            <Link to="/#cta">Contact</Link>
          </div>
        </div>
        <div className="footer__bottom">
          <span>
            © {year} re-forecast — renewable energy intelligence platform
          </span>
          <span className="footmark">re-forecast</span>
        </div>
      </div>
    </footer>
  );
}