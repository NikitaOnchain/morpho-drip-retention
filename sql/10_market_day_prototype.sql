-- SQLite 3 executable SQL; run by scripts/build_morpho_market_day_prototype.py.
--
-- Business question
-- -----------------
-- Can the accepted Morpho event-replay model be scaled from one position to
-- exactly one row per frozen market and UTC day, with continuous market totals,
-- aggregate collateral and auditable event flows for the complete Phase 2
-- interval [2025-07-09 13:00:00Z, 2026-08-18 00:00:00Z)?
--
-- Input grain
-- -----------
-- source_event: one immutable Morpho log, unique on
--   (block_number, transaction_hash, log_index).
-- day_boundary: one half-open UTC bucket.  The first bucket is the partial UTC
--   day [2025-07-09 13:00:00Z, 2025-07-10 00:00:00Z); all later buckets are
--   midnight-to-midnight UTC days.
-- rpc_checkpoint: one validated market(bytes32) response at end of block.
--
-- Output grain
-- ------------
-- market_day: exactly one row per market_id x day_utc (3 x 405 = 1,215).
-- Days before the first scoped event are retained as
-- status='inactive_pre_first_scoped_event' with zero state and zero flows.
-- The anchor at end of block 355887375 is independently required to be an
-- uninitialized all-zero market before aggregate collateral is seeded at zero.
--
-- Ordering and arithmetic
-- -----------------------
-- Events are sequenced strictly by
--   (block_number, transaction_index, log_index).
-- SQLite INTEGER is not used for protocol amounts.  Decimal TEXT amounts are
-- evaluated by exact Python bigint UDFs registered by the runner:
--   uadd, usub, usub_floor, u_sum, event_rounding_status.
-- Repay uses zero-floor subtraction for totalBorrowAssets.  Liquidate first
-- zero-floor subtracts repaidAssets, then removes emitted badDebtAssets and
-- badDebtShares; bad debt also reduces totalSupplyAssets.  AccrueInterest adds
-- emitted interest to both asset totals and emitted feeShares to supply shares.
-- Aggregate collateral is a direct asset balance: SupplyCollateral adds,
-- WithdrawCollateral and Liquidate.seizedAssets subtract.
--
-- Rounding
-- --------
-- VIRTUAL_SHARES=1e6 and VIRTUAL_ASSETS=1.  For each applicable raw event the
-- registered rounding check accepts exactly one of the protocol-permitted
-- assets-input or shares-input conversions described in Phase 3.  No clamp is
-- used except Morpho's specified zero-floor borrow-asset subtraction.

DROP TABLE IF EXISTS market_event_state;

