import type { ReactNode } from "react";
import { Section } from "@/components/dashboard/Section";
import type { ModuleDef } from "./modules";

/** One module page: §-numbered header (as the page h1) + ruled body. */
export function ModulePage({ def, children }: { def: ModuleDef; children: ReactNode }) {
  return (
    <Section id={`mod-${def.n}`} index={def.n} title={def.title} meta={def.meta} titleAs="h1">
      <div className="module__flow">{children}</div>
    </Section>
  );
}

function Skeleton() {
  return (
    <div className="module__skeleton" aria-hidden="true">
      <div className="module__skeleton-cells">
        {Array.from({ length: 4 }).map((_, i) => (
          <span key={i} className="sk sk--cell" />
        ))}
      </div>
      <span className="sk sk--chart" />
      <span className="sk sk--line" />
      <span className="sk sk--line sk--short" />
    </div>
  );
}

/** Shared empty/loading/error state for every module. */
export function ModuleEmpty({
  loading,
  error,
  onRetry,
}: {
  loading: boolean;
  error: string | null;
  onRetry?: () => void;
}) {
  if (loading) {
    return (
      <div className="module__empty" role="status" aria-live="polite" aria-busy="true">
        <span className="module__empty-k">running</span>
        <p>Running quantile forecast models…</p>
        <Skeleton />
      </div>
    );
  }

  if (error) {
    return (
      <div className="module__empty module__empty--error" role="alert">
        <span className="module__empty-k">error</span>
        <p>{error}</p>
        {onRetry && (
          <button type="button" className="btn btn--sm" onClick={onRetry}>
            Retry forecast
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="module__empty" role="status">
      <span className="module__empty-k">idle</span>
      <p>Configure inputs and run a forecast.</p>
    </div>
  );
}
