# Reproducible scripts

## Phase 8 local release preflight

The revised staging package adds `reproduce_release_csv.py` (CSV-only, no DB), `release_routes.py` (explicit checksum-bound external bundle), `audit_release_package.py` (actual package audit) and `run_release_sandbox.py` (Python accidental-dependency/network guard). `release_chart_renderer.py` is generated with presentation-only overrides from `release_chart_patch.py`.

Descriptions below are historical workspace tools. In staging, legacy isolated reproduction delegates to the bundle route with required `--bundle`/`--destination`; legacy preflight delegates to the package audit. Original/portable identities are mapped, not silently replaced. Use full isolated-job instructions before running any historical raw build command.

- `review_phase7_headlines.py`: separate-code read-only recalculation of 648 metric rows and 10,215 market/checkpoint share checks. Not an independent reviewer signoff.
- `reproduce_phase7_isolated.py`: copies accepted inputs into a retained versioned workspace and byte-compares five CSVs and six PNGs. Only copied metadata paths are relocated; no originals change or network calls run.
- `preflight_phase8_release.py`: non-destructive exact include/exclude inventory, local links, syntax/data structure and high-signal secret screen. No Git staging, push or publication.
- `build_release_preview.cjs`: optional static Markdown-to-HTML QA preview with Node 24.19.0 / marked 17.0.5. Temporary HTML is ignored and never published; no app/server is created.

See [reproduction instructions](../docs/REPRODUCTION.md) and [release limitations/holds](../docs/RELEASE_CANDIDATE_QA.md). Earlier extraction/build commands below are historical workflows, not instructions to rerun accepted phases during release preparation.

## `build_phase7_frozen_boundaries.py`

Builds the exact 227-timestamp 13:00 UTC block-boundary map required by frozen metrics v1.0. It uses only `eth_chainId` and rate-limited batched `eth_getBlockByNumber`, validates predecessor/chosen adjacency and hashes, persists a resume-safe identity-bound SQLite/WAL cache, and publishes immutable CSV/JSON/QA evidence. It never calls `eth_getLogs`, queries GBA, or writes to the Phase 6 production database.

The accepted map is complete. Revalidate it offline from the repository root:

```powershell
python .\scripts\build_phase7_frozen_boundaries.py --offline-only
```

See `docs/PHASE7_BOUNDARY_MAP.md` for the exact population, stop/resume evidence and QA.

## `rpc_morpho_event_feasibility.ps1`

Runs a bounded one-day Phase 2 RPC/GBA feasibility test. The default remains 2026-08-17 UTC, while explicit `StartUtc` and `EndExclusiveUtc` parameters support approved pilot days.

It:

- materializes the matching GBA raw-log reference with `sql/02_rpc_stratified_gba_reference.sql`, or reuses an explicitly supplied local reference;
- finds exact UTC block boundaries through Arbitrum RPC;
- retrieves the target Morpho logs with adaptive `eth_getLogs` ranges and retries;
- writes each completed range once as `shards/range_*.jsonl.part`, atomically renames it to `.jsonl`, and records its SHA-256 checksum in `manifest.json`;
- verifies all manifest shards, row counts, keys, and contiguous boundaries before resume;
- reconciles key, topics, and raw data;
- publishes compact summary, range, error, and mismatch files under `data/`.

Run from the repository root:

```powershell
pwsh -NoProfile -File .\scripts\rpc_morpho_event_feasibility.ps1
```

Use `-RefreshGba` only after a dry run approves the bounded GBA reference. `-GbaReferenceSourcePath` can copy a previously verified reference from inside the workspace without a new query. Without either option, an existing local reference is reused.

`-StopAfterSuccessfulRanges 1` intentionally exits after the first verified shard and manifest update. Running the same command again without that parameter verifies the manifest and resumes after its last shard. `-RunSuffix '_resume'` creates a separate namespace for a non-destructive resume probe.

The default parameters are deliberately restricted to one UTC day. Do not change them to the full research window. The separately authorized full extraction is complete and should not be rerun.

## `rpc_morpho_full_window.ps1`

Produced the authorized append-only RPC snapshot for `[355887376, 495647034)`. It is hard-restricted to the approved UTC interval and writes immutable range shards through `.part` plus atomic rename, with a verified manifest as the resume authority.

The manifest is now `complete` with 3,157 shards and 1,231,462 rows. **Do not run this extractor again.** The completion checkpoint is `FULL_WINDOW_CHECKPOINT.md`.

## `qa_morpho_full_window.py`

Runs independent streaming QA against the completed manifest and shards. It recomputes every SHA-256 and row count; checks continuous coverage, scope, key uniqueness, removed logs, shard bounds, and ordering; obtains exact UTC boundaries from the official Arbitrum RPC; and writes compact daily, family, boundary, and summary outputs under `data/`.

