# Full offline reconstruction commands and gates

Read [reproduction](REPRODUCTION.md) first. `release_routes.py` checks package/source identities and expands the exact commands below in a new job. `raw-preflight` parses all commands, executes steps 1 and 3 only and does not rebuild state. `raw` runs steps 1–4. No full raw rebuild ran in this correction pass.

Run these commands **inside the isolated job**, not the public package. All inputs are copied locally; cache misses stop in offline mode. Require 10 GiB free. Source: `[2025-07-09 13:00 UTC,2026-08-18 00:00 UTC)`; frozen checkpoints remain exact 13:00 UTC boundaries.

## 1. Merkl snapshot → CSV candidates and comparison

```powershell
python -B .\scripts\extract_drip_morpho_scope.py `
 --raw-snapshot .\data\raw\drip_morpho_scope\merkl_opportunities_20260902T115959247853Z.json `
 --accepted-campaigns .\data\drip_morpho_epoch_campaigns.csv --accepted-markets .\data\drip_morpho_markets.csv `
 --raw-dir .\work\scope_raw --candidate-dir .\work\scope_candidate `
 --comparison-report .\work\scope_comparison.json --manifest .\work\scope_manifest.json
```

## 2. Three-market prototype using the copied cache

```powershell
python -B .\scripts\build_morpho_market_day_prototype.py --offline-only `
 --manifest .\data\raw\morpho_full_window\manifest.json --boundaries .\data\raw\morpho_full_window\day_boundaries.json `
 --archetypes .\data\morpho_phase4_market_archetypes.csv `
 --sql-build .\sql\10_market_day_prototype.sql --sql-qa .\sql\90_qa_market_day_prototype.sql `
 --checkpoint-plan .\data\morpho_phase4_rpc_checkpoint_plan.json --checkpoint-evidence .\work\phase4_rpc_evidence.json `
 --rpc-cache .\data\tmp\morpho_phase4_market_day_rpc.sqlite --database .\work\prototype.sqlite `
 --sample-output .\work\prototype_sample.csv --qa-output .\work\prototype_qa.json
```

## 3. Eligibility bridge and preflight

Accepted portable Phase 4 cost evidence supplies the engineering estimate; the new prototype QA separately validates rebuilt states. Bridge output must match accepted bytes.

```powershell
python -B .\scripts\prepare_phase6_preflight.py --workspace . `
 --campaigns .\data\drip_morpho_epoch_campaigns.csv --markets .\data\drip_morpho_markets.csv `
 --reproduction-manifest .\work\scope_manifest.json --comparison .\work\scope_comparison.json `
 --phase2-manifest .\data\raw\morpho_full_window\manifest.json --day-boundaries .\data\raw\morpho_full_window\day_boundaries.json `
 --prototype-qa .\data\morpho_market_day_prototype_qa.json `
 --prototype-build-sql .\sql\10_market_day_prototype.sql --prototype-qa-sql .\sql\90_qa_market_day_prototype.sql `
 --metrics .\docs\METRICS.md --bridge-output .\work\bridge.csv --qa-output .\work\preflight_qa.json
```

## 4. Full state with the copied 60-response cache

```powershell
python -B .\scripts\build_morpho_market_day_full.py --offline-only `
 --manifest .\data\raw\morpho_full_window\manifest.json --boundaries .\data\raw\morpho_full_window\day_boundaries.json `
 --markets .\data\drip_morpho_markets.csv --bridge .\work\bridge.csv --metrics .\docs\METRICS.md `
 --prototype-db .\work\prototype.sqlite `
 --core-sql .\sql\10_market_day_prototype.sql --core-qa-sql .\sql\90_qa_market_day_prototype.sql `
 --production-sql .\sql\20_market_day_full.sql --production-qa-sql .\sql\90_qa_market_day_full.sql `
 --checkpoint-plan .\data\morpho_phase6_rpc_checkpoint_plan.json --checkpoint-evidence .\work\phase6_rpc_evidence.json `
 --rpc-cache .\data\tmp\morpho_phase6_rpc_checkpoints_v1.sqlite `
 --building-db .\work\full.building.sqlite --final-db .\work\full.sqlite `
 --build-checkpoint .\work\full_checkpoint.json --sample-output .\work\full_sample.csv `
 --coverage-output .\work\full_coverage.csv --qa-output .\work\full_qa.json
```

## 5. Logical reconciliation and identity gate

Before a different physical SQLite can feed frozen metrics, compare `source_event`, `market_event_state`, `market_day_full`, market dimensions and boundaries against accepted SQLite in canonical key order. Counts must be 1,231,462 events / 45 markets / 18,225 days, but counts alone are insufficient: compare all state/flow values, raw identities, rounding, continuity and cache checkpoints. Stop on unexplained differences.

New-DB logical comparison is not performed by `raw-preflight` and has **not run in this correction pass**. Physical bytes may vary by SQLite runtime. Never overwrite the production hash or boundary manifest identity to force success. A different DB requires an independently reviewed logical-equality/identity bridge before new metric lineage. Until then, Route 2a reproduces frozen metrics from the checksum-matched accepted SQLite. No new-DB end-to-end PASS is claimed.

These commands do not allocate shared/direct-vault budgets, create cohorts or a price layer, query RPC/GBA or re-extract logs/boundaries.
