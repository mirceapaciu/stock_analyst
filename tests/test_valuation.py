"""
Integration tests for the valuation module.
"""
import pytest
import sys
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from services.valuation import get_dcf_valuation, print_dcf_analysis, calculate_historical_fcf_growth_rates


def test_dcf_valuation_msft():
    """Test DCF valuation for Microsoft (MSFT)."""
    # Perform DCF valuation
    result = get_dcf_valuation('MSFT', forecast_years=5)
    
    # Verify result structure
    assert 'ticker' in result
    assert result['ticker'] == 'MSFT'
    assert 'fair_value_per_share' in result
    assert 'conservative_fair_value' in result
    assert 'current_price' in result
    assert 'in_discount_rate' in result
    assert 'in_terminal_growth_rate' in result
    
    # Verify numerical validity
    assert result['fair_value_per_share'] > 0
    assert result['conservative_fair_value'] > 0
    assert result['current_price'] > 0
    assert 0 < result['in_discount_rate'] < 1
    assert 0 < result['in_terminal_growth_rate'] < 1
    
    # Verify FCF projections
    assert len(result['projected_fcfs']) == 5
    assert len(result['in_fcf_growth_rates']) == 5
    assert all(fcf > 0 for fcf in result['projected_fcfs'])
    
    # Print analysis for visual inspection
    print_dcf_analysis(result)


def test_dcf_valuation_custom_parameters():
    """Test DCF valuation with custom parameters."""
    # Define test parameters once
    ticker = 'NVO'
    forecast_years = 5
    terminal_growth_rate = 0.025
    discount_rate = None
    # fcf_growth_rates = [0.14, 0.14, 0.14, 0.14, 0.14]
    conservative_factor = 0.9
    
    result = get_dcf_valuation(
        ticker=ticker,
        forecast_years=forecast_years,
        terminal_growth_rate=terminal_growth_rate,
        discount_rate=discount_rate,
        conservative_factor=conservative_factor
    )
    
    # Verify custom parameters were applied
    assert len(result['projected_fcfs']) == forecast_years
    assert result['in_terminal_growth_rate'] == terminal_growth_rate
    # assert result['in_discount_rate'] == discount_rate
    # assert result['in_fcf_growth_rates'] == fcf_growth_rates
    
    # Verify conservative fair value matches the conservative factor
    expected_conservative = result['fair_value_per_share'] * conservative_factor
    assert abs(result['conservative_fair_value'] - expected_conservative) < 0.01
    
    # Print analysis for visual inspection
    print_dcf_analysis(result)


def test_dcf_valuation_negative_upside():
    """Test DCF valuation produces correct upside calculation."""
    result = get_dcf_valuation('MSFT', forecast_years=5)
    
    # Calculate expected upside
    expected_upside = ((result['fair_value_per_share'] - result['current_price']) 
                      / result['current_price'] * 100)
    
    assert abs(result['upside_potential_pct'] - expected_upside) < 0.1


# ============================================================================
# Unit Tests for calculate_historical_fcf_growth_rates
# ============================================================================

