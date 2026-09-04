# Project brief

## Working title

**Did DRIP Create Sticky Lending Demand? Morpho on Arbitrum, 180 Days Later**

## Decision to support

Determine whether future DRIP incentives should repeat the same Morpho markets and taper, narrow the eligible set, redesign the mechanism, or stop subsidizing segments that show rapid post-incentive decay.

## Core research question

After DRIP ended on February 18, 2026, what share of the uplift in borrowed assets, collateral, and active borrowers remained at +30, +90, and +180 days, and which markets retained best?

## Unit of analysis

1. Primary: one row per Morpho market per UTC day.
2. Secondary: one row per wallet, market, and checkpoint after the market-level state is validated.

## Comparison design

- Pre-period: eight weeks before the campaign start.
- Incentive period: September 3, 2025 through February 18, 2026, subject to exact timestamp verification.
- Post-period checkpoints: +30, +90, and +180 days.
- Primary comparison: campaign-end level versus each post checkpoint, adjusted for the pre-period baseline.
- Sensitivity: campaign peak versus each post checkpoint.

## Reader promise

The study will not merely plot TVL. It will separate borrowed demand, supplied assets or collateral, wallet activity, market concentration, and cohort retention, then state what cannot be attributed to DRIP.

## Material confounders

- ARB and asset price changes
- broader lending-market conditions
- interest-rate and rewards changes outside DRIP
- market migrations or parameter changes
- oracle, LLTV, or interest-rate-model changes
- liquidations and refinancing
- wallet splitting, smart accounts, and contracts
- inability to identify exact reward receipt without Merkl records

## Completion standard

The case is complete only when source dates, definitions, reproducible SQL, QA evidence, manual samples, limitations, charts, and a decision-oriented conclusion are all present.
