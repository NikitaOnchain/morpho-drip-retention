--standardSQL
/*
Business question
-----------------
Can the selected Morpho wallet-market position be reconstructed from a known
end-of-block anchor and every scoped market event in canonical onchain order,
then reconciled to independent end-of-block RPC checkpoints?

Bounded input contract
----------------------
Load `data/morpho_one_position_market_events.csv` into the table referenced in
`source_events`.  This compact extract contains only the selected market and
the half-open block interval [464068387, 482431183); this query does not read
Google Blockchain Analytics or perform a full-window query.

Input grain: one immutable Morpho log, unique on
  (block_number, transaction_hash, log_index).
Replay grain: one post-event state, ordered strictly by
  (block_number, transaction_index, log_index).

Accounting/rounding contract (Morpho Blue v1.0.0)
--------------------------------------------------
VIRTUAL_SHARES = 1e6 and VIRTUAL_ASSETS = 1.

Supply / Repay:
  assets input -> toSharesDown; shares input -> toAssetsUp.
Withdraw / Borrow:
  assets input -> toSharesUp; shares input -> toAssetsDown.
Liquidate:
  repaidAssets = toAssetsUp(repaidShares), then badDebtAssets and
  badDebtShares are removed exactly as emitted.
AccrueInterest:
  interest increases totalBorrowAssets and totalSupplyAssets; feeShares
  increases totalSupplyShares.  The selected wallet is not feeRecipient.

The emitted assets/shares pair does not reveal which side was the non-zero
call input, so the event passes if either permitted branch matches exactly.
Repay and Liquidate use zero-floor subtraction for totalBorrowAssets because
emitted repaidAssets may exceed the pre-event total by one rounding unit.

Position assets at a checkpoint are quotes from current shares and the current
market totals: supply uses toAssetsDown and debt uses toAssetsUp.  They are not
SUM(Borrow assets) - SUM(Repay assets).
*/

DECLARE selected_market STRING DEFAULT
  '0xed06d9e82d7c35ca80d3983194e15462a96202bd875800af18183321f4611868';
DECLARE selected_wallet STRING DEFAULT
  '0xa0c826c8238dae8e11c637c29d0b3374c34f5f80';
DECLARE anchor_block INT64 DEFAULT 464068386;
DECLARE intermediate_block INT64 DEFAULT 464068387;
DECLARE final_block INT64 DEFAULT 482431182;
DECLARE replay_end_exclusive INT64 DEFAULT 482431183;

DECLARE virtual_shares BIGNUMERIC DEFAULT 1000000;
DECLARE virtual_assets BIGNUMERIC DEFAULT 1;

-- Independent archive-RPC state at end of block 464068386.
DECLARE wallet_supply_shares BIGNUMERIC DEFAULT 0;
DECLARE wallet_borrow_shares BIGNUMERIC DEFAULT 0;
DECLARE wallet_collateral_assets BIGNUMERIC DEFAULT 0;
DECLARE total_supply_assets BIGNUMERIC DEFAULT 2306147574352;
DECLARE total_supply_shares BIGNUMERIC DEFAULT 2153552919740529288;
DECLARE total_borrow_assets BIGNUMERIC DEFAULT 1993654167463;
DECLARE total_borrow_shares BIGNUMERIC DEFAULT 1847467653220434764;

DECLARE event_assets BIGNUMERIC;
DECLARE event_shares BIGNUMERIC;
DECLARE event_repaid_assets BIGNUMERIC;
DECLARE event_repaid_shares BIGNUMERIC;
DECLARE event_seized_assets BIGNUMERIC;
DECLARE event_bad_debt_assets BIGNUMERIC;
DECLARE event_bad_debt_shares BIGNUMERIC;
DECLARE event_interest BIGNUMERIC;
DECLARE event_fee_shares BIGNUMERIC;
DECLARE rounding_ok BOOL;

