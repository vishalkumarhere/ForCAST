"""
US IFM Carbon Credit Dashboard.

A Streamlit app surfacing US Improved Forest Management (IFM) carbon offset
projects from the Berkeley Carbon Trading Project's Voluntary Registry Offsets
Database. Includes credit issuance by vintage year and by issuance year, a
project map, and a state-policy reference section.

Run with:  streamlit run app.py
"""

import logging
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from config import (
    APP_TITLE,
    BERKELEY_CITATION,
    BERKELEY_VERSION,
    PAGE_SIZE,
    REGISTRY_LABELS,
    STATE_POLICY_DIR,
)
from data_loader import load_all
from pdf_search import (
    STATE_NAMES,
    extract_pages,
    list_pdf_files,
    list_pdfs_for_state,
    list_states,
    search_pdf,
)
from policies import list_states_with_policies, load_policy

logging.basicConfig(level=logging.INFO)


# ── Page config & theme ────────────────────────────────────────────────────
st.set_page_config(page_title="ForCAST", layout="wide")

# Michigan State colors: Spartan Green #18453B, White #FFFFFF
st.markdown("""
<style>
    .stApp { background-color: #18453B; }
    .stApp, .stApp p, .stApp label, .stApp span, .stApp li,
    .stMarkdown, .stMarkdown p { color: #FFFFFF; }
    .stApp h1, .stApp h2, .stApp h3, .stApp h4 { color: #FFFFFF; }

    section[data-testid="stSidebar"] { background-color: #0f2e27; }
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] span { color: #FFFFFF; }

    [data-testid="stMetricValue"] { color: #FFFFFF; }
    [data-testid="stMetricLabel"] { color: #FFFFFF; }

    .stTabs [data-baseweb="tab"] { color: #FFFFFF; }
    .stTabs [aria-selected="true"] { color: #FFFFFF; border-bottom-color: #FFFFFF; }

    hr { border-color: rgba(255,255,255,0.2); }

    /* Citation footer */
    .citation-footer {
        font-size: 0.8rem;
        opacity: 0.85;
        line-height: 1.4;
        padding-top: 0.5rem;
        border-top: 1px solid rgba(255,255,255,0.2);
    }
</style>
""", unsafe_allow_html=True)

# ── Header: logo (optional) + title ───────────────────────────────────────
_logo_path = next(
    (p for p in [Path("logo.png"), Path("logo.jpg"), Path("logo.jpeg")]
     if p.exists()),
    None,
)
if _logo_path:
    _col_logo, _col_title = st.columns([1, 8])
    with _col_logo:
        st.image(str(_logo_path))
    with _col_title:
        st.title(APP_TITLE)
else:
    st.title(APP_TITLE)


# ── Data loading ──────────────────────────────────────────────────────────
@st.cache_data(show_spinner="Loading project data...")
def _load():
    return load_all()


data = _load()
projects = data["projects"]
vintage_long = data["vintage"]
issuance_long = data["issuance"]


# ── Guard: empty data ────────────────────────────────────────────────────
if projects.empty:
    st.error(
        "No project data could be loaded. Place the Berkeley Voluntary Registry "
        "Offsets Database xlsx file at data/Voluntary-Registry-Offsets-Database--"
        f"{BERKELEY_VERSION}.xlsx, or ensure the legacy scrapers package is "
        "available."
    )
    st.stop()


# ── Sidebar: filters & citation ──────────────────────────────────────────
filtered = projects.copy()

with st.sidebar:
    st.header("Filters")

    # Registry
    registries = sorted(filtered["registry"].dropna().unique())
    sel_reg = st.multiselect(
        "Registry",
        options=registries,
        default=registries,
        format_func=lambda r: REGISTRY_LABELS.get(r, r),
    )
    filtered = filtered[filtered["registry"].isin(sel_reg)]

    # State
    states = sorted([s for s in filtered["state"].dropna().unique() if s])
    sel_states = st.multiselect("State (select to filter)", options=states, default=[])
    if sel_states:
        filtered = filtered[filtered["state"].isin(sel_states)]

    st.divider()
    st.markdown(
        "**Data source:** Berkeley Carbon Trading Project — "
        f"Voluntary Registry Offsets Database, {BERKELEY_VERSION}.  \n"
        "Filtered to **US Improved Forest Management** projects."
    )
    st.markdown(
        f'<div class="citation-footer">{BERKELEY_CITATION}</div>',
        unsafe_allow_html=True,
    )


