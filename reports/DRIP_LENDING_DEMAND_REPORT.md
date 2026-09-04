# A Narrower Incentive Test for Morpho

## Executive Summary

The useful decision is not whether to label DRIP a success or failure. It is whether another program should buy the same kind of activity. The accepted 45-market panel shows a large difference between campaign-end scale and longer-lived loan balances: baseline-adjusted debt persistence at +180 is 7.7% for USDC and 11.3% for USD₮0. This supports a more selective next experiment, not an unchanged broad repeat.

The full balances observed at +180—5.65M USDC and 4.14M USD₮0—include the baseline and all subsequent onchain changes. They are not debt proven to have been generated or preserved by DRIP. No untreated comparison group or exact reward-recipient attribution is available.

## Evaluate taper persistence, not just the campaign maximum

The primary calculation asks how much of the positive uplift present at campaign end remained: `(post − baseline) / (end − baseline)`. The baseline is the mean of 56 aligned closes. The peak sensitivity answers a different question and yields lower +180 values: 3.0% and 7.0% for USDC and USD₮0. Both are useful; switching between them after seeing the result is not.

The decline was not immediate in every asset group. USD₮0 was slightly above campaign end at +30 before falling substantially by +90. This makes a +30-only evaluation inadequate for judging durable scale. [Evidence and exact levels](../data/morpho_phase7_portfolio_retained_uplift.csv)

## Participation and balance economics can diverge

Material borrower count retained 63.8% of its campaign-end uplift, much more than either debt-balance series. Counts describe activity breadth but not the amount, revenue or risk of lending. Even the one-token threshold is a modest materiality rule, not a claim that every remaining position is economically important.

Interest accrued during the campaign is separately visible in the debt ledger. It increases outstanding assets without creating new borrower shares. Gross borrow and repay flows can also represent refinancing and repeated leverage. Neither outstanding debt nor gross flow alone is a complete demand measure. [Flow evidence](../data/morpho_phase7_period_flows.csv)

## Use market differences as hypotheses for the next design

The precommitted examples range from post-campaign expansion in the early shared USDC/weETH market to near-total balance runoff in the dedicated syrupUSDC and late USD₮0 examples. The surviving USDC balance also became more concentrated across markets. These observations justify market-specific hypotheses and monitoring, but not a retrospective claim that a particular incentive allocation was optimal. Shared budgets and direct-vault incentives cannot be defensibly assigned to individual markets here.

## Recommended next test

1. Pre-register a smaller market population and separate native-token balance targets from material-borrower targets.
2. Stage rewards or taper them with a holdback tied to precommitted +30 and +90 persistence measures; retain a longer post-period check.
3. Collect recipient exposure, rate/competing-incentive context and a credible comparison group before claiming incremental impact or cost effectiveness.

## Questions that remain open

Would these balances have existed without DRIP? Did principal-token maturity or refinancing move activity elsewhere? Were remaining positions profitable or risk-efficient? This dataset cannot settle those questions. Price changes, market conditions, organic adoption, migrations and other incentives remain plausible explanations.

This memo has high descriptive confidence in the accepted onchain measurements, moderate confidence as design guidance, and low causal confidence. It excludes wallet cohorts, wallet concentration, a price/USD layer and realized recipient attribution. Non-zero fee-share minting is implemented but empirically unexercised; bad debt is empirically covered. [Provenance](../docs/HEADLINE_PROVENANCE.md) · [Limitations](../docs/RELEASE_LIMITATIONS.md) · [Independent reviewer brief](../docs/REVIEWER_BRIEF.md)
