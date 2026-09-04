# Morpho full-window RPC extraction: independent QA

Access and QA date: **2026-08-31**  
Status: **PASS — Phase 2 `COMPLETE — accepted` on 2026-08-31.**

## Scope

The checked population is limited to:

- Arbitrum One;
- the official Morpho core contract `0x6c247b1f6182318877311737bac0844baa518f5e`;
- the eight Phase 2 event families;
- the 45 DRIP-eligible market IDs in `data/drip_morpho_markets.csv`;
- the half-open UTC interval `[2025-07-09 13:00:00, 2026-08-18 00:00:00)`, represented by block interval `[355887376, 495647034)`.

No extraction was rerun during this QA. No full-window Google Blockchain Analytics query was executed.

## Validation method

Two independent local passes were used.

1. A read-only preflight parsed `manifest.json`, checked sequential range IDs and half-open boundaries, inventoried the shard directory, and recomputed every shard SHA-256. It also reconciled declared bytes, rows, removed flags, and event-family totals.
2. `scripts/qa_morpho_full_window.py` independently re-read all JSONL rows. It recomputed checksums and row counts, checked scope and shard bounds, enforced global key uniqueness and onchain ordering, counted removed logs, and rebuilt daily and event-family totals.

UTC day boundaries were resolved with the official Arbitrum One public RPC. For each UTC boundary, the QA selected the first block whose timestamp is greater than or equal to the boundary and verified that the preceding block timestamp is earlier. The resulting boundary document was then reconciled exactly with the daily output.

## Results

| Check | Result |
|---|---:|
| Manifest status | `complete` |
| Block coverage | 139,759,658 / 139,759,658 blocks |
| Verified manifest entries | 3,157 |
| Actual shard files | 3,157 |
| Shard bytes | 786,571,394 |
| Total rows | 1,231,462 |
| Unique `(block_number, transaction_hash, log_index)` keys | 1,231,462 |
| Duplicate keys | 0 |
| Gaps / overlaps | 0 / 0 |
| Missing / unreferenced shard files | 0 / 0 |
| Remaining `.part` files | 0 |
| Checksum mismatches | 0 |
| Row-count mismatches | 0 |
| Per-shard family-count mismatches | 0 |
| Rows outside their shard bounds | 0 |
| Scope mismatches | 0 |
| Removed logs | 0 |
| Ordering violations | 0 |
| Manifest aggregate mismatches | 0 |
| Daily reconciliation mismatches | 0 |

The previously documented range-38 validation-bug orphan remains preserved under `quarantine/`. It is outside `shards/`, is not referenced by the manifest, and was not counted in this population.

## Event-family counts

| Event family | Rows |
|---|---:|
| Supply | 238,845 |
| Withdraw | 226,138 |
| Borrow | 45,285 |
| Repay | 32,187 |
| SupplyCollateral | 47,604 |
| WithdrawCollateral | 27,868 |
| Liquidate | 306 |
| AccrueInterest | 613,229 |
| **Total** | **1,231,462** |

The family total equals both the raw row count and the sum of all daily `event_count` values.

## UTC boundaries and daily output

- Boundary rows: **406**.
- Daily buckets: **405** — one partial first day followed by 404 complete UTC days.
- First boundary: `2025-07-09T13:00:00Z` → block `355887376`.
- First midnight boundary: `2025-07-10T00:00:00Z` → block `356045737`.
- Final exclusive boundary: `2026-08-18T00:00:00Z` → block `495647034`.
- Boundary JSON/CSV mismatches: **0**.
- Adjacent daily time/block discontinuities: **0**.
- Daily rows whose family sum differs from `event_count`: **0**.

As a compact temporal profile, 13 daily buckets contain zero scoped events; all are in the early baseline between 2025-07-09 and 2025-07-30. The median daily count is 2,347 and the maximum is 17,716 on 2025-11-04. These are not treated as coverage defects because the block intervals remain present and verified even when no scoped log was emitted. The large days are distribution observations, not state or retention conclusions.

The successful boundary run made 418 HTTP requests containing 7,946 RPC items, used 6 retries, and received 17,150,820 response bytes. Initial attempts stopped before shard scanning because the public endpoint rejected Python's default User-Agent with HTTP 403 and later rate-limited unpaced requests with HTTP 429. The QA client was changed to use an explicit User-Agent, bounded retries, and a minimum request interval. Those transport incidents did not modify the manifest or raw shards.

## Reproducibility artifacts

| Artifact | SHA-256 |
|---|---|
| `data/raw/morpho_full_window/manifest.json` | `c8552428187094e5aad725193f2e3023e622ddc4ab37428f1414c375e7d6be58` |
| `scripts/qa_morpho_full_window.py` | `013fdaebf5e352c84b9bb6424be4a7c6c1258da77a47f95d1bbbdcfa61b10136` |
| `data/morpho_full_window_qa_summary.json` | `d05d1cafdab8861ac5a7cb2cf2c39c84d270008ad6db58bbbcc9bd6aba9e6f93` |
| `data/morpho_full_window_daily_event_counts.csv` | `e8f0faa3826e9c85d5dfa3aad08d957ecf07d70dafe96745f0ccfa324e5482bd` |
| `data/morpho_full_window_event_family_counts.csv` | `2112325ed330838390cb557ce5f40e710786bf9d4e5d1cf36f30add22f4a2935` |
| `data/morpho_full_window_day_boundaries.csv` | `1f72f279c3de167f8bcd14b161ff2b1bf2def99c627d08f04147c58d38a9121e` |
| `data/raw/morpho_full_window/day_boundaries.json` | `da1b7c58406301f8b282ae798344dba292f2b0a650ae1f451235f84c8a261ac0` |

The raw shards and raw manifest are intentionally ignored by Git. The compact QA outputs and this report are the reviewable evidence layer.

## Phase 2 closure assessment

Phase 2's Definition of Done is satisfied:

- the official contract, event definitions, and Arbitrum source are documented;
- raw-event coverage is complete through the full authorized baseline/campaign/+180 window;
- the raw-log grain, unique key, and deterministic ordering rule are fixed;
- required-key NULL and duplicate checks passed on the bounded GBA population, while full RPC QA found zero duplicate keys or malformed required scope/order fields;
- the deterministic ten-event sample passed independent field-level RPC comparison 10/10;
- GBA's missing semantic decode is explained and the official-ABI raw-log fallback is documented;
- bounded GBA work passed the 8–10 GiB gate, while the prohibited full-window GBA query was not run;
- the user correctly stated what the ten-event sample and stratified windows prove and do not prove.

The user explicitly accepted Phase 2 closure on 2026-08-31. Phase 3 is now `CURRENT`; this QA remains the final Phase 2 coverage evidence.

## Limitations

This QA proves complete, internally consistent raw-log coverage only for the stated contract × event-family × eligible-market scope and block interval. It does not prove completeness for other Morpho contracts, event families, markets, or dates. Full-history GBA equality was not tested; GBA agreement remains bounded to the previously validated strata and ten-event sample.

The result does not reconstruct market state or wallet positions and says nothing by itself about reward receipt, retained demand, DRIP attribution, or causal impact. Those questions belong to later phases.
