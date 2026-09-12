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

/** Shared empty/loading state for every module. */
export function ModuleEmpty({ loading, error }: { loading: boolean; error: string | null }) {
  return (
    <div className="module__empty" role="status">
      <span className="module__empty-k">{error ? "error" : loading ? "running" : "idle"}</span>
      <p>{error ?? (loading ? "Running quantile forecast models…" : "Configure inputs and run a forecast.")}</p>
    </div>
  );
}
