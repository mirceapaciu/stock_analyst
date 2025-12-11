# Building a DCF Model in Excel: Template Guide

## Overview

This guide provides step-by-step instructions for building a professional DCF valuation model in Excel. The template is designed to be flexible, transparent, and easy to update.

---

## Excel Model Structure

### Recommended Worksheet Organization

1. **Cover Sheet** - Summary and key outputs
2. **Assumptions** - All input variables in one place
3. **Historical Financials** - 3-5 years of historical data
4. **Income Statement** - Projected P&L
5. **Cash Flow Statement** - FCF calculations
6. **WACC Calculation** - Cost of capital
7. **DCF Valuation** - Present value calculations
8. **Sensitivity Analysis** - Scenario testing
9. **Supporting Schedules** - Detailed calculations

---

## Sheet 1: Cover Sheet

### Purpose
Executive summary with key valuation outputs and investment recommendation.

### Contents

**A. Company Overview**
- Company name
- Ticker symbol
- Industry/Sector
- Fiscal year end
- Valuation date
- Analyst name

**B. Valuation Summary**
```
Current Stock Price:           $XX.XX
Intrinsic Value per Share:     $XX.XX
Upside/(Downside):             XX.X%
Recommendation:                BUY/HOLD/SELL
```

**C. Key Metrics Dashboard**
```
Market Capitalization:         $X,XXX M
Enterprise Value:              $X,XXX M
Shares Outstanding:            XXX M
52-Week Range:                 $XX - $XX
```

**D. Valuation Outputs**
```
Sum of PV(FCF 1-5):           $X,XXX M
PV of Terminal Value:          $X,XXX M
Enterprise Value:              $X,XXX M
+ Cash:                        $XXX M
- Debt:                        ($XXX M)
Equity Value:                  $X,XXX M
÷ Shares Outstanding:          XXX M
= Value per Share:             $XX.XX
```

**E. Key Assumptions**
```
Revenue CAGR (5-year):         X.X%
Terminal Growth Rate:          X.X%
WACC:                          X.X%
```

**F. Sensitivity Analysis Summary**
Mini table showing value range under different scenarios

---

## Sheet 2: Assumptions

### Purpose
Centralize all model inputs for easy scenario testing and updates.

### Layout

#### Section A: Revenue Assumptions
```
Historical Revenue Growth:
Year -2 to Year -1:            XX.X%
Year -1 to Year 0:             XX.X%

Projected Revenue Growth:
Year 1:                        XX.X%
Year 2:                        XX.X%
Year 3:                        XX.X%
Year 4:                        XX.X%
Year 5:                        XX.X%

Revenue Drivers (optional):
- Units sold growth:           X.X%
- Price increase:              X.X%
- New product contribution:    $XXX M
```

#### Section B: Margin Assumptions
```
Operating Margin:
Historical Average:            XX.X%
Year 1:                        XX.X%
Year 2:                        XX.X%
Year 3:                        XX.X%
Year 4:                        XX.X%
Year 5:                        XX.X%

Tax Rate:                      XX.X%
```

#### Section C: Working Capital & CapEx
```
Net Working Capital:
As % of Revenue:               X.X%

Capital Expenditures:
As % of Revenue:               X.X%

Depreciation & Amortization:
As % of Revenue:               X.X%
```

#### Section D: WACC Components
```
Risk-Free Rate:                X.XX%
Beta:                          X.XX
Market Risk Premium:           X.XX%
Cost of Equity:                X.XX%

Cost of Debt (pre-tax):        X.XX%
Tax Rate:                      XX.X%
Cost of Debt (after-tax):      X.XX%

Market Value of Equity:        $X,XXX M
Market Value of Debt:          $X,XXX M
Total Value:                   $X,XXX M

Weight of Equity:              XX.X%
Weight of Debt:                XX.X%

WACC:                          X.XX%
```

#### Section E: Terminal Value
```
Terminal Growth Rate:          X.XX%
Terminal FCF Margin:           XX.X%

Alternative: Exit Multiple
Terminal EBITDA Multiple:      XX.Xx
```

#### Section F: Balance Sheet Items
```
Cash & Cash Equivalents:       $XXX M
Total Debt:                    $XXX M
Minority Interest:             $XX M
Preferred Stock:               $XX M

Shares Outstanding:            XXX M
```

