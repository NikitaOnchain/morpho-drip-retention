# Phase 3 archive-RPC cache handoff

> **Historical checkpoint — superseded on 2026-09-01.** The user completed the full 5,575-candidate pass, and `data/morpho_one_position_selection.json` is now `complete`. Do not run the full-pass commands below again. Current selection and reconstruction evidence is in `docs/MORPHO_ONE_POSITION_RECONSTRUCTION.md`.

Date: **2026-09-01 Europe/Moscow / 2026-08-31 UTC**  
Status: **bounded stop/resume test PASS; full 5,575-candidate pass not started**

## Implemented contract

`scripts/select_morpho_one_position.py` now uses `scripts/morpho_archive_rpc_cache.py` for historical `eth_call` state.

- SQLite uses WAL, `synchronous=FULL`, transactions and an immutable cache identity.
- The cache key includes chain ID, normalized contract, RPC method, ABI method, block number, market ID and wallet where applicable.
- Every live run first validates `eth_chainId == 42161`.
- JSON-RPC envelopes must contain the matching request ID, `jsonrpc=2.0`, no error and a result.
- Calldata is regenerated and checked against `position(bytes32,address)`, `market(bytes32)` or `feeRecipient()`.
- ABI results must be exact-length hexadecimal: 3, 6 or 1 32-byte words respectively.
- Each response is checksum-committed in its own transaction. Only after that commit does a second transaction advance the contiguous plan checkpoint.
- Resume validates cached response/key checksums and the original deterministic call ordinal before use.
- Cache identity binds selector cache version, chain/contract, Phase 2 manifest SHA-256/rows/shards/block interval, selection-criteria SHA-256, candidate-population kind/count/SHA-256 and the verified fee-recipient-history assumption. Any mismatch fails closed.
- Error responses are never cached.

## Bounded evidence

The bounded fixture contains 12 exact structural candidates and is committed by candidate-population SHA-256 `737932ac1e4e5a72a0524032a7e5737d4e309f1286b16e8b6c75995aadeea2bf`.

The fixture was created with a targeted stream: it discovered a pool of 40 early candidates, then retained only those keys through the remaining immutable shards. It did not rebuild the global 9,959-to-5,575 funnel. Twenty-seven candidates remained exact after full-history event-count validation; the first 12 in the predeclared canonical fixture order were used.

| Run | Cache hits | New archive calls | Cache rows after run | Checkpoint |
|---|---:|---:|---:|---:|
| Intentional stop | 0 | 8 | 8 | 7 |
| Resume | 8 | 41 | 49 | 48 |
| Cache-only replay | 49 | 0 | 49 | 48 |

The third run made one HTTP request solely for mandatory live `eth_chainId`; it made zero archive `eth_call` requests. Final audit: SQLite integrity `ok`, WAL active, 49/49 contiguous progress rows, and zero invalid rows, duplicate key groups, error rows, gaps or orphan progress rows. All 12 bounded candidates had zero-state initialized anchors and available final checkpoints.

Six local unit tests also passed: stop/resume, repeated logical call at two ordinals, recovery when a response was committed before its checkpoint, invalid-result rejection, cache-identity mismatch and corruption detection.

Evidence:

- `data/morpho_phase3_rpc_cache_test_summary.json`
- `data/morpho_phase3_rpc_cache_stop.json`
- `data/morpho_phase3_rpc_cache_resume.json`
- `data/morpho_phase3_rpc_cache_cache_only.json`
- `data/morpho_phase3_bounded_candidates.json`
- ignored local cache: `data/tmp/morpho_phase3_bounded_cache.sqlite`

## Full-pass start/resume commands

The old complete offline run persisted funnel counts but not the 5,575 candidate records. Therefore a zero-rescan full start is impossible from the current artifacts. This bounded work did not repeat that funnel. Unless the missing population artifact is recovered, the first user-run command must perform one local, read-only re-materialization while starting the authorized full archive-state pass:

```powershell
python .\scripts\select_morpho_one_position.py `
  --write-candidate-population .\data\morpho_phase3_structural_candidates.json `
  --cache .\data\tmp\morpho_phase3_archive_rpc.sqlite `
  --output .\data\morpho_one_position_selection.json `
  --rpc-url https://arbitrum-one.public.blastapi.io `
  --assume-verified-no-fee-recipient-changes `
  --allow-full-archive-pass `
  --retries 8 `
  --min-request-interval 0.75
```

After that population file exists, every restart must use it so the offline funnel is not repeated:

```powershell
python .\scripts\select_morpho_one_position.py `
  --candidate-population .\data\morpho_phase3_structural_candidates.json `
  --cache .\data\tmp\morpho_phase3_archive_rpc.sqlite `
  --output .\data\morpho_one_position_selection.json `
  --rpc-url https://arbitrum-one.public.blastapi.io `
  --assume-verified-no-fee-recipient-changes `
  --allow-full-archive-pass `
  --retries 8 `
  --min-request-interval 0.75
```

Do not change the candidate file, cache version, manifest, criteria or fee-history flag between restarts. A provider URL may change only after its live chain ID is validated; the cached identity is chain/contract-bound rather than provider-bound.

## Stop boundary

No full archive-state pass, candidate ranking, rank-1 selection, reconstruction SQL, daily state or Phase 4 work was run in this session. Phase 3 remains `CURRENT`; Phase 4 remains `LOCKED`.
