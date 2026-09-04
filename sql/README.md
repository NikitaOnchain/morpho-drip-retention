# SQL workspace

Store reproducible SQL here. Phase 2 uses BigQuery Standard SQL; the bounded
Phase 4 daily-state prototype deliberately uses local SQLite 3 and records its
registered exact-bigint functions beside the query.

Suggested naming:

```text
00_feasibility_*.sql
10_market_events_*.sql
20_market_day_state_*.sql
30_wallet_positions_*.sql
40_metrics_*.sql
90_qa_*.sql
```

Every query should begin with a comment block containing:

- business question;
- output grain and expected unique key;
- source tables and access date;
- exact time boundaries;
- metric definition;
- expected scan or dry-run result;
- material limitations.

Do not overwrite a validated query to change its meaning. Create a new numbered version and record the decision in `../DECISIONS.md`.

## Phase 2 queries

- `00_feasibility_morpho_event_coverage.sql`: one-day GBA event-family profile and deterministic ten-event sample.
- `01_rpc_feasibility_gba_reference.sql`: raw-log reference for the one-day adaptive RPC reconciliation. Dry-run upper bound 2.96 GiB; executed result 2,087 rows.
- `02_rpc_stratified_gba_reference.sql`: parameterized one-day raw-log reference used by the approved baseline and campaign-boundary pilot. The runner substitutes exact half-open UTC timestamps.

## Phase 4 executable prototype

- `10_market_day_prototype.sql`: SQLite recursive replay from the staged immutable Phase 2 events to one row per frozen `market_id × UTC day`. It is executed unchanged by `scripts/build_morpho_market_day_prototype.py` with exact bigint UDFs.
- `90_qa_market_day_prototype.sql`: SQLite QA for expected rows, keys, calendar continuity, opening/closing continuity, raw event counts and flows, rounding, unsigned states, inactive rows, rare-branch incidence and 12 archive-RPC checkpoints.

The technical run is PASS: 275,797 events, 1,215 output rows, zero blocking defects and 12/12 RPC matches. See `../docs/MARKET_DAY_PROTOTYPE.md`.
