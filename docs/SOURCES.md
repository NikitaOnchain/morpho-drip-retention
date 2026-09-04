# Source inventory

## Phase 8 review corrections — local access 2026-09-04

Read the unchanged independent review report and linked numerical/package/render evidence. No new API/RPC/GBA or primary-source refresh was performed. Accepted source dates and identities remain unchanged. Portable copies retain original SHA-256 in `release/derivative_manifest.json`; source-bundle paths/hashes are in `release/external_inputs.json`. See [review response](RESPONSE_TO_REVIEW.md) for actual package tests and explicit unrun checks.

Access date for initial inventory: **2026-08-31**.

Primary sources should be opened again when their facts are used in published analysis. Search snippets are not evidence.

## Phase 8 release candidate (local access 2026-09-03)

Per the release scope, this pass uses only accepted Phases 1–7 artifacts, not refreshed APIs or web claims. Original source access dates below remain unchanged. The accepted production database, frozen metric contract, exact boundaries and chart-ready outputs were checksum-verified; no RPC/GBA/extraction or external-source request ran.

- [Headline provenance](HEADLINE_PROVENANCE.md) maps public numbers to definitions, producing code and reviewed evidence.
- [Reproduction contract](REPRODUCTION.md) records exact snapshot identities and tested runtimes.
- [Release QA](RELEASE_CANDIDATE_QA.md) separates local preflight evidence from pending independent review and publication gates.

## Phase 7 exact timestamp boundaries (accessed 2026-09-02)

1. Official Arbitrum One public JSON-RPC, `eth_chainId` and `eth_getBlockByNumber` only.
   - Used to map all 227 frozen v1.0 timestamps to the minimum block whose timestamp is greater than or equal to the target.
   - Every chosen block was validated against its immediately preceding block; block number, hash, parent hash and timestamp were checked before caching.
   - No endpoint URL containing credentials is persisted. The run made zero `eth_getLogs` calls and zero GBA queries.
2. `data/tmp/morpho_market_day_full_v1.sqlite` (accepted Phase 6 production database).
   - Opened read-only and used only for accepted UTC-day search brackets and source identity. SHA-256 remained `80aca74cc5e43db03fd93c69d7ad448ac9afdec5f9566a6b833ec11f7e5c9543`.
3. [Frozen metric contract v1.0](METRICS.md).
   - Defines the exact 13:00 UTC checkpoint population and half-open ordering that the boundary map implements.
4. [Boundary-map method and QA](PHASE7_BOUNDARY_MAP.md).
   - Records the target-list identity, cache/checkpoint protocol, stop/resume evidence, RPC telemetry, reconciliation and limitations.

## DRIP

