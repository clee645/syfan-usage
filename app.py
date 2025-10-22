# app.py
# How to run:
#   1) pip install streamlit pandas altair python-dateutil
#   2) streamlit run app.py
#
# Assumptions:
#   - Each row represents a single run.
#   - CSV columns include (case-insensitive): timestamp, workflow, branch, run_id (optional), duration (seconds), channel/type/etc.
#   - Some workflows (e.g., email/text) may not have duration. We show duration KPIs as "N/A" in that case.
#
# Features:
#   - Filters: workflow(s) and date range
#   - KPIs: Total Runs, Total Minutes, Avg Duration/Call (min), Active Workflows, Active Branches
#   - Pie chart: Runs by Branch
#   - Line chart: Runs over time (daily)
#   - Runs table: key columns
#
import os
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import streamlit as st
import altair as alt

st.set_page_config(page_title="Workflow Usage Dashboard", page_icon="📊", layout="wide")
st.title("📊 Workflow Usage Dashboard")

# --------------------------
# Data Loading (no uploader)
# --------------------------
CANDIDATE_PATHS = [
    "syfan_workflows.csv",             # same folder as app.py
    "/mnt/data/syfan_workflows.csv",   # fallback (for this environment)
]

df = None
used_path = None
for p in CANDIDATE_PATHS:
    if os.path.exists(p):
        try:
            df = pd.read_csv(p)
            used_path = p
            break
        except Exception:
            pass

if df is None:
    st.error("CSV not found. Please place 'syfan_workflows.csv' next to app.py and rerun.")
    st.stop()

st.caption(f"Data source: `{used_path}`")

# Normalize columns
df.columns = [c.strip().lower() for c in df.columns]

# Required columns
required = ["timestamp", "workflow", "branch"]
missing = [c for c in required if c not in df.columns]
if missing:
    st.error(f"Missing required column(s): {', '.join(missing)}")
    st.stop()

# Parse timestamp
df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
df = df.dropna(subset=["timestamp"]).copy()

# Duration handling (seconds -> minutes for display)
if "duration" in df.columns:
    df["duration"] = pd.to_numeric(df["duration"], errors="coerce")
    df["duration_minutes"] = df["duration"] / 60.0
else:
    df["duration_minutes"] = np.nan

# --------------------------
# Sidebar Filters (workflow + time)
# --------------------------
st.sidebar.header("Filters")

workflows = sorted(df["workflow"].dropna().unique().tolist())
selected_workflows = st.sidebar.multiselect(
    "Workflow(s)",
    options=workflows,
    default=workflows,  # all by default
)

min_dt = pd.to_datetime(df["timestamp"].min()).to_pydatetime()
max_dt = pd.to_datetime(df["timestamp"].max()).to_pydatetime()
default_start = max_dt - timedelta(days=213)

start_date, end_date = st.sidebar.date_input(
    "Date range",
    value=(default_start.date(), max_dt.date()),
    min_value=min_dt.date(),
    max_value=max_dt.date(),
)

# Make datetime bounds inclusive
if isinstance(start_date, (list, tuple)):
    start_date = start_date[0]
    end_date = start_date[1] if len(start_date) > 1 else max_dt.date()

start_dt = datetime.combine(start_date, datetime.min.time())
end_dt = datetime.combine(end_date, datetime.max.time())

# Apply filters
mask = (df["timestamp"] >= start_dt) & (df["timestamp"] <= end_dt)
if selected_workflows:
    mask &= df["workflow"].isin(selected_workflows)

filtered = df.loc[mask].copy()

# --------------------------
# KPIs (each row is a run)
# --------------------------
st.subheader("Key Metrics")

# Total runs = number of rows after filtering
total_runs = int(len(filtered))

# Duration-based metrics
has_any_duration = filtered["duration_minutes"].notna().any()
if has_any_duration:
    total_minutes = float(filtered["duration_minutes"].sum(skipna=True))
    avg_minutes = float(filtered.loc[filtered["duration_minutes"].notna(), "duration_minutes"].mean())
else:
    total_minutes = np.nan
    avg_minutes = np.nan