### Color Coding
- **Blue cells**: User inputs
- **Black cells**: Formulas and calculations
- **Green cells**: Links from other sheets

---

## Sheet 3: Historical Financials

### Purpose
Organize historical data for trend analysis and projection basis.

### Structure

#### Table Layout (Last 3-5 Years)

| Line Item | Year -2 | Year -1 | Year 0 | CAGR | Avg % of Revenue |
|-----------|---------|---------|--------|------|------------------|
| **INCOME STATEMENT** |
| Revenue | | | | =formula | |
| Cost of Revenue | | | | | =formula |
| Gross Profit | | | | | =formula |
| Operating Expenses | | | | | =formula |
| EBIT | | | | | =formula |
| Interest Expense | | | | | |
| Pre-Tax Income | | | | | =formula |
| Taxes | | | | | =formula |
| Net Income | | | | | =formula |
| | | | | | |
| **CASH FLOW** | | | | | |
| Operating Cash Flow | | | | | =formula |
| Capital Expenditures | | | | | =formula |
| Free Cash Flow | | | | | =formula |
| | | | | | |
| **BALANCE SHEET** | | | | | |
| Cash | | | | | |
| Accounts Receivable | | | | | =formula |
| Inventory | | | | | =formula |
| Current Assets | | | | | |
| PP&E | | | | | =formula |
| Total Assets | | | | | |
| Accounts Payable | | | | | =formula |
| Current Liabilities | | | | | |
| Total Debt | | | | | |
| Shareholders' Equity | | | | | |
| | | | | | |
| **KEY METRICS** | | | | | |
| Revenue Growth | | | =formula | | |
| Gross Margin | | | =formula | =AVG | |
| Operating Margin | | | =formula | =AVG | |
| Net Margin | | | =formula | =AVG | |
| FCF Margin | | | =formula | =AVG | |
| CapEx % of Revenue | | | =formula | =AVG | |
| NWC % of Revenue | | | =formula | =AVG | |

### Key Formulas

**CAGR:**
```
=((Latest Year / Earliest Year)^(1/Number of Years)) - 1
```

**Average % of Revenue:**
```
=AVERAGE(Line Item / Revenue for each year)
```

**Growth Rate:**
```
=(Current Year / Prior Year) - 1
```

---

## Sheet 4: Income Statement Projections

### Purpose
Project future P&L based on assumptions.

### Structure

| Line Item | Year 0 (A) | Year 1 | Year 2 | Year 3 | Year 4 | Year 5 |
|-----------|------------|--------|--------|--------|--------|--------|
| **Revenue Build-up** |
| Prior Year Revenue | | =Prior | =Prior | =Prior | =Prior | =Prior |
| Growth Rate | | =Assumptions | =Assumptions | =Assumptions | =Assumptions | =Assumptions |
| **Revenue** | **Actual** | **=Formula** | **=Formula** | **=Formula** | **=Formula** | **=Formula** |
| | | | | | | |
| **Operating Expenses** |
| Cost of Revenue | | | | | | |
| % of Revenue | | =Assumptions | =Assumptions | =Assumptions | =Assumptions | =Assumptions |
| Gross Profit | | =Revenue - COGS | | | | |
| Gross Margin % | | =GP/Revenue | | | | |
| | | | | | | |
| SG&A | | | | | | |
| % of Revenue | | =Assumptions | | | | |
| R&D | | | | | | |
| % of Revenue | | =Assumptions | | | | |
| Other Operating Exp | | | | | | |
| | | | | | | |
| **EBIT** | | **=Formula** | | | | |
| EBIT Margin % | | =EBIT/Revenue | | | | |
| | | | | | | |
| Less: Taxes | | | | | | |
| Tax Rate | | =Assumptions | | | | |
| **NOPAT** | | **=EBIT*(1-Tax)** | | | | |

### Key Formulas

**Revenue Projection:**
```
=Prior Year Revenue * (1 + Growth Rate from Assumptions)
```

**Cost of Revenue:**
```
=Revenue * (COGS % from Assumptions)
```

**EBIT:**
```
=Revenue - Cost of Revenue - Operating Expenses
```

