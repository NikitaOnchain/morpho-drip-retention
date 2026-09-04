# Interpretation Limits and Alternative Explanations

## Presentation guardrail

The 5.65M USDC and 4.14M USD₮0 figures are full outstanding borrowed-asset balances at `P180`. The retained-uplift ratio is `(P180-B)/(E-B)`, not `P180/E`, and the remaining uplift amount is `P180-B`, not `P180`. None of these amounts is identified as debt causally created or preserved by DRIP.

## Accepted release caveats

Independent re-review returned **APPROVE WITH CAVEATS** and closed R1–R4; see [review evidence](../reviews/public/README.md). Full raw rebuild and new-DB logical reconciliation were **not run**. Public acquisition of the source bundle is **unavailable**. Browser/GitHub rendering was **not checked**. These are accepted limitations, not successful tests.

The CSV-only route is autonomous with the documented Python/Pillow/fonts. The tested SQLite-route requires the external accepted production database and metadata snapshot. The package is **not self-contained for reconstruction from raw**. Cross-platform fonts and a fresh dependency installation also remain untested.

## What the design does not identify

- This is observational before/after analysis of a fixed eligible-market panel, not an experiment or causal estimate. There is no untreated counterfactual.
- Users of eligible markets are not confirmed reward recipients. No exact Merkl recipient attribution is available. A wallet can be a smart contract and is not a person.
- Material active-borrower counts are cross-sectional at each checkpoint. They are not cohorts of the same wallets; no cohort retention, wallet clustering or wallet concentration is claimed.
- Native balances are grouped by exact token address. USDC is not added to USD₮0; heterogeneous collateral is not summed. There is no historical price/USD layer, risk-adjusted return, or cost per retained dollar.
- Shared ARB pools remain campaign-level. Direct-vault incentives are not assigned to underlying markets. Market-level incentive efficiency cannot be inferred.

## Accounting and coverage limits

- The accepted source is scoped to the official Morpho contract, eight event families and 45 eligible markets. It does not represent every Arbitrum lending market or every DRIP protocol.
- All 45 anchors are independently zero-verified. Later independent RPC reconciliation is bounded, not a call at every market-day or every Phase 7 checkpoint.
- Aggregate collateral has no market-level RPC getter and is reconstructed from zero anchors and all collateral/seizure events.
- State changes only at emitted events; no synthetic between-event interest is added. Borrowed assets include accrued interest and must not be equated to new principal demand.
- Non-zero fee shares were implemented from the official specification but not empirically exercised. Three non-zero bad-debt events were exercised and reconciled. The older frozen metrics note refers to the bounded prototype; the later Phase 6 evidence supersedes only its empirical coverage status, not the metric contract.
- A full source snapshot and original evidence must be made accessible separately for complete third-party reproduction; the Git candidate intentionally omits large raw/cache/SQLite files.

## Comparisons that require care

Late markets can have tiny or zero baseline values. Small positive `E-B` can generate very large ratios; exact levels, deltas and applicability must accompany them. `E-B<=0` is not applicable, never zero-filled. No market is removed because it matured, became inactive, or performed poorly.

The global campaign end is used even for markets whose eligibility ended earlier. That is the frozen primary definition; it does not normalize every market to the same local exposure duration. Campaign peak uses 169 aligned snapshots, not an intraday maximum. Only three post checkpoints are observed in the chart series; connecting segments do not describe the intervening daily path.

## Alternative explanations

Changes in collateral prices, borrowing rates, competing rewards, general lending conditions, principal-token maturities, refinancing, protocol/market migrations, risk preferences and organic adoption can all affect balances. Gross borrow/repay flows may contain turnover or leverage recycling. None is automatically separated into a causal contribution by the before/after design.

Technical/descriptive confidence is high, decision-usefulness confidence moderate, and causal confidence low. Independent re-review is accepted with the caveats above. Publication approval remains outstanding.
