"""Streamlit page for viewing scheduled job dashboard status."""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Add src directory to Python path
# Resolve __file__ first to handle any .. components, then go up to src/
src_path = Path(__file__).resolve().parent.parent.parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

# Check authentication first
from utils.auth import check_password
if not check_password():
    st.stop()  # Stop execution if not authenticated

from config import DISCOVERY_INTERVAL_HOURS, TRACKED_BATCH_INTERVAL_HOURS, SWEEP_STALE_DAYS
from config import RECOMMENDATIONS_DB_PATH
from repositories.recommendations_db import RecommendationsDatabase

st.set_page_config(page_title="Job Dashboard", page_icon="🧭", layout="wide")

DISCOVERY_PROCESS = "recommendations_workflow"
TRACKED_PROCESS = "tracked_stock_batch"
TRACKED_WORKFLOW_TYPE = "tracked_stock"
MARKET_REFRESH_PROCESS = "market_price_refresh"


def _format_schedule_days(days: float) -> str:
    if float(days).is_integer():
        return f"Every {int(days)} day(s)"
    return f"Every {days:.2f} day(s)"


def _map_process_status(status: str | None) -> str:
    normalized = str(status or "").strip().upper()
    if normalized == "STARTED":
        return "Running"
    if normalized == "COMPLETED":
        return "Completed"
    if normalized.startswith("FAILED"):
        return "Failed"
    return "Pending"


def _resolve_last_run(process_status: dict | None, fallback_timestamp: str | None = None) -> str:
    if process_status:
        status = str(process_status.get("status") or "").strip().upper()
        if status == "STARTED":
            return process_status.get("start_timestamp") or "N/A"
        return process_status.get("end_timestamp") or process_status.get("start_timestamp") or "N/A"

    if fallback_timestamp:
        return str(fallback_timestamp)

    return "N/A"


@st.cache_data(ttl=60)
def load_job_dashboard_rows() -> list[dict]:
    with RecommendationsDatabase(RECOMMENDATIONS_DB_PATH) as db:
        discovery_status = db.get_process_status(DISCOVERY_PROCESS)
        tracked_status = db.get_process_status(TRACKED_PROCESS)
        market_refresh_status = db.get_process_status(MARKET_REFRESH_PROCESS)
        tracked_batch_status = db.get_batch_schedule_status(TRACKED_WORKFLOW_TYPE)

    tracked_fallback_status = None
    tracked_fallback_last_run = None
    if tracked_batch_status:
        tracked_fallback_status = tracked_batch_status.get("last_batch_status")
        tracked_fallback_last_run = tracked_batch_status.get("last_batch_at")

    tracked_display_status = _map_process_status(
        tracked_status.get("status") if tracked_status else tracked_fallback_status
    )

    return [
        {
            "Job Type": "Stock recommendation discovery",
            "Last Run Timestamp": _resolve_last_run(discovery_status),
            "Completion Status": _map_process_status(discovery_status.get("status") if discovery_status else None),
            "Schedule Frequency (days)": _format_schedule_days(DISCOVERY_INTERVAL_HOURS / 24.0),
        },
        {
            "Job Type": "Tracked Stock recommendation",
            "Last Run Timestamp": _resolve_last_run(tracked_status, tracked_fallback_last_run),
            "Completion Status": tracked_display_status,
            "Schedule Frequency (days)": _format_schedule_days(TRACKED_BATCH_INTERVAL_HOURS / 24.0),
        },
        {
            "Job Type": "Market price refresh",
            "Last Run Timestamp": _resolve_last_run(market_refresh_status),
            "Completion Status": _map_process_status(market_refresh_status.get("status") if market_refresh_status else None),
            "Schedule Frequency (days)": _format_schedule_days(float(SWEEP_STALE_DAYS)),
        },
    ]


st.title("🧭 Job Dashboard")
st.markdown("""
View status for scheduled jobs, including last run timestamp, completion status, and configured frequency.
""")

with st.sidebar:
    st.header("Actions")
    if st.button("🔄 Refresh", width="stretch"):
        st.cache_data.clear()
        st.rerun()

rows = load_job_dashboard_rows()
df = pd.DataFrame(rows)

col1, col2, col3 = st.columns(3)
with col1:
    running_count = int((df["Completion Status"] == "Running").sum())
    st.metric("Running Jobs", running_count)
with col2:
    completed_count = int((df["Completion Status"] == "Completed").sum())
    st.metric("Completed Jobs", completed_count)
with col3:
    failed_count = int((df["Completion Status"] == "Failed").sum())
    st.metric("Failed Jobs", failed_count)

st.dataframe(df, use_container_width=True, hide_index=True)
