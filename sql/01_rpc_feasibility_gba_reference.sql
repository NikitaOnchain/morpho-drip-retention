/*
Business question
  Does an adaptive eth_getLogs extraction reproduce the bounded Google
  Blockchain Analytics population used by the Phase 2 one-day QA?

Population
  Official Morpho Blue contract on Arbitrum, eight critical event families,
  45 DRIP-eligible market IDs, and the complete UTC day
  [2026-08-17 00:00:00, 2026-08-18 00:00:00).

Grain and expected unique key
  One raw onchain log.
  block_number + transaction_hash + log_index.

Ordering
  block_number, transaction_index, log_index.

Source
  bigquery-public-data.goog_blockchain_arbitrum_one_us.logs
  Accessed 2026-08-31. Address comparisons are lowercase.

Cost checkpoint
  Dry-run upper bound: 3,175,809,476 bytes (2.96 GiB).
  Executed job: bqjob_r2a2bb11540cb237_000001a057823957_1.
  Actual processed: 3,064,373,457 bytes; billed: 3,064,987,648 bytes.
  Final execution duration: 2,526 ms.

Important limitation
  This is a one-day RPC feasibility reference, not a full-window extraction.
  It intentionally reproduces the prior 2,087-row GBA population; it does not
  include unrelated Morpho event families or non-eligible market IDs.
*/

