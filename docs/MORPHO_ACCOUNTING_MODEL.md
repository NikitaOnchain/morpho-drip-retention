# Morpho Accounting Model and Deterministic Replay Rules

Status: **Phase 3 COMPLETE — accepted 2026-09-01**  
Accessed: **2026-09-01**

## Purpose and boundary

This note defines how the eight scoped Morpho event families change market and wallet state and records the result of the bounded one-position reconstruction. It does not create a daily-state dataset.

The canonical evidence is the official Morpho core implementation and event ABI. The Arbitrum deployment and full raw-log population were verified in Phase 2. The implementation statements below were checked against the official tagged `v1.0.0` source and the current official developer documentation.

## 1. Two different deposits: loan-asset supply and collateral

Morpho keeps two economically and mechanically different balances:

- **Loan-asset supply** is lender liquidity. `Supply` mints `supplyShares`; `Withdraw` burns them. At market level it changes `totalSupplyAssets` and `totalSupplyShares`.
- **Collateral** secures debt. `SupplyCollateral` and `WithdrawCollateral` change the position's `collateral` directly in collateral-token base units. Collateral has no shares, does not earn the market's lending yield, and is not part of `totalSupplyAssets`.

Consequently, market supplied assets, collateral, borrowed assets, liquidity, and TVL are not interchangeable. Morpho's `Market` struct has no `totalCollateral` field. A market-level collateral series must be reconstructed from collateral deltas plus a verified starting anchor, or reconciled from all wallet positions; it must not be read from `totalSupplyAssets`.

## 2. Stored market and wallet state

For each market ID, the core contract stores:

```text
Market:
  totalSupplyAssets
  totalSupplyShares
  totalBorrowAssets
  totalBorrowShares
  lastUpdate
  fee

Position[market_id, wallet]:
  supplyShares
  borrowShares
  collateral
```

Assets are token base units. Shares are internal, non-transferable accounting units. A wallet's current supplied assets or debt cannot be inferred from its own cash-flow events alone; its shares must be valued against the corresponding current market totals.

For checkpoint reporting, the protocol-conservative conversions are:

```text
wallet_supply_assets = toAssetsDown(supplyShares, totalSupplyAssets, totalSupplyShares)
wallet_borrow_assets = toAssetsUp(borrowShares, totalBorrowAssets, totalBorrowShares)
```

The upward rounding for debt is also used by the core health check. Per-wallet rounded asset values are presentation/reconciliation values; summing them need not equal a market total exactly. The market-level source of truth remains the stored/replayed market totals.

## 3. Assets-to-shares conversion and rounding

`SharesMathLib` adds virtual balances to make empty-market conversion defined and to mitigate share-price manipulation:

```text
VIRTUAL_SHARES = 1,000,000
VIRTUAL_ASSETS = 1

toSharesDown(A, TA, TS) = floor(A * (TS + 1,000,000) / (TA + 1))
toSharesUp(A, TA, TS)   = ceil (A * (TS + 1,000,000) / (TA + 1))
toAssetsDown(S, TA, TS) = floor(S * (TA + 1) / (TS + 1,000,000))
toAssetsUp(S, TA, TS)   = ceil (S * (TA + 1) / (TS + 1,000,000))
```

The action-specific direction is part of the accounting model:

| Action | Exact assets supplied | Exact shares supplied |
|---|---|---|
| `Supply` | shares = `toSharesDown` | assets = `toAssetsUp` |
| `Withdraw` | shares = `toSharesUp` | assets = `toAssetsDown` |
| `Borrow` | shares = `toSharesUp` | assets = `toAssetsDown` |
| `Repay` | shares = `toSharesDown` | assets = `toAssetsUp` |

For event replay, the emitted `assets` and `shares` are the actual post-conversion amounts used by the contract. The replay should apply those integers directly. Recomputing them is an independent validation, not a substitute for the emitted values.

## 4. Event-to-state transition table

