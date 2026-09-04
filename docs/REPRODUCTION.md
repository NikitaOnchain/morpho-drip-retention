# Reproduction: two explicit routes

Run from the **assembled release package root**, not the original workspace. Use new sibling output folders outside the package. This package contains code, frozen definitions, compact reviewed CSVs/evidence and figures, but no production SQLite, raw logs, credentials or caches. No command below fetches RPC/GBA data.

Independent re-review: **APPROVE WITH CAVEATS**, R1–R4 CLOSED; see [review evidence](../reviews/public/README.md). CSV-only is autonomous given the documented runtime/fonts. The SQLite-route is tested but requires two external inputs. The package is **not self-contained for raw reconstruction**: full raw rebuild was not run, public source-bundle acquisition is unavailable, and browser/GitHub rendering was not checked.

## Runtime

Tested in this correction pass: Python 3.12.14, SQLite 3.53.1 (stdlib), Pillow 12.3.0, Windows. Earlier RC tests used Python 3.12.13. Accepted Phase 6 originally used SQLite 3.50.4. SQL amounts are decimal TEXT with registered exact-integer Python UDFs, not floating-point or bare SQLite arithmetic. Install dependencies in your own prepared environment (no installation was performed in this correction pass):

```powershell
python -m pip install -r .\requirements-release.txt
```

Exact PNG reproduction requires legally installed `segoeui.ttf` and `segoeuib.ttf`, found in system Fonts or via `MORPHO_FONT_DIR`. Fonts are **not distributed**; used font hashes are recorded in CSV QA. Missing fonts fail clearly. Cross-OS/font reproduction and browser/GitHub rendering are **not certified**. Optional historical Markdown preview uses Node 24.19.0 / marked 17.0.5; neither is required for these two routes.

## Route 1 — CSV-only

Only included CSVs, manifests and renderer are needed: **no DB, raw metadata or RPC**. The command verifies five CSV hashes, 648 metric rows, exact-fraction ratios/applicability and key uniqueness, then renders six PNGs. This is published-table/render reproduction, not independent onchain completeness or event-state reconstruction.

```powershell
python -B .\scripts\audit_release_package.py
python -B .\scripts\reproduce_release_csv.py --output ..\csv_reproduction_01 --verify-figures
```

Outputs: six figures plus `csv_qa.json`. `--verify-figures` compares to the **revised package** images, not pre-review originals. Active-borrower/archetype post values are isolated markers; the other four figures retain accepted bytes.

## Route 2 — External-input SQLite reproduction and full reconstruction

### Required external inputs and access

[External manifest](../release/external_inputs.json) lists exact paths, sizes and SHA-256, including all 3,157 shards. **There is no public bundle URL or tested third-party acquisition route yet.** Request a privacy-reviewed checksum-matched archival bundle from the maintainer. Until provided, use CSV-only. Missing files stop explicitly; current API responses cannot silently replace accepted snapshots. No extraction fallback runs.

Place the provided files in sibling `..\source_bundle` using manifest-relative paths. Never add arbitrary private files to the public package.

| Excluded input | Role / identity |
|---|---|
| `data/tmp/morpho_market_day_full_v1.sqlite` | Accepted production; 1,878,016,000 bytes; SHA-256 `80aca74cc5e43db03fd93c69d7ad448ac9afdec5f9566a6b833ec11f7e5c9543` |
| `data/raw/drip_morpho_scope/merkl_opportunities_20260902T115959247853Z.json` | Metadata/decimals; SHA-256 `4d9bc3e011ce56ad555b3b650d42198d83fd78d35594d8b93e1f56d5362ae8c7` |
| `data/raw/morpho_full_window/manifest.json`, `day_boundaries.json`, all shards | Manifest SHA-256 `c8552428187094e5aad725193f2e3023e622ddc4ab37428f1414c375e7d6be58`; 1,231,462 logs / 786,571,394 shard bytes / `[355887376,495647034)` |
| `data/tmp/morpho_phase4_market_day_rpc.sqlite` | Sealed 12-response cache; copied before use |
| `data/tmp/morpho_phase6_rpc_checkpoints_v1.sqlite` | Sealed 60-response cache; copied before use |

Included: v1.0 metrics, 469-row bridge, 45-market/36-campaign CSVs, archetypes/checkpoint plans, exact 227-boundary map/manifest/QA, portable Phase 1/4/6 evidence and Python/SQL dependencies. Phase 3 selection SQLite and Phase 7 header cache are not required.

### 2a. Accepted SQLite → metrics/review → figures (tested)

This level needs only the first two external files. Require at least 10 GiB free for versioned copies. No hardlinks are used. The legacy entrypoint now accepts an explicit bundle:

```powershell
python -B .\scripts\reproduce_phase7_isolated.py --bundle ..\source_bundle --destination ..\metrics_reproduction_01
```

It runs read-only `review_phase7_headlines.py`, then the portable analyzer; checks five CSVs against frozen hashes and regenerates revised figures. Outputs include `route_qa.json`, `work/headline_review.json`, `work/reproduced_analysis_manifest.json`, `work/figures/csv_qa.json`. Do not run the analyzer directly over published results. [Derivative manifest](../release/derivative_manifest.json) explicitly maps portable code/evidence to original identity; frozen hashes are never silently replaced.

### 2b. Raw logs + copied caches → state

```powershell
python -B .\scripts\release_routes.py --mode raw-preflight --bundle ..\source_bundle --destination ..\raw_preflight_01
# Separate, deliberately selected full offline rebuild:
python -B .\scripts\release_routes.py --mode raw --bundle ..\source_bundle --destination ..\raw_reconstruction_01
```

Preflight verifies external hashes, parses all four complete CLI argument sets, reproduces Phase 1 candidate CSVs/bridge and writes `raw_commands.json`. It **does not build state**. The second command executes prototype and full-state SQL in a fresh job. Offline cache misses stop. Expanded commands and the new-database reconciliation/identity gate are in [Full reconstruction commands](FULL_RECONSTRUCTION_COMMANDS.md).

Correction-pass status: CSV-only, accepted-SQLite metrics and raw-preflight tested from staging with explicit copied inputs. Full author raw → prototype → production rebuild, new-DB logical reconciliation, public-bundle acquisition, cross-platform figures and final browser rendering are **NOT RUN**, not PASS. Historical/independent QA of accepted results is not proof these unrun steps executed.
