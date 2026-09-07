# Did DRIP Create Sticky Lending Demand?

*Morpho on Arbitrum, 180 days later*

An onchain study of borrowing, borrower activity, and market persistence across 45 DRIP-eligible Morpho markets.

## Executive Summary

**Most campaign-end borrowing uplift had unwound by day 180.** The primary retained-uplift ratio was **7.7% for USDC** and **11.3% for USD₮0**.

**Borrower participation was more persistent than borrowing balances.** Material active-borrower uplift retained **63.8%**, although the count fell from 765 at campaign end to 495 at day 180.

**Outcomes varied sharply across markets.** The remaining USDC debt became increasingly concentrated, so a future program should test narrower market selection and staged incentives rather than repeat the broad design unchanged.

| Metric | Retained uplift at +180 |
|---|---:|
| Outstanding borrowing — USDC | **7.7%** |
| Outstanding borrowing — USD₮0 | **11.3%** |
| Material active-borrower count | **63.8%** |

Retained uplift is `(post-period level − baseline) / (campaign-end level − baseline)` and is reported only when the campaign-end level is above baseline.

This is an observational measure of persistence, not evidence that DRIP caused the retained demand. The borrower count is cross-sectional and does not measure retention of the same wallet cohort.

[Findings](#most-campaign-end-borrowing-uplift-had-unwound-by-day-180) · [Implications](#implications-for-future-incentive-programs) · [Methodology](#scope-and-methodology) · [Reproducibility](#reproducibility-validation-and-limitations)

## Most campaign-end borrowing uplift had unwound by day 180

The primary comparison uses the uplift at campaign end as its denominator. USDC retained uplift fell from 67.9% at +30 to 19.8% at +90 and 7.7% at +180. USD₮0 moved from 101.0% to 38.3% and 11.3%. A value above 100% means that borrowing rose further above baseline after campaign end; it is not a causal claim.

### Retained uplift and campaign-peak sensitivity

![Primary retained uplift and campaign-peak sensitivity](figures/phase7_retained_uplift.png)

Campaign peaks were much higher than campaign-end levels. At +180, peak-relative retained uplift was only 3.0% for USDC and 7.0% for USD₮0. Campaign end remains the primary denominator because it measures persistence from the point incentives stopped; the peak comparison is a sensitivity showing how much of the highest observed uplift survived. Connecting lines between post checkpoints are visual guides, not observed daily post-period trajectories. [Reviewed portfolio data](data/morpho_phase7_portfolio_retained_uplift.csv)

### Outstanding borrowed assets at exact checkpoints

![Outstanding borrowed assets at exact checkpoints](figures/phase7_borrowed_assets_checkpoints.png)

The remaining uplift was small even though outstanding borrowing remained above baseline. At +180, the full balances were **5.65M USDC** and **4.14M USD₮0**. These are total outstanding balances, not amounts created or preserved by DRIP.

## Debt changes reflect borrowing, repayments, and accrued interest

Outstanding debt does not change through borrowing and repayment alone. It also reflects accrued interest, liquidation repayment, and bad debt.

### Outstanding-debt flow decomposition

![Outstanding-debt flow decomposition](figures/phase7_debt_flow_decomposition.png)

During the incentive interval, accrued interest contributed 5.20M USDC and 0.23M USD₮0 to outstanding debt. New borrowing continued after the campaign, but repayment and liquidation outflows were larger. The accounting identity reconciles these components with zero residual. Gross borrowing can include refinancing or repeated leverage, so it should not be read as unique end-user demand. [Reviewed flow data](data/morpho_phase7_period_flows.csv)

## Borrower participation persisted more than borrowing balances

A material active borrower has positive borrow shares and at least one native loan token of debt after Morpho's round-up conversion.

### Cross-sectional active borrowers and dust sensitivity

![Cross-sectional active borrowers and dust sensitivity](figures/phase7_active_borrowers.png)

Material active-borrower counts declined from 765 at campaign end to 495 at day 180, compared with a baseline mean of 19.3. This equals **63.8% retained uplift**, much higher than the balance-based ratios. The result means that participation was broader than the remaining balance size; it does not show retention of the same borrowers. Post-period values are isolated +30, +90, and +180 observations rather than a daily trajectory.

## Market outcomes diverged sharply

Aggregate results hide substantial differences between markets. The three examples below were selected before their outcomes were analyzed.

### Borrowed assets and collateral for three precommitted archetypes

![Borrowed assets and collateral for three precommitted archetypes](figures/phase7_archetype_borrowed_assets.png)

The early shared USDC/weETH market expanded after campaign end, retaining 5.94× its campaign-end uplift. The dedicated syrupUSDC/USDC and late USD₮0/syrupUSDC examples retained only 0.45% and 0.26% of borrowed-asset uplift. Collateral is shown in each token's native unit and panel scales differ, so levels should not be compared across panels. These examples demonstrate heterogeneity, not treatment effects. [Explore all 45 markets](data/morpho_phase7_market_retained_uplift.csv)

## Remaining borrowing became more concentrated

### Market concentration at campaign end and day 180

![Market concentration at campaign end and P180](figures/phase7_market_concentration.png)

The three largest USDC markets accounted for 65.8% of outstanding USDC debt at campaign end and 91.2% at +180. The portfolio result therefore became increasingly dependent on a small number of markets. This is concentration across markets, not across wallets or people. Shared campaign pools and direct-vault incentives are not allocated to individual markets in this analysis. [Reviewed concentration data](data/morpho_phase7_market_concentration.csv)

## Implications for future incentive programs

A follow-up program should be structured as a smaller, measurable pilot:

- Focus on markets that showed durable demand.
- Set both borrowed-balance and material-borrower targets for +30 and +90 days.
- Taper incentives gradually and tie part of the budget to the intended retention measure.

Balances and meaningful participation should be monitored together because high wallet counts can coexist with very small loan balances. This study cannot estimate a precise subsidy allocation or cost per retained dollar.

A causal evaluation would require recipient-level incentive exposure, other incentive and rate context, and a defensible comparison group. Maturities, migrations, collateral prices, organic adoption, and broader lending conditions remain alternative explanations.

## Scope and methodology

| Element | Definition |
|---|---|
| Scope | Arbitrum One; fixed panel of 45 ever-eligible Morpho markets |
| Loan assets | 32 USDC markets and 13 USD₮0 markets, analyzed separately by exact token address |
| Baseline | Mean of 56 campaign-hour-aligned daily closes before September 3, 2025 at 13:00 UTC |
| Campaign window | September 3, 2025 at 13:00 UTC to February 18, 2026 at 13:00 UTC; half-open interval |
| Post checkpoints | +30, +90, and +180 at exactly 13:00 UTC |
| Primary metric | Retained uplift relative to campaign-end uplift, applicable only when campaign end is above baseline |
| Material borrower | Positive borrow shares and at least one native loan token of debt |
| Data model | Market × UTC day, with exact checkpoint reconstruction from ordered events |

Balances are never combined into a single USD total, and heterogeneous collateral assets remain in their native units. For market-level borrowed assets, the retained-uplift ratio is applicable to 42 of 45 markets; levels and deltas remain available for all markets.

[Frozen metrics v1.0](docs/METRICS.md) · [Sources](docs/SOURCES.md) · [Headline provenance](docs/HEADLINE_PROVENANCE.md)

## Reproducibility, validation, and limitations

Three reproduction boundaries are documented:

- **From the published CSVs:** reproduce all six figures with the documented runtime and fonts, without a database or network access.
- **From the accepted database:** reproduce five analytical CSVs and all six figures; this route requires the external accepted database and metadata snapshot.
- **From raw events:** the package is not self-contained for raw reconstruction. A full raw rebuild was not performed, and the checksum-matched source bundle is not available for public download.

The accepted source coverage contains 1,231,462 unique scoped logs in 3,157 immutable shards. The production layer contains 18,225 unique market-day rows. Phase 7 reconciled 10,215 wallet-share/market checkpoints, preserved exact accounting, and separated interest from flows. Independent review found no numerical discrepancies; the CSV-only route reproduced six of six PNGs byte-for-byte.

Technical and descriptive confidence is high, decision confidence is moderate, and causal confidence is low. Wallets are not people or proven reward recipients. There is no price layer, wallet-cohort analysis, or wallet-concentration analysis. Non-zero fee shares remain empirically unexercised; three non-zero bad-debt events were covered.

[Reproduction guide](docs/REPRODUCTION.md) · [Full limitations](docs/RELEASE_LIMITATIONS.md) · [Independent review](reviews/public/README.md) · [Release QA](docs/RELEASE_CANDIDATE_QA.md)

| I want to… | Start here |
|---|---|
| Read the decision memo | [Decision report](reports/DRIP_LENDING_DEMAND_REPORT.md) |
| Check metric definitions | [Metrics v1.0](docs/METRICS.md) |
| Trace headline numbers | [Headline provenance](docs/HEADLINE_PROVENANCE.md) |
| Reproduce the outputs | [Reproduction guide](docs/REPRODUCTION.md) |
| Inspect implementation | [SQL](sql/) and [scripts](scripts/) |
| Review caveats and checks | [Limitations](docs/RELEASE_LIMITATIONS.md) and [independent review](reviews/public/README.md) |

**Version:** reviewed v1.0 analysis. Metrics and figures are frozen; this README revision changes presentation only.

This independent pseudonymous project is not affiliated with Arbitrum, DRIP, or Morpho.
