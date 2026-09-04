-- SQLite 3 executable QA for sql/10_market_day_prototype.sql.
-- Blocking checks must all return status='PASS'.  Rare-branch incidence is an
-- informational coverage result: zero non-zero feeShares or bad debt is GAP,
-- not a fabricated PASS and not a reason to replace a frozen market.

DROP TABLE IF EXISTS checkpoint_reconciliation;

CREATE TABLE checkpoint_reconciliation AS
WITH checkpoint_sequence AS (
  SELECT
    c.*,
    COALESCE((
      SELECT MAX(e.event_sequence)
      FROM source_event AS e
      WHERE e.market_id = c.market_id
        AND e.block_number <= c.block_number
    ), 0) AS reconstructed_event_sequence
  FROM rpc_checkpoint AS c
), comparison AS (
  SELECT
    c.market_id,
    c.checkpoint_name,
    c.block_number,
    c.reconstructed_event_sequence,
    s.total_supply_assets AS reconstructed_total_supply_assets,
    c.total_supply_assets AS rpc_total_supply_assets,
    s.total_supply_shares AS reconstructed_total_supply_shares,
    c.total_supply_shares AS rpc_total_supply_shares,
    s.total_borrow_assets AS reconstructed_total_borrow_assets,
    c.total_borrow_assets AS rpc_total_borrow_assets,
    s.total_borrow_shares AS reconstructed_total_borrow_shares,
    c.total_borrow_shares AS rpc_total_borrow_shares,
    c.last_update AS rpc_last_update,
    c.fee AS rpc_fee
  FROM checkpoint_sequence AS c
  JOIN market_event_state AS s
    ON s.market_id = c.market_id
   AND s.event_sequence = c.reconstructed_event_sequence
)
SELECT
  *,
  CASE WHEN
    reconstructed_total_supply_assets = rpc_total_supply_assets
    AND reconstructed_total_supply_shares = rpc_total_supply_shares
    AND reconstructed_total_borrow_assets = rpc_total_borrow_assets
    AND reconstructed_total_borrow_shares = rpc_total_borrow_shares
  THEN 1 ELSE 0 END AS totals_match
FROM comparison;

CREATE UNIQUE INDEX checkpoint_reconciliation_key_uq
  ON checkpoint_reconciliation (market_id, checkpoint_name);

DROP TABLE IF EXISTS event_family_reconciliation;

CREATE TABLE event_family_reconciliation AS
WITH families(event_family) AS (
  VALUES
    ('Supply'), ('Withdraw'), ('Borrow'), ('Repay'),
    ('SupplyCollateral'), ('WithdrawCollateral'),
    ('Liquidate'), ('AccrueInterest')
), raw_counts AS (
  SELECT market_id, event_family, COUNT(*) AS event_count
  FROM source_event
  GROUP BY market_id, event_family
), daily_counts AS (
  SELECT market_id, 'Supply' AS event_family, SUM(supply_event_count) AS event_count FROM market_day GROUP BY market_id
  UNION ALL SELECT market_id, 'Withdraw', SUM(withdraw_event_count) FROM market_day GROUP BY market_id
  UNION ALL SELECT market_id, 'Borrow', SUM(borrow_event_count) FROM market_day GROUP BY market_id
  UNION ALL SELECT market_id, 'Repay', SUM(repay_event_count) FROM market_day GROUP BY market_id
  UNION ALL SELECT market_id, 'SupplyCollateral', SUM(supply_collateral_event_count) FROM market_day GROUP BY market_id
  UNION ALL SELECT market_id, 'WithdrawCollateral', SUM(withdraw_collateral_event_count) FROM market_day GROUP BY market_id
  UNION ALL SELECT market_id, 'Liquidate', SUM(liquidate_event_count) FROM market_day GROUP BY market_id
  UNION ALL SELECT market_id, 'AccrueInterest', SUM(accrue_interest_event_count) FROM market_day GROUP BY market_id
)
SELECT
  m.market_id,
  f.event_family,
  COALESCE(r.event_count, 0) AS raw_event_count,
  COALESCE(d.event_count, 0) AS daily_event_count,
  CASE WHEN COALESCE(r.event_count, 0) = COALESCE(d.event_count, 0) THEN 1 ELSE 0 END AS counts_match
