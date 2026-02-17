"""Streamlit page for viewing favorite stocks."""

import streamlit as st
import pandas as pd
import sys
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

from repositories.recommendations_db import RecommendationsDatabase
from services.recommendations import update_market_data_for_recommended_stocks
from services.valuation import get_dcf_valuation
from services.risk import get_risk_evaluation
from fin_config import (
    RISK_VOLATILITY_LOW,
    RISK_VOLATILITY_HIGH,
    RISK_DOWNSIDE_DEV_LOW,
    RISK_DOWNSIDE_DEV_HIGH,
    RISK_VAR_LOW,
    RISK_VAR_HIGH,
    RISK_CVAR_LOW,
    RISK_CVAR_HIGH,
    RISK_BETA_LOW,
    RISK_BETA_HIGH,
    RISK_MAX_DRAWDOWN_LOW,
    RISK_MAX_DRAWDOWN_HIGH,
)
from config import RECOMMENDATIONS_DB_PATH


def _format_score(value):
    if value is None:
        return "N/A"
    return f"{value:.0f}"


def _format_decimal(value):
    if value is None:
        return "N/A"
    return f"{value:.2f}"


def _format_percent(value):
    if value is None:
        return "N/A"
    return f"{value:.1%}"


def _score_from_range(value, low, high, higher_is_risk=True):
    if value is None:
        return None
    if higher_is_risk:
        if value <= low:
            return 0.0
        if value >= high:
            return 100.0
        return float((value - low) / (high - low) * 100)
    if value >= high:
        return 0.0
    if value <= low:
        return 100.0
    return float((high - value) / (high - low) * 100)


def _color_for_score(score):
    if score is None:
        return "#cfd8dc"
    if score < 20:
        return "#2e7d32"
    if score < 40:
        return "#66bb6a"
    if score < 60:
        return "#fdd835"
    if score < 80:
        return "#fb8c00"
    return "#e53935"


def _escape_attr(text):
    if text is None:
        return ""
    return str(text).replace("&", "&amp;").replace("\"", "&quot;").replace("'", "&#39;")


def _render_metric(label, value_text, help_text, score=None):
    bg = _color_for_score(score)
    title = _escape_attr(help_text)
    st.markdown(
        f"""
        <div title="{title}" style="background:{bg};padding:0.35rem 0.5rem;border-radius:0.5rem;margin-bottom:0.4rem;color:#111;">
            <strong>{label}:</strong> {value_text}
        </div>
        """,
        unsafe_allow_html=True,
    )

st.set_page_config(page_title="Favorite Stocks", page_icon="⭐", layout="wide")

st.title("⭐ Favorite Stocks")

st.markdown("""
Track your favorite stocks and monitor their performance over time.
""")

# Sidebar options
with st.sidebar:
    st.header("Actions")
    
    refresh = st.button("🔄 Refresh Data", width='stretch')
    
    if st.button("💰 Update Market Prices", width='stretch'):
        with st.spinner("Updating market prices..."):
            try:
                result = update_market_data_for_recommended_stocks(force=True, only_favorite_stocks=True)
                st.success(f"✅ Updated {result['updated']} stocks, {result['failed']} failed, {result['skipped']} skipped")
                st.rerun()
            except ValueError as e:
                st.error(f"❌ {str(e)}")
            except Exception as e:
                st.error(f"❌ Error updating market data: {str(e)}")
    
    if st.button("💰 Valuate all stocks", width='stretch'):
        # Get all favorites and filter for those with NULL fair_price_dcf
        with RecommendationsDatabase(RECOMMENDATIONS_DB_PATH) as db:
            all_favorites = db.get_all_favorite_stocks()
        
        # Filter stocks with NULL fair_price_dcf
        stocks_to_valuate = [
            stock for stock in all_favorites 
            if pd.isna(stock.get('fair_price_dcf')) or stock.get('fair_price_dcf') is None
        ]
        
        if not stocks_to_valuate:
            st.info("✅ All favorite stocks already have DCF valuations.")
        else:
            st.info(f"📊 Found {len(stocks_to_valuate)} stock(s) to valuate.")
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            results_container = st.container()
            
            success_count = 0
            failed_count = 0
            failed_stocks = []
            
            with RecommendationsDatabase(RECOMMENDATIONS_DB_PATH) as db:
                for idx, stock in enumerate(stocks_to_valuate):
                    ticker = stock.get('ticker')
                    stock_id = stock.get('stock_id')
                    
                    status_text.text(f"Valuating {ticker} ({idx + 1}/{len(stocks_to_valuate)})...")
                    progress_bar.progress((idx + 1) / len(stocks_to_valuate))
                    
                    try:
                        result = get_dcf_valuation(ticker=ticker)
                        fair_value_per_share = result.get('fair_value_per_share')
                        
                        if fair_value_per_share is not None:
                            if db.update_fair_price_dcf(stock_id, fair_value_per_share):
                                success_count += 1
                            else:
                                failed_count += 1
                                failed_stocks.append(f"{ticker} (update failed)")
                        else:
                            failed_count += 1
                            failed_stocks.append(f"{ticker} (no fair value)")
                    except Exception as e:
                        failed_count += 1
                        failed_stocks.append(f"{ticker} ({str(e)})")
            
            # Clear cache and show results
            st.cache_data.clear()
            status_text.empty()
            progress_bar.empty()
            
            if success_count > 0:
                st.success(f"✅ Successfully valuated {success_count} stock(s)")
            
            if failed_count > 0:
                st.warning(f"⚠️ Failed to valuate {failed_count} stock(s)")
                with results_container:
                    for failed in failed_stocks:
                        st.text(f"  • {failed}")
            
            st.rerun()

