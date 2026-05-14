"""
One-shot build script: populate the centroid CSVs used by the map.

Run this once after installing the app:

    python tools/build_centroids.py

It walks the Berkeley dataset, finds every (state, county) pair mentioned in
project site-location strings, geocodes them via OpenStreetMap Nominatim, and
writes:

    data/state_centroids.csv
    data/county_centroids.csv

Both files are caches. Re-running the script only geocodes pairs that aren't
already in the CSVs, so it's safe to run repeatedly when you add new data.

Requirements (already in requirements.txt):
    geopy>=2.4
    pandas>=2.0
    openpyxl>=3.1

Nominatim usage policy is 1 request/second. The script throttles itself.
Total runtime for a fresh build: ~3-5 minutes for typical Berkeley coverage.
"""

from __future__ import annotations

import logging
import re
import sys
import time
from pathlib import Path

import pandas as pd

# Allow running from project root or from inside tools/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from berkeley import load_us_ifm  # noqa: E402
from config import (  # noqa: E402
    BERKELEY_XLSX,
    DATA_DIR,
    EXCLUDED_STATES,
    IFM_TYPES,
    US_COUNTRIES,
)
from geocode import extract_county_candidates  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

STATE_CSV = DATA_DIR / "state_centroids.csv"
COUNTY_CSV = DATA_DIR / "county_centroids.csv"
PROJECT_LOCS_CSV = DATA_DIR / "project_locations.csv"

NOMINATIM_USER_AGENT = "forcast-ifm-dashboard (build_centroids.py)"
NOMINATIM_DELAY_SECONDS = 1.1  # slightly over the 1/sec policy cap


def _geocode_site_location(
    geocoder,
    site_location: str,
    state: str,
    delay: float,
) -> tuple[float, float] | None:
    """
    Try to geocode a freeform site_location string via Nominatim.

    Takes only the first clause of multi-part strings (split on ';' or newline)
    and appends the state + "United States" if not already present. Validates
    that the returned address actually mentions the expected state.
    """
    text = re.sub(r"\s+", " ", site_location.strip())
    # Use only the first clause for long / multi-part strings
    for sep in (";", "\n", " - "):
        if sep in text:
            text = text.split(sep)[0].strip()
    if len(text) < 5:
        return None

    # Build query candidates: with state appended, then without
    queries: list[str] = []
    if state and state.lower() not in text.lower():
        queries.append(f"{text}, {state}, United States")
    queries.append(f"{text}, United States")

    for query in queries:
        try:
            result = geocoder.geocode(query[:250], country_codes="us", timeout=10)
        except Exception as exc:
            logger.warning("  Geocode failed for %r: %s", query[:60], exc)
            result = None
        time.sleep(delay)
        if result is None:
            continue
        address = (getattr(result, "address", "") or "").lower()
        # Validate: result must be in the expected state
        if state and state.lower() not in address:
            logger.debug(
                "  Skipping result for %r — state %r not in address %r",
                text[:40], state, address[:80],
            )
            continue
        return (result.latitude, result.longitude)

    return None


def _load_existing(path: Path, key_cols: list[str]) -> dict[tuple, dict]:
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    out = {}
    for _, row in df.iterrows():
        key = tuple(str(row[c]).lower().strip() for c in key_cols)
        out[key] = row.to_dict()
    return out


def _write(path: Path, rows: dict[tuple, dict], columns: list[str]) -> None:
    df = pd.DataFrame(list(rows.values()))
    if df.empty:
        df = pd.DataFrame(columns=columns)
    df = df[columns].sort_values(columns[: len(columns) - 2])
    df.to_csv(path, index=False)