FROM market_dim AS m
CROSS JOIN families AS f
LEFT JOIN raw_counts AS r
  ON r.market_id = m.market_id AND r.event_family = f.event_family
LEFT JOIN daily_counts AS d
  ON d.market_id = m.market_id AND d.event_family = f.event_family;

DROP TABLE IF EXISTS event_flow_reconciliation;

CREATE TABLE event_flow_reconciliation AS
WITH raw AS (
  SELECT
    market_id,
    u_sum(CASE WHEN event_family = 'Supply' THEN assets END) AS supply_assets_in,
    u_sum(CASE WHEN event_family = 'Supply' THEN shares END) AS supply_shares_minted,
    u_sum(CASE WHEN event_family = 'Withdraw' THEN assets END) AS withdraw_assets_out,
    u_sum(CASE WHEN event_family = 'Withdraw' THEN shares END) AS withdraw_shares_burned,
    u_sum(CASE WHEN event_family = 'Borrow' THEN assets END) AS borrow_assets_out,
    u_sum(CASE WHEN event_family = 'Borrow' THEN shares END) AS borrow_shares_minted,
    u_sum(CASE WHEN event_family = 'Repay' THEN assets END) AS repay_assets_in,
    u_sum(CASE WHEN event_family = 'Repay' THEN shares END) AS repay_shares_burned,
    u_sum(CASE WHEN event_family = 'SupplyCollateral' THEN assets END) AS collateral_assets_in,
    u_sum(CASE WHEN event_family = 'WithdrawCollateral' THEN assets END) AS collateral_assets_withdrawn,
    u_sum(CASE WHEN event_family = 'AccrueInterest' THEN interest END) AS accrued_interest_assets,
    u_sum(CASE WHEN event_family = 'AccrueInterest' THEN fee_shares END) AS accrued_fee_shares,
    u_sum(CASE WHEN event_family = 'Liquidate' THEN repaid_assets END) AS liquidation_repaid_assets,
    u_sum(CASE WHEN event_family = 'Liquidate' THEN repaid_shares END) AS liquidation_repaid_shares,
    u_sum(CASE WHEN event_family = 'Liquidate' THEN seized_assets END) AS liquidation_seized_collateral_assets,
    u_sum(CASE WHEN event_family = 'Liquidate' THEN bad_debt_assets END) AS liquidation_bad_debt_assets,
    u_sum(CASE WHEN event_family = 'Liquidate' THEN bad_debt_shares END) AS liquidation_bad_debt_shares
  FROM source_event
  GROUP BY market_id
), daily AS (
  SELECT
    market_id,
    u_sum(supply_assets_in) AS supply_assets_in,
    u_sum(supply_shares_minted) AS supply_shares_minted,
    u_sum(withdraw_assets_out) AS withdraw_assets_out,
    u_sum(withdraw_shares_burned) AS withdraw_shares_burned,
    u_sum(borrow_assets_out) AS borrow_assets_out,
    u_sum(borrow_shares_minted) AS borrow_shares_minted,
    u_sum(repay_assets_in) AS repay_assets_in,
    u_sum(repay_shares_burned) AS repay_shares_burned,
    u_sum(collateral_assets_in) AS collateral_assets_in,
    u_sum(collateral_assets_withdrawn) AS collateral_assets_withdrawn,
    u_sum(accrued_interest_assets) AS accrued_interest_assets,
    u_sum(accrued_fee_shares) AS accrued_fee_shares,
    u_sum(liquidation_repaid_assets) AS liquidation_repaid_assets,
    u_sum(liquidation_repaid_shares) AS liquidation_repaid_shares,
    u_sum(liquidation_seized_collateral_assets) AS liquidation_seized_collateral_assets,
    u_sum(liquidation_bad_debt_assets) AS liquidation_bad_debt_assets,
    u_sum(liquidation_bad_debt_shares) AS liquidation_bad_debt_shares
  FROM market_day
  GROUP BY market_id
), pairs AS (
  SELECT raw.market_id, 'supply_assets_in' AS measure, raw.supply_assets_in AS raw_value, daily.supply_assets_in AS daily_value FROM raw JOIN daily USING (market_id)
  UNION ALL SELECT raw.market_id, 'supply_shares_minted', raw.supply_shares_minted, daily.supply_shares_minted FROM raw JOIN daily USING (market_id)
  UNION ALL SELECT raw.market_id, 'withdraw_assets_out', raw.withdraw_assets_out, daily.withdraw_assets_out FROM raw JOIN daily USING (market_id)
  UNION ALL SELECT raw.market_id, 'withdraw_shares_burned', raw.withdraw_shares_burned, daily.withdraw_shares_burned FROM raw JOIN daily USING (market_id)
  UNION ALL SELECT raw.market_id, 'borrow_assets_out', raw.borrow_assets_out, daily.borrow_assets_out FROM raw JOIN daily USING (market_id)
  UNION ALL SELECT raw.market_id, 'borrow_shares_minted', raw.borrow_shares_minted, daily.borrow_shares_minted FROM raw JOIN daily USING (market_id)
  UNION ALL SELECT raw.market_id, 'repay_assets_in', raw.repay_assets_in, daily.repay_assets_in FROM raw JOIN daily USING (market_id)
  UNION ALL SELECT raw.market_id, 'repay_shares_burned', raw.repay_shares_burned, daily.repay_shares_burned FROM raw JOIN daily USING (market_id)
  UNION ALL SELECT raw.market_id, 'collateral_assets_in', raw.collateral_assets_in, daily.collateral_assets_in FROM raw JOIN daily USING (market_id)
  UNION ALL SELECT raw.market_id, 'collateral_assets_withdrawn', raw.collateral_assets_withdrawn, daily.collateral_assets_withdrawn FROM raw JOIN daily USING (market_id)
  UNION ALL SELECT raw.market_id, 'accrued_interest_assets', raw.accrued_interest_assets, daily.accrued_interest_assets FROM raw JOIN daily USING (market_id)
  UNION ALL SELECT raw.market_id, 'accrued_fee_shares', raw.accrued_fee_shares, daily.accrued_fee_shares FROM raw JOIN daily USING (market_id)
  UNION ALL SELECT raw.market_id, 'liquidation_repaid_assets', raw.liquidation_repaid_assets, daily.liquidation_repaid_assets FROM raw JOIN daily USING (market_id)
  UNION ALL SELECT raw.market_id, 'liquidation_repaid_shares', raw.liquidation_repaid_shares, daily.liquidation_repaid_shares FROM raw JOIN daily USING (market_id)
  UNION ALL SELECT raw.market_id, 'liquidation_seized_collateral_assets', raw.liquidation_seized_collateral_assets, daily.liquidation_seized_collateral_assets FROM raw JOIN daily USING (market_id)
  UNION ALL SELECT raw.market_id, 'liquidation_bad_debt_assets', raw.liquidation_bad_debt_assets, daily.liquidation_bad_debt_assets FROM raw JOIN daily USING (market_id)
  UNION ALL SELECT raw.market_id, 'liquidation_bad_debt_shares', raw.liquidation_bad_debt_shares, daily.liquidation_bad_debt_shares FROM raw JOIN daily USING (market_id)
)
SELECT
  market_id,
  measure,
  raw_value,
  daily_value,
  CASE WHEN raw_value = daily_value THEN 1 ELSE 0 END AS values_match
