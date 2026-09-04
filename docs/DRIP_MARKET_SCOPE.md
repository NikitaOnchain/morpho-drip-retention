# DRIP Season 1 × Morpho: verified campaign scope

Access date: **2026-08-31**.

## Result

- 36 root Merkl campaigns distributed **3,982,500 ARB** to Morpho-related DRIP opportunities across 12 epochs.
- The market-level campaign configurations contain **45 distinct Morpho market IDs**: 32 USDC-loan markets and 13 USD₮0-loan markets.
- The exact IDs, asset addresses, LLTV values, and eligible supply/borrow epochs are in [`data/drip_morpho_markets.csv`](../data/drip_morpho_markets.csv).
- Exact root campaign IDs, timestamps, allocation scopes, budgets, and source URLs are in [`data/drip_morpho_epoch_campaigns.csv`](../data/drip_morpho_epoch_campaigns.csv).

This completes the campaign-scope inventory only. It does not confirm event coverage, position reconstruction, price data, or analysis readiness.

Reproducibility update (2026-09-02):
`scripts/extract_drip_morpho_scope.py` now rebuilds both accepted CSVs through a
fail-closed raw-snapshot/candidate comparison workflow. A fresh Merkl response
reproduced both accepted files byte-for-byte with zero key or field defects;
the immutable evidence references are in
`data/drip_morpho_scope_reproducibility_manifest.json`. The accepted CSVs were
not overwritten.

## Source hierarchy and filtering rule

The canonical eligibility records are the Merkl root campaign configurations. Merkl documents campaign configuration as the source of truth used by its engine and states that the encoded configuration is stored onchain in the Distribution Creator contract. The extraction used:

- compute/distribution chain: Arbitrum One (`42161`);
- protocol: `morpho`;
- program tag: `drip`;
- reward token: ARB (`0x912CE59144191C1204E64559FE8253a0e49E6548`);
- DRIP creator: `0x7d0A9493Edecf7112486319E0fDBA72fC7a62468`;
- campaign window: from `2025-09-03T13:00:00Z` through `2026-02-18T13:00:00Z`;
- root campaigns only: `campaignId` begins with `0x`.

Numeric Merkl `campaignId` values are forwarding sub-campaigns, so they were excluded from budget sums. Non-ARB Morpho co-incentives were also excluded even when their opportunities carried the `drip` tag.

API inventory request:

```text
https://api.merkl.xyz/v4/opportunities?mainProtocolId=morpho&tags=drip&campaigns=true&status=PAST&items=100&page=0
```

Each retained campaign has a stable evidence URL in the campaign CSV.

## Epoch allocations

The timestamps below are the exact values in Merkl root campaign records. This inventory does **not** yet assert an inclusive/exclusive event-ordering rule.

| Epoch | Start UTC | End UTC | Market-pool and dedicated campaigns | Direct vault campaigns | Morpho total ARB |
|---:|---|---|---|---:|---:|
| 1 | 2025-09-03 13:00 | 2025-09-17 13:00 | 60K USDC supply + 60K USDC borrow | 0 | 120,000 |
| 2 | 2025-09-17 13:00 | 2025-10-01 13:00 | 120K USDC supply + 120K USDC borrow + 60K syrupUSDC dedicated supply | 0 | 300,000 |
| 3 | 2025-10-01 13:00 | 2025-10-15 13:00 | 360K USDC supply + 120K USDC borrow + 90K syrupUSDC dedicated supply | 0 | 570,000 |
| 4 | 2025-10-15 13:00 | 2025-10-29 13:00 | 340K USDC supply + 120K USDC borrow + 90K syrupUSDC dedicated supply | 0 | 550,000 |
| 5 | 2025-10-29 13:00 | 2025-11-12 13:00 | 300K USDC supply + 120K USDC borrow + 90K syrupUSDC dedicated supply | 0 | 510,000 |
| 6 | 2025-11-12 13:00 | 2025-11-26 13:00 | 55K USDC supply + 55K USDC borrow | 0 | 110,000 |
| 7 | 2025-11-26 13:00 | 2025-12-10 13:00 | 85K USDC supply + 55K USDC borrow | 0 | 140,000 |
| 8 | 2025-12-10 13:00 | 2025-12-24 13:00 | 250K USDC supply + 40K USDC borrow | 0 | 290,000 |
| 9 | 2025-12-24 13:00 | 2026-01-07 13:00 | 270K USDC supply + 20K USDC borrow + 20K USD₮0 borrow | 140,000 | 450,000 |
| 10 | 2026-01-07 13:00 | 2026-01-21 13:00 | 220K USDC supply + 60K USD₮0 borrow | 140,000 | 420,000 |
| 11 | 2026-01-21 13:00 | 2026-02-04 13:00 | 145K USDC supply + 40K USD₮0 borrow | 140,000 | 325,000 |
| 12 | 2026-02-04 13:00 | 2026-02-18 13:00 | 72.5K USDC supply + 40K USD₮0 borrow | 85,000 | 197,500 |
| **Total** |  |  | **3,477,500** | **505,000** | **3,982,500** |

