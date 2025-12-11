"""Financial Modeling Prep API client for stock ticker validation."""

import json
import urllib.parse
import urllib.request
import requests
import logging
from typing import List, Dict, Optional
from config import FMP_API_KEY

logger = logging.getLogger(__name__)


class FMPClient:
    """Client for Financial Modeling Prep API."""
    
    BASE_URL = "https://financialmodelingprep.com/api/v3"
    
    def __init__(self, api_key: str = FMP_API_KEY):
        """Initialize the FMP client.
        
        Args:
            api_key: Financial Modeling Prep API key
        """
        self.api_key = api_key
    
    def search_symbol(self, symbol: str) -> List[Dict]:
        """Search for a stock symbol.
        
        Args:
            symbol: Stock ticker symbol to search for
            
        Returns:
            List of matching symbols with metadata

        Example response:
            [
                {
                    "symbol": "AAPL",
                    "name": "Apple Inc.",
                    "currency": "USD",
                    "exchangeFullName": "NASDAQ Global Select",
                    "exchange": "NASDAQ"
                },
                {
                    "symbol": "AAPL.L",
                    "name": "LS 1x Apple Tracker ETC",
                    "currency": "GBp",
                    "exchangeFullName": "London Stock Exchange",
                    "exchange": "LSE"
                }
            ]            
        """
        params = {
            "query": symbol,
            "apikey": self.api_key
        }
        
        url = "https://financialmodelingprep.com/stable/search-symbol?" + urllib.parse.urlencode(params)
        
        with urllib.request.urlopen(url, timeout=10) as resp:
            if resp.status != 200:
                raise RuntimeError(f"FMP request failed: {resp.status} {resp.reason}")
            return json.load(resp)
    
    def get_quote(self, symbol: str) -> Optional[Dict]:
        """Get current quote for a stock symbol.
        
        Args:
            symbol: Stock ticker symbol
            
        Returns:
            Dictionary with quote data or None if not found
        """
        url = f"{self.BASE_URL}/quote/{symbol}"
        params = {"apikey": self.api_key}
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data[0] if data else None
        except (requests.RequestException, IndexError, KeyError) as e:
            logger.error(f"Error getting quote for {symbol}: {e}")
            return None
