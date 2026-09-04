# Morpho three-market daily-state prototype

Access date: **2026-09-01**  
Status: **Phase 4 COMPLETE — accepted 2026-09-01; Phase 5 LOCKED**

## Result

The bounded prototype replayed **275,797** immutable Morpho logs for the three
frozen markets and produced exactly **1,215 rows**: three markets × 405 UTC
buckets. All blocking QA checks passed. The four stored Morpho market totals
matched **12/12** independent archive-RPC checkpoints, all 24 market/family
event-count comparisons matched, and all 51 market/flow-amount comparisons
matched. No calendar gap, duplicate key, unexplained NULL, continuity break,
rounding defect, invalid unsigned state or unexplained negative balance was
found.

This is a three-market accounting and engineering feasibility result. It does
not validate a future 45-market output or any retention, uplift, attribution,
cohort or causal claim.

## Executable engine and command

The fixed engine is **SQLite 3.50.4 through Python's standard-library
`sqlite3` driver**. Protocol amounts are stored as unsigned decimal `TEXT`, not
SQLite `INTEGER`, because Morpho share values can exceed signed `INT64`.
`scripts/build_morpho_market_day_prototype.py` registers exact Python-bigint
SQLite functions and then executes, without SQL rewriting:

- `sql/10_market_day_prototype.sql` — recursive event replay and daily layer;
- `sql/90_qa_market_day_prototype.sql` — calendar, key, continuity, raw-flow,
  rounding, nonnegative-state and RPC reconciliation checks.

Run from the repository root:

```powershell
python .\scripts\build_morpho_market_day_prototype.py --offline-only
```

`--offline-only` is the reproducible default after the validated 12-response
cache has been filled. It made 12 cache hits and zero new archive calls in the
final run. Removing the flag is only needed for the initial bounded cache fill
or a separately authorized rebuild against an empty cache. The script never
calls `eth_getLogs`, never queries GBA and never opens the sealed Phase 3
selection SQLite.

## Source contract

- Chain: Arbitrum One, chain ID `42161`.
- Official Morpho contract:
  `0x6c247b1f6182318877311737bac0844baa518f5e`.
- Immutable source interval:
  `[2025-07-09T13:00:00Z, 2026-08-18T00:00:00Z)` or
  blocks `[355887376, 495647034)`.
- Phase 2 manifest SHA-256:
  `c8552428187094e5aad725193f2e3023e622ddc4ab37428f1414c375e7d6be58`.
- Source verified again during this build: 3,157/3,157 shard checksums and row
  counts; 1,231,462 rows; 786,571,394 bytes; zero removed, scope, malformed,
  ordering or selected-key defects.
- Event order: `(block_number, transaction_index, log_index)`.

Only the three frozen IDs in `PHASE4_MARKET_ARCHETYPES.md` are retained. No
market was added or substituted after looking at results.

## Time and grain

The result key is `(market_id, day_utc)`. The first bucket is intentionally the
partial UTC day
`[2025-07-09T13:00:00Z, 2025-07-10T00:00:00Z)`; the remaining 404 buckets are
midnight-to-midnight UTC. Exact block boundaries come from the independently
verified Phase 2 boundary artifact.

Every market retains all 405 buckets. Before its first scoped event a row has
`status = inactive_pre_first_scoped_event`, zero state and zero flows. This is
an analytical status meaning “no event in the accepted eight-family history has
occurred yet”; it must not be read as a general claim about an explorer's market
creation label. The independent anchor at end of block `355887375` returned an
uninitialized all-zero `market(bytes32)` value, so the replay and aggregate
collateral balance legitimately start at zero.

| Archetype | Events replayed | Inactive rows | First active UTC day | Total rows |
|---|---:|---:|---|---:|
| Early shared USDC | 62,753 | 9 | 2025-07-18 | 405 |
| Dedicated syrupUSDC | 182,549 | 51 | 2025-08-29 | 405 |
| Late USD₮0 | 30,495 | 167 | 2025-12-23 | 405 |

## Accounting transitions

Each daily row stores opening and closing:

- `totalSupplyAssets` and `totalSupplyShares`;
- `totalBorrowAssets` and `totalBorrowShares`;
- replayed aggregate collateral assets.

It also stores eight event-family counts and the emitted asset/share flows for
supply, withdrawal, borrow, repay, collateral, interest and liquidation.

The recursive SQL applies the Phase 3 model event by event:

- `Supply`/`Withdraw` change loan-asset supply totals, not collateral;
- `Borrow`/`Repay` change borrow assets and shares;
- `AccrueInterest` adds emitted `interest` to both asset totals and emitted
  `feeShares` to supply shares;
- `Liquidate` removes repaid and bad-debt borrow amounts, seized collateral and
  any bad-debt loss from supply assets;
- `Repay` and the repayment leg of `Liquidate` use Morpho's specified
  zero-floor asset subtraction; no other clamp or manual correction exists;
- aggregate collateral is replayed from every collateral event because Morpho
  has no market-level `totalCollateral` getter.

For `Supply`, `Withdraw`, `Borrow`, `Repay` and `Liquidate`, each emitted pair is
checked against the allowed `VIRTUAL_SHARES = 1e6`, `VIRTUAL_ASSETS = 1`
conversion and rounding direction using its pre-event totals. **129,881 / 129,881**
applicable event checks passed; 145,916 non-conversion events plus three anchor
rows were not applicable.

## Raw-log population

| Market | Supply | Withdraw | Borrow | Repay | Supply collateral | Withdraw collateral | Liquidate | Accrue interest | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Early shared USDC | 11,800 | 14,446 | 111 | 114 | 100 | 85 | 11 | 36,086 | 62,753 |
| Dedicated syrupUSDC | 43,059 | 39,814 | 4,907 | 1,507 | 6,025 | 1,560 | 0 | 85,677 | 182,549 |
| Late USD₮0 | 6,756 | 6,428 | 439 | 489 | 454 | 478 | 0 | 15,451 | 30,495 |

