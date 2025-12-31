"""Streamlit page for viewing stock recommendations."""

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
from recommendations.workflow import create_workflow
from services.recommendations import update_market_data_for_recommended_stocks
from services.valuation import get_dcf_valuation
from config import RECOMMENDATIONS_DB_PATH

st.set_page_config(page_title="Stock Recommendations", page_icon="📊", layout="wide")

def startup_cleanup():
    """On startup, check for any orphaned workflow processes and mark them as FAILED."""
    db = RecommendationsDatabase(RECOMMENDATIONS_DB_PATH)
    process_status = db.get_process_status("recommendations_workflow")
    if process_status and process_status.get('status') == 'STARTED':
        # Mark orphaned process as FAILED (likely from previous crash/shutdown)
        db.end_process("recommendations_workflow", 'FAILED')
    st.session_state['startup_cleanup_done'] = True

if 'startup_cleanup_done' not in st.session_state:
    startup_cleanup()

st.title("📊 Stock Recommendations")

st.markdown("""
Browse stock recommendations collected from various financial websites and analyst reports.
""")

# Filters in sidebar
with st.sidebar:
    st.header("Actions")
    
    # Check if workflow is currently running
    db = RecommendationsDatabase(RECOMMENDATIONS_DB_PATH)
    process_status = db.get_process_status("recommendations_workflow")
    is_running = db.is_process_running("recommendations_workflow")
       
    if is_running:
        # Disabled button when running
        st.button("🔍 Collect New Recommendations", type="primary", width='stretch', disabled=True)
        if process_status:
            progress = process_status.get('progress_pct', 0)
            st.progress(progress / 100.0)
            st.caption(f"Progress: {progress}%")
    else:
        # Collect new recommendations button
        if st.button("🔍 Collect New Recommendations", type="primary", width='stretch'):
            # Set flag to start workflow (process will be started in collect_recommendations_workflow
            # after S3 sync to avoid race condition)
            st.session_state['run_workflow'] = True
            st.rerun()
    
    # Always show last process status if it exists
    if process_status:
        status = process_status.get('status', 'UNKNOWN')
        start_time = process_status.get('start_timestamp', 'N/A')
        
        if status == 'STARTED':
            st.warning(f"⚙️ Workflow is currently running, Started on {start_time}")
        elif status == 'COMPLETED':
            st.success(f"✅ Last run: COMPLETED on {process_status.get('end_timestamp', 'N/A')}")
        elif status == 'FAILED':
            st.error(f"❌ Last run: FAILED on {process_status.get('end_timestamp', start_time)}")

    if st.button("💰 Update Market Prices", width='stretch'):
        with st.spinner("Updating market prices..."):
            try:
                result = update_market_data_for_recommended_stocks()
                st.success(f"✅ Updated {result['updated']} stocks, {result['failed']} failed, {result['skipped']} skipped")
                st.rerun()
            except ValueError as e:
                st.error(f"❌ {str(e)}")
            except Exception as e:
                st.error(f"❌ Error updating market data: {str(e)}")
    
    if st.button("💰 Valuate all stocks", width='stretch'):
        # Get all recommendations and filter for those with NULL fair_price_dcf
        with RecommendationsDatabase(RECOMMENDATIONS_DB_PATH) as db:
            all_recommendations = db.get_all_recommended_stocks()
        
        # Filter stocks with NULL fair_price_dcf
        stocks_to_valuate = [
            stock for stock in all_recommendations 
            if pd.isna(stock.get('fair_price_dcf')) or stock.get('fair_price_dcf') is None
        ]
        
        if not stocks_to_valuate:
            st.info("✅ All recommended stocks already have DCF valuations.")
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
            
            # Use toast for persistent notifications across rerun
            if success_count > 0:
                st.toast(f"✅ Successfully valuated {success_count} stock(s)", icon="✅")
            
            if failed_count > 0:
                st.toast(f"⚠️ Failed to valuate {failed_count} stock(s)", icon="⚠️")
                # Store failed stocks in session state to display after rerun
                st.session_state['valuation_failures'] = failed_stocks
            
            st.rerun()

    st.divider()
    
    st.header("Filters")
    
    filter_na_price = st.checkbox(
        "Filter N/A Market Price",
        value=True,
        help="Show only stocks with available market prices"
    )
    
    min_rating = st.slider(
        "Minimum Rating",
        min_value=0.0,
        max_value=5.0,
        value=4.0,
        step=0.5,
        help="Filter stocks with average rating >= this value"
    )
    
    sort_by = st.selectbox(
        "Sort By",
        options=["Rating (Highest)", "Rating (Lowest)", "Date (Recent)", "Date (Oldest)", "Ticker (A-Z)"],
        index=0
    )
    
    refresh = st.button("🔄 Refresh Data", width='stretch')