FROM pairs;

DROP TABLE IF EXISTS qa_result;

CREATE TABLE qa_result (
  check_name TEXT PRIMARY KEY,
  blocking INTEGER NOT NULL,
  observed TEXT NOT NULL,
  expected TEXT NOT NULL,
  defect_count INTEGER NOT NULL,
  status TEXT NOT NULL
);

INSERT INTO qa_result
SELECT
  'expected_market_day_rows', 1,
  CAST((SELECT COUNT(*) FROM market_day) AS TEXT),
  CAST((SELECT COUNT(*) FROM market_dim) * (SELECT COUNT(*) FROM day_boundary) AS TEXT),
  ABS((SELECT COUNT(*) FROM market_day) - (SELECT COUNT(*) FROM market_dim) * (SELECT COUNT(*) FROM day_boundary)),
  CASE WHEN (SELECT COUNT(*) FROM market_day) =
                 (SELECT COUNT(*) FROM market_dim) * (SELECT COUNT(*) FROM day_boundary)
       THEN 'PASS' ELSE 'FAIL' END;

INSERT INTO qa_result
SELECT
  'per_market_calendar_coverage', 1,
  CAST(MIN(n) AS TEXT) || '..' || CAST(MAX(n) AS TEXT),
  CAST((SELECT COUNT(*) FROM day_boundary) AS TEXT) || '..' || CAST((SELECT COUNT(*) FROM day_boundary) AS TEXT),
  SUM(CASE WHEN n = (SELECT COUNT(*) FROM day_boundary) THEN 0 ELSE 1 END),
  CASE WHEN SUM(CASE WHEN n = (SELECT COUNT(*) FROM day_boundary) THEN 0 ELSE 1 END) = 0
       THEN 'PASS' ELSE 'FAIL' END
