# Independent Reviewer Brief

## Mandate

Status update: independent re-review is accepted as **APPROVE WITH CAVEATS**, R1–R4 **CLOSED**. See [public re-review evidence](../reviews/public/README.md). The mandate below is preserved as the original review procedure, not an outstanding request. Full raw rebuild, public source access and browser/GitHub rendering remain explicitly unverified/unavailable; publication approval is separate.

Re-review context: the independent 4 September review confirmed frozen numbers and returned `CHANGES REQUESTED` for R1–R4. Inspect the actual revised staging package, [response](RESPONSE_TO_REVIEW.md), original-to-derivative manifest and route receipts. Original review files remain unchanged; the author's response is not signoff.

Review the question, accounting and interpretation without relying on the ready-made findings text. Start with frozen definitions and production evidence; open the README/report only after recomputing the headline metrics. Same-author preflight PASS is supporting evidence, not independent signoff.

## Primary evidence, in order

1. `docs/METRICS.md`: frozen v1.0 windows, ordering, baseline, applicability, peak and active-position threshold.
2. `data/drip_morpho_markets.csv` and `data/drip_morpho_eligibility_bridge.csv`: fixed population and epoch-side eligibility. Do not directly join the multi-row bridge to market-day.
3. `data/morpho_phase7_boundary_manifest.json`, `data/morpho_phase7_boundary_map.json` and `data/morpho_phase7_boundary_qa.json`: exact 227 timestamp identities, predecessor/chosen proof and known UTC-day brackets.
4. `data/tmp/morpho_market_day_full_v1.sqlite`: immutable production database; verify the exact authoritative hash below.

   Authoritative production SHA-256: `80aca74cc5e43db03fd93c69d7ad448ac9afdec5f9566a6b833ec11f7e5c9543`. Verify this exact value before opening the database `mode=ro&immutable=1`.

5. `data/morpho_market_day_full_qa.json`, source `data/raw/morpho_full_window/manifest.json` and immutable shards: original accounting/source evidence if a production value needs tracing.
6. Official-code references in `docs/MORPHO_ACCOUNTING_MODEL.md`: position owners, loan supply vs collateral, virtual assets/shares, round-up/down conversions, interest, fee shares, liquidations and bad debt.

## Required independent recalculation

- Generate baseline and campaign dates from the frozen timestamps yourself, not from labels in the output CSV. Confirm 56 baseline closes, 169 campaign snapshots and all three post points.
- At each timestamp select the last market state strictly before the chosen boundary block in canonical `(block_number, transaction_index, log_index)` order. Do not use midnight closes.
- Aggregate `totalBorrowAssets` separately for the two exact loan-token addresses, then calculate `B`, `E`, `Q`, `P30/P90/P180`, absolute deltas and both ratios. Do not average market ratios or sum asynchronous market peaks.
- Rebuild borrower shares from all Borrow, Repay and Liquidate position-owner events from the proven anchors. Apply exact checkpoint conversions and the per-position one-token threshold, then count distinct wallets across markets.
- Recompute market applicability counts, representative archetype ratios, concentration shares and incentive/post flow equations. Confirm interest is separate from new borrowing.
- Only then compare your results with `data/morpho_phase7_*` reviewed CSVs. The same-author alternate path `scripts/review_phase7_headlines.py` is available for inspection, but using it alone does not constitute an independent recomputation.

## Questions to answer

1. Are all headline levels, denominators, ratios and units exactly reproducible? Identify the first divergent key if not.
2. Do inactive/matured markets remain in the fixed population, and is any unknown/non-zero anchor being hidden?
3. Does raw source reconciliation support the production layer, and are rounding/rare-branch limitations stated honestly?
4. Could chart connectors between sparse post checkpoints imply an observed daily trajectory? Is the neighboring text sufficient?
5. Are full P180 balances consistently distinguished from baseline-relative uplift and from causal DRIP attribution?
6. Are the recommendation, confidence labels and alternative explanations proportionate to the observational design?
7. Can a pseudonymous release be reproduced without disclosing local identity paths, secrets, raw caches or private infrastructure?

## Review output and stop rule

Return `PASS`, `PASS_WITH_CAVEATS` or `BLOCKED`, with your environment, code/query path, input hashes, recomputed table and exact discrepancies. Separate numerical/methodological blockers from packaging/documentation issues. Do not edit frozen artifacts, try another market population, run new RPC/GBA/extraction, or publish. Any numerical/methodological concern blocks release until explicitly resolved and versioned.

Source access, pseudonym, license, privacy-safe packaging and publication remain separate gates. The revised candidate has not been independently approved. New-DB raw reconstruction, public bundle acquisition and final browser rendering must not be relabeled PASS from historical results.
