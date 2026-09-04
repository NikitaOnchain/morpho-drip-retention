#!/usr/bin/env python3
"""Build and fail-closed QA the Phase 6 45-market Morpho daily state.

Only the immutable Phase 2 shard manifest and accepted Phase 1 eligibility
bridge are read.  The accepted Phase 4 replay SQL is reused as the accounting
module, then sql/20_market_day_full.sql materializes the production layer.  A
versioned SQLite database is built under a `.building.sqlite` name and is
atomically published only after SQL, RPC, prototype and SQLite integrity QA.
"""

from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import json
import os
import platform
import shutil
import sqlite3
import time
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import build_morpho_market_day_prototype as core
from morpho_archive_rpc_cache import ArchiveRpcCache, CachedArchiveSession, EXPECTED_CHAIN_ID
from select_morpho_one_position import (
    FEE_RECIPIENT_SELECTOR,
    MARKET_SELECTOR,
    MORPHO_ADDRESS,
    POSITION_SELECTOR,
    RpcClient,
    archive_market_call,
    decode_words,
    validate_live_chain,
)


SCRIPT_VERSION = "morpho-phase6-full-market-day-v1"
CACHE_VERSION = "morpho-phase6-independent-market-checkpoints-v1"
EXPECTED_MANIFEST_SHA256 = "c8552428187094e5aad725193f2e3023e622ddc4ab37428f1414c375e7d6be58"
EXPECTED_MARKETS_SHA256 = "a88fceaa19fe383bb956ef698a819facb2d345a29bd173db730e85bbd5213a6a"
EXPECTED_BRIDGE_SHA256 = "cbab02426bcd1ac1ad0679156f837e155c5b04e86b63001a9149b0cbae27d305"
EXPECTED_BOUNDARIES_SHA256 = "da1b7c58406301f8b282ae798344dba292f2b0a650ae1f451235f84c8a261ac0"
EXPECTED_METRICS_SHA256 = "2774c0856ca66da4611523289a7e1c4da937ce208cad9799c2f008753eca2ba2"
EXPECTED_MARKETS = 45
EXPECTED_DAYS = 405
EXPECTED_OUTPUT_ROWS = EXPECTED_MARKETS * EXPECTED_DAYS
EXPECTED_BRIDGE_ROWS = 469
MAX_DATABASE_BYTES = 10 * 1024**3
MIN_FREE_BYTES = 10 * 1024**3
RPC_SAMPLE_MARKETS = 5
PROTOTYPE_MARKETS = {
    "0xd09404e9512e1341321c8ae3bd663fab7087582142ac61486635a6c072c2af12",
    "0xf86f3edd6f16cd8211f4d206866dc4ecd41be6211063ac11f8508e1b7112ef40",
    "0x571cb3ac535d61d92026c071ef1df4794d0bbbe1755f916ff640746f81b52af4",
}