Daily counts reconcile exactly to these raw counts. Seventeen emitted-flow
measures per market — 51 comparisons in total — independently sum to the same
values in raw events and the daily layer.

## Archive-RPC reconciliation

The checkpoint rule was written to
`data/morpho_phase4_rpc_checkpoint_plan.json` before calls were made: anchor,
end of first scoped-event block, end of the lower-median ordered-event block,
and end of the final allowed block. Its SHA-256 is
`17eeec9fd829a9649a87a0681150a4c23854429d90764eeb94b1c7f554983804`.

| Archetype | Anchor | Start | Mid | End | Matches |
|---|---:|---:|---:|---:|---:|
| Early shared USDC | 355887375 | 358881054 | 449327957 | 495647033 | 4/4 |
| Dedicated syrupUSDC | 355887375 | 373644710 | 419106522 | 495647033 | 4/4 |
| Late USD₮0 | 355887375 | 413594451 | 445271692 | 495647033 | 4/4 |

Each comparison covers exact
`totalSupplyAssets`, `totalSupplyShares`, `totalBorrowAssets` and
`totalBorrowShares` at end of block. The separate Phase 4 SQLite/WAL cache has
12 valid unique rows, contiguous progress `0..11`, integrity `ok`, and zero
invalid, duplicate, gap or orphan defects. The final offline run reused all
12 responses and made no archive call. Phase 3's selection cache was not
modified.

Aggregate collateral is not in this RPC comparison because Morpho exposes no
market-level collateral total. Its zero anchor and all event deltas are checked,
but that field has no independent single-call equivalent.

## QA result

| Check | Result |
|---|---|
| Expected rows | 1,215 / 1,215 |
| Per-market calendar coverage | 405 / 405 for all three |
| Duplicate `(market_id, day_utc)` keys | 0 |
| Calendar gaps | 0 |
| Unexplained required NULLs | 0 |
| Previous close ≠ next opening | 0 |
| Daily event-sequence/count defects | 0 |
| Raw family-count mismatches | 0 / 24 |
| Raw flow-amount mismatches | 0 / 51 |
| Raw event-key or ordering duplicates | 0 |
| Rounding defects | 0 / 129,881 applicable |
| Invalid/negative state defects | 0 |
| Inactive non-zero state/flow defects | 0 |
| RPC market-total mismatches | 0 / 12 |

## Rare-branch coverage

- Non-zero `feeShares`: **0 events** across all three fixed markets. The
  transition is implemented from emitted `AccrueInterest.feeShares`, but it is
  not empirically exercised here.
- Non-zero `badDebtAssets` or `badDebtShares`: **0 events**. The early USDC
  market has 11 ordinary `Liquidate` logs, all with zero bad debt. The bad-debt
  write-off branch is implemented but not empirically exercised.

Both remain explicit non-blocking coverage gaps for Phase 4 acceptance and
future final limitations. They were not used to change the market selection.

## Measured cost and 45-market projection

Final offline run on the local machine:

- source scan: 786,571,394 bytes (0.732552 GiB) in 19.755 seconds;
- selected raw rows: 275,797 / 176,785,557 JSONL bytes;
- SQL build and QA: 89.265 seconds;
- complete wall time: 117.260 seconds;
- prototype SQLite: 415,236,096 bytes;
- sample: 15 deterministic rows;
- GBA bytes billed: **0**.

The Phase 2 population already supplies the exact all-45 event count:
1,231,462, or 4.465103× the prototype event count. A full calendar has 18,225
rows, or 15× the prototype output. Conservatively scaling the larger of the
event and row factors and adding 25% headroom gives:

- SQL replay estimate: **498 seconds** (about 8.3 minutes);
- database estimate: **7,785,676,800 bytes / 7.250977 GiB**;
- existing source plus projected database: **7.983528 GiB**.

That is within the accepted 8–10 GiB engineering gate. It is deliberately
conservative because a 45-market run can scan the immutable shards once; source
I/O does not multiply by 15. This is a local engineering projection, not a
BigQuery dry run and not permission to start Phase 5 or the full Phase 6 build.

## Artifacts and fingerprints

- `sql/10_market_day_prototype.sql` —
  `c989c4d9985785c53ce8dfa6006d5898e5d64348e946f22e08ccbc15c3be035f`;
- `sql/90_qa_market_day_prototype.sql` —
  `ff43c5ce72aac30052e766db635770f3e69c1cb285ba8db8ee5c79c4197e5272`;
- `scripts/build_morpho_market_day_prototype.py` —
  `a298a1f2e00f9751dbf89be4e9b3dac4c89a074f31fd4bcab13e383954fa9c45`;
- `data/market_day_prototype_sample.csv` — 15 rows,
  `7bb1417d33228965ade08ba5504f36fb0d65b31eed1c6656d8e1b813fdbc7053`;
- `data/morpho_market_day_prototype_qa.json` — complete machine-readable QA;
- `data/morpho_phase4_rpc_checkpoint_plan.json` and
  `data/morpho_phase4_rpc_checkpoint_evidence.json` — bounded RPC plan/evidence;
- ignored local SQLite database and cache under `data/tmp/`.

## What this does not prove

The prototype does not prove the correctness of all 45 markets, wallet
positions or cohorts; DRIP reward receipt; the final retention/uplift metrics;
incentive effectiveness; or causality. It also does not empirically validate
non-zero fee-share minting or bad-debt write-offs. Phase 5 remains locked until
the user explains the executed grain/JOIN/replay logic and explicitly accepts
Phase 4 closure.
