import sys
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from repositories.stocks_db import StockRepository


def _build_stock_info(minority_interest=None, source=None, note=None):
    return {
        "shortName": "Test Corp",
        "longName": "Test Corporation",
        "sector": "Technology",
        "industry": "Software",
        "country": "US",
        "currency": "USD",
        "financialCurrency": "USD",
        "exchange": "NASDAQ",
        "sharesOutstanding": 1000,
        "marketCap": 1000000,
        "currentPrice": 100.0,
        "beta": 1.1,
        "dividendRate": None,
        "dividendYield": None,
        "payoutRatio": None,
        "minorityInterest": minority_interest,
        "minorityInterestSource": source,
        "minorityInterestNote": note,
    }


def test_upsert_and_get_stock_info_include_minority_interest_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_S3_SYNC", "false")
    db_path = tmp_path / "stocks.duckdb"

    with StockRepository(str(db_path)) as repo:
        repo.upsert_stock(
            "TEST",
            _build_stock_info(
                minority_interest=125.0,
                source="stock_info.minorityInterest",
                note="",
            ),
        )

        info = repo.get_stock_info("TEST")

    assert info is not None
    assert info["minorityInterest"] == 125.0
    assert info["minorityInterestSource"] == "stock_info.minorityInterest"
    assert info["minorityInterestNote"] is None


def test_update_minority_interest_updates_existing_stock(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_S3_SYNC", "false")
    db_path = tmp_path / "stocks.duckdb"

    with StockRepository(str(db_path)) as repo:
        repo.upsert_stock("TEST", _build_stock_info())
        repo.update_minority_interest(
            ticker="TEST",
            minority_interest=0.0,
            source="unavailable",
            note="Minority interest data unavailable; adjustment assumed 0.",
        )
        info = repo.get_stock_info("TEST")

    assert info is not None
    assert info["minorityInterest"] == 0.0
    assert info["minorityInterestSource"] == "unavailable"
    assert "assumed 0" in info["minorityInterestNote"]
