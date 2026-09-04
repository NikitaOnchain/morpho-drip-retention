# Morpho append-only RPC resume test

Access date: **2026-08-31**  
Status: **PASS for bounded persistence and resume; full-window extraction remains unauthorized.**

## Outcome

The Phase 2 RPC runner now persists every completed half-open block range as one write-once JSONL shard. A shard is first written beside its final path with a `.part` suffix, hashed, atomically renamed, hashed again, parsed, and counted. The script refuses to overwrite an existing final shard or `.part` file.

`manifest.json` is the resume authority. Each shard entry records:

- `range_id`, `from_block`, and `to_block_exclusive`;
- `row_count`, filename, byte size, and SHA-256 checksum;
- `status=verified` plus request and timing metadata.

Before a resumed process makes another `eth_getLogs` request, it verifies every manifest shard in order: status, path safety, file presence, checksum, row count, row block bounds, global event-key uniqueness, and continuous block coverage from `start_block` through `next_block`. An orphan `.part`, an unreferenced final shard, checksum failure, duplicate key, gap, or overlap stops the run rather than advancing the cursor.

## Bounded active-data test

The test reused the previously reconciled GBA reference for `[2026-02-18 00:00:00 UTC, 2026-02-19 00:00:00 UTC)`. No new BigQuery scan was executed.

| Check | Result |
|---|---:|
| Block interval | `[433213243, 433559875)` |
| Intentional-stop shard | `[433213243, 433233243)` |
| Rows at stop / unique keys | 270 / 270 |
| Resume block | `433233243` |
| Final verified shards | 10 |
| Final RPC / GBA rows | 6,358 / 6,358 |
| Missing / extra | 0 / 0 |
| Duplicate-key groups | 0 |
| Topics / raw-data mismatches | 0 / 0 |
| Manifest gaps / overlaps | 0 / 0 |
| Completed ranges re-fetched | 0 |
| Remaining `.part` files | 0 |

The first shard had SHA-256 `6bdfa41966b623567b05e2aa7b14837a081e8dbac2d3238ab383e15feedae132` before and after resume. Its filesystem modification timestamp also remained `2026-08-31T12:20:52.0662269Z`, consistent with write-once behavior. The resumed process reported one verified shard and 270 verified rows loaded before continuing with range 2.

The complete bounded run used ten `eth_getLogs` requests and 61 total RPC requests including block-boundary lookup. It wrote 4,089,667 bytes of raw JSONL shards. All requests succeeded without retry in this run.

## Independent file-level QA

After the runner completed, a separate PowerShell check read the final files directly rather than trusting the summary. It recomputed all ten SHA-256 checksums and row counts, parsed every JSONL row, rebuilt the candidate event key `(block_number, transaction_hash, log_index)`, rechecked range continuity, and independently compared key, topics, and raw data with the local GBA reference.

Results: ten verified statuses, zero checksum mismatches, zero row-count mismatches, zero out-of-range rows, 6,358 rows and 6,358 unique keys, zero gaps or overlaps, and zero GBA reconciliation defects.

## Scope and limitation

This test validates the storage contract and bounded resume behavior on one active day. It removes the prior quadratic whole-file checkpointing blocker. It does not prove complete coverage of the 404-day research window, and it does not authorize that extraction. Phase 2 remains CURRENT; Phase 3 remains LOCKED.

## Evidence

- Runner: `scripts/rpc_morpho_event_feasibility.ps1`
- Compact summary: `data/morpho_rpc_feasibility_2026-02-18_shard_resume_summary.json`
- Per-range checksums: `data/morpho_rpc_feasibility_2026-02-18_shard_resume_ranges.csv`
- Stop/resume evidence: `data/morpho_rpc_feasibility_2026-02-18_shard_resume_resume_test.json`
- Independent QA result: `data/morpho_rpc_append_only_resume_qa.json`
- Raw manifest and shards: `data/tmp/rpc_feasibility_2026-02-18_shard_resume/` (ignored)