1. [DRIP Season 1 Launch Recap](https://forum.arbitrum.foundation/t/drip-season-1-launch-recap/29921)
   - Intended program design, target strategies, initial budget and taper rationale.
2. [DRIP September 2025 Update](https://forum.arbitrum.foundation/t/drip-september-2025-update/30057)
   - Early Morpho market-growth claims and links to contemporary dashboards.
3. [DRIP October 2025 Update](https://forum.arbitrum.foundation/t/drip-october-2025-update/30187)
   - Later campaign-period Morpho market observations.
4. [DRIP February 2026 Update](https://forum.arbitrum.foundation/t/drip-february-2026-update/30628)
   - Program-end accounting, unclaimed incentives and remaining budget context.
5. [DRIP Season 1 Retrospective](https://forum.arbitrum.foundation/t/drip-season-1-retrospective/30644)
   - Official campaign dates, protocol coverage and reported campaign-period outcomes.
6. [Extending DRIP's Mandate](https://forum.arbitrum.foundation/t/extending-drips-mandate/30985)
   - Current governance decision and explicit demand for post-incentive retention evidence.
7. [Arbitrum Foundation DRIP Season 1 Recap](https://blog.arbitrum.io/drip-season-1-recap/)
   - Useful narrative context; treat as program communication, not independent validation.

### Exact Morpho scope verification (accessed 2026-08-31)

1. [Merkl API V4 filtered opportunity inventory](https://api.merkl.xyz/v4/opportunities?mainProtocolId=morpho&tags=drip&campaigns=true&status=PAST&items=100&page=0)
   - Primary campaign records used to recover root campaign IDs, exact UTC timestamps, ARB amounts, market IDs, asset addresses, LLTV and reward side.
   - Retained only Arbitrum campaigns rewarding ARB from creator `0x7d0A9493Edecf7112486319E0fDBA72fC7a62468` whose root `campaignId` begins with `0x`.
   - Stable per-campaign evidence URLs are stored in `data/drip_morpho_epoch_campaigns.csv`.
2. [Merkl campaign configuration documentation](https://docs.merkl.xyz/merkl-mechanisms/campaignConfiguration)
   - Defines the configuration as the Merkl engine's source of truth and documents `amount`, timestamps and distribution method fields.
3. [Merkl lending and borrowing campaign documentation](https://docs.merkl.xyz/merkl-mechanisms/campaign-types/lending-borrowing)
   - Documents multi-market Morpho reward cascading; supports treating a shared campaign amount as a pool rather than a per-market allocation.
4. [DRIP November 2025 Update](https://forum.arbitrum.foundation/t/drip-november-2025-update/30321)
   - Official epoch 6–7 protocol allocations.
5. [DRIP December 2025 Update](https://forum.arbitrum.foundation/t/drip-december-2025-update/30382)
   - Official epoch 8–9 allocations and Steakhouse/Bitget special-purpose campaign description.
6. [DRIP January 2026 Update](https://forum.arbitrum.foundation/t/drip-january-2026-update/30546)
   - Official epoch 10–12 narrative. Contains a 5K inconsistency for epoch 11: the Morpho bullet says 140K base while the epoch headline, Merkl record and final chart imply 145K.
7. [Final ARB allocations per epoch by lending protocol](https://canada1.discourse-cdn.com/flex029/uploads/arbitrum1/original/3X/1/5/1542a5e2c91a3d2f661f5d296249c1327a462d8a.jpeg)
   - Original chart attached to the February update; reconciles all 12 Morpho epoch totals, including 325K in epoch 11.
8. [Verified scope memo](DRIP_MARKET_SCOPE.md)
   - Extraction filters, allocation semantics, reconciliation, duplicate handling and limitations.
9. [Frozen Phase 4 market archetypes](PHASE4_MARKET_ARCHETYPES.md) (accessed 2026-09-01)
   - Reuses the exact three archetype priorities precommitted in Phase 2 and records their market IDs, assets, epoch coverage, first scoped RPC event-days, source fingerprints and non-result-conditioned selection rule.
10. [Phase 6 eligibility and reproducibility preflight](PHASE6_PREFLIGHT.md) (accessed 2026-09-02)
   - A fresh official Merkl V4 response was saved as a SHA-bound ignored snapshot and reproduced both accepted Phase 1 CSVs byte-for-byte with zero comparison defects.
   - Records the normalized 469-row `market_id × epoch × side` bridge, campaign membership/budget QA, attribution guardrails and full-build capacity gate.

## Morpho

1. [Morpho contract addresses](https://docs.morpho.org/developers/contracts/addresses/)
   - Verified on 2026-08-31: official Arbitrum Morpho Blue deployment is `0x6c247b1F6182318877311737BaC0844bAa518F5e`.
   - Google Blockchain Analytics comparisons use lowercase `0x6c247b1f6182318877311737bac0844baa518f5e`.
2. [Official Morpho `EventsLib.sol`](https://github.com/morpho-org/morpho-blue/blob/main/src/libraries/EventsLib.sol)
   - Primary source for the eight checked event signatures, indexed participant roles, and non-indexed numeric-field order.
3. [Morpho asset-flow documentation](https://docs.morpho.org/developers/borrow/tutorials/assets-flow/)
   - Event and position semantics for supply, borrow, repay, collateral and withdrawal flows.
4. [Morpho developer resources](https://docs.morpho.org/developers/borrow/resources/all/)
   - API and indexing resources; API is metadata/cross-check unless explicitly justified otherwise.

### Phase 3 accounting semantics and bounded replay (accessed 2026-09-01)

1. [Morpho Blue `v1.0.0` core implementation](https://github.com/morpho-org/morpho-blue/blob/v1.0.0/src/Morpho.sol)
   - Primary source for exact action deltas, assets/shares rounding direction, interest accrual, fee-share minting, liquidation and bad-debt state changes.
2. [Morpho Blue `v1.0.0` interface](https://github.com/morpho-org/morpho-blue/blob/v1.0.0/src/interfaces/IMorpho.sol)
   - Primary source for the `Market` and `Position` storage fields and warnings about unaccrued view state.
3. [Official tagged `SharesMathLib.sol`](https://github.com/morpho-org/morpho-blue/blob/v1.0.0/src/libraries/SharesMathLib.sol)
   - Primary source for `VIRTUAL_SHARES = 1e6`, `VIRTUAL_ASSETS = 1`, conversion formulas and up/down rounding variants.
4. [Official tagged `EventsLib.sol`](https://github.com/morpho-org/morpho-blue/blob/v1.0.0/src/libraries/EventsLib.sol)
   - Primary source for position-owner roles, emitted assets/shares fields, `AccrueInterest` fields and the warning that fee-recipient shares have no `Supply` event.
5. [Morpho Market Mechanics](https://docs.morpho.org/developers/borrow/concepts/market-mechanics/)
   - Official explanatory source for market totals, wallet shares, share-price behavior and the fact that collateral has no shares or lending yield.
6. [Morpho asset-flow tutorial](https://docs.morpho.org/developers/borrow/tutorials/assets-flow/)
   - Official integration guidance for borrow/repay assets versus shares and collateral asset accounting.
7. [Morpho liquidation documentation](https://docs.morpho.org/developers/borrow/concepts/liquidation/)
   - Official explanatory source for liquidator repayment, collateral seizure and residual bad debt borne by lenders.
8. [Accounting model memo](MORPHO_ACCOUNTING_MODEL.md)
   - Project specification for event-to-state transitions, deterministic ordering, UTC boundary semantics, the deterministic selection rule and the completed bounded replay.
9. [One-position reconstruction QA](MORPHO_ONE_POSITION_RECONSTRUCTION.md)
   - Exact rank-1 identity, source/cache verification, 2,634-event market population, 19-event wallet trace, RPC checkpoint reconciliations, limitations and artifact links.
10. [`morpho_one_position_reconstruction_qa.json`](../data/morpho_one_position_reconstruction_qa.json)
   - Machine-readable PASS evidence for manifest/selection identity, sealed-cache audit, shard checks, event counts, rounding, negative balances and anchor/intermediate/final reconciliation.

### Phase 4 three-market daily-state prototype (accessed 2026-09-01)

1. [Three-market prototype report](MARKET_DAY_PROTOTYPE.md)
   - Executable SQLite engine, exact source fingerprints, UTC grain, event replay, 12 archive-RPC checkpoint reconciliations, rare-branch coverage and 45-market cost/storage projection.
2. [`morpho_market_day_prototype_qa.json`](../data/morpho_market_day_prototype_qa.json)
   - Machine-readable PASS for 3,157 shard checks, 275,797 selected events, 1,215 market-day rows, raw family/flow reconciliation, rounding, continuity, nonnegative states and RPC comparisons.
3. [`morpho_phase4_rpc_checkpoint_plan.json`](../data/morpho_phase4_rpc_checkpoint_plan.json)
   - Deterministically frozen anchor/start/mid/end block plan created before the bounded archive calls.
4. [`morpho_phase4_rpc_checkpoint_evidence.json`](../data/morpho_phase4_rpc_checkpoint_evidence.json)
   - Decoded `market(bytes32)` results and audit of the separate identity-bound 12-row SQLite/WAL cache; the final verification used 12 cache hits and zero new calls.

### Phase 6 full 45-market daily state (accessed 2026-09-02)

1. [Full market-day QA report](MARKET_DAY_FULL_QA.md)
   - Production grain, immutable source fingerprints, accounting/order rules, population reconciliation, bounded RPC design, measured runtime/storage and limitations.
2. [`morpho_market_day_full_qa.json`](../data/morpho_market_day_full_qa.json)
   - Machine-readable PASS evidence for 45 × 405 rows, 1,231,462 source events, blocking SQL checks, exact rounding, prototype comparison, RPC reconciliation and the 10 GiB gate.
3. [`morpho_market_day_full_coverage.csv`](../data/morpho_market_day_full_coverage.csv)
   - One compact coverage record for each of the 45 accepted markets.
4. [`morpho_phase6_rpc_checkpoint_plan.json`](../data/morpho_phase6_rpc_checkpoint_plan.json)
   - Precommitted all-anchor and five-market hash-ranked checkpoint population.
5. [`morpho_phase6_rpc_checkpoint_evidence.json`](../data/morpho_phase6_rpc_checkpoint_evidence.json)
   - Sixty decoded `market(bytes32)` responses and integrity evidence for the separate Phase 6 SQLite/WAL cache.

### Phase 7 retained-uplift analysis (accessed 2026-09-03)

1. [Phase 7 findings](../reports/PHASE7_FINDINGS.md)
   - English observational readout for borrowed-asset persistence, active borrowers, flows, market concentration, three frozen archetypes, alternative explanations and incentive-design recommendation.
2. [Phase 7 technical QA](PHASE7_ANALYSIS_QA.md)
   - Exact frozen calculation contract, accepted input fingerprints, population/accounting checks, applicability counts and the question/population/unit/window/source contract for every figure.
3. [`morpho_phase7_analysis_qa.json`](../data/morpho_phase7_analysis_qa.json)
   - Machine-readable PASS for boundary identity, read-only production access, 10,215 wallet-share reconciliations, raw family/amount checks, flow equations, chart-ready grains and rare-branch coverage.
4. [`morpho_phase7_analysis_manifest.json`](../data/morpho_phase7_analysis_manifest.json)
   - SHA-256 binding for the producing script, immutable Phase 6 database, frozen metrics, eligibility bridge, exact boundary artifacts and every published CSV/figure.
5. [`analyze_phase7_metrics.py`](../scripts/analyze_phase7_metrics.py)
   - Offline reproducer for all retained-uplift tables and six figures. It makes no RPC/GBA calls and opens the accepted production database read-only/immutable.

### Phase 3 archive-state selection probes (accessed 2026-08-31)

1. [Official Arbitrum One chain information](https://docs.arbitrum.io/for-devs/dev-tools-and-resources/chain-info)
   - The documented public RPC served the earlier raw-log extraction but returned `missing trie node ... state ... is not available, not found` for the historical `eth_call` required by the Phase 3 zero-state anchor.
2. [Tenderly Arbitrum gateway](https://docs.tenderly.co/node/rpc-reference/arbitrum)
   - A historical `position()` probe succeeded. The attempted complete candidate-state pass failed closed after bounded retries on HTTP 429; no partial responses were accepted as selection evidence.
3. [BlastAPI Arbitrum endpoints](https://docs.blastapi.io/blast-documentation/apis-documentation/core-api/arbitrum)
   - Historical probes succeeded. The longer candidate-state pass was intentionally interrupted on the user's stop request and produced no final evidence file.
4. [Alchemy Arbitrum RPC](https://www.alchemy.com/rpc/arbitrum)
   - A separate public historical probe returned the same `position()` result as the successful Tenderly and BlastAPI probes. This is a probe only, not a completed population gate.
5. [Phase 3 selection checkpoint](../PHASE3_SELECTION_CHECKPOINT.md)
   - Durable record of the complete offline candidate funnel, selector checksum, RPC provider outcomes, unpersisted-progress limitation and exact continuation point.
6. [Phase 3 archive-RPC cache handoff](../PHASE3_RPC_CACHE_HANDOFF.md)
   - Bounded 12-candidate stop/resume evidence, SQLite identity/validation/transaction contract, final integrity counts and exact full-start/resume commands.

## Arbitrum One

1. [Official chain information and public RPC](https://docs.arbitrum.io/for-devs/dev-tools-and-resources/chain-info)
   - Primary source for the Arbitrum One public RPC and chain ID `42161`.
   - On 2026-08-31, `eth_getTransactionReceipt`, `eth_getBlockByNumber`, and `eth_chainId` were used as the independent source for the deterministic event sample.
   - The bounded RPC feasibility test additionally used `eth_getLogs` over the exact block interval `[495303648, 495647034)` and reproduced all 2,087 GBA reference rows. Request, retry, error, timing, and volume evidence is in `MORPHO_RPC_FEASIBILITY.md`.
   - The append-only resume test on 2026-08-31 used `eth_getLogs` over `[433213243, 433559875)`. It intentionally stopped after `[433213243, 433233243)`, then resumed from the exact next block without re-fetching the completed range.
   - The completed Phase 2 raw snapshot used `eth_getLogs` for `[355887376, 495647034)`. Independent QA used `eth_getBlockByNumber` to verify every UTC-day boundary. The final evidence is in `MORPHO_FULL_WINDOW_RPC_QA.md`; no full-window GBA query was run.

## Google Blockchain Analytics

1. [Supported datasets](https://docs.cloud.google.com/blockchain-analytics/docs/supported-datasets)
   - Confirms Arbitrum availability; re-check dataset freshness before execution.
2. [Blockchain Analytics schemas](https://docs.cloud.google.com/blockchain-analytics/docs/schema)
   - Tables, partitions, address casing and event/log availability.
   - Schema inspection on 2026-08-31 confirmed the Arbitrum authorized views `goog_blockchain_arbitrum_one_us.logs` and `goog_blockchain_arbitrum_one_us.decoded_events`; both are monthly time-partitioned on `block_timestamp`.
   - A bounded 2026-08-17 probe found 2,087 Morpho rows in each view with exact key/topic reconciliation, but all checked decoded rows had blank `event_signature` and NULL `args`.
3. [Blockchain Analytics pricing](https://cloud.google.com/blockchain-analytics/pricing)
   - Blockchain Analytics uses normal BigQuery pricing; partition pruning is required for cost control.
   - Full-window dry-run upper bounds recorded on 2026-08-31 were 948.79 GiB for a minimal decoded-event profile and 1.59 TiB for raw logs including `data`, so they were not executed.
4. [Morpho event coverage checkpoint](MORPHO_EVENT_COVERAGE.md)
   - Local evidence note for schemas, one-day population QA, deterministic sample design, RPC comparison, exact byte estimates, and the documented raw-log fallback.
5. [Morpho one-day RPC feasibility](MORPHO_RPC_FEASIBILITY.md)
   - Local evidence note for adaptive block ranges, retries, checkpoints, exact key/topics/raw-data reconciliation, and operational cost of the public RPC route.
6. [Morpho stratified multi-day RPC pilot](MORPHO_RPC_STRATIFIED_PILOT.md)
   - Baseline, campaign-end, and post-period reconciliation; live resume evidence; bounded GBA cost accounting; and a full-window RPC request/time/storage estimate.
7. [Morpho append-only RPC resume test](MORPHO_RPC_APPEND_ONLY_RESUME.md)
   - Immutable shard write protocol, manifest validation rules, active-data intentional stop/resume evidence, independent file-level QA, and the remaining full-history limitation.
8. [Morpho full-window RPC QA](MORPHO_FULL_WINDOW_RPC_QA.md)
   - Final manifest/shard coverage, checksum, uniqueness, scope, ordering, UTC-boundary, daily-count, and event-family reconciliation evidence for the complete authorized window.

## Source hierarchy

Local review access, 2026-09-04: the owner accepted independent re-review **APPROVE WITH CAVEATS**, closing R1–R4. [Public report/evidence guide](../reviews/public/README.md) and [original-to-public evidence manifest](../reviews/public/evidence_manifest.json) preserve provenance. No new external source, API or RPC was accessed during final packaging. Full raw rebuild and browser/GitHub rendering were not run; public source-bundle acquisition is unavailable.

1. Onchain raw events and transactions.
2. Official campaign allocations and dates.
3. Official protocol documentation for semantics and addresses.
4. Morpho API or public dashboards for metadata and reconciliation.
5. Program blog posts only for narrative context.

Record the exact URL, access date, query/table identifiers and any archived snapshot used in every published claim.
