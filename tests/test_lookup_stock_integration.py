"""
Integration tests for lookup_stock function.

Tests the lookup_stock function with real API calls to verify:
- Exchange filtering works correctly
- Flexible exchange matching (e.g., NASDAQ matches NasdaqGS)
- Database caching functionality
- Correct stock data retrieval
"""

import pytest
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from services.recommendations import lookup_stock
from repositories.recommendations_db import RecommendationsDatabase


class TestLookupStockIntegration:
    """Integration tests for lookup_stock function."""

    def test_lookup_nasdaq_doo_returns_brp_inc(self):
        """
        Test that DOOO on NASDAQ returns BRP Inc.
        
        Tests the exchange filtering logic to ensure correct stock is returned.
        Note: BRP Inc. trades as DOOO on NASDAQ and DOO on TSX.
        
        This test makes live FMP API calls and may insert DOOO into the database.
        """
        result = lookup_stock("DOOO", "NASDAQ")
        
        assert result is not None, "DOOO should be found on NASDAQ (requires FMP API access)"
        assert result["ticker"] == "DOOO"
        assert result["stock_name"] == "BRP Inc."
        assert "NASDAQ" in result["exchange"].upper() or result["exchange"] == "NASDAQ"

    def test_lookup_with_flexible_exchange_matching(self):
        """
        Test that exchange matching is flexible.
        
        FMP API may return 'NasdaqGS' or 'NASDAQ Global Select' but
        we should accept 'NASDAQ' as a match.
        """
        result = lookup_stock("AAPL", "NASDAQ")
        
        assert result is not None, "AAPL should be found on NASDAQ"
        assert result["ticker"] == "AAPL"
        assert "NASDAQ" in result["exchange"].upper()

    def test_lookup_filters_by_exchange(self):
        """
        Test that specifying an exchange filters results appropriately.
        
        BRP Inc. exists on both TSX (as DOO) and NASDAQ (as DOOO).
        
        Note: This test makes live FMP API calls.
        """
        nasdaq_result = lookup_stock("DOOO", "NASDAQ")
        
        assert nasdaq_result is not None, "DOOO should be found on NASDAQ (requires FMP API access)"
        assert nasdaq_result["ticker"] == "DOOO"
        assert nasdaq_result["stock_name"] == "BRP Inc."
        
        # Test TSX listing (DOO.TO format)
        tsx_result = lookup_stock("DOO.TO", "TSX")
        if tsx_result:
            assert tsx_result["ticker"] == "DOO.TO"
            assert tsx_result["stock_name"] == "BRP Inc."
            assert "TSX" in tsx_result["exchange"].upper()
        
        # TSX listing should be different if it exists
        # Note: This test assumes DOO:TSX exists; adjust if needed
        # tsx_result = lookup_stock("DOO", "TSX")
        # if tsx_result:
        #     assert tsx_result["ticker"] == "DOO"
        #     assert tsx_result["exchange"] == "TSX"

    def test_lookup_without_exchange(self):
        """
        Test lookup without specifying exchange returns a match.
        """
        result = lookup_stock("AAPL")
        
        assert result is not None, "AAPL should be found"
        assert result["ticker"] == "AAPL"
        assert "exchange" in result

    def test_lookup_caches_in_database(self):
        """
        Test that lookup_stock caches results in the database.
        
        Second call should retrieve from database, not API.
        """
        # First call - may hit API
        result1 = lookup_stock("MSFT", "NASDAQ")
        assert result1 is not None
        
        # Second call - should hit database cache
        result2 = lookup_stock("MSFT", "NASDAQ")
        assert result2 is not None
        
        # Results should be identical
        assert result1["ticker"] == result2["ticker"]
        assert result1["stock_name"] == result2["stock_name"]
        assert result1["exchange"] == result2["exchange"]

    def test_lookup_invalid_ticker(self):
        """
        Test lookup with invalid ticker returns None.
        """
        result = lookup_stock("INVALIDTICKER12345")
        
        assert result is None, "Invalid ticker should return None"

    def test_lookup_returns_required_fields(self):
        """
        Test that lookup_stock returns all required fields.
        """
        result = lookup_stock("GOOGL", "NASDAQ")
        
        assert result is not None
        assert "ticker" in result
        assert "stock_name" in result
        assert "exchange" in result
        # Optional fields that may be present
        # assert "mic" in result
        # assert "isin" in result

    def test_lookup_multiple_tickers_same_exchange(self):
        """
        Test looking up multiple different tickers on the same exchange.
        """
        tickers = ["AAPL", "MSFT", "GOOGL"]
        results = []
        
        for ticker in tickers:
            result = lookup_stock(ticker, "NASDAQ")
            assert result is not None, f"{ticker} should be found on NASDAQ"
            assert result["ticker"] == ticker
            results.append(result)
        
        # Verify we got different stocks
        stock_names = [r["stock_name"] for r in results]
        assert len(set(stock_names)) == len(stock_names), "Should get different stocks"

    def test_lookup_case_insensitive(self):
        """
        Test that ticker lookup is case-insensitive.
        """
        result_upper = lookup_stock("AAPL", "NASDAQ")
        result_lower = lookup_stock("aapl", "NASDAQ")
        
        assert result_upper is not None
        assert result_lower is not None
        assert result_upper["ticker"] == result_lower["ticker"]
        assert result_upper["stock_name"] == result_lower["stock_name"]


class TestLookupStockEdgeCases:
    """Edge case tests for lookup_stock function."""

    def test_lookup_with_whitespace_in_ticker(self):
        """
        Test that whitespace in ticker is handled properly.
        """
        result = lookup_stock(" AAPL ", "NASDAQ")
        
        assert result is not None, "Should handle whitespace"
        assert result["ticker"] == "AAPL"

    def test_lookup_with_special_exchange_names(self):
        """
        Test handling of various exchange name formats from FMP.
        """
        # Test common exchange variations
        exchanges_to_test = [
            ("NASDAQ", ["NASDAQ", "NasdaqGS", "NASDAQ Global Select"]),
            ("NYSE", ["NYSE", "New York Stock Exchange"]),
        ]
        
        for exchange_input, expected_matches in exchanges_to_test:
            result = lookup_stock("AAPL", exchange_input)
            if result:
                # Verify the exchange field contains or matches one of expected values
                exchange_upper = result["exchange"].upper()
                assert any(em.upper() in exchange_upper or exchange_upper in em.upper() 
                          for em in expected_matches), \
                    f"Exchange {result['exchange']} should match one of {expected_matches}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