CREATE TABLE market_event_state AS
WITH RECURSIVE replay (
  market_id,
  event_sequence,
  block_number,
  transaction_index,
  log_index,
  transaction_hash,
  event_family,
  day_utc,
  total_supply_assets,
  total_supply_shares,
  total_borrow_assets,
  total_borrow_shares,
  total_collateral_assets,
  rounding_status
) AS (
  SELECT
    m.market_id,
    0,
    c.block_number,
    -1,
    -1,
    '',
    'ANCHOR',
    '',
    c.total_supply_assets,
    c.total_supply_shares,
    c.total_borrow_assets,
    c.total_borrow_shares,
    '0',
    'not_applicable'
  FROM market_dim AS m
  JOIN rpc_checkpoint AS c
    ON c.market_id = m.market_id
   AND c.checkpoint_name = 'anchor'

  UNION ALL

  SELECT
    r.market_id,
    e.event_sequence,
    e.block_number,
    e.transaction_index,
    e.log_index,
    e.transaction_hash,
    e.event_family,
    e.day_utc,
    CASE e.event_family
      WHEN 'Supply' THEN uadd(r.total_supply_assets, e.assets)
      WHEN 'Withdraw' THEN usub(r.total_supply_assets, e.assets)
      WHEN 'AccrueInterest' THEN uadd(r.total_supply_assets, e.interest)
      WHEN 'Liquidate' THEN usub(r.total_supply_assets, e.bad_debt_assets)
      ELSE r.total_supply_assets
    END,
    CASE e.event_family
      WHEN 'Supply' THEN uadd(r.total_supply_shares, e.shares)
      WHEN 'Withdraw' THEN usub(r.total_supply_shares, e.shares)
      WHEN 'AccrueInterest' THEN uadd(r.total_supply_shares, e.fee_shares)
      ELSE r.total_supply_shares
    END,
    CASE e.event_family
      WHEN 'Borrow' THEN uadd(r.total_borrow_assets, e.assets)
      WHEN 'Repay' THEN usub_floor(r.total_borrow_assets, e.assets)
      WHEN 'AccrueInterest' THEN uadd(r.total_borrow_assets, e.interest)
      WHEN 'Liquidate' THEN
        usub(usub_floor(r.total_borrow_assets, e.repaid_assets), e.bad_debt_assets)
      ELSE r.total_borrow_assets
    END,
    CASE e.event_family
      WHEN 'Borrow' THEN uadd(r.total_borrow_shares, e.shares)
      WHEN 'Repay' THEN usub(r.total_borrow_shares, e.shares)
      WHEN 'Liquidate' THEN
        usub(usub(r.total_borrow_shares, e.repaid_shares), e.bad_debt_shares)
      ELSE r.total_borrow_shares
    END,
    CASE e.event_family
      WHEN 'SupplyCollateral' THEN uadd(r.total_collateral_assets, e.assets)
      WHEN 'WithdrawCollateral' THEN usub(r.total_collateral_assets, e.assets)
      WHEN 'Liquidate' THEN usub(r.total_collateral_assets, e.seized_assets)
      ELSE r.total_collateral_assets
    END,
    event_rounding_status(
      e.event_family,
      e.assets,
      e.shares,
      e.repaid_assets,
      e.repaid_shares,
      r.total_supply_assets,
      r.total_supply_shares,
      r.total_borrow_assets,
      r.total_borrow_shares
    )
  FROM replay AS r
  JOIN source_event AS e
    ON e.market_id = r.market_id
   AND e.event_sequence = r.event_sequence + 1
)
SELECT * FROM replay;

CREATE UNIQUE INDEX market_event_state_sequence_uq
  ON market_event_state (market_id, event_sequence);
CREATE INDEX market_event_state_block_ix
  ON market_event_state (market_id, block_number, event_sequence);

DROP TABLE IF EXISTS daily_flow;

CREATE TABLE daily_flow AS
SELECT
  market_id,
  day_utc,
  COUNT(*) AS total_event_count,
  SUM(event_family = 'Supply') AS supply_event_count,
  SUM(event_family = 'Withdraw') AS withdraw_event_count,
  SUM(event_family = 'Borrow') AS borrow_event_count,
  SUM(event_family = 'Repay') AS repay_event_count,
  SUM(event_family = 'SupplyCollateral') AS supply_collateral_event_count,
  SUM(event_family = 'WithdrawCollateral') AS withdraw_collateral_event_count,
  SUM(event_family = 'Liquidate') AS liquidate_event_count,
  SUM(event_family = 'AccrueInterest') AS accrue_interest_event_count,
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
  u_sum(CASE WHEN event_family = 'Liquidate' THEN bad_debt_shares END) AS liquidation_bad_debt_shares,
  MIN(block_number) AS first_event_block,
  MAX(block_number) AS last_event_block
FROM source_event
GROUP BY market_id, day_utc;

CREATE UNIQUE INDEX daily_flow_key_uq ON daily_flow (market_id, day_utc);

DROP TABLE IF EXISTS market_day_sequence;

CREATE TABLE market_day_sequence AS
SELECT
  m.archetype,
  m.market_id,
  d.day_ordinal,
  d.day_utc,
  d.day_start_utc,
  d.day_end_exclusive_utc,
  d.start_block,
  d.end_block_exclusive,
  COALESCE((
    SELECT MAX(e.event_sequence)
    FROM source_event AS e
    WHERE e.market_id = m.market_id
      AND e.block_number < d.start_block
  ), 0) AS opening_event_sequence,
  COALESCE((
    SELECT MAX(e.event_sequence)
    FROM source_event AS e
    WHERE e.market_id = m.market_id
      AND e.block_number < d.end_block_exclusive
  ), 0) AS closing_event_sequence
FROM market_dim AS m
CROSS JOIN day_boundary AS d;

