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

from config import DISCOVERY_INTERVAL_HOURS, MARKET_PRICE_REFRESH_INTERVAL_HOURS, TRACKED_BATCH_INTERVAL_HOURS
from config import RECOMMENDATIONS_DB_PATH
from repositories.recommendations_db import RecommendationsDatabase

st.set_page_config(page_title="Job Dashboard", page_icon="🧭", layout="wide")

DISCOVERY_PROCESS = "recommendations_workflow"
TRACKED_PROCESS = "tracked_stock_batch"
TRACKED_WORKFLOW_TYPE = "tracked_stock"
MARKET_REFRESH_PROCESS = "market_price_refresh"
SCHEDULER_HEARTBEAT_PROCESS = "scheduler_heartbeat"
SCHEDULER_HEARTBEAT_STALE_MINUTES = 3


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


def _resolve_process_message(process_status: dict | None, fallback_message: str | None = None) -> str:
    if process_status:
        message = str(process_status.get("message") or "").strip()
        if message:
            return message
    if fallback_message:
        return str(fallback_message)
    return "N/A"


def _resolve_heartbeat_timestamp(process_status: dict | None) -> str:
    if not process_status:
        return "N/A"

    return process_status.get("end_timestamp") or process_status.get("start_timestamp") or "N/A"


def _get_scheduler_heartbeat_state(process_status: dict | None) -> tuple[str, str, str]:
    heartbeat_timestamp = _resolve_heartbeat_timestamp(process_status)
    parsed_timestamp = pd.to_datetime(heartbeat_timestamp, errors="coerce", utc=True)

    if pd.isna(parsed_timestamp):
        return "missing", "Scheduler heartbeat missing", "No heartbeat recorded yet"

    heartbeat_threshold = pd.Timestamp.now(tz="UTC") - pd.to_timedelta(
        SCHEDULER_HEARTBEAT_STALE_MINUTES,
        unit="m",
    )

    if parsed_timestamp >= heartbeat_threshold:
        return "active", "Scheduler heartbeat active", f"Last heartbeat: {heartbeat_timestamp}"

    return "stale", "Scheduler heartbeat stale", f"Last heartbeat: {heartbeat_timestamp}"


def _style_last_run_timestamp(column: pd.Series, metadata: pd.DataFrame) -> list[str]:
    now_utc = pd.Timestamp.now(tz="UTC")
    styles: list[str] = []

    for row_index, value in column.items():
        last_run_timestamp = pd.to_datetime(value, errors="coerce", utc=True)
        schedule_days = float(metadata.at[row_index, "_Schedule Days"])
        raw_status = str(metadata.at[row_index, "_Raw Status"] or "").strip().upper()

        if pd.isna(last_run_timestamp):
            styles.append("background-color: #fee2e2; color: #7f1d1d;")
            continue

        freshness_threshold = now_utc - pd.to_timedelta(schedule_days, unit="D")

        if last_run_timestamp >= freshness_threshold and raw_status != "STARTED":
            styles.append("background-color: #dcfce7; color: #14532d;")
        elif last_run_timestamp < freshness_threshold and raw_status == "STARTED":
            styles.append("background-color: #fef9c3; color: #713f12;")
        elif last_run_timestamp < freshness_threshold and raw_status != "STARTED":
            styles.append("background-color: #fee2e2; color: #7f1d1d;")
        else:
            styles.append("")

    return styles