FROM (SELECT market_id, COUNT(*) AS n FROM market_day GROUP BY market_id);

INSERT INTO qa_result
SELECT
  'unique_market_day_key', 1,
  CAST(COUNT(*) AS TEXT), '0', COUNT(*),
  CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END
FROM (
  SELECT market_id, day_utc
  FROM market_day
  GROUP BY market_id, day_utc
  HAVING COUNT(*) > 1
);

INSERT INTO qa_result
SELECT
  'continuous_calendar_boundaries', 1,
  CAST(COUNT(*) AS TEXT), '0', COUNT(*),
  CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END
FROM (
  SELECT day_ordinal
  FROM (
    SELECT
      day_ordinal,
      day_start_utc,
      LAG(day_end_exclusive_utc) OVER (ORDER BY day_ordinal) AS previous_end,
      LAG(day_ordinal) OVER (ORDER BY day_ordinal) AS previous_ordinal
    FROM day_boundary
  )
  WHERE previous_ordinal IS NOT NULL
    AND (day_ordinal <> previous_ordinal + 1 OR day_start_utc <> previous_end)
);

INSERT INTO qa_result
SELECT
  'unexplained_required_nulls', 1,
  CAST(COUNT(*) AS TEXT), '0', COUNT(*),
  CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END
FROM market_day
WHERE market_id IS NULL OR day_utc IS NULL OR status IS NULL
   OR opening_total_supply_assets IS NULL OR opening_total_supply_shares IS NULL
   OR opening_total_borrow_assets IS NULL OR opening_total_borrow_shares IS NULL
   OR opening_total_collateral_assets IS NULL
   OR closing_total_supply_assets IS NULL OR closing_total_supply_shares IS NULL
   OR closing_total_borrow_assets IS NULL OR closing_total_borrow_shares IS NULL
   OR closing_total_collateral_assets IS NULL OR total_event_count IS NULL;

INSERT INTO qa_result
SELECT
  'previous_close_equals_next_open', 1,
  CAST(COUNT(*) AS TEXT), '0', COUNT(*),
  CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END
FROM (
  SELECT *
  FROM (
    SELECT
      market_id,
      day_ordinal,
      opening_total_supply_assets,
      opening_total_supply_shares,
      opening_total_borrow_assets,
      opening_total_borrow_shares,
      opening_total_collateral_assets,
      LAG(closing_total_supply_assets) OVER (PARTITION BY market_id ORDER BY day_ordinal) AS p_supply_assets,
      LAG(closing_total_supply_shares) OVER (PARTITION BY market_id ORDER BY day_ordinal) AS p_supply_shares,
      LAG(closing_total_borrow_assets) OVER (PARTITION BY market_id ORDER BY day_ordinal) AS p_borrow_assets,
      LAG(closing_total_borrow_shares) OVER (PARTITION BY market_id ORDER BY day_ordinal) AS p_borrow_shares,
      LAG(closing_total_collateral_assets) OVER (PARTITION BY market_id ORDER BY day_ordinal) AS p_collateral
    FROM market_day
  )
  WHERE day_ordinal > 0
    AND (
      opening_total_supply_assets <> p_supply_assets
      OR opening_total_supply_shares <> p_supply_shares
      OR opening_total_borrow_assets <> p_borrow_assets
      OR opening_total_borrow_shares <> p_borrow_shares
      OR opening_total_collateral_assets <> p_collateral
    )
);

