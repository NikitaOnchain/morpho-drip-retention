# Data workspace

Commit only small, reviewable evidence or examples.

Each saved extract must have:

- source and access date;
- producing SQL or API request;
- row grain and expected unique key;
- whether the extract is complete, filtered or sampled;
- a note on any address or transaction privacy considerations.

Large raw exports belong in `data/raw/` or `data/tmp/`, which are ignored by Git. Never store credentials, cookies, wallet secrets or personal identifiers here.

## Phase 7 exact frozen boundaries

Access date: **2026-09-02**.

- `morpho_phase7_boundary_map.csv`: complete 227-row reviewable map from frozen 13:00 UTC timestamp to predecessor and chosen Arbitrum blocks; unique key is `target_timestamp_utc`.
- `morpho_phase7_boundary_map.json`: complete machine-readable copy with hashes, timestamps, roles, bracket evidence and exact inequalities.
- `morpho_phase7_boundary_qa.json`: blocking completeness, monotonicity, adjacency, hash, cache and accepted-day-bracket QA; status `PASS`.
- `morpho_phase7_boundary_manifest.json`: immutable identity binding the target list and outputs to chain 42161, the producing script, accepted Phase 6 database, frozen metrics v1.0, eligibility bridge and production day-boundary snapshot.
- `morpho_phase7_boundary_checkpoint.json`: compact final resume state. The sealed 4,427-header SQLite cache is stored under ignored `data/tmp/`.
- Producing code: `scripts/build_phase7_frozen_boundaries.py`. Network scope was only `eth_chainId` and `eth_getBlockByNumber`; `eth_getLogs` and GBA usage were zero.

## Verified DRIP × Morpho extracts

Access date: **2026-08-31**.

### `drip_morpho_epoch_campaigns.csv`

- Source: Merkl API V4 root campaign records; official Entropy/Arbitrum forum updates and the final allocation chart were used for reconciliation.
- Producing API request: `https://api.merkl.xyz/v4/opportunities?mainProtocolId=morpho&tags=drip&campaigns=true&status=PAST&items=100&page=0`.
- Grain: one official root ARB campaign.
- Expected unique key: `campaign_db_id`.
- Coverage: complete filtered inventory for DRIP Season 1 × Morpho on Arbitrum, 36 rows across epochs 1–12.
- Important: `allocation_arb` is a campaign-level budget. For `shared_market_pool`, it is not a per-market amount.
- Privacy: contract, campaign, and protocol identifiers only; no wallet-level personal identifiers.

### `drip_morpho_markets.csv`

- Source: the `params.markets[].campaignParameters` or dedicated `params.market` fields of the root campaigns listed above.
- Grain: one distinct Morpho market ID.
- Expected unique key: `market_id`.
- Coverage: complete filtered inventory of market IDs explicitly named in the 36 root campaigns; 45 rows.
- `supply_epochs` and `borrow_epochs` are semicolon-delimited epoch numbers after exact duplicate child records were removed.
- Direct Steakhouse vault campaigns have no market ID in their root configuration and are intentionally absent; their 505K ARB remains visible in the campaign extract.
- Privacy: contract and market identifiers only; no wallet-level personal identifiers.

### `morpho_event_sample_10.csv`

- Sources: Google Blockchain Analytics Arbitrum `logs` and `decoded_events`, plus independent `eth_getTransactionReceipt`, `eth_getBlockByNumber`, and `eth_chainId` calls to the official Arbitrum One public RPC.
- Producing SQL: `sql/00_feasibility_morpho_event_coverage.sql`; raw receipt fields were decoded against Morpho's official `EventsLib.sol` definitions.
- Grain: one deterministic raw Morpho event log.
- Expected unique key: `block_number + transaction_hash + log_index`; the saved file has 10 rows and 10 unique keys.
- Coverage: a filtered sample from `[2026-08-17 00:00:00 UTC, 2026-08-18 00:00:00 UTC)`, not a complete history. It contains one row for each of the eight critical event families plus two fixed boundary cases around 13:00 UTC.
- Validation: 10/10 rows match the GBA raw/index key and topics; 10/10 independently match the applicable RPC receipt and ABI-decoded fields. `assets`, `shares`, and other numeric fields remain raw native-unit integer strings.
- Important limitation: GBA's `decoded_events.event_signature` is blank and `args` is NULL for all checked Morpho rows. The semantic columns in this CSV come from the raw RPC log and official ABI, not from GBA's decoder.
- Privacy: all addresses and transaction identifiers are public onchain identifiers. They must not be described as natural persons or reward recipients.

### `morpho_rpc_feasibility_2026-08-17_*`

