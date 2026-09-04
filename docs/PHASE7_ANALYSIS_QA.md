# Phase 7 Metrics, Charts, and QA

Status: **technical PASS; Phase 7 awaiting user acceptance**  
Generated: 2026-09-03 (Europe/Moscow)  
Metric contract: frozen v1.0

## Scope and immutable inputs

The analysis reads the accepted Phase 6 SQLite only through `mode=ro&immutable=1` with `PRAGMA query_only=ON`. It made zero RPC calls, zero `eth_getLogs` calls, zero GBA queries, and did not modify the production database.

| Input | Accepted identity |
|---|---|
| Phase 6 production SQLite | SHA-256 `80aca74cc5e43db03fd93c69d7ad448ac9afdec5f9566a6b833ec11f7e5c9543` |
| Frozen `docs/METRICS.md` | SHA-256 `2774c0856ca66da4611523289a7e1c4da937ce208cad9799c2f008753eca2ba2` |
| Eligibility bridge | SHA-256 `cbab02426bcd1ac1ad0679156f837e155c5b04e86b63001a9149b0cbae27d305` |
| Exact boundary CSV | SHA-256 `329ca8510fdd73d4623fa9de17b621ef752c383db5fb131ba77a5ffe507aeac9` |
| Exact timestamp population | SHA-256 `be8ee9c6c0a80864090d50b2d16737acd58da5c70a184a7728666ca0f3d04959` |

The accepted boundary manifest identity was verified before any metric calculation. The population is 227 distinct exact timestamps carrying 228 roles: 56 baseline closes, 169 campaign-aligned snapshots with campaign start shared by the two series, and three post checkpoints.

## Frozen calculation contract

- State at timestamp `t` is the state after all logs in blocks with `block_number < first_block(timestamp >= t)`; the boundary block is excluded.
- `B` is the arithmetic mean of 56 campaign-hour-aligned baseline checkpoints.
- `E` is the exact campaign-end checkpoint. `P30`, `P90`, and `P180` use exact accepted boundaries.
- `Q` is the maximum of the 169 aligned campaign checkpoints.
- Primary retained uplift is `(P_k - B) / (E - B)` only when `E - B > 0`; otherwise status is `not_applicable_no_positive_end_uplift` and raw levels/deltas remain present.
- Peak sensitivity is `(P_k - B) / (Q - B)` and is never substituted for the primary denominator.
- Portfolio ratios are calculated from asset-group aggregates before division, never as averages of market ratios.
- USDC and USD₮0 are grouped only by their exact addresses and never added. Heterogeneous collateral addresses are never added.
- A primary active borrower is a distinct wallet whose current borrow shares are positive and whose rounded-up checkpoint debt is at least one native loan token. Positive shares without that threshold are a separately labeled dust sensitivity.

## Population and accounting QA

| Check | Result |
|---|---:|
| Fixed markets | 45/45 |
| Production market-day rows | 18,225 |
| Exact state grid | 45 × 228 roles = 10,260 |
| Wallet checkpoint/market share reconciliations | 10,215/10,215 |
| Max difference: summed wallet shares vs market `totalBorrowShares` | 0 |
| Wallet position events replayed | 77,768 |
| Negative wallet-share states | 0 |
| Malformed owner events | 0 |
| Raw event-family reconciliation | 8/8, zero defects |
| Raw amount reconciliation | 17/17, zero defects |
| Period debt-equation residuals | 0 |
| Exact token-aggregation defects | 0 |
| Negative market checkpoint balances | 0 |
| Duplicate/unexplained NULL chart-ready keys | 0 |
| Phase 6 exact-rounding checks inherited | 542,761 PASS; 688,746 not applicable |
| Non-zero `feeShares` events | 0 — implemented, not empirically exercised |
| Non-zero bad-debt events | 3 — empirically exercised |

The ten Phase 2 source events after the `P180` boundary remain in the immutable source buffer and were deliberately excluded from all frozen-window calculations.