CREATE TEMP TABLE source_events AS
SELECT
  CAST(block_number AS INT64) AS block_number,
  CAST(transaction_index AS INT64) AS transaction_index,
  CAST(log_index AS INT64) AS log_index,
  LOWER(transaction_hash) AS transaction_hash,
  family AS event_family,
  LOWER(market_id) AS market_id,
  LOWER(NULLIF(owner, '')) AS position_owner,
  SAFE_CAST(NULLIF(CAST(assets AS STRING), '') AS BIGNUMERIC) AS assets,
  SAFE_CAST(NULLIF(CAST(shares AS STRING), '') AS BIGNUMERIC) AS shares,
  SAFE_CAST(NULLIF(CAST(interest AS STRING), '') AS BIGNUMERIC) AS interest,
  SAFE_CAST(NULLIF(CAST(fee_shares AS STRING), '') AS BIGNUMERIC) AS fee_shares,
  SAFE_CAST(NULLIF(CAST(repaid_assets AS STRING), '') AS BIGNUMERIC) AS repaid_assets,
  SAFE_CAST(NULLIF(CAST(repaid_shares AS STRING), '') AS BIGNUMERIC) AS repaid_shares,
  SAFE_CAST(NULLIF(CAST(seized_assets AS STRING), '') AS BIGNUMERIC) AS seized_assets,
  SAFE_CAST(NULLIF(CAST(bad_debt_assets AS STRING), '') AS BIGNUMERIC) AS bad_debt_assets,
  SAFE_CAST(NULLIF(CAST(bad_debt_shares AS STRING), '') AS BIGNUMERIC) AS bad_debt_shares,
  topics_json,
  data
FROM `replace_with_project.replace_with_dataset.morpho_one_position_market_events`
WHERE LOWER(market_id) = selected_market
  AND CAST(block_number AS INT64) >= anchor_block + 1
  AND CAST(block_number AS INT64) < replay_end_exclusive;

ASSERT (SELECT COUNT(*) FROM source_events) = 2634
  AS 'Expected the sealed 2,634-event selected-market extract';
ASSERT (
  SELECT COUNT(*) = COUNT(DISTINCT FORMAT('%d|%s|%d', block_number, transaction_hash, log_index))
  FROM source_events
) AS 'Duplicate onchain event key';
ASSERT (
  SELECT COUNT(*) = COUNT(DISTINCT FORMAT('%d|%d|%d', block_number, transaction_index, log_index))
  FROM source_events
) AS 'Duplicate deterministic ordering key';
ASSERT (
  SELECT COUNT(*) FROM source_events WHERE position_owner = selected_wallet
) = 19 AS 'Selected owner must have exactly 19 position events';

CREATE TEMP TABLE replay_states (
  event_sequence INT64,
  block_number INT64,
  transaction_index INT64,
  log_index INT64,
  transaction_hash STRING,
  event_family STRING,
  position_owner STRING,
  rounding_ok BOOL,
  wallet_supply_shares BIGNUMERIC,
  wallet_borrow_shares BIGNUMERIC,
  wallet_collateral_assets BIGNUMERIC,
  total_supply_assets BIGNUMERIC,
  total_supply_shares BIGNUMERIC,
  total_borrow_assets BIGNUMERIC,
  total_borrow_shares BIGNUMERIC
);

