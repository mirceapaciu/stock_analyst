"""Streamlit page for DCF valuation calculator."""

import streamlit as st
import sys
import pandas as pd
from pathlib import Path

# Add src directory to Python path
# Resolve __file__ first to handle any .. components, then go up to src/
src_path = Path(__file__).resolve().parent.parent.parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

# Check authentication first
from utils.auth import check_password
if not check_password():
    st.stop()  # Stop execution if not authenticated

from services.valuation import get_dcf_valuation, print_dcf_analysis, get_recomendation_from_upside_potential
from services.risk import get_risk_evaluation
from services.financial import get_or_create_stock_info
from services.currency import get_financial_currency
from fin_config import DEFAULT_TERMINAL_GROWTH_RATE, MIN_WACC, MAX_WACC, DEFAULT_WACC

st.set_page_config(page_title="DCF Valuation", page_icon="💰", layout="wide")

st.title("💰 DCF Valuation Calculator")

st.markdown("""
Calculate the fair price of any stock using Discounted Cash Flow (DCF) analysis.
This analysis uses historical financial data and projects future free cash flows to estimate what the stock is truly worth.
""")

# Checkbox for custom discount rate (outside form so it can trigger rerun)
use_custom_discount = st.checkbox(
    "Use Custom Discount Rate",
    value=False,
    help="By default, WACC is calculated automatically. Check to use a custom rate."
)

# Input form
with st.form("dcf_form"):
    col1, col2 = st.columns(2)
    
    with col1:
        ticker = st.text_input(
            "Stock Ticker",
            value="NVO",
            help="Enter the stock ticker symbol (e.g., AAPL, MSFT, GOOGL)"
        ).upper()
        
        forecast_years = st.slider(
            "Forecast Period (Years)",
            min_value=3,
            max_value=10,
            value=5,
            help="Number of years to forecast free cash flows"
        )
        
        terminal_growth_rate_pct = st.slider(
            "Terminal Growth Rate",
            min_value=1.0,
            max_value=5.0,
            value=DEFAULT_TERMINAL_GROWTH_RATE * 100,
            step=0.5,
            format="%.1f%%",
            help="The perpetual growth rate used to calculate the company's value beyond the forecast period. Typically 2-4% (roughly equal to long-term GDP growth or inflation). This assumes the company will grow at this rate forever."
        )
        terminal_growth_rate = terminal_growth_rate_pct / 100
    
    with col2:
        discount_rate = None
        if use_custom_discount:
            discount_rate = st.slider(
                "Discount Rate (WACC)",
                min_value=MIN_WACC*100,
                max_value=MAX_WACC*100,
                value=DEFAULT_WACC*100,
                step=1.,
                format="%.0f%%",
                help="Weighted Average Cost of Capital. WACC is the average rate a company pays to finance its assets, weighted by the proportion of equity and debt. It’s the discount rate used in DCF valuation."
            )
            discount_rate = discount_rate / 100
        else:
            st.info("WACC will be calculated automatically based on company financials")
        
        conservative_factor = st.slider(
            "Conservative Factor",
            min_value=0.70,
            max_value=1.00,
            value=0.90,
            step=0.05,
            format="%.2f",
            help="Apply a margin of safety to the valuation"
        )
    
    submit = st.form_submit_button("Calculate DCF", width='stretch', type="primary")

