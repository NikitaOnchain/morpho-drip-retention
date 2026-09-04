# Metric definitions

Status: **frozen for v1 — COMPLETE, accepted 2026-09-01**.

Version: **v1.0**. The user accepted the complete definition contract after correctly explaining the retained-uplift numerator, denominator, applicability rule and peak sensitivity. Any future change requires a new versioned decision; v1.0 must not be silently rewritten.

These definitions measure persistence of onchain demand in the 45 markets that were eligible in at least one accepted DRIP epoch. They do not identify reward recipients and do not establish that DRIP caused an observed change.

## 1. Time and ordering contract

All timestamps are UTC. Intervals are half-open: the start is included and the end is excluded.

| Label | Exact interval or checkpoint | Length / role |
|---|---|---|
| Baseline | `[2025-07-09T13:00:00Z, 2025-09-03T13:00:00Z)` | 56 days |
| Incentive | `[2025-09-03T13:00:00Z, 2026-02-18T13:00:00Z)` | 168 days / 12 accepted epochs |
| Post, full analytical window | `[2026-02-18T13:00:00Z, 2026-08-17T13:00:00Z)` | 180 days |
| Post band 1 | `[2026-02-18T13:00:00Z, 2026-03-20T13:00:00Z)` | campaign end to +30 |
| Post band 2 | `[2026-03-20T13:00:00Z, 2026-05-19T13:00:00Z)` | +30 to +90 |
| Post band 3 | `[2026-05-19T13:00:00Z, 2026-08-17T13:00:00Z)` | +90 to +180 |
| Campaign-end checkpoint | `2026-02-18T13:00:00Z` | primary denominator checkpoint |
| +30 checkpoint | `2026-03-20T13:00:00Z` | exact 30-day offset |
| +90 checkpoint | `2026-05-19T13:00:00Z` | exact 90-day offset |
| +180 checkpoint | `2026-08-17T13:00:00Z` | exact 180-day offset |

The immutable Phase 2 source continues through `2026-08-18T00:00:00Z`. The final eleven hours are source/QA buffer, not part of the primary post interval.

Define `M(t)` as the state after every accepted log whose block timestamp is strictly less than `t`, and before every log whose block timestamp is greater than or equal to `t`. Therefore, a block stamped exactly at campaign end belongs to the post period, not the incentive period. Within the included history, replay order remains `(block_number, transaction_index, log_index)`.

The reporting table remains `market_id × UTC calendar day`, but exact 13:00 checkpoints must be derived from ordered replay. A midnight daily close is not a substitute for an exact campaign boundary. State changes only through the accepted Morpho events; v1 does not add synthetic interest between `AccrueInterest` events.

## 2. Fixed population and state measures

The primary panel is the fixed set of all 45 exact market IDs that were eligible in at least one accepted epoch. Supply/borrow side and eligible epochs remain attributes for interpretation; they do not change the panel between checkpoints.

- **Borrowed assets:** `totalBorrowAssets` for a market, in the native loan token.
- **Supplied assets:** `totalSupplyAssets` for a market, in the native loan token. This is a diagnostic rather than a headline retained-demand metric.
- **Collateral:** replayed outstanding collateral for a market, in the native collateral token.
- **Active borrowers:** distinct lowercase wallet addresses with at least one material positive wallet-market borrow position at the checkpoint.

Amounts use exact token addresses and validated ERC-20 decimals. Values with the same symbol but different addresses are not silently combined.

### Material positive borrow position

A wallet-market position is positive for the primary active-borrower metric when:

1. `borrowShares > 0`; and
2. assets obtained from those shares with Morpho's borrow-asset round-up rule are at least `1.0` native loan token (`10^loan_decimals` base units).

A wallet active in several eligible markets is counted once in the all-program checkpoint count. The threshold is applied per wallet-market position before distinct-wallet aggregation. Smart contracts are included because a wallet is not assumed to be a person; the zero address and malformed owners are excluded. A protocol-positive diagnostic using only `borrowShares > 0` should be retained to show dust sensitivity.

## 3. Baseline reference

The frozen v1 reference is the arithmetic mean of 56 equally spaced 24-hour closing checkpoints aligned to the verified campaign hour:

```text
t_i = 2025-07-09T13:00:00Z + i days, for i = 1, ..., 56
B(M) = (1 / 56) * SUM(M(t_i))
```

For active borrowers, each `M(t_i)` is the distinct active-wallet count at that checkpoint; it is not the number of distinct wallets seen anywhere in the whole baseline.

Mean is primary because it preserves the magnitude of the full pre-period and is additive when identical-asset markets are aggregated. Median is a labeled robustness sensitivity: it is less affected by short spikes, but is not additive and often collapses to zero for late or inactive markets.

## 4. Retained uplift

For metric `M`, let:

```text
B       = baseline mean defined above
E       = M(2026-02-18T13:00:00Z)
P_k     = M at the exact +30, +90, or +180 checkpoint
uplift_end = E - B
uplift_k   = P_k - B
```

The primary retained-uplift ratio is:

```text
retained_uplift_k = (P_k - B) / (E - B)
```

It is defined only when `E - B > 0`. If campaign-end uplift is zero or negative, the ratio is `NULL` with status `not_applicable_no_positive_end_uplift`; the raw baseline, end, post value and deltas remain reported. Ratios are never clamped:

- `1.0` means all campaign-end uplift remains;
- `0.0` means the metric returned to baseline;
- below `0.0` means it fell below baseline;
- above `1.0` means it grew further after incentives, without implying DRIP causality.

Every ratio must be shown with `B`, `E`, `P_k`, `E - B`, the applicability flag, unit and population. This prevents a tiny denominator from looking like strong evidence.

### Campaign-peak sensitivity

Define the campaign daily-close peak from the campaign-aligned boundary snapshots, including the opening and final checkpoint:

```text
Q = MAX(M(2025-09-03T13:00:00Z + i days)), for i = 0, ..., 168
peak_retained_uplift_k = (P_k - B) / (Q - B)
```

The sensitivity is defined only when `Q - B > 0` and must be labeled separately. It asks how much of peak uplift remains; it never replaces the campaign-end denominator in the primary series. An event-level intraday maximum is not used because a transient within-block or short-lived state is less comparable with checkpoint retention.

## 5. Aggregation contract

- Calculate market-level retained uplift for each exact market ID.
- For a portfolio view, aggregate state first and then apply the formula; do not take an unweighted mean of market ratios.
- Borrowed and supplied assets may be aggregated only within the same exact loan-token address. USDC and USD₮0 remain separate native-unit series.
- Collateral may be aggregated only within the same exact collateral-token address. Heterogeneous collateral tokens cannot form one native-unit total.
- Program active borrowers are a distinct-wallet count across the fixed 45-market panel, not the sum of market-level counts.
- For a portfolio peak sensitivity, take the maximum of the aggregate series at each aligned checkpoint; do not sum market-specific peaks that occurred at different times.

## 6. Inactive and matured markets

All 45 markets retain one row per UTC day and remain in the fixed panel at every checkpoint.

- `inactive_uninitialized` may carry zero state only when the market's zero anchor is independently proven and no earlier in-scope state transition exists.
- An unverified or non-zero anchor is not imputed to zero; it is `unknown_anchor` and blocks a complete retained-uplift result for that market and any affected aggregate.
- Once initialized, a zero-balance or no-event market remains an initialized market; it does not revert to `inactive`.
- A matured collateral market is not removed, reweighted or manually zeroed. Exact onchain balances continue to count. A verified maturity date may be a descriptive flag, while later runoff or zero state remains part of the measured outcome.
- The primary global campaign-end checkpoint is used even when a market's last eligible epoch ended earlier. Market-specific incentive-end retention is an optional sensitivity, not the primary comparison.

This fixed-panel rule prevents post-outcome survivorship and changing-composition bias.

## 7. Native units and USD policy

Primary v1 presentation is native-unit only:

- loan balances by exact loan-token address;
- collateral balances by exact collateral-token address or market;
- borrower counts as wallets;
- retained-uplift ratios as dimensionless values.