**NOPAT (Net Operating Profit After Tax):**
```
=EBIT * (1 - Tax Rate)
```

---

## Sheet 5: Free Cash Flow Calculation

### Purpose
Calculate projected free cash flows for discounting.

### Structure

| Line Item | Year 0 | Year 1 | Year 2 | Year 3 | Year 4 | Year 5 |
|-----------|--------|--------|--------|--------|--------|--------|
| **Starting Point** |
| EBIT | =Link | =Link | =Link | =Link | =Link | =Link |
| Less: Taxes | =Link | =Link | =Link | =Link | =Link | =Link |
| **NOPAT** | **=Formula** | | | | | |
| | | | | | | |
| **Adjustments** |
| + Depreciation & Amortization | | | | | | |
| D&A % of Revenue | | =Assumptions | | | | |
| | | | | | | |
| **Changes in Working Capital** |
| Net Working Capital | | | | | | |
| NWC % of Revenue | | =Assumptions | | | | |
| Change in NWC | | =Current - Prior | | | | |
| | | | | | | |
| **Capital Expenditures** |
| CapEx | | | | | | |
| CapEx % of Revenue | | =Assumptions | | | | |
| | | | | | | |
| **Free Cash Flow** | | **=Formula** | | | | |
| FCF Margin % | | =FCF/Revenue | | | | |

### Key Formulas

**Depreciation & Amortization:**
```
=Revenue * (D&A % from Assumptions)
```

**Net Working Capital:**
```
=Revenue * (NWC % from Assumptions)
```

**Change in NWC:**
```
=Current Year NWC - Prior Year NWC
```

**CapEx:**
```
=Revenue * (CapEx % from Assumptions)
```

**Free Cash Flow:**
```
=NOPAT + D&A - Change in NWC - CapEx
```

---

## Sheet 6: WACC Calculation

### Purpose
Calculate the discount rate for present value calculations.

### Structure

#### Section A: Cost of Equity (CAPM)

| Component | Value | Formula/Source |
|-----------|-------|----------------|
| Risk-Free Rate | X.XX% | =Assumptions |
| Beta | X.XX | =Assumptions |
| Market Risk Premium | X.XX% | =Assumptions |
| **Cost of Equity** | **X.XX%** | **=Rf + Beta × MRP** |

**Formula:**
```
=Risk_Free_Rate + (Beta * Market_Risk_Premium)
```

#### Section B: Cost of Debt

| Component | Value | Formula/Source |
|-----------|-------|----------------|
| Interest Expense | $XX M | =Historical Data |
| Total Debt | $XXX M | =Assumptions |
| Cost of Debt (pre-tax) | X.XX% | =Interest / Debt |
| Tax Rate | XX.X% | =Assumptions |
| **Cost of Debt (after-tax)** | **X.XX%** | **=Rd × (1 - Tax)** |

**Formula:**
```
=Cost_of_Debt_Pretax * (1 - Tax_Rate)
```

#### Section C: Capital Structure Weights

| Component | Value | Formula |
|-----------|-------|---------|
| Market Value of Equity | $X,XXX M | =Assumptions |
| Market Value of Debt | $XXX M | =Assumptions |
| **Total Value** | **$X,XXX M** | **=E + D** |
| | | |
| Weight of Equity (E/V) | XX.X% | =E / (E+D) |
| Weight of Debt (D/V) | XX.X% | =D / (E+D) |

#### Section D: WACC Calculation

| Component | Weight | Cost | Weighted Cost |
|-----------|--------|------|---------------|
| Equity | XX.X% | XX.X% | =Weight × Cost |
| Debt (after-tax) | XX.X% | X.X% | =Weight × Cost |
| **WACC** | | | **=SUM** |

**Formula:**
```
=(Weight_Equity * Cost_Equity) + (Weight_Debt * Cost_Debt_AfterTax)
```

---

## Sheet 7: DCF Valuation

### Purpose
Discount projected cash flows and calculate enterprise and equity value.

### Structure

#### Section A: Present Value of Projected Cash Flows

