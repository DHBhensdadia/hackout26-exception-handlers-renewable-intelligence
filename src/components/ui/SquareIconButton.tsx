import type { ReactNode } from "react";

/** Square, un-rounded icon button — the reference FAQ control, dark-theme form. */
export function SquareIconButton({
  label,
  open,
  onClick,
  children,
}: {
  label: string;
  open?: boolean;
  onClick?: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      className={`sqbtn${open ? " sqbtn--on" : ""}`}
      aria-label={label}
      aria-pressed={open}
      onClick={onClick}
    >
      {children}
    </button>
  );
}
