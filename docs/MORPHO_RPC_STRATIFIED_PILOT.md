# Morpho stratified multi-day RPC pilot

Access date: **2026-08-31**  
Status: **PASS for three stratified days; Phase 2 remains CURRENT and Phase 3 remains LOCKED. No full-window extraction was started.**

## Outcome

The official Arbitrum One public RPC reproduced the complete scoped GBA population on three strategically different UTC days:

- baseline start day: 0 RPC / 0 GBA rows;
- DRIP campaign-end boundary day: 6,358 / 6,358 rows;
- +180 post-period day, reused from the prior test: 2,087 / 2,087 rows.

Across every window, missing, extra, duplicate-key, topics-mismatch, and raw-data-mismatch counts are zero. A live active-data interruption test also resumed from a 270-row checkpoint without repeating the completed range and finished at exactly 6,358 unique rows.

## Window selection

The exact campaign source records establish `2025-09-03 13:00:00 UTC` through `2026-02-18 13:00:00 UTC`. The project baseline begins eight weeks earlier, at `2025-07-09 13:00:00 UTC`.

| Role | Complete UTC window | Boundary inside the day | Reason |
|---|---|---|---|
| Baseline start | `[2025-07-09, 2025-07-10)` | Baseline starts at 13:00 | Tests old historical availability before incentives |
| Campaign boundary | `[2026-02-18, 2026-02-19)` | Campaign ends at 13:00 | Tests a high-activity, exact campaign boundary |
| Post +180 | `[2026-08-17, 2026-08-18)` | +180 calendar checkpoint | Reuses the already verified day without another download |

The campaign-start day `2025-09-03` was considered first. Its dry-run upper bound combined with the baseline day was 11,157,672,312 bytes (10.39 GiB), above the gate, so it was not executed. The exact campaign-end day was selected instead, as allowed by the pilot design.

## GBA cost gate

| Window | Dry-run upper bound | Actual processed | Actual billed | New scan? |
|---|---:|---:|---:|---|
| Baseline start | 5,587,488,684 | 5,410,352,105 | 5,410,652,160 | Yes |
| Campaign end | 4,037,319,193 | 3,860,182,614 | 3,860,856,832 | Yes |
| Post +180 | 3,175,809,476 | 3,064,373,457 | 3,064,987,648 | No; reused |
| **Two new pilot jobs** | **9,624,807,877 (8.964 GiB)** | **9,270,534,719 (8.634 GiB)** | **9,271,508,992 (8.635 GiB)** | **Within gate** |

Both new queries were dry-run before execution. The already completed post query generated no new scan in this pilot and is therefore excluded from the new 8–10 GiB budget.

## Reconciliation

| Window | Blocks | GBA rows | RPC rows | Matched keys | Missing | Extra | RPC/GBA duplicate groups | Topics mismatch | Raw-data mismatch |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline start | 345,285 | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 0 | 0 |
| Campaign end | 346,632 | 6,358 | 6,358 | 6,358 | 0 | 0 | 0 / 0 | 0 | 0 |
| Post +180 | 343,386 | 2,087 | 2,087 | 2,087 | 0 | 0 | 0 / 0 | 0 | 0 |

The baseline zero is an observed coverage result, not a missing-data assumption: the RPC queried the entire day and returned no logs matching the official contract × eight event families × 45 eligible market IDs, exactly like GBA.

## Requests, retries, time, and volume

| Window | Total RPC attempts | `eth_getLogs` attempts | Retries / error attempts | Successful log time | Total response bytes | Log response bytes |
|---|---:|---:|---:|---:|---:|---:|
| Baseline start | 58 | 6 | 3 / 3 | 20.181 s | 98,348 | 223 |
| Campaign end | 60 | 10 | 0 / 0 | 8.031 s | 4,816,576 | 4,703,888 |
| Post +180 | 65 | 10 | 3 / 3 | 5.734 s | 1,664,679 | 1,555,804 |

The baseline and post errors were 60-second `eth_getBlockByNumber` timeouts during boundary search; all retries succeeded. The primary campaign extraction had no errors.

Observed first-run wall time was dominated by boundary timeouts: approximately 211 seconds for baseline, 57 seconds for campaign end, and 204 seconds for the prior post day. Successful `eth_getLogs` calls themselves were much faster.

## Resume verification

The baseline runner intentionally stopped after its first completed range. Its partial checkpoint contained zero rows, then resumed from `next_block=355720452`, covered the remaining five ranges, and finished without overlap or gaps. This proved range continuation but was weak evidence for row-level duplication because the completed range was empty.

The stronger active-data test used a separate campaign-end checkpoint namespace:

1. The first completed range `[433213243, 433233243)` produced 270 rows.
2. The intentional-stop checkpoint contained 270 unique keys, zero duplicates, and `next_block=433233243`.
3. The second process loaded that checkpoint and began at range 2 rather than re-fetching range 1.
4. It finished with ten contiguous ranges, 6,358 rows, 6,358 matched GBA keys, and zero duplicates or field mismatches.
5. One `eth_getLogs` call timed out during the resumed run and succeeded on retry, providing direct evidence that log-request retries work.

The active resume evidence is stored under files whose label includes `2026-02-18_resume`.

## Full-window extraction estimate

The target interval is `[2025-07-09 13:00:00 UTC, 2026-08-18 00:00:00 UTC)`, or 404.458 days. The three days average 345,101 blocks/day, implying approximately 139.6 million blocks.

| Estimate | Low | Central | High |
|---|---:|---:|---:|
| `eth_getLogs` requests | 2,792 | 3,506 | 4,046 |
| Total RPC attempts including one boundary/control allowance | 2,850 | 3,561 | 4,101 |
| Event rows | 844,105 | 1,138,550 | 2,571,546 |
| Serialized raw-log size | 0.56 GiB | 0.75 GiB | 1.69 GiB |

The request estimate uses observed adaptive spans: approximately 34.5K blocks/request on active days, 57.5K on the empty baseline day, and 39.8K across all pilot ranges. The central request time uses the observed 1.306 seconds per successful `eth_getLogs` attempt, or about 76 minutes of successful network time. A practical planning envelope is **2–6 hours** after throttling, retries, checkpointing, and filesystem work.

These estimates have **medium confidence for request count and medium-low confidence for duration and row volume**. Three stratified days do not establish the activity distribution across 404 days, and a public RPC can change its rate limits or latency.

### Resolved storage precondition; extraction remains unauthorized

The bounded runner has now been refactored to immutable append-only range shards plus a verified manifest. An active-data stop/resume test preserved its first 270-row shard, resumed from the exact next block, and finished with ten contiguous shards, 6,358 unique rows, and zero defects. Full evidence is in `MORPHO_RPC_APPEND_ONLY_RESUME.md`.

Expected final raw storage remains approximately 0.6–1.7 GiB. Resolving persistence scalability does not authorize or prove the full 404-day extraction.

## Interpretation

The pilot provides high-confidence evidence that the RPC route can reproduce GBA raw logs at baseline, campaign-boundary, and post-period strata. The follow-up append-only test shows that verified range shards recover from process interruption without re-fetching a completed range.

It does **not** prove complete coverage for every block in the 404-day history. It does not validate position reconstruction, rewards, retention, or causality. Full-history GBA reconciliation also remains economically infeasible; the defensible route is full RPC extraction with internal continuity checks and the completed stratified GBA comparisons.

Phase 2 remains CURRENT. Phase 3 remains LOCKED.
