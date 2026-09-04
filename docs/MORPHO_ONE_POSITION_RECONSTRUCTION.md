# Morpho One-Position Reconstruction — Phase 3 QA

Status: **PASS — Phase 3 accepted 2026-09-01**  
Accessed: **2026-09-01**

## Answer

The bounded reconstruction passed for the deterministic rank-1 pair:

- market: `0xed06d9e82d7c35ca80d3983194e15462a96202bd875800af18183321f4611868`;
- position owner: `0xa0c826c8238dae8e11c637c29d0b3374c34f5f80`;
- selection SHA-256: `00031bb5035ff7db2acca4ee754c563e588412db7a46428d7248682152615e5f`;
- anchor: end of block `464068386`;
- replay: `[464068387, 482431183)`;
- intermediate checkpoint, fixed before the bounded RPC call: end of block `464068387`;
- final checkpoint: end of block `482431182`.

Starting from the zero RPC position and the RPC market totals at the anchor, the replay processed all 2,634 selected-market logs in strict `(block_number, transaction_index, log_index)` order. It reproduced the non-zero intermediate position and the zero final position exactly. The four stored market totals also matched RPC exactly at the intermediate and final checkpoints. No unexplained negative balance, duplicate key, ordering collision, malformed scoped event, rounding mismatch, shard checksum mismatch, or reconciliation difference was found.

This is the requested feasibility proof for one position. It is not evidence that every wallet and all 45 markets will reconstruct correctly, and it does not prove the future market-day pipeline, reward receipt, retention, or a causal DRIP effect.

## Selection and source verification

The rank was not changed and no fallback candidate was inspected.

| Check | Result |
|---|---:|
| Current Phase 2 manifest | `complete` |
| Manifest SHA-256 | `c8552428187094e5aad725193f2e3023e622ddc4ab37428f1414c375e7d6be58` |
| Verified shards / rows | 3,157 / 1,231,462 |
| Structural candidates | 5,575 |
| Archive gates passed | 5,575 / 5,575 |
| Planned calls completed | 22,301 / 22,301 |
| Sealed selection SQLite | integrity `ok`; 22,181 unique cache entries; zero invalid, duplicate, gap, or orphan defects |
| Selected rank | 1 |
| Recomputed selection hash | exact match |

The selection SQLite was opened with `mode=ro&immutable=1`. Its SHA-256 was identical before and after verification. Anchor and final state came from its already-sealed responses. No new call was written to it.

The replay touched only the 252 verified shards intersecting the selected interval. Their 60,419,048 bytes and 94,598 rows were rechecked against the current manifest row counts and SHA-256 values. This was a bounded read of the immutable Phase 2 result, not a new extraction.

## Replay population

All eight scoped event families were present:

| Event family | Market events |
|---|---:|
| `AccrueInterest` | 1,108 |
| `Borrow` | 262 |
| `Liquidate` | 6 |
| `Repay` | 179 |
| `Supply` | 388 |
| `SupplyCollateral` | 316 |
| `Withdraw` | 257 |
| `WithdrawCollateral` | 118 |
| **Total / unique onchain keys** | **2,634 / 2,634** |

The selected owner contributed exactly 19 position events: 4 `SupplyCollateral`, 7 `Borrow`, 5 `Repay`, and 3 `WithdrawCollateral`. Their first and last full ordering keys and transaction hashes match the selection artifact. The canonical digest of all 19 ordered `(block_number, transaction_hash, log_index)` keys is `87b48ed89653cbe70f27b55677de15f3a80f17c6658692fb5df94159e3f99582`.

## Checkpoint reconciliation

All values are raw token units or raw Morpho shares.

| State | Anchor RPC | Intermediate replay | Intermediate RPC | Final replay | Final RPC |
|---|---:|---:|---:|---:|---:|
| wallet supply shares | 0 | 0 | 0 | 0 | 0 |
| wallet borrow shares | 0 | 3,243,341,461,534,715 | 3,243,341,461,534,715 | 0 | 0 |
| wallet collateral assets | 0 | 6,188,640 | 6,188,640 | 0 | 0 |
| total supply assets | 2,306,147,574,352 | 2,306,158,539,888 | 2,306,158,539,888 | 719,347,685,838 | 719,347,685,838 |
| total supply shares | 2,153,552,919,740,529,288 | 2,153,552,919,740,529,288 | 2,153,552,919,740,529,288 | 669,107,751,092,827,764 | 669,107,751,092,827,764 |
| total borrow assets | 1,993,654,167,463 | 1,997,165,132,999 | 1,997,165,132,999 | 640,120,558,484 | 640,120,558,484 |
| total borrow shares | 1,847,467,653,220,434,764 | 1,850,710,994,681,969,479 | 1,850,710,994,681,969,479 | 590,476,084,282,594,003 | 590,476,084,282,594,003 |

