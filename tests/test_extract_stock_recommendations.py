"""Unit tests for extract_stock_recommendations_with_llm function."""

import pytest
import sys
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from recommendations.workflow import (
    extract_stock_recommendations_with_llm,
    StockRecommendationsResponse,
    StockRecommendation,
    RecommendationQuality
)


class TestExtractStockRecommendations:
    """Test extract_stock_recommendations_with_llm with real-world Morningstar data."""
    
    @pytest.fixture
    def morningstar_homepage_data(self):
        """Test data from Morningstar stocks homepage."""
        return {
            "url": "https://www.morningstar.com/stocks",
            "webpage_title": "Stocks, Economic Moats, Company Earnings, and Dividends ...",
            "webpage_date": "2025-11-17",
            "page_text": "Bella Albrecht Nov 17, 2025 Susan Dziubinski Nov 18, 2025 Tori Brovet Nov 18, 2025 David Sekera, CFA and Susan Dziubinski Nov 17, 2025 Bella Albrecht Nov 17, 2025 Cyclical Basic Materials −1.65% Consumer Cyclical −0.87% Financial Services −2.05% Real Estate −0.72% Sensitive Communication Services +0.39% Energy −1.88% Industrials −1.30% Technology −1.47% Defensive Consumer Defensive −0.65% Healthcare −0.03% Utilities +0.76% Featured Moat Stocks by Sector Moat Stocks by Style Undervalued Stocks By Sector Undervalued Stocks by Style Ambev SA ADR Bristol-Myers Squibb Co Clorox Co Vdwmgnx Gxgkx Yfrbdk M.J. Ldkhqm View Full List Adient PLC Akamai Technologies Inc Americold Realty Trust Inc Kyfh & Qhys Rkkjp Gm Wkmngz Gncplrhgvztvg Dkpvlb WZ Hbxbfgfstlb Hbp Tmjvj View Full List adidas AG ADR Adient PLC Adobe Inc Zbl Gxfgytzm ffh Bnzllwpdc Plqvjz Nfh Zqwjbxpk Snfxyh - Hthpv Tfdsjx Ftgxzfqsnndg Lgwm View Full List ABB Ltd ADR AbbVie Inc Accenture PLC Class A Fgtwh Cz Kqnmcsz Myzmkhsjcvln Xpjc Vsh Vskjtcrw dcj Ydxzbnbkf Wd View Full List Adobe Inc Air Products and Chemicals Inc Airbnb Inc Ordinary Shares - Class A Jsldzvs Yzxrq Mfskpsz Cbz PKHKXR Zntrqyxd Mhj Kxlmw PCV Klnpxksv Rwd Rtsjy GCM View Full List Jump-start your search with Investor's pre-built screens based on our analysts' stock research and ratings. View Free for 7 Days These 12 undervalued industrials stocks look attractive today. Tori Brovet Nov 17, 2025 Berkshire reports net sales of roughly $7.9 billion for the third quarter. Greggory Warren, CFA Nov 15, 2025 Plus, the full list of stocks bought and sold last quarter. Susan Dziubinski Nov 14, 2025 Albemarle stock jumps while Endava stock dips. Frank Lee Nov 14, 2025 We view this as an orderly, internally driven succession that maintains strategic continuity rather than signaling a shift in direction. Brett Husslein Nov 14, 2025 With outstanding long-term estimates, here's what we think of Nvidia stock. Brian Colello, CPA Nov 14, 2025 We think Tencent Holdings stock is moderately undervalued. Ivan Su Nov 14, 2025 The weakness was entirely in linear entertainment networks and theatrical films. Matthew Dolgin, CFA Nov 13, 2025 The crypto investment manager's revenue has been dropping, but its net income has increased. Michael Bodley Nov 13, 2025 We've raised our fair value estimate of Cisco stock. William Kerwin, CFA Nov 13, 2025 With reduced unit production costs and raised guidance, here's what we think of Albemarle's stock. Seth Goldstein, CFA Nov 13, 2025 This stock offers a reliable yield and upside potential backed by durable competitive advantages. Erin Lash, CFA Nov 13, 2025 These 10 undervalued REIT stocks look attractive today. Tori Brovet Nov 13, 2025 Challenges in today's credit markets could be canaries in the coal mine or red herrings. Dan Lefkovitz Nov 13, 2025 We've raised our fair value estimate of AMD stock. Brian Colello, CPA Nov 12, 2025 With shares richly valued, here's what we think of Home Depot stock. Jaime M. Katz, CFA Nov 12, 2025 These are the top dividend-paying stocks to buy today. Susan Dziubinski Nov 11, 2025 We've raised our fair value estimate of Oxy stock. Joshua Aguilar Nov 11, 2025 We think Paramount stock is moderately undervalued. Matthew Dolgin, CFA Nov 11, 2025 With results exceeding management's forecast for Q3, here's what we think of Uber stock. Mark Giarelli Nov 11, 2025"
        }
    
    @pytest.fixture
    def morningstar_amd_article_data(self):
        """Test data from Morningstar AMD investor day article."""
        return {
            "url": "https://www.morningstar.com/stocks/amd-investor-day-touts-tremendous-ai-growth-with-steady-margins",
            "webpage_title": "We've raised our fair value estimate of AMD stock.Brian Colello, CPANov 12, 2025",
            "webpage_date": "2025-11-12",
            "page_text": "Securities in This Article Advanced Micro Devices Inc (AMD) Key Morningstar Metrics for Advanced Micro Devices Fair Value Estimate : $270.00 Morningstar Rating : ★★★ Morningstar Economic Moat Rating : Narrow Morningstar Uncertainty Rating : Very High Advanced Micro Devices AMD hosted an investor day that featured updated revenue growth and financial targets. These include growth in the next three to five years of 80% in data center artificial intelligence products, 60% in all data center products, and 35% for total AMD. The firm's adjusted gross margin target is now 55%-58%, ahead of 54% currently. Why it matters: AMD increased its bullishness on the AI market, both in total (targeting a $1 trillion-plus market by 2030) and for the company (expecting 10%-plus market share). This implies $100 billion in AI revenue over the next three to five years, which exceeds our expectations. Meanwhile, AMD is targeting modest gross margin expansion, which is encouraging to us, as we were concerned that AI revenue might be a bit dilutive as the company strives to gain market share. Between growth and healthy margins, AMD is targeting $20 of earnings per share by 2030. AI growth seems plausible to us and is based on its customer conversations. AMD has public partnerships with OpenAI, Oracle, and Meta. The company hinted that it is in deep discussions with other leading hyperscalers, sovereign entities, and AI-native firms. The bottom line: We raise our fair value estimate for narrow-moat AMD to $270 per share from $210, as we again lift our AI revenue estimates for the firm. We retain our Very High Uncertainty Rating, as the AI market continues to shift rapidly. Shares now appear a little undervalued to us. We now model a 31% revenue compound annual growth rate for AMD through 2029, up from our prior estimate of 26%. Our data center and AI GPU CAGRs now rise to 42% and 62%, respectively, up from 37% and 55%. Yet we still have some modest conservatism compared with AMD's targets. Even though the AI industry is computing-constrained, and management addressed these concerns head-on, we're still cautious that industry funding and energy/power generation might cause firms like OpenAI to grow a bit more slowly than visualized. Editor's Note: This analysis was originally published as a stock note by Morningstar Equity Research. The author or authors do not own shares in any securities mentioned in this article. Find out about Morningstar's editorial policies ."
        }
    
    @pytest.fixture
    def mock_llm_response_homepage(self):
        """Mock LLM response for homepage data - should extract AMD."""
        return StockRecommendationsResponse(
            analysis_date="2025-11-17",
            tickers=[
                StockRecommendation(
                    ticker="AMD",
                    exchange="NASDAQ",
                    stock_name="Advanced Micro Devices, Inc.",
                    rating=4,
                    price="N/A",
                    fair_price="N/A",
                    target_price="N/A",
                    price_growth_forecast_pct="N/A",
                    pe="N/A",
                    recommendation_text="We've raised our fair value estimate of AMD stock.",
                    quality=RecommendationQuality(
                        description_word_count=9,
                        has_explicit_rating=False,
                        reasoning_detail_level=1
                    )
                )
            ]
        )
    
    @pytest.fixture
    def mock_llm_response_amd_article(self):
        """Mock LLM response for AMD article - should extract AMD with 3-star rating."""
        return StockRecommendationsResponse(
            analysis_date="2025-11-12",
            tickers=[
                StockRecommendation(
                    ticker="AMD",
                    exchange="NASDAQ",
                    stock_name="Advanced Micro Devices, Inc.",
                    rating=3,  # 3 stars = Hold
                    price="N/A",
                    fair_price=270,
                    target_price="N/A",
                    price_growth_forecast_pct=31,
                    pe="N/A",
                    recommendation_text="Shares now appear a little undervalued to us, with a raised fair value estimate reflecting strong growth expectations in AI revenue.",
                    quality=RecommendationQuality(
                        description_word_count=500,
                        has_explicit_rating=True,
                        reasoning_detail_level=3
                    )
                )
            ]
        )
    
    def test_extract_from_homepage(self, morningstar_homepage_data, mock_llm_response_homepage):
        """Test extraction from Morningstar homepage with brief mention of AMD."""
        url = morningstar_homepage_data["url"]
        title = morningstar_homepage_data["webpage_title"]
        page_text = morningstar_homepage_data["page_text"]
        page_date = datetime.strptime(morningstar_homepage_data["webpage_date"], "%Y-%m-%d")
        
        with patch('recommendations.workflow.ChatOpenAI') as mock_openai:
            # Mock the LLM to return our test response
            mock_llm = Mock()
            mock_structured_llm = Mock()
            mock_structured_llm.invoke.return_value = mock_llm_response_homepage
            mock_llm.with_structured_output.return_value = mock_structured_llm
            mock_openai.return_value = mock_llm
            
            # Call the function
            recommendations = extract_stock_recommendations_with_llm(url, title, page_text, page_date)
            
            # Assertions
            assert len(recommendations) == 1
            
            amd_rec = recommendations[0]
            assert amd_rec["ticker"] == "AMD"
            assert amd_rec["exchange"] == "NASDAQ"
            assert amd_rec["stock_name"] == "Advanced Micro Devices, Inc."
            assert amd_rec["rating"] == 4  # Buy rating
            assert amd_rec["analysis_date"] == "2025-11-17"
            assert amd_rec["quality_score"] == 10  # Low quality: 9 words, no rating, brief reasoning
            assert amd_rec["quality_description_words"] == 9
            assert amd_rec["quality_has_rating"] is False
            assert amd_rec["quality_reasoning_level"] == 1
    
    def test_extract_from_amd_article(self, morningstar_amd_article_data, mock_llm_response_amd_article):
        """Test extraction from detailed AMD article with 3-star Morningstar rating."""
        url = morningstar_amd_article_data["url"]
        title = morningstar_amd_article_data["webpage_title"]
        page_text = morningstar_amd_article_data["page_text"]
        page_date = datetime.strptime(morningstar_amd_article_data["webpage_date"], "%Y-%m-%d")
        
        with patch('recommendations.workflow.ChatOpenAI') as mock_openai:
            # Mock the LLM to return our test response
            mock_llm = Mock()
            mock_structured_llm = Mock()
            mock_structured_llm.invoke.return_value = mock_llm_response_amd_article
            mock_llm.with_structured_output.return_value = mock_structured_llm
            mock_openai.return_value = mock_llm
            
            # Call the function
            recommendations = extract_stock_recommendations_with_llm(url, title, page_text, page_date)
            
            # Assertions
            assert len(recommendations) == 1
            
            amd_rec = recommendations[0]
            assert amd_rec["ticker"] == "AMD"
            assert amd_rec["exchange"] == "NASDAQ"
            assert amd_rec["stock_name"] == "Advanced Micro Devices, Inc."
            assert amd_rec["rating"] == 3  # Hold rating (3 stars)
            assert amd_rec["analysis_date"] == "2025-11-12"
            assert amd_rec["fair_price"] == "270"
            assert amd_rec["price_growth_forecast_pct"] == "31"
            assert amd_rec["quality_score"] == 85  # High quality: 500 words, has rating, detailed reasoning
            assert amd_rec["quality_description_words"] == 500
            assert amd_rec["quality_has_rating"] is True
            assert amd_rec["quality_reasoning_level"] == 3
    
    def test_ticker_validation_filters_hallucinations(self, morningstar_homepage_data):
        """Test that tickers not in page text are filtered out (hallucination prevention)."""
        url = morningstar_homepage_data["url"]
        title = morningstar_homepage_data["webpage_title"]
        page_text = morningstar_homepage_data["page_text"]
        page_date = datetime.strptime(morningstar_homepage_data["webpage_date"], "%Y-%m-%d")
        
        # Mock LLM response with a hallucinated ticker not in the page text
        mock_response = StockRecommendationsResponse(
            analysis_date="2025-11-17",
            tickers=[
                StockRecommendation(
                    ticker="FAKE",  # This ticker doesn't appear in page_text
                    exchange="NASDAQ",
                    stock_name="Fake Company Inc.",
                    rating=5,
                    recommendation_text="This is a hallucinated recommendation.",
                    quality=RecommendationQuality(
                        description_word_count=50,
                        has_explicit_rating=True,
                        reasoning_detail_level=2
                    )
                )
            ]
        )
        
        with patch('recommendations.workflow.ChatOpenAI') as mock_openai:
            mock_llm = Mock()
            mock_structured_llm = Mock()
            mock_structured_llm.invoke.return_value = mock_response
            mock_llm.with_structured_output.return_value = mock_structured_llm
            mock_openai.return_value = mock_llm
            
            # Call the function
            recommendations = extract_stock_recommendations_with_llm(url, title, page_text, page_date)
            
            # Should filter out the hallucinated ticker
            assert len(recommendations) == 0
    
    def test_quality_score_calculation(self, morningstar_amd_article_data, mock_llm_response_amd_article):
        """Test that quality score is calculated correctly from LLM components."""
        url = morningstar_amd_article_data["url"]
        title = morningstar_amd_article_data["webpage_title"]
        page_text = morningstar_amd_article_data["page_text"]
        page_date = datetime.strptime(morningstar_amd_article_data["webpage_date"], "%Y-%m-%d")
        
        with patch('recommendations.workflow.ChatOpenAI') as mock_openai:
            mock_llm = Mock()
            mock_structured_llm = Mock()
            mock_structured_llm.invoke.return_value = mock_llm_response_amd_article
            mock_llm.with_structured_output.return_value = mock_structured_llm
            mock_openai.return_value = mock_llm
            
            recommendations = extract_stock_recommendations_with_llm(url, title, page_text, page_date)
            
            amd_rec = recommendations[0]
            
            # Quality score calculation:
            # Description: 500 words = 30 points (capped at 30)
            # Has rating: 25 points
            # Reasoning level 3: 30 points (3 * 10)
            # Total: 30 + 25 + 30 = 85
            assert amd_rec["quality_score"] == 85
    
    def test_rating_normalization_from_stars(self):
        """Test that star symbols in rating field are normalized to numeric 1-5."""
        # Test that if LLM returns star symbols, they get converted to numeric
        star_recommendation = StockRecommendation(
            ticker="TEST",
            rating="★★★",  # 3 stars should become 3
            recommendation_text="Test",
            quality=RecommendationQuality()
        )
        
        # model_post_init should have converted stars to numeric
        assert star_recommendation.rating == 3
        assert isinstance(star_recommendation.rating, int)
    
    def test_rating_normalization_from_text(self):
        """Test that text ratings are normalized to numeric 1-5."""
        # Test various text ratings
        test_cases = [
            ("Strong Buy", 5),
            ("Buy", 4),
            ("Hold", 3),
            ("Sell", 2),
            ("Strong Sell", 1),
        ]
        
        for text_rating, expected_numeric in test_cases:
            rec = StockRecommendation(
                ticker="TEST",
                rating=text_rating,
                recommendation_text="Test",
                quality=RecommendationQuality()
            )
            assert rec.rating == expected_numeric
            assert isinstance(rec.rating, int)
    
    def test_llm_error_handling(self, morningstar_homepage_data):
        """Test that LLM errors are handled gracefully and return empty list."""
        url = morningstar_homepage_data["url"]
        title = morningstar_homepage_data["webpage_title"]
        page_text = morningstar_homepage_data["page_text"]
        page_date = datetime.strptime(morningstar_homepage_data["webpage_date"], "%Y-%m-%d")
        
        with patch('recommendations.workflow.ChatOpenAI') as mock_openai:
            mock_llm = Mock()
            mock_structured_llm = Mock()
            # Simulate LLM error
            mock_structured_llm.invoke.side_effect = Exception("LLM API error")
            mock_llm.with_structured_output.return_value = mock_structured_llm
            mock_openai.return_value = mock_llm
            
            # Should return empty list on error
            recommendations = extract_stock_recommendations_with_llm(url, title, page_text, page_date)
            assert recommendations == []
    
    def test_empty_tickers_returns_empty_list(self, morningstar_homepage_data):
        """Test that when LLM returns no tickers, function returns empty list."""
        url = morningstar_homepage_data["url"]
        title = morningstar_homepage_data["webpage_title"]
        page_text = morningstar_homepage_data["page_text"]
        page_date = datetime.strptime(morningstar_homepage_data["webpage_date"], "%Y-%m-%d")
        
        # Mock LLM response with no tickers
        mock_response = StockRecommendationsResponse(
            analysis_date="2025-11-17",
            tickers=[]
        )
        
        with patch('recommendations.workflow.ChatOpenAI') as mock_openai:
            mock_llm = Mock()
            mock_structured_llm = Mock()
            mock_structured_llm.invoke.return_value = mock_response
            mock_llm.with_structured_output.return_value = mock_structured_llm
            mock_openai.return_value = mock_llm
            
            recommendations = extract_stock_recommendations_with_llm(url, title, page_text, page_date)
            assert recommendations == []