| Year | FCF ($M) | Discount Factor | Present Value ($M) |
|------|----------|-----------------|-------------------|
| 1 | =Link | =1/(1+WACC)^1 | =FCF × DF |
| 2 | =Link | =1/(1+WACC)^2 | =FCF × DF |
| 3 | =Link | =1/(1+WACC)^3 | =FCF × DF |
| 4 | =Link | =1/(1+WACC)^4 | =FCF × DF |
| 5 | =Link | =1/(1+WACC)^5 | =FCF × DF |
| **Total PV of Projected FCFs** | | | **=SUM** |

**Discount Factor Formula:**
```
=1 / ((1 + WACC) ^ Year_Number)
```

**Present Value Formula:**
```
=FCF * Discount_Factor
```

#### Section B: Terminal Value Calculation

**Method 1: Perpetuity Growth Model**

| Component | Value | Formula |
|-----------|-------|---------|
| Year 5 FCF | $XXX M | =Link |
| Terminal Growth Rate | X.X% | =Assumptions |
| WACC | X.X% | =Link |
| **Terminal Value** | **$X,XXX M** | **=FCF5 × (1+g) / (WACC-g)** |
| | | |
| Discount Factor (Year 5) | X.XXX | =1/(1+WACC)^5 |
| **PV of Terminal Value** | **$X,XXX M** | **=TV × DF** |

**Terminal Value Formula:**
```
=(FCF_Year5 * (1 + Terminal_Growth_Rate)) / (WACC - Terminal_Growth_Rate)
```

**Method 2: Exit Multiple (Alternative)**

| Component | Value | Formula |
|-----------|-------|---------|
| Year 5 EBITDA | $XXX M | =Link |
| Exit Multiple | XX.Xx | =Assumptions |
| **Terminal Value** | **$X,XXX M** | **=EBITDA × Multiple** |

#### Section C: Enterprise Value

| Component | Value ($M) |
|-----------|-----------|
| PV of Projected FCFs (Years 1-5) | =SUM |
| PV of Terminal Value | =Formula |
| **Enterprise Value** | **=SUM** |

#### Section D: Equity Value Bridge

| Component | Value ($M) |
|-----------|-----------|
| Enterprise Value | =Link |
| **Add:** | |
| Cash & Cash Equivalents | =Assumptions |
| **Less:** | |
| Total Debt | =Assumptions |
| Minority Interest | =Assumptions |
| Preferred Stock | =Assumptions |
| **Equity Value** | **=Formula** |

**Equity Value Formula:**
```
=Enterprise_Value + Cash - Debt - Minority_Interest - Preferred_Stock
```

#### Section E: Value Per Share

| Component | Value |
|-----------|-------|
| Equity Value | $X,XXX M |
| Shares Outstanding | XXX M |
| **Intrinsic Value per Share** | **$XX.XX** |
| | |
| Current Market Price | $XX.XX |
| **Upside/(Downside)** | **XX.X%** |

**Value Per Share Formula:**
```
=Equity_Value / Shares_Outstanding
```

**Upside/Downside Formula:**
```
=(Intrinsic_Value - Current_Price) / Current_Price
```

---

## Sheet 8: Sensitivity Analysis

### Purpose
Test how changes in key assumptions affect valuation.

### Table 1: WACC vs. Terminal Growth Rate

|  | g=1.5% | g=2.0% | g=2.5% | g=3.0% | g=3.5% |
|---------|--------|--------|--------|--------|--------|
| WACC=8.0% | | | | | |
| WACC=9.0% | | | | | |
| WACC=10.0% | | | | | |
| WACC=11.0% | | | | | |
| WACC=12.0% | | | | | |

**Setup:**
1. Create row headers with WACC values (±2% from base)
2. Create column headers with terminal growth rates (±1% from base)
3. Use Data Table feature:
   - Row input cell: WACC in Assumptions
   - Column input cell: Terminal growth rate in Assumptions
4. Formula in top-left cell: =Value_per_Share

**Excel Formula for Data Table:**
- Select entire table including headers
- Go to Data → What-If Analysis → Data Table
- Row input cell: Link to WACC assumption
- Column input cell: Link to terminal growth rate assumption

### Table 2: Revenue Growth vs. Operating Margin

|  | Margin=18% | Margin=20% | Margin=22% | Margin=24% | Margin=26% |
|---------|--------|--------|--------|--------|--------|
| Growth=8% | | | | | |
| Growth=10% | | | | | |
| Growth=12% | | | | | |
| Growth=14% | | | | | |
| Growth=16% | | | | | |

