# 1. Data Privacy & User Data Protection

- Local data storage: Data is stored locally in SQLite/DuckDB, not sent to third parties
- No personal data collection: The app doesn't collect or store personal information
- Password protection: The authentication layer (APP_PASSWORD) is protecting access
- API key security: The API keys are stored as environment variables, not hardcoded

# 2. Web Scraping Ethics & Respect for Website Terms

- Rate limiting: Rate limits are respected and scraping follows respectful practices
- Public data only: Only scraping publicly available financial information
- Cookie consent handling: Cookie consent banners are handled appropriately
- User-Agent identification: The scraper uses standard browser headers to access publicly available content. While this is common practice, we acknowledge that some websites may prefer explicit bot identification. In production, we would consider adding a custom User-Agent that identifies our application, or using official APIs where available.
- Error handling: Respects 403 errors and backs off when sites block access

# 3. AI Bias & Transparency

- Hallucination prevention: Validation steps are implemented to prevent LLM hallucinations
- Quality scoring: Recommendations are scored for quality and detail
- Transparency: The disclaimer clearly states this is for educational purposes only

# 4. Financial Responsibility & Disclaimers

- Clear disclaimer: A clear disclaimer is provided stating this is for educational purposes only
- Educational purpose: Emphasize this is not financial advice
- User responsibility: Users are responsible for their own investment decisions

# 5. Data Source Attribution & Intellectual Property

- Source tracking: The database stores source URLs for recommendations
- Attribution: Original sources are preserved and can be referenced
- Public APIs: Using official APIs (Yahoo Finance, Finnhub) rather than unauthorized scraping

# 6. Limitations & Honest Assessment

- Geographic limitations: US stocks only due to API constraints
- API dependencies: Reliance on third-party APIs with rate limits
- Model accuracy: AI extraction may not be 100% accurate