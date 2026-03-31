"""
General Application Configuration
"""

import os
from pathlib import Path
from typing import List
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Base directory
# Resolve __file__ first to handle any .. components in the path
BASE_DIR = Path(__file__).resolve().parent.parent

# Database Configuration
# Support EFS mount path for persistent storage in ECS Fargate
EFS_MOUNT_PATH = os.getenv("EFS_MOUNT_PATH", "")
if EFS_MOUNT_PATH:
    # Use EFS mount path if specified (for ECS Fargate deployments)
    DB_PATH = os.getenv("DB_PATH", str(Path(EFS_MOUNT_PATH) / "data" / "db" / "stocks.duckdb"))
    RECOMMENDATIONS_DB_PATH = os.getenv("RECOMMENDATIONS_DB_PATH", str(Path(EFS_MOUNT_PATH) / "data" / "db" / "recommendations.db"))
else:
    # Use local paths (for local development or Lightsail)
    # Ensure absolute path to avoid relative path issues
    default_db_path = (BASE_DIR / "data" / "db" / "stocks.duckdb").resolve()
    default_rec_path = (BASE_DIR / "data" / "db" / "recommendations.db").resolve()
    DB_PATH = os.getenv("DB_PATH", str(default_db_path))
    RECOMMENDATIONS_DB_PATH = os.getenv("RECOMMENDATIONS_DB_PATH", str(default_rec_path))

# OpenAI settings
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Google Custom Search API settings
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")  # Custom Search Engine ID

# Search settings
MAX_SEARCH_RESULTS = 10 # Maximum results to fetch per query. Note Google CSE limits to 10 per request.
MAX_RESULT_AGE_DAYS = 20  # Filter results older than this
CSE_DAILY_QUOTA = max(1, int(os.getenv("CSE_DAILY_QUOTA", "100")))

# Search query templates.
# Use {year}, {month}, and {site} placeholders for dynamic values.
# site will be replaced with reputable financial websites.
# year and month will be replaced with the current year and month.
SEARCH_QUERIES = [
    "undervalued stocks site:{site}",
    "best value stocks site:{site}",
    "stocks to buy site:{site}"
]

REPUTABLE_SITES = [
    # "bloomberg.com", requires sign-in
    "reuters.com",    
    "morningstar.com",
    "finance.yahoo.com",
    "fool.com",
    # "zacks.com", too many low quality pages
    "seekingalpha.com"
]

# Tracked stock batch search settings (used by scheduler-driven tracked workflow).
TRACKED_BATCH_SIZE = max(1, int(os.getenv("TRACKED_BATCH_SIZE", "27")))
TRACKED_BATCH_MIN_RATING = min(5.0, max(1.0, float(os.getenv("TRACKED_BATCH_MIN_RATING", "4.0"))))
TRACKED_BATCH_INTERVAL_HOURS = max(1, int(os.getenv("TRACKED_BATCH_INTERVAL_HOURS", "8")))
TRACKED_RESULT_AGE_DAYS = max(1, int(os.getenv("TRACKED_RESULT_AGE_DAYS", str(MAX_RESULT_AGE_DAYS))))
DISCOVERY_INTERVAL_HOURS = max(
    1,
    int(os.getenv("DISCOVERY_INTERVAL_HOURS", "72")),  # Default to every 3 days for discovery workflow
)
SWEEP_STALE_DAYS = max(1, int(os.getenv("SWEEP_STALE_DAYS", "14")))

TRACKED_BATCH_SITES = [
    s.strip() for s in os.getenv("TRACKED_BATCH_SITES", ",".join(REPUTABLE_SITES)).split(",") if s.strip()
] or list(REPUTABLE_SITES)

# Delimiter is '|', to avoid conflicts with comma-separated site lists.
TRACKED_BATCH_SEARCH_QUERIES = [
    q.strip() for q in os.getenv("TRACKED_BATCH_SEARCH_QUERIES", "{ticker} {stock_name} stock analysis").split("|") if q.strip()
] or ["{ticker} {stock_name} stock analysis"]


def build_tracked_query(ticker: str, stock_name: str, template: str, sites: List[str]) -> str:
    """Build one CSE query that targets multiple sites via OR filters.

    Ensures tracked queries include both ticker and stock name when available.
    """
    normalized_ticker = str(ticker or "").strip().upper()
    normalized_stock_name = " ".join(str(stock_name or "").split())

    base_query = template.replace("{ticker}", normalized_ticker)
    base_query = base_query.replace(
        "{stock_name}",
        f'"{normalized_stock_name}"' if normalized_stock_name else "",
    )
    base_query = " ".join(base_query.split())

    if normalized_stock_name:
        if normalized_ticker and normalized_ticker not in base_query:
            base_query = f"{normalized_ticker} {base_query}".strip()
        if normalized_stock_name.lower() not in base_query.lower():
            base_query = f'"{normalized_stock_name}" {base_query}'.strip()

    site_filter = " OR ".join(f"site:{site}" for site in sites if site)
    if not site_filter:
        return base_query
    return f"{base_query} ({site_filter})"


# Legacy tracked-search settings retained for backwards compatibility.
TRACKED_STOCK_SEARCH_QUERIES = [
    "{ticker} stock analysis site:{site}",
    "{ticker} stock rating site:{site}",
]
MAX_TRACKED_STOCK_SEARCHES = max(0, int(os.getenv("MAX_TRACKED_STOCK_SEARCHES", "20")))

# API Keys
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
FMP_API_KEY = os.getenv("FMP_API_KEY")

# Authentication
APP_PASSWORD = os.getenv("APP_PASSWORD", "")

# Filter settings
MAX_PE_RATIO = float(os.getenv("MAX_PE_RATIO", "15.0"))
MIN_MARKET_CAP = float(os.getenv("MIN_MARKET_CAP", "1000000000"))  # $1B

# New stocks (not in recommended_stock) must meet this minimum rating to be persisted.
MIN_RATING_NEW_STOCK = min(5, max(1, int(os.getenv("MIN_RATING_NEW_STOCK", "4"))))

# Thread pool settings
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "2"))

# Browser scraping timeout (seconds) to avoid indefinite hangs on problematic pages.
BROWSER_FETCH_TIMEOUT_SECONDS = max(10, int(os.getenv("BROWSER_FETCH_TIMEOUT_SECONDS", "90")))

# Recommendations aggregation settings
RECOMMENDATION_LOOKBACK_MONTHS = max(0, int(os.getenv("RECOMMENDATION_LOOKBACK_MONTHS", "2")))