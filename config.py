"""
Configuration for the IFM Carbon Credit Dashboard.

Primary data source: Berkeley Carbon Trading Project's Voluntary Registry Offsets
Database (v2026-02), filtered to US Improved Forest Management projects.

Fallback: manually collected per-registry CSVs (ACR, CAR, Verra), used only if
the Berkeley file is missing.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Data files
# ---------------------------------------------------------------------------
DATA_DIR = Path("data")

# Primary source: Berkeley Carbon Trading Project xlsx
# Bundled with the app; update manually by replacing this file with the latest
# version from https://gspp.berkeley.edu/berkeley-carbon-trading-project/offsets-database
BERKELEY_XLSX = DATA_DIR / "Voluntary-Registry-Offsets-Database--v2026-02.xlsx"
BERKELEY_VERSION = "v2026-02"

# Fallback per-registry CSVs (used only if BERKELEY_XLSX is missing)
ACR_CSV = DATA_DIR / "acr.csv"
CAR_CSV = DATA_DIR / "CAR.csv"
VERRA_CSV = DATA_DIR / "verra.csv"

# Geocoding cache (kept for backwards compat; no longer used by primary path)
GEOCACHE_PATH = DATA_DIR / "geocache.json"

# Centroid CSVs produced by tools/build_centroids.py (one-time setup)
STATE_CENTROIDS_CSV = DATA_DIR / "state_centroids.csv"
COUNTY_CENTROIDS_CSV = DATA_DIR / "county_centroids.csv"
# Per-project site-location geocoding cache (also built by build_centroids.py)
PROJECT_LOCATIONS_CSV = DATA_DIR / "project_locations.csv"

# State policy markdown files (one .md per state, e.g. michigan.md)
STATE_POLICY_DIR = DATA_DIR / "state_policies"

# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
# Type values in the Berkeley DB that count as IFM (exact-match strings)
IFM_TYPES = {"Improved Forest Management"}

# Countries to keep
US_COUNTRIES = {"United States"}

# States to exclude (current behavior keeps Alaska out of the dashboard)
EXCLUDED_STATES = {"ALASKA"}

# ---------------------------------------------------------------------------
# Registry labels
# ---------------------------------------------------------------------------
REGISTRY_LABELS = {
    "ACR": "ACR (American Carbon Registry)",
    "CAR": "CAR (Climate Action Reserve)",
    "Verra": "Verra (VCS)",
    "VCS": "Verra (VCS)",
}

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
APP_TITLE = "ForCAST: Forest Carbon Assessment and Statutory Tracker"
PAGE_SIZE = 50

# ---------------------------------------------------------------------------
# Data citation (shown in app footer)
# ---------------------------------------------------------------------------
BERKELEY_CITATION = (
    "Haya, B. K., Quartson, P., Bernard, T., Abayo, A., Rong, X., So, I. S., "
    "Elias, M. (2026). Voluntary Registry Offsets Database v2026-02, "
    "Berkeley Carbon Trading Project, University of California, Berkeley. "
    "Retrieved from https://gspp.berkeley.edu/berkeley-carbon-trading-project/"
    "offsets-database. Used under CC BY 4.0."
)
