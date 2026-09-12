"""Command-line forecasting. Point it at any coordinates and get a 72-hour forecast.

Exists so the model can be exercised without running a server or hand-writing JSON. The
API remains the interface Phase 2 modules build against; this is the same prediction path
with a human-readable front end, so what it prints is exactly what `/forecast` returns.

    python -m reip.cli --lat 23.03 --lon 72.57 --tech solar --capacity 50
    python -m reip.cli --site GJ-WIND-KUTCH --hours 24
    python -m reip.cli --lat 23.9 --lon 71.2 --tech solar --capacity 730 --format csv
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

import pandas as pd

from reip.ingest.openmeteo import WeatherUnavailable, fetch_forecast
from reip.models.predict import ArtifactMissing, load_model, predict_site
from reip.schemas import MAX_HORIZON_H, SiteForecast, SiteMeta, Tech
from reip.sites.registry import SiteNotFound, SiteRegistry


def resolve_site(args: argparse.Namespace) -> SiteMeta:
    """Turn CLI arguments into site metadata, registered or ad hoc."""
    registry = SiteRegistry.load()

    if args.site:
        try:
            site = registry.get(args.site)
        except SiteNotFound as exc:
            raise SystemExit(f"error: {exc}") from exc
        overrides = {k: v for k, v in (("capacity_mw", args.capacity),) if v is not None}
        return site.model_copy(update=overrides).defaulted if overrides else site

    missing = [n for n, v in (("--lat", args.lat), ("--lon", args.lon), ("--capacity", args.capacity)) if v is None]
    if missing:
        raise SystemExit(f"error: need --site, or all of {', '.join(missing)}")

    return SiteMeta(
        site_id=f"adhoc-{args.lat:.4f},{args.lon:.4f}",
        name="Ad-hoc site",
        tech=Tech(args.tech),
        capacity_mw=args.capacity,
        latitude=args.lat,
        longitude=args.lon,
        tilt_deg=args.tilt,
        azimuth_deg=args.azimuth,
        hub_height_m=args.hub_height,
    ).defaulted


def render_table(forecast: SiteForecast, site: SiteMeta) -> str:
    """Human-readable forecast with a bar showing the p10-p90 band."""
    capacity = forecast.capacity_mw
    lines = [
        "",
        f"  {site.name or forecast.site_id}  ({forecast.site_id})",
        f"  {forecast.tech.value} | {capacity:,.0f} MW | {site.latitude:.4f}, {site.longitude:.4f}",
        f"  issued {forecast.issue_time_utc:%Y-%m-%d %H:%MZ} | model {forecast.model_version}"
        f" | weather {forecast.weather_source}",
        "",
        "   h  valid (UTC)        p10      p50      p90   clearsky        0 ── forecast ── cap",
        "  " + "-" * 92,
    ]

    for point in forecast.points:
        # The bar shows the uncertainty band, not just the median: its width is the part
        # an operator acts on.
        width = 24
        lo = int(round(width * point.p10_mw / capacity))
        mid = int(round(width * point.p50_mw / capacity))
        hi = int(round(width * point.p90_mw / capacity))
        bar = "".join(
            "|" if i == mid else ("=" if lo <= i <= hi else ("." if i < lo else " "))
            for i in range(width)
        )
        lines.append(
            f"  {point.horizon_h:2d}  {point.valid_time_utc:%m-%d %H:%M}"
            f"  {point.p10_mw:7.2f}  {point.p50_mw:7.2f}  {point.p90_mw:7.2f}"
            f"  {point.clearsky_mw:9.2f}   [{bar}]"
        )

    frame = forecast.to_frame()
    energy = frame["p50_mw"].sum()
    lines += [
        "  " + "-" * 92,
        f"  energy (p50): {energy:,.0f} MWh over {len(forecast.points)} h"
        f"  |  capacity factor {100 * energy / (capacity * len(forecast.points)):.1f}%"
        f"  |  peak {frame['p50_mw'].max():,.1f} MW",
        "",
        "  p50 is the forecast; p10-p90 is an 80% confidence band.",
        "  Plan shortages against p10 and size storage against p90.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m reip.cli",
        description="24-72 hour solar and wind power forecast for any location.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("\n\n")[-1],
    )
    parser.add_argument("--site", help="registered site id (see --list)")
    parser.add_argument("--lat", type=float, help="latitude, decimal degrees")
    parser.add_argument("--lon", type=float, help="longitude, decimal degrees")
    parser.add_argument("--tech", choices=[t.value for t in Tech], default="solar")
    parser.add_argument("--capacity", type=float, help="installed capacity, MW")
    parser.add_argument("--hours", type=int, default=MAX_HORIZON_H, help="horizon, 1-72")
    parser.add_argument("--tilt", type=float, help="solar panel tilt, degrees")
    parser.add_argument("--azimuth", type=float, help="solar panel azimuth, degrees")
    parser.add_argument("--hub-height", type=float, help="wind turbine hub height, m")
    parser.add_argument("--format", choices=["table", "json", "csv"], default="table")
    parser.add_argument("--list", action="store_true", help="list registered sites and exit")
    args = parser.parse_args(argv)

    if args.list:
        for site in sorted(SiteRegistry.load().all(), key=lambda s: s.site_id):
            trained = "trained-on" if site.site_id.startswith(("AEMO-", "GEFCOM-")) else "unseen"
            print(
                f"  {site.site_id:24s} {site.tech.value:6s} {site.capacity_mw:8,.0f} MW  "
                f"{site.latitude:8.3f},{site.longitude:9.3f}  {trained}  {site.name}"
            )
        return 0

    if not 1 <= args.hours <= MAX_HORIZON_H:
        raise SystemExit(f"error: --hours must be 1-{MAX_HORIZON_H}")

    site = resolve_site(args)

    try:
        load_model(site.tech)
    except (ArtifactMissing, FileNotFoundError) as exc:
        raise SystemExit(f"error: {exc}") from exc

    issue_time = pd.Timestamp(datetime.now(UTC)).floor("h")
    try:
        weather = fetch_forecast(site, horizon_h=args.hours, issue_time=issue_time)
    except WeatherUnavailable as exc:
        raise SystemExit(f"error: weather unavailable: {exc}") from exc

    forecast = predict_site(weather, site, issue_time=issue_time)

    if args.format == "json":
        print(forecast.model_dump_json(indent=2))
    elif args.format == "csv":
        forecast.to_frame().to_csv(sys.stdout, index=False)
    else:
        print(render_table(forecast, site))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