The position owner is `onBehalf` for the six ordinary position actions and `borrower` for `Liquidate`. `caller` and `receiver` are operational roles and must not be mistaken for the position owner.

| Event | Market transition | Wallet transition |
|---|---|---|
| `Supply` | `totalSupplyAssets += assets`; `totalSupplyShares += shares` | `onBehalf.supplyShares += shares` |
| `Withdraw` | subtract emitted assets and shares | `onBehalf.supplyShares -= shares` |
| `Borrow` | `totalBorrowAssets += assets`; `totalBorrowShares += shares` | `onBehalf.borrowShares += shares` |
| `Repay` | burn shares; apply zero-floor subtraction of assets | `onBehalf.borrowShares -= shares` |
| `SupplyCollateral` | no stored market-total field changes | `onBehalf.collateral += assets` |
| `WithdrawCollateral` | no stored market-total field changes | `onBehalf.collateral -= assets` |
| `AccrueInterest` | add `interest` to both supply and borrow assets; add `feeShares` to total supply shares | add `feeShares` to the active fee recipient's supply shares |
| `Liquidate` | reduce borrow assets/shares by repayment; if bad debt is realized, also reduce borrow assets/shares and reduce supply assets | reduce borrower collateral by `seizedAssets`; reduce borrower borrow shares by `repaidShares + badDebtShares` |

`Repay.repaidAssets` and liquidation `repaidAssets` may be one unit above the pre-transition `totalBorrowAssets` because of upward rounding. The contract uses zero-floor subtraction; an offchain replay must reproduce this behavior instead of allowing a negative balance.

## 5. Interest and protocol fee shares

Before most market actions, Morpho calls `_accrueInterest`. `SupplyCollateral` is the explicit exception because collateral addition does not require interest accrual. If elapsed time is non-zero and the market has an IRM, the core contract:

1. computes `interest` from the prior `totalBorrowAssets`, borrow rate, and elapsed seconds;
2. adds the same `interest` amount to `totalBorrowAssets` and `totalSupplyAssets`;
3. computes the protocol `feeAmount` as a fraction of that interest;
4. converts the fee amount to `feeShares` against the post-interest supply assets excluding the fee amount from the conversion denominator;
5. mints those shares to the active `feeRecipient` and increases `totalSupplyShares`;
6. emits `AccrueInterest(id, prevBorrowRate, interest, feeShares)`.

Borrow and supply shares do not grow merely because interest accrues. Their asset value changes because the asset totals change. Fee shares are different: they are newly minted supply shares, dilute other suppliers, and are not accompanied by a `Supply` event. This is why a fee-recipient wallet cannot be reconstructed from only its `Supply` and `Withdraw` rows; the applicable fee-recipient history must also be known.

For the bounded reconstruction, the emitted `interest` and `feeShares` are sufficient to update market totals. If the chosen wallet was the fee recipient at any point, `SetFeeRecipient` history and the recipient active at every accrual would become required inputs. The completed selection excluded that complication: the selected non-zero wallet was never the active fee recipient.

## 6. Liquidation and bad debt

Liquidation is not a normal borrower `Repay` event. The liquidator repays loan assets and receives seized collateral, while the `borrower` position is modified. The `Liquidate` event supplies five accounting deltas: `repaidAssets`, `repaidShares`, `seizedAssets`, `badDebtAssets`, and `badDebtShares`.

The ordinary liquidation leg burns `repaidShares`, lowers `totalBorrowAssets` by the zero-floor `repaidAssets`, and lowers the borrower's collateral by `seizedAssets`. If collateral reaches zero and borrow shares remain, the core realizes all remaining borrow shares as bad debt. It then:

- sets the borrower's remaining borrow shares to zero;
- removes `badDebtShares` and `badDebtAssets` from market borrow totals; and
- subtracts `badDebtAssets` from `totalSupplyAssets`, imposing the loss on suppliers through a lower supply-share value.

