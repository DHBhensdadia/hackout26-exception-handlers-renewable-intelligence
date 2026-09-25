import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

/**
 * Annotation callout — the console's voice for caveats, assumptions and empty states.
 * A left accent rule and mono caption separate it from the ruled data grid around it.
 */
export function Callout({
  tone = "info",
  label,
  icon: Icon,
  children,
}: {
  tone?: "info" | "warn" | "empty" | "muted";
  label?: string;
  icon?: LucideIcon;
  children: ReactNode;
}) {
  return (
    <div className={`callout callout--${tone}`} role="note">
      {Icon && (
        <span className="callout__ico" aria-hidden="true">
          <Icon size={15} strokeWidth={1.8} />
        </span>
      )}
      <div className="callout__body">
        {label && <span className="callout__k">{label}</span>}
        <p className="callout__v">{children}</p>
      </div>
    </div>
  );
}