class TestCalculateHistoricalFcfGrowthRates:
    """Unit tests for calculate_historical_fcf_growth_rates function."""
    
    def test_calculate_historical_fcf_growth_rates_with_free_cash_flow_row(self):
        """Test with 'Free Cash Flow' row in cashflow statement."""
        # Create mock cashflow DataFrame with Free Cash Flow row
        mock_cashflow = pd.DataFrame({
            '2024-09-30': [100000000],
            '2023-09-30': [80000000],
            '2022-09-30': [60000000],
            '2021-09-30': [50000000],
            '2020-09-30': [40000000]
        }, index=['Free Cash Flow'])
        
        with patch('services.valuation.get_financial_statements') as mock_get_statements:
            mock_get_statements.return_value = {'cashflow': mock_cashflow}
            
            result = calculate_historical_fcf_growth_rates('TEST', years_of_history=5)
            
            # Verify structure
            assert result['ticker'] == 'TEST'
            assert len(result['historical_fcf']) == 5
            assert len(result['historical_dates']) == 5
            assert len(result['growth_rates']) == 4  # 4 year-over-year growth rates
            
            # Verify FCF values are correct (most recent first)
            assert result['historical_fcf'] == [100000000.0, 80000000.0, 60000000.0, 50000000.0, 40000000.0]
            
            # Verify growth rates calculation
            # Year 1: (100M - 80M) / 80M = 0.25
            # Year 2: (80M - 60M) / 60M = 0.333...
            # Year 3: (60M - 50M) / 50M = 0.2
            # Year 4: (50M - 40M) / 40M = 0.25
            expected_growth_1 = (100000000 - 80000000) / 80000000
            expected_growth_2 = (80000000 - 60000000) / 60000000
            expected_growth_3 = (60000000 - 50000000) / 50000000
            expected_growth_4 = (50000000 - 40000000) / 40000000
            
            assert abs(result['growth_rates'][0] - expected_growth_1) < 0.0001
            assert abs(result['growth_rates'][1] - expected_growth_2) < 0.0001
            assert abs(result['growth_rates'][2] - expected_growth_3) < 0.0001
            assert abs(result['growth_rates'][3] - expected_growth_4) < 0.0001
            
            # Verify average and median
            assert result['average_growth'] > 0
            assert result['median_growth'] > 0
            
            # Verify CAGR calculation
            # CAGR = (100M / 40M)^(1/4) - 1
            expected_cagr = (100000000 / 40000000) ** (1/4) - 1
            assert abs(result['cagr'] - expected_cagr) < 0.0001
    
    def test_calculate_historical_fcf_growth_rates_with_calculated_fcf(self):
        """Test with FCF calculated from Operating Cash Flow + Capital Expenditure."""
        # Create mock cashflow DataFrame without Free Cash Flow row
        mock_cashflow = pd.DataFrame({
            '2024-09-30': [120000000, -20000000],  # Operating CF, Capex
            '2023-09-30': [100000000, -20000000],
            '2022-09-30': [80000000, -20000000]
        }, index=['Operating Cash Flow', 'Capital Expenditure'])
        
        with patch('services.valuation.get_financial_statements') as mock_get_statements:
            mock_get_statements.return_value = {'cashflow': mock_cashflow}
            
            result = calculate_historical_fcf_growth_rates('TEST', years_of_history=3)
            
            # Verify FCF values are calculated correctly
            # FCF = Operating CF + Capex (Capex is negative, so we add it)
            # 2024: 120M + (-20M) = 100M
            # 2023: 100M + (-20M) = 80M
            # 2022: 80M + (-20M) = 60M
            assert len(result['historical_fcf']) == 3
            assert result['historical_fcf'][0] == 100000000.0
            assert result['historical_fcf'][1] == 80000000.0
            assert result['historical_fcf'][2] == 60000000.0
            
            # Verify growth rates
            assert len(result['growth_rates']) == 2
    
    def test_calculate_historical_fcf_growth_rates_with_nan_values(self):
        """Test that NaN values are properly skipped."""
        mock_cashflow = pd.DataFrame({
            '2024-09-30': [100000000],
            '2023-09-30': [np.nan],  # NaN should be skipped
            '2022-09-30': [80000000],
            '2021-09-30': [60000000]
        }, index=['Free Cash Flow'])
        
        with patch('services.valuation.get_financial_statements') as mock_get_statements:
            mock_get_statements.return_value = {'cashflow': mock_cashflow}
            
            result = calculate_historical_fcf_growth_rates('TEST', years_of_history=4)
            
            # NaN value should be skipped, so we should have 3 FCF values
            assert len(result['historical_fcf']) == 3
            assert 100000000.0 in result['historical_fcf']
            assert 80000000.0 in result['historical_fcf']
            assert 60000000.0 in result['historical_fcf']
            
            # Should have 2 growth rates (between the 3 valid values)
            assert len(result['growth_rates']) == 2
    
    def test_calculate_historical_fcf_growth_rates_with_zero_values(self):
        """Test handling of zero FCF values in growth rate calculation."""
        mock_cashflow = pd.DataFrame({
            '2024-09-30': [100000000],
            '2023-09-30': [0],  # Zero value - growth rate should be skipped
            '2022-09-30': [50000000]
        }, index=['Free Cash Flow'])
        
        with patch('services.valuation.get_financial_statements') as mock_get_statements:
            mock_get_statements.return_value = {'cashflow': mock_cashflow}
            
            result = calculate_historical_fcf_growth_rates('TEST', years_of_history=3)
            
            # All FCF values should be included (including zero)
            assert len(result['historical_fcf']) == 3
            assert 0.0 in result['historical_fcf']
            
            # Growth rate calculation should skip when older_fcf is 0
            # So we should have 1 growth rate: (100M - 0) / 0 is skipped, (0 - 50M) / 50M = -1
            # Actually, looking at the code: if older_fcf != 0, so (newer - older) / abs(older)
            # So: (100M - 0) is skipped because older_fcf (0) == 0
            # And: (0 - 50M) / 50M = -1
            assert len(result['growth_rates']) == 1
            assert result['growth_rates'][0] == -1.0
    
    def test_calculate_historical_fcf_growth_rates_with_negative_fcf(self):
        """Test handling of negative FCF values."""
        mock_cashflow = pd.DataFrame({
            '2024-09-30': [-10000000],  # Negative FCF
            '2023-09-30': [-20000000],
            '2022-09-30': [-30000000]
        }, index=['Free Cash Flow'])
        
        with patch('services.valuation.get_financial_statements') as mock_get_statements:
            mock_get_statements.return_value = {'cashflow': mock_cashflow}
            
            result = calculate_historical_fcf_growth_rates('TEST', years_of_history=3)
            
            # All negative values should be included
            assert len(result['historical_fcf']) == 3
            assert result['historical_fcf'][0] == -10000000.0
            
            # Growth rates should be calculated correctly
            # (-10M - (-20M)) / abs(-20M) = 10M / 20M = 0.5
            # (-20M - (-30M)) / abs(-30M) = 10M / 30M = 0.333...
            assert len(result['growth_rates']) == 2
            assert abs(result['growth_rates'][0] - 0.5) < 0.0001
            assert abs(result['growth_rates'][1] - (10/30)) < 0.0001
    
    def test_calculate_historical_fcf_growth_rates_with_insufficient_data(self):
        """Test with only one FCF value (no growth rates possible)."""
        mock_cashflow = pd.DataFrame({
            '2024-09-30': [100000000]
        }, index=['Free Cash Flow'])
        
        with patch('services.valuation.get_financial_statements') as mock_get_statements:
            mock_get_statements.return_value = {'cashflow': mock_cashflow}
            
            result = calculate_historical_fcf_growth_rates('TEST', years_of_history=1)
            
            # Should have 1 FCF value but no growth rates
            assert len(result['historical_fcf']) == 1
            assert len(result['growth_rates']) == 0
            assert result['average_growth'] == 0
            assert result['median_growth'] == 0
            assert result['cagr'] == 0
    
    def test_calculate_historical_fcf_growth_rates_with_years_limit(self):
        """Test that years_of_history parameter limits the number of years analyzed."""
        mock_cashflow = pd.DataFrame({
            '2024-09-30': [100000000],
            '2023-09-30': [80000000],
            '2022-09-30': [60000000],
            '2021-09-30': [50000000],
            '2020-09-30': [40000000]
        }, index=['Free Cash Flow'])
        
        with patch('services.valuation.get_financial_statements') as mock_get_statements:
            mock_get_statements.return_value = {'cashflow': mock_cashflow}
            
            # Limit to 3 years
            result = calculate_historical_fcf_growth_rates('TEST', years_of_history=3)
            
            # Should only include 3 years
            assert len(result['historical_fcf']) == 3
            assert len(result['growth_rates']) == 2
    
    def test_calculate_historical_fcf_growth_rates_empty_cashflow(self):
        """Test that empty cashflow raises ValueError."""
        with patch('services.valuation.get_financial_statements') as mock_get_statements:
            mock_get_statements.return_value = {'cashflow': pd.DataFrame()}
            
            with pytest.raises(ValueError, match="No cash flow data available for TEST"):
                calculate_historical_fcf_growth_rates('TEST')
    
    def test_calculate_historical_fcf_growth_rates_none_cashflow(self):
        """Test that None cashflow raises ValueError."""
        with patch('services.valuation.get_financial_statements') as mock_get_statements:
            mock_get_statements.return_value = {'cashflow': None}
            
            with pytest.raises(ValueError, match="No cash flow data available for TEST"):
                calculate_historical_fcf_growth_rates('TEST')
    
    def test_calculate_historical_fcf_growth_rates_cagr_with_zero_starting_value(self):
        """Test CAGR calculation when oldest (starting) FCF value is zero."""
        mock_cashflow = pd.DataFrame({
            '2024-09-30': [100000000],  # Most recent (fcf_values[0])
            '2023-09-30': [80000000],
            '2022-09-30': [60000000],
            '2021-09-30': [0]  # Oldest (fcf_values[-1]) - zero value
        }, index=['Free Cash Flow'])
        
        with patch('services.valuation.get_financial_statements') as mock_get_statements:
            mock_get_statements.return_value = {'cashflow': mock_cashflow}
            
            result = calculate_historical_fcf_growth_rates('TEST', years_of_history=4)
            
            # CAGR should be 0 when oldest value (fcf_values[-1]) is 0
            # The condition checks: fcf_values[-1] != 0 and fcf_values[0] > 0
            # Since fcf_values[-1] (oldest) is 0, CAGR should be 0
            assert result['cagr'] == 0
    
    def test_calculate_historical_fcf_growth_rates_missing_operating_cf(self):
        """Test when Operating Cash Flow is missing (should default to 0)."""
        mock_cashflow = pd.DataFrame({
            '2024-09-30': [-20000000],  # Only Capex
            '2023-09-30': [-20000000]
        }, index=['Capital Expenditure'])
        
        with patch('services.valuation.get_financial_statements') as mock_get_statements:
            mock_get_statements.return_value = {'cashflow': mock_cashflow}
            
            result = calculate_historical_fcf_growth_rates('TEST', years_of_history=2)
            
            # FCF = 0 (missing Operating CF) + (-20M) = -20M
            assert len(result['historical_fcf']) == 2
            assert result['historical_fcf'][0] == -20000000.0


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])