There is no burn of supply shares for the bad-debt loss. Ignoring the bad-debt fields would therefore overstate both debt and supplier assets.

## 7. Why `SUM(Borrow.assets) - SUM(Repay.assets)` is not outstanding debt

That expression measures only two cash-flow families. It is not a position balance because:

- debt ownership is stored in `borrowShares`, while interest raises the asset value of unchanged shares;
- `AccrueInterest` increases market borrow assets without a `Borrow` event;
- every assets/shares conversion has a specified rounding direction and virtual balances;
- `Liquidate` burns debt shares and may realize bad debt without emitting `Repay`;
- the position owner is `onBehalf`/`borrower`, which may differ from `caller` or `receiver`;
- a wallet may already have a non-zero balance at the start of the observed interval; and
- same-block and same-transaction order matters because an accrual can precede the user action that triggered it.

The correct workflow is to replay market totals and wallet shares from a verified anchor, then convert the final wallet shares with the final market totals.

## 8. Deterministic ordering and checkpoint boundaries

Apply canonical raw logs in ascending:

```text
block_number, transaction_index, log_index
```

The event identity/uniqueness key remains:

```text
block_number, transaction_hash, log_index
```

`block_timestamp` is not an ordering key, and a transaction hash has no sortable execution meaning. `log_index` preserves emission order inside a transaction. This is essential because `_accrueInterest` runs and emits before the action event that triggered it. Reverted calls emit no canonical receipt logs, and `removed=true` logs are forbidden by the Phase 2 QA contract.

All processing ranges are half-open. For a UTC boundary `T`, define `B(T)` as the first canonical block with `timestamp >= T`. The state **at** `T` is the state after all logs in blocks `< B(T)`; logs in block `B(T)` belong to `[T, next_T)`. Daily bucket `T0` is therefore `[B(T0), B(T1))`. This matches the 406 independently verified boundary blocks used for the full-window QA.

## 9. Proposed deterministic one-position selection rule

The rule is specified before inspecting candidate outcomes:

1. Candidate identity is `(market_id, position_owner)`, using `onBehalf` or `borrower`, never `caller` or `receiver`.
2. Keep only the 45 eligible markets and candidates whose position-changing history contains `SupplyCollateral`, `Borrow`, and at least one later `Repay` or `Liquidate`, with at least one market `AccrueInterest` between the first borrow and the final checkpoint.
3. Require 4–50 position-changing events so the trace is multi-event but still manually auditable.
4. Require an archive-RPC anchor immediately before the first included event where the wallet position is exactly zero, plus the market totals at that same block. Require an independent post-state RPC checkpoint after the replay interval.
5. Exclude a candidate that was the active Morpho fee recipient during the interval; do not exclude contract wallets merely because they are contracts, and make no person-level claim.
6. Rank eligible candidates by the ascending hexadecimal SHA-256 digest of the exact ASCII string `morpho-phase3-v1|<lowercase market_id>|<lowercase wallet>`. Select rank 1. If a predeclared technical requirement fails, record the reason and take the next rank; do not hand-pick a convenient trace.

The user checkpoint was accepted on 2026-08-31. The complete offline structural funnel narrowed 9,959 distinct wallet-market pairs to 5,575 structural candidates. The manually completed archive pass then finished all 22,301 planned calls; all 5,575 candidates passed the archive gates, and the sealed cache audit reported SQLite integrity `ok` with zero invalid, error, duplicate, gap, or orphan defects.

The exact preimage rule selected rank 1 without manual substitution:

```text
market_id = 0xed06d9e82d7c35ca80d3983194e15462a96202bd875800af18183321f4611868
wallet    = 0xa0c826c8238dae8e11c637c29d0b3374c34f5f80
SHA-256   = 00031bb5035ff7db2acca4ee754c563e588412db7a46428d7248682152615e5f
```