- Sources: official Arbitrum One public RPC and the bounded GBA raw-log reference produced by `sql/01_rpc_feasibility_gba_reference.sql`.
- Producing code: `scripts/rpc_morpho_event_feasibility.ps1`.
- Grain: `summary` has one test row; `ranges` has one successful `eth_getLogs` block range; `errors` has one failed RPC attempt; `mismatches` has one reconciliation defect and therefore contains only a header when all checks pass.
- Expected keys: range `range_id`; error occurrence fields; mismatch `category + key`. The raw event grain and comparison key remain `block_number + transaction_hash + log_index`.
- Coverage: complete only for the target population on `[2026-08-17 00:00:00 UTC, 2026-08-18 00:00:00 UTC)`. The saved result is 2,087 RPC rows versus 2,087 GBA rows with zero missing, extra, duplicate-key, topics, or raw-data defects.
- Operational evidence: 65 total RPC attempts, ten successful `eth_getLogs` ranges, three retried `eth_getBlockByNumber` timeouts, 1,664,679 response bytes, and a complete resumable checkpoint under ignored `data/tmp/`.
- Privacy: public contract, market, block, and transaction identifiers only. Raw checkpoint files remain ignored to avoid committing larger extracts.

### Stratified RPC pilot files

- `morpho_rpc_stratified_pilot_summary.csv` has one row per baseline, campaign-boundary, or reused post-period window. Its grain is `window_role`; expected unique key is `window_role`.
- `morpho_rpc_full_window_estimate.csv` has one scenario summary row for the proposed full interval. It is an estimate from three days, not observed full-history volume.
- Date-labeled `morpho_rpc_feasibility_*` files contain per-window summaries, ranges, errors, mismatches, and intentional-resume evidence. The `2026-02-18_resume` label is a separate active-data resume probe that reused the local GBA reference without another scan.
- The two new GBA jobs were dry-run first. Their combined upper bound was 8.964 GiB; actual processed volume was 8.634 GiB. The existing 2026-08-17 reference was reused at zero new scan cost.
- All three main windows have zero missing, extra, duplicate-key, topics-mismatch, and raw-data-mismatch rows. The active resume checkpoint preserved 270 unique rows and finished at 6,358 rows without duplicates.
- Raw RPC logs and GBA reference CSVs remain under ignored `data/tmp/`. Only compact evidence is retained in the reviewable data directory.

### Append-only bounded resume files

- `morpho_rpc_feasibility_2026-02-18_shard_resume_summary.*` records the completed bounded run at one-row run grain.
- `morpho_rpc_feasibility_2026-02-18_shard_resume_ranges.csv` has one row per immutable block-range shard; expected key is `range_id`, and every row includes half-open block bounds, row count, filename, status, byte size, and SHA-256 checksum.
- `morpho_rpc_feasibility_2026-02-18_shard_resume_resume_test.json` preserves the one-shard intentional-stop state and the subsequent resume outcome.
- `morpho_rpc_append_only_resume_qa.json` is a compact independent file-level recheck of checksums, counts, keys, continuity, and GBA reconciliation.
- Raw JSONL shards and `manifest.json` remain under ignored `data/tmp/rpc_feasibility_2026-02-18_shard_resume/`.
- Coverage is complete only for `[2026-02-18, 2026-02-19)` and does not establish full-history completeness.

### Full-window RPC QA files

- `morpho_full_window_qa_summary.json` is the one-row-equivalent final QA record for the complete scoped raw snapshot. It records coverage, file, checksum, row-count, uniqueness, scope, ordering, removed-log, daily, and family reconciliation results.
- `morpho_full_window_daily_event_counts.csv` has one row per UTC bucket. Its grain is `date_utc` within the authorized window; the first row is the partial interval starting at 2025-07-09 13:00 UTC, followed by complete UTC days. Expected unique key: `date_utc`.
- `morpho_full_window_event_family_counts.csv` has one row per official Phase 2 event family. Expected unique key: `event_family`.
- `morpho_full_window_day_boundaries.csv` has one row per exact UTC boundary and maps it to the first block with timestamp at or after that instant. Expected unique key: `boundary_utc`.
- The compact outputs contain 405 daily buckets, 406 boundaries, eight families, and 1,231,462 reconciled events. All final mismatch counters are zero.
- Producing code: `scripts/qa_morpho_full_window.py`. Method and output checksums: `docs/MORPHO_FULL_WINDOW_RPC_QA.md`.
- Raw `manifest.json`, `day_boundaries.json`, and 3,157 immutable JSONL shards remain under ignored `data/raw/morpho_full_window/`; they are complete source evidence, not files for Git.
- Privacy: public contract, market, block, transaction, and wallet identifiers only. Wallet addresses must not be described as natural persons or reward recipients.

### Phase 4 three-market daily-state evidence

- `market_day_prototype_sample.csv` is a 15-row deterministic sample from the complete 1,215-row local result. It contains the first bucket, the last inactive/first active boundary, the midpoint and the final bucket for each frozen market. Expected key: `market_id + day_utc`.
- `morpho_market_day_prototype_qa.json` is the complete machine-readable QA record for 275,797 selected raw events, 1,215 daily rows, raw count/flow reconciliation, exact rounding, continuity, rare-branch coverage, 12 RPC comparisons and measured/projection cost.
- `morpho_phase4_rpc_checkpoint_plan.json` freezes anchor/start/mid/end blocks before calls. `morpho_phase4_rpc_checkpoint_evidence.json` records decoded market totals and the identity-bound cache audit.
- Producing code: `scripts/build_morpho_market_day_prototype.py`; executable SQL: `sql/10_market_day_prototype.sql` and `sql/90_qa_market_day_prototype.sql`.
- The complete working SQLite and RPC cache remain under ignored `data/tmp/`. The sample is filtered evidence, not the full 45-market dataset.
- Privacy: only public market, block and transaction identifiers; no claim equates a wallet with a person.

