"""
General Application Configuration
"""

import os
from pathlib import Path
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
    "zacks.com",
    "seekingalpha.com"
]

# API Keys
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
FMP_API_KEY = os.getenv("FMP_API_KEY")

# Authentication
APP_PASSWORD = os.getenv("APP_PASSWORD", "")

# Filter settings
MAX_PE_RATIO = float(os.getenv("MAX_PE_RATIO", "15.0"))
MIN_MARKET_CAP = float(os.getenv("MIN_MARKET_CAP", "1000000000"))  # $1B

# Thread pool settings
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "2"))