The anchor is end of block `464068386`, the replay interval is `[464068387, 482431183)`, and the final checkpoint is end of block `482431182`. Because the final wallet state is zero, end of block `464068387` — the first `Borrow` block — was separately precommitted as the non-zero intermediate checkpoint before its bounded RPC call.

## 10. Bounded reconstruction result

The replay read only the 252 verified Phase 2 shards intersecting the selected interval. It applied all 2,634 selected-market logs in canonical order. All eight scoped event families were present, including 1,108 `AccrueInterest` and six `Liquidate` logs. Market totals were updated for every market event; wallet state changed only when the decoded position owner equaled the selected wallet.

The wallet trace contains exactly the 19 events stored in the selection evidence: 4 `SupplyCollateral`, 7 `Borrow`, 5 `Repay`, and 3 `WithdrawCollateral`. The full ordered-key digest is `87b48ed89653cbe70f27b55677de15f3a80f17c6658692fb5df94159e3f99582`.

| Checkpoint | supply shares | borrow shares | collateral | borrow assets, rounded up |
|---|---:|---:|---:|---:|
| anchor RPC, block `464068386` | 0 | 0 | 0 | 0 |
| intermediate replay/RPC, block `464068387` | 0 | 3,243,341,461,534,715 | 6,188,640 | 3,500,000,001 |
| final replay/RPC, block `482431182` | 0 | 0 | 0 | 0 |

The intermediate and final position fields matched RPC exactly. `totalSupplyAssets`, `totalSupplyShares`, `totalBorrowAssets`, and `totalBorrowShares` also matched RPC exactly at both checkpoints. All 1,092 applicable assets/shares pairs passed the official rounding alternatives; there were zero negative-balance, duplicate-key, ordering, or reconciliation defects.

This trace contains the liquidation event family, but its six liquidations all emitted zero bad debt. It also has a zero market fee and zero emitted fee shares. The replay implements the non-zero bad-debt and fee-share deltas from the official code, but this deterministic trace does not empirically exercise those non-zero branches. The complete evidence and exact values are in [`MORPHO_ONE_POSITION_RECONSTRUCTION.md`](MORPHO_ONE_POSITION_RECONSTRUCTION.md).

## Official sources

- [Morpho Blue `v1.0.0` core implementation](https://github.com/morpho-org/morpho-blue/blob/v1.0.0/src/Morpho.sol)
- [Morpho Blue `v1.0.0` market and position structs](https://github.com/morpho-org/morpho-blue/blob/v1.0.0/src/interfaces/IMorpho.sol)
- [Official share-conversion library](https://github.com/morpho-org/morpho-blue/blob/v1.0.0/src/libraries/SharesMathLib.sol)
- [Official event ABI](https://github.com/morpho-org/morpho-blue/blob/v1.0.0/src/libraries/EventsLib.sol)
- [Morpho Market Mechanics](https://docs.morpho.org/developers/borrow/concepts/market-mechanics/)
- [Morpho asset-flow tutorial](https://docs.morpho.org/developers/borrow/tutorials/assets-flow/)
- [Morpho liquidation documentation](https://docs.morpho.org/developers/borrow/concepts/liquidation/)

## Current limitation

The bounded trace establishes empirical correctness for one deterministic wallet-market pair, including exact anchor, intermediate, final, ordering, rounding, market-total, and negative-balance checks. It does not prove reconstruction for every wallet or all 45 markets, the completeness of a future market-day pipeline, reward receipt, retention, or DRIP impact.

The user accepted Phase 3 on 2026-09-01. The lack of non-zero `feeShares` and non-zero bad debt in this trace is an accepted non-blocking coverage gap, not empirical validation of those branches. Phase 4 is now `CURRENT`; the gap is frozen in its future QA coverage matrix and final limitations without changing the three-market selection rule. See [`PHASE4_MARKET_ARCHETYPES.md`](PHASE4_MARKET_ARCHETYPES.md).
