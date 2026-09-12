"""Site registry: the lookup from site_id to physical metadata.

Holds two kinds of site:

  * GEFCom2014 training zones. Anonymised in the source data, so their coordinates are
    recovered by fitting (see physics/fit_location.py) and flagged
    `location_is_estimated=True`. Placeholder coordinates are written here at scaffold
    time and overwritten by the fit.

  * Real Gujarat demo sites, used to show the cold-start path. These have true
    coordinates and are deliberately absent from training data.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from reip.config import get_settings
from reip.schemas import SiteMeta, Tech


class SiteNotFound(KeyError):
    """Raised when a site_id is not in the registry."""


class SiteRegistry:
    """In-memory registry loaded from YAML.

    Ad-hoc sites (a lat/lon the caller invents at request time) are not stored here;
    the API builds a transient `SiteMeta` for those. This class covers named sites only.
    """

    def __init__(self, sites: dict[str, SiteMeta]) -> None:
        self._sites = sites

    @classmethod
    def load(cls, path: Path | None = None) -> SiteRegistry:
        path = path or get_settings().sites_file
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        sites: dict[str, SiteMeta] = {}
        for entry in raw.get("sites", []):
            meta = SiteMeta(**entry).defaulted
            if meta.site_id in sites:
                raise ValueError(f"duplicate site_id in {path}: {meta.site_id}")
            sites[meta.site_id] = meta
        return cls(sites)

    def get(self, site_id: str) -> SiteMeta:
        try:
            return self._sites[site_id]
        except KeyError as exc:
            raise SiteNotFound(
                f"unknown site_id {site_id!r}; known: {sorted(self._sites)}"
            ) from exc

    def by_tech(self, tech: Tech) -> list[SiteMeta]:
        return [s for s in self._sites.values() if s.tech is tech]

    def all(self) -> list[SiteMeta]:
        return list(self._sites.values())

    def __contains__(self, site_id: object) -> bool:
        return site_id in self._sites

    def __len__(self) -> int:
        return len(self._sites)
