import { Link } from "react-router-dom";
import type { ReactNode } from "react";

/** Arrow glyph reused by button variants. */
export function ArrowIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
      strokeWidth={1.5}
      stroke="currentColor"
      aria-hidden="true"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M4.5 12h15m0 0l-6.75-6.75M19.5 12l-6.75 6.75"
      />
    </svg>
  );
}

/** HUD-style pill CTA (the refined closing call-to-action). */
export function HudButton({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="btn-hud">
      <span className="btn-hud__label">{children}</span>
      <span className="btn-hud__icon" aria-hidden="true">
        <svg viewBox="0 0 16 19" xmlns="http://www.w3.org/2000/svg">
          <path d="M7 18C7 18.5523 7.44772 19 8 19C8.55228 19 9 18.5523 9 18H7ZM8.70711 0.292893C8.31658 -0.0976311 7.68342 -0.0976311 7.29289 0.292893L0.928932 6.65685C0.538408 7.04738 0.538408 7.68054 0.928932 8.07107C1.31946 8.46159 1.95262 8.46159 2.34315 8.07107L8 2.41421L13.6569 8.07107C14.0474 8.46159 14.6805 8.46159 15.0711 8.07107C15.4616 7.68054 15.4616 7.04738 15.0711 6.65685L8.70711 0.292893ZM9 18L9 1H7L7 18H9Z" />
        </svg>
      </span>
    </Link>
  );
}

/** Ghost / solid buttons used in hero + body. */
export function Button({
  to,
  variant = "solid",
  children,
  onClick,
  type,
  disabled,
}: {
  to?: string;
  variant?: "solid" | "ghost";
  children: ReactNode;
  onClick?: () => void;
  type?: "button" | "submit";
  disabled?: boolean;
}) {
  const cls = `btn ${variant === "ghost" ? "btn--ghost" : ""}`;
  if (to) {
    return (
      <Link to={to} className={cls}>
        {children}
      </Link>
    );
  }
  return (
    <button type={type ?? "button"} onClick={onClick} disabled={disabled} className={cls}>
      {children}
    </button>
  );
}