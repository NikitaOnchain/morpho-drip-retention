-- SQLite 3 production materialization for the accepted 45-market Phase 6 build.
-- Executed after the exact replay module in sql/10_market_day_prototype.sql by
-- scripts/build_morpho_market_day_full.py.  The reusable module name is
-- historical; it is parameterized by market_dim and therefore replays all 45
-- accepted markets here, not the three-market prototype population.
--
-- Business question
-- -----------------
-- Can immutable Morpho logs be represented at exactly one row per accepted
-- market_id x half-open UTC bucket over
-- [2025-07-09T13:00:00Z, 2026-08-18T00:00:00Z), while retaining exact market
-- totals, aggregate collateral and raw event flows?
--
-- Ordering and arithmetic
-- -----------------------
-- The upstream replay orders every event by
-- (block_number, transaction_index, log_index).  Protocol amounts remain
-- unsigned decimal TEXT and are evaluated with exact Python-bigint SQLite UDFs.
-- Supply/withdraw/borrow/repay rounding, AccrueInterest feeShares, liquidation
-- and bad debt use the accepted Phase 3 accounting contract.  No corrective
-- clamp is applied; only the protocol-specified repay borrow-assets zero floor
-- exists in the replay module.
--
-- Eligibility join
-- ----------------
-- eligibility_bridge has grain market_id x epoch x side and MUST NOT be joined
-- directly to market_day.  It is first rolled up to one row per market.  Shared
-- ARB pools are deliberately absent from market-level amount columns, and the
-- 505K direct-vault campaigns have no bridge rows.  Only exact dedicated-market
-- allocations are summed below.

DROP TABLE IF EXISTS eligibility_market_rollup;

CREATE TABLE eligibility_market_rollup AS
SELECT
  market_id,
  COUNT(*) AS eligibility_bridge_rows,
  COUNT(DISTINCT epoch) AS eligible_epoch_count,
  SUM(side = 'supply') AS supply_epoch_side_rows,
  SUM(side = 'borrow') AS borrow_epoch_side_rows,
  MAX(shared_pool_eligible) AS has_shared_pool_eligibility,
  MAX(dedicated_market_eligible) AS has_dedicated_market_eligibility,
  u_sum(CASE
    WHEN dedicated_market_eligible = 1
      THEN dedicated_market_allocation_arb
    ELSE NULL
  END) AS dedicated_market_allocation_arb
FROM eligibility_bridge
GROUP BY market_id;

CREATE UNIQUE INDEX eligibility_market_rollup_key_uq
  ON eligibility_market_rollup (market_id);

DROP TABLE IF EXISTS market_day_full;

CREATE TABLE market_day_full AS
SELECT
  d.*,
  e.eligibility_bridge_rows,
  e.eligible_epoch_count,
  e.supply_epoch_side_rows,
  e.borrow_epoch_side_rows,
  e.has_shared_pool_eligibility,
  e.has_dedicated_market_eligibility,
  e.dedicated_market_allocation_arb
FROM market_day AS d
JOIN eligibility_market_rollup AS e
  ON e.market_id = d.market_id
ORDER BY d.market_id, d.day_ordinal;

CREATE UNIQUE INDEX market_day_full_key_uq
  ON market_day_full (market_id, day_utc);

