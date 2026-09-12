"""Join AEMO generation to lead-resolved weather and write the canonical training corpus.

The last step of the data rebuild. Generation comes from `ingest.aemo` (real metered
output, 155 plants, true coordinates); weather comes from `ingest.weather_bulk` (what the
forecast said 24, 48 and 72 hours beforehand). This module aligns them and writes the
canonical weather parquet the trainer reads.

The join is the point where a lead-resolved corpus differs from the old one. Generation is
observed once per hour, but weather now exists three times per hour - once per lead - so
each observed hour becomes three training rows. That is what finally lets the model see
that a 72-hour-old forecast is worse than a 24-hour-old one, instead of assuming it.

Because quota limits mean the weather fetch can stop part-way, the join is written to
tolerate partial coverage: sites without weather are reported and excluded rather than
silently producing a corpus that looks complete and is not.
"""

from __future__ import annotations

import logging

import pandas as pd

from reip.config import get_settings
from reip.ingest.weather_bulk import LEAD_DAYS, fetch_sites
from reip.schemas import Tech, validate_weather
from reip.sites.registry import SiteRegistry

log = logging.getLogger(__name__)


def build(
    start_date: str,
    end_date: str,
    *,
    techs: list[Tech] | None = None,
    leads: tuple[int, ...] = LEAD_DAYS,
    batch_size: int = 1,
    limit: int | None = None,
    source: str = "previous_runs",
    corpus: str = "aemo",
) -> dict[str, object]:
    """Fetch weather for every AEMO site with generation data and write canonical parquet.

    `corpus` names the weather half of the output. It exists so a re-fetch under different
    terms - a different source, or different lead days - lands beside the existing corpus
    instead of on top of it, leaving the two directly comparable. The power half is shared
    and never rewritten, because the generation data does not change when the weather does.
    """
    settings = get_settings()
    settings.ensure_dirs()
    registry = SiteRegistry.load()
    summary: dict[str, object] = {}

    for tech in techs or list(Tech):
        power_path = settings.data_canonical / f"aemo_{tech.value}_power.parquet"
        if not power_path.exists():
            log.warning("no AEMO %s power; run `python -m reip.ingest.aemo` first", tech.value)
            continue

        power = pd.read_parquet(power_path)
        wanted = sorted(power["site_id"].unique())
        sites = [registry.get(s) for s in wanted if s in registry]
        if limit:
            sites = sites[:limit]

        log.info("%s: fetching weather for %d sites", tech.value, len(sites))
        weather, progress = fetch_sites(
            sites, start_date, end_date, leads=leads, batch_size=batch_size, source=source
        )

        if progress.failed:
            log.warning("%s: %d sites failed", tech.value, len(progress.failed))
        if progress.quota_hit:
            log.warning(
                "%s: stopped on quota with %d/%d sites; re-run to resume from cache",
                tech.value,
                progress.total,
                len(sites),
            )

        covered = set(weather["site_id"].unique())
        missing = sorted(set(wanted) - covered)
        if missing:
            log.warning("%s: %d sites have no weather and are excluded", tech.value, len(missing))

        validated = validate_weather(weather, name=f"{corpus}-{tech.value}")
        out_path = settings.data_canonical / f"{corpus}_{tech.value}_weather.parquet"
        validated.to_parquet(out_path, index=False)

        # The power corpus is deliberately NOT rewritten to match. `assemble` already skips
        # any site missing either half, so filtering here would buy nothing - and an
        # interrupted or `--limit`ed run would permanently truncate the expensive
        # generation corpus to whatever subset that run happened to cover.

        summary[tech.value] = {
            "weather_rows": len(validated),
            "power_rows": int(power["site_id"].isin(covered).sum()),
            "sites": len(covered),
            "leads": sorted(validated["horizon_h"].unique().tolist()),
            "missing_sites": missing,
            "quota_hit": progress.quota_hit,
        }
        log.info(
            "%s: %s weather rows, %d sites, horizons %s",
            tech.value,
            f"{len(validated):,}",
            len(covered),
            sorted(validated["horizon_h"].unique().tolist()),
        )

    return summary


if __name__ == "__main__":
    import argparse
    import json

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Build the AEMO + weather training corpus")
    parser.add_argument("--start", default="2025-09-01")
    parser.add_argument("--end", default="2026-08-31")
    parser.add_argument("--tech", action="append", choices=[t.value for t in Tech])
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--source", default="previous_runs", choices=["previous_runs", "historical_forecast"])
    parser.add_argument(
        "--corpus",
        default="aemo",
        help="name for the weather half; use a new name to keep an existing corpus intact",
    )
    args = parser.parse_args()

    result = build(
        args.start,
        args.end,
        techs=[Tech(t) for t in args.tech] if args.tech else None,
        batch_size=args.batch_size,
        limit=args.limit,
        source=args.source,
        corpus=args.corpus,
    )
    print(json.dumps(result, indent=2, default=str)[:2000])
