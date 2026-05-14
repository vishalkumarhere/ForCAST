"""
Berkeley Carbon Trading Project loader.

Reads the Voluntary Registry Offsets Database (v2026-02 schema) and returns
US Improved Forest Management projects in a normalized shape.

Schema notes (verified against v2026-02 PROJECTS tab):
- Header is on row 4 (zero-indexed row 3). Rows 1-3 are banner text and
  filter formulas.
- The PROJECTS tab has ~170 meaningful columns. Everything beyond column 169
  is empty padding.
- Several headers contain embedded line breaks (e.g. "Total Credits \\nIssued");
  we normalize by replacing newlines with spaces.
- The years 1996-2026 appear in 4 separate column blocks:
    cols 23-53   Credits Issued by Vintage Year
    cols 54-84   Credits Retired or Cancelled
    cols 86-116  Credits Remaining by Vintage
    cols 134-164 Credits Issued by Issuance Year
  Pandas suffixes duplicate column names (1996, 1996.1, 1996.2, 1996.3), so we
  use positional iloc slicing rather than name-based lookup for the year blocks.
- There is NO project area / acreage column in this dataset. The closest
  size metric is "Estimated Annual Emissions Reductions" (tCO2e/yr).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# Column index ranges (0-indexed) for the four year-blocks of 1996-2026
_VINTAGE_COLS = (23, 54)     # [start, stop) — 31 years: 1996..2026
_RETIRED_COLS = (54, 85)     # [start, stop)
_REMAINING_COLS = (86, 117)  # [start, stop)
_ISSUANCE_COLS = (134, 165)  # [start, stop)

_YEARS = list(range(1996, 2027))  # 1996..2026 inclusive — matches Berkeley schema


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Strip embedded newlines and double-spaces from string column names."""
    df = df.copy()
    df.columns = [
        " ".join(str(c).split()) if isinstance(c, str) else c
        for c in df.columns
    ]
    return df


def _melt_year_block(
    df: pd.DataFrame,
    project_id_col: str,
    start: int,
    stop: int,
    value_name: str,
) -> pd.DataFrame:
    """
    Take a slice of year columns and return long-format:
        project_id | year | <value_name>
    """
    block = df.iloc[:, start:stop].copy()
    block.columns = _YEARS  # overwrite the pandas-suffixed names with bare years
    block[project_id_col] = df[project_id_col].values
    long = block.melt(
        id_vars=[project_id_col],
        var_name="year",
        value_name=value_name,
    )
    # Normalize the id column name to match what the rest of the app expects
    long = long.rename(columns={project_id_col: "project_id"})
    long["project_id"] = long["project_id"].astype(str)
    long[value_name] = pd.to_numeric(long[value_name], errors="coerce").fillna(0)
    long["year"] = long["year"].astype(int)
    return long


def load_us_ifm(
    xlsx_path: Path,
    ifm_types: set[str],
    us_countries: set[str],
    excluded_states: set[str],
) -> dict[str, pd.DataFrame]:
    """
    Load the Berkeley xlsx and return a dict with:

      "projects":  one row per US IFM project, normalized column names
      "vintage":   long-format (project_id, year, credits) by vintage year
      "issuance":  long-format (project_id, year, credits) by issuance year

    Raises FileNotFoundError if xlsx_path doesn't exist (so the caller can
    fall back to scrapers).
    """
    xlsx_path = Path(xlsx_path)
    if not xlsx_path.exists():
        raise FileNotFoundError(
            f"Berkeley xlsx not found at {xlsx_path}. "
            f"Download the latest version from "
            f"https://gspp.berkeley.edu/berkeley-carbon-trading-project/offsets-database"
        )

    logger.info("Loading Berkeley xlsx from %s", xlsx_path)
    raw = pd.read_excel(
        xlsx_path,
        sheet_name="PROJECTS",
        header=3,          # row 4 holds the headers
        usecols=range(170),  # everything after col 169 is empty padding
        engine="openpyxl",
    )
    raw = _normalize_columns(raw)

    # ---- filter to US IFM (excluding configured states) -----------------
    mask = (
        raw["Type"].isin(ifm_types)
        & raw["Country"].isin(us_countries)
        & ~raw["State"].astype(str).str.upper().isin({s.upper() for s in excluded_states})
    )
    df = raw[mask].copy().reset_index(drop=True)
    logger.info("Filtered to %d US IFM projects", len(df))

    # ---- build the long-format time-series tables ------------------------
    # Must extract BEFORE renaming columns, since we rely on positional slicing
    vintage_long = _melt_year_block(
        df, project_id_col="Project ID",
        start=_VINTAGE_COLS[0], stop=_VINTAGE_COLS[1],
        value_name="credits",
    )
    issuance_long = _melt_year_block(
        df, project_id_col="Project ID",
        start=_ISSUANCE_COLS[0], stop=_ISSUANCE_COLS[1],
        value_name="credits",
    )

    # ---- build the normalized projects table ------------------------------
    projects = pd.DataFrame({
        "project_id":   df["Project ID"].astype(str),
        "name":         df["Project Name"].astype(str),
        "registry":     df["Voluntary Registry"].astype(str),
        "status":       df["Voluntary Status"].astype(str),
        "scope":        df["Scope"].astype(str),
        "type":         df["Type"].astype(str),
        "protocol":     df["Methodology / Protocol"].astype(str),
        "developer":    df["Project Developer"].astype(str),
        "owner":        df["Project Owner"].astype(str),
        "country":      df["Country"].astype(str),
        "state":        df["State"].astype(str).str.title(),  # uppercase -> title
        "site_location": df["Project Site Location"].astype(str),
        "credits_issued":    pd.to_numeric(df["Total Credits Issued"], errors="coerce").fillna(0),
        "credits_retired":   pd.to_numeric(df["Total Credits Retired"], errors="coerce").fillna(0),
        "credits_remaining": pd.to_numeric(df["Total Credits Remaining"], errors="coerce").fillna(0),
        "buffer_pool":       pd.to_numeric(df["Total Buffer Pool Deposits"], errors="coerce").fillna(0),
        "estimated_annual_reductions": pd.to_numeric(
            df["Estimated Annual Emission Reductions"], errors="coerce"
        ).fillna(0),
        "first_vintage_year": pd.to_numeric(
            df["First Year of Project (Vintage)"], errors="coerce"
        ),
        "project_listed":     df["Project Listed"].astype(str),
        "project_registered": df["Project Registered"].astype(str),
        "registry_documents": df["Registry Documents"].astype(str),
        "project_website":    df["Project Website"].astype(str),
    })

    # Project Site Location is freeform text. The legacy app expected a `county`
    # column for filter parity; use the same text for now (best available).
    projects["county"] = projects["site_location"]

    return {
        "projects": projects,
        "vintage": vintage_long,
        "issuance": issuance_long,
    }
