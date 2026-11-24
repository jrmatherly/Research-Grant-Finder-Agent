from __future__ import annotations

import sqlite3
import warnings
from pathlib import Path

import pandas as pd
import streamlit as st

from nih_grant_matcher.config import MatcherConfig
from nih_grant_matcher.excel import write_excel
from nih_grant_matcher.models import ScoredOpportunity
from nih_grant_matcher.profile import ProfileError, ranks_like_builtin
from nih_grant_matcher.rules import GRANT_TYPES, grant_types_for, why_not_covered
from nih_grant_matcher.scoring import score_bin
from nih_grant_matcher.ui.apply_page import apply_page, show_notices, start_application
from nih_grant_matcher.ui.find_page import picked_option
from nih_grant_matcher.ui.markdown import escape_markdown
from nih_grant_matcher.ui.profile_page import profile_page, profile_sentence, saved_profile, show_unreadable
from nih_grant_matcher.workflow import load_saved, run_and_save


DEFAULT_DB = "data/grants.sqlite3"
DEFAULT_EXCEL = "outputs/nih_grant_opportunities_ui.xlsx"


st.set_page_config(page_title="NIH Grant Matcher", page_icon="NIH", layout="wide")
st.title("NIH Grant Opportunity Matcher")


def get_scored_items_from_session() -> list[ScoredOpportunity]:
    # Older versions accidentally used the items attribute of session state, which resolves
    # to a method. Clear that key and guard against any stale callable value.
    if "items" in st.session_state:
        del st.session_state["items"]
    value = st.session_state.get("scored_items", [])
    if callable(value) or value is None:
        st.session_state["scored_items"] = []
        return []
    return list(value)


def set_scored_items_in_session(value: list[ScoredOpportunity]) -> None:
    st.session_state["scored_items"] = list(value or [])


def scored_to_records(items: list[ScoredOpportunity]) -> list[dict]:
    records = []
    for rank, item in enumerate(items, start=1):
        opp = item.opportunity
        raw = opp.raw or {}
        grants_gov_url = raw.get("grants_gov_url") or ""
        if not grants_gov_url and isinstance(raw.get("guide_item"), dict) and raw["guide_item"].get("ggid"):
            grants_gov_url = f"https://www.grants.gov/search-results-detail/{raw['guide_item']['ggid']}"
        records.append(
            {
                "Rank": rank,
                "Classification": item.classification,
                "Score": item.score,
                "Opportunity Number": opp.opportunity_number,
                "Title": opp.title,
                "NIH Institute": opp.agency_code or opp.agency_name,
                "Agency": opp.agency_name,
                "Status": opp.status,
                "Open Date": opp.open_date,
                "Close Date": opp.close_date,
                "Activity": ", ".join(opp.funding_instruments),
                "Category": ", ".join(opp.funding_categories),
                "Matched Terms": ", ".join(item.matched_terms),
                "Why It Matched": "; ".join(item.reasons),
                "Summary": opp.description,
                "Source URL": opp.source_url,
                "Grants.gov URL": grants_gov_url,
                "Source ID": opp.source_id,
            }
        )
    return records


def make_dataframe(items: list[ScoredOpportunity]) -> pd.DataFrame:
    frame = pd.DataFrame(scored_to_records(items))
    if frame.empty:
        return frame
    frame["Open Date"] = pd.to_datetime(frame["Open Date"], errors="coerce")
    frame["Close Date"] = pd.to_datetime(frame["Close Date"], errors="coerce")
    frame["Close Month"] = frame["Close Date"].dt.to_period("M").astype(str).replace("NaT", "Not listed")
    return frame