# Calculate and display results
if submit:
    if not ticker:
        st.error("Please enter a stock ticker symbol")
    else:
        with st.spinner(f"Calculating DCF valuation for {ticker}..."):
            try:
                result = get_dcf_valuation(
                    ticker=ticker,
                    forecast_years=forecast_years,
                    terminal_growth_rate=terminal_growth_rate,
                    discount_rate=discount_rate,
                    conservative_factor=conservative_factor
                )
                
                # Display key metrics
                st.success(f"✅ Successfully calculated DCF valuation for {ticker}")
                
                # Get currencies - trading currency for current price, financial currency for valuation
                stock_info = get_or_create_stock_info(ticker)
                trading_currency = stock_info.get('currency') or 'n/a'  # Trading currency for current price
                financial_currency = stock_info.get('financialCurrency') or 'n/a'  # Financial currency for valuation
                
                st.divider()
                
                # Key results
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.metric(
                        "Current Price",
                        f"{trading_currency} {result.get('current_price', 0):.2f}"
                    )
                
                with col2:
                    st.metric(
                        "Fair Price",
                        f"{trading_currency} {result.get('conservative_fair_value', 0):.2f}"
                    )
                
                with col3:
                    upside = result.get('conservative_upside_pct', 0)
                    st.metric(
                        "Upside Potential",
                        f"{upside:.1f}%",
                        delta=f"{upside:.1f}%",
                        delta_color="normal" if upside > 0 else "inverse"
                    )
                
                with col4:
                    recommendation = recommendation = get_recomendation_from_upside_potential(result['conservative_upside_pct'])
                    # Color-code recommendation
                    if recommendation == 'STRONG BUY':
                        st.success(f"**{recommendation}**")
                    elif recommendation == 'BUY':
                        st.info(f"**{recommendation}**")
                    elif recommendation == 'HOLD':
                        st.warning(f"**{recommendation}**")
                    else:
                        st.error(f"**{recommendation}**")
                
                st.divider()
                
                # Risk evaluation
                with st.expander("⚠️ Risk Evaluation", expanded=False):
                    try:
                        risk_result = get_risk_evaluation(ticker)
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Risk Score", f"{risk_result.get('risk_score', 0):.0f}")
                        with col2:
                            st.metric("Risk Label", risk_result.get('risk_label', 'N/A'))
                        with col3:
                            st.metric("Benchmark", risk_result.get('benchmark', 'N/A'))

                        sub_scores = risk_result.get("sub_scores") or {}
                        metrics = risk_result.get("metrics") or {}
                        valuation = risk_result.get("valuation_sensitivity") or {}

                        st.markdown("**Sub-scores**")
                        st.dataframe(
                            pd.DataFrame([
                                {
                                    "Market": sub_scores.get("market"),
                                    "Downside": sub_scores.get("downside"),
                                    "Drawdown": sub_scores.get("drawdown"),
                                    "Leverage": sub_scores.get("leverage"),
                                    "Stability": sub_scores.get("stability"),
                                    "Valuation": sub_scores.get("valuation"),
                                }
                            ]),
                            width='stretch',
                            hide_index=True,
                        )

                        st.markdown("**Key metrics**")
                        st.dataframe(
                            pd.DataFrame([
                                {
                                    "Volatility": metrics.get("volatility"),
                                    "Downside Deviation": metrics.get("downside_deviation"),
                                    "VaR (95%)": metrics.get("var_95"),
                                    "CVaR (95%)": metrics.get("cvar_95"),
                                    "Beta": metrics.get("beta"),
                                    "Max Drawdown": metrics.get("max_drawdown"),
                                }
                            ]),
                            width='stretch',
                            hide_index=True,
                        )

                        if valuation and valuation.get("percent_below_market") is not None:
                            st.markdown(
                                f"**Valuation sensitivity:** {valuation['percent_below_market']:.0%} of grid below market price"
                            )
                    except Exception as risk_error:
                        st.warning(f"Risk evaluation unavailable: {risk_error}")

                st.divider()

                # Detailed analysis
                with st.expander("📊 Detailed Analysis", expanded=True):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.subheader("Valuation Inputs")
                        st.write(f"**Discount Rate (WACC):** {result.get('in_discount_rate', 0)*100:.2f}%")
                        st.write(f"**Terminal Growth Rate:** {result.get('in_terminal_growth_rate', 0)*100:.2f}%")
                        st.write(f"**Forecast Period:** {result.get('in_forecast_years', 0)} years")
                        st.write(f"**Conservative Factor:** {result.get('in_conservative_factor', 0)*100:.0f}%")
                        
                        fcf_growth = result.get('in_fcf_growth_rates', [])
                        if fcf_growth:
                            st.write(f"**FCF Growth Rates:**")
                            for i, rate in enumerate(fcf_growth, 1):
                                st.write(f"  Year {i}: {rate*100:.1f}%")
                    
                    with col2:
                        st.subheader("Valuation Components")
                        pv_fcfs = result.get('pv_fcfs', [])
                        pv_projected_fcf = sum(pv_fcfs) if pv_fcfs else 0
                        st.write(f"**PV of Projected FCF:** {financial_currency} {pv_projected_fcf:,.0f}")
                        st.write(f"**PV of Terminal Value:** {financial_currency} {result.get('pv_terminal_value', 0):,.0f}")
                        st.write(f"**Enterprise Value:** {financial_currency} {result.get('total_enterprise_value', 0):,.0f}")
                        st.write(f"**Equity Value:** {financial_currency} {result.get('equity_value', 0):,.0f}")
                        st.write(f"**Shares Outstanding:** {result.get('shares_outstanding', 0):,.0f}")
                
                # Historical FCF Growth Analysis
                fcf_growth_notes = result.get('fcf_growth_notes', [])
                if fcf_growth_notes:
                    with st.expander("📈 Historical FCF Growth Analysis", expanded=False):
                        st.markdown("### Free Cash Flow Growth Analysis")
                        st.markdown("This section shows how the projected growth rates were derived from historical data.")
                        st.text("\n".join(fcf_growth_notes))
                
                # Cash flow projections
                with st.expander("💵 Cash Flow Projections"):
                    import pandas as pd
                    
                    projected_fcfs = result.get('projected_fcfs', [])
                    pv_fcfs = result.get('pv_fcfs', [])
                    
                    if projected_fcfs and pv_fcfs:
                        df = pd.DataFrame({
                            'Year': list(range(1, len(projected_fcfs) + 1)),
                            'Projected FCF': [f"{financial_currency} {x:,.0f}" for x in projected_fcfs],
                            'Present Value': [f"{financial_currency} {x:,.0f}" for x in pv_fcfs]
                        })
                        st.dataframe(df, width='stretch', hide_index=True)
                
                # Text analysis
                with st.expander("📝 Text Analysis"):
                    import io
                    from contextlib import redirect_stdout
                    
                    # Capture print output to string
                    f = io.StringIO()
                    with redirect_stdout(f):
                        print_dcf_analysis(result)
                    analysis_text = f.getvalue()
                    st.code(analysis_text, language=None)
                
            except Exception as e:
                st.error(f"Error calculating DCF valuation: {e}")
                st.exception(e)

