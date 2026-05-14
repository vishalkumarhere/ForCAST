"""
Data loader that prefers the Berkeley xlsx and falls back to the legacy
per-registry scrapers if the Berkeley file is missing.

Coordinate assignment uses the centroid CSVs in data/ (built one time by
running tools/build_centroids.py). If those don't exist, the projects come
back without coordinates and the map shows a "no centroid data" message.

Returns a dict with:
    "projects": DataFrame of US IFM projects, with latitude/longitude/location_precision
    "vintage":  long-format (project_id, year, credits) by vintage year
    "issuance": long-format (project_id, year, credits) by issuance year
"""

from __future__ import annotations

import logging

import pandas as pd

from berkeley import load_us_ifm
from config import (
    BERKELEY_XLSX,
    COUNTY_CENTROIDS_CSV,
    EXCLUDED_STATES,
    IFM_TYPES,
    PROJECT_LOCATIONS_CSV,
    STATE_CENTROIDS_CSV,
    US_COUNTRIES,
)
from geocode import add_coordinates

logger = logging.getLogger(__name__)


def _empty_year_long() -> pd.DataFrame:
    return pd.DataFrame({"project_id": [], "year": [], "credits": []})


def _attach_coords(projects: pd.DataFrame) -> pd.DataFrame:
    return add_coordinates(
        projects,
        state_centroids_path=STATE_CENTROIDS_CSV,
        county_centroids_path=COUNTY_CENTROIDS_CSV,
        project_locations_path=PROJECT_LOCATIONS_CSV,
    )


def _try_legacy_scrapers() -> dict[str, pd.DataFrame] | None:
    """Best-effort fallback: import the legacy scrapers package if it exists."""
    try:
        from scrapers.load_data import load_all_projects  # type: ignore
    except ImportError:
        logger.warning("Legacy scrapers package not found.")
        return None

    logger.info("Loading projects via legacy scrapers (Berkeley file missing).")
    projects = load_all_projects()
    projects = projects[~projects["state"].astype(str).str.upper().isin(EXCLUDED_STATES)]
    projects = _attach_coords(projects)
    return {
        "projects": projects,
        "vintage": _empty_year_long(),
        "issuance": _empty_year_long(),
    }


def load_all() -> dict[str, pd.DataFrame]:
    try:
        data = load_us_ifm(
            xlsx_path=BERKELEY_XLSX,
            ifm_types=IFM_TYPES,
            us_countries=US_COUNTRIES,
            excluded_states=EXCLUDED_STATES,
        )
        data["projects"] = _attach_coords(data["projects"])
        return data
    except FileNotFoundError as exc:
        logger.warning("Berkeley file missing: %s", exc)
        fallback = _try_legacy_scrapers()
        if fallback is not None:
            return fallback
        return {
            "projects": pd.DataFrame(),
            "vintage": _empty_year_long(),
            "issuance": _empty_year_long(),
        }