def apply_filters(frame: pd.DataFrame, min_score: float, classifications: list[str], institutes: list[str], term_query: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    filtered = frame[frame["Score"] >= min_score].copy()
    if classifications:
        filtered = filtered[filtered["Classification"].isin(classifications)]
    if institutes:
        filtered = filtered[filtered["NIH Institute"].isin(institutes)]
    if term_query.strip():
        query = term_query.strip().lower()
        haystack = (
            filtered["Title"].fillna("")
            + " "
            + filtered["Matched Terms"].fillna("")
            + " "
            + filtered["Summary"].fillna("")
        ).str.lower()
        filtered = filtered[haystack.str.contains(query, regex=False)]
    return filtered


# A keyed widget drawn again after a run without it shows its default, not the value the server kept, unless it persists, so every keyed Find widget persists.
with st.sidebar:
    view = st.sidebar.radio("View", ["Find", "Apply", "Profile"], key="view")
    db_path = st.text_input("Database", value=DEFAULT_DB)
    if view == "Find":
        st.header("Run Search")
        source = st.selectbox("Source", ["nih-guide", "both", "grants.gov"], key="find_source", persist_state="session")
        keyword = st.text_input("Keyword", placeholder="AI, machine learning, imaging...", key="find_keyword", persist_state="session")
        limit = st.slider("Rows per source", min_value=25, max_value=1000, value=500, step=25, key="find_rows", persist_state="session")
        run_clicked = st.button("Run Search", type="primary", width="stretch")

        st.divider()
        st.header("Display")
        min_score = st.slider("Minimum score shown", 0.0, 100.0, step=5.0, key="find_min_score", persist_state="session")
        max_saved = st.slider("Saved rows to load", 50, 1000, 500, step=50, key="find_max_saved", persist_state="session")
        load_clicked = st.button("Load Saved Results", width="stretch")

        st.divider()
        st.header("Export")
        excel_path = st.text_input("Excel output", DEFAULT_EXCEL, key="find_excel", persist_state="session")
        export_clicked = st.button("Export Current View", width="stretch")


if "scored_items" not in st.session_state:
    st.session_state["scored_items"] = []
if "items" in st.session_state:
    del st.session_state["items"]
if "last_run" not in st.session_state:
    st.session_state["last_run"] = None

db_error = None
try:
    saved, unreadable = saved_profile(db_path), None
except ProfileError as exc:
    saved, unreadable = None, exc
except sqlite3.Error as exc:
    saved, unreadable, db_error = None, None, exc
st.caption(f"Run NIH Guide and Grants.gov searches, rank {'computational ' if saved is None or ranks_like_builtin(saved) else ''}opportunities, and explore the results interactively.")

if view == "Profile":
    profile_page(db_path)
    st.stop()
if view == "Apply":
    apply_page(db_path)
    st.stop()
if db_error:
    st.warning(f"Could not open the database, so ranking uses the built-in profile. {db_error}")
if unreadable:
    show_unreadable(unreadable)
elif saved is None:
    st.caption("Ranking uses the built-in profile (machine learning and data science). Set your own under Profile.")
else:
    st.caption(profile_sentence(saved))

if run_clicked:
    config = MatcherConfig(rows=limit, db_path=db_path, min_digest_score=min_score)
    with st.spinner("Fetching and scoring opportunities..."):
        try:
            items, summary = run_and_save(config, source=source, keyword=keyword)
        except Exception as exc:
            st.error(f"Search failed: {exc}")
        else:
            set_scored_items_in_session(items)
            st.session_state["last_run"] = summary
            st.success(f"Fetched {summary.fetched} records from {summary.source}; saved {summary.saved} current NIH/HHS opportunities.")
            if summary.capped:
                st.warning("A source reached the row limit and may hold more. Raise Rows per source and run again.")

if load_clicked or (not get_scored_items_from_session() and Path(db_path).exists()):
    try:
        with warnings.catch_warnings(record=True) as load_warnings:
            warnings.simplefilter("always", RuntimeWarning)
            set_scored_items_in_session(load_saved(db_path, min_score=0.0, limit=max_saved))
        for load_warning in load_warnings:
            if issubclass(load_warning.category, RuntimeWarning):
                st.warning(str(load_warning.message))
    except Exception as exc:
        st.warning(f"Could not load saved results: {exc}")

items = get_scored_items_from_session()
frame = make_dataframe(items)

if frame.empty:
    st.info("Run a search or load saved results to populate the dashboard.")
    st.stop()

# Every class is offered whatever the rows hold, so a kept choice of all classes still shows a class that a new ranking brings.
all_classes = ["High", "Medium", "Watchlist"]
all_institutes = sorted(frame["NIH Institute"].dropna().unique().tolist())

filter_col1, filter_col2, filter_col3 = st.columns([1.1, 1.3, 1.6])
with filter_col1:
    selected_classes = st.multiselect("Classification", all_classes, default=all_classes, key="find_classes", persist_state="session")
with filter_col2:
    selected_institutes = st.multiselect("NIH institute", all_institutes, key="find_institutes", persist_state="session")
with filter_col3:
    term_filter = st.text_input("Filter within results", placeholder="PRIMED-AI, EHR, NINDS...", key="find_filter", persist_state="session")

filtered = apply_filters(frame, min_score=min_score, classifications=selected_classes, institutes=selected_institutes, term_query=term_filter)

metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
metric_col1.metric("Visible Opportunities", f"{len(filtered):,}")
metric_col2.metric("High Matches", f"{(filtered['Classification'] == 'High').sum():,}")
metric_col3.metric("Median Score", f"{filtered['Score'].median():.1f}" if not filtered.empty else "0")
next_deadline = filtered["Close Date"].dropna().min() if not filtered.empty else None
metric_col4.metric("Next Expiration", next_deadline.strftime("%Y-%m-%d") if pd.notna(next_deadline) else "Not listed")
st.caption("For an NIH Guide notice, Expires is the day the notice expires, and application due dates are in the announcement. For a Grants.gov row, Expires is the closing date.")

options = (filtered["Opportunity Number"].fillna("") + " | " + filtered["Title"].fillna("")).tolist()

def _pick_row(options: list[str] = options) -> None:
    picked = picked_option(st.session_state.get("find_table"), options)
    if picked is not None:
        st.session_state["find_opportunity"] = picked

tab_results, tab_visuals, tab_detail = st.tabs(["Results", "Visuals", "Details"], key="find_tabs")

with tab_results:
    st.dataframe(
        filtered.drop(columns=["Source ID", "Close Month"], errors="ignore"),
        width="stretch",
        hide_index=True,
        column_config={
            "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.1f"),
            "Source URL": st.column_config.LinkColumn("NIH Guide URL"),
            "Grants.gov URL": st.column_config.LinkColumn("Grants.gov URL"),
            "Open Date": st.column_config.DateColumn("Open Date", format="YYYY-MM-DD"),
            "Close Date": st.column_config.DateColumn("Expires", format="YYYY-MM-DD"),
        },
        key="find_table",
        on_select=_pick_row,
        selection_mode="single-cell",
    )
    st.caption("Select a row, then open Details to read it.")

