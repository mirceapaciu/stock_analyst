"""Streamlit page for viewing scheduled job dashboard status."""

import json
import sys
from datetime import datetime, timezone
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
SCHEDULER_NEXT_RUN_DISCOVERY_PROCESS = "scheduler_next_run_discovery_workflow"
SCHEDULER_NEXT_RUN_TRACKED_PROCESS = "scheduler_next_run_tracked_stock_batch"
SCHEDULER_NEXT_RUN_MARKET_PROCESS = "scheduler_next_run_market_price_refresh"
JOB_CONFIG_BY_TYPE = {
    "Stock recommendation discovery": {
        "process": DISCOVERY_PROCESS,
        "request_process": "scheduler_next_start_discovery_workflow",
    },
    "Tracked Stock recommendation": {
        "process": TRACKED_PROCESS,
        "request_process": "scheduler_next_start_tracked_stock_batch",
    },
    "Market price refresh": {
        "process": MARKET_REFRESH_PROCESS,
        "request_process": "scheduler_next_start_market_price_refresh",
    },
}


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


def _format_timestamp_local(timestamp: str | None) -> str:
    raw_value = str(timestamp or "").strip()
    if not raw_value or raw_value.upper() == "N/A":
        return "N/A"

    parsed_timestamp = pd.to_datetime(raw_value, errors="coerce", utc=True)
    if pd.isna(parsed_timestamp):
        return raw_value

    return parsed_timestamp.to_pydatetime().astimezone().isoformat(timespec="seconds")


def _resolve_last_run(process_status: dict | None, fallback_timestamp: str | None = None) -> str:
    if process_status:
        status = str(process_status.get("status") or "").strip().upper()
        if status == "STARTED":
            return _format_timestamp_local(process_status.get("start_timestamp"))
        return _format_timestamp_local(
            process_status.get("end_timestamp") or process_status.get("start_timestamp")
        )

    if fallback_timestamp:
        return _format_timestamp_local(fallback_timestamp)

    return "N/A"


def _resolve_process_message(process_status: dict | None, fallback_message: str | None = None) -> str:
    if process_status:
        message = str(process_status.get("message") or "").strip()
        if message:
            return message
    if fallback_message:
        return str(fallback_message)
    return "N/A"


def _extract_job_pid(process_status: dict | None) -> str:
    if not process_status:
        return "N/A"

    raw_message = str(process_status.get("message") or "").strip()
    if not raw_message:
        return "N/A"

    try:
        payload = json.loads(raw_message)
        if isinstance(payload, dict) and payload.get("pid") is not None:
            return str(payload.get("pid"))
    except json.JSONDecodeError:
        pass

    return "N/A"


def _request_job_start_now(job_type: str) -> tuple[bool, str]:
    job_config = JOB_CONFIG_BY_TYPE.get(job_type)
    if not job_config:
        return False, f"Unknown job type: {job_type}"

    process_name = job_config["process"]
    request_process = job_config["request_process"]

    with RecommendationsDatabase(RECOMMENDATIONS_DB_PATH) as db:
        status = db.get_process_status(process_name)
        if status and str(status.get("status") or "").strip().upper() == "STARTED":
            return False, f"{job_type} is already running"

        requested_start = datetime.now(timezone.utc).isoformat()
        db.touch_process_heartbeat(
            request_process,
            status="REQUESTED",
            message=requested_start,
        )

    return True, f"Queued {job_type} to run at {requested_start}"


def _resolve_scheduler_next_run(process_status: dict | None) -> str:
    if not process_status:
        return "N/A"

    next_run = str(process_status.get("message") or "").strip()
    if next_run:
        return _format_timestamp_local(next_run)

    return "N/A"


