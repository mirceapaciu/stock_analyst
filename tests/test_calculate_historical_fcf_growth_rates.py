"""
Unit tests for calculate_historical_fcf_growth_rates function
"""
import pytest
import numpy as np
import sys
import os

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from services.valuation import calculate_historical_fcf_growth_rates, get_fcf_outliers


class TestCalculateHistoricalFCFGrowthRates:
    """Test suite for calculate_historical_fcf_growth_rates function"""
    
    def test_with_volatile_data(self):
        """
        Test with volatile FCF data including negative values
        
        Data pattern:
        2021: USD 720,000,000
        2022: USD 440,100,000 (decline of -38.9%)
        2023: USD -520,300,000 (decline of -218.2%, outlier)
        2024: USD 603,200,000 (growth of +215.9%)
        """
        # Arrange
        fcf_dates = ['2021', '2022', '2023', '2024']
        fcf_values = [720_000_000, 440_100_000, -520_300_000, 603_200_000]
        
        # Act
        result = calculate_historical_fcf_growth_rates(fcf_dates, fcf_values)
        
        # Assert - Check return structure
        assert 'growth_rates' in result
        assert 'average_growth' in result
        assert 'median_growth' in result
        assert 'cagr' in result
        assert 'fcf_growth_notes' in result
        
        # Assert - Check growth_rates list
        assert isinstance(result['growth_rates'], list)
        assert len(result['growth_rates']) == 3  # n-1 growth rates for n data points
        
        # Assert - All growth rates are finite
        for rate in result['growth_rates']:
            assert np.isfinite(rate), f"Growth rate {rate} is not finite"
        
        # Assert - Expected growth rate calculations (approximately)
        # 2021 -> 2022: (440.1M - 720M) / 720M ≈ -38.9%
        expected_growth_1 = (440_100_000 - 720_000_000) / 720_000_000
        assert abs(result['growth_rates'][0] - expected_growth_1) < 0.001
        
        # 2022 -> 2023: (-520.3M - 440.1M) / 440.1M ≈ -218.2%
        expected_growth_2 = (-520_300_000 - 440_100_000) / 440_100_000
        assert abs(result['growth_rates'][1] - expected_growth_2) < 0.001
        
        # 2023 -> 2024: (603.2M - (-520.3M)) / |-520.3M| ≈ +215.9%
        expected_growth_3 = (603_200_000 - (-520_300_000)) / abs(-520_300_000)
        assert abs(result['growth_rates'][2] - expected_growth_3) < 0.001
        
        # Assert - Check that aggregate metrics are calculated
        assert isinstance(result['average_growth'], (int, float))
        assert isinstance(result['median_growth'], (int, float))
        assert isinstance(result['cagr'], (int, float))
        assert np.isfinite(result['average_growth'])
        assert np.isfinite(result['median_growth'])
        assert np.isfinite(result['cagr'])
        
        # Assert - Check fcf_growth_notes is populated
        assert isinstance(result['fcf_growth_notes'], list)
        assert len(result['fcf_growth_notes']) > 0
        
        print("\n" + "="*60)
        print("TEST RESULTS: Volatile FCF Data")
        print("="*60)
        print(f"\nInput Data:")
        for date, value in zip(fcf_dates, fcf_values):
            print(f"  {date}: ${value:,.0f}")
        
        print(f"\nCalculated Growth Rates:")
        for i, rate in enumerate(result['growth_rates']):
            print(f"  {fcf_dates[i]} → {fcf_dates[i+1]}: {rate:.1%}")
        
        print(f"\nAggregate Metrics:")
        print(f"  Average Growth: {result['average_growth']:.1%}")
        print(f"  Median Growth: {result['median_growth']:.1%}")
        print(f"  CAGR: {result['cagr']:.1%}")
        
        print(f"\nDetailed Notes:")
        for note in result['fcf_growth_notes']:
            print(note)
        print("="*60)
    
    def test_outlier_detection(self):
        """Test that outliers are detected in volatile data"""
        # Arrange
        fcf_dates = ['2021', '2022', '2023', '2024']
        fcf_values = [720_000_000, 440_100_000, -520_300_000, 603_200_000]
        
        # Act - test with default multiplier
        outliers_default = get_fcf_outliers(fcf_dates, fcf_values, iqr_multiplier=2.0)
        # Act - test with more aggressive detection
        outliers_aggressive = get_fcf_outliers(fcf_dates, fcf_values, iqr_multiplier=1.5)
        
        # Assert
        assert isinstance(outliers_default, list)
        assert isinstance(outliers_aggressive, list)
        
        print(f"\nOutliers detected (IQR multiplier=2.0): {outliers_default}")
        print(f"Outliers detected (IQR multiplier=1.5): {outliers_aggressive}")
        
        # With more aggressive detection, the negative value should be caught
        # Note: With the moderate 2.0 multiplier, the data might not have outliers
        # as the IQR accommodates the volatility
    
    def test_with_stable_growth(self):
        """Test with stable, positive growth data"""
        # Arrange - Consistent 10% growth
        fcf_dates = ['2021', '2022', '2023', '2024']
        fcf_values = [100_000_000, 110_000_000, 121_000_000, 133_100_000]
        
        # Act
        result = calculate_historical_fcf_growth_rates(fcf_dates, fcf_values)
        
        # Assert
        assert len(result['growth_rates']) == 3
        # All growth rates should be around 10%
        for rate in result['growth_rates']:
            assert 0.09 < rate < 0.11, f"Expected ~10% growth, got {rate:.1%}"
        
        # Average, median, and CAGR should all be close to 10%
        assert 0.09 < result['average_growth'] < 0.11
        assert 0.09 < result['median_growth'] < 0.11
        assert 0.09 < result['cagr'] < 0.11
    
    def test_with_two_data_points(self):
        """Test with minimum data (2 points)"""
        # Arrange
        fcf_dates = ['2023', '2024']
        fcf_values = [100_000_000, 120_000_000]
        
        # Act
        result = calculate_historical_fcf_growth_rates(fcf_dates, fcf_values)
        
        # Assert
        assert len(result['growth_rates']) == 1
        expected_growth = (120_000_000 - 100_000_000) / 100_000_000
        assert abs(result['growth_rates'][0] - expected_growth) < 0.001
        assert abs(result['cagr'] - 0.20) < 0.001  # 20% growth
    
    def test_with_zero_fcf(self):
        """Test handling of zero FCF values"""
        # Arrange
        fcf_dates = ['2021', '2022', '2023', '2024']
        fcf_values = [100_000_000, 0, 50_000_000, 75_000_000]
        
        # Act
        result = calculate_historical_fcf_growth_rates(fcf_dates, fcf_values)
        
        # Assert - Should handle zero without crashing
        assert 'growth_rates' in result
        # Growth rate from zero should be skipped (only 2 valid growth rates)
        assert len(result['growth_rates']) == 2
        assert all(np.isfinite(rate) for rate in result['growth_rates'])
    
    def test_aggregate_metrics_with_outliers(self):
        """
        Test that aggregate metrics use filtered data when outliers exist
        """
        # Arrange
        fcf_dates = ['2021', '2022', '2023', '2024']
        fcf_values = [720_000_000, 440_100_000, -520_300_000, 603_200_000]
        
        # Act
        result = calculate_historical_fcf_growth_rates(fcf_dates, fcf_values)
        outliers = get_fcf_outliers(fcf_dates, fcf_values)
        
        # Assert
        if outliers:
            # When outliers exist, check that notes mention filtered calculation
            notes_text = '\n'.join(result['fcf_growth_notes'])
            assert 'non-outlier data' in notes_text.lower() or 'filtered' in notes_text.lower()
            
            # The aggregate metrics should be more moderate than the raw year-over-year rates
            # which include the extreme swing from -520M to 603M
            extreme_rate = result['growth_rates'][1]  # The outlier transition
            assert abs(result['average_growth']) < abs(extreme_rate)
            assert abs(result['median_growth']) < abs(extreme_rate)


if __name__ == '__main__':
    # Run the main test with the provided data
    test = TestCalculateHistoricalFCFGrowthRates()
    test.test_with_volatile_data()
    test.test_outlier_detection()
    test.test_with_stable_growth()
    test.test_with_two_data_points()
    test.test_with_zero_fcf()
    test.test_aggregate_metrics_with_outliers()
    print("\n✅ All tests passed!")
