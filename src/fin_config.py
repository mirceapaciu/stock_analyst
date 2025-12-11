"""
Financial Configuration Constants for DCF Valuation
"""

# Risk-Free Rate (10-year Treasury)
RISK_FREE_RATE = 0.045  # 4.5%

# Market Risk Premium
MARKET_RISK_PREMIUM = 0.04  # 4.0% (reduced for large-cap tech)

# Cost of Debt
COST_OF_DEBT = 0.04  # 4.0% (approximate corporate bond rate)

# Tax Rate
CORPORATE_TAX_RATE = 0.21  # 21% (US corporate tax rate)

# Terminal Growth Rate
DEFAULT_TERMINAL_GROWTH_RATE = 0.025

# WACC Bounds
MIN_WACC = 0.05  # 5%
MAX_WACC = 0.15  # 15%

# Default WACC (fallback)
DEFAULT_WACC = 0.10  # 10%

# Growth Rate Bounds
MIN_HISTORICAL_GROWTH = -0.20  # -20%
MAX_HISTORICAL_GROWTH = 0.50   # 50%
DEFAULT_MIN_GROWTH = 0.05      # 5% (default minimum growth rate)

# Minimum Growth Rates for Projections
MIN_STARTING_GROWTH = -0.10  # -10%
MAX_STARTING_GROWTH = 0.15   # 15%
MIN_BASELINE_GROWTH = 0.03   # 3%
FALLBACK_BASELINE_GROWTH = 0.05  # 5%
MIN_PROJECTED_GROWTH = 0.02  # 2%

# Growth Decline Factors
GROWTH_DECLINE_FACTOR = 0.90  # Growth declines by 10% per year

# Default Beta
DEFAULT_BETA = 1.0

# Conservative Valuation Factor
DEFAULT_CONSERVATIVE_FACTOR = 0.90  # 90%

# Default Forecast Years
DEFAULT_FORECAST_YEARS = 5

# Default Historical Growth Base Rate
DEFAULT_HISTORICAL_BASE_RATE = 0.07  # 7%

# Projection Method Options
PROJECTION_METHODS = ['declining', 'constant', 'cagr']

# Historical Years to Analyze
DEFAULT_HISTORICAL_YEARS = 5
FCF_HISTORICAL_WINDOW = 4  # Last 4 years for estimation
