-- Population-level Phase 6 QA, executed after the reusable blocking checks in
-- sql/90_qa_market_day_prototype.sql.  All rows written here are blocking.
-- phase4_reference_market_day is loaded through a separate immutable/read-only
-- SQLite connection by the runner, so the accepted prototype cannot be mutated
-- by unqualified SQLite DDL.

DROP TABLE IF EXISTS phase6_qa_result;

CREATE TABLE phase6_qa_result (
  check_name TEXT PRIMARY KEY,
  observed TEXT NOT NULL,
  expected TEXT NOT NULL,
  defect_count INTEGER NOT NULL,
  status TEXT NOT NULL
);

INSERT INTO phase6_qa_result
SELECT 'coverage_45_markets', CAST(COUNT(DISTINCT market_id) AS TEXT), '45',
       ABS(COUNT(DISTINCT market_id) - 45),
       CASE WHEN COUNT(DISTINCT market_id) = 45 THEN 'PASS' ELSE 'FAIL' END
FROM market_day_full;

INSERT INTO phase6_qa_result
SELECT 'expected_18225_market_days', CAST(COUNT(*) AS TEXT), '18225',
       ABS(COUNT(*) - 18225),
       CASE WHEN COUNT(*) = 18225 THEN 'PASS' ELSE 'FAIL' END
FROM market_day_full;

INSERT INTO phase6_qa_result
SELECT 'each_market_has_405_days',
       CAST(MIN(n) AS TEXT) || '..' || CAST(MAX(n) AS TEXT), '405..405',
       SUM(n <> 405), CASE WHEN SUM(n <> 405) = 0 THEN 'PASS' ELSE 'FAIL' END
FROM (SELECT market_id, COUNT(*) AS n FROM market_day_full GROUP BY market_id);

INSERT INTO phase6_qa_result
SELECT 'unique_market_day_full_key', CAST(COUNT(*) AS TEXT), '0', COUNT(*),
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END
FROM (
  SELECT market_id, day_utc FROM market_day_full
  GROUP BY market_id, day_utc HAVING COUNT(*) > 1
);

INSERT INTO phase6_qa_result
SELECT 'eligibility_bridge_unique_key', CAST(COUNT(*) AS TEXT), '0', COUNT(*),
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END
FROM (
  SELECT market_id, epoch, side FROM eligibility_bridge
  GROUP BY market_id, epoch, side HAVING COUNT(*) > 1
);

INSERT INTO phase6_qa_result
SELECT 'eligibility_bridge_45_markets', CAST(COUNT(DISTINCT market_id) AS TEXT), '45',
       ABS(COUNT(DISTINCT market_id) - 45),
       CASE WHEN COUNT(DISTINCT market_id) = 45 THEN 'PASS' ELSE 'FAIL' END
FROM eligibility_bridge;

INSERT INTO phase6_qa_result
SELECT 'eligibility_bridge_orphan_markets', CAST(COUNT(*) AS TEXT), '0', COUNT(*),
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END
FROM eligibility_bridge AS b
LEFT JOIN market_dim AS m ON m.market_id = b.market_id
WHERE m.market_id IS NULL;

INSERT INTO phase6_qa_result
SELECT 'eligibility_rollup_one_row_per_market', CAST(COUNT(*) AS TEXT), '45',
       ABS(COUNT(*) - 45), CASE WHEN COUNT(*) = 45 THEN 'PASS' ELSE 'FAIL' END
FROM eligibility_market_rollup;

INSERT INTO phase6_qa_result
SELECT 'eligibility_join_preserves_grain',
       CAST((SELECT COUNT(*) FROM market_day_full) AS TEXT),
       CAST((SELECT COUNT(*) FROM market_day) AS TEXT),
       ABS((SELECT COUNT(*) FROM market_day_full) - (SELECT COUNT(*) FROM market_day)),
       CASE WHEN (SELECT COUNT(*) FROM market_day_full) = (SELECT COUNT(*) FROM market_day)
            THEN 'PASS' ELSE 'FAIL' END;

INSERT INTO phase6_qa_result
SELECT 'shared_budget_not_allocated_to_markets', CAST(COUNT(*) AS TEXT), '0', COUNT(*),
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END
FROM pragma_table_info('eligibility_bridge')
WHERE lower(name) IN ('shared_budget_arb', 'shared_market_allocation_arb');

INSERT INTO phase6_qa_result
SELECT 'direct_vault_not_attributed_to_markets', CAST(COUNT(*) AS TEXT), '0', COUNT(*),
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END
FROM eligibility_bridge
WHERE lower(eligibility_mode) LIKE '%vault%';

INSERT INTO phase6_qa_result
SELECT 'prototype_three_markets_exact_match', CAST(COUNT(*) AS TEXT), '0', COUNT(*),
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END
FROM (
  SELECT * FROM main.market_day
  WHERE market_id IN (
    '0xd09404e9512e1341321c8ae3bd663fab7087582142ac61486635a6c072c2af12',
    '0xf86f3edd6f16cd8211f4d206866dc4ecd41be6211063ac11f8508e1b7112ef40',
    '0x571cb3ac535d61d92026c071ef1df4794d0bbbe1755f916ff640746f81b52af4'
  )
  EXCEPT SELECT * FROM phase4_reference_market_day
  UNION ALL
  SELECT * FROM phase4_reference_market_day
  EXCEPT SELECT * FROM main.market_day
  WHERE market_id IN (
    '0xd09404e9512e1341321c8ae3bd663fab7087582142ac61486635a6c072c2af12',
    '0xf86f3edd6f16cd8211f4d206866dc4ecd41be6211063ac11f8508e1b7112ef40',
    '0x571cb3ac535d61d92026c071ef1df4794d0bbbe1755f916ff640746f81b52af4'
  )
);

INSERT INTO phase6_qa_result
SELECT 'prototype_source_qa_is_accepted', CAST(COUNT(*) AS TEXT), '0', COUNT(*),
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END
FROM phase4_reference_status
WHERE blocking_failure_count <> 0;

INSERT INTO phase6_qa_result
SELECT 'full_required_fields_not_null', CAST(COUNT(*) AS TEXT), '0', COUNT(*),
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END
FROM market_day_full
WHERE market_id IS NULL OR day_utc IS NULL OR status IS NULL
   OR opening_total_supply_assets IS NULL OR opening_total_supply_shares IS NULL
   OR opening_total_borrow_assets IS NULL OR opening_total_borrow_shares IS NULL
   OR opening_total_collateral_assets IS NULL
   OR closing_total_supply_assets IS NULL OR closing_total_supply_shares IS NULL
   OR closing_total_borrow_assets IS NULL OR closing_total_borrow_shares IS NULL
   OR closing_total_collateral_assets IS NULL OR total_event_count IS NULL
   OR eligibility_bridge_rows IS NULL OR eligible_epoch_count IS NULL;
