"""Unit tests for workflow-scoped market data refresh behavior."""

import sys
from pathlib import Path
from types import SimpleNamespace

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from services import recommendations as recommendation_service


class DummyRecommendationsDatabase:
    def __init__(self, stocks_to_update=None, favorite_stock_ids=None):
        self._stocks_to_update = stocks_to_update or []
        self._favorite_stock_ids = favorite_stock_ids or []
        self.updated_rows = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def get_stocks_needing_market_data_refresh(self, force=False):
        return list(self._stocks_to_update)

    def get_favorite_stock_ids(self):
        return list(self._favorite_stock_ids)

    def update_stock_market_data(self, stock_id, market_price, market_date):
        self.updated_rows.append((stock_id, market_price, market_date))


class FakeFinnhubClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.quoted_tickers = []

    def quote(self, ticker):
        self.quoted_tickers.append(ticker)
        return {"c": 123.45}


def test_collect_workflow_recommendation_tickers_from_deduplicated_pages():
    workflow_result = {
        "deduplicated_pages": [
            {
                "stock_recommendations": [
                    {"ticker": "msft"},
                    {"ticker": " AAPL "},
                ]
            },
            {
                "stock_recommendations": [
                    {"ticker": "MSFT"},
                    {"ticker": ""},
                    {},
                ]
            },
        ]
    }

    tickers = recommendation_service.collect_workflow_recommendation_tickers(workflow_result)

    assert tickers == {"MSFT", "AAPL"}


def test_collect_workflow_recommendation_tickers_falls_back_to_scraped_pages():
    workflow_result = {
        "deduplicated_pages": [],
        "scraped_pages": [
            {"stock_recommendations": [{"ticker": "tsla"}]},
            {"stock_recommendations": [{"ticker": "TSLA"}, {"ticker": "nvda"}]},
        ],
    }

    tickers = recommendation_service.collect_workflow_recommendation_tickers(workflow_result)

    assert tickers == {"TSLA", "NVDA"}


def test_update_market_data_scoped_to_workflow_tickers(monkeypatch):
    db = DummyRecommendationsDatabase(
        stocks_to_update=[
            {"stock_id": 1, "ticker": "AAPL", "exchange": "NASDAQ", "market_date": None},
            {"stock_id": 2, "ticker": "MSFT", "exchange": "NASDAQ", "market_date": None},
            {"stock_id": 3, "ticker": "SAP", "exchange": "XETRA", "market_date": None},
        ]
    )

    monkeypatch.setattr(recommendation_service, "FINNHUB_API_KEY", "test-key")
    monkeypatch.setattr(recommendation_service, "RecommendationsDatabase", lambda _db_path: db)
    monkeypatch.setitem(
        sys.modules,
        "finnhub",
        SimpleNamespace(Client=FakeFinnhubClient),
    )

    result = recommendation_service.update_market_data_for_recommended_stocks(
        workflow_tickers=["MSFT", "SAP"]
    )

    assert result == {"updated": 1, "failed": 0, "skipped": 1}
    assert len(db.updated_rows) == 1
    assert db.updated_rows[0][0] == 2


def test_update_market_data_empty_workflow_tickers_updates_nothing(monkeypatch):
    db = DummyRecommendationsDatabase(
        stocks_to_update=[
            {"stock_id": 1, "ticker": "AAPL", "exchange": "NASDAQ", "market_date": None},
        ]
    )

    monkeypatch.setattr(recommendation_service, "FINNHUB_API_KEY", "test-key")
    monkeypatch.setattr(recommendation_service, "RecommendationsDatabase", lambda _db_path: db)
    monkeypatch.setitem(
        sys.modules,
        "finnhub",
        SimpleNamespace(Client=FakeFinnhubClient),
    )

    result = recommendation_service.update_market_data_for_recommended_stocks(workflow_tickers=[])

    assert result == {"updated": 0, "failed": 0, "skipped": 0}
    assert db.updated_rows == []