CREATE UNIQUE INDEX market_day_sequence_key_uq
  ON market_day_sequence (market_id, day_utc);

DROP TABLE IF EXISTS market_day;

CREATE TABLE market_day AS
SELECT
  q.archetype,
  q.market_id,
  q.day_ordinal,
  q.day_utc,
  q.day_start_utc,
  q.day_end_exclusive_utc,
  q.start_block AS day_start_block,
  q.end_block_exclusive AS day_end_block_exclusive,
  CASE
    WHEN q.closing_event_sequence = 0 THEN 'inactive_pre_first_scoped_event'
    ELSE 'active'
  END AS status,
  q.opening_event_sequence,
  q.closing_event_sequence,
  o.total_supply_assets AS opening_total_supply_assets,
  o.total_supply_shares AS opening_total_supply_shares,
  o.total_borrow_assets AS opening_total_borrow_assets,
  o.total_borrow_shares AS opening_total_borrow_shares,
  o.total_collateral_assets AS opening_total_collateral_assets,
  c.total_supply_assets AS closing_total_supply_assets,
  c.total_supply_shares AS closing_total_supply_shares,
  c.total_borrow_assets AS closing_total_borrow_assets,
  c.total_borrow_shares AS closing_total_borrow_shares,
  c.total_collateral_assets AS closing_total_collateral_assets,
  COALESCE(f.total_event_count, 0) AS total_event_count,
  COALESCE(f.supply_event_count, 0) AS supply_event_count,
  COALESCE(f.withdraw_event_count, 0) AS withdraw_event_count,
  COALESCE(f.borrow_event_count, 0) AS borrow_event_count,
  COALESCE(f.repay_event_count, 0) AS repay_event_count,
  COALESCE(f.supply_collateral_event_count, 0) AS supply_collateral_event_count,
  COALESCE(f.withdraw_collateral_event_count, 0) AS withdraw_collateral_event_count,
  COALESCE(f.liquidate_event_count, 0) AS liquidate_event_count,
  COALESCE(f.accrue_interest_event_count, 0) AS accrue_interest_event_count,
  COALESCE(f.supply_assets_in, '0') AS supply_assets_in,
  COALESCE(f.supply_shares_minted, '0') AS supply_shares_minted,
  COALESCE(f.withdraw_assets_out, '0') AS withdraw_assets_out,
  COALESCE(f.withdraw_shares_burned, '0') AS withdraw_shares_burned,
  COALESCE(f.borrow_assets_out, '0') AS borrow_assets_out,
  COALESCE(f.borrow_shares_minted, '0') AS borrow_shares_minted,
  COALESCE(f.repay_assets_in, '0') AS repay_assets_in,
  COALESCE(f.repay_shares_burned, '0') AS repay_shares_burned,
  COALESCE(f.collateral_assets_in, '0') AS collateral_assets_in,
  COALESCE(f.collateral_assets_withdrawn, '0') AS collateral_assets_withdrawn,
  COALESCE(f.accrued_interest_assets, '0') AS accrued_interest_assets,
  COALESCE(f.accrued_fee_shares, '0') AS accrued_fee_shares,
  COALESCE(f.liquidation_repaid_assets, '0') AS liquidation_repaid_assets,
  COALESCE(f.liquidation_repaid_shares, '0') AS liquidation_repaid_shares,
  COALESCE(f.liquidation_seized_collateral_assets, '0') AS liquidation_seized_collateral_assets,
  COALESCE(f.liquidation_bad_debt_assets, '0') AS liquidation_bad_debt_assets,
  COALESCE(f.liquidation_bad_debt_shares, '0') AS liquidation_bad_debt_shares,
  f.first_event_block,
  f.last_event_block
FROM market_day_sequence AS q
JOIN market_event_state AS o
  ON o.market_id = q.market_id
 AND o.event_sequence = q.opening_event_sequence
JOIN market_event_state AS c
  ON c.market_id = q.market_id
 AND c.event_sequence = q.closing_event_sequence
LEFT JOIN daily_flow AS f
  ON f.market_id = q.market_id
 AND f.day_utc = q.day_utc
ORDER BY q.market_id, q.day_ordinal;

CREATE UNIQUE INDEX market_day_key_uq ON market_day (market_id, day_utc);

