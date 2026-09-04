# Phase 7 frozen checkpoint boundary map

Access date: **2026-09-02**  
Status: **TECHNICAL PASS — metric calculation not started**

## Purpose and exact rule

Frozen metrics v1.0 require campaign-hour-aligned state at 13:00 UTC. For each target timestamp `t`, this artifact defines the half-open boundary as:

```text
chosen_block(t) = MIN(block_number) WHERE block.timestamp >= t
```

Every row is accepted only when the immediately preceding block satisfies `timestamp < t`, the chosen block satisfies `timestamp >= t`, the block numbers are adjacent, and the chosen block's `parentHash` equals the predecessor hash. A midnight close, average block-time interpolation, or nearest event is not an admissible final boundary.

## Frozen population

The canonical population contains 227 distinct timestamps and 228 semantic roles:

- 56 baseline closes from `2025-07-10T13:00:00Z` through `2025-09-03T13:00:00Z`;
- 169 campaign snapshots from `2025-09-03T13:00:00Z` through `2026-02-18T13:00:00Z`;
- `P30`, `P90`, and `P180` at `2026-03-20T13:00:00Z`, `2026-05-19T13:00:00Z`, and `2026-08-17T13:00:00Z`.

The campaign-start timestamp has both `baseline_close_56` and `campaign_snapshot_000` roles. The distinct-count formula is `56 + 169 - 1 + 3 = 227`. The canonical timestamp-list SHA-256 is `be8ee9c6c0a80864090d50b2d16737acd58da5c70a184a7728666ca0f3d04959`.

## Reproducible implementation

`scripts/build_phase7_frozen_boundaries.py` opens the accepted Phase 6 production database with `mode=ro&immutable=1` and uses its accepted UTC-day blocks only as search brackets. It validates live chain ID `42161`, rate-limits batched requests, retries transient failures, and only calls:

- `eth_chainId`;
- `eth_getBlockByNumber` with `full_transactions=false`.

Validated headers are stored in a separate SQLite cache keyed by `(chain_id, rpc_method, block_number)`. Each cached row includes block number, block hash, parent hash, timestamp, and a SHA-256 of the validated RPC result. A transaction commits valid responses before a later transaction advances binary-search state. Cache identity binds the script, exact target list, production database, frozen metrics, eligibility bridge, and accepted production day boundaries. Resume stops on any identity mismatch.

Run or verify from PowerShell:

```powershell
python .\scripts\build_phase7_frozen_boundaries.py
python .\scripts\build_phase7_frozen_boundaries.py --offline-only
```

When the immutable manifest already exists, the second command validates its artifact and cache fingerprints without making a network call.

## Stop/resume evidence

The first run stopped intentionally after completed binary-search round 3:

- 227 search states persisted;
- 912 unique validated block headers persisted;
- cache integrity was `ok` and duplicate cache keys were zero.

The second run resumed at round 4. Across both runs, `eth_getBlockByNumber` contained 4,427 RPC items and the sealed cache contains exactly 4,427 unique block headers. Therefore no confirmed block-header call was repeated. The two additional RPC items are the separately validated `eth_chainId` call at each process start.

## QA result

| Check | Result |
|---|---:|
| Target timestamps | 227 / 227 |
| Unique target timestamps | 227 / 227 |
| Missing boundaries | 0 |
| Duplicate timestamps | 0 |
| Non-monotonic boundary blocks | 0 |
| Predecessor timestamp `< target` | 227 / 227 |
| Chosen timestamp `>= target` | 227 / 227 |
| Adjacent block-number failures | 0 |
| Parent-hash failures | 0 |
| Accepted Phase 6 day-bracket failures | 0 |
| Invalid cache entries | 0 |
| Duplicate cache keys | 0 |
| SQLite integrity | `ok` |

The first chosen boundary is block `356233093`; the last is block `495489315`. In this population every chosen block timestamp equals the target second and every predecessor timestamp is one second earlier.

The accepted Phase 2/6 timestamp map contains midnight boundaries, while all 227 frozen targets are at 13:00 UTC. Exact timestamp intersections are therefore zero and intersection mismatches are also zero. This is not presented as an independent same-timestamp match. The applicable reconciliation is complete: all 227 chosen blocks fall inside the corresponding accepted Phase 6 day brackets.

## RPC and storage evidence

- HTTP requests: 236 total — 2 chain-ID requests and 234 successful block batches;
- RPC items: 4,429 total — 2 chain-ID items and 4,427 block-header items;
- response bytes: 10,344,658;
- configured retries: 6; observed error attempts/retries: 0;
- rate limit: at least 0.5 seconds between HTTP requests;
- sealed cache: 1,495,040 bytes; no remaining WAL or `.part` file.

No `eth_getLogs` call or GBA query was made. The Phase 6 production database remains 1,878,016,000 bytes with SHA-256 `80aca74cc5e43db03fd93c69d7ad448ac9afdec5f9566a6b833ec11f7e5c9543`. Frozen metrics v1.0 and the eligibility bridge also retain their accepted fingerprints.

## Published artifacts

- `data/morpho_phase7_boundary_map.csv` — 227 reviewable rows;
- `data/morpho_phase7_boundary_map.json` — complete machine-readable evidence;
- `data/morpho_phase7_boundary_qa.json` — blocking QA and RPC/cache telemetry;
- `data/morpho_phase7_boundary_manifest.json` — immutable identity and artifact fingerprints;
- `data/morpho_phase7_boundary_checkpoint.json` — final compact resume status;
- `data/tmp/morpho_phase7_boundary_cache_v1.sqlite` — sealed local cache, ignored by Git.

## Current boundary

This artifact resolves only the exact timestamp-to-block mapping required by frozen metrics v1.0. It does not calculate market states, retained uplift, active borrowers, findings, or charts. Phase 7 remains current and Phase 8 remains locked.