## Metric QA

The primary campaign-end applicability counts are stable across all three post checkpoints:

| Metric | Applicable markets | Not applicable markets |
|---|---:|---:|
| Borrowed assets | 42 | 3 |
| Supplied assets | 45 | 0 |
| Collateral assets | 44 | 1 |
| Active borrowers | 38 | 7 |

The complete chart-ready outputs have the expected unique grain: 540 market retained-uplift rows, 108 portfolio rows, 2,724 checkpoint-series rows, 141 period-flow rows, and 90 concentration rows. All required key fields are non-NULL and all key counts equal row counts.

Outstanding-debt reconciliation uses:

`closing debt - opening debt = Borrow assets - Repay assets - Liquidation repaid assets + Accrued interest - Liquidation bad debt`

This identity has zero residual in every market/period row. Consequently, accrued interest is reported separately and is not labeled new borrowing demand.

## Chart contracts and visual review

All six figures were inspected at full resolution after the final build.

| Figure | Question | Population | Unit | Window | Source | Visual QA |
|---|---|---|---|---|---|---|
| `phase7_borrowed_assets_checkpoints.png` | How did outstanding debt move from baseline through +180? | Fixed 32 USDC and 13 USD₮0 markets | Native loan tokens, separate panels | 56 baseline, 169 campaign, P30/P90/P180 | Phase 6 states + exact boundary map | PASS: zero axes, end/peak separate, exact labels |
| `phase7_retained_uplift.png` | What share of end uplift remained, and how does peak sensitivity differ? | Same fixed exact-loan groups | Ratio / percent | P30, P90, P180 | Portfolio retained-uplift CSV | PASS: primary and peak are distinct series; no clamp |
| `phase7_debt_flow_decomposition.png` | Was debt change caused by new borrowing, interest, repayment, or liquidation? | Fixed exact-loan groups | Native loan tokens | Incentive and 180-day post intervals | Period-flow CSV | PASS: gross flows and interest are separately labeled |
| `phase7_market_concentration.png` | How concentrated was outstanding debt across markets? | Markets within each exact loan-token group | Share of group debt | Campaign end and P180 | Concentration CSV | PASS: 0–100% scale, exact checkpoint labels |
| `phase7_archetype_borrowed_assets.png` | How did the three precommitted archetypes differ? | Three frozen market IDs | Native loan/collateral token per panel | Full aligned series through P180 | Checkpoint-series CSV | PASS: no mixed assets; independent labeled y-scales |
| `phase7_active_borrowers.png` | Did cross-sectional material participation persist? | Distinct wallets across fixed 45 markets | Wallet count | Full aligned series through P180 | Validated wallet-share replay | PASS: material threshold primary; shares-only dust sensitivity labeled |

Producing code for every chart and table is [`scripts/analyze_phase7_metrics.py`](../scripts/analyze_phase7_metrics.py). Final runtime was 55.455 seconds and published outputs total 1,393,141 bytes. The manifest records SHA-256 for the script and every output.

## Interpretation guardrails

- The design is observational before/after; it does not identify a causal DRIP effect.
- Wallets are not people or confirmed recipients. Active-borrower results are cross-sectional checkpoint counts, not cohorts.
- No wallet concentration or top-wallet list is produced because a validated cohort/concentration layer is out of scope.
- Shared ARB and 505,000 ARB of direct-vault incentives are not allocated to markets.
- No price/USD layer is used, so exact native-token groups remain separate.
- Matured collateral, migrations, rates, asset prices, market risk, competing incentives, and organic adoption are viable alternative explanations.

Machine-readable evidence is in [`morpho_phase7_analysis_qa.json`](../data/morpho_phase7_analysis_qa.json) and [`morpho_phase7_analysis_manifest.json`](../data/morpho_phase7_analysis_manifest.json). Phase 7 remains **CURRENT — awaiting user acceptance**; Phase 8 remains **LOCKED**.
