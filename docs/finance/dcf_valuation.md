# Valuating MSFT

Scenario	WACC	Terminal Growth	Fair Value	In Analyst Range?
Conservative	10.6%	3.0%	$159	❌ Too low
Current Default	8.6%	4.5%	$286	❌ Below range
Low WACC	7.8%	4.5%	$355	✅ YES!
Optimistic	7.8%	5.0%	$411	✅ YES!
Very Optimistic	7.8%	5.0% + Higher Growth	$449	✅ YES!
Analyst Range: $343 - $467 ✅

# Terminal Growth Rate
The terminal growth rate represents the perpetual growth rate of free cash flows beyond the forecast period. Here are the main methods to calculate/estimate it:

1. GDP Growth Rate Method (Most Common)

Use the long-term GDP growth rate of the country where the company operates:
- US GDP long-term growth: ~2-3%
- Global GDP growth: ~3-4%
- Developed markets: 2-3%
- Emerging markets: 4-6%
- For MSFT (US-based): 2.5-3% is reasonable

2. Inflation Rate Method

Use the long-term inflation target:

- US Fed inflation target: 2%
- Plus real GDP growth: ~1-2%
- Total: 3-4%

3. Industry Growth Method

Use the expected long-term growth rate of the industry:
- Mature tech: 3-5%
- High-growth tech: 5-7%
- Stable industries: 2-3%

4. Rule of Thumb

Never exceed the long-term GDP growth rate by much

- Typical range: 2-5%
- Conservative: 2-3%
- Aggressive: 4-5%

Important Constraints:
⚠️ Terminal growth MUST be < WACC (otherwise terminal value = infinity)

If WACC = 8.6%, terminal growth must be < 8.6%
Typical spread: WACC - Terminal Growth ≥ 3-4%

## Typical values
- Conservative: terminal_growth_rate = 0.03   # 3%
- Moderate: terminal_growth_rate = 0.04   # 4%
- Optimistic (tech companies): terminal_growth_rate = 0.05   # 5%