### Phase 6 bounded preflight evidence

- `drip_morpho_eligibility_bridge.csv` has grain and unique key `market_id + epoch + side`. It contains 469 rows for all 45 accepted markets and has no semicolon-list cells; shared and dedicated campaign references use separate columns.
- `drip_morpho_scope_reproducibility_manifest.json` binds the official Merkl request, ignored raw snapshot, extractor version/checksum, accepted/candidate CSV checksums and comparison result. Both candidate CSVs reproduce the accepted files byte-for-byte.
- `drip_morpho_scope_comparison.json` records zero missing, extra or field-mismatch defects and confirms that accepted files were not modified.
- `phase6_preflight_qa.json` records bridge key/completeness/integrity checks, campaign membership and budget reconciliation, immutable input fingerprints, 18,225-row full-build expectation and local runtime/storage/free-space projections.
- Producing code for this bounded checkpoint: `scripts/extract_drip_morpho_scope.py` and `scripts/prepare_phase6_preflight.py`. The later full build is documented separately below.
- Shared campaign amounts remain at root-campaign grain; 505,000 ARB of direct-vault incentives have no market bridge rows. Only exact dedicated-market amounts are market-attributable in the bridge.

### Phase 6 full market-day evidence

- `morpho_market_day_full_qa.json` is the machine-readable QA result for 45 markets × 405 UTC buckets = 18,225 unique rows, all 1,231,462 source events, 360 family and 765 flow reconciliations, exact rounding, continuity, prototype equality, RPC sampling and measured storage/runtime.
- `morpho_market_day_full_coverage.csv` contains one reviewed coverage row per accepted market. `morpho_market_day_full_sample.csv` contains 225 deterministic market-day rows: first bucket, inactive/active boundary, midpoint and final bucket per market.
- `morpho_phase6_rpc_checkpoint_plan.json` freezes all 45 anchors and the five-market SHA-ranked start/mid/end sample before RPC. `morpho_phase6_rpc_checkpoint_evidence.json` records 60 decoded checkpoints and cache QA.
- The full published SQLite and RPC cache are intentionally ignored under `data/tmp/`; the published database SHA-256 is recorded in the compact QA JSON and build checkpoint.
- Producing code: `scripts/build_morpho_market_day_full.py`; executable production SQL: `sql/20_market_day_full.sql`; population QA SQL: `sql/90_qa_market_day_full.sql`. The accepted `sql/10_market_day_prototype.sql` and its QA SQL are reused as the exact replay module without changing Phase 4 outputs.

### Phase 7 chart-ready analysis evidence

- `morpho_phase7_market_retained_uplift.csv` has grain `market_id × metric × post_checkpoint` for all 45 fixed markets, four metrics and three post checkpoints: 540 unique rows.
- `morpho_phase7_portfolio_retained_uplift.csv` contains exact-loan-asset, exact-collateral-asset, fixed-program and three-archetype aggregates: 108 unique rows. USDC and USD₮0 remain separate; heterogeneous collateral addresses are not added.
- `morpho_phase7_checkpoint_series.csv` contains the exact aligned series used for charts: 2,724 unique `scope × metric × checkpoint` rows.
- `morpho_phase7_period_flows.csv` contains 135 market-period plus six exact-loan-group period rows. Borrow, repay, interest, liquidation repayment and bad debt remain separate and the debt equation reconciles exactly.
- `morpho_phase7_market_concentration.csv` contains 45 markets at campaign end and P180: 90 unique rows. It is market concentration, not wallet concentration.
- `morpho_phase7_analysis_qa.json` and `morpho_phase7_analysis_manifest.json` bind the immutable inputs, script and outputs and record a final PASS. Producing code: `scripts/analyze_phase7_metrics.py`.
- No exported chart-ready file contains a wallet-level cohort, top-wallet list or asserted reward-recipient identity.

### Phase 8 local release evidence

- `release/phase8_headline_verification.json`: separate-code same-author read-only calculation comparison; not independent signoff.
- `release/phase8_reproduction_qa.json`: isolated rerun, unchanged source identities and byte equality for all five CSVs/six PNGs.
- `release/phase8_markdown_build.json`: nine-page static build, figure identities and parser runtime.
- `release/phase8_release_inventory.csv`: file-by-file candidate INCLUDE/EXCLUDE decisions, sizes and compact-file checksums. The three self-generated hygiene receipts are separately identified in the scanner scope to avoid a self-hash cycle.
- `release/phase8_hygiene_findings.csv` and `release/phase8_release_preflight.json`: redacted locations, link/structure/ignore checks and release holds. No suspected secret values or personal path contents are exported.
- Raw/cache/databases and retained reproduction/preview directories remain ignored. This is a local candidate, not a privacy-safe published source bundle.
