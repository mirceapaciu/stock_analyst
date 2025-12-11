# Stock Analyst
AI-powered application for analyzing stocks

## Functional Description

**Stock Analyst** is an AI-powered application that automates the collection and analysis of stock investment recommendations from web sources, combining them with fundamental financial analysis to help users make informed investment decisions.

### Problem It Solves

Investors face the challenge of aggregating and analyzing stock recommendations scattered across numerous financial websites, articles, and analyst reports. Manually collecting, organizing, and evaluating this information is time-consuming and error-prone. Additionally, investors need tools to validate these recommendations against fundamental financial metrics to assess their credibility.

### How It Works

The application uses a multi-stage AI workflow to automate stock recommendation discovery and analysis:

1. **Automated Web Scraping & Analysis**: 
   - Searches financial websites using Google Custom Search API for articles containing stock recommendations
   - Uses an LLM to intelligently extract structured stock data (ticker, rating, price targets, analysis dates) from web content
   - Validates extracted data to prevent hallucinations and ensure accuracy
   - Stores recommendations in a local database with quality scoring

2. **Fundamental Analysis**:
   - Provides DCF (Discounted Cash Flow) valuation calculator to estimate fair stock prices
   - Integrates financial data from Yahoo Finance and Finnhub APIs
   - Calculates WACC (Weighted Average Cost of Capital) automatically or allows custom discount rates
   - Supports customizable forecast periods and growth rate assumptions

3. **Unified Interface**:
   - Streamlit-based web interface for browsing recommendations, managing favorites, and performing valuations
   - Combines web-sourced recommendations with fundamental analysis for comprehensive stock evaluation
   - Password-protected access for security

### Key Features

- **📊 Stock Recommendations**: Automated collection and extraction of stock recommendations from financial websites with ratings, price targets, and analysis dates
- **💰 DCF Valuation**: Calculate intrinsic stock values using discounted cash flow analysis with customizable parameters
- **⭐ Favorites Tracking**: Save and monitor favorite stocks and their performance over time
- **🤖 AI-Powered Extraction**: Uses LLM to intelligently parse unstructured web content into structured stock recommendation data
- **🔍 Quality Scoring**: Automatically assesses recommendation quality based on detail level, explicit ratings, and reasoning depth
- **📈 Real-time Data**: Integrates with financial APIs for current market prices and financial metrics

For a detailed user guide please refer to [docs/USER_GUIDE.md](docs/USER_GUIDE.md)

### Technology Stack

- **AI/LLM**: OpenAI GPT-4o-mini for content extraction and analysis
- **Workflow Engine**: LangGraph for orchestrating multi-step recommendation collection workflow
- **Web Framework**: Streamlit for interactive user interface
- **Data Sources**: Google Custom Search API, Yahoo Finance (yfinance), Finnhub API, Financial Modeling Prep API
- **Database**: SQLite for storing recommendations, DuckDB for the Valuation.

## Quick Start

1. **Clone the repository**
2. **Install dependencies**: `uv sync`  
3. **Set environment variables** in `.env` file or directly in the current environment:
   ```
   OPENAI_API_KEY=your_key
   GOOGLE_API_KEY=your_key
   GOOGLE_CSE_ID=your_id
   FINNHUB_API_KEY=your_key
   FMP_API_KEY=your_key
   APP_PASSWORD=your_password
   ```
4. **Run tests**: `uv run python scripts/run_tests.py unit`
5. **Run the application**: `uv run streamlit run ./src/ui/main_app.py`

## Testing

The project includes two types of tests:

### Unit Tests (Fast) 
```bash
uv run pytest -m "not integration"          # Exclude integration tests
uv run python scripts/run_tests.py unit     # Using helper script
```
- **Fast execution** (no API calls)
- **Reliable** (mocked responses) 
- **CI/CD friendly** (no costs or rate limits)
- Tests business logic, data parsing, error handling

### Integration Tests (Slow)
```bash
uv run pytest -m integration                # Only integration tests  
uv run python scripts/run_tests.py integration # Using helper script
```
- **Real API calls** to OpenAI
- **End-to-end validation** with real data
- **Requires**: API keys in the environment variables
- Tests that prompts work with actual LLM responses

### Run All Tests
```bash
uv run pytest                               # All tests
uv run python scripts/run_tests.py all     # Using helper script  
```

## Deployment
For building and running a docker container please refer to [DOCKER.md](DOCKER.md)
For deploying the container in AWS ECS-Fargate please refer to [deploy/ecs/README.md](deploy/ecs/README.md)

## Architecture

For detailed architecture documentation please refer to [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Ethical considerations

For ethical considerations please refer to [docs/ETHICS.md](docs/ETHICS.md)

## Disclaimer

**This application is for educational and informational purposes only.** 

The stock valuations, analyses, and recommendations provided by this application are based on historical data and mathematical models. They should not be considered as financial advice or recommendations to buy, sell, or hold any securities.

**Important considerations:**
- Past performance does not guarantee future results
- Financial models use assumptions that may not reflect actual market conditions
- Stock prices are influenced by many factors beyond fundamental analysis
- Always conduct your own research and consult with qualified financial advisors before making investment decisions

The author and contributors are not liable for any financial losses, damages, or consequences resulting from the use of this application or reliance on its outputs. **Invest at your own risk.**

# Limitations

The initial version is focussing on US stocks for the following reasons:
- Used APIs support only US stocks
- Default financial parameters are set for the US

