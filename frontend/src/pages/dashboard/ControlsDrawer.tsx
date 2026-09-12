import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import { useDashboardContext } from "@/hooks/useDashboardContext";
import { ControlsPanel } from "@/components/dashboard/ControlsPanel";

/** Right-hand run configuration drawer, built on the native <dialog> element. */
export function ControlsDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const { sites, form, patch, run, loading, jsonPreview } = useDashboardContext();

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className="drawer"
      aria-label="Run settings"
      onClose={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
    >
      <div className="drawer__panel">
        <header className="drawer__head">
          <span>Run settings</span>
          <button type="button" onClick={onClose} aria-label="Close run settings">
            <X size={16} aria-hidden="true" />
          </button>
        </header>
        <div className="drawer__body">
          <ControlsPanel
            sites={sites}
            form={form}
            onChange={patch}
            onRun={() => {
              run();
              onClose();
            }}
            loading={loading}
          />
          <details className="rail__json">
            <summary>Request preview</summary>
            <pre>{jsonPreview}</pre>
          </details>
        </div>
      </div>
    </dialog>
  );
}
