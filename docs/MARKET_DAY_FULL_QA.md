# Phase 6 full 45-market daily-state build and QA

Status: **TECHNICAL PASS — awaiting user acceptance**.  
Evidence date: **2026-09-02**.

## Scope and output grain

The production layer was built only from the immutable Phase 2 RPC shards and
the accepted Phase 1 eligibility bridge. No `eth_getLogs` extraction or GBA
query was run. Frozen metrics v1.0 were not changed; the pre- and post-build
`docs/METRICS.md` SHA-256 is
`2774c0856ca66da4611523289a7e1c4da937ce208cad9799c2f008753eca2ba2`.

The output grain is exactly one row per `market_id × UTC bucket` over the
half-open interval `[2025-07-09T13:00:00Z, 2026-08-18T00:00:00Z)`. The first
bucket is partial; the other buckets are midnight-to-midnight UTC days.

| Measure | Observed | Expected | Result |
|---|---:|---:|---|
| Markets | 45 | 45 | PASS |
| UTC buckets per market | 405–405 | 405 | PASS |
| Market-day rows | 18,225 | 18,225 | PASS |
| Unique `(market_id, day_utc)` keys | 18,225 | 18,225 | PASS |
| Active rows | 13,743 | documented status | PASS |
| Explicit pre-first-event inactive rows | 4,482 | documented status | PASS |

## Executable pipeline

The engine is Python stdlib SQLite 3.50.4. Protocol integers are stored as
unsigned decimal text and evaluated with exact Python-bigint SQLite UDFs. The
accepted Phase 4 replay module is executed over the 45-row `market_dim`, then
`sql/20_market_day_full.sql` materializes the production table. Events are
ordered strictly by `(block_number, transaction_index, log_index)`.

The database was built as
`data/tmp/morpho_market_day_full_v1.building.sqlite` and atomically renamed to
`data/tmp/morpho_market_day_full_v1.sqlite` only after all blocking SQL checks,
RPC comparisons and SQLite integrity checks passed. The published database is
ignored by Git; its SHA-256 is
`80aca74cc5e43db03fd93c69d7ad448ac9afdec5f9566a6b833ec11f7e5c9543`.

## Population reconciliation

All 3,157 verified shards and 786,571,394 bytes were reread. Their checksums,
row counts, scope, ordering, removed flags and raw event keys passed. The full
1,231,462-event population was replayed and its daily event count sums back to
1,231,462.

| Event family | Raw events | Daily count | Result |
|---|---:|---:|---|
| Supply | 238,845 | 238,845 | PASS |
| Withdraw | 226,138 | 226,138 | PASS |
| Borrow | 45,285 | 45,285 | PASS |
| Repay | 32,187 | 32,187 | PASS |
| SupplyCollateral | 47,604 | 47,604 | PASS |
| WithdrawCollateral | 27,868 | 27,868 | PASS |
| Liquidate | 306 | 306 | PASS |
| AccrueInterest | 613,229 | 613,229 | PASS |

The database contains 360/360 matching market-family count comparisons and
765/765 matching market-flow comparisons. There are zero raw key duplicates,
deterministic-order duplicates, required NULLs, calendar gaps, opening/closing
continuity defects, daily sequence-delta defects, invalid unsigned states or
unexplained negative balances. Exact rounding checks are 542,761/542,761 PASS;
688,746 rows are not applicable, including the 45 anchors.

## Eligibility integrity

The bridge remains at `market_id × epoch × side`: 469 rows, 469 unique keys and
45 markets. Production SQL first rolls it up to one row per market and only
then joins it to the daily layer. The join preserves 18,225 rows exactly.
Shared-pool ARB has no market-allocation column; only exact dedicated-market
allocations are retained. Direct-vault rows are absent, so the 505,000 ARB
direct-vault budget is not attributed to underlying markets.

## Independent RPC evidence

The checkpoint rule was committed before calls. It queries all 45 zero-state
anchors, then selects five markets by ascending
`SHA256("morpho-phase6-rpc-sample-v1|" + market_id)` and queries the end of the
first-event block, lower-median-event block and final replay block for each.
This yields 60 `market(bytes32)` calls in a separate Phase 6 SQLite/WAL cache;
the sealed Phase 3 selection database was not opened for writes.

The cache has integrity `ok`, 60 unique valid entries, contiguous progress
0–59 and zero invalid, error, duplicate, gap or orphan records. Its initial
network fill ran from `2026-09-02T12:33:24.746036Z` to
`2026-09-02T12:34:10.340689Z` (45.594653 seconds). The final cache-only replay
used 60 hits and zero new archive calls. Reconstructed market totals match RPC
at 60/60 checkpoints.

## Prototype and rare-branch QA

All 1,215 rows for the three frozen Phase 4 markets match the accepted Phase 4
result exactly; symmetric row differences are zero. The accepted Phase 4 local
database was rebuilt once offline from the same immutable shards and its
existing 12-entry cache after a pre-publication comparison-handle defect; its
restored result again passed 12/12 RPC comparisons and all blocking checks.
No production database was published before this repair.

The full population contains three liquidations with non-zero bad debt, so the
bad-debt transition is now empirically exercised. Non-zero `feeShares` occurs
zero times; fee-share minting remains implemented from the accepted accounting
specification but is not empirically exercised by this snapshot.

## Runtime and storage

- final immutable-source verification scan: 46.879548 seconds;
- initial RPC cache fill: 45.594653 seconds for 60 calls;
- full replay/materialization: approximately 385.3 seconds, measured between
  the durable input-loaded checkpoint and the post-materialization database
  timestamp;
- final QA/publish resume: 73.270304 seconds, including another immutable scan,
  cache-only validation, integrity check and database checksum;
- published SQLite: 1,878,016,000 bytes (1.749039 GiB);
- maximum observed main+WAL working size: 1.749887 GiB;
- published database plus existing raw shards: 2.481590 GiB;
- free space after publication: 216.916691 GiB;
- GBA billed bytes: 0; new `eth_getLogs` calls: 0.

The measured artifact and working set are below the 10 GiB stop gate.

## Limitations and acceptance gate

Aggregate collateral cannot be checked through a single Morpho market getter;
it is reconstructed from verified zero anchors and every collateral/seizure
delta. RPC state comparison is bounded rather than exhaustive: all 45 anchors
plus three non-anchor checkpoints for five deterministic markets. Non-zero
`feeShares` remains a coverage gap.

This layer proves full-scope state construction and technical QA. It does not
yet calculate retained uplift, wallet cohorts, reward receipt, incentive
effectiveness or causal impact. Phase 6 therefore remains **CURRENT — awaiting
user acceptance**, and Phase 7 remains locked.

