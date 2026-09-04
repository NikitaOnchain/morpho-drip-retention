# Data-quality protocol

## Before the first full query

- Confirm chain, contract, event signature and address casing.
- Build the canonical eligible-market table from primary DRIP sources.
- Record exact UTC boundaries and whether each interval is half-open or closed.
- Estimate scan size with a bounded dry run.

## Grain and uniqueness

For raw events, test the expected key, normally:

```text
block_number + transaction_hash + log_index
```

For derived daily state, expected key:

```text
market_id + UTC date
```

Do not assume decoded events are unique. Compare raw log counts, decoded row counts and distinct expected keys.

## Required checks

1. Row count by event type and day.
2. Duplicate expected keys.
3. NULL in market ID, wallet, asset amount or event-order fields.
4. Lowercase address normalization.
5. Reconciliation of signed flows to daily state.
6. No impossible negative balances after ordering and interest accounting.
7. Native-unit decimals verified per asset.
8. Ten deterministic event samples checked against an independent source.
9. One wallet-market position reconstructed manually across supply/borrow/repay/withdraw events.
10. Aggregate comparison with an official or protocol dashboard, with differences explained rather than forced to match.

## Attribution checks

- Separate market participation from verified reward receipt.
- Separate event activity from positive-position retention.
- Report market migrations, liquidations and parameter changes that can move metrics independently of DRIP.
- Never infer causality from a pre/post chart alone. Use language such as `consistent with`, `associated with`, or `cannot rule out` when appropriate.

## Evidence to save

- SQL query and dry-run estimate
- schema snapshot or table identifiers
- QA result table
- ten-event sample with source links or RPC evidence
- wallet-position reconstruction
- source access dates
- known limitations and unresolved discrepancies
