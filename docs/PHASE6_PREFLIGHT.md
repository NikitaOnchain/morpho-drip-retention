# Phase 6 eligibility bridge and full-build preflight

Status: **PASS — bounded preparation only**.  
Evidence date: **2026-09-02**.

This checkpoint starts Phase 6 but does not build the 45-market daily-state
dataset. It normalizes accepted campaign eligibility, closes the Phase 1
extraction-script debt, and checks whether the accepted inputs and local
capacity are ready for the separately gated full build.

## Reproducibility result

`scripts/extract_drip_morpho_scope.py` is a fail-closed extractor for the
official Merkl V4 opportunity inventory. It filters root campaigns by Arbitrum
One, the DRIP creator, ARB reward token, the exact 12 epoch boundaries, and
supported Morpho campaign forms. It writes a timestamped raw response and
candidate CSVs only to ignored paths, then compares them with the accepted
Phase 1 CSVs. It has no accepted-file overwrite mode.

The 2026-09-02 response was saved locally as a 1,236,207-byte raw snapshot with
SHA-256
`4d9bc3e011ce56ad555b3b650d42198d83fd78d35594d8b93e1f56d5362ae8c7`.
The candidate outputs reproduce both accepted CSVs byte-for-byte:

| Artifact | Rows | Accepted and candidate SHA-256 |
|---|---:|---|
| Root campaigns | 36 | `6474919d49b87ed38df72de55f470f24535a506899a4ccdcfb05c2085a27045b` |
| Distinct markets | 45 | `a88fceaa19fe383bb956ef698a819facb2d345a29bd173db730e85bbd5213a6a` |

The current Merkl campaign `type` does not distinguish the two shared sides:
both shared supply and shared borrow records use `MULTILENDBORROW`. The frozen
extractor therefore reads `opportunity.action` (`LEND` or `BORROW`) for side and
validates it; it does not infer side from the campaign type or opportunity
name. Exact comparison has zero missing keys, extra keys, or field mismatches.

Evidence:

- `data/drip_morpho_scope_reproducibility_manifest.json`
- `data/drip_morpho_scope_comparison.json`
- ignored raw snapshot and candidate paths recorded in the manifest

## Normalized eligibility bridge

The saved bridge is `data/drip_morpho_eligibility_bridge.csv`.

- Grain and unique key: `market_id × epoch × side`.
- Rows / unique keys: **469 / 469**.
- Markets: **45/45** accepted market IDs.
- Sides: **252 supply** rows and **217 borrow** rows.
- Epochs: all **1–12**.
- Duplicate keys, required-field NULLs, orphan markets, and semicolon cells:
  **0**.
- Four syrupUSDC supply rows in epochs 2–5 are explicitly
  `shared_plus_dedicated`; they are not duplicated into two grain rows.

The bridge contains normalized lowercase market and token addresses plus one
row per side and epoch. `shared_campaign_db_id` and
`dedicated_campaign_db_id` are separate nullable references. The only budget
column is `dedicated_market_allocation_arb`, because those four campaigns name
one exact market. Shared campaign amounts remain at root-campaign grain and
must be joined through a distinct campaign table before aggregation.

## Campaign and budget QA

| Scope | Root campaigns | ARB | Market attribution policy |
|---|---:|---:|---|
| Shared market pool | 25 | 3,147,500 | Campaign-level pool only; not divided or copied to markets |
| Dedicated market | 4 | 330,000 | Attributable to the exact syrupUSDC market |
| Direct vault | 7 | 505,000 | Excluded from bridge; not attributed to underlying markets |
| **Total** | **36** | **3,982,500** | Reconciles to accepted Phase 1 totals |

All 25 shared campaign membership counts equal their accepted
`unique_market_count`. Each of the four dedicated campaigns maps to exactly one
matching market. There are no orphan market-linked campaigns or epochs. Epoch
budgets reconcile exactly to the accepted sequence from 120,000 ARB in epoch 1
through 197,500 ARB in epoch 12, including 325,000 ARB in epoch 11.

## Full-build preflight

The future target is fixed at **45 markets × 405 UTC day buckets = 18,225
rows**, with unique key `market_id × day_utc`. The bounded preflight identifies
these required inputs:

1. immutable Phase 2 `manifest.json`, its 3,157 shards, and exact day boundaries;
2. the accepted 45-market dimension and the new normalized eligibility bridge;
3. the accepted Phase 4 executable replay/QA implementation as the scaling
   template;
4. frozen metric contract v1.0 as a read-only downstream definition input.

The accepted Phase 2 manifest still has SHA-256
`c8552428187094e5aad725193f2e3023e622ddc4ab37428f1414c375e7d6be58`,
status `complete`, 3,157 verified shards, and 1,231,462 source events. This
bounded step checks that immutable identity but does not rescan the shards.

The Phase 4 engineering projection with 25% headroom is:

- one-pass source read: 786,571,394 bytes (0.732552 GiB already present);
- full SQLite runtime: approximately 498.223 seconds;
- full database: approximately 7,785,676,800 bytes (7.250977 GiB);
- database plus existing source: approximately 7.983528 GiB;
- operational free-space gate: **10 GiB**, allowing room beyond the projected
  database for SQLite WAL and temporary work;
- observed free space at preflight: **218.666069 GiB** — PASS.

This is a projection, not an observed Phase 6 build measurement. GBA bytes and
new RPC calls at this checkpoint are both zero.

## QA conclusion and gate

All blocking checks in `data/phase6_preflight_qa.json` pass. The bridge and
Phase 1 reproducibility evidence are safe inputs for the next Phase 6 step.
They do not prove the unbuilt 45-market daily layer, full-population replay,
active-borrower results, retained uplift, or any Phase 7 conclusion.

The full 45-market build remains **not started** and requires the next explicit
user confirmation. Phase 7 remains locked.