class FullBuildError(RuntimeError):
    """A fail-closed production build, evidence or QA defect."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="data/raw/morpho_full_window/manifest.json")
    parser.add_argument("--boundaries", default="data/raw/morpho_full_window/day_boundaries.json")
    parser.add_argument("--markets", default="data/drip_morpho_markets.csv")
    parser.add_argument("--bridge", default="data/drip_morpho_eligibility_bridge.csv")
    parser.add_argument("--metrics", default="docs/METRICS.md")
    parser.add_argument("--prototype-db", default="data/tmp/morpho_phase4_market_day_prototype.sqlite")
    parser.add_argument("--core-sql", default="sql/10_market_day_prototype.sql")
    parser.add_argument("--core-qa-sql", default="sql/90_qa_market_day_prototype.sql")
    parser.add_argument("--production-sql", default="sql/20_market_day_full.sql")
    parser.add_argument("--production-qa-sql", default="sql/90_qa_market_day_full.sql")
    parser.add_argument("--checkpoint-plan", default="data/morpho_phase6_rpc_checkpoint_plan.json")
    parser.add_argument("--checkpoint-evidence", default="data/morpho_phase6_rpc_checkpoint_evidence.json")
    parser.add_argument("--rpc-cache", default="data/tmp/morpho_phase6_rpc_checkpoints_v1.sqlite")
    parser.add_argument("--building-db", default="data/tmp/morpho_market_day_full_v1.building.sqlite")
    parser.add_argument("--final-db", default="data/tmp/morpho_market_day_full_v1.sqlite")
    parser.add_argument("--build-checkpoint", default="data/morpho_market_day_full_build_checkpoint.json")
    parser.add_argument("--sample-output", default="data/morpho_market_day_full_sample.csv")
    parser.add_argument("--coverage-output", default="data/morpho_market_day_full_coverage.csv")
    parser.add_argument("--qa-output", default="data/morpho_market_day_full_qa.json")
    parser.add_argument("--rpc-url", default="https://arbitrum-one.public.blastapi.io")
    parser.add_argument("--offline-only", action="store_true")
    parser.add_argument("--retries", type=int, default=8)
    parser.add_argument("--min-request-interval", type=float, default=0.75)
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FullBuildError(message)


def sha256_file(path: Path) -> str:
    return core.sha256_file(path)


def atomic_json(path: Path, value: object) -> None:
    core.atomic_write_json(path, value)


def atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    core.atomic_write_csv(path, rows)


def update_checkpoint(path: Path, stage: str, status: str, **details: Any) -> None:
    value = {
        "version": SCRIPT_VERSION,
        "stage": stage,
        "status": status,
        "updated_at_utc": utc_now(),
        "immutable_manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "markets_sha256": EXPECTED_MARKETS_SHA256,
        "eligibility_bridge_sha256": EXPECTED_BRIDGE_SHA256,
        "frozen_metrics_sha256": EXPECTED_METRICS_SHA256,
        **details,
    }
    atomic_json(path, value)


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_inputs(
    markets_path: Path,
    bridge_path: Path,
    archetypes_path: Path,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    require(sha256_file(markets_path) == EXPECTED_MARKETS_SHA256, "Accepted market CSV hash changed")
    require(sha256_file(bridge_path) == EXPECTED_BRIDGE_SHA256, "Accepted eligibility bridge hash changed")
    markets = load_csv(markets_path)
    bridge = load_csv(bridge_path)
    require(len(markets) == EXPECTED_MARKETS, "Expected exactly 45 accepted markets")
    require(len(bridge) == EXPECTED_BRIDGE_ROWS, "Expected exactly 469 eligibility rows")
    market_ids = [row["market_id"].lower() for row in markets]
    require(len(set(market_ids)) == EXPECTED_MARKETS, "Accepted market IDs are not unique")
    market_set = set(market_ids)
    bridge_keys: set[tuple[str, int, str]] = set()
    for row in bridge:
        row["market_id"] = row["market_id"].lower()
        key = (row["market_id"], int(row["epoch"]), row["side"])
        require(key not in bridge_keys, f"Duplicate eligibility key: {key}")
        bridge_keys.add(key)
        require(row["market_id"] in market_set, f"Orphan bridge market: {row['market_id']}")
        require(1 <= int(row["epoch"]) <= 12, f"Invalid bridge epoch: {row['epoch']}")
        require(row["side"] in {"supply", "borrow"}, f"Invalid bridge side: {row['side']}")
    require({row["market_id"] for row in bridge} == market_set, "Bridge does not cover all 45 markets")

    archetype_map = {
        row["market_id"].lower(): row["archetype"]
        for row in load_csv(archetypes_path)
    }
    dimension: list[dict[str, str]] = []
    for row in markets:
        market_id = row["market_id"].lower()
        dimension.append({
            "archetype": archetype_map.get(market_id, "accepted_drip_market"),
            "market_id": market_id,
            "loan_symbol": row["loan_symbol"],
            "loan_address": row["loan_address"].lower(),
            "collateral_symbol": row["collateral_symbol"],
            "collateral_address": row["collateral_address"].lower(),
            "lltv_1e18": row["lltv_1e18"],
        })
    return dimension, bridge


def build_checkpoint_plan(
    path: Path,
    manifest_sha: str,
    markets_sha: str,
    bridge_sha: str,
    events: list[dict[str, Any]],
    market_ids: list[str],
) -> tuple[dict[str, Any], str]:
    by_market: dict[str, list[dict[str, Any]]] = {market: [] for market in market_ids}
    for event in events:
        by_market[str(event["market_id"])].append(event)
    require(all(by_market.values()), "At least one accepted market has no scoped event")
    ranked = sorted(
        market_ids,
        key=lambda market: hashlib.sha256(
            f"morpho-phase6-rpc-sample-v1|{market}".encode("ascii")
        ).hexdigest(),
    )
    sample_markets = ranked[:RPC_SAMPLE_MARKETS]
    checkpoints: list[dict[str, Any]] = []
    for market in sorted(market_ids):
        checkpoints.append({
            "ordinal": len(checkpoints),
            "market_id": market,
            "checkpoint_name": "anchor",
            "block_number": core.EXPECTED_START_BLOCK - 1,
            "sample_rank": None,
            "rationale": "initialization evidence at end of block before replay interval",
        })
    for rank, market in enumerate(sample_markets, start=1):
        rows = by_market[market]
        points = (
            ("sample_start", int(rows[0]["block_number"]), "end of first scoped-event block"),
            ("sample_mid", int(rows[(len(rows) - 1) // 2]["block_number"]), "end of lower-median ordered-event block"),
            ("sample_end", core.EXPECTED_END_BLOCK_EXCLUSIVE - 1, "end of final replay block"),
        )
        require(len({point[1] for point in points}) == 3, f"Non-distinct sample checkpoints: {market}")
        for name, block, rationale in points:
            checkpoints.append({
                "ordinal": len(checkpoints),
                "market_id": market,
                "checkpoint_name": name,
                "block_number": block,
                "sample_rank": rank,
                "rationale": rationale,
            })
    planned = {
        "version": SCRIPT_VERSION,
        "status": "precommitted_before_rpc",
        "created_at_utc": utc_now(),
        "chain_id": EXPECTED_CHAIN_ID,
        "contract_address": MORPHO_ADDRESS,
        "manifest_sha256": manifest_sha,
        "markets_sha256": markets_sha,
        "eligibility_bridge_sha256": bridge_sha,
        "selection_rule": "all 45 anchors; then first 5 SHA256(morpho-phase6-rpc-sample-v1|market_id) markets with start/mid/end checkpoints",
        "sample_market_count": RPC_SAMPLE_MARKETS,
        "sample_markets": sample_markets,
        "ordering": ["block_number", "transaction_index", "log_index"],
        "checkpoints": checkpoints,
    }
    if path.exists():
        existing = core.load_json(path)
        for key in (
            "version", "chain_id", "contract_address", "manifest_sha256", "markets_sha256",
            "eligibility_bridge_sha256", "selection_rule", "sample_market_count",
            "sample_markets", "ordering", "checkpoints",
        ):
            require(existing.get(key) == planned.get(key), f"Existing Phase 6 checkpoint plan mismatch: {key}")
        plan = existing
    else:
        atomic_json(path, planned)
        plan = planned
    return plan, sha256_file(path)


def fetch_rpc_checkpoints(
    args: argparse.Namespace,
    plan: dict[str, Any],
    plan_sha: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    identity = {
        "cache_version": CACHE_VERSION,
        "chain_id": EXPECTED_CHAIN_ID,
        "contract_address": MORPHO_ADDRESS,
        "manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "markets_sha256": EXPECTED_MARKETS_SHA256,
        "eligibility_bridge_sha256": EXPECTED_BRIDGE_SHA256,
        "checkpoint_plan_sha256": plan_sha,
        "planned_calls": [
            {
                "abi_method": "market(bytes32)",
                "market_id": row["market_id"],
                "checkpoint_name": row["checkpoint_name"],
                "block_number": row["block_number"],
            }
            for row in plan["checkpoints"]
        ],
    }
    cache_path = Path(args.rpc_cache).resolve()
    cache = ArchiveRpcCache(
        cache_path, identity, MORPHO_ADDRESS,
        POSITION_SELECTOR, MARKET_SELECTOR, FEE_RECIPIENT_SELECTOR,
    )
    client: RpcClient | None = None
    results: list[dict[str, Any]] = []
    audit: dict[str, Any] = {}
    session_metrics: dict[str, Any] = {}
    try:
        if args.offline_only:
            def cache_miss(_method: str, _params: list[Any]) -> Any:
                raise FullBuildError("Phase 6 RPC cache miss in --offline-only mode")
            rpc_call = cache_miss
        else:
            client = RpcClient(
                args.rpc_url,
                retries=args.retries,
                min_request_interval=args.min_request_interval,
            )
            validate_live_chain(client)
            rpc_call = client.call
        session = CachedArchiveSession(rpc_call, cache, MORPHO_ADDRESS)
        for row in plan["checkpoints"]:
            call = archive_market_call(str(row["market_id"]), int(row["block_number"]))
            result_hex = session.execute(call)
            words = decode_words(result_hex, 6)
            result = {
                "market_id": str(row["market_id"]),
                "checkpoint_name": str(row["checkpoint_name"]),
                "block_number": int(row["block_number"]),
                "total_supply_assets": str(words[0]),
                "total_supply_shares": str(words[1]),
                "total_borrow_assets": str(words[2]),
                "total_borrow_shares": str(words[3]),
                "last_update": int(words[4]),
                "fee": str(words[5]),
                "cache_key_sha256": call.key_sha256(EXPECTED_CHAIN_ID, MORPHO_ADDRESS),
                "result_sha256": hashlib.sha256(result_hex.encode("ascii")).hexdigest(),
            }
            if result["checkpoint_name"] == "anchor":
                require(
                    all(result[field] == "0" for field in (
                        "total_supply_assets", "total_supply_shares",
                        "total_borrow_assets", "total_borrow_shares",
                    )) and result["last_update"] == 0,
                    f"Non-zero market anchor blocks aggregate-collateral replay: {result['market_id']}",
                )
            results.append(result)
        audit = cache.audit()
        session_metrics = session.metrics()
    finally:
        cache.close()
    expected_calls = EXPECTED_MARKETS + RPC_SAMPLE_MARKETS * 3
    require(len(results) == expected_calls, "Unexpected bounded RPC result count")
    require(audit.get("sqlite_integrity") == "ok", "Phase 6 RPC cache integrity failed")
    require(audit.get("invalid_entries") == 0, "Invalid Phase 6 RPC cache entries")
    require(audit.get("duplicate_key_groups") == 0, "Duplicate Phase 6 RPC cache entries")
    require(audit.get("progress_gaps") == 0 and audit.get("orphan_progress_rows") == 0, "Phase 6 RPC progress defects")
    require(audit.get("cache_entries") == expected_calls, "Phase 6 RPC cache entry count mismatch")
    evidence = {
        "version": CACHE_VERSION,
        "status": "validated",
        "created_at_utc": utc_now(),
        "chain_id": EXPECTED_CHAIN_ID,
        "contract_address": MORPHO_ADDRESS,
        "manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "markets_sha256": EXPECTED_MARKETS_SHA256,
        "eligibility_bridge_sha256": EXPECTED_BRIDGE_SHA256,
        "checkpoint_plan_sha256": plan_sha,
        "cache_path_ignored": str(cache_path),
        "cache_audit": audit,
        "archive_session_metrics": session_metrics,
        "rpc_transport_metrics": dict(client.metrics) if client is not None else {"offline_only": 1},
        "checkpoints": results,
    }
    atomic_json(Path(args.checkpoint_evidence).resolve(), evidence)
    return results, evidence


def initialize_database(
    path: Path,
    manifest_sha: str,
    boundaries_sha: str,
    markets_sha: str,
    bridge_sha: str,
    markets: list[dict[str, str]],
    bridge: list[dict[str, str]],
    boundaries: list[dict[str, Any]],
    events: list[dict[str, Any]],
    checkpoints: list[dict[str, Any]],
) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.exists(), f"Building database already exists; inspect checkpoint instead of overwriting: {path}")
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA temp_store=FILE")
    connection.execute("PRAGMA foreign_keys=ON")
    core.register_exact_functions(connection)
    connection.executescript(
        """
        CREATE TABLE prototype_config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE market_dim (
          archetype TEXT NOT NULL, market_id TEXT PRIMARY KEY,
          loan_symbol TEXT NOT NULL, loan_address TEXT NOT NULL,
          collateral_symbol TEXT NOT NULL, collateral_address TEXT NOT NULL,
          first_scoped_event_block INTEGER NOT NULL, data_start_utc_day TEXT NOT NULL
        );
        CREATE TABLE day_boundary (
          day_ordinal INTEGER PRIMARY KEY, day_utc TEXT NOT NULL,
          day_start_utc TEXT NOT NULL, day_end_exclusive_utc TEXT NOT NULL,
          start_block INTEGER NOT NULL, end_block_exclusive INTEGER NOT NULL
        );
        CREATE TABLE source_event (
          market_id TEXT NOT NULL, event_sequence INTEGER NOT NULL,
          day_ordinal INTEGER NOT NULL, day_utc TEXT NOT NULL,
          block_number INTEGER NOT NULL, transaction_index INTEGER NOT NULL,
          log_index INTEGER NOT NULL, transaction_hash TEXT NOT NULL,
          event_family TEXT NOT NULL, owner TEXT NOT NULL, caller TEXT NOT NULL,
          assets TEXT, shares TEXT, interest TEXT, fee_shares TEXT,
          repaid_assets TEXT, repaid_shares TEXT, seized_assets TEXT,
          bad_debt_assets TEXT, bad_debt_shares TEXT,
          topics_json TEXT NOT NULL, data TEXT NOT NULL,
          PRIMARY KEY (market_id, event_sequence),
          UNIQUE (block_number, transaction_hash, log_index)
        ) WITHOUT ROWID;
        CREATE INDEX source_event_block_ix ON source_event (market_id, block_number, event_sequence);
        CREATE INDEX source_event_day_ix ON source_event (market_id, day_utc);
        CREATE TABLE rpc_checkpoint (
          market_id TEXT NOT NULL, checkpoint_name TEXT NOT NULL,
          block_number INTEGER NOT NULL, total_supply_assets TEXT NOT NULL,
          total_supply_shares TEXT NOT NULL, total_borrow_assets TEXT NOT NULL,
          total_borrow_shares TEXT NOT NULL, last_update INTEGER NOT NULL,
          fee TEXT NOT NULL, cache_key_sha256 TEXT NOT NULL,
          result_sha256 TEXT NOT NULL,
          PRIMARY KEY (market_id, checkpoint_name)
        ) WITHOUT ROWID;
        CREATE TABLE eligibility_bridge (
          market_id TEXT NOT NULL, epoch INTEGER NOT NULL, side TEXT NOT NULL,
          epoch_start_utc TEXT NOT NULL, epoch_end_utc TEXT NOT NULL,
          loan_symbol TEXT NOT NULL, loan_address TEXT NOT NULL,
          collateral_symbol TEXT NOT NULL, collateral_address TEXT NOT NULL,
          lltv_1e18 TEXT NOT NULL, eligibility_mode TEXT NOT NULL,
          shared_pool_eligible INTEGER NOT NULL,
          dedicated_market_eligible INTEGER NOT NULL,
          shared_campaign_db_id TEXT,
          dedicated_campaign_db_id TEXT,
          dedicated_market_allocation_arb TEXT,
          PRIMARY KEY (market_id, epoch, side)
        ) WITHOUT ROWID;
        """
    )
    config = {
        "script_version": SCRIPT_VERSION,
        "sql_engine": f"SQLite {sqlite3.sqlite_version} via Python {platform.python_version()}",
        "manifest_sha256": manifest_sha,
        "markets_sha256": markets_sha,
        "eligibility_bridge_sha256": bridge_sha,
        "boundary_json_sha256": boundaries_sha,
        "frozen_metrics_sha256": EXPECTED_METRICS_SHA256,
        "window_start_utc": "2025-07-09T13:00:00Z",
        "window_end_exclusive_utc": "2026-08-18T00:00:00Z",
        "ordering": "block_number, transaction_index, log_index",
        "numeric_storage": "unsigned decimal TEXT with exact Python bigint SQLite UDFs",
    }
    connection.executemany("INSERT INTO prototype_config VALUES (?, ?)", config.items())
    event_first: dict[str, dict[str, Any]] = {}
    for event in events:
        event_first.setdefault(str(event["market_id"]), event)
    connection.executemany(
        "INSERT INTO market_dim VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(
            row["archetype"], row["market_id"], row["loan_symbol"], row["loan_address"],
            row["collateral_symbol"], row["collateral_address"],
            int(event_first[row["market_id"]]["block_number"]),
            str(event_first[row["market_id"]]["day_utc"]),
        ) for row in markets],
    )
    connection.executemany(
        "INSERT INTO day_boundary VALUES (?, ?, ?, ?, ?, ?)",
        [(
            index, str(boundaries[index]["boundary_utc"])[:10],
            boundaries[index]["boundary_utc"], boundaries[index + 1]["boundary_utc"],
            int(boundaries[index]["block_number"]), int(boundaries[index + 1]["block_number"]),
        ) for index in range(EXPECTED_DAYS)],
    )
    bridge_columns = list(bridge[0])
    require(bridge_columns == [
        "market_id", "epoch", "side", "epoch_start_utc", "epoch_end_utc",
        "loan_symbol", "loan_address", "collateral_symbol", "collateral_address",
        "lltv_1e18", "eligibility_mode", "shared_pool_eligible",
        "dedicated_market_eligible", "shared_campaign_db_id",
        "dedicated_campaign_db_id", "dedicated_market_allocation_arb",
    ], "Eligibility bridge schema changed")
    connection.executemany(
        "INSERT INTO eligibility_bridge VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [tuple(row[column] if row[column] != "" else None for column in bridge_columns) for row in bridge],
    )
    event_columns = (
        "market_id", "event_sequence", "day_ordinal", "day_utc", "block_number",
        "transaction_index", "log_index", "transaction_hash", "family", "owner", "caller",
        *core.NUMERIC_FIELDS, "topics_json", "data",
    )
    placeholders = ",".join("?" for _ in event_columns)
    def event_values() -> Iterable[tuple[Any, ...]]:
        for event in events:
            yield tuple(
                None if event.get(column) is None
                else str(event.get(column)) if column in core.NUMERIC_FIELDS
                else event.get(column)
                for column in event_columns
            )
    connection.executemany(f"INSERT INTO source_event VALUES ({placeholders})", event_values())
    connection.executemany(
        "INSERT INTO rpc_checkpoint VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(
            row["market_id"], row["checkpoint_name"], row["block_number"],
            row["total_supply_assets"], row["total_supply_shares"],
            row["total_borrow_assets"], row["total_borrow_shares"],
            row["last_update"], row["fee"], row["cache_key_sha256"], row["result_sha256"],
        ) for row in checkpoints],
    )
    connection.commit()
    return connection


def resume_loaded_database(path: Path) -> tuple[sqlite3.Connection, str]:
    """Resume a validated input load or a fully materialized pre-population-QA DB."""
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    core.register_exact_functions(connection)
    config = dict(connection.execute("SELECT key, value FROM prototype_config").fetchall())
    expected = {
        "script_version": SCRIPT_VERSION,
        "manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "markets_sha256": EXPECTED_MARKETS_SHA256,
        "eligibility_bridge_sha256": EXPECTED_BRIDGE_SHA256,
        "boundary_json_sha256": EXPECTED_BOUNDARIES_SHA256,
        "frozen_metrics_sha256": EXPECTED_METRICS_SHA256,
    }
    require(all(config.get(key) == value for key, value in expected.items()), "Building DB identity mismatch")
    require(connection.execute("SELECT COUNT(*) FROM market_dim").fetchone()[0] == EXPECTED_MARKETS, "Resume market count mismatch")
    require(connection.execute("SELECT COUNT(*) FROM day_boundary").fetchone()[0] == EXPECTED_DAYS, "Resume boundary count mismatch")
    require(connection.execute("SELECT COUNT(*) FROM source_event").fetchone()[0] == core.EXPECTED_ROWS, "Resume source-event count mismatch")
    require(connection.execute("SELECT COUNT(*) FROM eligibility_bridge").fetchone()[0] == EXPECTED_BRIDGE_ROWS, "Resume bridge count mismatch")
    require(connection.execute("SELECT COUNT(*) FROM rpc_checkpoint").fetchone()[0] == EXPECTED_MARKETS + RPC_SAMPLE_MARKETS * 3, "Resume RPC count mismatch")
    output_names = {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('market_event_state','market_day','market_day_full','qa_result','phase6_qa_result')"
    ).fetchall()}
    if not output_names:
        resume_mode = "database_loaded"
    else:
        require(
            {"market_event_state", "market_day", "market_day_full", "qa_result"}.issubset(output_names),
            f"Refusing ambiguous partial SQL resume: {sorted(output_names)}",
        )
        require(connection.execute("SELECT COUNT(*) FROM market_day_full").fetchone()[0] == EXPECTED_OUTPUT_ROWS, "Materialized resume row count mismatch")
        resume_mode = "population_qa_only"
    require(connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "Building DB integrity failed before resume")
    return connection, resume_mode


def load_phase4_reference(connection: sqlite3.Connection, prototype_path: Path) -> str:
    """Copy the accepted comparison table through an immutable read-only handle."""
    uri = f"file:{prototype_path.as_posix()}?mode=ro&immutable=1"
    source = sqlite3.connect(uri, uri=True)
    source.row_factory = sqlite3.Row
    try:
        tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        require("market_day" in tables and "qa_result" in tables, "Accepted Phase 4 database is incomplete")
        failures = source.execute(
            "SELECT COUNT(*) FROM qa_result WHERE blocking=1 AND status<>'PASS'"
        ).fetchone()[0]
        require(failures == 0, "Accepted Phase 4 database contains blocking QA failures")
        columns = [row[1] for row in source.execute("PRAGMA table_info(market_day)")]
        rows = source.execute("SELECT * FROM market_day ORDER BY market_id, day_ordinal").fetchall()
        require(len(rows) == 3 * EXPECTED_DAYS, "Accepted Phase 4 market_day row count changed")
        source_schema = source.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='market_day'"
        ).fetchone()[0]
    finally:
        source.close()
    connection.execute("DROP TABLE IF EXISTS phase4_reference_market_day")
    quoted = ", ".join(f'"{column}"' for column in columns)
    connection.execute(f"CREATE TABLE phase4_reference_market_day AS SELECT {quoted} FROM market_day WHERE 0")
    connection.executemany(
        f"INSERT INTO phase4_reference_market_day ({quoted}) VALUES ({','.join('?' for _ in columns)})",
        [tuple(row[column] for column in columns) for row in rows],
    )
    connection.execute(
        "CREATE UNIQUE INDEX phase4_reference_market_day_uq ON phase4_reference_market_day (market_id, day_utc)"
    )
    connection.execute("DROP TABLE IF EXISTS phase4_reference_status")
    connection.execute("CREATE TABLE phase4_reference_status (blocking_failure_count INTEGER NOT NULL)")
    connection.execute("INSERT INTO phase4_reference_status VALUES (?)", (int(failures),))
    connection.commit()
    return hashlib.sha256(str(source_schema).encode("utf-8")).hexdigest()


def database_working_bytes(path: Path) -> int:
    return sum(
        candidate.stat().st_size
        for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm"))
        if candidate.exists()
    )


def coverage_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(
        """
        SELECT m.market_id, m.loan_symbol, m.collateral_symbol,
               COUNT(d.day_utc) AS market_day_rows,
               SUM(d.total_event_count) AS source_event_rows,
               MIN(CASE WHEN d.status='active' THEN d.day_utc END) AS first_active_day,
               MAX(CASE WHEN d.status='active' THEN d.day_utc END) AS last_active_day,
               SUM(d.status='inactive_pre_first_scoped_event') AS inactive_day_rows
        FROM market_dim AS m
        LEFT JOIN market_day_full AS d ON d.market_id=m.market_id
        GROUP BY m.market_id, m.loan_symbol, m.collateral_symbol
        ORDER BY m.market_id
        """
    ).fetchall()]


def main() -> int:
    args = parse_args()
    started = time.perf_counter()
    checkpoint_path = Path(args.build_checkpoint).resolve()
    building_path = Path(args.building_db).resolve()
    final_path = Path(args.final_db).resolve()
    connection: sqlite3.Connection | None = None
    try:
        paths = {
            name: Path(getattr(args, name)).resolve()
            for name in (
                "manifest", "boundaries", "markets", "bridge", "metrics", "prototype_db",
                "core_sql", "core_qa_sql", "production_sql", "production_qa_sql",
            )
        }
        require(not final_path.exists(), f"Published database already exists; refusing overwrite: {final_path}")
        require(shutil.disk_usage(building_path.parent).free >= MIN_FREE_BYTES, "Less than 10 GiB free before build")
        require(sha256_file(paths["metrics"]) == EXPECTED_METRICS_SHA256, "Frozen metrics v1.0 changed")
        require(sha256_file(paths["manifest"]) == EXPECTED_MANIFEST_SHA256, "Immutable Phase 2 manifest changed")
        require(sha256_file(paths["boundaries"]) == EXPECTED_BOUNDARIES_SHA256, "Accepted UTC boundaries changed")
        manifest = core.load_json(paths["manifest"])
        require(manifest.get("status") == "complete" and manifest.get("complete") is True, "Phase 2 manifest is not complete")
        require(int(manifest["row_count"]) == core.EXPECTED_ROWS, "Phase 2 row count changed")
        require(int(manifest["verified_shard_count"]) == core.EXPECTED_SHARDS, "Phase 2 shard count changed")
        require(paths["prototype_db"].exists(), "Accepted Phase 4 prototype database is unavailable")
        archetype_path = Path("data/morpho_phase4_market_archetypes.csv").resolve()
        markets, bridge = load_inputs(paths["markets"], paths["bridge"], archetype_path)
        boundaries = core.load_boundaries(paths["boundaries"])
        update_checkpoint(
            checkpoint_path, "preflight", "complete",
            expected_rows=EXPECTED_OUTPUT_ROWS,
            free_bytes=shutil.disk_usage(building_path.parent).free,
            building_database=str(building_path), final_database=str(final_path),
        )

        events, scan_evidence = core.collect_events(
            paths["manifest"], manifest, boundaries, {row["market_id"] for row in markets}
        )
        require(len(events) == core.EXPECTED_ROWS, "Full accepted market population does not equal Phase 2 rows")
        update_checkpoint(checkpoint_path, "source_scan", "complete", source_scan=scan_evidence)

        plan, plan_sha = build_checkpoint_plan(
            Path(args.checkpoint_plan).resolve(), EXPECTED_MANIFEST_SHA256,
            EXPECTED_MARKETS_SHA256, EXPECTED_BRIDGE_SHA256,
            events, [row["market_id"] for row in markets],
        )
        checkpoints, rpc_evidence = fetch_rpc_checkpoints(args, plan, plan_sha)
        update_checkpoint(
            checkpoint_path, "rpc_evidence", "complete",
            checkpoint_plan_sha256=plan_sha,
            rpc_cache_audit=rpc_evidence["cache_audit"],
            rpc_session_metrics=rpc_evidence["archive_session_metrics"],
        )

        load_started = time.perf_counter()
        resumed_loaded_database = building_path.exists()
        if resumed_loaded_database:
            connection, resume_mode = resume_loaded_database(building_path)
        else:
            connection = initialize_database(
                building_path, EXPECTED_MANIFEST_SHA256, EXPECTED_BOUNDARIES_SHA256,
                EXPECTED_MARKETS_SHA256, EXPECTED_BRIDGE_SHA256,
                markets, bridge, boundaries, events, checkpoints,
            )
            resume_mode = "database_loaded"
        load_seconds = time.perf_counter() - load_started
        del events
        gc.collect()
        require(database_working_bytes(building_path) <= MAX_DATABASE_BYTES, "10 GiB gate exceeded during input load")
        update_checkpoint(
            checkpoint_path, "database_loaded", "complete",
            load_seconds=round(load_seconds, 6),
            resumed_loaded_database=resumed_loaded_database,
            resume_mode=resume_mode,
            database_working_bytes=database_working_bytes(building_path),
        )

        size_gate = {"exceeded": False, "observed": 0}
        def progress_gate() -> int:
            observed = database_working_bytes(building_path)
            size_gate["observed"] = max(size_gate["observed"], observed)
            if observed > MAX_DATABASE_BYTES:
                size_gate["exceeded"] = True
                return 1
            return 0
        connection.set_progress_handler(progress_gate, 100_000)
        sql_started = time.perf_counter()
        if resume_mode == "database_loaded":
            connection.executescript(paths["core_sql"].read_text(encoding="utf-8-sig"))
            connection.executescript(paths["production_sql"].read_text(encoding="utf-8-sig"))
            connection.executescript(paths["core_qa_sql"].read_text(encoding="utf-8-sig"))
        phase4_schema_sha = load_phase4_reference(connection, paths["prototype_db"])
        connection.executescript(paths["production_qa_sql"].read_text(encoding="utf-8-sig"))
        connection.commit()
        sql_seconds = time.perf_counter() - sql_started
        connection.set_progress_handler(None, 0)
        require(not size_gate["exceeded"], "10 GiB gate exceeded during SQL replay")

        core_qa = core.dict_rows(connection.execute("SELECT * FROM qa_result ORDER BY check_name"))
        phase6_qa = core.dict_rows(connection.execute("SELECT * FROM phase6_qa_result ORDER BY check_name"))
        blocking_failures = [row for row in core_qa if int(row["blocking"]) == 1 and row["status"] != "PASS"]
        blocking_failures += [row for row in phase6_qa if row["status"] != "PASS"]
        require(not blocking_failures, f"Blocking population QA failures: {blocking_failures}")
        output_rows = int(connection.execute("SELECT COUNT(*) FROM market_day_full").fetchone()[0])
        require(output_rows == EXPECTED_OUTPUT_ROWS, "Unexpected production market-day rows")
        checkpoint_rows = core.dict_rows(connection.execute(
            "SELECT * FROM checkpoint_reconciliation ORDER BY market_id, block_number"
        ))
        require(all(int(row["totals_match"]) == 1 for row in checkpoint_rows), "RPC checkpoint mismatch")
        family_rows = core.dict_rows(connection.execute(
            "SELECT * FROM event_family_reconciliation ORDER BY market_id, event_family"
        ))
        flow_rows = core.dict_rows(connection.execute(
            "SELECT * FROM event_flow_reconciliation ORDER BY market_id, measure"
        ))
        coverage = coverage_rows(connection)
        sample = core.deterministic_sample(connection)
        rounding = dict(connection.execute(
            "SELECT rounding_status, COUNT(*) FROM market_event_state GROUP BY rounding_status"
        ).fetchall())
        fee_nonzero = int(connection.execute(
            "SELECT COUNT(*) FROM source_event WHERE event_family='AccrueInterest' AND u_is_nonzero(fee_shares)=1"
        ).fetchone()[0])
        bad_debt_nonzero = int(connection.execute(
            "SELECT COUNT(*) FROM source_event WHERE event_family='Liquidate' AND (u_is_nonzero(bad_debt_assets)=1 OR u_is_nonzero(bad_debt_shares)=1)"
        ).fetchone()[0])
        prototype_defects = int(connection.execute(
            "SELECT defect_count FROM phase6_qa_result WHERE check_name='prototype_three_markets_exact_match'"
        ).fetchone()[0])
        foreign_key_defects = len(connection.execute("PRAGMA foreign_key_check").fetchall())
        require(foreign_key_defects == 0, "SQLite foreign-key defects")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        require(integrity == "ok", f"SQLite integrity_check failed: {integrity}")
        connection.close()
        connection = None

        database_bytes = building_path.stat().st_size
        require(database_bytes <= MAX_DATABASE_BYTES, "Final database exceeds 10 GiB gate")
        require(sha256_file(paths["metrics"]) == EXPECTED_METRICS_SHA256, "Frozen metrics changed during build")
        final_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(building_path, final_path)
        final_sha = sha256_file(final_path)
        final_free = shutil.disk_usage(final_path.parent).free

        atomic_csv(Path(args.sample_output).resolve(), sample)
        atomic_csv(Path(args.coverage_output).resolve(), coverage)
        qa = {
            "version": SCRIPT_VERSION,
            "status": "pass",
            "acceptance_status": "awaiting_user_acceptance",
            "completed_at_utc": utc_now(),
            "sql_engine": f"SQLite {sqlite3.sqlite_version} through Python stdlib sqlite3",
            "scope": {
                "market_count": EXPECTED_MARKETS,
                "utc_bucket_count": EXPECTED_DAYS,
                "market_day_rows": output_rows,
                "grain": "market_id x UTC day",
                "window_start_utc": "2025-07-09T13:00:00Z",
                "window_end_exclusive_utc": "2026-08-18T00:00:00Z",
                "ordering": ["block_number", "transaction_index", "log_index"],
            },
            "input_fingerprints": {
                "phase2_manifest_sha256": EXPECTED_MANIFEST_SHA256,
                "markets_sha256": EXPECTED_MARKETS_SHA256,
                "eligibility_bridge_sha256": EXPECTED_BRIDGE_SHA256,
                "utc_boundaries_sha256": EXPECTED_BOUNDARIES_SHA256,
                "frozen_metrics_v1_sha256": EXPECTED_METRICS_SHA256,
                "prototype_database_sha256_at_comparison": sha256_file(paths["prototype_db"]),
                "prototype_market_day_schema_sha256": phase4_schema_sha,
            },
            "sql_files": {
                "replay_module": str(paths["core_sql"]),
                "replay_module_sha256": sha256_file(paths["core_sql"]),
                "production": str(paths["production_sql"]),
                "production_sha256": sha256_file(paths["production_sql"]),
                "replay_qa_module": str(paths["core_qa_sql"]),
                "replay_qa_module_sha256": sha256_file(paths["core_qa_sql"]),
                "population_qa": str(paths["production_qa_sql"]),
                "population_qa_sha256": sha256_file(paths["production_qa_sql"]),
            },
            "source_scan": scan_evidence,
            "rpc_evidence": {
                "selection_rule": plan["selection_rule"],
                "sample_markets": plan["sample_markets"],
                "checkpoint_count": len(checkpoint_rows),
                "matching_checkpoints": sum(int(row["totals_match"]) for row in checkpoint_rows),
                "plan_sha256": plan_sha,
                "evidence_path": str(Path(args.checkpoint_evidence).resolve()),
                "cache_audit": rpc_evidence["cache_audit"],
                "archive_session_metrics": rpc_evidence["archive_session_metrics"],
                "transport_metrics": rpc_evidence["rpc_transport_metrics"],
            },
            "qa_checks": {
                "replay": core_qa,
                "population": phase6_qa,
                "blocking_failures": 0,
                "sqlite_integrity_check": integrity,
                "foreign_key_defects": foreign_key_defects,
                "prototype_comparison_defects": prototype_defects,
            },
            "event_reconciliation": {
                "family_rows": len(family_rows),
                "family_mismatches": sum(1 for row in family_rows if int(row["counts_match"]) != 1),
                "flow_rows": len(flow_rows),
                "flow_mismatches": sum(1 for row in flow_rows if int(row["values_match"]) != 1),
            },
            "rounding_status_counts": rounding,
            "rare_branch_coverage": {
                "nonzero_fee_shares_events": fee_nonzero,
                "nonzero_bad_debt_events": bad_debt_nonzero,
                "fee_shares_status": "empirically_covered" if fee_nonzero else "implemented_not_empirically_exercised",
                "bad_debt_status": "empirically_covered" if bad_debt_nonzero else "implemented_not_empirically_exercised",
            },
            "runtime_and_storage": {
                "input_load_seconds": round(load_seconds, 6),
                "sql_and_qa_seconds": round(sql_seconds, 6),
                "total_elapsed_seconds": round(time.perf_counter() - started, 6),
                "database_bytes": database_bytes,
                "database_gib": round(database_bytes / 1024**3, 6),
                "maximum_observed_working_database_bytes": size_gate["observed"],
                "gate_bytes": MAX_DATABASE_BYTES,
                "within_10_gib_gate": database_bytes <= MAX_DATABASE_BYTES,
                "free_bytes_after_publish": final_free,
                "gba_bytes_billed": 0,
                "new_eth_getLogs_calls": 0,
            },
            "artifacts": {
                "published_database_ignored": str(final_path),
                "published_database_sha256": final_sha,
                "sample_csv": str(Path(args.sample_output).resolve()),
                "sample_rows": len(sample),
                "coverage_csv": str(Path(args.coverage_output).resolve()),
                "coverage_rows": len(coverage),
            },
            "limitations": [
                "The first UTC bucket is partial because the immutable interval starts at 2025-07-09T13:00:00Z.",
                "Aggregate collateral has no Morpho market-level RPC getter; it is replayed from verified zero anchors and all collateral/seizure deltas.",
                "Independent RPC evidence is bounded: all 45 anchors plus start/mid/end for five precommitted hash-ranked markets.",
                "Shared campaign budgets remain campaign-level pools and the 505K direct-vault budget is not attributed to underlying markets.",
                "This state layer does not yet calculate retained uplift, wallet cohorts, reward receipt or DRIP causality.",
            ],
        }
        atomic_json(Path(args.qa_output).resolve(), qa)
        update_checkpoint(
            checkpoint_path, "published", "complete",
            final_database=str(final_path), final_database_sha256=final_sha,
            qa_output=str(Path(args.qa_output).resolve()),
            market_day_rows=output_rows, database_bytes=database_bytes,
        )
        print(json.dumps({
            "status": "pass",
            "acceptance_status": "awaiting_user_acceptance",
            "markets": EXPECTED_MARKETS,
            "market_day_rows": output_rows,
            "source_events": scan_evidence["selected_event_rows"],
            "rpc_matches": f"{sum(int(row['totals_match']) for row in checkpoint_rows)}/{len(checkpoint_rows)}",
            "prototype_defects": prototype_defects,
            "blocking_qa_failures": 0,
            "database_bytes": database_bytes,
            "total_elapsed_seconds": qa["runtime_and_storage"]["total_elapsed_seconds"],
            "qa_output": str(Path(args.qa_output).resolve()),
        }, indent=2))
        return 0
    except BaseException as exc:
        if connection is not None:
            try:
                connection.commit()
                connection.close()
            except Exception:
                pass
        update_checkpoint(
            checkpoint_path, "blocked", "failed",
            error_type=type(exc).__name__, error=str(exc),
            traceback=traceback.format_exc(),
            building_database=str(building_path),
            building_database_bytes=database_working_bytes(building_path),
            final_database_exists=final_path.exists(),
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