# Project IDs selected by the current sidebar filters (used to scope the
# year-based time series tables)
selected_ids = set(filtered["project_id"].astype(str).tolist())


# ── KPI row ───────────────────────────────────────────────────────────────
st.divider()
k1, k2, k3 = st.columns(3)
k1.metric("IFM Projects", f"{len(filtered):,}")
k2.metric("Credits Issued (tCO2e)", f"{filtered['credits_issued'].sum():,.0f}")
k3.metric("Registries", filtered["registry"].nunique())


# ── Tabs ──────────────────────────────────────────────────────────────────
tab_map, tab_overview, tab_time, tab_table, tab_policy, tab_pdfsearch = st.tabs([
    "Map",
    "Overview",
    "Credits Over Time",
    "Project Table",
    "State Policies",
    "Policy PDF Search",
])


# ── Tab: Map ──────────────────────────────────────────────────────────────
with tab_map:
    st.subheader("US IFM Project Locations")
    map_data = filtered.dropna(subset=["latitude", "longitude"]).copy()

    if map_data.empty:
        if not (Path("data") / "state_centroids.csv").exists():
            st.warning(
                "No centroid data found. Run `python tools/build_centroids.py` "
                "once to populate `data/state_centroids.csv` and "
                "`data/county_centroids.csv`. The script uses OpenStreetMap "
                "Nominatim and takes a few minutes."
            )
        else:
            st.info("No projects with coordinates in the current filter selection.")
    else:
        # Counts by precision for the caption
        precision_counts = map_data["location_precision"].value_counts().to_dict()
        site_n = precision_counts.get("site", 0)
        county_n = precision_counts.get("county", 0)
        state_n = precision_counts.get("state", 0) + precision_counts.get("state-jittered", 0)
        st.caption(
            f"{len(map_data):,} of {len(filtered):,} projects mapped — "
            f"{site_n} at site location, {county_n} at county centroid, "
            f"{state_n} at state centroid "
            "(state-centroid points are jittered to reduce overlap; "
            "they do not represent precise locations)."
        )

        # Display label for the legend
        precision_display = {
            "site": "Site location",
            "county": "County centroid",
            "state": "State centroid",
            "state-jittered": "State centroid (jittered)",
        }
        map_data["Precision"] = map_data["location_precision"].map(precision_display)

        fig = px.scatter_map(
            map_data,
            lat="latitude",
            lon="longitude",
            color="Precision",
            color_discrete_map={
                "Site location": "#1B6CA8",
                "County centroid": "#18453B",
                "State centroid": "#E8500A",
                "State centroid (jittered)": "#E8500A",
            },
            hover_name="name",
            hover_data={
                "project_id": True,
                "registry": True,
                "state": True,
                "site_location": True,
                "credits_issued": ":,.0f",
                "latitude": False,
                "longitude": False,
                "Precision": False,
            },
            zoom=3,
            height=600,
        )
        fig.update_layout(
            map_style="carto-positron",
            margin={"l": 0, "r": 0, "t": 0, "b": 0},
            legend=dict(
                title="Precision",
                orientation="h",
                yanchor="bottom", y=0.01,
                xanchor="left", x=0.01,
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="rgba(0,0,0,0.2)",
                borderwidth=1,
                font=dict(color="#000000"),
            ),
        )
        st.plotly_chart(fig, use_container_width=True)


# ── Tab: Overview charts ──────────────────────────────────────────────────
with tab_overview:
    def _short_method(name):
        if pd.isna(name) or not name or name == "nan":
            return "Unknown"
        s = str(name)
        if "ARB Compliance" in s:
            version = s.rsplit(",", 1)[-1].strip() if "," in s else ""
            return f"ARB Compliance ({version})" if version else "ARB Compliance"
        s = s.replace("Improved Forest Management", "IFM")
        if len(s) > 40:
            s = s[:37] + "..."
        return s

    left, right = st.columns(2)

    with left:
        by_reg_method = (
            filtered.assign(
                Registry=filtered["registry"].map(lambda r: REGISTRY_LABELS.get(r, r)),
                Methodology=filtered["protocol"].map(_short_method),
            )
            .groupby(["Registry", "Methodology"])
            .size()
            .reset_index(name="Projects")
        )
        fig = px.bar(
            by_reg_method, x="Registry", y="Projects",
            color="Methodology",
            title="IFM Projects by Registry and Methodology",
        )
        fig.update_layout(
            legend=dict(
                title="Methodology",
                font=dict(size=10),
                orientation="h",
                yanchor="top", y=-0.3,
                xanchor="left", x=0,
            ),
            barmode="stack",
        )
        st.plotly_chart(fig, use_container_width=True)

    with right:
        by_state = (
            filtered["state"].replace("", pd.NA).dropna()
            .value_counts().head(15).reset_index()
        )
        by_state.columns = ["State", "Projects"]
        fig = px.bar(
            by_state, x="Projects", y="State",
            title="Top 15 States",
            orientation="h",
            color="Projects",
            color_continuous_scale="Greens",
        )
        fig.update_layout(yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig, use_container_width=True)

    cred_method = (
        filtered.assign(Methodology=filtered["protocol"].map(_short_method))
        .groupby("Methodology")["credits_issued"]
        .sum()
        .reset_index()
    )
    cred_method.columns = ["Methodology", "Credits Issued"]
    fig = px.pie(
        cred_method, values="Credits Issued", names="Methodology",
        title="IFM Credits Issued by Methodology",
    )
    fig.update_layout(legend=dict(font=dict(size=10)))
    st.plotly_chart(fig, use_container_width=True)


