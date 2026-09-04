# Morpho event coverage checkpoint

Access date: **2026-08-31**  
Status: **Phase 2 `COMPLETE — accepted` on 2026-08-31. The full-window RPC extraction and independent QA are complete; no full-window GBA query was run.**

## Outcome

- The official Morpho Blue deployment on Arbitrum is [`0x6c247b1F6182318877311737BaC0844bAa518F5e`](https://docs.morpho.org/developers/contracts/addresses/). Queries use its lowercase form, `0x6c247b1f6182318877311737bac0844baa518f5e`.
- Google Blockchain Analytics contains Morpho logs on 2026-08-17, so the checked dataset is fresh through the +180 calendar date.
- On the bounded UTC day `[2026-08-17 00:00:00, 2026-08-18 00:00:00)`, the 45 DRIP-eligible market IDs produced 2,087 matching rows in both `logs` and `decoded_events`. There were no missing keys, topic mismatches, duplicate candidate keys, required-key NULLs, or removed rows.
- The `decoded_events` rows are not semantically decoded for this contract: all 2,087 checked rows have a blank `event_signature` and `args IS NULL`. Their keys and topics mirror raw logs, but they do not supply participant or numeric fields.
- A deterministic ten-row sample was independently checked against receipts from the official Arbitrum public RPC. All ten rows passed the applicable contract, event type, market ID, participant-role address, assets/shares or event-specific amount, block, transaction, transaction index, and log index checks.
- The bounded GBA/RPC work established the raw-log fallback. The later full-window RPC snapshot now provides complete scoped coverage for `[2025-07-09 13:00:00, 2026-08-18 00:00:00)`; its independent QA is recorded in [`MORPHO_FULL_WINDOW_RPC_QA.md`](MORPHO_FULL_WINDOW_RPC_QA.md). Full-window GBA equality was not tested because the scans exceed the cost gate.

## Primary sources and schemas

The contract address comes from [Morpho's deployment registry](https://docs.morpho.org/developers/contracts/addresses/). Event definitions and indexed-field layouts come from the official [`EventsLib.sol`](https://github.com/morpho-org/morpho-blue/blob/main/src/libraries/EventsLib.sol). Independent receipts and blocks were requested from the [official Arbitrum One public RPC](https://docs.arbitrum.io/for-devs/dev-tools-and-resources/chain-info), whose chain ID is `42161`.

The checked Google Blockchain Analytics authorized views are:

- `bigquery-public-data.goog_blockchain_arbitrum_one_us.logs`
- `bigquery-public-data.goog_blockchain_arbitrum_one_us.decoded_events`

Both are monthly time-partitioned on `block_timestamp`, as documented in the [Google Blockchain Analytics schema](https://docs.cloud.google.com/blockchain-analytics/docs/schema). Address comparisons use lowercase, following the same schema guidance.

The raw-log grain is one emitted log. The tested candidate unique key is:

`block_number + transaction_hash + log_index`

For deterministic state reconstruction, the total event order is:

`block_number, transaction_index, log_index`

`block_timestamp` is useful for windows but is not an ordering key within a block.

## Official event map

| Event | Official signature | Topic 0 |
|---|---|---|
| Supply | `Supply(bytes32,address,address,uint256,uint256)` | `0xedf8870433c83823eb071d3df1caa8d008f12f6440918c20d75a3602cda30fe0` |
| Withdraw | `Withdraw(bytes32,address,address,address,uint256,uint256)` | `0xa56fc0ad5702ec05ce63666221f796fb62437c32db1aa1aa075fc6484cf58fbf` |
| Borrow | `Borrow(bytes32,address,address,address,uint256,uint256)` | `0x570954540bed6b1304a87dfe815a5eda4a648f7097a16240dcd85c9b5fd42a43` |
| Repay | `Repay(bytes32,address,address,uint256,uint256)` | `0x52acb05cebbd3cd39715469f22afbf5a17496295ef3bc9bb5944056c63ccaa09` |
| SupplyCollateral | `SupplyCollateral(bytes32,address,address,uint256)` | `0xa3b9472a1399e17e123f3c2e6586c23e504184d504de59cdaa2b375e880c6184` |
| WithdrawCollateral | `WithdrawCollateral(bytes32,address,address,address,uint256)` | `0xe80ebd7cc9223d7382aab2e0d1d6155c65651f83d53c8b9b06901d167e321142` |
| Liquidate | `Liquidate(bytes32,address,address,uint256,uint256,uint256,uint256,uint256)` | `0xa4946ede45d0c6f06a0f5ce92c9ad3b4751452d2fe0e25010783bcab57a67e41` |
| AccrueInterest | `AccrueInterest(bytes32,uint256,uint256,uint256)` | `0x9d9bd501d0657d7dfe415f779a620a62b78bc508ddc0891fbbd8b7ac0f8fce87` |

The topic hashes were derived from these exact official signatures through Arbitrum RPC `web3_sha3`.

## Bounded population QA

Population: the official Morpho contract, the eight critical event hashes, and the 45 DRIP-eligible market IDs on the probe day.

| Check | Result |
|---|---:|
| Raw-log rows | 2,087 |
| `decoded_events` rows | 2,087 |
| Exact candidate-key matches | 2,087 |
| Raw-only / decoded-only rows | 0 / 0 |
| Topic mismatches | 0 |
| Duplicate candidate keys, raw / decoded | 0 / 0 |
| Required-key NULL rows, raw / decoded | 0 / 0 |
| Removed rows, raw / decoded | 0 / 0 |
| Blank GBA event signatures | 2,087 |
| NULL GBA args | 2,087 |

| Event | Rows | Distinct eligible markets | First UTC | Last UTC |
|---|---:|---:|---|---|
| Supply | 497 | 8 | 2026-08-17 00:02:52 | 2026-08-17 23:55:34 |
| Withdraw | 605 | 8 | 2026-08-17 00:04:28 | 2026-08-17 23:43:13 |
| Borrow | 8 | 4 | 2026-08-17 01:42:37 | 2026-08-17 19:28:45 |
| Repay | 10 | 4 | 2026-08-17 03:38:51 | 2026-08-17 16:03:40 |
| SupplyCollateral | 9 | 3 | 2026-08-17 07:07:45 | 2026-08-17 19:28:45 |
| WithdrawCollateral | 4 | 2 | 2026-08-17 03:38:51 | 2026-08-17 16:03:40 |
| Liquidate | 1 | 1 | 2026-08-17 10:25:21 | 2026-08-17 10:25:21 |
| AccrueInterest | 953 | 13 | 2026-08-17 00:02:52 | 2026-08-17 23:55:34 |

These counts describe only the bounded probe day. Zero rows for a market or family outside this population cannot be inferred from them.

## Deterministic ten-event verification

The SQL first selects one event from each available critical family using a fixed market-priority and onchain-order rule. It then adds the last non-duplicate event before `2026-08-17 13:00:00 UTC` and the first non-duplicate event at or after that timestamp. All eight families were available, so no replacement rule was needed.

The exact evidence is stored in [`../data/morpho_event_sample_10.csv`](../data/morpho_event_sample_10.csv). It contains ten unique candidate keys and all eight event families. The comparison used nine receipts because one transaction contains both a `Repay` and a `WithdrawCollateral` log.

For each row, the verifier checked:

1. RPC chain ID, receipt transaction hash/index, block number, block timestamp, and receipt log index;
2. emitting address against the official Morpho contract;
3. topic 0 against the official event signature hash and topic 1 against the market ID;
4. indexed participant roles from topics and non-indexed fields from 32-byte ABI words in `data`;
5. GBA raw/decoded-index key and topic equality against the same receipt log.

All ten rows are `PASS`. Participant roles are stored explicitly as `caller`, `on_behalf`, `receiver`, or `borrower`. `AccrueInterest` has no participant address in the official event ABI, so that field is not applicable rather than missing. Numeric values are preserved as decimal strings in native integer units; no token-decimal or USD conversion is implied.

## Cost checkpoint and blocker

| Query scope | Dry-run upper bound / actual |
|---|---:|
| One-day raw component | 1,869,752,296 bytes |
| One-day decoded-index component | 2,542,944,018 bytes |
| One-day combined dry-run upper bound | 4,412,696,314 bytes (4.11 GiB) |
| Executed bounded job, bytes processed | 3,522,328,461 bytes (3.28 GiB) |
| Executed bounded job, bytes billed | 3,633,315,840 bytes (3.38 GiB) |
| Full-window minimal `decoded_events` profile | 1,018,759,566,134 bytes (948.79 GiB) |
| Full-window raw-log profile including `data` | 1,744,775,870,714 bytes (1,624.95 GiB / 1.59 TiB) |

The intended full coverage interval is `[2025-07-09 13:00:00 UTC, 2026-08-18 00:00:00 UTC)`: eight weeks before campaign start through the complete +180 calendar day. Its two dry-run estimates are upper bounds, but both are far above the project's 8–10 GiB gate, so those queries were not executed. Google states that Blockchain Analytics follows normal [BigQuery pricing](https://cloud.google.com/blockchain-analytics/pricing); partition filters alone did not make these authorized-view scans sufficiently small.

An adaptive one-day RPC feasibility test reproduced all 2,087 GBA rows with zero missing, extra, duplicate, topics-mismatch, or raw-data-mismatch rows. A stratified pilot and append-only resume test then passed before the authorized full-window RPC extraction. The completed snapshot contains 3,157 verified shards and 1,231,462 unique scoped events. Independent QA found zero gaps, overlaps, checksum, row-count, scope, duplicate-key, removed-log, or ordering defects and reconciled exact UTC daily/family totals. See [`MORPHO_FULL_WINDOW_RPC_QA.md`](MORPHO_FULL_WINDOW_RPC_QA.md).

All technical Phase 2 Definition of Done criteria were satisfied and the user accepted closure on 2026-08-31. Position reconstruction belongs to the now-current Phase 3 and remains gated by its own user checkpoint.

## What this evidence does and does not prove

The sample proves that ten deterministically selected GBA index rows identify real raw logs emitted by the official Morpho contract, and that the official ABI can recover the event type, market ID, applicable participant roles, assets/shares or event-specific numeric fields, block, transaction, and log ordering without unexplained discrepancies. Those fields are suitable inputs for a later attempt to reconstruct market state and a wallet position.

The ten-row sample alone does **not** prove complete historical coverage. That separate claim now rests on the full append-only RPC manifest and independent population QA, not on extrapolating the sample or the three validated strata.

Neither evidence layer proves the correctness of future reconstructed positions, reward receipt, DRIP attribution, retention, or causal impact. Full-history GBA equality also remains untested; cross-source equality is bounded to the deterministic sample and validated pilot windows.
