"""Main Streamlit application for stock analysis."""

import streamlit as st
import logging
import sys
from pathlib import Path

# Add src to path for imports
# Resolve __file__ first to handle any .. components, then go up to src/
src_path = Path(__file__).resolve().parent.parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from utils.logger import setup_logging
from utils.auth import check_password

setup_logging()

# Check authentication before showing anything
if not check_password():
    st.stop()  # Stop execution if not authenticated

# Page configuration
st.set_page_config(
    page_title="Stock Analysis Platform",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Main page
st.title("📈 Stock Analysis Platform")

# User Guide link/button
col1, col2 = st.columns([3, 1])
with col1:
    st.markdown("""
    Welcome to the Stock Analysis Platform! This application combines:

    1. **Favorite stocks** - Track your favorite stocks and their performance
    2. **Stock Recommendations** - Automated collection and analysis of stock recommendations from web sources
    3. **DCF Valuation** - Discounted Cash Flow valuation calculator for fair price estimation
    """)
with col2:
    # Try to use st.page_link if available (Streamlit 1.28.0+), otherwise use button
    try:
        st.page_link("pages/3_User_Guide.py", label="📖 User Guide", icon="📖")
    except (AttributeError, TypeError):
        # Fallback for older Streamlit versions
        if st.button("📖 User Guide", use_container_width=True):
            st.switch_page("pages/3_User_Guide.py")

st.markdown("""
### Features

- **📊 Recommendations**: Browse stock recommendations collected from various financial websites
- **⭐ Favorites**: Track your favorite stocks and their performance
- **💰 DCF Valuation**: Calculate the fair price using discounted cash flow analysis

### Getting Started

Use the sidebar navigation to explore different sections of the application.

For detailed step-by-step instructions, see the **User Guide** page in the sidebar navigation.

#### Favorite stocks
View your favorite stocks and their performance.

#### Recommendations
View and filter stock recommendations collected from web sources. Each recommendation includes:
- Stock ticker and company name
- Rating (Strong Buy, Buy, Hold, Sell, Strong Sell)
- Fair price estimates
- Target prices
- Analysis date

#### DCF Valuation
Calculate the fair price of any stock using DCF analysis:
- Automatic WACC calculation or custom discount rate
- Customizable forecast period (3-10 years)
- Terminal growth rate settings
- Conservative factor adjustment


### Data Sources

- **Web Recommendations**: Collected via Google Custom Search API and LLM-based extraction
- **Financial Data**: Yahoo Finance via yfinance library
- **Market Data**: Finnhub API for real-time market prices

### Disclaimer

**This application is for educational and informational purposes only.** 

The stock valuations, analyses, and recommendations provided by this application are based on historical data and mathematical models. They should not be considered as financial advice or recommendations to buy, sell, or hold any securities.

**Important considerations:**
- Past performance does not guarantee future results
- Financial models use assumptions that may not reflect actual market conditions
- Stock prices are influenced by many factors beyond fundamental analysis
- Always conduct your own research and consult with qualified financial advisors before making investment decisions

The author and contributors are not liable for any financial losses, damages, or consequences resulting from the use of this application or reliance on its outputs. **Invest at your own risk.**

### Limitations

The initial version is focussing on US stocks for the following reasons:
- Used APIs support only US stocks
- Default financial parameters are set for the US
""")

  
