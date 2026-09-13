import type { RegionRecord } from "@/types";

/** Regional selector shared by the Seasonal and Demand modules. */
export function RegionPicker({
  regions,
  value,
  onChange,
}: {
  regions: RegionRecord[];
  value: string;
  onChange: (id: string) => void;
}) {
  return (
    <div className="rpick" role="tablist" aria-label="Region">
      {regions.map((r) => {
        const on = r.region_id === value;
        return (
          <button
            key={r.region_id}
            type="button"
            role="tab"
            aria-selected={on}
            className={on ? "active" : undefined}
            title={r.caveat ?? `${r.name} — nMAE ${r.nmae_pct} %, coverage ${r.coverage_pct} %`}
            onClick={() => onChange(r.region_id)}
          >
            {r.region_id}
            {r.caveat && <span className="rpick__flag" aria-label="known limitation" />}
          </button>
        );
      })}
    </div>
  );
}