def _resolve_due_state(raw_status: str | None, next_run_timestamp: str | None) -> str:
    normalized_status = str(raw_status or "").strip().upper()
    if normalized_status == "STARTED":
        return "Running"

    parsed_next_run = pd.to_datetime(next_run_timestamp, errors="coerce", utc=True)
    if pd.isna(parsed_next_run):
        return "Unknown"

    return "Due" if pd.Timestamp.now(tz="UTC") >= parsed_next_run else "Waiting"


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
    styles: list[str] = []
    now_utc = pd.Timestamp.now(tz="UTC")

    for row_index, _value in column.items():
        due_state = str(metadata.at[row_index, "_Due State"] or "").strip()
        schedule_days = metadata.at[row_index, "_Schedule Days"]

        parsed_last_run = pd.to_datetime(_value, errors="coerce", utc=True)
        parsed_schedule_days = pd.to_numeric(schedule_days, errors="coerce")
        if not pd.isna(parsed_last_run) and not pd.isna(parsed_schedule_days):
            freshness_threshold = now_utc - pd.to_timedelta(float(parsed_schedule_days), unit="d")
            if parsed_last_run >= freshness_threshold:
                styles.append("background-color: #dcfce7; color: #14532d;")
                continue

        if due_state == "Waiting":
            styles.append("background-color: #dcfce7; color: #14532d;")
        elif due_state == "Running":
            styles.append("background-color: #fef9c3; color: #713f12;")
        elif due_state == "Due":
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
        discovery_next_run_status = db.get_process_status(SCHEDULER_NEXT_RUN_DISCOVERY_PROCESS)
        tracked_next_run_status = db.get_process_status(SCHEDULER_NEXT_RUN_TRACKED_PROCESS)
        market_next_run_status = db.get_process_status(SCHEDULER_NEXT_RUN_MARKET_PROCESS)
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
    discovery_next_run = _resolve_scheduler_next_run(discovery_next_run_status)
    tracked_next_run = _resolve_scheduler_next_run(tracked_next_run_status)
    market_next_run = _resolve_scheduler_next_run(market_next_run_status)

    return [
        {
            "Job Type": "Stock recommendation discovery",
            "Last Run Timestamp": _resolve_last_run(discovery_status),
            "Last Run Status": _map_process_status(discovery_status.get("status") if discovery_status else None),
            "Next Scheduled Run": discovery_next_run,
            "Job PID": _extract_job_pid(discovery_status),
            "Message": _resolve_process_message(discovery_status),
            "Schedule Frequency (days)": _format_schedule_days(discovery_schedule_days),
            "_Raw Status": discovery_raw_status,
            "_Schedule Days": discovery_schedule_days,
            "_Due State": _resolve_due_state(discovery_raw_status, discovery_next_run),
        },
        {
            "Job Type": "Tracked Stock recommendation",
            "Last Run Timestamp": _resolve_last_run(tracked_status, tracked_fallback_last_run),
            "Last Run Status": tracked_display_status,
            "Next Scheduled Run": tracked_next_run,
            "Job PID": _extract_job_pid(tracked_status),
            "Message": _resolve_process_message(tracked_status, tracked_fallback_message),
            "Schedule Frequency (days)": _format_schedule_days(tracked_schedule_days),
            "_Raw Status": tracked_raw_status,
            "_Schedule Days": tracked_schedule_days,
            "_Due State": _resolve_due_state(tracked_raw_status, tracked_next_run),
        },
        {
            "Job Type": "Market price refresh",
            "Last Run Timestamp": _resolve_last_run(market_refresh_status),
            "Last Run Status": _map_process_status(market_refresh_status.get("status") if market_refresh_status else None),
            "Next Scheduled Run": market_next_run,
            "Job PID": _extract_job_pid(market_refresh_status),
            "Message": _resolve_process_message(market_refresh_status),
            "Schedule Frequency (days)": _format_schedule_days(market_refresh_schedule_days),
            "_Raw Status": market_refresh_raw_status,
            "_Schedule Days": market_refresh_schedule_days,
            "_Due State": _resolve_due_state(market_refresh_raw_status, market_next_run),
        },
    ], scheduler_heartbeat_status


st.title("🧭 Job Dashboard")
st.markdown("""
View status for scheduled jobs, including last run timestamp, status, and configured frequency.
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

metadata_df = df[["_Raw Status", "_Schedule Days", "_Due State"]].copy()
display_df = df.drop(columns=["_Raw Status", "_Schedule Days", "_Due State"])

col1, col2, col3 = st.columns(3)
with col1:
    running_count = int((display_df["Last Run Status"] == "Running").sum())
    st.metric("Running Jobs", running_count)
with col2:
    completed_count = int((display_df["Last Run Status"] == "Completed").sum())
    st.metric("Completed Jobs", completed_count)
with col3:
    failed_count = int((display_df["Last Run Status"] == "Failed").sum())
    st.metric("Failed Jobs", failed_count)

styled_df = display_df.style.apply(
    lambda column: _style_last_run_timestamp(column, metadata_df),
    subset=["Last Run Timestamp"],
)

selection_event = st.dataframe(
    styled_df,
    width="stretch",
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
)

selected_row = None
selected_indices: list[int] = []
if selection_event is not None:
    selection_payload = getattr(selection_event, "selection", None)
    if isinstance(selection_payload, dict):
        selected_indices = list(selection_payload.get("rows") or [])
    elif selection_payload is not None:
        selected_indices = list(getattr(selection_payload, "rows", []) or [])

if selected_indices:
    selected_row = display_df.iloc[selected_indices[0]].to_dict()
    st.caption(
        f"Selected job: {selected_row['Job Type']} | "
        f"Status: {selected_row['Last Run Status']} | "
        f"PID: {selected_row['Job PID']}"
    )

selected_is_running = bool(selected_row and selected_row.get("Last Run Status") == "Running")
run_job_disabled = selected_row is None or selected_is_running

if st.button("Run job", width="stretch", disabled=run_job_disabled):
    started, message = _request_job_start_now(selected_row["Job Type"])
    if started:
        st.success(message)
        st.cache_data.clear()
        st.rerun()
    else:
        st.warning(message)