### Scenario Analysis Table

| Scenario | Revenue CAGR | Op Margin | WACC | Terminal g | Value/Share | vs. Base |
|----------|--------------|-----------|------|------------|-------------|----------|
| Bear Case | | | | | | |
| Base Case | | | | | | |
| Bull Case | | | | | | |

**Conditional Formatting:**
- Green shading for values > current price
- Red shading for values < current price
- Color scale for gradient visualization

---

## Sheet 9: Supporting Schedules

### Purpose
Detailed calculations and reconciliations.

### Schedule A: Revenue Build-up (Detailed)

For companies with multiple segments or products:

| Product/Segment | Year 0 | Year 1 | Year 2 | Year 3 | Year 4 | Year 5 |
|-----------------|--------|--------|--------|--------|--------|--------|
| **Product A** | | | | | | |
| Units | | | | | | |
| Price per Unit | | | | | | |
| Revenue | | | | | | |
| | | | | | | |
| **Product B** | | | | | | |
| Units | | | | | | |
| Price per Unit | | | | | | |
| Revenue | | | | | | |
| | | | | | | |
| **Total Revenue** | | | | | | |

### Schedule B: Working Capital Detail

| Component | Year 0 | Year 1 | Year 2 | Year 3 | Year 4 | Year 5 |
|-----------|--------|--------|--------|--------|--------|--------|
| Accounts Receivable | | | | | | |
| Days Sales Outstanding | | | | | | |
| | | | | | | |
| Inventory | | | | | | |
| Days Inventory Outstanding | | | | | | |
| | | | | | | |
| Accounts Payable | | | | | | |
| Days Payable Outstanding | | | | | | |
| | | | | | | |
| **Net Working Capital** | | | | | | |
| Change in NWC | | | | | | |

**Days Sales Outstanding (DSO):**
```
=(Accounts Receivable / Revenue) * 365
```

### Schedule C: Debt Schedule

| Component | Year 0 | Year 1 | Year 2 | Year 3 | Year 4 | Year 5 |
|-----------|--------|--------|--------|--------|--------|--------|
| Beginning Debt | | | | | | |
| Debt Issuance | | | | | | |
| Debt Repayment | | | | | | |
| **Ending Debt** | | | | | | |
| | | | | | | |
| Interest Expense | | | | | | |
| Average Interest Rate | | | | | | |

---

## Best Practices for Excel DCF Models

### 1. Formatting

**Color Coding:**
- **Blue**: Hard-coded inputs (user enters data)
- **Black**: Formulas (calculated values)
- **Green**: Links from other sheets
- **Red**: Checks and error flags

**Cell Formatting:**
- Currency: $#,##0 or $#,##0.0 for millions
- Percentages: 0.0%
- Use consistent decimal places
- Bold headers and totals

**Borders and Shading:**
- Use borders to separate sections
- Light shading for input areas
- Double underline for totals

### 2. Formula Best Practices

**Use Named Ranges:**
```
Instead of: =B15*(1-B20)
Use: =EBIT*(1-Tax_Rate)
```

**Avoid Hard-Coding:**
```
Bad: =Revenue * 0.25
Good: =Revenue * Operating_Margin
```

**Use Consistent References:**
- Absolute references ($) for assumption links
- Relative references for formulas that copy across

**Error Checking:**
```
=IFERROR(formula, 0)
=IF(denominator=0, 0, numerator/denominator)
```

### 3. Model Integrity

**Build in Checks:**
- Balance sheet check: Assets = Liabilities + Equity
- Cash flow check: Beginning + Changes = Ending
- Circular reference flags

**Example Check:**
```
Balance Check: =IF(ABS(Assets - (Liabilities + Equity)) < 0.01, "OK", "ERROR")
```

**Audit Trail:**
- Version control in file name
- Change log on cover sheet
- Comments for complex formulas

### 4. Flexibility

**Scenario Manager:**
- Create named scenarios (Bull, Base, Bear)
- Use Excel's Scenario Manager tool
- Quick switching between assumptions

**Toggle Switches:**
- Use data validation dropdowns
- Example: Choose between perpetuity growth or exit multiple
```
=IF(Terminal_Method="Perpetuity", Formula1, Formula2)
```