INSERT INTO qa_result
SELECT
  'daily_event_sequence_delta', 1,
  CAST(COUNT(*) AS TEXT), '0', COUNT(*),
  CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END
FROM market_day
WHERE closing_event_sequence - opening_event_sequence <> total_event_count;

INSERT INTO qa_result
SELECT
  'raw_event_counts_reconcile', 1,
  CAST(COUNT(*) AS TEXT), '0', COUNT(*),
  CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END
FROM event_family_reconciliation
WHERE counts_match = 0;

INSERT INTO qa_result
SELECT
  'raw_event_flows_reconcile', 1,
  CAST(COUNT(*) AS TEXT), '0', COUNT(*),
  CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END
FROM event_flow_reconciliation
WHERE values_match = 0;

INSERT INTO qa_result
SELECT
  'raw_event_key_duplicates', 1,
  CAST(COUNT(*) AS TEXT), '0', COUNT(*),
  CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END
FROM (
  SELECT block_number, transaction_hash, log_index
  FROM source_event
  GROUP BY block_number, transaction_hash, log_index
  HAVING COUNT(*) > 1
);

INSERT INTO qa_result
SELECT
  'deterministic_ordering_duplicates', 1,
  CAST(COUNT(*) AS TEXT), '0', COUNT(*),
  CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END
FROM (
  SELECT block_number, transaction_index, log_index
  FROM source_event
  GROUP BY block_number, transaction_index, log_index
  HAVING COUNT(*) > 1
);

INSERT INTO qa_result
SELECT
  'rounding_checks', 1,
  CAST(COUNT(*) AS TEXT), '0', COUNT(*),
  CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END
FROM market_event_state
WHERE rounding_status = 'fail';

INSERT INTO qa_result
SELECT
  'unsigned_state_format_and_nonnegative', 1,
  CAST(COUNT(*) AS TEXT), '0', COUNT(*),
  CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END
FROM market_event_state
WHERE uvalid(total_supply_assets) = 0
   OR uvalid(total_supply_shares) = 0
   OR uvalid(total_borrow_assets) = 0
   OR uvalid(total_borrow_shares) = 0
   OR uvalid(total_collateral_assets) = 0;

INSERT INTO qa_result
SELECT
  'inactive_days_are_zero', 1,
  CAST(COUNT(*) AS TEXT), '0', COUNT(*),
  CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END
FROM market_day
WHERE status = 'inactive_pre_first_scoped_event'
  AND (
    opening_total_supply_assets <> '0' OR opening_total_supply_shares <> '0'
    OR opening_total_borrow_assets <> '0' OR opening_total_borrow_shares <> '0'
    OR opening_total_collateral_assets <> '0'
    OR closing_total_supply_assets <> '0' OR closing_total_supply_shares <> '0'
    OR closing_total_borrow_assets <> '0' OR closing_total_borrow_shares <> '0'
    OR closing_total_collateral_assets <> '0' OR total_event_count <> 0
  );

INSERT INTO qa_result
SELECT
  'rpc_market_checkpoint_reconciliation', 1,
  CAST(COUNT(*) - SUM(totals_match) AS TEXT), '0',
  COUNT(*) - SUM(totals_match),
  CASE WHEN COUNT(*) - SUM(totals_match) = 0 THEN 'PASS' ELSE 'FAIL' END
FROM checkpoint_reconciliation;

INSERT INTO qa_result
SELECT
  'nonzero_fee_shares_incidence', 0,
  CAST(COUNT(*) AS TEXT), '>0 for empirical coverage', 0,
  CASE WHEN COUNT(*) > 0 THEN 'COVERED' ELSE 'GAP' END
FROM source_event
WHERE event_family = 'AccrueInterest' AND u_is_nonzero(fee_shares) = 1;

INSERT INTO qa_result
SELECT
  'nonzero_bad_debt_incidence', 0,
  CAST(COUNT(*) AS TEXT), '>0 for empirical coverage', 0,
  CASE WHEN COUNT(*) > 0 THEN 'COVERED' ELSE 'GAP' END
FROM source_event
WHERE event_family = 'Liquidate'
  AND (u_is_nonzero(bad_debt_assets) = 1 OR u_is_nonzero(bad_debt_shares) = 1);
