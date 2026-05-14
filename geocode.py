"""
County / state centroid lookup for Berkeley project locations.

This module does NOT call any external service at app runtime. It reads
pre-built CSV files produced by `tools/build_centroids.py`:

    data/state_centroids.csv   columns: state, latitude, longitude
    data/county_centroids.csv  columns: state, county, latitude, longitude

For each project, we attempt to map its `site_location` text to a county
within the project's `state`. If that fails, we fall back to the state
centroid. If both fail, the project is left without coordinates.

A new `location_precision` column is added to the projects DataFrame with
one of: "county", "state", "state-jittered", "none".

Overlapping state-centroid points are jittered slightly so they don't fully
occlude each other on the map. Jitter is deterministic per project (seeded
from project_id) so the same project always lands in the same spot.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# Roughly ~5 miles at typical US latitudes. Small enough to keep pins in-state,
# large enough to be visually distinct on a continent-scale map.
_JITTER_DEGREES = 0.08


def _norm(s) -> str:
    """Normalize a name for case-insensitive matching. Safe against NaN/None."""
    if s is None:
        return ""
    if isinstance(s, float) and math.isnan(s):
        return ""
    return re.sub(r"\s+", " ", str(s).strip().lower())


def _load_state_centroids(path: Path) -> dict[str, tuple[float, float]]:
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    out: dict[str, tuple[float, float]] = {}
    for _, row in df.iterrows():
        key = _norm(row.get("state"))
        if not key:
            continue
        try:
            out[key] = (float(row["latitude"]), float(row["longitude"]))
        except (TypeError, ValueError):
            continue
    return out


def _load_project_locations(path: Path) -> dict[str, tuple[float, float]]:
    """Load per-project geocoded coordinates keyed by project_id.

    Rows where latitude/longitude are NaN are sentinel "tried but failed"
    entries written by build_centroids.py and are skipped here so the
    county/state fallback chain still applies.
    """
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    out: dict[str, tuple[float, float]] = {}
    for _, row in df.iterrows():
        pid = str(row.get("project_id", "")).strip()
        if not pid:
            continue
        try:
            lat = float(row["latitude"])
            lon = float(row["longitude"])
        except (TypeError, ValueError):
            continue
        if math.isnan(lat) or math.isnan(lon):
            continue  # failed geocode sentinel — skip, allow fallback
        out[pid] = (lat, lon)
    return out


def _load_county_centroids(path: Path) -> dict[tuple[str, str], tuple[float, float]]:
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    out: dict[tuple[str, str], tuple[float, float]] = {}
    for _, row in df.iterrows():
        state_key = _norm(row.get("state"))
        county_key = _norm(row.get("county"))
        if not state_key or not county_key:
            continue
        try:
            out[(state_key, county_key)] = (
                float(row["latitude"]),
                float(row["longitude"]),
            )
        except (TypeError, ValueError):
            continue
    return out


def extract_county_candidates(site_location: str) -> list[str]:
    """
    Pull county-name candidates out of a freeform site-location string.

    Strategy: find each occurrence of "<chunk> Count(y/ies)" or "<chunk>
    Parish(es)" in the text, then split the chunk on commas and the word "and".
    This handles patterns like:

        "Flathead County"                  -> ["Flathead"]
        "Yuba and Butte Counties"          -> ["Yuba", "Butte"]
        "Marquette County, Michigan"       -> ["Marquette"]
        "Wise, Dickenson, Russell, and Buchannan Counties"
            -> ["Wise", "Dickenson", "Russell", "Buchannan"]

    Returns an empty list when no county/parish word is present.
    """
    if not isinstance(site_location, str) or not site_location.strip():
        return []

    # Find each occurrence of "<chunk> County(ies)" or "<chunk> Parish(es)".
    # The chunk is non-greedy and bounded behind by a capital letter so we
    # don't suck in arbitrary prose.
    matches = re.finditer(
        r"([A-Z][a-zA-Z'.,\- ]*?)\s+(?:Count(?:y|ies)|Parish(?:es)?)\b",
        site_location,
        re.IGNORECASE,
    )

    out: list[str] = []
    for m in matches:
        chunk = m.group(1).strip()
        # Strip a leading "the" or trailing comma if any
        chunk = re.sub(r"^[Tt]he\s+", "", chunk).rstrip(",").strip()
        # Split on commas or the word "and" (with optional leading comma)
        parts = re.split(r"\s*,\s*(?:and\s+)?|\s+and\s+", chunk)
        for p in parts:
            p = p.strip().strip(",").strip()
            # Reject: empty, single letter, all-caps state-abbreviation noise,
            # and anything starting with a lowercase letter (likely junk)
            if (
                p
                and len(p) > 1
                and not re.fullmatch(r"[A-Z]{2,3}", p)
                and p[0].isupper()
            ):
                out.append(p)
    return out


def _jitter(project_id: str, lat: float, lng: float) -> tuple[float, float]:
    """
    Deterministic small offset around (lat, lng) seeded by project_id.

    Same project_id always produces the same offset, so re-running the loader
    doesn't move pins around between renders.
    """
    h = hashlib.md5(str(project_id).encode("utf-8")).digest()
    # Map first 4 bytes to an angle, next 4 to a radius factor in [0, 1]
    angle_seed = int.from_bytes(h[:4], "big") / 0xFFFFFFFF
    radius_seed = int.from_bytes(h[4:8], "big") / 0xFFFFFFFF
    angle = angle_seed * 2 * math.pi
    radius = _JITTER_DEGREES * math.sqrt(radius_seed)  # sqrt for uniform area
    return (lat + radius * math.sin(angle), lng + radius * math.cos(angle))


def add_coordinates(
    projects: pd.DataFrame,
    state_centroids_path: Path,
    county_centroids_path: Path,
    project_locations_path: Path | None = None,
) -> pd.DataFrame:
    """
    Add `latitude`, `longitude`, and `location_precision` columns to projects.

    `location_precision` values:
        "site"            - geocoded directly from site_location text (most accurate)
        "county"          - matched a county centroid
        "state"           - fell back to state centroid (first project in state)
        "state-jittered"  - state centroid with jitter (additional projects in state)
        "none"            - no centroid available
    """
    df = projects.copy()
    project_lookup = _load_project_locations(project_locations_path) if project_locations_path else {}
    state_lookup = _load_state_centroids(state_centroids_path)
    county_lookup = _load_county_centroids(county_centroids_path)

    if not project_lookup and not state_lookup and not county_lookup:
        logger.warning(
            "No centroid files found. Run tools/build_centroids.py to populate "
            "data/state_centroids.csv and data/county_centroids.csv."
        )
        df["latitude"] = pd.NA
        df["longitude"] = pd.NA
        df["location_precision"] = "none"
        return df

    latitudes: list[float | None] = []
    longitudes: list[float | None] = []
    precisions: list[str] = []

    # Track how many projects we've already placed at each state-centroid so
    # additional ones get jittered to avoid full overlap.
    state_centroid_use_count: dict[str, int] = {}

    for _, row in df.iterrows():
        state_raw = str(row.get("state") or "").strip()
        site_loc = str(row.get("site_location") or "").strip()
        project_id = str(row.get("project_id") or "")

        # Multi-state strings ("West Virginia; Virginia") -> use the first
        state_for_lookup = state_raw.split(";")[0].strip()
        state_key = _norm(state_for_lookup) if state_for_lookup else ""

        # Priority 1: per-project site-location geocode
        coords: tuple[float, float] | None = None
        precision = "none"
        if project_id in project_lookup:
            coords = project_lookup[project_id]
            precision = "site"

        # Priority 2: county centroid
        if coords is None:
            for candidate in extract_county_candidates(site_loc):
                key = (state_key, _norm(candidate))
                if key in county_lookup:
                    coords = county_lookup[key]
                    precision = "county"
                    break

        # Fall back to state centroid
        if coords is None and state_key in state_lookup:
            coords = state_lookup[state_key]
            use_count = state_centroid_use_count.get(state_key, 0)
            if use_count == 0:
                precision = "state"
            else:
                # Jitter every project after the first to spread the pins
                coords = _jitter(project_id, coords[0], coords[1])
                precision = "state-jittered"
            state_centroid_use_count[state_key] = use_count + 1

        if coords is not None:
            latitudes.append(coords[0])
            longitudes.append(coords[1])
            precisions.append(precision)
        else:
            latitudes.append(None)
            longitudes.append(None)
            precisions.append("none")

    df["latitude"] = latitudes
    df["longitude"] = longitudes
    df["location_precision"] = precisions
    return df
