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
from config import RECOMMENDATIONS_DB_PATH

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
        col1, col2, col3 = st.columns([3, 1, 1])
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
                        st.rerun()
                    else:
                        st.error(f"❌ Failed to remove {ticker}.")
        
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
