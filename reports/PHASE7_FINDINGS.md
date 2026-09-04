# Did DRIP Create Sticky Lending Demand? Morpho on Arbitrum, 180 Days Later

## Answer in one sentence

The accepted onchain panel shows that some campaign-associated borrowing remained 180 days after incentives ended, but most of the campaign-end balance uplift had unwound: **7.7% for USDC markets and 11.3% for USD₮0 markets**. This is observational before/after evidence, not proof that DRIP caused either the growth or the retained balance.

## Decision readout

The fixed population contains all 45 accepted DRIP-eligible Morpho markets: 32 USDC-loan markets and 13 USD₮0-loan markets. USDC and USD₮0 are reported separately by exact token address and are never added together.

| Loan asset | Baseline mean `B` | Campaign end `E` | Campaign peak `Q` | `P30` | `P90` | `P180` | Primary retained uplift at `P180` | Peak sensitivity at `P180` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| USDC | 244,010 | 70,647,245 | 180,871,350 | 48,068,436 | 14,172,734 | 5,645,593 | **7.7%** | 3.0% |
| USD₮0 | 17 | 36,750,499 | 59,368,918 | 37,113,026 | 14,081,479 | 4,135,334 | **11.3%** | 7.0% |

The primary ratio is `(P_k - B) / (E - B)`, only when `E - B > 0`. Campaign peak is a separate sensitivity and never replaces the frozen campaign-end denominator. USDC retained 67.9%, 19.8%, and 7.7% at +30, +90, and +180. USD₮0 retained 101.0%, 38.3%, and 11.3%. The +30 USD₮0 value slightly above 100% means its checkpoint balance exceeded campaign end; it is not clamped.

![Borrowed assets at exact checkpoints](../figures/phase7_borrowed_assets_checkpoints.png)

![Primary retained uplift and peak sensitivity](../figures/phase7_retained_uplift.png)

## Balance growth is not the same as new borrowing demand

Outstanding debt includes both borrower flows and interest accrued on existing debt. During the incentive interval, USDC debt rose by 69.61 million native tokens, of which 5.20 million came from interest accrual; USD₮0 debt rose by 36.75 million, of which 0.23 million came from interest. Interest therefore accounts for about 7.5% and 0.6% of the respective observed incentive-period debt increases. It must not be labeled new borrowing.

Gross borrowing continued after campaign end, but repayments and liquidations were larger. Over the 180-day post interval, USDC recorded 376.55 million borrowed versus 441.12 million repaid plus 0.88 million repaid in liquidation; USD₮0 recorded 101.08 million borrowed versus 133.97 million repaid plus 0.03 million repaid in liquidation. Interest partially offset those outflows, while the exact replay reconciles the closing debt with zero residual.

![Debt-flow decomposition](../figures/phase7_debt_flow_decomposition.png)

## Participation remained broader than balances

The cross-sectional number of material active borrowers—distinct wallets with positive borrow shares and at least one native loan token of rounded-up debt—was 765 at campaign end and 495 at +180. Against the 56-checkpoint baseline mean of 19.3, this represents 63.8% retained uplift at +180. The campaign peak was 3,132 wallets, so the peak-based sensitivity is only 15.3%.

The shares-only dust sensitivity is materially higher: 1,416 wallets at campaign end and 1,172 at +180, for 82.5% primary retained uplift. This gap is why the one-token materiality threshold is primary. These are cross-sectional checkpoint counts, not wallet cohorts, retention cohorts, people, or verified reward recipients.

![Active borrowers](../figures/phase7_active_borrowers.png)

## Heterogeneity matters

At market level, campaign-end uplift was positive and therefore ratio-applicable for 42 of 45 borrowed-asset series, 45 of 45 supply series, 44 of 45 collateral series, and 38 of 45 active-borrower series. Non-applicable rows retain their levels and absolute deltas; their ratios are not forced to zero.

Among the three archetypes frozen before outcomes were calculated:

- The early shared USDC / weETH market had 1.41 million USDC borrowed at +180 and retained **5.94×** its campaign-end uplift; collateral retained **6.07×**. This market expanded after incentives rather than merely preserving its end balance.
- The dedicated syrupUSDC / USDC market retained only **0.45%** of borrowed-asset uplift and **0.50%** of collateral uplift, despite 91.4% retained uplift in its cross-sectional material active-borrower count.
- The late USD₮0 / syrupUSDC market retained **0.26%** of borrowed-asset uplift, **0.25%** of collateral uplift, and 44.4% of active-borrower uplift.

![Three frozen archetypes](../figures/phase7_archetype_borrowed_assets.png)

Surviving USDC debt became more concentrated: the largest market's share rose from 40.0% at campaign end to 45.5% at +180, and the top three rose from 65.8% to 91.2%. USD₮0 concentration rotated in the opposite direction: top-one share fell from 49.5% to 37.9%, while the identity of the leading market changed. No shared or direct-vault incentive budget is allocated to these markets.

![Market concentration](../figures/phase7_market_concentration.png)

## Recommendation

Do not repeat the broad program unchanged. A future program should use a narrower, market-specific design with a staged taper or a retention-conditioned holdback. Favor markets that preserve material borrowed balances at +30 and +90 without relying on dust positions; reduce or end support for markets whose balances collapse even when wallet counts remain elevated. Pre-register balance and material-borrower thresholds, retain the campaign-end denominator, and collect exact recipient exposure plus a credible comparison group if the governance question is causal effectiveness rather than descriptive persistence.

## Confidence and limitations

- **Technical/descriptive confidence: high.** Exact block boundaries, canonical event ordering, Morpho rounding, immutable-source reconciliation, 45-market coverage, and checkpoint wallet-share reconciliation all pass.
- **Decision-usefulness confidence: moderate.** The result clearly distinguishes persistent from transient market patterns, but it does not include prices, risk-adjusted economics, or market-attributed shared budgets.
- **Causal confidence: low.** The design has no untreated counterfactual and does not identify reward recipients. Market conditions, rates, collateral prices, competing protocols, maturities, migrations, and organic adoption may explain part of the change.

Further limitations: wallet cohorts and wallet concentration are intentionally absent; collateral is never aggregated across heterogeneous token addresses; USDC is never added to USD₮0; non-zero `feeShares` was implemented but not empirically exercised, while three bad-debt events were exercised and reconciled.

## Reproducibility

The analysis is produced by [`scripts/analyze_phase7_metrics.py`](../scripts/analyze_phase7_metrics.py). Chart-ready tables are [`morpho_phase7_market_retained_uplift.csv`](../data/morpho_phase7_market_retained_uplift.csv), [`morpho_phase7_portfolio_retained_uplift.csv`](../data/morpho_phase7_portfolio_retained_uplift.csv), [`morpho_phase7_checkpoint_series.csv`](../data/morpho_phase7_checkpoint_series.csv), [`morpho_phase7_period_flows.csv`](../data/morpho_phase7_period_flows.csv), and [`morpho_phase7_market_concentration.csv`](../data/morpho_phase7_market_concentration.csv). Full technical checks are in [`docs/PHASE7_ANALYSIS_QA.md`](../docs/PHASE7_ANALYSIS_QA.md).