FOR event_row IN (
  SELECT
    ROW_NUMBER() OVER (
      ORDER BY block_number, transaction_index, log_index
    ) AS event_sequence,
    *
  FROM source_events
  ORDER BY block_number, transaction_index, log_index
) DO
  SET event_assets = event_row.assets;
  SET event_shares = event_row.shares;
  SET event_repaid_assets = event_row.repaid_assets;
  SET event_repaid_shares = event_row.repaid_shares;
  SET event_seized_assets = event_row.seized_assets;
  SET event_bad_debt_assets = event_row.bad_debt_assets;
  SET event_bad_debt_shares = event_row.bad_debt_shares;
  SET event_interest = event_row.interest;
  SET event_fee_shares = event_row.fee_shares;

  -- Validate emitted conversion before applying the event delta.
  SET rounding_ok = CASE event_row.event_family
    WHEN 'Supply' THEN
      event_shares = DIV(
        event_assets * (total_supply_shares + virtual_shares),
        total_supply_assets + virtual_assets
      )
      OR event_assets = DIV(
        event_shares * (total_supply_assets + virtual_assets)
          + (total_supply_shares + virtual_shares) - 1,
        total_supply_shares + virtual_shares
      )
    WHEN 'Withdraw' THEN
      event_shares = DIV(
        event_assets * (total_supply_shares + virtual_shares)
          + (total_supply_assets + virtual_assets) - 1,
        total_supply_assets + virtual_assets
      )
      OR event_assets = DIV(
        event_shares * (total_supply_assets + virtual_assets),
        total_supply_shares + virtual_shares
      )
    WHEN 'Borrow' THEN
      event_shares = DIV(
        event_assets * (total_borrow_shares + virtual_shares)
          + (total_borrow_assets + virtual_assets) - 1,
        total_borrow_assets + virtual_assets
      )
      OR event_assets = DIV(
        event_shares * (total_borrow_assets + virtual_assets),
        total_borrow_shares + virtual_shares
      )
    WHEN 'Repay' THEN
      event_shares = DIV(
        event_assets * (total_borrow_shares + virtual_shares),
        total_borrow_assets + virtual_assets
      )
      OR event_assets = DIV(
        event_shares * (total_borrow_assets + virtual_assets)
          + (total_borrow_shares + virtual_shares) - 1,
        total_borrow_shares + virtual_shares
      )
    WHEN 'Liquidate' THEN
      event_repaid_assets = DIV(
        event_repaid_shares * (total_borrow_assets + virtual_assets)
          + (total_borrow_shares + virtual_shares) - 1,
        total_borrow_shares + virtual_shares
      )
    ELSE TRUE
  END;
  ASSERT rounding_ok AS 'Morpho assets/shares rounding mismatch';

  CASE event_row.event_family
    WHEN 'Supply' THEN
      SET total_supply_assets = total_supply_assets + event_assets;
      SET total_supply_shares = total_supply_shares + event_shares;
      IF event_row.position_owner = selected_wallet THEN
        SET wallet_supply_shares = wallet_supply_shares + event_shares;
      END IF;
    WHEN 'Withdraw' THEN
      SET total_supply_assets = total_supply_assets - event_assets;
      SET total_supply_shares = total_supply_shares - event_shares;
      IF event_row.position_owner = selected_wallet THEN
        SET wallet_supply_shares = wallet_supply_shares - event_shares;
      END IF;
    WHEN 'Borrow' THEN
      SET total_borrow_assets = total_borrow_assets + event_assets;
      SET total_borrow_shares = total_borrow_shares + event_shares;
      IF event_row.position_owner = selected_wallet THEN
        SET wallet_borrow_shares = wallet_borrow_shares + event_shares;
      END IF;
    WHEN 'Repay' THEN
      SET total_borrow_assets = GREATEST(0, total_borrow_assets - event_assets);
      SET total_borrow_shares = total_borrow_shares - event_shares;
      IF event_row.position_owner = selected_wallet THEN
        SET wallet_borrow_shares = wallet_borrow_shares - event_shares;
      END IF;
    WHEN 'SupplyCollateral' THEN
      IF event_row.position_owner = selected_wallet THEN
        SET wallet_collateral_assets = wallet_collateral_assets + event_assets;
      END IF;
    WHEN 'WithdrawCollateral' THEN
      IF event_row.position_owner = selected_wallet THEN
        SET wallet_collateral_assets = wallet_collateral_assets - event_assets;
      END IF;
    WHEN 'AccrueInterest' THEN
      SET total_borrow_assets = total_borrow_assets + event_interest;
      SET total_supply_assets = total_supply_assets + event_interest;
      SET total_supply_shares = total_supply_shares + event_fee_shares;
    WHEN 'Liquidate' THEN
      SET total_borrow_assets = GREATEST(0, total_borrow_assets - event_repaid_assets);
      SET total_borrow_shares = total_borrow_shares - event_repaid_shares;
      SET total_borrow_assets = total_borrow_assets - event_bad_debt_assets;
      SET total_supply_assets = total_supply_assets - event_bad_debt_assets;
      SET total_borrow_shares = total_borrow_shares - event_bad_debt_shares;
      IF event_row.position_owner = selected_wallet THEN
        SET wallet_borrow_shares =
          wallet_borrow_shares - event_repaid_shares - event_bad_debt_shares;
        SET wallet_collateral_assets = wallet_collateral_assets - event_seized_assets;
      END IF;
    ELSE
      ASSERT FALSE AS 'Unsupported scoped event family';
  END CASE;

  ASSERT wallet_supply_shares >= 0
     AND wallet_borrow_shares >= 0
     AND wallet_collateral_assets >= 0
     AND total_supply_assets >= 0
     AND total_supply_shares >= 0
     AND total_borrow_assets >= 0
     AND total_borrow_shares >= 0
    AS 'Unexplained negative balance after event replay';

  INSERT INTO replay_states VALUES (
    event_row.event_sequence,
    event_row.block_number,
    event_row.transaction_index,
    event_row.log_index,
    event_row.transaction_hash,
    event_row.event_family,
    event_row.position_owner,
    rounding_ok,
    wallet_supply_shares,
    wallet_borrow_shares,
    wallet_collateral_assets,
    total_supply_assets,
    total_supply_shares,
    total_borrow_assets,
    total_borrow_shares
  );