Across the season, the market-linked allocation comprises 2,277,500 ARB in shared USDC supply pools, 710,000 ARB in shared USDC borrow pools, 160,000 ARB in shared USD₮0 borrow pools, and 330,000 ARB in dedicated syrupUSDC supply campaigns.

## Allocation semantics

A `shared_market_pool` row is one Merkl multi-market campaign budget, not a fixed allocation to every listed market. Merkl states that a multi-market campaign cascades rewards across whitelisted Morpho markets based on market liquidity/size and the user's share. Therefore:

- do not multiply the parent amount by `unique_market_count`;
- do not divide the parent amount evenly across market IDs;
- do not calculate market-level cost effectiveness until realized Merkl distribution records or another defensible allocation rule are added.

The syrupUSDC/USDC market (`0xf86f3edd6f16cd8211f4d206866dc4ecd41be6211063ac11f8508e1b7112ef40`) was also covered by dedicated 60K/90K supply campaigns in epochs 2–5. Those budgets are additive to its eligibility in the shared USDC supply pool.

## Direct vault campaigns

Epochs 9–12 include 505,000 ARB of direct Steakhouse vault incentives:

- `bbqUSDC`: `0xbeeff1D5dE8F79ff37a151681100B039661da518`;
- `bbqUSDT0`: `0xbeeff77CE5C059445714E6A3490E273fE7F2492F`.

These root configurations target vault tokens, not Morpho market IDs. They are included in Morpho's epoch totals but excluded from the 45-market eligibility count. Their ARB must not be attributed to underlying markets without time-aware vault allocation evidence.

## Reconciliation and anomalies

1. All 12 Morpho totals reconcile to Entropy's final allocation chart: 120K, 300K, 570K, 550K, 510K, 110K, 140K, 290K, 450K, 420K, 325K, and 197.5K ARB.
2. The January update says epoch 11 Morpho received 140K base plus 180K special-purpose incentives, which would total 320K. The same post says the epoch distributed 695K overall. Merkl records show a 145K USDC supply campaign, and Entropy's final chart shows 325K for Morpho. This inventory uses the campaign record and final chart: **145K + 40K + 70K + 70K = 325K**.
3. Merkl campaign DB IDs `1695825053467459259` (epoch 8) and `2173420697471906676` (epoch 9) each repeat the same PT-USDai market child record twice, with identical child campaign ID `0x8d61fbea5b64f4afcf6238ebb29c57b1c277b01b`. The extract de-duplicates by `epoch + campaign_db_id + side + market_id`; unique supply-market counts are 22 and 23 rather than the raw array counts 23 and 24.
4. Several asset pairs have more than one market ID. Market ID is the canonical key; asset symbols or `loan + collateral + LLTV` are not safe substitutes because other market parameters can differ.

## Primary references

- [Merkl campaign configuration](https://docs.merkl.xyz/merkl-mechanisms/campaignConfiguration)
- [Merkl Morpho multi-market campaign semantics](https://docs.merkl.xyz/merkl-mechanisms/campaign-types/lending-borrowing)
- [DRIP September 2025 update](https://forum.arbitrum.foundation/t/drip-september-2025-update/30057)
- [DRIP October 2025 update](https://forum.arbitrum.foundation/t/drip-october-2025-update/30187)
- [DRIP November 2025 update](https://forum.arbitrum.foundation/t/drip-november-2025-update/30321)
- [DRIP December 2025 update](https://forum.arbitrum.foundation/t/drip-december-2025-update/30382)
- [DRIP January 2026 update](https://forum.arbitrum.foundation/t/drip-january-2026-update/30546)
- [DRIP February 2026 update](https://forum.arbitrum.foundation/t/drip-february-2026-update/30628)
- [Final official allocation chart](https://canada1.discourse-cdn.com/flex029/uploads/arbitrum1/original/3X/1/5/1542a5e2c91a3d2f661f5d296249c1327a462d8a.jpeg)
