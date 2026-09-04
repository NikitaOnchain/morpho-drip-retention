# Phase 4 market archetypes

Access date: **2026-09-01**  
Status: **frozen before the market-day prototype; Phase 4 COMPLETE — accepted 2026-09-01**

## Selection rule

The prototype reuses the exact three archetype-priority market IDs already hard-coded in the accepted Phase 2 deterministic-sample query. That rule predates the Phase 3 reconstruction and any Phase 4 daily output:

1. early shared USDC: the Phase 2 USDC borrow/repay priority;
2. dedicated syrupUSDC: the Phase 2 supply/withdraw priority and the unique market targeted by the dedicated syrupUSDC campaigns;
3. late USD₮0: the Phase 2 USD₮0 collateral/accrual priority.

This is the deterministic tie-break. No market was ranked or replaced using daily-state outcomes, activity level, reconciliation convenience, or the incidence of non-zero fee shares or bad debt. The priority evidence is in [`../sql/00_feasibility_morpho_event_coverage.sql`](../sql/00_feasibility_morpho_event_coverage.sql); its SHA-256 is `10e3aef8bedb705da47ae95477f136fc98f7e0e3b70344e466fc6c1bc847b7c0`.

## Frozen markets

| Archetype | Exact market ID | Loan asset | Collateral asset | Campaign and epoch coverage | First scoped event data | Why this market |
|---|---|---|---|---|---|---|
| Early shared USDC | `0xd09404e9512e1341321c8ae3bd663fab7087582142ac61486635a6c072c2af12` | USDC — `0xaf88d065e77c8cC2239327C5EDb3A432268e5831` | weETH — `0x35751007a407ca6FEFfE80b3cB397736D2cf4dbe` | Shared USDC supply epochs 1–12 (`2025-09-03 13:00`–`2026-02-18 13:00` UTC); shared USDC borrow epochs 1–9 (`2025-09-03 13:00`–`2026-01-07 13:00` UTC) | `2025-07-18` UTC; first scoped log block `358881054`, tx index `6`, log index `51`, `AccrueInterest` | It is the exact early-USDC priority fixed in Phase 2 and is continuously supply-eligible from epoch 1. |
| Dedicated syrupUSDC | `0xf86f3edd6f16cd8211f4d206866dc4ecd41be6211063ac11f8508e1b7112ef40` | USDC — `0xaf88d065e77c8cC2239327C5EDb3A432268e5831` | syrupUSDC — `0x41CA7586cC1311807B4605fBB748a3B8862b42b5` | Shared USDC supply epochs 1–12 and borrow epochs 1–9; dedicated supply epochs 2–5 (`2025-09-17 13:00`–`2025-11-12 13:00` UTC), totaling 330,000 ARB across 60K + 90K + 90K + 90K root campaigns | `2025-08-29` UTC; first scoped log block `373644710`, tx index `3`, log index `4`, `AccrueInterest` | It is both the exact Phase 2 priority and the unique market ID named by the dedicated syrupUSDC campaigns. |
| Late USD₮0 | `0x571cb3ac535d61d92026c071ef1df4794d0bbbe1755f916ff640746f81b52af4` | USD₮0 — `0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9` | syrupUSDC — `0x41CA7586cC1311807B4605fBB748a3B8862b42b5` | Shared USD₮0 borrow epochs 9–12 (`2025-12-24 13:00`–`2026-02-18 13:00` UTC); no market-level DRIP supply campaign | `2025-12-23` UTC; first scoped log block `413594451`, tx index `1`, log index `1`, `AccrueInterest` | It is the exact late-USD₮0 priority fixed in Phase 2 and first becomes campaign-eligible at the epoch-9 USD₮0 launch. |

The machine-readable copy is [`../data/morpho_phase4_market_archetypes.csv`](../data/morpho_phase4_market_archetypes.csv). LLTV is `86%` for the early USDC market and `91.5%` for the other two.

## Data-start semantics and evidence

`First scoped event data` means the first occurrence of the market ID when the immutable Phase 2 shards are read in `(block_number, transaction_index, log_index)` order, limited to the eight accepted event families. It is not a claim about the market's creation time or events before the snapshot. A later daily-state replay must therefore use a defensible initial market-state anchor rather than silently assume zero.

The scan used the accepted full-window snapshot for `[2025-07-09 13:00:00, 2026-08-18 00:00:00)` with manifest SHA-256 `c8552428187094e5aad725193f2e3023e622ddc4ab37428f1414c375e7d6be58`. UTC days were assigned with the independently verified boundary table. The exact source fingerprints are:

- market scope CSV: `a88fceaa19fe383bb956ef698a819facb2d345a29bd173db730e85bbd5213a6a`;
- root campaign CSV: `6474919d49b87ed38df72de55f470f24535a506899a4ccdcfb05c2085a27045b`;
- UTC boundary CSV: `1f72f279c3de167f8bcd14b161ff2b1bf2def99c627d08f04147c58d38a9121e`.

Campaign scope and allocation semantics come from [`DRIP_MARKET_SCOPE.md`](DRIP_MARKET_SCOPE.md), [`../data/drip_morpho_markets.csv`](../data/drip_morpho_markets.csv), and [`../data/drip_morpho_epoch_campaigns.csv`](../data/drip_morpho_epoch_campaigns.csv). Shared-pool budgets are not divided evenly or attributed as realized market-level spend.

## QA coverage matrix

This matrix was frozen before implementation. The bounded prototype executed it on 2026-09-01 without changing the selected markets.

| Branch | Required future check | Outcome now |
|---|---|---|
| Ordinary supply/borrow/collateral and interest transitions | Reconcile ordered event deltas to daily market totals and independent checkpoints | PASS: 275,797 events, 1,215 daily rows, 12/12 RPC checkpoints, zero blocking defects |
| Non-zero `feeShares` | Search all three fixed markets; if present, verify the `AccrueInterest` supply-share transition and fee accounting | 0 non-zero events; implemented but not empirically exercised |
| Non-zero `badDebtAssets` or `badDebtShares` | Search all three fixed markets; if present, verify liquidation write-off transitions and lender loss | 0 non-zero events; implemented but not empirically exercised. Eleven ordinary liquidations had zero bad debt |

If either rare branch is absent, the prototype must report it as empirically unexercised and carry the limitation forward. Absence is not a reason to change the selection rule.

## Current boundary

The bounded implementation and QA are complete in [`MARKET_DAY_PROTOTYPE.md`](MARKET_DAY_PROTOTYPE.md). The user explained the executed grain/JOIN/replay logic and explicitly accepted Phase 4 on 2026-09-01. No retention metric or Phase 5 work has started; Phase 5 remains `LOCKED`.