active_workflows = int(filtered["workflow"].nunique()) if not filtered.empty else 0
active_branches = int(filtered["branch"].nunique()) if not filtered.empty else 0

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total Runs", f"{total_runs:,}")
c2.metric("Total Minutes", f"{total_minutes:,.1f} min" if not np.isnan(total_minutes) else "N/A")
c3.metric("Avg Duration/Call", f"{avg_minutes:,.2f} min" if not np.isnan(avg_minutes) else "N/A")
c4.metric("Active Workflows", f"{active_workflows:,}")
c5.metric("Active Branches", f"{active_branches:,}")

# --------------------------
# Charts
# --------------------------
st.subheader("Usage Breakdown & Trends")

if filtered.empty:
    st.info("No data for the selected filters.")
else:
    # Pie chart: Runs by Branch (count rows)
    runs_by_branch = (
        filtered.groupby("branch").size().reset_index(name="runs")
        .sort_values("runs", ascending=False)
    )

    if runs_by_branch["runs"].sum() == 0:
        st.warning("No runs to display for the selected filters.")
    else:
        # Calculate percentages
        runs_by_branch["percentage"] = (runs_by_branch["runs"] / runs_by_branch["runs"].sum() * 100).round(1)
        runs_by_branch["percentage_label"] = runs_by_branch["percentage"].astype(str) + "%"
        
        # Get the sorted order of branches (largest to smallest)
        branch_order = runs_by_branch["branch"].tolist()
        
        # Pie chart with darker color scheme, ordered largest to smallest clockwise
        pie = alt.Chart(runs_by_branch).mark_arc(outerRadius=160).encode(
            theta=alt.Theta(field="runs", type="quantitative", stack=True),
            color=alt.Color(
                field="branch", 
                type="nominal",
                sort=branch_order,  # Explicit ordering from largest to smallest
                scale=alt.Scale(scheme="tableau20"),  # Darker, less bright color scheme
                legend=alt.Legend(title="Branch")
            ),
            order=alt.Order(
                field="runs",
                type="quantitative",
                sort="descending"  # Ensure slices are ordered largest to smallest
            ),
            tooltip=[
                alt.Tooltip("branch", title="Branch"), 
                alt.Tooltip("runs:Q", title="Runs"),
                alt.Tooltip("percentage_label:N", title="Percentage")
            ]
        ).properties(
            width=500, 
            height=450, 
            title="Runs by Branch"
        ).configure_view(
            strokeWidth=0
        )
        
        # Center the pie chart
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.altair_chart(pie, use_container_width=False)

    # Line chart: Runs over time (daily counts)
    ts = filtered.set_index("timestamp").sort_index()
    daily = ts.resample("D").size().reset_index(name="runs")
    daily.columns = ["date", "runs"]

    line = alt.Chart(daily).mark_line(point=True).encode(
        x=alt.X("date:T", title="Date"),
        y=alt.Y("runs:Q", title="Runs"),
        tooltip=[alt.Tooltip("date:T", title="Date"), alt.Tooltip("runs:Q", title="Runs")]
    ).properties(title="Runs Over Time")
    st.altair_chart(line, use_container_width=True)

# --------------------------
# Runs Table
# --------------------------
st.subheader("Runs Table")

display_cols = [c for c in ["timestamp", "workflow", "branch", "channel", "type", "run_id", "duration_minutes", "subject", "snippet"] if c in filtered.columns]

if not filtered.empty:
    table_df = filtered.sort_values("timestamp", ascending=False).loc[:, display_cols].copy()
    table_df["timestamp"] = table_df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    if "duration_minutes" in table_df.columns:
        table_df["duration_minutes"] = table_df["duration_minutes"].round(2)
    st.dataframe(table_df, use_container_width=True, hide_index=True)
else:
    st.info("No rows to show for the selected filters.")

with st.expander("ℹ️ Tips"):
    st.markdown(
        """
        - Each **row = one run**. Metrics and charts are based on the filtered rows.
        - **Duration** is shown in **minutes**. If your selection only includes workflows without duration (e.g., email), duration KPIs show *N/A*.
        - **Pie** shows distribution of runs across **branches**.
        - **Line** shows daily run totals.
        """
    )