def collect_recommendations_workflow():
    """Start the workflow in a background subprocess (non-blocking)."""
    import subprocess
    from pathlib import Path
    
    # Get project root directory (src_path is src/, so parent is project root)
    root_path = src_path.parent
    
    # Create database instance (this will sync from S3 first)
    db = RecommendationsDatabase(RECOMMENDATIONS_DB_PATH)
    
    # Check if already running (safety check)
    if db.is_process_running("recommendations_workflow"):
        st.warning("⚠️ Workflow is already running.")
        return
    
    # Start process tracking AFTER S3 sync to ensure it's persisted
    try:
        db.start_process("recommendations_workflow")
        # Verify the process was started
        if not db.is_process_running("recommendations_workflow"):
            st.error("❌ Process was not started properly. Please try again.")
            return
        # Sync to S3 immediately so sidebar can see the status
        from utils.s3_storage import get_s3_storage
        s3 = get_s3_storage()
        if s3.s3_client:
            s3.sync_database_to_s3(RECOMMENDATIONS_DB_PATH)
    except Exception as e:
        st.error(f"❌ Failed to start process tracking: {str(e)}")
        import traceback
        with st.expander("🐛 Error Details"):
            st.code(traceback.format_exc())
        return
    
    # Run workflow in subprocess to avoid event loop conflicts
    script_path = root_path / "scripts" / "run_recommendations_workflow.py"
    
    # Verify script exists
    if not script_path.exists():
        st.error(f"❌ Script not found: {script_path}")
        db.end_process("recommendations_workflow", 'FAILED')
        return
    
    try:
        # Start the workflow script in the background (non-blocking)
        subprocess.Popen(
            ["uv", "run", "python", str(script_path)],
            cwd=root_path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        st.toast("🚀 Workflow started in background. Check sidebar for progress.", icon="✅")
        # Rerun to update the sidebar with the new process status
        st.rerun()
        
    except Exception as e:
        st.error(f"Error starting workflow: {str(e)}")
        db.end_process("recommendations_workflow", 'FAILED')
        import traceback
        with st.expander("🐛 Error Details"):
            st.code(traceback.format_exc())

# Check if workflow should run
if st.session_state.get('run_workflow', False):
    st.session_state['run_workflow'] = False
    collect_recommendations_workflow()

# Load recommendations
@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_recommendations():
    """Load recommendations from database."""
    with RecommendationsDatabase(RECOMMENDATIONS_DB_PATH) as db:
        return db.get_all_recommended_stocks()

######################  Module-level Logic  ######################
try:
    if refresh:
        st.cache_data.clear()
    
    # Display valuation failures from previous run if they exist
    if 'valuation_failures' in st.session_state and st.session_state['valuation_failures']:
        with st.expander("⚠️ Failed Valuations", expanded=False):
            for failed in st.session_state['valuation_failures']:
                st.text(f"  • {failed}")
            if st.button("Clear Failures", key="clear_failures"):
                del st.session_state['valuation_failures']
                st.rerun()
    
    recommendations = load_recommendations()
    
    if not recommendations:
        st.info("No recommendations found. Run the collection workflow to gather stock recommendations.")
        st.stop()
    
    # Convert to DataFrame
    df = pd.DataFrame(recommendations)
    
    # Filter by market price if checkbox is enabled
    if filter_na_price:
        df = df[df['market_price'].notna()]
    
    # Filter by rating
    df = df[df['rating'] >= min_rating]
    
    # Sort
    if sort_by == "Rating (Highest)":
        df = df.sort_values('rating', ascending=False)
    elif sort_by == "Rating (Lowest)":
        df = df.sort_values('rating', ascending=True)
    elif sort_by == "Date (Recent)":
        df = df.sort_values('last_analysis_date', ascending=False)
    elif sort_by == "Date (Oldest)":
        df = df.sort_values('last_analysis_date', ascending=True)
    elif sort_by == "Ticker (A-Z)":
        df = df.sort_values('ticker', ascending=True)
    
    # Display summary metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Recommendations", len(df))
    
    with col2:
        avg_rating = df['rating'].mean() if len(df) > 0 else 0
        st.metric("Average Rating", f"{avg_rating:.2f}")
    
    with col3:
        strong_buy_count = len(df[df['rating'] >= 4.5])
        st.metric("Strong Buy", strong_buy_count)
    
    with col4:
        buy_count = len(df[(df['rating'] >= 3.5) & (df['rating'] < 4.5)])
        st.metric("Buy", buy_count)
    
    st.divider()
    
    # Display recommendations table
    st.subheader(f"Showing {len(df)} Recommendations")
    
    # Format columns for display
    display_df = df.copy()
    
    # Format numeric columns
    if 'rating' in display_df.columns:
        display_df['rating'] = display_df['rating'].apply(lambda x: f"{x:.1f}" if pd.notna(x) else "N/A")
    if 'fair_price' in display_df.columns:
        display_df['fair_price'] = display_df['fair_price'].apply(lambda x: f"${x:.2f}" if pd.notna(x) else "N/A")
    if 'fair_price_dcf' in display_df.columns:
        display_df['fair_price_dcf'] = display_df['fair_price_dcf'].apply(lambda x: f"${x:.2f}" if pd.notna(x) else "N/A")
    if 'target_price' in display_df.columns:
        display_df['target_price'] = display_df['target_price'].apply(lambda x: f"${x:.2f}" if pd.notna(x) else "N/A")
    if 'market_price' in display_df.columns:
        display_df['market_price'] = display_df['market_price'].apply(lambda x: f"${x:.2f}" if pd.notna(x) else "N/A")
    if 'price_potential_pct' in display_df.columns:
        display_df['price_potential_pct'] = display_df['price_potential_pct'].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "N/A")
    if 'price_growth_forecast_pct' in display_df.columns:
        display_df['price_growth_forecast_pct'] = display_df['price_growth_forecast_pct'].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "N/A")
    
    # Select columns to display
    display_columns = ['ticker', 'stock_name', 'exchange', 'rating', 'last_analysis_date', 
                       'fair_price', 'fair_price_dcf', 'market_price', 'price_potential_pct']
    
    # Filter to available columns
    display_columns = [col for col in display_columns if col in display_df.columns]
    
    # Rename for better display
    column_names = {
        'ticker': 'Ticker',
        'stock_name': 'Company',
        'exchange': 'Exchange',
        'rating': 'Rating',
        'last_analysis_date': 'Analysis Date',
        'fair_price': 'Recommendations Fair Price',
        'fair_price_dcf': 'My Fair Price (DCF)',
        'target_price': 'Target Price',
        'market_price': 'Market Price',
        'price_potential_pct': 'Price Potential %'
    }
    
    display_df = display_df[display_columns].rename(columns=column_names)
    
    # Style the dataframe
    def highlight_rating(val):
        """Highlight rating values."""
        try:
            val_float = float(val)
            if val_float >= 4.5:
                return 'background-color: #90EE90'  # Light green
            elif val_float >= 3.5:
                return 'background-color: #FFFFE0'  # Light yellow
            else:
                return ''
        except:
            return ''
    
    styled_df = display_df.style.map(highlight_rating, subset=['Rating'] if 'Rating' in display_df.columns else [])
    
    # Display the table with selection capability
    event = st.dataframe(
        styled_df,
        width='stretch',
        height=600,
        key="recommended_stocks_table",
        on_select="rerun",
        selection_mode="single-row"
    )
    
    # Download button
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Download CSV",
        data=csv,
        file_name="stock_recommendations.csv",
        mime="text/csv"
    )
    
    # Handle row selection for adding to favorites and showing details
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
                                    st.error(f"❌ Failed to update fair price DCF.")
                        else:
                            st.error(f"❌ DCF valuation did not return a fair value per share.")
                    except Exception as e:
                        st.error(f"❌ Error calculating DCF valuation: {str(e)}")
        
        with col3:
            with RecommendationsDatabase(RECOMMENDATIONS_DB_PATH) as db:
                is_fav = db.is_favorite(stock_id)
            
            if is_fav:
                st.success("⭐ Already in Favorites")
            else:
                if st.button("⭐ Add to Favorites", type="secondary", width='stretch'):
                    # Add to favorites
                    try:
                        with RecommendationsDatabase(RECOMMENDATIONS_DB_PATH) as db:
                            if db.add_to_favorites(stock_id):
                                st.success(f"✅ Added {ticker} to favorites!")
                                st.rerun()
                            else:
                                st.warning(f"⚠️ {ticker} is already in favorites.")
                    except ValueError as e:
                        st.error(f"❌ Cannot add to favorites: {str(e)}")
                        st.info("💡 Try updating market data first.")
        
        # Display details for selected stock
        st.divider()
        st.subheader(f"📋 Details for {ticker}")
        
        # Get summary statistics
        with RecommendationsDatabase(RECOMMENDATIONS_DB_PATH) as db:
            summary = db.get_input_recommendations_summary_for_stock(stock_id)
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric(
                label="Total Recommendations",
                value=summary['total_count']
            )
        with col2:
            avg_rating = summary['average_rating']
            if avg_rating is not None:
                # Map numeric rating to name
                rating_names = ['N/A', 'Strong Sell', 'Sell', 'Hold', 'Buy', 'Strong Buy']
                rating_idx = round(avg_rating)
                rating_name = rating_names[rating_idx] if 0 <= rating_idx < len(rating_names) else 'N/A'
                st.metric(
                    label="Average Rating",
                    value=f"{avg_rating:.1f}",
                    delta=rating_name
                )
            else:
                st.metric(
                    label="Average Rating",
                    value="N/A"
                )
        
        # Get and display input recommendations table
        st.subheader("📊 Individual Stock Recommendations")
        with RecommendationsDatabase(RECOMMENDATIONS_DB_PATH) as db:
            input_recs = db.get_input_recommendations_for_stock(stock_id)
        
        if input_recs:
            input_df = pd.DataFrame(input_recs)
            
            # Select and rename columns for display
            display_cols = {
                'rating': 'Rating',
                'analysis_date': 'Analysis Date',
                'price': 'Price',
                'fair_price': 'Fair Price',
                'target_price': 'Target Price',
                'price_growth_forecast_pct': 'Growth %',
                'pe': 'P/E',
                'recommendation_text': 'Recommendation Reason',
                'webpage_url': 'Source URL'
            }
            
            # Select only columns that exist
            available_cols = {k: v for k, v in display_cols.items() if k in input_df.columns}
            
            if available_cols:
                input_df_display = input_df[list(available_cols.keys())].copy()
                input_df_display.columns = list(available_cols.values())
                
                # Format numeric columns
                if 'Price' in input_df_display.columns:
                    input_df_display['Price'] = input_df_display['Price'].apply(
                        lambda x: f"${x:.2f}" if pd.notna(x) else "N/A"
                    )
                if 'Fair Price' in input_df_display.columns:
                    input_df_display['Fair Price'] = input_df_display['Fair Price'].apply(
                        lambda x: f"${x:.2f}" if pd.notna(x) else "N/A"
                    )
                if 'Target Price' in input_df_display.columns:
                    input_df_display['Target Price'] = input_df_display['Target Price'].apply(
                        lambda x: f"${x:.2f}" if pd.notna(x) else "N/A"
                    )
                if 'Growth %' in input_df_display.columns:
                    input_df_display['Growth %'] = input_df_display['Growth %'].apply(
                        lambda x: f"{x:+.2f}%" if pd.notna(x) else "N/A"
                    )
                if 'P/E' in input_df_display.columns:
                    input_df_display['P/E'] = input_df_display['P/E'].apply(
                        lambda x: f"{x:.2f}" if pd.notna(x) else "N/A"
                    )
                
                # Truncate recommendation text for better display
                MAX_RECOMMENDATION_LENGTH = 200
                if 'Recommendation' in input_df_display.columns:
                    input_df_display['Recommendation'] = input_df_display['Recommendation'].apply(
                        lambda x: (x[:MAX_RECOMMENDATION_LENGTH] + '...') if pd.notna(x) and len(str(x)) > MAX_RECOMMENDATION_LENGTH else (x if pd.notna(x) else "N/A")
                    )
                
                st.dataframe(
                    input_df_display,
                    width='stretch',
                    hide_index=True,
                    column_config={
                        'Source URL': st.column_config.LinkColumn('Source URL'),
                        'Recommendation': st.column_config.TextColumn(
                            'Recommendation',
                            width='large'
                        )
                    }
                )
            else:
                st.dataframe(input_df, width='stretch', hide_index=True)
        else:
            st.info("No individual recommendations found for this stock.")
    else:
        st.info("👆 Click on a row above to select a stock and view details")


except Exception as e:
    st.error(f"Error loading recommendations: {e}")
    st.exception(e)