def main() -> int:
    try:
        from geopy.geocoders import Nominatim
    except ImportError:
        logger.error("geopy is required. Install with: pip install geopy")
        return 1

    geocoder = Nominatim(user_agent=NOMINATIM_USER_AGENT)

    # ---- Load Berkeley data -------------------------------------------------
    logger.info("Loading Berkeley data to discover (state, county) pairs...")
    data = load_us_ifm(
        xlsx_path=BERKELEY_XLSX,
        ifm_types=IFM_TYPES,
        us_countries=US_COUNTRIES,
        excluded_states=EXCLUDED_STATES,
    )
    projects = data["projects"]
    logger.info("Loaded %d US IFM projects.", len(projects))

    # ---- Build the work list ------------------------------------------------
    state_set: set[str] = set()
    county_pairs: set[tuple[str, str]] = set()
    for _, row in projects.iterrows():
        state_raw = str(row.get("state") or "").strip()
        site_loc = str(row.get("site_location") or "").strip()
        for s in state_raw.split(";"):
            s = s.strip()
            if s:
                state_set.add(s)
        # Counties only need to be resolved within the project's first state
        first_state = state_raw.split(";")[0].strip()
        if first_state:
            for c in extract_county_candidates(site_loc):
                county_pairs.add((first_state, c))

    logger.info(
        "Discovered %d distinct states and %d distinct (state, county) pairs.",
        len(state_set),
        len(county_pairs),
    )

    # ---- Load existing caches -----------------------------------------------
    state_rows = _load_existing(STATE_CSV, ["state"])
    county_rows = _load_existing(COUNTY_CSV, ["state", "county"])

    states_to_fetch = [s for s in sorted(state_set) if (s.lower(),) not in state_rows]
    counties_to_fetch = [
        (s, c) for (s, c) in sorted(county_pairs)
        if (s.lower(), c.lower()) not in county_rows
    ]
    logger.info(
        "Need to fetch %d states and %d counties (existing cache: %d states, %d counties).",
        len(states_to_fetch),
        len(counties_to_fetch),
        len(state_rows),
        len(county_rows),
    )

    # ---- Geocode states -----------------------------------------------------
    for state in states_to_fetch:
        if not isinstance(state, str) or not state.strip():
            logger.warning("  Skipping empty/invalid state value: %r", state)
            continue
        state = state.strip()
        query = f"{state}, United States"
        logger.info("Geocoding state: %s", query)
        try:
            result = geocoder.geocode(query, country_codes="us", timeout=10)
        except Exception as exc:
            logger.warning("  Failed: %s", exc)
            result = None
        time.sleep(NOMINATIM_DELAY_SECONDS)
        if result is None:
            logger.warning("  No result for state %r", state)
            continue
        # Sanity check: result must actually mention the state we asked for
        display = (getattr(result, "address", "") or "").lower()
        if state.lower() not in display:
            logger.warning(
                "  Result for %r looks wrong: %r. Skipping.",
                state, getattr(result, "address", None),
            )
            continue
        state_rows[(state.lower(),)] = {
            "state": state,
            "latitude": result.latitude,
            "longitude": result.longitude,
        }
        # Write after every successful fetch so partial runs are preserved
        _write(STATE_CSV, state_rows, ["state", "latitude", "longitude"])

    # ---- Geocode counties ---------------------------------------------------
    for state, county in counties_to_fetch:
        if not isinstance(state, str) or not state.strip():
            continue
        if not isinstance(county, str) or not county.strip():
            continue
        state = state.strip()
        county = county.strip()
        # Add "County" suffix for the query, since Berkeley strips it
        suffix = "Parish" if state.lower() == "louisiana" else "County"
        query = f"{county} {suffix}, {state}, United States"
        logger.info("Geocoding county: %s", query)
        try:
            result = geocoder.geocode(query, country_codes="us", timeout=10)
        except Exception as exc:
            logger.warning("  Failed: %s", exc)
            result = None
        time.sleep(NOMINATIM_DELAY_SECONDS)
        if result is None:
            logger.warning("  No result for %s, %s", county, state)
            continue
        # Sanity check: result must actually mention the state we asked for
        display = (getattr(result, "address", "") or "").lower()
        if state.lower() not in display:
            logger.warning(
                "  Result for %s, %s looks wrong: %r. Skipping.",
                county, state, getattr(result, "address", None),
            )
            continue
        county_rows[(state.lower(), county.lower())] = {
            "state": state,
            "county": county,
            "latitude": result.latitude,
            "longitude": result.longitude,
        }
        _write(COUNTY_CSV, county_rows, ["state", "county", "latitude", "longitude"])

    # ---- Per-project site-location geocoding --------------------------------
    # This gives finer accuracy than county centroids for projects whose
    # site_location names a specific forest, wilderness, or named place.
    proj_rows = _load_existing(PROJECT_LOCS_CSV, ["project_id"])
    projects_to_geocode = [
        row for _, row in projects.iterrows()
        if (str(row["project_id"]).lower(),) not in proj_rows
        and str(row.get("site_location") or "").strip() not in ("", "nan")
    ]
    logger.info(
        "Need to geocode %d projects by site_location (%d already cached).",
        len(projects_to_geocode),
        len(proj_rows),
    )

    for row in projects_to_geocode:
        pid = str(row["project_id"])
        site_loc = str(row.get("site_location") or "").strip()
        state = str(row.get("state") or "").strip().split(";")[0].strip()

        logger.info("Geocoding project %s: %r", pid, site_loc[:60])
        coords = _geocode_site_location(geocoder, site_loc, state, NOMINATIM_DELAY_SECONDS)
        if coords is None:
            logger.info("  No result — will fall back to county/state centroid at runtime.")
            # Store a sentinel so we don't retry on future runs
            proj_rows[(pid.lower(),)] = {
                "project_id": pid,
                "site_location": site_loc[:200],
                "latitude": float("nan"),
                "longitude": float("nan"),
            }
        else:
            logger.info("  → (%.4f, %.4f)", coords[0], coords[1])
            proj_rows[(pid.lower(),)] = {
                "project_id": pid,
                "site_location": site_loc[:200],
                "latitude": coords[0],
                "longitude": coords[1],
            }
        _write(PROJECT_LOCS_CSV, proj_rows, ["project_id", "site_location", "latitude", "longitude"])

    logger.info("Done. Wrote %s, %s, and %s.", STATE_CSV, COUNTY_CSV, PROJECT_LOCS_CSV)
    return 0


if __name__ == "__main__":
    sys.exit(main())