@st.cache_data(ttl=60)
def load_job_dashboard_rows() -> tuple[list[dict], dict | None]:
    with RecommendationsDatabase(RECOMMENDATIONS_DB_PATH) as db:
        discovery_status = db.get_process_status(DISCOVERY_PROCESS)
        tracked_status = db.get_process_status(TRACKED_PROCESS)
        market_refresh_status = db.get_process_status(MARKET_REFRESH_PROCESS)
        scheduler_heartbeat_status = db.get_process_status(SCHEDULER_HEARTBEAT_PROCESS)
        tracked_batch_status = db.get_batch_schedule_status(TRACKED_WORKFLOW_TYPE)

    tracked_fallback_status = None
    tracked_fallback_last_run = None
    tracked_fallback_message = None
    if tracked_batch_status:
        tracked_fallback_status = tracked_batch_status.get("last_batch_status")
        tracked_fallback_last_run = tracked_batch_status.get("last_batch_at")
        if tracked_fallback_status:
            tracked_fallback_message = f"Last tracked batch status: {tracked_fallback_status}"

    tracked_display_status = _map_process_status(
        tracked_status.get("status") if tracked_status else tracked_fallback_status
    )

    discovery_schedule_days = DISCOVERY_INTERVAL_HOURS / 24.0
    tracked_schedule_days = TRACKED_BATCH_INTERVAL_HOURS / 24.0
    market_refresh_schedule_days = MARKET_PRICE_REFRESH_INTERVAL_HOURS / 24.0

    discovery_raw_status = discovery_status.get("status") if discovery_status else None
    tracked_raw_status = tracked_status.get("status") if tracked_status else tracked_fallback_status
    market_refresh_raw_status = market_refresh_status.get("status") if market_refresh_status else None

    return [
        {
            "Job Type": "Stock recommendation discovery",
            "Last Run Timestamp": _resolve_last_run(discovery_status),
            "Completion Status": _map_process_status(discovery_status.get("status") if discovery_status else None),
            "Message": _resolve_process_message(discovery_status),
            "Schedule Frequency (days)": _format_schedule_days(discovery_schedule_days),
            "_Raw Status": discovery_raw_status,
            "_Schedule Days": discovery_schedule_days,
        },
        {
            "Job Type": "Tracked Stock recommendation",
            "Last Run Timestamp": _resolve_last_run(tracked_status, tracked_fallback_last_run),
            "Completion Status": tracked_display_status,
            "Message": _resolve_process_message(tracked_status, tracked_fallback_message),
            "Schedule Frequency (days)": _format_schedule_days(tracked_schedule_days),
            "_Raw Status": tracked_raw_status,
            "_Schedule Days": tracked_schedule_days,
        },
        {
            "Job Type": "Market price refresh",
            "Last Run Timestamp": _resolve_last_run(market_refresh_status),
            "Completion Status": _map_process_status(market_refresh_status.get("status") if market_refresh_status else None),
            "Message": _resolve_process_message(market_refresh_status),
            "Schedule Frequency (days)": _format_schedule_days(market_refresh_schedule_days),
            "_Raw Status": market_refresh_raw_status,
            "_Schedule Days": market_refresh_schedule_days,
        },
    ], scheduler_heartbeat_status


st.title("🧭 Job Dashboard")
st.markdown("""
View status for scheduled jobs, including last run timestamp, completion status, and configured frequency.
""")

with st.sidebar:
    st.header("Actions")
    if st.button("🔄 Refresh", width="stretch"):
        st.cache_data.clear()
        st.rerun()

rows, scheduler_heartbeat_status = load_job_dashboard_rows()
df = pd.DataFrame(rows)

heartbeat_state, heartbeat_title, heartbeat_message = _get_scheduler_heartbeat_state(
    scheduler_heartbeat_status
)

if heartbeat_state == "active":
    st.success(f"{heartbeat_title}. {heartbeat_message}")
elif heartbeat_state == "stale":
    st.error(f"{heartbeat_title}. {heartbeat_message}")
else:
    st.error(f"{heartbeat_title}. {heartbeat_message}")

metadata_df = df[["_Raw Status", "_Schedule Days"]].copy()
display_df = df.drop(columns=["_Raw Status", "_Schedule Days"])

col1, col2, col3 = st.columns(3)
with col1:
    running_count = int((display_df["Completion Status"] == "Running").sum())
    st.metric("Running Jobs", running_count)
with col2:
    completed_count = int((display_df["Completion Status"] == "Completed").sum())
    st.metric("Completed Jobs", completed_count)
with col3:
    failed_count = int((display_df["Completion Status"] == "Failed").sum())
    st.metric("Failed Jobs", failed_count)

styled_df = display_df.style.apply(
    lambda column: _style_last_run_timestamp(column, metadata_df),
    subset=["Last Run Timestamp"],
)

st.dataframe(styled_df, width='stretch', hide_index=True)