V1 will not treat USDC or USD₮0 as exactly one dollar and will not publish a mixed-asset USD total. A USD layer is deferred until a separate versioned decision freezes a reproducible price source, timestamp convention, decimals, missing-price policy and coverage for collateral assets, including principal tokens. Prices must never be silently forward-filled across unsupported periods.

Cost per retained dollar, cost per retained borrower and market-level ARB efficiency remain out of scope because shared campaign budgets and direct-vault budgets cannot yet be defensibly attributed to individual markets or wallets.

## 8. Wallet cohorts in v1

V1 excludes wallet cohort-retention and new-borrower-cohort claims from the primary analysis. Cross-sectional active-borrower counts at the frozen checkpoints remain in scope, but they are not cohort retention and do not identify reward recipients.

End-position retention, first-borrow timing and `campaign-exposed wallet` cohorts require population-wide wallet-position replay, prehistory adequacy and separate QA. They may be added only through a later versioned decision; until exact Merkl recipient evidence exists, eligible-market wallets must not be called reward recipients.

## 9. Definition contract by headline metric

| Metric | Population and grain | Numerator / denominator | Window | Exclusions / flags | Unit |
|---|---|---|---|---|---|
| Borrowed-assets retained uplift | Fixed 45 markets; market × checkpoint, plus exact-loan-address aggregates | `P_k - B` / `E - B` | Mean of 56 baseline closes; exact end and +30/+90/+180 | Ratio N/A when `E-B <= 0`; no mixed loan assets | Dimensionless ratio; supporting balances in native loan tokens |
| Collateral retained uplift | Fixed 45 markets; market × checkpoint, plus exact-collateral-address aggregates | `P_k - B` / `E - B` | Same | Ratio N/A when `E-B <= 0`; unknown anchor blocks; no mixed collateral assets | Dimensionless ratio; supporting balances in native collateral tokens |
| Active-borrower retained uplift | Distinct wallets across the fixed panel at each checkpoint | `P_k - B` / `E - B` using checkpoint counts | Same | Material-position rule; ratio N/A when `E-B <= 0`; contracts included | Dimensionless ratio; supporting values in wallets |

## 10. Recommendation versus alternatives

| Disputed choice | Recommended v1 | Main alternative | Effect of choosing the alternative |
|---|---|---|---|
| Baseline statistic | Mean of 56 aligned daily closes | Median | More robust to spikes, but non-additive and more likely to produce zero baselines for late markets |
| Campaign-end ordering | State before the first block with timestamp `>=` the boundary | Include same-timestamp blocks in incentive | Moves boundary-block activity into campaign end and makes results dependent on an inclusive convention |
| Primary denominator | Positive campaign-end uplift | Campaign peak | Peak denominator usually lowers retention and changes the question from taper/end persistence to maximum persistence |
| Peak definition | Max of 169 aligned boundary snapshots | Event-level intraday max | More sensitive to transient states and harder to compare with checkpoint outcomes |
| Positive position | At least 1 native loan token after exact conversion | Any `borrowShares > 0` | Includes dust and can overstate active-borrower retention |
| Market panel | Fixed 45 ever-eligible markets, including proven inactive zeros | Only markets active/eligible at each date | Changes composition over time and can hide failed or matured markets |
| Market incentive end | One global program-end checkpoint | Per-market last eligible epoch | Better matches local incentive exposure but produces non-comparable horizons |
| Presentation | Native units by exact token address | Historical USD conversion | Enables cross-asset totals but adds price-source, depeg, timing and missing-coverage assumptions |
| Wallet cohorts | Exclude from primary v1; keep cross-sectional active counts | Add end-position/new-borrower cohorts | Adds a useful retention lens but requires a separately validated full wallet pipeline and adequate prehistory |

## 11. Required guardrails and limitations

- `Wallet` is not a person or an independent user.
- Eligible-market activity is not proof of reward receipt.
- Retained uplift is descriptive and does not establish causal DRIP impact.
- Market size, supplied assets, borrowed assets and collateral are not interchangeable.
- Non-zero `feeShares` and bad debt were implemented but not empirically exercised in the accepted bounded prototype; this remains a Phase 6 QA and final-report limitation.
- Any change after v1 freeze requires a new versioned decision rather than an in-place silent rewrite.