### 5. Documentation

**Assumptions Sheet Notes:**
- Source for each input
- Date of data
- Rationale for key assumptions

**Formula Comments:**
- Right-click cell → Insert Comment
- Explain complex calculations
- Note any special considerations

---

## Common Excel Formulas for DCF

### Financial Functions

**NPV (Net Present Value):**
```
=NPV(WACC, FCF_Year1:FCF_Year5)
```

**XNPV (for non-annual periods):**
```
=XNPV(WACC, Cash_Flows, Dates)
```

**IRR (Internal Rate of Return):**
```
=IRR(Cash_Flow_Range)
```

**XIRR (for non-annual periods):**
```
=XIRR(Cash_Flows, Dates)
```

### Growth Calculations

**CAGR:**
```
=((Ending_Value / Beginning_Value) ^ (1 / Number_of_Years)) - 1
```

**Year-over-Year Growth:**
```
=(Current_Year / Prior_Year) - 1
```

### Statistical Functions

**Average:**
```
=AVERAGE(Range)
```

**Median:**
```
=MEDIAN(Range)
```

**Standard Deviation:**
```
=STDEV.S(Range)
```

### Lookup Functions

**VLOOKUP (for comparable company data):**
```
=VLOOKUP(Lookup_Value, Table_Range, Column_Number, FALSE)
```

**INDEX-MATCH (more flexible):**
```
=INDEX(Return_Range, MATCH(Lookup_Value, Lookup_Range, 0))
```

---

## Keyboard Shortcuts for Efficiency

### Essential Shortcuts

- **Ctrl + ;** : Insert current date
- **Ctrl + Shift + ;** : Insert current time
- **F4** : Toggle absolute/relative references
- **Ctrl + `** : Show formulas
- **Ctrl + [** : Go to precedent cells
- **Ctrl + ]** : Go to dependent cells
- **Alt + =** : AutoSum
- **F9** : Calculate all worksheets
- **Shift + F9** : Calculate active worksheet
- **Ctrl + Shift + $** : Format as currency
- **Ctrl + Shift + %** : Format as percentage

### Navigation

- **Ctrl + Home** : Go to cell A1
- **Ctrl + End** : Go to last used cell
- **Ctrl + Arrow Key** : Jump to edge of data region
- **Ctrl + Page Up/Down** : Switch between worksheets

---

## Quality Control Checklist

Before finalizing your DCF model:

- [ ] All inputs are in the Assumptions sheet
- [ ] Formulas reference assumptions (no hard-coding)
- [ ] Historical data is accurate and sourced
- [ ] Projections are reasonable and documented
- [ ] WACC calculation is correct
- [ ] Terminal value formula is appropriate
- [ ] All cash flows are properly discounted
- [ ] Equity value bridge is complete
- [ ] Sensitivity analysis is functional
- [ ] All sheets are properly labeled
- [ ] Model is free of circular references (unless intentional)
- [ ] Error checks pass
- [ ] Model recalculates correctly when inputs change
- [ ] Documentation is complete
- [ ] File is saved with clear version naming

---

## Template Download and Usage

### Using the Template

1. **Input Historical Data**: Start with Sheet 3
2. **Set Assumptions**: Fill out Sheet 2 with your projections
3. **Review Calculations**: Check Sheets 4-7 auto-populate correctly
4. **Run Sensitivity**: Use Sheet 8 to test scenarios
5. **Review Summary**: Check Sheet 1 for final outputs

### Customization Tips

- Add/remove projection years as needed
- Modify expense categories to match company
- Add detailed schedules for complex businesses
- Customize sensitivity tables for key variables
- Adjust formatting to match your preferences

---

## Conclusion

A well-built Excel DCF model is:
- **Transparent**: Easy to follow and audit
- **Flexible**: Quick to update and test scenarios
- **Robust**: Free of errors and circular references
- **Professional**: Well-formatted and documented

Invest time upfront in building a solid template, and you'll save hours on future valuations.

---

**Next Steps:**
1. Download or build the template following this guide
2. Practice with a real company (start with a simple business)
3. Refine your template based on your workflow
4. Build a library of templates for different industries

---

*This guide is designed to complement the main DCF Valuation Guide. Use both documents together for comprehensive understanding.*