END FOR;

-- The checkpoint is end-of-block, so select the last canonical log in block.
CREATE TEMP TABLE checkpoint_states AS
SELECT * EXCEPT(checkpoint_rank)
FROM (
  SELECT
    IF(block_number = intermediate_block, 'intermediate', 'final') AS checkpoint_name,
    replay_states.*,
    ROW_NUMBER() OVER (
      PARTITION BY IF(block_number = intermediate_block, 'intermediate', 'final')
      ORDER BY block_number DESC, transaction_index DESC, log_index DESC
    ) AS checkpoint_rank
  FROM replay_states
  WHERE block_number = intermediate_block OR block_number <= final_block
)
WHERE checkpoint_rank = 1;

-- Independent archive-RPC reconciliation at end of block 464068387.
ASSERT (
  SELECT wallet_supply_shares = 0
    AND wallet_borrow_shares = 3243341461534715
    AND wallet_collateral_assets = 6188640
    AND total_supply_assets = 2306158539888
    AND total_supply_shares = 2153552919740529288
    AND total_borrow_assets = 1997165132999
    AND total_borrow_shares = 1850710994681969479
  FROM checkpoint_states WHERE checkpoint_name = 'intermediate'
) AS 'Intermediate position or market totals differ from RPC';

-- Independent archive-RPC reconciliation at end of block 482431182.
ASSERT (
  SELECT wallet_supply_shares = 0
    AND wallet_borrow_shares = 0
    AND wallet_collateral_assets = 0
    AND total_supply_assets = 719347685838
    AND total_supply_shares = 669107751092827764
    AND total_borrow_assets = 640120558484
    AND total_borrow_shares = 590476084282594003
  FROM checkpoint_states WHERE checkpoint_name = 'final'
) AS 'Final position or market totals differ from RPC';

-- Checkpoint assets are derived only after the shares and market totals exist.
SELECT
  checkpoint_name,
  block_number,
  wallet_supply_shares,
  DIV(
    wallet_supply_shares * (total_supply_assets + virtual_assets),
    total_supply_shares + virtual_shares
  ) AS wallet_supply_assets_down,
  wallet_borrow_shares,
  DIV(
    wallet_borrow_shares * (total_borrow_assets + virtual_assets)
      + (total_borrow_shares + virtual_shares) - 1,
    total_borrow_shares + virtual_shares
  ) AS wallet_borrow_assets_up,
  wallet_collateral_assets,
  total_supply_assets,
  total_supply_shares,
  total_borrow_assets,
  total_borrow_shares
FROM checkpoint_states
ORDER BY block_number;
