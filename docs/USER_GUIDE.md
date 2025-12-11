# User Guide - Stock Analysis Platform

## Table of Contents

1. [Getting Started](#getting-started)
2. [Authentication](#authentication)
3. [Stock Recommendations Page](#stock-recommendations-page)
4. [Favorite Stocks Page](#favorite-stocks-page)
5. [DCF Valuation Page](#dcf-valuation-page)
6. [Understanding the Data](#understanding-the-data)
7. [Tips and Best Practices](#tips-and-best-practices)
8. [Troubleshooting](#troubleshooting)

---

## Getting Started

### First Steps

1. **Access the Application**: Open the Streamlit application in your web browser
2. **Authenticate**: Enter the password when prompted (see [Authentication](#authentication) section)
3. **Navigate**: Use the sidebar to switch between the three main pages:
   - 📊 **Stock Recommendations** - Browse and collect stock recommendations
   - ⭐ **Favorite Stocks** - Track your favorite stocks and their performance
   - 💰 **DCF Valuation** - Calculate fair stock prices using DCF analysis

### Quick Workflow

1. Start by visiting the **Stock Recommendations** page
2. Collect new recommendations or browse existing ones
3. Click on interesting stocks to view details
4. Add promising stocks to your **Favorites**
5. Use **DCF Valuation** to calculate fair prices for stocks you're considering
6. Monitor your favorites' performance over time

---

## Authentication

The application is password-protected for security. When you first access the application:

1. You'll see a password input field
2. Enter the application password (set via `APP_PASSWORD` environment variable)
3. If the password is incorrect, you'll see an error message and can try again
4. Once authenticated, you'll have access to all features

**Note**: The password is stored securely and not displayed after entry.

---

## Stock Recommendations Page

### Overview

The Recommendations page displays stock recommendations collected from various financial websites and analyst reports. Each recommendation includes ratings, price targets, and analysis dates.

### Collecting New Recommendations

1. Click the **"🔍 Collect New Recommendations"** button in the sidebar
2. The workflow will start running in the background
3. You'll see a progress bar showing the collection status
4. The button will be disabled while the workflow is running
5. Status messages will show:
   - ⚙️ **STARTED** - Workflow is currently running
   - ✅ **COMPLETED** - Last run completed successfully
   - ❌ **FAILED** - Last run encountered an error

**Note**: The collection process can take several minutes as it searches the web, extracts data, and validates recommendations.

### Viewing Recommendations

The main table displays:
- **Ticker** - Stock symbol
- **Company** - Company name
- **Exchange** - Stock exchange (e.g., NASDAQ, NYSE)
- **Rating** - Average rating (0-5 scale, see [Understanding Ratings](#understanding-ratings))
- **Analysis Date** - Date of the most recent recommendation
- **Recommendations Fair Price** - Average fair price from web sources
- **My Fair Price (DCF)** - Your calculated DCF fair price (if available)
- **Market Price** - Current market price
- **Price Potential %** - Upside potential based on fair price vs market price

### Filtering and Sorting

Use the sidebar filters to customize your view:

- **Filter N/A Market Price**: Check to hide stocks without current market prices
- **Minimum Rating**: Use the slider (0.0-5.0) to show only stocks with ratings above a threshold
- **Sort By**: Choose from:
  - Rating (Highest) - Best rated stocks first
  - Rating (Lowest) - Lowest rated stocks first
  - Date (Recent) - Most recent analysis first
  - Date (Oldest) - Oldest analysis first
  - Ticker (A-Z) - Alphabetical order

### Interacting with Stocks

1. **Select a Stock**: Click on any row in the recommendations table
2. **View Details**: The selected stock's details will appear below the table
3. **Available Actions**:
   - **💰 Valuate stock** - Calculate DCF valuation for this stock
   - **⭐ Add to Favorites** - Add the stock to your favorites list

### Stock Details View

When you select a stock, you'll see:

- **Summary Statistics**:
  - Total number of recommendations for this stock
  - Average rating with rating name (Strong Buy, Buy, Hold, etc.)

- **Individual Recommendations Table**: Shows all individual recommendations from different sources, including:
  - Rating
  - Analysis Date
  - Price at time of recommendation
  - Fair Price
  - Target Price
  - Growth Forecast %
  - P/E Ratio
  - Recommendation Text
  - Source URL (clickable link)

### Updating Market Prices

1. Click **"💰 Update Market Prices"** in the sidebar
2. The system will fetch the latest market prices for all recommended stocks
3. You'll see a summary: number of stocks updated, failed, and skipped
4. The table will refresh automatically with new prices

### Valuating Stocks

- **Valuate Individual Stock**: Select a stock and click **"💰 Valuate stock"** to calculate its DCF valuation
- **Valuate All Stocks**: Click **"💰 Valuate all stocks"** in the sidebar to calculate DCF valuations for all stocks that don't have one yet
  - A progress bar will show the valuation progress
  - Results will show how many succeeded and failed

### Downloading Data

Click the **"📥 Download CSV"** button to download all recommendations as a CSV file for external analysis.

---

## Favorite Stocks Page

### Overview

The Favorites page allows you to track stocks you're interested in and monitor their performance over time.

### Adding Stocks to Favorites

1. Go to the **Stock Recommendations** page
2. Click on a stock row to select it
3. Click the **"⭐ Add to Favorites"** button
4. The stock will be added with the current market price as the entry price

**Note**: If a stock doesn't have a market price, you may need to update market prices first.

### Viewing Your Favorites

The main table shows:
- **Ticker** - Stock symbol
- **Company** - Company name
- **Exchange** - Stock exchange
- **Entry Date** - Date when you added the stock
- **Entry Price** - Market price when you added it
- **Recommendations Fair Price** - Average fair price from web sources
- **My Fair Price (DCF)** - Your calculated DCF fair price
- **Current Price** - Latest market price
- **Price Date** - Date of the current price
- **Gain/Loss %** - Percentage change since entry (color-coded: green for gains, red for losses)

### Summary Metrics

At the top of the page, you'll see:
- **Total Favorites** - Number of stocks in your favorites
- **Avg Gain/Loss** - Average percentage gain/loss across all favorites
- **Winners** - Number of stocks with positive returns
- **Losers** - Number of stocks with negative returns

### Managing Favorites

1. **Select a Stock**: Click on any row in the favorites table
2. **Available Actions**:
   - **💰 Valuate stock** - Calculate or update DCF valuation
   - **🗑️ Remove from Favorites** - Remove the stock from your favorites list

### Updating Market Prices

1. Click **"💰 Update Market Prices"** in the sidebar
2. This updates prices for all favorite stocks
3. Gain/loss percentages will be recalculated automatically

### Valuating Favorite Stocks

- **Valuate Individual Stock**: Select a stock and click **"💰 Valuate stock"**
- **Valuate All Stocks**: Click **"💰 Valuate all stocks"** to calculate DCF valuations for all favorites that don't have one yet

### Performance Details

When you select a favorite stock, you'll see detailed metrics:
- Entry Price
- Fair Price (DCF)
- Current Price
- Gain/Loss percentage with color-coded delta

---

## DCF Valuation Page

### Overview

The DCF (Discounted Cash Flow) Valuation page allows you to calculate the intrinsic fair value of any stock using fundamental financial analysis.

### How DCF Works

DCF valuation estimates a stock's fair price by:
1. Projecting future free cash flows
2. Discounting them to present value using WACC (Weighted Average Cost of Capital)
3. Adding terminal value (value beyond the forecast period)
4. Converting to per-share value

### Using the DCF Calculator

1. **Enter Stock Ticker**: Type the stock symbol (e.g., AAPL, MSFT, GOOGL)
2. **Set Forecast Period**: Choose 3-10 years (default: 5 years)
   - Longer periods provide more detailed projections but require more assumptions
3. **Set Terminal Growth Rate**: Choose 1.0-5.0% (default: 2.5%)
   - This is the perpetual growth rate after the forecast period
   - Typically 2-4% (roughly equal to long-term GDP growth)
   - Must be less than the discount rate
4. **Choose Discount Rate**:
   - **Automatic WACC**: Leave "Use Custom Discount Rate" unchecked
     - WACC is calculated automatically based on company financials
   - **Custom Rate**: Check "Use Custom Discount Rate" and set a value (typically 8-15%)
5. **Set Conservative Factor**: Choose 0.70-1.00 (default: 0.90)
   - Applies a margin of safety to the valuation
   - Lower values = more conservative (safer) valuation
6. **Click "Calculate DCF"**

### Understanding the Results

After calculation, you'll see:

#### Key Metrics
- **Current Price** - Current market price of the stock
- **Fair Price** - Calculated fair value (with conservative factor applied)
- **Upside Potential** - Percentage difference between fair price and current price
- **Recommendation** - Based on upside potential:
  - **STRONG BUY** - Price < 70% of fair price
  - **BUY** - Price < 90% of fair price
  - **HOLD** - Price within 90-110% of fair price
  - **SELL** - Price > fair price

#### Detailed Analysis

Expand the **"📊 Detailed Analysis"** section to see:
- **Valuation Inputs**: Discount rate, terminal growth rate, forecast period, conservative factor, FCF growth rates
- **Valuation Components**: 
  - PV of Projected FCF (Present Value of projected free cash flows)
  - PV of Terminal Value (Present Value of terminal value)
  - Enterprise Value
  - Equity Value
  - Shares Outstanding

#### Cash Flow Projections

Expand the **"💵 Cash Flow Projections"** section to see:
- Year-by-year projected free cash flows
- Present value of each year's cash flow

#### Text Analysis

Expand the **"📝 Text Analysis"** section to see:
- Detailed textual breakdown of the valuation calculation

### Tips for DCF Valuation

- **Terminal Growth Rate**: 
  - Be conservative (2-3%) unless the company has strong competitive advantages
  - Higher rates significantly increase valuation
  - Should always be less than the discount rate
  - See [DCF Valuation Details](finance/dcf_valuation.md) for more information
  
- **Forecast Period**: 
  - 5 years is a good balance for most stocks
  - Use longer periods (7-10 years) for stable, predictable companies
  - Use shorter periods (3-5 years) for volatile or cyclical companies

- **Conservative Factor**: 
  - Use 0.85-0.90 for most stocks (15-10% margin of safety)
  - Use 0.70-0.80 for high-risk stocks (30-20% margin of safety)
  - Use 1.00 only if you're very confident in the inputs

- **Custom Discount Rate**: 
  - Use automatic WACC unless you have specific reasons to override
  - Custom rates are useful for comparing different scenarios
  - Typical range: 8-12% for stable companies, 12-15% for riskier companies

---

## Understanding the Data

### Rating System

Ratings are on a 0-5 scale, mapped to traditional ratings:
- **5.0** = Strong Buy
- **4.0-4.9** = Buy
- **3.0-3.9** = Hold
- **2.0-2.9** = Sell
- **1.0-1.9** = Strong Sell
- **0.0-0.9** = No rating / N/A

The rating shown is an average of all recommendations for that stock.

### Price Metrics

- **Market Price**: Current trading price from Finnhub API
- **Recommendations Fair Price**: Average fair price estimate from web sources
- **My Fair Price (DCF)**: Your calculated fair price using DCF analysis
- **Target Price**: Analyst target price from recommendations
- **Entry Price**: Price when you added the stock to favorites

### Performance Metrics

- **Gain/Loss %**: `(Current Price - Entry Price) / Entry Price × 100`
  - Positive = gain (green)
  - Negative = loss (red)
  
- **Price Potential %**: `(Fair Price - Market Price) / Market Price × 100`
  - Positive = stock is undervalued
  - Negative = stock is overvalued

### Data Sources

- **Web Recommendations**: Collected via Google Custom Search API and LLM-based extraction
- **Financial Data**: Yahoo Finance via yfinance library
- **Market Data**: Finnhub API for real-time market prices
- **Financial Metrics**: Financial Modeling Prep API

---

## Tips and Best Practices

### General Tips

1. **Start with Recommendations**: Browse recommendations to discover new stocks
2. **Validate with DCF**: Use DCF valuation to verify recommendation prices
3. **Track Performance**: Add interesting stocks to favorites to monitor over time
4. **Update Regularly**: Refresh market prices weekly to keep data current
5. **Compare Sources**: Look at individual recommendations to see consensus

### Recommendation Collection

- **Don't Over-Collect**: The workflow can take time; collect when you need fresh data
- **Check Status**: Monitor the workflow progress in the sidebar
- **Be Patient**: Collection involves web searching, extraction, and validation

### DCF Valuation

- **Use Multiple Scenarios**: Try different terminal growth rates and conservative factors
- **Compare to Recommendations**: See how your DCF compares to web source fair prices
- **Consider Context**: DCF works best for companies with predictable cash flows
- **Update Regularly**: Recalculate as new financial data becomes available

### Favorites Management

- **Regular Review**: Periodically review favorites and remove stocks you're no longer interested in
- **Track Entry Points**: The entry price helps you track your decision-making
- **Monitor Valuations**: Update DCF valuations when financial data changes

---

## Troubleshooting

### Common Issues

#### "No recommendations found"
- **Solution**: Click "🔍 Collect New Recommendations" to gather initial data
- The workflow may take several minutes to complete

#### "Cannot add to favorites"
- **Solution**: The stock may not have a market price. Click "💰 Update Market Prices" first
- Then try adding to favorites again

#### "DCF valuation failed"
- **Possible Causes**:
  - Stock ticker is incorrect
  - Financial data is unavailable for this stock
  - Company doesn't have sufficient financial history
- **Solution**: 
  - Verify the ticker symbol
  - Try a different stock
  - Check if the company is publicly traded in the US

#### "Market price is N/A"
- **Solution**: Click "💰 Update Market Prices" to fetch latest prices
- Some stocks may not have real-time data available

#### Workflow Status Shows "FAILED"
- **Possible Causes**:
  - API rate limits exceeded
  - Network connectivity issues
  - Invalid API keys
- **Solution**: 
  - Wait a few minutes and try again
  - Check your API key configuration
  - Review error details if available

#### Password Not Working
- **Solution**: Verify the `APP_PASSWORD` environment variable is set correctly
- Restart the application after changing the password

### Data Refresh Issues

- **Cache**: The application caches data for performance
- **Force Refresh**: Click "🔄 Refresh Data" to clear cache and reload
- **Automatic Refresh**: Some actions (like updating prices) automatically refresh data

### Performance Tips

- **Large Datasets**: If you have many favorites, consider filtering or removing old entries
- **Valuation Time**: DCF calculations can take 10-30 seconds per stock
- **Batch Operations**: Use "Valuate all stocks" during off-peak times

---

## Additional Resources

- **Architecture Documentation**: See [ARCHITECTURE.md](ARCHITECTURE.md) for technical details
- **Ethical Considerations**: See [ETHICS.md](ETHICS.md) for ethical guidelines
- **DCF Details**: See [finance/dcf_valuation.md](finance/dcf_valuation.md) for detailed DCF methodology

---

## Disclaimer

**This application is for educational and informational purposes only.**

The stock valuations, analyses, and recommendations provided by this application are based on historical data and mathematical models. They should not be considered as financial advice or recommendations to buy, sell, or hold any securities.

**Important considerations:**
- Past performance does not guarantee future results
- Financial models use assumptions that may not reflect actual market conditions
- Stock prices are influenced by many factors beyond fundamental analysis
- Always conduct your own research and consult with qualified financial advisors before making investment decisions

The author and contributors are not liable for any financial losses, damages, or consequences resulting from the use of this application or reliance on its outputs. **Invest at your own risk.**

