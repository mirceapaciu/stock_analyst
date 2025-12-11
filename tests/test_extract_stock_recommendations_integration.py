"""Integration tests for extract_stock_recommendations_with_llm function.

These tests make REAL API calls to OpenAI and should be run separately from unit tests.
They verify that the LLM can actually extract stock recommendations from real Morningstar content.

Run with: pytest tests/test_extract_stock_recommendations_integration.py -v -m integration
"""

import pytest
import sys
import os
from pathlib import Path
from datetime import datetime

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from recommendations.workflow import extract_stock_recommendations_with_llm
from utils.logger import setup_logging


# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


class TestExtractStockRecommendationsIntegration:
    """Integration tests using real LLM calls with Morningstar data."""
    
    @classmethod
    def setup_class(cls):
        """Setup logging and check for API key before running tests."""
        setup_logging()
        
        # Check for OpenAI API key
        if not os.getenv('OPENAI_API_KEY'):
            pytest.skip("OPENAI_API_KEY not found - skipping integration tests")
    
    @pytest.fixture
    def morningstar_homepage_data(self):
        """Real Morningstar homepage data with multiple stock mentions."""
        return {
            "url": "https://www.morningstar.com/stocks",
            "title": "Stocks, Economic Moats, Company Earnings, and Dividends ...",
            "page_text": """Bella Albrecht Nov 17, 2025 Susan Dziubinski Nov 18, 2025 Tori Brovet Nov 18, 2025 David Sekera, CFA and Susan Dziubinski Nov 17, 2025 Bella Albrecht Nov 17, 2025 Cyclical Basic Materials −1.65% Consumer Cyclical −0.87% Financial Services −2.05% Real Estate −0.72% Sensitive Communication Services +0.39% Energy −1.88% Industrials −1.30% Technology −1.47% Defensive Consumer Defensive −0.65% Healthcare −0.03% Utilities +0.76% Featured Moat Stocks by Sector Moat Stocks by Style Undervalued Stocks By Sector Undervalued Stocks by Style Ambev SA ADR Bristol-Myers Squibb Co Clorox Co Vdwmgnx Gxgkx Yfrbdk M.J. Ldkhqm View Full List Adient PLC Akamai Technologies Inc Americold Realty Trust Inc Kyfh & Qhys Rkkjp Gm Wkmngz Gncplrhgvztvg Dkpvlb WZ Hbxbfgfstlb Hbp Tmjvj View Full List adidas AG ADR Adient PLC Adobe Inc Zbl Gxfgytzm ffh Bnzllwpdc Plqvjz Nfh Zqwjbxpk Snfxyh - Hthpv Tfdsjx Ftgxzfqsnndg Lgwm View Full List ABB Ltd ADR AbbVie Inc Accenture PLC Class A Fgtwh Cz Kqnmcsz Myzmkhsjcvln Xpjc Vsh Vskjtcrw dcj Ydxzbnbkf Wd View Full List Adobe Inc Air Products and Chemicals Inc Airbnb Inc Ordinary Shares - Class A Jsldzvs Yzxrq Mfskpsz Cbz PKHKXR Zntrqyxd Mhj Kxlmw PCV Klnpxksv Rwd Rtsjy GCM View Full List Jump-start your search with Investor's pre-built screens based on our analysts' stock research and ratings. View Free for 7 Days These 12 undervalued industrials stocks look attractive today. Tori Brovet Nov 17, 2025 Berkshire reports net sales of roughly $7.9 billion for the third quarter. Greggory Warren, CFA Nov 15, 2025 Plus, the full list of stocks bought and sold last quarter. Susan Dziubinski Nov 14, 2025 Albemarle stock jumps while Endava stock dips. Frank Lee Nov 14, 2025 We view this as an orderly, internally driven succession that maintains strategic continuity rather than signaling a shift in direction. Brett Husslein Nov 14, 2025 With outstanding long-term estimates, here's what we think of Nvidia stock. Brian Colello, CPA Nov 14, 2025 We think Tencent Holdings stock is moderately undervalued. Ivan Su Nov 14, 2025 The weakness was entirely in linear entertainment networks and theatrical films. Matthew Dolgin, CFA Nov 13, 2025 The crypto investment manager's revenue has been dropping, but its net income has increased. Michael Bodley Nov 13, 2025 We've raised our fair value estimate of Cisco stock. William Kerwin, CFA Nov 13, 2025 With reduced unit production costs and raised guidance, here's what we think of Albemarle's stock. Seth Goldstein, CFA Nov 13, 2025 This stock offers a reliable yield and upside potential backed by durable competitive advantages. Erin Lash, CFA Nov 13, 2025 These 10 undervalued REIT stocks look attractive today. Tori Brovet Nov 13, 2025 Challenges in today's credit markets could be canaries in the coal mine or red herrings. Dan Lefkovitz Nov 13, 2025 We've raised our fair value estimate of AMD stock. Brian Colello, CPA Nov 12, 2025 With shares richly valued, here's what we think of Home Depot stock. Jaime M. Katz, CFA Nov 12, 2025 These are the top dividend-paying stocks to buy today. Susan Dziubinski Nov 11, 2025 We've raised our fair value estimate of Oxy stock. Joshua Aguilar Nov 11, 2025 We think Paramount stock is moderately undervalued. Matthew Dolgin, CFA Nov 11, 2025 With results exceeding management's forecast for Q3, here's what we think of Uber stock. Mark Giarelli Nov 11, 2025""",
            "date": "2025-11-17"
        }
    
    @pytest.fixture
    def morningstar_amd_article_data(self):
        """Real Morningstar AMD article with 3-star rating and detailed analysis."""
        return {
            "url": "https://www.morningstar.com/stocks/amd-investor-day-touts-tremendous-ai-growth-with-steady-margins",
            "title": "We've raised our fair value estimate of AMD stock.Brian Colello, CPANov 12, 2025",
            "page_text": """Securities in This Article Advanced Micro Devices Inc (AMD) Key Morningstar Metrics for Advanced Micro Devices Fair Value Estimate : $270.00 Morningstar Rating : ★★★ Morningstar Economic Moat Rating : Narrow Morningstar Uncertainty Rating : Very High Advanced Micro Devices AMD hosted an investor day that featured updated revenue growth and financial targets. These include growth in the next three to five years of 80% in data center artificial intelligence products, 60% in all data center products, and 35% for total AMD. The firm's adjusted gross margin target is now 55%-58%, ahead of 54% currently. Why it matters: AMD increased its bullishness on the AI market, both in total (targeting a $1 trillion-plus market by 2030) and for the company (expecting 10%-plus market share). This implies $100 billion in AI revenue over the next three to five years, which exceeds our expectations. Meanwhile, AMD is targeting modest gross margin expansion, which is encouraging to us, as we were concerned that AI revenue might be a bit dilutive as the company strives to gain market share. Between growth and healthy margins, AMD is targeting $20 of earnings per share by 2030. AI growth seems plausible to us and is based on its customer conversations. AMD has public partnerships with OpenAI, Oracle, and Meta. The company hinted that it is in deep discussions with other leading hyperscalers, sovereign entities, and AI-native firms. The bottom line: We raise our fair value estimate for narrow-moat AMD to $270 per share from $210, as we again lift our AI revenue estimates for the firm. We retain our Very High Uncertainty Rating, as the AI market continues to shift rapidly. Shares now appear a little undervalued to us. We now model a 31% revenue compound annual growth rate for AMD through 2029, up from our prior estimate of 26%. Our data center and AI GPU CAGRs now rise to 42% and 62%, respectively, up from 37% and 55%. Yet we still have some modest conservatism compared with AMD's targets. Even though the AI industry is computing-constrained, and management addressed these concerns head-on, we're still cautious that industry funding and energy/power generation might cause firms like OpenAI to grow a bit more slowly than visualized. Editor's Note: This analysis was originally published as a stock note by Morningstar Equity Research. The author or authors do not own shares in any securities mentioned in this article. Find out about Morningstar's editorial policies .""",
            "date": "2025-11-12"
        }
    
    @pytest.mark.slow
    def test_extract_from_morningstar_homepage_real_llm(self, morningstar_homepage_data):
        """Test extraction from Morningstar homepage using real LLM - should find multiple stocks."""
        url = morningstar_homepage_data["url"]
        title = morningstar_homepage_data["title"]
        page_text = morningstar_homepage_data["page_text"]
        page_date = datetime.strptime(morningstar_homepage_data["date"], "%Y-%m-%d")
        
        # Make real LLM call
        recommendations = extract_stock_recommendations_with_llm(url, title, page_text, page_date)
        
        # Assertions - the LLM should find several stocks from the homepage
        print(f"Found {len(recommendations)} recommendations:")
        for rec in recommendations:
            print(f"  {rec['ticker']}: {rec['recommendation_text'][:50]}...")
        
        # Should find at least a few stocks (AMD, NVDA, CISCO, OXY, UBER, etc. are mentioned)
        assert len(recommendations) >= 1, "Should find at least one stock recommendation"
        
        # Verify structure of returned recommendations
        for rec in recommendations:
            assert "ticker" in rec
            assert "rating" in rec
            assert isinstance(rec["rating"], int), f"Rating should be int, got {type(rec['rating'])}"
            assert 1 <= rec["rating"] <= 5, f"Rating should be 1-5, got {rec['rating']}"
            assert "quality_score" in rec
            assert isinstance(rec["quality_score"], int)
            assert 0 <= rec["quality_score"] <= 100
            assert "analysis_date" in rec
            print(f"✓ {rec['ticker']}: rating={rec['rating']}, quality={rec['quality_score']}")
    
    @pytest.mark.slow  
    def test_extract_from_amd_article_real_llm(self, morningstar_amd_article_data):
        """Test extraction from detailed AMD article using real LLM - should extract AMD with high quality."""
        url = morningstar_amd_article_data["url"]
        title = morningstar_amd_article_data["title"] 
        page_text = morningstar_amd_article_data["page_text"]
        page_date = datetime.strptime(morningstar_amd_article_data["date"], "%Y-%m-%d")
        
        # Make real LLM call
        recommendations = extract_stock_recommendations_with_llm(url, title, page_text, page_date)
        
        print(f"Found {len(recommendations)} recommendations from AMD article")
        
        # Should find exactly AMD 
        assert len(recommendations) == 1, f"Should find exactly 1 recommendation, got {len(recommendations)}"
        
        amd_rec = recommendations[0]
        print(f"AMD recommendation: {amd_rec}")
        
        # Verify AMD details
        assert amd_rec["ticker"] == "AMD"
        assert amd_rec["analysis_date"] == "2025-11-12"
        
        # Rating should be 3 (Hold) based on 3 stars
        assert amd_rec["rating"] == 3, f"Expected rating 3 (Hold), got {amd_rec['rating']}"
        
        # Should have high quality due to detailed analysis, star rating, etc.
        assert amd_rec["quality_score"] >= 60, f"Expected high quality score >=60, got {amd_rec['quality_score']}"
        
        # Should extract numerical data from the article
        assert amd_rec["fair_price"] == "270" or amd_rec["fair_price"] == 270, "Should extract $270 fair value"
        
        print(f"✓ AMD: rating={amd_rec['rating']}, quality={amd_rec['quality_score']}, fair_value={amd_rec['fair_price']}")
    
    @pytest.mark.slow
    def test_prompt_extracts_star_ratings(self, morningstar_amd_article_data):
        """Test that the LLM correctly interprets Morningstar star ratings from the prompt."""
        # This article has "Morningstar Rating : ★★★" which should become rating=3
        url = morningstar_amd_article_data["url"]
        title = morningstar_amd_article_data["title"]
        page_text = morningstar_amd_article_data["page_text"]
        page_date = datetime.strptime(morningstar_amd_article_data["date"], "%Y-%m-%d")
        
        recommendations = extract_stock_recommendations_with_llm(url, title, page_text, page_date)
        
        assert len(recommendations) == 1
        amd_rec = recommendations[0]
        
        # The key test: LLM should correctly interpret 3 stars as rating=3 (Hold)
        assert amd_rec["rating"] == 3, f"3 stars should convert to rating=3, got {amd_rec['rating']}"
        
        # Quality should reflect that it has an explicit rating
        assert amd_rec["quality_has_rating"] is True, "Should detect explicit star rating"
        
        print(f"✓ Star rating conversion: ★★★ → {amd_rec['rating']} (Hold)")
    
    def test_no_hallucinations_real_llm(self):
        """Test that LLM doesn't hallucinate tickers not in the text."""
        # Use minimal text with no stock mentions
        minimal_text = "This is a general market overview with no specific stock recommendations."
        
        recommendations = extract_stock_recommendations_with_llm(
            url="https://example.com",
            title="Market Overview",
            page_text=minimal_text,
            page_date=datetime.now()
        )
        
        # Should return empty list - no stocks to extract
        assert len(recommendations) == 0, f"Should find no stocks in minimal text, got {len(recommendations)}"
        print("✓ No hallucinations: LLM correctly returned empty list for text with no stocks")
    
    @pytest.mark.slow
    def test_quality_assessment_real_llm(self, morningstar_amd_article_data, morningstar_homepage_data):
        """Test that LLM quality assessment works correctly for different content types."""
        
        # Extract from detailed article (should have high quality)
        detailed_recs = extract_stock_recommendations_with_llm(
            morningstar_amd_article_data["url"],
            morningstar_amd_article_data["title"], 
            morningstar_amd_article_data["page_text"],
            datetime.strptime(morningstar_amd_article_data["date"], "%Y-%m-%d")
        )
        
        # Extract from homepage (should have lower quality - brief mentions)
        homepage_recs = extract_stock_recommendations_with_llm(
            morningstar_homepage_data["url"],
            morningstar_homepage_data["title"],
            morningstar_homepage_data["page_text"], 
            datetime.strptime(morningstar_homepage_data["date"], "%Y-%m-%d")
        )
        
        if detailed_recs and homepage_recs:
            detailed_quality = detailed_recs[0]["quality_score"]
            homepage_quality = max(rec["quality_score"] for rec in homepage_recs)
            
            print(f"Quality scores - Detailed article: {detailed_quality}, Homepage: {homepage_quality}")
            
            # Detailed article should have higher quality than homepage mentions
            assert detailed_quality > homepage_quality, \
                f"Detailed article ({detailed_quality}) should have higher quality than homepage ({homepage_quality})"
            
            print("✓ Quality assessment: Detailed analysis scored higher than brief mentions")
        else:
            pytest.skip("Need both detailed and homepage recommendations to compare quality")


if __name__ == "__main__":
    # Allow running integration tests directly
    pytest.main([__file__, "-v", "-m", "integration", "-s"])