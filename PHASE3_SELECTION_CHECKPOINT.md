> Historical checkpoint only; selection and Phase 3 are complete. Do not execute obsolete continuation instructions.

# Phase 3 deterministic-position selection checkpoint

Checkpoint date: **2026-08-31**  
Status: **stopped by user; Phase 3 remains CURRENT**

## Authorized task

Apply the precommitted deterministic selection rule in `docs/MORPHO_ACCOUNTING_MODEL.md` to the complete Phase 2 RPC history, construct the exact candidate population, verify the required archive-RPC anchors/checkpoints, rank every eligible pair by the specified SHA-256 preimage, and select rank 1. Do not reconstruct the position yet.

## Completed work

A reusable non-SQL selector was added at `scripts/select_morpho_one_position.py`.

- Script SHA-256: `0330f8f149a329daac79fd63131909170f68676ee8c0022590dbfb5d64c769ed`.
- The script passed `python -m py_compile`.
- It scanned all 3,157 immutable Phase 2 shards and all 1,231,462 scoped raw logs.
- Position-changing rows decoded: 618,233.
- Malformed owner rows: 0.
- Scope mismatches: 0.
- Removed logs: 0.
- Ordering violations: 0.

The complete offline structural funnel is:

| Gate | Wallet-market pairs remaining |
|---|---:|
| Distinct pairs in position-changing events | 9,959 |
| Has `SupplyCollateral` | 9,127 |
| `SupplyCollateral` precedes `Borrow` | 7,013 |
| Has a later `Repay` or `Liquidate` | 6,135 |
| Has 4–50 position-changing events | 5,575 |
| Has same-market `AccrueInterest` after first borrow and no later than the final event block | 5,575 |

The sequence comparison uses the canonical key `(block_number, transaction_index, log_index)`. The final 5,575 pairs are only **structural candidates**. They are not the eligible population until the archive-state and historical fee-recipient gates pass.

An exact `SetFeeRecipient(address)` log query against the official Morpho contract over `[355887376, 495647034)` returned zero logs. The fee recipient active at the beginning of the interval still requires a historical `feeRecipient()` call at `355887375`.

## Archive-RPC work attempted

The state gate requires, for every structural candidate:

1. `position(market_id, wallet)` at `first_event_block - 1` and exact zero collateral, supply shares and borrow shares;
2. `market(market_id)` at that anchor block;
3. an independently available final `position` and `market` checkpoint at the candidate's last event block;
4. exclusion if the wallet was the active fee recipient during its interval.

Provider outcomes during bounded probes/runs:

- Official Arbitrum public RPC: historical `eth_call` failed with `missing trie node ... state ... is not available, not found`.
- PublicNode: `Archive requests require a personal token.`
- dRPC: usage-limit error requiring an upgraded plan.
- Tenderly public gateway: historical probe succeeded, but the full 5,575-candidate state pass stopped after bounded retries with HTTP 429.
- BlastAPI public endpoint: historical probes succeeded. A full state pass was intentionally interrupted after the user's stop request.
- Alchemy public Arbitrum endpoint: an independent historical probe returned the same result as Tenderly and BlastAPI.
- BlockPI returned HTTP 521; the tested rpcfree URL returned HTML rather than JSON-RPC.

The interrupted BlastAPI process was PID 24920. It is confirmed stopped. It produced neither `data/morpho_one_position_selection.json` nor a `.part` file.

## Important resume limitation

The current selector writes its evidence atomically only after all archive-RPC gates finish. It does **not** persist successful RPC batches. Therefore:

- the complete offline funnel above is reproducible and finished;
- partial Tenderly/BlastAPI responses are not evidence and must not be used for selection;
- resuming the current script would rescan the immutable shards and restart the archive-state pass;
- no pair has been selected, no candidate hashes have been ranked, and no final eligible-candidate count exists yet.

## Exact continuation point

Before another full archive-state pass, add a resume-safe cache/checkpoint keyed by `(rpc_method, block_number, market_id, wallet when applicable)` with atomic writes and response validation. Then run only the remaining Phase 3 selection gates against the unchanged full-window snapshot, produce the complete eligible population/evidence, compute the exact preimage

`morpho-phase3-v1|<lowercase market_id>|<lowercase wallet>`

for every eligible pair, sort by ascending hexadecimal SHA-256, and select rank 1.

Do not rerun the Phase 2 extraction. Do not write reconstruction SQL, reconstruct a position, build daily state, or start Phase 4 until the selection completes and the user separately confirms reconstruction.

## 2026-09-01 addendum

The resume-safe SQLite/WAL layer and a bounded 12-candidate stop/resume test are complete and PASS. The exact current state, QA evidence and full-start/resume commands are in `PHASE3_RPC_CACHE_HANDOFF.md`. This supersedes the earlier statement that the selector has no RPC checkpoint; the full 5,575-candidate pass itself remains unstarted.