# Load favorites
@st.cache_data(ttl=60)  # Cache for 1 minute
def load_favorites():
    """Load favorite stocks from database."""
    with RecommendationsDatabase(RECOMMENDATIONS_DB_PATH) as db:
        return db.get_all_favorite_stocks()

try:
    if refresh:
        st.cache_data.clear()
    
    favorites = load_favorites()
    
    if not favorites:
        st.info("No favorite stocks yet. Add stocks from the Recommendations page.")
        st.stop()
    
    # Convert to DataFrame
    df = pd.DataFrame(favorites)
    
    # Display summary metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Favorites", len(df))
    
    with col2:
        if 'gain_loss_pct' in df.columns:
            avg_gain = df['gain_loss_pct'].mean() if len(df) > 0 else 0
            st.metric("Avg Gain/Loss", f"{avg_gain:+.2f}%", delta=f"{avg_gain:+.2f}%")
        else:
            st.metric("Avg Gain/Loss", "N/A")
    
    with col3:
        if 'gain_loss_pct' in df.columns:
            winners = len(df[df['gain_loss_pct'] > 0])
            st.metric("Winners", winners)
        else:
            st.metric("Winners", "N/A")
    
    with col4:
        if 'gain_loss_pct' in df.columns:
            losers = len(df[df['gain_loss_pct'] < 0])
            st.metric("Losers", losers)
        else:
            st.metric("Losers", "N/A")
    
    st.divider()
    
    # Display favorites table
    st.subheader(f"Showing {len(df)} Favorite Stocks")
    
    # Format columns for display
    display_df = df.copy()
    
    # Format numeric columns
    if 'price_on_entry_date' in display_df.columns:
        display_df['price_on_entry_date'] = display_df['price_on_entry_date'].apply(
            lambda x: f"${x:.2f}" if pd.notna(x) else "N/A"
        )
    if 'fair_price' in display_df.columns:
        display_df['fair_price'] = display_df['fair_price'].apply(
            lambda x: f"${x:.2f}" if pd.notna(x) else "N/A"
        )
    if 'fair_price_dcf' in display_df.columns:
        display_df['fair_price_dcf'] = display_df['fair_price_dcf'].apply(
            lambda x: f"${x:.2f}" if pd.notna(x) else "N/A"
        )
    if 'market_price' in display_df.columns:
        display_df['market_price'] = display_df['market_price'].apply(
            lambda x: f"${x:.2f}" if pd.notna(x) else "N/A"
        )
    if 'gain_loss_pct' in display_df.columns:
        display_df['gain_loss_pct'] = display_df['gain_loss_pct'].apply(
            lambda x: f"{x:+.2f}%" if pd.notna(x) else "N/A"
        )
    
    # Select columns to display
    display_columns = ['ticker', 'stock_name', 'exchange', 'entry_date', 
                       'price_on_entry_date', 'fair_price', 'fair_price_dcf', 'market_price', 'market_date', 'gain_loss_pct']
    
    # Filter to available columns
    display_columns = [col for col in display_columns if col in display_df.columns]
    
    # Rename for better display
    column_names = {
        'ticker': 'Ticker',
        'stock_name': 'Company',
        'exchange': 'Exchange',
        'entry_date': 'Entry Date',
        'price_on_entry_date': 'Entry Price',
        'fair_price': 'Recommendations Fair Price',
        'fair_price_dcf': 'My Fair Price (DCF)',
        'market_price': 'Current Price',
        'market_date': 'Price Date',
        'gain_loss_pct': 'Gain/Loss %'
    }
    
    display_df = display_df[display_columns].rename(columns=column_names)
    
    # Style the dataframe
    def highlight_gain_loss(val):
        """Highlight gain/loss percentages."""
        try:
            # Remove % sign and convert to float
            val_str = str(val).replace('%', '').replace('+', '')
            val_float = float(val_str)
            if val_float > 0:
                return 'background-color: #90EE90'  # Light green
            elif val_float < 0:
                return 'background-color: #FFB6C1'  # Light red
            else:
                return ''
        except:
            return ''
    
    styled_df = display_df.style.map(
        highlight_gain_loss, 
        subset=['Gain/Loss %'] if 'Gain/Loss %' in display_df.columns else []
    )
    
    # Display the table with selection capability
    event = st.dataframe(
        styled_df,
        width='stretch',
        height=600,
        key="favorite_stocks_table",
        on_select="rerun",
        selection_mode="single-row"
    )
    
    # Download button
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Download CSV",
        data=csv,
        file_name="favorite_stocks.csv",
        mime="text/csv"
    )
    
    # Handle row selection for removing from favorites
    selected_rows = event.selection.rows
    
    if selected_rows:
        selected_idx = selected_rows[0]
        selected_stock = df.iloc[selected_idx]
        stock_id = selected_stock['stock_id']
        ticker = selected_stock['ticker']
        stock_name = selected_stock['stock_name']
        
        # Display selected stock info and action buttons
        st.divider()
        col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
        with col1:
            st.info(f"📌 Selected: **{ticker}** - {stock_name}")
        
        with col2:
            if st.button("💰 Valuate stock", type="primary", width='stretch'):
                # Perform DCF valuation and update fair_price_dcf
                with st.spinner(f"Calculating DCF valuation for {ticker}..."):
                    try:
                        result = get_dcf_valuation(ticker=ticker)
                        fair_value_per_share = result.get('fair_value_per_share')
                        
                        if fair_value_per_share is not None:
                            with RecommendationsDatabase(RECOMMENDATIONS_DB_PATH) as db:
                                if db.update_fair_price_dcf(stock_id, fair_value_per_share):
                                    st.success(f"✅ Updated fair price DCF for {ticker}: ${fair_value_per_share:.2f}")
                                    # Clear cache to force reload of updated data
                                    st.cache_data.clear()
                                    st.rerun()
                                else:
                                    st.error(f"❌ Failed to update fair price DCF. Stock may not be in favorites.")
                        else:
                            st.error(f"❌ DCF valuation did not return a fair value per share.")
                    except Exception as e:
                        st.error(f"❌ Error calculating DCF valuation: {str(e)}")
        
        with col3:
            if st.button("🗑️ Remove from Favorites", type="secondary", width='stretch'):
                # Remove from favorites
                with RecommendationsDatabase(RECOMMENDATIONS_DB_PATH) as db:
                    if db.remove_from_favorites(stock_id):
                        st.success(f"✅ Removed {ticker} from favorites.")
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(f"❌ Failed to remove {ticker}.")

        with col4:
            if st.button("⚠️ Evaluate Risk", type="secondary", width='stretch'):
                with st.spinner(f"Evaluating risk for {ticker}..."):
                    try:
                        risk_result = get_risk_evaluation(ticker)
                        st.session_state[f"risk_result_{ticker}"] = risk_result
                        st.success("✅ Risk evaluation complete")
                    except Exception as risk_error:
                        st.error(f"❌ Risk evaluation failed: {risk_error}")
        
        # Display additional details
        st.divider()
        st.subheader(f"📊 Performance Details for {ticker}")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            entry_price = selected_stock.get('price_on_entry_date')
            if pd.notna(entry_price):
                st.metric("Entry Price", f"${entry_price:.2f}")
            else:
                st.metric("Entry Price", "N/A")
        
        with col2:
            fair_price_dcf = selected_stock.get('fair_price_dcf')
            if pd.notna(fair_price_dcf):
                st.metric("Fair Price (DCF)", f"${fair_price_dcf:.2f}")
            else:
                st.metric("Fair Price (DCF)", "N/A", help="Click 'Valuate stock' to calculate")
        
        with col3:
            current_price = selected_stock.get('market_price')
            if pd.notna(current_price):
                st.metric("Current Price", f"${current_price:.2f}")
            else:
                st.metric("Current Price", "N/A")
        
        with col4:
            gain_loss = selected_stock.get('gain_loss_pct')
            if pd.notna(gain_loss):
                delta_color = "normal" if gain_loss >= 0 else "inverse"
                st.metric("Gain/Loss", f"{gain_loss:+.2f}%", delta=f"{gain_loss:+.2f}%", delta_color=delta_color)
            else:
                st.metric("Gain/Loss", "N/A")

        # Risk evaluation section
        risk_state_key = f"risk_result_{ticker}"
        if risk_state_key in st.session_state:
            risk_result = st.session_state[risk_state_key]
            st.divider()
            st.subheader(f"⚠️ Risk Evaluation for {ticker}")
            col1, col2, col3 = st.columns(3)
            with col1:
                risk_score = risk_result.get("risk_score")
                _render_metric(
                    "Risk Score",
                    _format_score(risk_score),
                    "Composite risk score from 0-100. Higher means riskier.",
                    score=risk_score,
                )
            with col2:
                _render_metric(
                    "Risk Label",
                    risk_result.get('risk_label', 'N/A'),
                    "Bucketed label based on the composite score.",
                    score=risk_score,
                )
            with col3:
                _render_metric(
                    "Benchmark",
                    risk_result.get('benchmark', 'N/A'),
                    "Market index used to compute beta and relative risk.",
                    score=risk_score,
                )

            sub_scores = risk_result.get("sub_scores") or {}
            metrics = risk_result.get("metrics") or {}
            valuation = risk_result.get("valuation_sensitivity") or {}

            st.markdown("**Sub-scores**")
            col1, col2, col3 = st.columns(3)
            with col1:
                market_score = sub_scores.get("market")
                downside_score = sub_scores.get("downside")
                _render_metric(
                    "Market",
                    _format_score(market_score),
                    "Market risk from beta and volatility. Higher means more sensitive to market moves.",
                    score=market_score,
                )
                _render_metric(
                    "Downside",
                    _format_score(downside_score),
                    "Downside risk from downside deviation, VaR, and CVaR. Higher means worse tail losses.",
                    score=downside_score,
                )
            with col2:
                drawdown_score = sub_scores.get("drawdown")
                leverage_score = sub_scores.get("leverage")
                _render_metric(
                    "Drawdown",
                    _format_score(drawdown_score),
                    "Severity and duration of peak-to-trough declines. Higher means deeper/longer drawdowns.",
                    score=drawdown_score,
                )
                _render_metric(
                    "Leverage",
                    _format_score(leverage_score),
                    "Balance-sheet leverage and liquidity indicators. Higher means more financial risk.",
                    score=leverage_score,
                )
            with col3:
                stability_score = sub_scores.get("stability")
                valuation_score = sub_scores.get("valuation")
                _render_metric(
                    "Stability",
                    _format_score(stability_score),
                    "Volatility of cash flow, revenue, and margins. Higher means less stable fundamentals.",
                    score=stability_score,
                )
                _render_metric(
                    "Valuation",
                    _format_score(valuation_score),
                    "Sensitivity of DCF value to discount rate and terminal growth. Higher means more fragile valuation.",
                    score=valuation_score,
                )

            st.markdown("**Key metrics**")
            col1, col2, col3 = st.columns(3)
            with col1:
                volatility = metrics.get("volatility")
                downside_dev = metrics.get("downside_deviation")
                _render_metric(
                    "Volatility",
                    _format_decimal(volatility),
                    "Annualized standard deviation of daily returns. Higher means larger price swings.",
                    score=_score_from_range(volatility, RISK_VOLATILITY_LOW, RISK_VOLATILITY_HIGH),
                )
                _render_metric(
                    "Downside Deviation",
                    _format_decimal(downside_dev),
                    "Annualized volatility of negative returns only. Higher means worse downside swings.",
                    score=_score_from_range(downside_dev, RISK_DOWNSIDE_DEV_LOW, RISK_DOWNSIDE_DEV_HIGH),
                )
            with col2:
                var_95 = metrics.get("var_95")
                cvar_95 = metrics.get("cvar_95")
                _render_metric(
                    "VaR (95%)",
                    _format_decimal(var_95),
                    "Estimated one-day loss threshold at 95% confidence. Higher means larger typical worst-day loss.",
                    score=_score_from_range(var_95, RISK_VAR_LOW, RISK_VAR_HIGH),
                )
                _render_metric(
                    "CVaR (95%)",
                    _format_decimal(cvar_95),
                    "Average loss beyond the 95% VaR threshold. Higher means fatter tail losses.",
                    score=_score_from_range(cvar_95, RISK_CVAR_LOW, RISK_CVAR_HIGH),
                )
            with col3:
                beta = metrics.get("beta")
                max_drawdown = metrics.get("max_drawdown")
                _render_metric(
                    "Beta",
                    _format_decimal(beta),
                    "Sensitivity of returns to the benchmark index. Above 1 means more volatile than the market.",
                    score=_score_from_range(beta, RISK_BETA_LOW, RISK_BETA_HIGH),
                )
                _render_metric(
                    "Max Drawdown",
                    _format_percent(max_drawdown),
                    "Largest peak-to-trough decline over the lookback window. Higher means bigger historical losses.",
                    score=_score_from_range(max_drawdown, RISK_MAX_DRAWDOWN_LOW, RISK_MAX_DRAWDOWN_HIGH),
                )

            if valuation and valuation.get("percent_below_market") is not None:
                valuation_pct = valuation["percent_below_market"] * 100
                _render_metric(
                    "Valuation Sensitivity",
                    f"{valuation['percent_below_market']:.0%}",
                    "Share of DCF grid scenarios below the current market price. Higher means more downside in plausible scenarios.",
                    score=valuation_pct,
                )

        # Notes section for the selected stock
        st.divider()
        st.subheader(f"📝 Notes for {ticker}")

        with RecommendationsDatabase(RECOMMENDATIONS_DB_PATH) as db:
            notes = db.get_stock_notes(stock_id)

        notes_container = st.container()
        if notes:
            for note in notes:
                with notes_container:
                    st.markdown(f"**{note['entry_date']}**")
                    st.markdown(note['note'])
                    st.markdown("---")
        else:
            st.info("No notes yet for this stock. Add one below to capture your thoughts.")

        form_key = f"add_note_form_{stock_id}"
        note_input_key = f"note_input_{stock_id}"
        with st.form(form_key, clear_on_submit=True):
            note_text = st.text_area(
                "Add a note",
                key=note_input_key,
                height=150,
                placeholder="Example: Reasons for adding to favorites, catalysts, earnings dates, etc."
            )
            submitted = st.form_submit_button("Add note", use_container_width=True)

            if submitted:
                cleaned_note = note_text.strip()
                if not cleaned_note:
                    st.warning("Please enter a note before submitting.")
                else:
                    try:
                        with RecommendationsDatabase(RECOMMENDATIONS_DB_PATH) as db:
                            db.add_stock_note(stock_id, cleaned_note)
                        st.success("Note added ✅")
                        st.rerun()
                    except Exception as note_err:
                        st.error(f"Failed to add note: {note_err}")
    else:
        st.info("👆 Click on a row above to select a favorite stock and remove it")

except Exception as e:
    st.error(f"Error loading favorites: {e}")
    st.exception(e)

# Information section
with st.sidebar:
    st.divider()
    st.header("About Favorites")
    st.markdown("""
    **Track your picks**
    
    - Add stocks from the Recommendations page
    - Monitor price changes since entry
    - Track gains/losses over time
    - Update prices with latest market data
    
    **Tips:**
    - Green = Positive returns
    - Red = Negative returns
    - Click "Update Market Prices" to get latest data
    """)
