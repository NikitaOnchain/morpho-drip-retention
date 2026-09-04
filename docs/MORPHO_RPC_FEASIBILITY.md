# Morpho one-day RPC feasibility test

Access date: **2026-08-31**  
Status: **PASS for the bounded day; Phase 2 remains CURRENT and no full-window extraction was started.**

## Dataset and grain

This test asks whether the official Arbitrum One public RPC can reproduce the exact Google Blockchain Analytics population already used for Phase 2 QA.

The comparable population is:

- official Morpho Blue contract `0x6c247b1f6182318877311737bac0844baa518f5e`;
- the eight critical Morpho event hashes;
- the 45 DRIP-eligible market IDs;
- `[2026-08-17 00:00:00 UTC, 2026-08-18 00:00:00 UTC)`.

This definition is important: “all events” here means all events in the prior 2,087-row GBA comparison population. Unrelated Morpho event families and non-eligible market IDs are intentionally outside this test.

The grain is one raw onchain log. The comparison key is:

`block_number + transaction_hash + log_index`

The deterministic order is:

`block_number, transaction_index, log_index`

## Method

The reproducible runner is [`../scripts/rpc_morpho_event_feasibility.ps1`](../scripts/rpc_morpho_event_feasibility.ps1). The GBA reference query is [`../sql/01_rpc_feasibility_gba_reference.sql`](../sql/01_rpc_feasibility_gba_reference.sql).

1. The script used `eth_chainId` to verify Arbitrum One (`42161`).
2. Binary searches with `eth_getBlockByNumber` found the first block at or after each UTC boundary.
3. The resulting half-open block interval was `[495303648, 495647034)`, or 343,386 blocks.
4. `eth_getLogs` filtered the contract address, eight event hashes at topic 0, and 45 market IDs at topic 1.
5. The initial range was 20,000 blocks. Successful low-volume ranges could expand up to 80,000 blocks; failed ranges would retry and then halve down to one block.
6. RPC logs, counters, errors, ranges, and `next_block` were checkpointed after every successful range. The final checkpoint is marked complete.
7. RPC and GBA rows were normalized to lowercase and compared on key, full topics array, and raw `data` bytes.

Raw resumable files are under `data/tmp/rpc_feasibility_2026-08-17/` and are excluded from version control. Small QA summaries are retained in `data/`.

## Reconciliation result

| Check | Result | Rate |
|---|---:|---:|
| GBA rows | 2,087 | 100.00% reference |
| RPC rows | 2,087 | 100.00% of reference |
| Matched unique keys | 2,087 | 100.00% |
| Missing in RPC | 0 | 0.00% |
| Extra in RPC | 0 | 0.00% |
| RPC duplicate-key groups | 0 | 0.00% |
| GBA duplicate-key groups | 0 | 0.00% |
| Topics mismatches | 0 | 0.00% |
| Raw-data mismatches | 0 | 0.00% |

The one-day comparison is an exact match.

## RPC ranges, retries, and errors

| Operational check | Result |
|---|---:|
| Total JSON-RPC attempts | 65 |
| Successful JSON-RPC responses | 62 |
| `eth_getLogs` attempts | 10 |
| Successful block ranges | 10 |
| Retries | 3 |
| Error attempts | 3 |
| Adaptive expansions | 2 |
| Adaptive reductions | 0 |

The ten non-overlapping ranges covered the entire block interval. They began with two 20,000-block ranges, then used 40,000-block ranges, and expanded the final low-volume tail to an 80,000-block target. All ten `eth_getLogs` requests succeeded on their first attempt.

The three errors were 60-second timeouts from `eth_getBlockByNumber` during UTC-boundary binary search. Each retry succeeded. There were no `eth_getLogs` errors, no exhausted retries, and no missing block range. This is a **medium operational risk with high confidence**: the public RPC is adequate for the bounded extraction, but timestamp-boundary lookups can dominate wall time and require resumability.

## Time and data volume

| Measure | Result |
|---|---:|
| Successful `eth_getLogs` response time, summed | 5.734 seconds |
| Timeout delay from three failed block lookups | approximately 180 seconds |
| Initial RPC run wall time observed by the command runner | approximately 204 seconds |
| Total RPC response bytes | 1,664,679 bytes (1.59 MiB) |
| `eth_getLogs` response bytes | 1,555,804 bytes (1.48 MiB) |
| Serialized RPC log checkpoint | 1,485,476 bytes (1.42 MiB) |
| Local GBA reference CSV | 1,162,100 bytes (1.11 MiB) |

The GBA reference query had a dry-run upper bound of 3,175,809,476 bytes (2.96 GiB). The executed job processed 3,064,373,457 bytes and billed 3,064,987,648 bytes (both approximately 2.85 GiB); its final BigQuery execution duration was 2.526 seconds. This stays inside the 8–10 GiB bounded-query gate.

The published evidence files are:

- [`../data/morpho_rpc_feasibility_2026-08-17_summary.json`](../data/morpho_rpc_feasibility_2026-08-17_summary.json)
- [`../data/morpho_rpc_feasibility_2026-08-17_summary.csv`](../data/morpho_rpc_feasibility_2026-08-17_summary.csv)
- [`../data/morpho_rpc_feasibility_2026-08-17_ranges.csv`](../data/morpho_rpc_feasibility_2026-08-17_ranges.csv)
- [`../data/morpho_rpc_feasibility_2026-08-17_errors.csv`](../data/morpho_rpc_feasibility_2026-08-17_errors.csv)
- [`../data/morpho_rpc_feasibility_2026-08-17_mismatches.csv`](../data/morpho_rpc_feasibility_2026-08-17_mismatches.csv)

The mismatch file contains only its header because every mismatch count is zero.

## Interpretation and limits

This test provides high-confidence evidence that adaptive `eth_getLogs` can reproduce GBA's raw Morpho population for one complete UTC day, including exact raw payloads. It also demonstrates working retries and resumable checkpoints.

It does **not** prove that the public endpoint will remain stable across the full baseline, campaign, and post-campaign history. It does not exclude historical RPC pruning, rate limits, provider-specific gaps, or failures that appear only over longer runs. It also does not prove position reconstruction, rewards, retention, or DRIP attribution.

The approved multi-day follow-up subsequently passed across baseline, campaign-end, and post-period strata, including an active-data resume test. See [`MORPHO_RPC_STRATIFIED_PILOT.md`](MORPHO_RPC_STRATIFIED_PILOT.md). Phase 2 remains open because the complete 404-day history has not been extracted.