At the intermediate checkpoint, converting the reconstructed borrow shares with the contemporaneous market totals and Morpho's upward debt rounding gives `3,500,000,001` loan-asset units. The emitted first `Borrow` was `3,500,000,000`; the one-unit difference is the expected protocol-conservative checkpoint quote, not a reconciliation defect.

## Accounting QA

- 1,092 `Supply`/`Withdraw`/`Borrow`/`Repay`/`Liquidate` asset-share pairs passed the exact virtual-share rounding alternatives; 1,542 collateral or accrual events had no such pair.
- `AccrueInterest` was applied before subsequent same-transaction actions according to log order. Its emitted `interest` changed both asset totals and its emitted `feeShares` changed total supply shares.
- All six market `Liquidate` logs were applied using the emitted repayment, seized collateral, and bad-debt fields. In this bounded interval all six emitted zero bad debt.
- The market fee was zero at both sealed RPC endpoints. All 1,108 accruals emitted zero fee shares. Therefore the code paths for non-zero bad debt and non-zero fee shares are specified and implemented but are not empirically exercised by this deterministic trace.
- `Repay` and `Liquidate` use zero-floor subtraction for market borrow assets. Wallet shares and collateral use exact emitted deltas and are never zero-floored; a negative value would fail the run.
- The final position is derived from shares and collateral state. No `SUM(Borrow.assets) - SUM(Repay.assets)` shortcut is used.

## Separate intermediate RPC evidence

The intermediate checkpoint rule was persisted in `data/morpho_one_position_checkpoint_plan.json` before the RPC call. Two validated `eth_call` responses — `position(bytes32,address)` and `market(bytes32)` at block `464068387` — were committed to the separate identity-bound cache `data/tmp/morpho_phase3_one_position_rpc.sqlite`. The cache contains two valid unique entries, contiguous checkpoint `1`, SQLite integrity `ok`, and zero invalid, duplicate, gap, error, or orphan defects. A later offline-only replay produced two cache hits and zero new archive calls.

## Reproducible artifacts

- Accounting SQL: [`../sql/01_feasibility_one_position.sql`](../sql/01_feasibility_one_position.sql)
- Exact 19-event wallet trace: [`../data/morpho_one_position_sample.csv`](../data/morpho_one_position_sample.csv)
- Bounded 2,634-event market input: [`../data/morpho_one_position_market_events.csv`](../data/morpho_one_position_market_events.csv)
- Machine-readable QA: [`../data/morpho_one_position_reconstruction_qa.json`](../data/morpho_one_position_reconstruction_qa.json)
- Checkpoint precommit: [`../data/morpho_one_position_checkpoint_plan.json`](../data/morpho_one_position_checkpoint_plan.json)
- Reproducer: [`../scripts/reconstruct_morpho_one_position.py`](../scripts/reconstruct_morpho_one_position.py)

The SQL intentionally reads only the compact staged CSV, not GBA. It records the business question, source and replay grain, deterministic order, all eight transition rules, virtual balances, rounding directions, zero-floor behavior, and the exact intermediate/final assertions beside the query.

## Interpretation boundary

This PASS establishes that the recorded accounting logic can reconstruct this selected position from a known zero anchor while the same replay reconciles the selected market totals. A single trace cannot establish cross-market generality. In particular, because this trace has zero non-zero-fee accruals and zero non-zero-bad-debt liquidations, those non-zero branches still require broader validation before a production all-market state pipeline can rely on them without further QA.

The user accepted Phase 3 on 2026-09-01 and correctly explained the share-based debt accounting rule. The non-zero `feeShares` and bad-debt coverage gap is accepted as non-blocking for this one-position feasibility proof. Phase 4 is now `CURRENT`; the gap is carried into its future QA matrix and final limitations without changing the frozen three-market selection. See [`PHASE4_MARKET_ARCHETYPES.md`](PHASE4_MARKET_ARCHETYPES.md).

## Official implementation references

- [Morpho Blue v1.0.0 core accounting](https://github.com/morpho-org/morpho-blue/blob/v1.0.0/src/Morpho.sol)
- [Morpho Blue v1.0.0 event ABI](https://github.com/morpho-org/morpho-blue/blob/v1.0.0/src/libraries/EventsLib.sol)
- [Morpho Blue v1.0.0 share conversions](https://github.com/morpho-org/morpho-blue/blob/v1.0.0/src/libraries/SharesMathLib.sol)