# Information section
with st.sidebar:
    st.header("How it works")
    st.markdown("""
    **DCF Valuation Steps:**
    
    1. **Get Financial Data** - Fetches historical financials from Yahoo Finance
    2. **Calculate WACC** - Determines appropriate discount rate
    3. **Project Cash Flows** - Forecasts future free cash flows
    4. **Calculate Terminal Value** - Estimates value beyond forecast period
    5. **Discount to Present** - Applies discount rate to all cash flows
    6. **Determine Per-Share Value** - Converts to stock price
    
    **Interpretation:**
    - **Strong Buy**: Price < 70% of fair price
    - **Buy**: Price < 90% of fair price
    - **Hold**: Price within 90-110% of fair price
    - **Sell**: Price > fair price
    """)
    
    with st.expander("📚 Understanding Terminal Growth Rate"):
        st.markdown("""
        **What is Terminal Growth Rate?**
        
        The Terminal Growth Rate is the perpetual growth rate used to estimate a company's value beyond the explicit forecast period (typically 5-10 years).
        
        **Why is it needed?**
        
        DCF models can't forecast cash flows forever, so we use a simplified approach:
        - **Forecast Period**: Detailed year-by-year projections (e.g., 5 years)
        - **Terminal Value**: Assumes the company grows at a constant rate forever after the forecast period
        
        **How to choose the rate?**
        
        - **2-3%**: Conservative, assumes growth slows to match long-term GDP growth
        - **3-4%**: Moderate, accounts for inflation and modest real growth
        - **4-5%**: Optimistic, assumes company maintains competitive advantages
        
        **Important Notes:**
        
        - The terminal growth rate should be **less than** the discount rate (WACC), otherwise the model becomes invalid
        - Typically set between 2-4% (roughly equal to long-term GDP growth or inflation)
        - Higher rates significantly increase valuation, so be conservative
        - This rate assumes the company will grow at this rate **forever**, which is a simplifying assumption
        
        **Example:**
        
        If you forecast 5 years of cash flows, the terminal growth rate estimates what happens in year 6, 7, 8... and beyond, assuming the company grows at this constant rate indefinitely.
        """)
