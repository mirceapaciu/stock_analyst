"""Database module for stock recommendations tracking."""

import sqlite3
import csv
import json
import logging
import os
from fnmatch import fnmatch
from dataclasses import dataclass
from typing import List, Dict, Optional
from datetime import date, timedelta, datetime
from pathlib import Path
import time
from urllib.parse import urlsplit, urlunsplit
from config import (
    RECOMMENDATIONS_DB_PATH,
    FINNHUB_API_KEY,
    RECOMMENDATION_LOOKBACK_MONTHS,
    TRACKED_BATCH_SIZE,
)
from utils.s3_storage import get_s3_storage

logger = logging.getLogger(__name__)


@dataclass
class BatchSweep:
    """Represents persisted sweep state for tracked-stock batch processing."""

    workflow_type: str
    ticker_list: List[str]
    batch_index: int
    total_batches: int
    batch_size: int
    sweep_started_at: Optional[str] = None
    last_batch_at: Optional[str] = None
    last_batch_status: Optional[str] = None
    sweep_completed_at: Optional[str] = None

    def next_batch(self, batch_size: Optional[int] = None) -> List[str]:
        """Return the next ticker slice using the persisted cursor."""
        size = max(1, int(batch_size or self.batch_size or 1))
        start = max(0, int(self.batch_index or 0))
        end = start + size
        return self.ticker_list[start:end]

    def next_batch_number(self, batch_size: Optional[int] = None) -> int:
        """Return 1-based batch sequence number for reporting."""
        if not self.ticker_list:
            return 0
        size = max(1, int(batch_size or self.batch_size or 1))
        return (max(0, int(self.batch_index or 0)) // size) + 1


class RecommendationsDatabase:
    """Manages SQLite database for stock recommendations."""

    @staticmethod
    def _normalize_domain(domain: str) -> str:
        normalized = (domain or '').strip().lower()
        if normalized.startswith('www.'):
            normalized = normalized[4:]
        return normalized

    @classmethod
    def _normalize_url_pattern(cls, url: str) -> str:
        parsed = urlsplit((url or '').strip())
        scheme = (parsed.scheme or 'https').lower()
        netloc = parsed.netloc.lower()
        path = parsed.path or '/'
        return urlunsplit((scheme, netloc, path, '', ''))

    @staticmethod
    def _looks_dynamic_url_segment(segment: str) -> bool:
        candidate = (segment or '').strip()
        if not candidate:
            return False
        if candidate.isdigit():
            return True
        if any(char.isdigit() for char in candidate):
            return True
        if '.' in candidate and any(char.isalpha() for char in candidate) and candidate.upper() == candidate:
            return True
        if candidate.upper() == candidate and any(char.isalpha() for char in candidate) and len(candidate) <= 12:
            return True
        return False

    @classmethod
    def _build_blocked_url_patterns(cls, url: str) -> List[str]:
        normalized_url = cls._normalize_url_pattern(url)
        parsed = urlsplit(normalized_url)
        segments = [segment for segment in parsed.path.split('/') if segment]
        patterns = [normalized_url]

        if not segments:
            return patterns

        wildcard_segments = []
        wildcard_count = 0
        for segment in segments:
            if cls._looks_dynamic_url_segment(segment):
                wildcard_segments.append('*')
                wildcard_count += 1
            else:
                wildcard_segments.append(segment)

        if 0 < wildcard_count <= min(3, len(segments)):
            wildcard_path = '/' + '/'.join(wildcard_segments)
            if parsed.path.endswith('/'):
                wildcard_path += '/'
            wildcard_url = urlunsplit((parsed.scheme, parsed.netloc, wildcard_path, '', ''))
            if wildcard_url != normalized_url:
                patterns.append(wildcard_url)

        return patterns
    
    def __init__(self, db_path: str = RECOMMENDATIONS_DB_PATH):
        """Initialize database connection and create tables if needed."""
        self.db_path = db_path
        self._rating_map_cache = None  # Cache for rating name to ID mapping
        
        # Try to download database from S3 on initialization (only if S3 is configured and not using EFS)
        # EFS provides persistent storage, so S3 sync is optional/for backup
        use_s3_sync = os.getenv("USE_S3_SYNC", "true").lower() == "true"
        if use_s3_sync:
            s3 = get_s3_storage()
            if s3.s3_client:
                logger.info(f"Checking S3 for existing database: {Path(db_path).name}")
                s3.sync_database_from_s3(db_path)
        
        self.init_database()
    
    def _get_connection(self):
        """Get a database connection with proper timeout and WAL mode settings."""
        # Ensure parent directory exists before connecting
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        
        conn = sqlite3.connect(self.db_path, timeout=30.0)  # Wait up to 30 seconds
        conn.execute('PRAGMA journal_mode=WAL')  # Enable Write-Ahead Logging for better concurrency
        conn.execute('PRAGMA busy_timeout=30000')  # 30 second timeout in milliseconds
        return conn
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit. Sync to S3 on clean exit (optional, for backup)."""
        # Only sync to S3 if enabled (EFS provides primary persistence)
        use_s3_sync = os.getenv("USE_S3_SYNC", "true").lower() == "true"
        if exc_type is None and use_s3_sync:  # Only sync if no exception occurred and S3 sync is enabled
            self._sync_to_s3()
        return False
    
    def _sync_to_s3(self):
        """Sync database to S3 after changes (optional backup)."""
        s3 = get_s3_storage()
        if s3.s3_client:
            s3.sync_database_to_s3(self.db_path)
    
    def init_database(self):
        """Create all required tables if they don't exist."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Market table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS market (
                mic VARCHAR(10) PRIMARY KEY,
                market_name VARCHAR(100),
                market_category_code VARCHAR(20),
                acronym VARCHAR(10),
                iso_country_code VARCHAR(2),
                city VARCHAR(50),
                website VARCHAR(100),
                currency_code VARCHAR(10)
            )
        """)

        # Website table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS website (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain VARCHAR(50) NOT NULL UNIQUE,
                is_usable INTEGER NOT NULL DEFAULT 0,
                requires_browser INTEGER NOT NULL DEFAULT 0
            )
        """)

        # Webpage table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS webpage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url VARCHAR(500) NOT NULL,
                date DATE,
                title VARCHAR(200),
                excerpt VARCHAR(1000),
                page_text TEXT,
                last_seen_date DATE NOT NULL,
                website_id INTEGER,
                is_stock_recommendation INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (website_id) REFERENCES website(id),
                UNIQUE (url, date)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS blocked_url_pattern (
                pattern VARCHAR(500) PRIMARY KEY,
                domain VARCHAR(100) NOT NULL,
                status_code INTEGER,
                reason VARCHAR(100),
                hit_count INTEGER NOT NULL DEFAULT 1,
                first_seen_at TIMESTAMP NOT NULL,
                last_seen_at TIMESTAMP NOT NULL
            )
        """)

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_blocked_url_pattern_domain ON blocked_url_pattern (domain)"
        )

        # Stock table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                isin CHAR(12),
                ticker VARCHAR(10) NOT NULL,
                exchange VARCHAR(20) NOT NULL,
                mic VARCHAR(10),
                stock_name VARCHAR(100),
                FOREIGN KEY (mic) REFERENCES market(mic),
                UNIQUE (ticker, exchange)
            )
        """)

        # Stock table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_note (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_id INTEGER references stock(id),
                note TEXT,
                entry_date DATE
            )
        """)

        # Reference stock rating table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ref_stock_rating (
                id INTEGER PRIMARY KEY,
                name VARCHAR(20) NOT NULL UNIQUE
            )
        """)

        # Input stock recommendation table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS input_stock_recommendation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker VARCHAR(10),
                exchange VARCHAR(20),
                currency_code VARCHAR(10),
                stock_id INTEGER references stock(id),
                isin CHAR(12),
                stock_name VARCHAR(100),
                rating_id INTEGER references ref_stock_rating(id),
                analysis_date DATE,
                price DECIMAL(10,2),
                fair_price DECIMAL(10,2),
                target_price DECIMAL(10,2),
                price_growth_forecast_pct DECIMAL(10,2),
                pe DECIMAL(6,2),
                recommendation_text VARCHAR(10000),
                quality_score INTEGER,
                quality_description_words INTEGER,
                quality_has_rating INTEGER,
                quality_reasoning_level INTEGER,
                is_invalid INTEGER NOT NULL DEFAULT 0,
                webpage_id INTEGER,
                entry_date DATE,
                FOREIGN KEY (isin) REFERENCES stock(isin),
                FOREIGN KEY (webpage_id) REFERENCES webpage(id)
            )
        """)

        # Recommendation feedback table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recommendation_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recommendation_id INTEGER NOT NULL,
                stock_id INTEGER,
                feedback_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (recommendation_id) REFERENCES input_stock_recommendation(id),
                FOREIGN KEY (stock_id) REFERENCES stock(id)
            )
        """)

        # Recommendation feedback invalid fields table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recommendation_feedback_invalid_fields (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feedback_id INTEGER NOT NULL,
                field_name VARCHAR(50) NOT NULL,
                FOREIGN KEY (feedback_id) REFERENCES recommendation_feedback(id)
            )
        """)

        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_webpage_unique ON input_stock_recommendation (stock_id, webpage_id)")

        # Recommended stock table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recommended_stock (
                stock_id INTEGER PRIMARY KEY,
                rating DECIMAL(2,1),
                last_analysis_date DATE,
                fair_price DECIMAL(10,2),
                target_price DECIMAL(10,2),
                price_growth_forecast_pct DECIMAL(10,2),
                market_price DECIMAL(10,2),
                market_cap INTEGER,
                market_pe DECIMAL(6,2),
                entry_date DATE,
                market_date DATE,
                FOREIGN KEY (stock_id) REFERENCES stock(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS favorite_stock (
                stock_id INTEGER PRIMARY KEY,
                entry_date DATE NOT NULL,
                price_on_entry_date DECIMAL(10,2) NOT NULL,
                FOREIGN KEY (stock_id) REFERENCES stock(id)
            )
        """)

        # Process tracking table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS process (
                process_name VARCHAR(50) PRIMARY KEY,
                start_timestamp TIMESTAMP,
                end_timestamp TIMESTAMP,
                progress_pct INTEGER DEFAULT 0,
                   status VARCHAR(20) DEFAULT 'STARTED',
                   message TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS batch_schedule (
                workflow_type VARCHAR(50) PRIMARY KEY,
                ticker_list TEXT NOT NULL DEFAULT '[]',
                batch_index INTEGER NOT NULL DEFAULT 0,
                total_batches INTEGER NOT NULL DEFAULT 0,
                sweep_started_at TIMESTAMP,
                last_batch_at TIMESTAMP,
                last_batch_status VARCHAR(20),
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                sweep_completed_at TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cse_usage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_date DATE NOT NULL,
                workflow_type VARCHAR(50) NOT NULL,
                queries_count INTEGER NOT NULL,
                logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_cse_usage_date ON cse_usage_log(query_date)"
        )

        # Populate ref_stock_rating table if empty
        cursor.execute("SELECT COUNT(*) FROM ref_stock_rating")
        if cursor.fetchone()[0] == 0:
            cursor.executemany(
                "INSERT INTO ref_stock_rating (id, name) VALUES (?, ?)",
                [
                    (0, 'N/A'),
                    (1, 'Strong Sell'),
                    (2, 'Sell'),
                    (3, 'Hold'),
                    (4, 'Buy'),
                    (5, 'Strong Buy')
                ]
            )

        conn.commit()
        conn.close()
        
        # Migration: Add page_text column if it doesn't exist
        # FIXME: once all deployments have this column, remove this call
        self._add_page_text_column_if_missing()
        
        # Migration: Add quality columns if they don't exist
        self._add_quality_columns_if_missing()

        # Migration: Add is_invalid column if it doesn't exist
        self._add_is_invalid_column_if_missing()

        # Migration: Add currency_code column if it doesn't exist
        self._add_currency_code_column_if_missing()

        # Migration: Add currency_code column to market table if it doesn't exist
        self._add_market_currency_code_column_if_missing()
        
        # Migration: Add fair_price_dcf column to recommended_stock if it doesn't exist
        self._add_fair_price_dcf_column_if_missing()

        # Migration: Add consecutive_failures column to batch_schedule if it doesn't exist
        self._add_batch_schedule_consecutive_failures_if_missing()

        # Migration: Add message column to process table if it doesn't exist
        self._add_process_message_column_if_missing()

        # Migration: Remove fair_price_dcf column from favorite_stock if it exists (moved to recommended_stock)
        self._remove_fair_price_dcf_from_favorite_stock_if_exists()
        
        # Load website data from CSV if the website table is empty
        self.load_websites_if_empty()
    
    def _add_process_message_column_if_missing(self) -> None:
        """Add message column to process table if it doesn't exist."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(process)")
        columns = [column[1] for column in cursor.fetchall()]

        if 'message' not in columns:
            cursor.execute("ALTER TABLE process ADD COLUMN message TEXT")
            conn.commit()
            logger.info("Added message column to process table")

        conn.close()

    def _add_page_text_column_if_missing(self):
        """Add page_text column to webpage table if it doesn't exist."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Check if column exists
        cursor.execute("PRAGMA table_info(webpage)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'page_text' not in columns:
            cursor.execute("ALTER TABLE webpage ADD COLUMN page_text TEXT")
            conn.commit()
            logger.info("Added page_text column to webpage table")
        
        conn.close()
    
    def _add_quality_columns_if_missing(self):
        """Add quality assessment columns to input_stock_recommendation table if they don't exist."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Check if columns exist
        cursor.execute("PRAGMA table_info(input_stock_recommendation)")
        columns = [column[1] for column in cursor.fetchall()]
        
        quality_columns = {
            'quality_score': 'INTEGER',
            'quality_description_words': 'INTEGER',
            'quality_has_rating': 'INTEGER',
            'quality_reasoning_level': 'INTEGER'
        }
        
        for col_name, col_type in quality_columns.items():
            if col_name not in columns:
                cursor.execute(f"ALTER TABLE input_stock_recommendation ADD COLUMN {col_name} {col_type}")
                logger.info(f"Added {col_name} column to input_stock_recommendation table")
        
        conn.commit()
        conn.close()

    def _add_is_invalid_column_if_missing(self):
        """Add is_invalid column to input_stock_recommendation table if it doesn't exist."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(input_stock_recommendation)")
        columns = [column[1] for column in cursor.fetchall()]

        if 'is_invalid' not in columns:
            cursor.execute("ALTER TABLE input_stock_recommendation ADD COLUMN is_invalid INTEGER NOT NULL DEFAULT 0")
            conn.commit()
            logger.info("Added is_invalid column to input_stock_recommendation table")

        conn.close()

    def _add_currency_code_column_if_missing(self):
        """Add currency_code column to input_stock_recommendation table if it doesn't exist."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(input_stock_recommendation)")
        columns = [column[1] for column in cursor.fetchall()]

        if 'currency_code' not in columns:
            cursor.execute("ALTER TABLE input_stock_recommendation ADD COLUMN currency_code VARCHAR(10)")
            conn.commit()
            logger.info("Added currency_code column to input_stock_recommendation table")

        conn.close()

    def _add_market_currency_code_column_if_missing(self):
        """Add currency_code column to market table if it doesn't exist."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(market)")
        columns = [column[1] for column in cursor.fetchall()]

        if 'currency_code' not in columns:
            cursor.execute("ALTER TABLE market ADD COLUMN currency_code VARCHAR(10)")
            conn.commit()
            logger.info("Added currency_code column to market table")

        conn.close()
    
    def _add_fair_price_dcf_column_if_missing(self):
        """Add fair_price_dcf column to recommended_stock table if it doesn't exist."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Check if column exists
        cursor.execute("PRAGMA table_info(recommended_stock)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'fair_price_dcf' not in columns:
            cursor.execute("ALTER TABLE recommended_stock ADD COLUMN fair_price_dcf DECIMAL(10,2)")
            conn.commit()
            logger.info("Added fair_price_dcf column to recommended_stock table")
        
        conn.close()

    def _add_batch_schedule_consecutive_failures_if_missing(self):
        """Add consecutive_failures column to batch_schedule if missing."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(batch_schedule)")
        columns = [column[1] for column in cursor.fetchall()]

        if 'consecutive_failures' not in columns:
            cursor.execute(
                "ALTER TABLE batch_schedule ADD COLUMN consecutive_failures INTEGER NOT NULL DEFAULT 0"
            )
            conn.commit()
            logger.info("Added consecutive_failures column to batch_schedule table")

        conn.close()
    
    def _remove_fair_price_dcf_from_favorite_stock_if_exists(self):
        """Remove fair_price_dcf column from favorite_stock if it exists (moved to recommended_stock).
        
        Note: SQLite doesn't support DROP COLUMN directly, so we need to recreate the table.
        This migration preserves existing data and moves fair_price_dcf values to recommended_stock.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Check if column exists in favorite_stock
        cursor.execute("PRAGMA table_info(favorite_stock)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'fair_price_dcf' in columns:
            # SQLite doesn't support DROP COLUMN, so we need to recreate the table
            # First, migrate any existing fair_price_dcf values to recommended_stock
            cursor.execute("""
                UPDATE recommended_stock 
                SET fair_price_dcf = (
                    SELECT fair_price_dcf 
                    FROM favorite_stock 
                    WHERE favorite_stock.stock_id = recommended_stock.stock_id
                )
                WHERE EXISTS (
                    SELECT 1 
                    FROM favorite_stock 
                    WHERE favorite_stock.stock_id = recommended_stock.stock_id 
                    AND favorite_stock.fair_price_dcf IS NOT NULL
                )
            """)
            
            # Recreate favorite_stock table without fair_price_dcf column
            cursor.execute("""
                CREATE TABLE favorite_stock_new (
                    stock_id INTEGER PRIMARY KEY,
                    entry_date DATE NOT NULL,
                    price_on_entry_date DECIMAL(10,2) NOT NULL,
                    FOREIGN KEY (stock_id) REFERENCES stock(id)
                )
            """)
            
            cursor.execute("""
                INSERT INTO favorite_stock_new (stock_id, entry_date, price_on_entry_date)
                SELECT stock_id, entry_date, price_on_entry_date
                FROM favorite_stock
            """)
            
            cursor.execute("DROP TABLE favorite_stock")
            cursor.execute("ALTER TABLE favorite_stock_new RENAME TO favorite_stock")
            
            conn.commit()
            logger.info("Removed fair_price_dcf column from favorite_stock table (moved to recommended_stock)")
        
        conn.close()
    
    def load_websites_if_empty(self):
        """Load website data from CSV file if the website table is empty."""
        if not self.is_websites_table_empty():
            return
        
        # Look for CSV file in data/input directory
        csv_path = Path(self.db_path).parent.parent / "input" / "website.csv"
        
        if not csv_path.exists():
            logger.warning(f"Website CSV not found at {csv_path}. Skipping initial data load.")
            return
        
        try:
            loaded_count = 0
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    domain = row['domain'].strip()
                    is_usable = int(row['is_usable'])
                    requires_browser = int(row.get('requires_browser', 0))
                    self.upsert_website(domain, is_usable, requires_browser)
                    loaded_count += 1
            
            logger.info(f"Loaded {loaded_count} websites from {csv_path.name}")
        except Exception as e:
            logger.warning(f"Failed to load website data: {e}")

    def is_websites_table_empty(self) -> bool:
        """Check if the website table is empty."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM website")
        count = cursor.fetchone()[0]
        
        conn.close()
        return count == 0

    def upsert_website(self, domain: str, is_usable: int = None, requires_browser: int = None) -> int:
        """Insert or get website ID."""
        conn = self._get_connection()
        cursor = conn.cursor()

        normalized_domain = self._normalize_domain(domain)
        
        cursor.execute("SELECT id, is_usable, requires_browser FROM website WHERE domain = ?", (normalized_domain,))
        result = cursor.fetchone()

        if result:
            website_id = result[0]
            existing_is_usable = result[1]
            existing_requires_browser = result[2]
            
            # Only update if values were explicitly provided
            new_is_usable = is_usable if is_usable is not None else existing_is_usable
            new_requires_browser = requires_browser if requires_browser is not None else existing_requires_browser
            
            cursor.execute("UPDATE website SET is_usable = ?, requires_browser = ? WHERE id = ?", 
                         (new_is_usable, new_requires_browser, website_id))
            conn.commit()
        else:
            # Insert with defaults if not provided
            final_is_usable = is_usable if is_usable is not None else 2
            final_requires_browser = requires_browser if requires_browser is not None else 0
            cursor.execute("INSERT INTO website (domain, is_usable, requires_browser) VALUES (?, ?, ?)", 
                         (normalized_domain, final_is_usable, final_requires_browser))
            website_id = cursor.lastrowid
            conn.commit()
        
        conn.close()
        return website_id
    
    def upsert_webpage(self, url: str, date: str, title: str, excerpt: str, 
                       last_seen_date: str, website_id: int, is_stock_recommendation: int = 0,
                       page_text: str = None) -> int:
        """Insert or update webpage record."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT id FROM webpage WHERE url = ? AND date = ?", (url, date))
        result = cursor.fetchone()
        
        if result:
            webpage_id = result[0]
            cursor.execute("""
                UPDATE webpage 
                SET last_seen_date = ?, is_stock_recommendation = ?, page_text = ?
                WHERE id = ?
            """, (last_seen_date, is_stock_recommendation, page_text, webpage_id))
        else:
            cursor.execute("""
                INSERT INTO webpage (url, date, title, excerpt, page_text, last_seen_date, website_id, is_stock_recommendation)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (url, date, title, excerpt, page_text, last_seen_date, website_id, is_stock_recommendation))
            webpage_id = cursor.lastrowid
        
        conn.commit()
        conn.close()
        return webpage_id
    
    def webpage_exists(self, url: str, date: str) -> bool:
        """Check if webpage with same URL and date already exists."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        if date is None:
            cursor.execute("SELECT id FROM webpage WHERE url = ? AND date IS NULL", (url,))
        else:
            cursor.execute("SELECT id FROM webpage WHERE url = ? AND date = ?", (url, date))
        
        result = cursor.fetchone()
        conn.close()
        return result is not None

    def get_webpage_by_id(self, webpage_id: int) -> Dict:
        """Get webpage details by ID."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, url, date, title, excerpt, last_seen_date, website_id, is_stock_recommendation
            FROM webpage 
            WHERE id = ?
        """, (webpage_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'id': row[0],
                'url': row[1],
                'date': row[2],
                'title': row[3],
                'excerpt': row[4],
                'last_seen_date': row[5],
                'website_id': row[6],
                'is_stock_recommendation': row[7]
            }
        return None

    def get_unusable_domains(self) -> List[str]:
        """Get list of domains marked as unusable (is_usable=0)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT domain FROM website WHERE is_usable = 0")
        domains = [row[0] for row in cursor.fetchall()]
        
        conn.close()
        return domains

    def record_blocked_url(self, url: str, status_code: Optional[int] = None, reason: Optional[str] = None) -> List[str]:
        """Persist an exact URL and a coarse wildcard URL pattern for terminal blocked pages."""
        normalized_url = self._normalize_url_pattern(url)
        parsed = urlsplit(normalized_url)
        domain = self._normalize_domain(parsed.netloc)
        patterns = self._build_blocked_url_patterns(normalized_url)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        conn = self._get_connection()
        cursor = conn.cursor()

        for pattern in patterns:
            cursor.execute(
                """
                INSERT INTO blocked_url_pattern (pattern, domain, status_code, reason, hit_count, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(pattern) DO UPDATE SET
                    status_code = COALESCE(excluded.status_code, blocked_url_pattern.status_code),
                    reason = COALESCE(excluded.reason, blocked_url_pattern.reason),
                    hit_count = blocked_url_pattern.hit_count + 1,
                    last_seen_at = excluded.last_seen_at
                """,
                (pattern, domain, status_code, reason, timestamp, timestamp),
            )

        conn.commit()
        conn.close()
        return patterns

    def get_blocked_url_match(self, url: str) -> Optional[Dict]:
        """Return matching blocked URL rule for a URL, if any."""
        normalized_url = self._normalize_url_pattern(url)
        parsed = urlsplit(normalized_url)
        domain = self._normalize_domain(parsed.netloc)

        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT pattern, status_code, reason, hit_count
            FROM blocked_url_pattern
            WHERE domain = ?
            ORDER BY CASE WHEN instr(pattern, '*') = 0 THEN 0 ELSE 1 END, LENGTH(pattern) DESC
            """,
            (domain,),
        )
        rows = cursor.fetchall()
        conn.close()

        for pattern, status_code, reason, hit_count in rows:
            if fnmatch(normalized_url, pattern):
                return {
                    'pattern': pattern,
                    'status_code': status_code,
                    'reason': reason,
                    'hit_count': hit_count,
                }

        return None

    def get_blocked_url_patterns(self) -> List[str]:
        """Return all persisted blocked URL patterns."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT pattern FROM blocked_url_pattern ORDER BY pattern")
        patterns = [row[0] for row in cursor.fetchall()]
        conn.close()
        return patterns
    
    def needs_browser_rendering(self, domain: str) -> bool:
        """Check if domain requires browser rendering for JavaScript content."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Check exact domain or any parent domain
        domain_parts = self._normalize_domain(domain).split('.')
        domains_to_check = ['.'.join(domain_parts[i:]) for i in range(len(domain_parts) - 1)]
        
        for check_domain in domains_to_check:
            cursor.execute("SELECT requires_browser FROM website WHERE domain = ? LIMIT 1", (check_domain,))
            result = cursor.fetchone()
            
            if result is not None:
                conn.close()
                return result[0] == 1
        
        conn.close()
        return False
    
    def upsert_stock(self, isin: str, ticker: str, exchange: str, stock_name: str, mic: str = None) -> int:
        """Insert or update stock record."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Check if stock exists by ticker + exchange (unique constraint)
        cursor.execute("SELECT id FROM stock WHERE ticker = ? AND exchange = ?", (ticker, exchange))
        result = cursor.fetchone()
        
        if result:
            # Update existing record
            stock_id = result[0]
            cursor.execute("""
                UPDATE stock 
                SET isin = ?, mic = ?, stock_name = ?
                WHERE id = ?
            """, (isin, mic, stock_name, stock_id))
        else:
            # Insert new record
            cursor.execute("""
                INSERT INTO stock (isin, ticker, exchange, mic, stock_name)
                VALUES (?, ?, ?, ?, ?)
            """, (isin, ticker, exchange, mic, stock_name))
            stock_id = cursor.lastrowid
        
        conn.commit()
        conn.close()
        return stock_id
    
    def insert_stock_recommendation(self, recommendation: Dict) -> int:
        """Insert a stock recommendation record.
        
        Returns:
            The recommendation ID, or None if duplicate (stock_id, webpage_id) combination
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Get or create stock_id if not provided
        stock_id = recommendation.get('stock_id')
        if not stock_id:
            # Look up stock by ticker + exchange
            ticker = recommendation.get('ticker')
            exchange = recommendation.get('exchange')
            cursor.execute("SELECT id FROM stock WHERE ticker = ? AND exchange = ?", (ticker, exchange))
            result = cursor.fetchone()
            if result:
                stock_id = result[0]
        
        try:
            cursor.execute("""
                INSERT INTO input_stock_recommendation (
                    ticker, exchange, currency_code, stock_id, isin, stock_name, rating_id, analysis_date,
                    price, fair_price, target_price, price_growth_forecast_pct, pe,
                    recommendation_text, quality_score, quality_description_words,
                    quality_has_rating, quality_reasoning_level, is_invalid,
                    webpage_id, entry_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                recommendation.get('ticker'),
                recommendation.get('exchange'),
                recommendation.get('currency_code'),
                stock_id,
                recommendation.get('isin'),
                recommendation.get('stock_name'),
                recommendation.get('rating_id'),
                recommendation.get('analysis_date'),
                recommendation.get('price'),
                recommendation.get('fair_price'),
                recommendation.get('target_price'),
                recommendation.get('price_growth_forecast_pct'),
                recommendation.get('pe'),
                recommendation.get('recommendation_text'),
                recommendation.get('quality_score'),
                recommendation.get('quality_description_words'),
                1 if recommendation.get('quality_has_rating') else 0,
                recommendation.get('quality_reasoning_level'),
                recommendation.get('is_invalid', 0),
                recommendation.get('webpage_id'),
                recommendation.get('entry_date')
            ))
            
            recommendation_id = cursor.lastrowid
            conn.commit()
            conn.close()
            return recommendation_id
        except sqlite3.IntegrityError as e:
            conn.close()
            if "idx_stock_webpage_unique" in str(e) or "UNIQUE constraint failed" in str(e):
                logger.warning(f"Duplicate recommendation: stock_id={stock_id}, webpage_id={recommendation.get('webpage_id')}. Skipping.")
                return None
            else:
                # Re-raise if it's a different integrity error
                raise
    
    def get_all_stock_recommendations(self) -> List[Dict]:
        """Retrieve all stock recommendations."""
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT ticker, exchange, stock_name, rsr.name AS rating, 
                max(analysis_date) as last_analysis_date, avg(price) as price, avg(fair_price) as fair_price, 
                avg(target_price) as target_price, avg(price_growth_forecast_pct) as price_growth_forecast_pct            
            FROM input_stock_recommendation isr
            JOIN ref_stock_rating rsr ON isr.rating_id = rsr.id
            WHERE IFNULL(isr.is_invalid, 0) = 0
            GROUP BY ticker, exchange, stock_name, rsr.name
            ORDER BY isr.rating_id DESC
        """)
        rows = cursor.fetchall()
        
        recommendations = [dict(row) for row in rows]
        conn.close()
        
        return recommendations
    
    def get_mic_by_exchange(self, exchange: str) -> str:
        """Look up MIC code by exchange name or acronym."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Try exact match on acronym first (case-insensitive)
        cursor.execute("""
            SELECT mic FROM market 
            WHERE UPPER(acronym) = UPPER(?)
            LIMIT 1
        """, (exchange,))
        result = cursor.fetchone()
        
        if result:
            conn.close()
            return result[0]
        
        # Try partial match on market_name (case-insensitive)
        cursor.execute("""
            SELECT mic FROM market 
            WHERE UPPER(market_name) LIKE UPPER(?)
            LIMIT 1
        """, (f'%{exchange}%',))
        result = cursor.fetchone()
        
        if result:
            conn.close()
            return result[0]
        
        # No result found - check if market table is empty
        cursor.execute("SELECT COUNT(*) FROM market")
        count = cursor.fetchone()[0]
        conn.close()
        
        if count == 0:
            # Market table is empty, try to load from CSV
            logger.info("Market table is empty. Loading data from data/input/market.csv...")
            if self.load_market_data_from_csv():
                # Retry the lookup after loading
                return self.get_mic_by_exchange(exchange)
        
        return None
    
    def load_market_data_from_csv(self, csv_path: str = None) -> bool:
        """Load market data from CSV file into the market table."""
        if csv_path is None:
            # Use path relative to database file
            csv_path = Path(self.db_path).parent.parent / "input" / "market.csv"
        
        if not Path(csv_path).exists():
            logger.warning(f"Market CSV file not found at: {csv_path}")
            return False
        
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            with open(csv_path, 'r', encoding='utf-8') as f:
                csv_reader = csv.DictReader(f)
                
                rows_inserted = 0
                for row in csv_reader:
                    try:
                        cursor.execute("""
                            INSERT OR IGNORE INTO market (mic, market_name, market_category_code, acronym, iso_country_code, city, website)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (
                            row.get('MIC', '').strip(),
                            row.get('MARKET_NAME', '').strip(),
                            row.get('MARKET_CATEGORY_CODE', '').strip(),
                            row.get('ACRONYM', '').strip(),
                            row.get('ISO_COUNTRY_CODE', '').strip(),
                            row.get('CITY', '').strip(),
                            row.get('WEBSITE', '').strip()
                        ))
                        rows_inserted += 1
                    except Exception as e:
                        logger.error(f"Error inserting row: {e}")
                        continue
                
                conn.commit()
                conn.close()
                
                logger.info(f"Successfully loaded {rows_inserted} market records from CSV")
                return True
                
        except Exception as e:
            logger.error(f"Error loading market data from CSV: {e}")
            return False
    
    def get_rating_name_to_id_map(self) -> Dict[str, int]:
        """Get a dictionary mapping rating names to their IDs."""
        # Return cached value if available
        if self._rating_map_cache is not None:
            return self._rating_map_cache
        
        # Query database and cache the result
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, name FROM ref_stock_rating")
        rows = cursor.fetchall()
        
        self._rating_map_cache = {name: rating_id for rating_id, name in rows}
        conn.close()
        
        return self._rating_map_cache
    
    def find_stock_in_db(self, ticker: str, exchange: str = None) -> List[Dict]:
        """Look up stock in the database only (no external API calls).
        
        Args:
            ticker: Stock ticker symbol
            exchange: Optional exchange to filter results
            
        Returns:
            List of matching stock records from database, empty list if not found
        """
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if exchange:
            cursor.execute(
                "SELECT * FROM stock WHERE ticker = ? AND exchange = ?",
                (ticker, exchange)
            )
        else:
            cursor.execute(
                "SELECT * FROM stock WHERE ticker = ?",
                (ticker,)
            )
        
        results = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in results]

    def has_recommended_stock(self, stock_id: int) -> bool:
        """Return True when a stock already exists in recommended_stock."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT 1 FROM recommended_stock WHERE stock_id = ? LIMIT 1",
            (stock_id,)
        )
        exists = cursor.fetchone() is not None
        conn.close()

        return exists

    def get_tracked_tickers(self, limit: int = 0) -> List[str]:
        """Return ticker symbols that are already tracked in recommended_stock.

        Args:
            limit: Optional max number of tickers to return. 0 means no limit.
        """
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = """
            SELECT DISTINCT s.ticker
            FROM recommended_stock rs
            JOIN stock s ON rs.stock_id = s.id
            WHERE s.ticker IS NOT NULL AND TRIM(s.ticker) <> ''
            ORDER BY rs.last_analysis_date DESC, rs.stock_id DESC
        """

        if limit and limit > 0:
            cursor.execute(query + " LIMIT ?", (limit,))
        else:
            cursor.execute(query)

        rows = cursor.fetchall()
        conn.close()

        return [str(row["ticker"]).strip().upper() for row in rows if row["ticker"]]

    def get_tracked_tickers_by_min_rating(self, min_rating: float = 4.0) -> List[str]:
        """Return tracked tickers with rating >= min_rating ordered by staleness."""
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT DISTINCT s.ticker
            FROM recommended_stock rs
            JOIN stock s ON rs.stock_id = s.id
            WHERE rs.rating >= ?
              AND s.ticker IS NOT NULL
              AND TRIM(s.ticker) <> ''
            ORDER BY COALESCE(rs.last_analysis_date, '1970-01-01') ASC, s.ticker ASC
            """,
            (min_rating,),
        )

        rows = cursor.fetchall()
        conn.close()

        return [str(row["ticker"]).strip().upper() for row in rows if row["ticker"]]

    @staticmethod
    def _normalize_ticker_list(raw_tickers: List[str]) -> List[str]:
        """Normalize and deduplicate ticker list while preserving order."""
        normalized: List[str] = []
        seen = set()

        for ticker in raw_tickers:
            value = str(ticker or '').strip().upper()
            if not value or value in seen:
                continue
            seen.add(value)
            normalized.append(value)

        return normalized

    @staticmethod
    def _parse_sqlite_timestamp(timestamp_value: Optional[str]) -> Optional[datetime]:
        """Parse SQLite timestamp strings into datetime objects."""
        if not timestamp_value:
            return None

        raw_value = str(timestamp_value).strip()
        if not raw_value:
            return None

        try:
            return datetime.fromisoformat(raw_value)
        except ValueError:
            pass

        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw_value, fmt)
            except ValueError:
                continue

        return None

    def _start_new_sweep(self, workflow_type: str, min_rating: float, batch_size: int) -> BatchSweep:
        """Create or replace a sweep definition for the given workflow."""
        ticker_list = self._normalize_ticker_list(
            self.get_tracked_tickers_by_min_rating(min_rating=min_rating)
        )
        total_batches = (len(ticker_list) + batch_size - 1) // batch_size if ticker_list else 0

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO batch_schedule (
                workflow_type,
                ticker_list,
                batch_index,
                total_batches,
                sweep_started_at,
                last_batch_at,
                last_batch_status,
                consecutive_failures,
                sweep_completed_at
            )
            VALUES (?, ?, 0, ?, datetime('now'), NULL, NULL, 0, NULL)
            ON CONFLICT(workflow_type) DO UPDATE SET
                ticker_list = excluded.ticker_list,
                batch_index = 0,
                total_batches = excluded.total_batches,
                sweep_started_at = datetime('now'),
                last_batch_at = NULL,
                last_batch_status = NULL,
                consecutive_failures = 0,
                sweep_completed_at = NULL
            """,
            (workflow_type, json.dumps(ticker_list), total_batches),
        )

        conn.commit()
        conn.close()

        return BatchSweep(
            workflow_type=workflow_type,
            ticker_list=ticker_list,
            batch_index=0,
            total_batches=total_batches,
            batch_size=batch_size,
            sweep_started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    def get_or_start_sweep(self, workflow_type: str, min_rating: float, stale_days: int) -> BatchSweep:
        """Load current sweep state or start a new one if complete/missing/stale."""
        batch_size = max(1, TRACKED_BATCH_SIZE)

        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT workflow_type, ticker_list, batch_index, total_batches,
                     sweep_started_at, last_batch_at, last_batch_status,
                     consecutive_failures, sweep_completed_at
            FROM batch_schedule
            WHERE workflow_type = ?
            """,
            (workflow_type,),
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return self._start_new_sweep(
                workflow_type=workflow_type,
                min_rating=min_rating,
                batch_size=batch_size,
            )

        try:
            ticker_list = self._normalize_ticker_list(json.loads(row["ticker_list"] or "[]"))
        except Exception:
            ticker_list = []

        batch_index = max(0, int(row["batch_index"] or 0))
        total_batches = int(row["total_batches"] or 0)
        sweep_completed_at = row["sweep_completed_at"]
        sweep_started_at = row["sweep_started_at"]

        should_refresh = False

        if sweep_completed_at:
            should_refresh = True
        elif batch_index >= len(ticker_list):
            should_refresh = True
        elif stale_days > 0:
            started_dt = self._parse_sqlite_timestamp(sweep_started_at)
            if started_dt and datetime.now() - started_dt >= timedelta(days=stale_days):
                should_refresh = True

        if should_refresh:
            return self._start_new_sweep(
                workflow_type=workflow_type,
                min_rating=min_rating,
                batch_size=batch_size,
            )

        if total_batches <= 0:
            total_batches = (len(ticker_list) + batch_size - 1) // batch_size if ticker_list else 0

        return BatchSweep(
            workflow_type=workflow_type,
            ticker_list=ticker_list,
            batch_index=batch_index,
            total_batches=total_batches,
            batch_size=batch_size,
            sweep_started_at=sweep_started_at,
            last_batch_at=row["last_batch_at"],
            last_batch_status=row["last_batch_status"],
            sweep_completed_at=sweep_completed_at,
        )

    def advance_sweep(
        self,
        workflow_type: str,
        processed_tickers: List[str],
        status: str = "COMPLETED",
    ) -> None:
        """Advance sweep cursor by processed ticker count or mark batch failure."""
        normalized_status = (status or "COMPLETED").strip().upper()
        if normalized_status not in {"COMPLETED", "FAILED"}:
            normalized_status = "COMPLETED"

        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT ticker_list, batch_index, consecutive_failures
            FROM batch_schedule
            WHERE workflow_type = ?
            """,
            (workflow_type,),
        )
        row = cursor.fetchone()

        if not row:
            conn.close()
            return

        try:
            ticker_list = self._normalize_ticker_list(json.loads(row["ticker_list"] or "[]"))
        except Exception:
            ticker_list = []

        cursor_position = max(0, int(row["batch_index"] or 0))
        consecutive_failures = max(0, int(row["consecutive_failures"] or 0))

        if normalized_status == "COMPLETED":
            cursor_position += len(processed_tickers or [])
            consecutive_failures = 0
        elif normalized_status == "FAILED":
            consecutive_failures += 1

        total_tickers = len(ticker_list)

        if normalized_status == "FAILED" and consecutive_failures >= 3:
            skip_size = max(1, TRACKED_BATCH_SIZE)
            cursor_position += skip_size
            normalized_status = "FAILED_SKIPPED"
            consecutive_failures = 0

        cursor_position = min(cursor_position, total_tickers)
        batch_size = max(1, TRACKED_BATCH_SIZE)
        total_batches = (total_tickers + batch_size - 1) // batch_size if total_tickers else 0

        sweep_completed_at = None
        if normalized_status in {"COMPLETED", "FAILED_SKIPPED"} and (
            total_tickers == 0 or cursor_position >= total_tickers
        ):
            sweep_completed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute(
            """
            UPDATE batch_schedule
            SET batch_index = ?,
                total_batches = ?,
                last_batch_at = datetime('now'),
                last_batch_status = ?,
                consecutive_failures = ?,
                sweep_completed_at = ?
            WHERE workflow_type = ?
            """,
            (
                cursor_position,
                total_batches,
                normalized_status,
                consecutive_failures,
                sweep_completed_at,
                workflow_type,
            ),
        )

        conn.commit()
        conn.close()

    def log_cse_usage(self, workflow_type: str, queries_count: int) -> None:
        """Log Google CSE usage for the current UTC day."""
        if queries_count <= 0:
            return

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO cse_usage_log (query_date, workflow_type, queries_count)
            VALUES (date('now'), ?, ?)
            """,
            (workflow_type, int(queries_count)),
        )

        conn.commit()
        conn.close()

    def get_cse_calls_today(self) -> int:
        """Return total CSE calls logged for the current UTC day."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT COALESCE(SUM(queries_count), 0)
            FROM cse_usage_log
            WHERE query_date = date('now')
            """
        )

        value = cursor.fetchone()[0]
        conn.close()

        return int(value or 0)
    
    def upsert_recommended_stock_from_input(self, stock_id: int = None) -> int:
        """Upsert recommended_stock table from recent input_stock_recommendation rows.

        Only recommendations within RECOMMENDATION_LOOKBACK_MONTHS of each stock's
        latest analysis_date are considered for aggregation.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # Normalize stock_id early when provided
        normalized_stock_id = None
        if stock_id is not None:
            try:
                normalized_stock_id = int(stock_id)
            except Exception:
                conn.close()
                raise ValueError(f"stock_id must be an integer, got {stock_id!r}")
        
        # Build query to aggregate data from input_stock_recommendation.
        # Keep only recommendations within RECOMMENDATION_LOOKBACK_MONTHS of each stock's newest
        # analysis_date.
        if normalized_stock_id is not None:
            eligible_where_clause = "WHERE stock_id = ? AND IFNULL(is_invalid, 0) = 0 AND rating_id > 0"
            eligible_params = (normalized_stock_id,)
        else:
            eligible_where_clause = "WHERE IFNULL(is_invalid, 0) = 0 AND rating_id > 0"
            eligible_params = ()
        
        lookback_modifier = f"-{RECOMMENDATION_LOOKBACK_MONTHS} months"

        # Get aggregated data for each stock
        query = f"""
            WITH latest_per_stock AS (
                SELECT
                    stock_id,
                    MAX(analysis_date) AS latest_analysis_date
                FROM input_stock_recommendation
                {eligible_where_clause}
                GROUP BY stock_id
            ),
            recent_recommendations AS (
                SELECT isr.*
                FROM input_stock_recommendation isr
                JOIN latest_per_stock lps ON lps.stock_id = isr.stock_id
                WHERE IFNULL(isr.is_invalid, 0) = 0
                  AND isr.rating_id > 0
                  AND date(isr.analysis_date) >= date(lps.latest_analysis_date, ?)
            )
            SELECT
                stock_id,
                AVG(CAST(rating_id AS REAL)) as avg_rating,
                MAX(analysis_date) as last_analysis_date,
                AVG(fair_price) as avg_fair_price,
                AVG(target_price) as avg_target_price,
                AVG(price_growth_forecast_pct) as avg_price_growth_forecast_pct,
                MIN(entry_date) as first_entry_date
            FROM recent_recommendations
            GROUP BY stock_id
        """
        
        cursor.execute(query, eligible_params + (lookback_modifier,))
        aggregated_data = cursor.fetchall()

        # If recalculating one stock and there are no valid input recommendations left,
        # remove stale recommended_stock row for that stock.
        if normalized_stock_id is not None and not aggregated_data:
            cursor.execute(
                "DELETE FROM recommended_stock WHERE stock_id = ?",
                (normalized_stock_id,)
            )
            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()
            return deleted_count
        
        upserted_count = 0
        inserted_count = 0
        
        for row in aggregated_data:
            (stock_id, avg_rating, last_analysis_date, avg_fair_price, 
             avg_target_price, avg_price_growth_forecast_pct, first_entry_date) = row

            effective_fair_price = avg_fair_price if avg_fair_price is not None else avg_target_price
            
            # Check if record exists in recommended_stock
            cursor.execute(
                "SELECT stock_id, entry_date, market_price, market_cap, market_pe, market_date FROM recommended_stock WHERE stock_id = ?",
                (stock_id,)
            )
            existing = cursor.fetchone()
            
            if existing:
                # Update existing record, preserving market data
                _, entry_date, market_price, market_cap, market_pe, market_date = existing
                
                cursor.execute("""
                    UPDATE recommended_stock 
                    SET rating = ?,
                        last_analysis_date = ?,
                        fair_price = ?,
                        target_price = ?,
                        price_growth_forecast_pct = ?
                    WHERE stock_id = ?
                """, (
                    avg_rating,
                    last_analysis_date,
                    effective_fair_price,
                    avg_target_price,
                    avg_price_growth_forecast_pct,
                    stock_id
                ))
            else:
                # Insert new record
                cursor.execute("""
                    INSERT INTO recommended_stock (
                        stock_id, rating, last_analysis_date, fair_price, target_price,
                        price_growth_forecast_pct, market_price, market_cap, market_pe,
                        entry_date, market_date
                    ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, NULL)
                """, (
                    stock_id,
                    avg_rating,
                    last_analysis_date,
                    effective_fair_price,
                    avg_target_price,
                    avg_price_growth_forecast_pct,
                    first_entry_date
                ))

                inserted_count += 1
            
            upserted_count += 1
        
        conn.commit()
        conn.close()
        
        # Note: Caller should call update_market_data_for_recommended_stocks from service layer
        # if market data needs to be refreshed for newly inserted stocks

        return upserted_count
    
    def get_all_recommended_stocks(self) -> List[Dict]:
        """Retrieve all recommended stocks with stock details."""
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                rs.stock_id,
                s.ticker,
                s.exchange,
                s.stock_name,
                rs.rating,
                rs.last_analysis_date,
                rs.fair_price,
                rs.fair_price_dcf,
                rs.target_price,
                rs.price_growth_forecast_pct,
                rs.market_price,
                ROUND(IFNULL(rs.fair_price - rs.market_price, 0)/rs.market_price*100) as price_potential_pct,
                rs.market_cap,
                rs.market_pe,
                rs.entry_date,
                rs.market_date
            FROM recommended_stock rs
            JOIN stock s ON rs.stock_id = s.id
            ORDER BY rs.rating DESC, rs.last_analysis_date DESC
        """)
        
        rows = cursor.fetchall()
        recommended_stocks = [dict(row) for row in rows]
        conn.close()
        
        return recommended_stocks
    
    def delete_stock_recommendation(self, recommendation_id: int) -> None:
        """Delete a stock recommendation by its ID.
        
        Args:
            recommendation_id: The ID of the recommendation to delete
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM input_stock_recommendation WHERE id = ?", (recommendation_id,))
        
        conn.commit()
        conn.close()

    def delete_recommended_stock(self, stock_id: int) -> None:
        """Delete a recommended stock by its stock ID.
        
        Args:
            stock_id: The stock ID of the recommended stock to delete
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM recommended_stock WHERE stock_id = ?", (stock_id,))
        
        conn.commit()
        conn.close()

    def get_stocks_needing_market_data_refresh(self, force: bool = False) -> List[Dict]:
        """Get stocks that need market data refresh based on market_date.
        
        Args:
            force: If True, return all stocks. If False, only return stocks with stale data (>1 day old)
            
        Returns:
            List of dictionaries with stock_id, ticker, exchange, market_date
        """
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if force:
            cursor.execute("""
                SELECT rs.stock_id, s.ticker, s.exchange, rs.market_date
                FROM recommended_stock rs
                JOIN stock s ON rs.stock_id = s.id
            """)
        else:
            # Use cutoff date as 1 day ago
            cutoff_date = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')
            cursor.execute("""
                SELECT rs.stock_id, s.ticker, s.exchange, rs.market_date
                FROM recommended_stock rs
                JOIN stock s ON rs.stock_id = s.id
                WHERE rs.market_date IS NULL OR rs.market_date < ?
            """, (cutoff_date,))
        
        rows = cursor.fetchall()
        stocks = [dict(row) for row in rows]
        conn.close()
        
        return stocks
    
    def update_stock_market_data(self, stock_id: int, market_price: float, market_date: str) -> None:
        """Update market price and market date for a stock.
        
        Args:
            stock_id: The stock ID to update
            market_price: The current market price
            market_date: The date of the market price (YYYY-MM-DD)
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE recommended_stock
            SET market_price = ?,
                market_date = ?
            WHERE stock_id = ?
        """, (market_price, market_date, stock_id))
        
        conn.commit()
        conn.close()
    

    
    def get_input_recommendations_for_stock(self, stock_id: int) -> List[Dict]:
        """Retrieve all input stock recommendations for a specific stock.
        
        Args:
            stock_id: The stock ID to get recommendations for
            
        Returns:
            List of dictionaries containing input stock recommendation data
        """
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Normalize input types to avoid SQLite datatype mismatches
        try:
            stock_id = int(stock_id)
        except Exception:
            raise ValueError(f"stock_id must be an integer, got {stock_id!r}")

        cursor.execute("""
            SELECT 
                isr.id,
                rsr.name AS rating,
                isr.analysis_date,
                isr.currency_code,
                isr.price,
                isr.fair_price,
                isr.target_price,
                isr.price_growth_forecast_pct,
                isr.pe,
                isr.recommendation_text,
                w.url AS webpage_url,
                w.id AS webpage_id
            FROM input_stock_recommendation isr
            JOIN ref_stock_rating rsr ON isr.rating_id = rsr.id
            LEFT JOIN webpage w ON isr.webpage_id = w.id
            WHERE isr.stock_id = ? AND IFNULL(isr.is_invalid, 0) = 0
            ORDER BY isr.analysis_date DESC
        """, (stock_id,))
        
        rows = cursor.fetchall()
        recommendations = [dict(row) for row in rows]
        conn.close()
        
        return recommendations
    
    def get_input_recommendations_summary_for_stock(self, stock_id: int) -> Dict:
        """Get summary statistics for input stock recommendations for a specific stock.
        
        Args:
            stock_id: The stock ID to get summary for
            
        Returns:
            Dictionary with total_count and average_rating
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # Normalize input types to avoid SQLite datatype mismatches
        try:
            stock_id = int(stock_id)
        except Exception:
            raise ValueError(f"stock_id must be an integer, got {stock_id!r}")
                    
        cursor.execute("""
            SELECT 
                COUNT(*) as total_count,
                AVG(CAST(rating_id AS REAL)) as avg_rating
            FROM input_stock_recommendation
            WHERE stock_id = ? AND IFNULL(is_invalid, 0) = 0
        """, (stock_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {
                'total_count': result[0],
                'average_rating': result[1]
            }
        else:
            return {
                'total_count': 0,
                'average_rating': None
            }
    
    def add_to_favorites(self, stock_id: int, price_on_entry_date: float = None) -> bool:
        """Add a stock to favorites.
        
        Args:
            stock_id: The stock ID to add to favorites
            price_on_entry_date: Optional price to record. If None, will use market_price from recommended_stock
            
        Returns:
            True if stock was added, False if already in favorites
            
        Raises:
            ValueError: If price_on_entry_date cannot be determined
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # Normalize input types to avoid SQLite datatype mismatches
        try:
            stock_id = int(stock_id)
        except Exception:
            raise ValueError(f"stock_id must be an integer, got {stock_id!r}")
        
        # Check if stock is already in favorites
        cursor.execute("SELECT stock_id FROM favorite_stock WHERE stock_id = ?", (stock_id,))
        if cursor.fetchone():
            conn.close()
            return False
        
        # If price not provided, try to get from recommended_stock
        if price_on_entry_date is None:
            cursor.execute("SELECT market_price FROM recommended_stock WHERE stock_id = ?", (stock_id,))
            result = cursor.fetchone()
            if result is not None and result[0] is not None:
                # Ensure numeric type for insertion into DECIMAL column
                value = result[0]
                if isinstance(value, (int, float)):
                    price_on_entry_date = float(value)
                else:
                    # Attempt to coerce from string/Decimal-like
                    try:
                        # Replace commas used as thousand separators, if any
                        if isinstance(value, str):
                            cleaned = value.replace(',', '')
                            price_on_entry_date = float(cleaned)
                        else:
                            price_on_entry_date = float(value)
                    except Exception:
                        price_on_entry_date = None
        
        # Ensure we have a valid price
        if price_on_entry_date is None:
            conn.close()
            raise ValueError(f"Cannot add stock {stock_id} to favorites: no price available. "
                           "Please ensure the stock has market_price data in recommended_stock table.")
        
        # Insert into favorites
        cursor.execute("""
            INSERT INTO favorite_stock (stock_id, entry_date, price_on_entry_date)
            SELECT stock_id, market_date, market_price 
            FROM recommended_stock WHERE stock_id = ?
        """, (stock_id,))
        
        conn.commit()
        conn.close()
        return True
    
    def remove_from_favorites(self, stock_id: int) -> bool:
        """Remove a stock from favorites.
        
        Args:
            stock_id: The stock ID to remove from favorites
            
        Returns:
            True if stock was removed, False if not in favorites
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Normalize input types to avoid SQLite datatype mismatches
        try:
            stock_id = int(stock_id)
        except Exception:
            raise ValueError(f"stock_id must be an integer, got {stock_id!r}")

        cursor.execute("DELETE FROM favorite_stock WHERE stock_id = ?", (stock_id,))
        rows_deleted = cursor.rowcount
        
        conn.commit()
        conn.close()
        return rows_deleted > 0
    
    def update_fair_price_dcf(self, stock_id: int, fair_price_dcf: float) -> bool:
        """Update the fair_price_dcf column for a recommended stock.
        
        Args:
            stock_id: The stock ID to update
            fair_price_dcf: The fair price from DCF valuation
            
        Returns:
            True if stock was updated, False if stock is not in recommended_stock
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Normalize input types to avoid SQLite datatype mismatches
        try:
            stock_id = int(stock_id)
            fair_price_dcf = float(fair_price_dcf)
        except Exception as e:
            raise ValueError(f"Invalid input types: {e}")

        # Update recommended_stock table
        cursor.execute(
            "UPDATE recommended_stock SET fair_price_dcf = ? WHERE stock_id = ?",
            (fair_price_dcf, stock_id)
        )
        rows_updated = cursor.rowcount
        
        # If stock doesn't exist in recommended_stock, create an entry
        if rows_updated == 0:
            # Check if stock exists in recommended_stock
            cursor.execute("SELECT stock_id FROM recommended_stock WHERE stock_id = ?", (stock_id,))
            if not cursor.fetchone():
                # Create a minimal entry in recommended_stock
                cursor.execute("""
                    INSERT INTO recommended_stock (stock_id, fair_price_dcf)
                    VALUES (?, ?)
                """, (stock_id, fair_price_dcf))
                rows_updated = cursor.rowcount
        
        conn.commit()
        conn.close()
        return rows_updated > 0
    
    def get_all_favorite_stocks(self) -> List[Dict]:
        """Retrieve all favorite stocks with stock details.
        
        Returns:
            List of dictionaries containing favorite stock data joined with stock details.
        """
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                fs.stock_id,
                s.ticker,
                s.exchange,
                s.stock_name,
                fs.entry_date,
                fs.price_on_entry_date,
                rs.fair_price,
                rs.fair_price_dcf,
                rs.market_price,
                rs.market_date,
                ROUND((rs.market_price - fs.price_on_entry_date) / fs.price_on_entry_date * 100, 2) as gain_loss_pct
            FROM favorite_stock fs
            JOIN stock s ON fs.stock_id = s.id
            LEFT JOIN recommended_stock rs ON fs.stock_id = rs.stock_id
            ORDER BY fs.entry_date DESC
        """)
        
        rows = cursor.fetchall()
        favorite_stocks = [dict(row) for row in rows]
        conn.close()
        
        return favorite_stocks
    
    def get_favorite_stock_ids(self) -> List[int]:
        """Get list of stock IDs that are in favorites.
        
        Returns:
            List of stock IDs
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT stock_id FROM favorite_stock")
        stock_ids = [row[0] for row in cursor.fetchall()]
        
        conn.close()
        return stock_ids
    
    def is_favorite(self, stock_id: int) -> bool:
        """Check if a stock is in favorites.
        
        Args:
            stock_id: The stock ID to check
            
        Returns:
            True if stock is in favorites, False otherwise
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT stock_id FROM favorite_stock WHERE stock_id = ?", (stock_id,))
        result = cursor.fetchone()
        
        conn.close()
        return result is not None

    # Process tracking methods

    def get_batch_schedule_status(self, workflow_type: str) -> Dict:
        """Get persisted tracked-batch sweep status for a workflow type.

        Args:
            workflow_type: Workflow key in batch_schedule (for example, tracked_stock)

        Returns:
            Dictionary with batch schedule row or None if not found
        """
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT workflow_type, batch_index, total_batches,
                   sweep_started_at, last_batch_at, last_batch_status,
                   consecutive_failures, sweep_completed_at
            FROM batch_schedule
            WHERE workflow_type = ?
            """,
            (workflow_type,),
        )

        row = cursor.fetchone()
        conn.close()

        if row:
            return dict(row)
        return None
    
    def start_process(self, process_name: str) -> None:
        """Mark a process as started by upserting with current timestamp and NULL end_timestamp.
        
        Args:
            process_name: Name of the process to track
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO process (process_name, start_timestamp, end_timestamp, progress_pct, status, message)
            VALUES (?, datetime('now'), NULL, 0, 'STARTED', NULL)
            ON CONFLICT(process_name) DO UPDATE SET
                start_timestamp = datetime('now'),
                end_timestamp = NULL,
                progress_pct = 0,
                status = 'STARTED',
                message = NULL
        """, (process_name,))
        
        conn.commit()
        conn.close()
        logger.info(f"Process '{process_name}' started")
    
    def end_process(self, process_name: str, status: str = 'COMPLETED', message: str | None = None) -> None:
        """Mark a process as completed or failed by setting end_timestamp to current time.

        Args:
            process_name: Name of the process to mark as complete
            status: Status to set (COMPLETED or FAILED)
            message: Optional short summary of what the job did
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE process
            SET end_timestamp = datetime('now'), progress_pct = 100, status = ?, message = ?
            WHERE process_name = ?
        """, (status, message, process_name))

        conn.commit()
        conn.close()
        logger.info(f"Process '{process_name}' ended with status {status}")

    def update_process_progress(self, process_name: str, progress_pct: int) -> None:
        """Update the progress percentage for a running process.
        
        Args:
            process_name: Name of the process
            progress_pct: Progress percentage (0-100)
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE process 
            SET progress_pct = ?
            WHERE process_name = ?
        """, (progress_pct, process_name))
        
        conn.commit()
        conn.close()

    def touch_process_heartbeat(self, process_name: str, status: str = 'HEARTBEAT') -> None:
        """Persist a liveness heartbeat timestamp for a long-running process.

        Args:
            process_name: Name of the process to track
            status: Stored status label for the heartbeat row
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO process (process_name, start_timestamp, end_timestamp, progress_pct, status)
            VALUES (?, datetime('now'), datetime('now'), 100, ?)
            ON CONFLICT(process_name) DO UPDATE SET
                start_timestamp = datetime('now'),
                end_timestamp = datetime('now'),
                progress_pct = 100,
                status = excluded.status
        """, (process_name, status))

        conn.commit()
        conn.close()
    
    def get_process_status(self, process_name: str) -> Dict:
        """Get the status of a process.
        
        Args:
            process_name: Name of the process
            
        Returns:
            Dictionary with process status info or None if not found
        """
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT process_name, start_timestamp, end_timestamp, progress_pct, status, message
            FROM process
            WHERE process_name = ?
        """, (process_name,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    
    def is_process_running(self, process_name: str) -> bool:
        """Check if a process is currently running (status is STARTED).
        
        Args:
            process_name: Name of the process
            
        Returns:
            True if process is running, False otherwise
        """
        status = self.get_process_status(process_name)
        if status:
            return status['status'] == 'STARTED'
        return False

    def add_stock_note(self, stock_id: int, note: str, entry_date: str = None) -> int:
        """Add a new note for a specific stock."""
        if entry_date is None:
            entry_date = date.today().isoformat()

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO stock_note (stock_id, note, entry_date)
            VALUES (?, ?, ?)
            """,
            (stock_id, note, entry_date)
        )

        conn.commit()
        note_id = cursor.lastrowid
        conn.close()
        return note_id

    def mark_recommendation_invalid(
        self,
        recommendation_id: int,
        feedback_text: str,
        invalid_fields: List[str]
    ) -> int:
        """Mark an input recommendation as invalid and store user feedback.

        Returns:
            stock_id for the invalidated recommendation
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            recommendation_id = int(recommendation_id)
        except Exception:
            conn.close()
            raise ValueError(f"recommendation_id must be an integer, got {recommendation_id!r}")

        cursor.execute(
            "SELECT stock_id, is_invalid FROM input_stock_recommendation WHERE id = ?",
            (recommendation_id,)
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            raise ValueError(f"Recommendation {recommendation_id} not found")

        stock_id, is_invalid = row
        if is_invalid == 1:
            conn.close()
            return stock_id

        cursor.execute(
            "UPDATE input_stock_recommendation SET is_invalid = 1 WHERE id = ?",
            (recommendation_id,)
        )

        cursor.execute(
            """
            INSERT INTO recommendation_feedback (
                recommendation_id, stock_id, feedback_text
            ) VALUES (?, ?, ?)
            """,
            (recommendation_id, stock_id, feedback_text)
        )

        feedback_id = cursor.lastrowid

        for field_name in set(invalid_fields or []):
            cursor.execute(
                """
                INSERT INTO recommendation_feedback_invalid_fields (
                    feedback_id, field_name
                ) VALUES (?, ?)
                """,
                (feedback_id, field_name)
            )

        conn.commit()
        conn.close()
        return stock_id

    def get_stock_notes(self, stock_id: int) -> List[Dict]:
        """Retrieve all notes for a specific stock."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, note, entry_date
            FROM stock_note
            WHERE stock_id = ?
            ORDER BY entry_date DESC
            """,
            (stock_id,)
        )

        notes = [
            {"id": row[0], "note": row[1], "entry_date": row[2]}
            for row in cursor.fetchall()
        ]

        conn.close()
        return notes