# ── Tab: Credits Over Time ────────────────────────────────────────────────
with tab_time:
    st.subheader("Credit Issuance Over Time")
    st.caption(
        "Berkeley publishes two complementary views of credit issuance over "
        "time: by **vintage year** (when the emission reduction or removal "
        "occurred) and by **issuance year** (when the registry issued the "
        "credits). They reconcile to the same totals but tell different "
        "stories about market timing."
    )

    view = st.radio(
        "Time view",
        options=["Vintage year", "Issuance year"],
        horizontal=True,
        help=(
            "Vintage = year the emission reduction occurred. "
            "Issuance = year the registry actually issued the credits "
            "(typically 1-3 years after vintage)."
        ),
    )

    if view == "Vintage year":
        long_df = vintage_long
        y_label = "Credits Issued by Vintage Year (tCO2e)"
    else:
        long_df = issuance_long
        y_label = "Credits Issued by Issuance Year (tCO2e)"

    if long_df.empty:
        st.warning(
            "Year-by-year credit data is not available. The Berkeley xlsx file "
            "is required for this view; the legacy CSV fallback does not "
            "include per-year breakdowns."
        )
    else:
        # Restrict to projects passing the sidebar filters
        scoped = long_df[long_df["project_id"].astype(str).isin(selected_ids)].copy()
        # Attach registry for color
        reg_map = dict(zip(filtered["project_id"].astype(str), filtered["registry"]))
        scoped["Registry"] = scoped["project_id"].astype(str).map(reg_map)

        # Aggregate
        agg = (
            scoped.groupby(["year", "Registry"], as_index=False)["credits"]
            .sum()
            .rename(columns={"credits": "Credits"})
        )

        # Drop years with zero across all registries (cleaner X axis)
        nonzero_years = agg.groupby("year")["Credits"].sum()
        keep_years = nonzero_years[nonzero_years > 0].index
        agg = agg[agg["year"].isin(keep_years)]

        if agg.empty:
            st.info("No credits issued for the current filter selection.")
        else:
            fig = px.bar(
                agg,
                x="year",
                y="Credits",
                color="Registry",
                title=y_label,
                labels={"year": "Year", "Credits": "Credits (tCO2e)"},
            )
            fig.update_layout(barmode="stack", xaxis=dict(dtick=1))
            st.plotly_chart(fig, use_container_width=True)

            # Cumulative line below
            cum = (
                scoped.groupby("year", as_index=False)["credits"]
                .sum()
                .sort_values("year")
            )
            cum["Cumulative"] = cum["credits"].cumsum()
            fig2 = px.line(
                cum, x="year", y="Cumulative",
                title=f"Cumulative {view.lower()} credits issued (tCO2e)",
                labels={"year": "Year", "Cumulative": "Cumulative credits (tCO2e)"},
                markers=True,
            )
            fig2.update_traces(line_color="#FFFFFF")
            st.plotly_chart(fig2, use_container_width=True)