WITH event_hashes AS (
  SELECT event_hash
  FROM UNNEST([
    '0xedf8870433c83823eb071d3df1caa8d008f12f6440918c20d75a3602cda30fe0',
    '0xa56fc0ad5702ec05ce63666221f796fb62437c32db1aa1aa075fc6484cf58fbf',
    '0x570954540bed6b1304a87dfe815a5eda4a648f7097a16240dcd85c9b5fd42a43',
    '0x52acb05cebbd3cd39715469f22afbf5a17496295ef3bc9bb5944056c63ccaa09',
    '0xa3b9472a1399e17e123f3c2e6586c23e504184d504de59cdaa2b375e880c6184',
    '0xe80ebd7cc9223d7382aab2e0d1d6155c65651f83d53c8b9b06901d167e321142',
    '0xa4946ede45d0c6f06a0f5ce92c9ad3b4751452d2fe0e25010783bcab57a67e41',
    '0x9d9bd501d0657d7dfe415f779a620a62b78bc508ddc0891fbbd8b7ac0f8fce87'
  ]) AS event_hash
),
eligible_markets AS (
  SELECT market_id
  FROM UNNEST([
    '0xff608e5881ccba3859006b3c01e377314384c3d661d684c3e8b6354146e62155',
    '0x090ff0cd57a258b342c870691a180bb79691e97b31ddda2b7cdd4b5a362c3cca',
    '0xd91052003758145cc53615895c0ce2081c7080b661dbab5652c2b8433b248c2d',
    '0x8e58f0dea27f877db258ecbbe16e57c9bb3541448ac0d578ef08c5b93ea9b84b',
    '0xde895fd4a9d1ca693485fcfc2ee47d8c3b47f810bbce3c965c60d97b855d4ed2',
    '0x571cb3ac535d61d92026c071ef1df4794d0bbbe1755f916ff640746f81b52af4',
    '0xed06d9e82d7c35ca80d3983194e15462a96202bd875800af18183321f4611868',
    '0xe0432ceb599fbe41defbd62fe8e914824af9d891a0a92c39de7063176c8e480b',
    '0xac6a118134cc4208a22534b041a83f4ac5ca42e2ab9ea732ee53c44b7deebc62',
    '0xef62d07c7e29c3864feb6de8945edd82688a2ea558de5a44dc795ad1eb1d9853',
    '0x209fa1520640f664f59f7c1f955d52e8b81ead826edf439b48254d21d24b97a9',
    '0xadc6897d644a005149d1aa42de72bcb1ff1c9f7c4a8b00db3e2356752995f80e',
    '0x1d094624063756fc61aaf061c7da056aebe3b3ad0ae0395b22e00db6c074de7c',
    '0xb7b5729ad332f57a02f4d9f87aa50910ee955d859e2b2ad9b0b8e15ca44d8b7f',
    '0xa35d91efb3e284a0ab7098e8c5a65caf58ea0451073e36a544a821fd8f350953',
    '0x14982da64b67967ef3a70c2f3b7d05518f7dd4ba98d850c40c46618c75059a64',
    '0x1a926ab8add08dca634f8d6cecd8c866e166a4affc65801beda9f239d21b622a',
    '0x6a2b0c23c79dde84628314d21797f7bd5b06ae36e6bde6924ece64ef4821d2df',
    '0x7717f1e04510390518811b3133ea47c298094ddd1d806ed8f8867d88c727bad7',
    '0x52f4d5038749565658a51f43d214e811c328c00c8b58c544accfb8924e8be8f8',
    '0x58df3ad9cf719b1ca97365db634a11b770785517f409ecbe85eefdb34803de1f',
    '0x84367e5bc5df26437618f749d5beb793746e620560721fec15518d684191ebc6',
    '0x6c831dcc45a7c0af00b751da651bd874b96653c587615d11aafade7b357c4b43',
    '0x30c505b1ce479157e1035bdc5de3d4c811cf3e427c31db0b81b5c27a09054e97',
    '0x7d4799e15dcaad9da49ab8edf46d647db2da2ff419db52e8ec0984d0c49e8b9b',
    '0x8147c63f3f6f5a0825c84bf2cb11443c72b609fa39cf9a362e3d4dc2c5ca76c4',
    '0xf4ab212f6fcc943e2669cb6307fa4b608b0418ac5255c100e58394822157785c',
    '0x729e4ab1f1613a55f4dc6444cb073a2f9ba4c402f8c59e93e1d725f9ce45f23a',
    '0x678b525f162b499b17d8fd71f3129bd3a5a10d4c728e6af02ee7c644ae262d01',
    '0xc7670063349ac19dfa324ead7bd7da2985ae931e1b09fb0e31b62c6486b730bd',
    '0xd478de9c069f12759d3baed9ddd16fe8902128937821af3a3cf77eca1885c7fc',
    '0xe23e15ddd552eb148045e3f4b74e71f4923bc6bea6e5bda0a4cf89a0cecd1a3b',
    '0x71c2954e00c8f72864600c9d1d1cd70fa15202c4294cd938d80add3be2eced26',
    '0x989ddb4f5b09e6d02e7f5f2f8efb846fd2de1f3f3dfd96e1939455abe7dd5a48',
    '0x7e7c08f2d8bb6821408ac6b4e2f322d73ba1fb8ce20b3b65087f440ef3b2f8f1',
    '0x77fe2f7c2dd6f4da6bc5f445b06052ff8df55cb70cfce9afc16ec3c69a5fd3a3',
    '0xf86f3edd6f16cd8211f4d206866dc4ecd41be6211063ac11f8508e1b7112ef40',
    '0x551dbcdcceaf9322986e0cddde993d49840522a9532dc441359acd98af8badff',
    '0xe0de6b571ec913ada63d5327f70c8849ea2363d47f44a190e8fb489db07fee1e',
    '0xd09404e9512e1341321c8ae3bd663fab7087582142ac61486635a6c072c2af12',
    '0x11d3bca0d1a9af8bf2982ef802f2971cf86043df1b31a044cacb35a8048156c6',
    '0x33e0c8ab132390822b07e5dc95033cf250c963153320b7ffca73220664da2ea0',
    '0x06a5954e8222a1f4719934d370ac558b657c6a5321d6cae615127b6596d10d32',
    '0x582c92d5ea0ab48eba3a1ee88c8884e34f7fc61c57fb821f3f6d9e474574c6e3',
    '0x9e90aec7d768403dacc9dd0d8320307fda3f980eed4df43e3e52168a1c667709'
  ]) AS market_id
)
SELECT
  CAST(block_timestamp AS STRING) AS block_timestamp_utc,
  CAST(block_number AS STRING) AS block_number,
  LOWER(transaction_hash) AS transaction_hash,
  CAST(transaction_index AS STRING) AS transaction_index,
  CAST(log_index AS STRING) AS log_index,
  LOWER(address) AS address,
  TO_JSON_STRING(ARRAY(SELECT LOWER(topic) FROM UNNEST(topics) AS topic)) AS topics_json,
  LOWER(data) AS data,
  CAST(removed AS STRING) AS removed
FROM `bigquery-public-data.goog_blockchain_arbitrum_one_us.logs`
WHERE block_timestamp >= TIMESTAMP('2026-08-17 00:00:00+00')
  AND block_timestamp < TIMESTAMP('2026-08-18 00:00:00+00')
  AND address = '0x6c247b1f6182318877311737bac0844baa518f5e'
  AND topics[SAFE_OFFSET(0)] IN (SELECT event_hash FROM event_hashes)
  AND topics[SAFE_OFFSET(1)] IN (SELECT market_id FROM eligible_markets)
  AND NOT removed
ORDER BY block_number, transaction_index, log_index;