with tab_visuals:
    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        st.subheader("Matches by Classification")
        st.bar_chart(filtered["Classification"].value_counts().reindex(["High", "Medium", "Watchlist"]).dropna())
    with chart_col2:
        st.subheader("Top NIH Institutes")
        st.bar_chart(filtered["NIH Institute"].value_counts().head(12))

    chart_col3, chart_col4 = st.columns(2)
    with chart_col3:
        st.subheader("Score Distribution")
        score_labels = ["0-25", "25-35", "35-70", "70-100"]
        score_counts = filtered["Score"].map(score_bin).value_counts().reindex(score_labels, fill_value=0)
        st.bar_chart(score_counts)
    with chart_col4:
        st.subheader("Expirations by Month")
        month_counts = filtered[filtered["Close Month"] != "Not listed"]["Close Month"].value_counts().sort_index()
        if month_counts.empty:
            st.info("No expiration dates in the current view.")
        else:
            st.bar_chart(month_counts)

with tab_detail:
    selected = st.selectbox("Opportunity", options, key="find_opportunity", persist_state="session") if not filtered.empty else None
    if selected:
        row = filtered.iloc[options.index(selected)]
        st.subheader(row["Title"])
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Score", f"{row['Score']:.1f}")
        d2.metric("Class", row["Classification"])
        d3.metric("Institute", row["NIH Institute"])
        d4.metric("Expires", row["Close Date"].strftime("%Y-%m-%d") if pd.notna(row["Close Date"]) else "Not listed")
        st.markdown(f"**Opportunity number:** {row['Opportunity Number']}")
        st.markdown(f"**Matched terms:** {row['Matched Terms'] or 'None'}")
        st.markdown(f"**Why it matched:** {row['Why It Matched']}")
        st.write(row["Summary"] or "No summary available.")
        link_cols = st.columns(2)
        if row["Source URL"]:
            link_cols[0].link_button("Open NIH Guide", row["Source URL"], width="stretch")
        if row["Grants.gov URL"]:
            link_cols[1].link_button("Open Grants.gov", row["Grants.gov URL"], width="stretch")
        opportunity = next(item.opportunity for item in items if item.opportunity.source_id == row["Source ID"])
        covered = grant_types_for(opportunity)
        if covered:
            grant_type = st.selectbox("Grant type", [f"{g.funder}:{g.code}" for g in covered], format_func=lambda key: f"{GRANT_TYPES[key].code} {GRANT_TYPES[key].title}", key="find_grant_type", persist_state="session")
            resubmission = st.checkbox("This is a resubmission", key="find_resubmission", persist_state="session")
            st.button("Start application", key="start_application", type="primary", on_click=start_application, args=(db_path, opportunity, grant_type, resubmission))
            show_notices()
        else:
            st.caption(escape_markdown(f"Grant Matcher writes applications for {', '.join(g.code for g in GRANT_TYPES.values())}. This opportunity lists {', '.join(opportunity.funding_instruments) or 'no activity code'}. {why_not_covered(opportunity)}".strip()))
            st.button("Start application", key="start_application", disabled=True)

if export_clicked:
    visible_ids = set(filtered["Source ID"].tolist())
    visible_items = [item for item in items if item.opportunity.source_id in visible_ids]
    try:
        output_path = write_excel(visible_items, excel_path, min_score=min_score)
        st.success(f"Wrote Excel file to {output_path}")
        with open(output_path, "rb") as handle:
            st.download_button("Download Excel", handle.read(), file_name=Path(output_path).name, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception as exc:
        st.error(f"Excel export failed: {exc}")