Run only when a deliberate revalidation of the unchanged snapshot is needed:

```powershell
python .\scripts\qa_morpho_full_window.py
```

The public RPC rejects Python's default User-Agent and can rate-limit bursty requests. The client therefore uses an explicit User-Agent, bounded retries, batch fallback, and minimum request pacing. A successful boundary document is cached under ignored raw data, so subsequent unchanged-snapshot checks do not repeat timestamp RPC calls.

## `select_morpho_one_position.py`

Scans the completed Phase 2 shards and applies the precommitted Phase 3 wallet-market selection rule without SQL. The complete offline scan currently narrows 9,959 distinct pairs to 5,575 structural candidates.

Historical state calls now use `morpho_archive_rpc_cache.py`: SQLite/WAL, strict chain/JSON-RPC/calldata/ABI validation, response checksums, immutable run identity, and a response-before-checkpoint transaction order. The bounded 12-candidate intentional-stop/resume test is PASS; see `PHASE3_RPC_CACHE_HANDOFF.md`.

Historical note: the later manually completed 5,575-candidate pass and rank-1 selection were accepted in Phase 3. The sealed selection SQLite must not receive new arbitrary calls. Use `--bounded-test` only when deliberately retesting the cache mechanism; never reuse a cache after an identity mismatch and never edit its candidate file between restarts.

## `prepare_morpho_bounded_candidates.py`

Creates the 10–20 candidate fixture used only to validate cache/resume mechanics. It discovers a small early pool, then tracks only those keys through the remaining immutable shards; it does not rebuild the global structural funnel.

## `test_morpho_archive_rpc_cache.py`

Runs the local cache contract tests:

```powershell
python -m unittest .\scripts\test_morpho_archive_rpc_cache.py -v
```

## `build_morpho_market_day_prototype.py`

Builds the bounded Phase 4 daily-state layer for only the three frozen markets.
It re-verifies and scans the immutable Phase 2 shards once, decodes the accepted
eight event families, stages exact unsigned decimal values in SQLite, executes
`sql/10_market_day_prototype.sql` and `sql/90_qa_market_day_prototype.sql`, and
writes compact sample/QA evidence. It never calls `eth_getLogs`, never queries
GBA and never writes the Phase 3 selection cache.

The initial run filled a separate identity-bound 12-response archive cache.
Reproduce the completed build without network calls:

```powershell
python .\scripts\build_morpho_market_day_prototype.py --offline-only
```

The final run made 12/12 cache hits, produced 1,215 market-day rows from 275,797
events and passed every blocking check. Full methodology and cost projection are
in `docs/MARKET_DAY_PROTOTYPE.md`.

## `extract_drip_morpho_scope.py`

Rebuilds the accepted Phase 1 campaign and market CSVs from the official Merkl
V4 opportunity inventory. The workflow is fail-closed: raw responses and
candidate CSVs go to ignored paths, accepted files are read-only, and any
missing/extra/field difference returns a non-zero exit after writing comparison
evidence. `--raw-snapshot` provides a fully offline replay path.

The 2026-09-02 snapshot reproduced both accepted CSVs byte-for-byte. Exact
paths and checksums are in
`data/drip_morpho_scope_reproducibility_manifest.json`.

## `prepare_phase6_preflight.py`

Reads only accepted Phase 1 files and accepted Phase 2/4 evidence. It creates
the normalized `market_id × epoch × side` bridge and machine-readable Phase 6
preflight QA. It does not scan RPC shards, call an API, build the 45-market
daily layer, or alter frozen metrics.

## `build_morpho_market_day_full.py`

Builds the versioned Phase 6 production SQLite from all immutable Phase 2
shards, executes the accepted exact-bigint replay, materializes the normalized
eligibility rollup, performs population/prototype/RPC QA and atomically
publishes only after integrity checks. Its independent RPC evidence uses a
separate 60-entry cache; it never calls `eth_getLogs`, GBA, or the Phase 3
selection cache.

## `analyze_phase7_metrics.py`

Reads the accepted Phase 6 SQLite in immutable/query-only mode, verifies the
frozen v1.0 definitions and accepted 227-boundary identity, then calculates
market and exact-token portfolio checkpoints, retained-uplift ratios, period
flows, cross-sectional active borrowers, market concentration and the three
precommitted archetypes. It publishes five chart-ready CSV files, six PNG
figures and identity-bound QA/manifest JSON atomically.

The script performs no network calls and does not mutate the production
database. It replays wallet borrow shares solely to derive validated
cross-sectional checkpoint counts; it does not produce wallet cohorts,
wallet concentration or recipient claims.