# ── Tab: Project Table ────────────────────────────────────────────────────
with tab_table:
    st.subheader("IFM Project List")
    search = st.text_input("Search projects (name, ID, state, developer...)", "")
    if search:
        mask = pd.Series(False, index=filtered.index)
        for c in filtered.columns:
            mask = mask | filtered[c].astype(str).str.contains(
                search, case=False, na=False
            )
        display = filtered[mask]
    else:
        display = filtered

    st.caption(f"Showing {len(display):,} of {len(filtered):,} projects")

    table_cols = [
        "project_id", "name", "registry", "developer",
        "protocol", "credits_issued", "credits_retired",
        "site_location", "state",
    ]
    table_cols = [c for c in table_cols if c in display.columns]

    st.dataframe(
        display[table_cols].head(PAGE_SIZE * 10),
        use_container_width=True,
        hide_index=True,
    )

    csv = display[table_cols].to_csv(index=False).encode("utf-8")
    st.download_button("Download filtered CSV", csv, "ifm_projects.csv", "text/csv")


# ── Tab: State Policies ───────────────────────────────────────────────────
with tab_policy:
    st.subheader("State Forest Policies")
    st.caption(
        "Forest action plans, BMPs, taxes, and laws/regulations relevant to "
        "IFM projects, organized by state. Drop a Markdown file into "
        f"`{STATE_POLICY_DIR}/` (e.g. `michigan.md`) to add a state. See the "
        "_README.md in that folder for the suggested structure."
    )

    states_with_files = list_states_with_policies(STATE_POLICY_DIR)

    # Scope selector: respect sidebar filters by default, allow override
    states_in_filter = sorted([s for s in filtered["state"].dropna().unique() if s])
    use_filtered = st.checkbox(
        "Restrict to states in the current sidebar filter",
        value=True,
        help=(
            "When on, only states present in the filtered project list AND "
            "with a policy file are selectable. Turn off to pick any state "
            "that has a policy file, regardless of filters."
        ),
    )

    if use_filtered:
        choices = [s for s in states_with_files if s in states_in_filter]
    else:
        choices = states_with_files

    if not states_with_files:
        st.info(
            f"No state policy files found in `{STATE_POLICY_DIR}/`. Add a "
            "Markdown file there to populate this section."
        )
    elif not choices:
        st.info(
            "No states match both the current filter and the available policy "
            "files. Either uncheck the filter restriction above, or change "
            "the sidebar filters."
        )
    else:
        state = st.selectbox("State", options=choices)
        content = load_policy(STATE_POLICY_DIR, state)
        if content:
            st.markdown(content)
        else:
            st.warning(f"Could not load policy file for {state}.")


# ── Tab: Policy PDF Search ────────────────────────────────────────────────
with tab_pdfsearch:
    st.subheader("Policy PDF Search")
    st.caption(
        "Search state BMP and forest action plan PDFs for forest carbon language. "
        "Select a state and document from `Documents/<STATE>/`. "
        "Drop any PDF into the matching state subfolder to make it available here."
    )

    pdf_path = None

    available_states = list_states()
    if not available_states:
        st.info("No state subfolders found in `Documents/`. Add PDFs under `Documents/<STATE>/`.")
    else:
        state_options = {f"{abbr} — {STATE_NAMES.get(abbr, abbr)}": abbr for abbr in available_states}
        chosen_label = st.selectbox("State", list(state_options.keys()))
        chosen_state = state_options[chosen_label]

        state_pdfs = list_pdfs_for_state(chosen_state)
        if not state_pdfs:
            st.info(
                f"No PDFs in `Documents/{chosen_state}/` yet. "
                "Drop PDF files there to make them searchable."
            )
        else:
            doc_options = {p.name: p for p in state_pdfs}
            chosen_doc = st.selectbox("Document", list(doc_options.keys()))
            pdf_path = doc_options[chosen_doc]

    query = st.text_input(
        "Search term",
        value="forest carbon",
        help="Case-insensitive keyword or phrase to find in the selected PDF.",
    )

    if pdf_path and query.strip():
        display_name = pdf_path.name
        try:
            with st.spinner(f"Searching `{display_name}`..."):
                results = search_pdf(pdf_path, query)

            if not results:
                st.info(f"No matches for **{query}** in `{display_name}`.")
            else:
                st.success(f"Found **{len(results)}** match(es) for **{query}** in `{display_name}`")
                for i, r in enumerate(results, start=1):
                    with st.expander(f"Match {i} — Page {r['page']}"):
                        st.markdown(r["snippet"])
        except ImportError:
            st.error(
                "`pypdf` is not installed. Run `pip install pypdf` "
                "(or `pip install -r requirements.txt`) and restart the app."
            )
        except Exception as exc:
            st.error(f"Could not read PDF: {exc}")
    elif pdf_path and not query.strip():
        st.info("Enter a search term above to begin.")
