#!/usr/bin/env python3
"""Build and QA the bounded Phase 4 three-market Morpho daily-state prototype.

The runner reads only the immutable Phase 2 RPC shards.  It never calls
eth_getLogs, never queries GBA, and never opens the sealed Phase 3 selection
SQLite.  Historical market checkpoints use a separate identity-bound SQLite/WAL
cache.  The two SQL files are executed by Python's stdlib SQLite 3 engine with
registered exact-bigint functions because protocol uint128 values can exceed
SQLite's signed INT64 range.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import os
import platform
import sqlite3
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from morpho_archive_rpc_cache import ArchiveRpcCache, CachedArchiveSession, EXPECTED_CHAIN_ID
from reconstruct_morpho_one_position import (
    EXPECTED_DATA_WORDS,
    EXPECTED_TOPIC_COUNTS,
    decode_event,
    to_assets_down,
    to_assets_up,
    to_shares_down,
    to_shares_up,
)
from select_morpho_one_position import (
    EVENTS,
    FEE_RECIPIENT_SELECTOR,
    MARKET_SELECTOR,
    MORPHO_ADDRESS,
    POSITION_SELECTOR,
    RpcClient,
    archive_market_call,
    decode_words,
    validate_live_chain,
)


SCRIPT_VERSION = "morpho-phase4-three-market-daily-v1"
CACHE_VERSION = "morpho-phase4-market-checkpoints-v1"
EXPECTED_MANIFEST_SHA256 = "c8552428187094e5aad725193f2e3023e622ddc4ab37428f1414c375e7d6be58"
EXPECTED_START_BLOCK = 355_887_376
EXPECTED_END_BLOCK_EXCLUSIVE = 495_647_034
EXPECTED_ROWS = 1_231_462
EXPECTED_SHARDS = 3_157
EXPECTED_DAYS = 405
EXPECTED_MARKETS = (
    "0xd09404e9512e1341321c8ae3bd663fab7087582142ac61486635a6c072c2af12",
    "0xf86f3edd6f16cd8211f4d206866dc4ecd41be6211063ac11f8508e1b7112ef40",
    "0x571cb3ac535d61d92026c071ef1df4794d0bbbe1755f916ff640746f81b52af4",
)
NUMERIC_FIELDS = (
    "assets",
    "shares",
    "interest",
    "fee_shares",
    "repaid_assets",
    "repaid_shares",
    "seized_assets",
    "bad_debt_assets",
    "bad_debt_shares",
)


class PrototypeError(RuntimeError):
    """Fail-closed evidence, accounting, RPC or QA error."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="data/raw/morpho_full_window/manifest.json")
    parser.add_argument("--boundaries", default="data/raw/morpho_full_window/day_boundaries.json")
    parser.add_argument("--archetypes", default="data/morpho_phase4_market_archetypes.csv")
    parser.add_argument("--sql-build", default="sql/10_market_day_prototype.sql")
    parser.add_argument("--sql-qa", default="sql/90_qa_market_day_prototype.sql")
    parser.add_argument("--checkpoint-plan", default="data/morpho_phase4_rpc_checkpoint_plan.json")
    parser.add_argument("--checkpoint-evidence", default="data/morpho_phase4_rpc_checkpoint_evidence.json")
    parser.add_argument("--rpc-cache", default="data/tmp/morpho_phase4_market_day_rpc.sqlite")
    parser.add_argument("--database", default="data/tmp/morpho_phase4_market_day_prototype.sqlite")
    parser.add_argument("--sample-output", default="data/market_day_prototype_sample.csv")
    parser.add_argument("--qa-output", default="data/morpho_market_day_prototype_qa.json")
    parser.add_argument("--rpc-url", default="https://arbitrum-one.public.blastapi.io")
    parser.add_argument("--offline-only", action="store_true")
    parser.add_argument("--retries", type=int, default=8)
    parser.add_argument("--min-request-interval", type=float, default=0.75)
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PrototypeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="")
    os.replace(part, path)


def atomic_write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    require(bool(rows), f"Refusing to write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    with part.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(part, path)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    require(isinstance(value, dict), f"Expected JSON object: {path}")
    return value


def load_archetypes(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    require(len(rows) == 3, "Archetype CSV must contain exactly three rows")
    ids = tuple(row["market_id"].lower() for row in rows)
    require(set(ids) == set(EXPECTED_MARKETS), "Archetype market IDs differ from the frozen set")
    require(len(set(ids)) == 3, "Duplicate frozen market ID")
    for row in rows:
        row["market_id"] = row["market_id"].lower()
    return rows


def load_boundaries(path: Path) -> list[dict[str, Any]]:
    document = load_json(path)
    values = document.get("boundaries")
    require(isinstance(values, list) and len(values) == EXPECTED_DAYS + 1, "Unexpected UTC boundary count")
    boundaries: list[dict[str, Any]] = []
    for index, row in enumerate(values):
        require(isinstance(row, dict), "Malformed UTC boundary row")
        timestamp = str(row["boundary_utc"])
        block = int(row["block_number"])
        if index:
            require(block > int(values[index - 1]["block_number"]), "UTC boundary blocks are not increasing")
            require(timestamp > str(values[index - 1]["boundary_utc"]), "UTC boundaries are not increasing")
        boundaries.append({"boundary_utc": timestamp, "block_number": block})
    require(boundaries[0] == {"boundary_utc": "2025-07-09T13:00:00Z", "block_number": EXPECTED_START_BLOCK}, "Wrong first UTC boundary")
    require(boundaries[-1] == {"boundary_utc": "2026-08-18T00:00:00Z", "block_number": EXPECTED_END_BLOCK_EXCLUSIVE}, "Wrong final UTC boundary")
    return boundaries


def manifest_shard_path(manifest_path: Path, file_value: str) -> Path:
    filename = Path(file_value).name
    candidates = (manifest_path.parent / "shards" / filename, manifest_path.parent / filename)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise PrototypeError(f"Manifest shard missing: {file_value}")


def collect_events(
    manifest_path: Path,
    manifest: dict[str, Any],
    boundaries: list[dict[str, Any]],
    markets: set[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = time.perf_counter()
    start_blocks = [int(row["block_number"]) for row in boundaries]
    selected: list[dict[str, Any]] = []
    source_rows = 0
    source_bytes = 0
    selected_jsonl_bytes = 0
    checksum_defects = 0
    row_count_defects = 0
    removed_rows = 0
    scope_defects = 0
    malformed_rows = 0
    previous_order: tuple[int, int, int] | None = None
    source_ordering_defects = 0
    selected_keys: set[tuple[int, str, int]] = set()
    duplicate_selected_keys = 0

    shards = manifest.get("shards")
    require(isinstance(shards, list) and len(shards) == EXPECTED_SHARDS, "Unexpected manifest shard population")
    for shard_index, entry in enumerate(shards, start=1):
        require(entry.get("status") == "verified", f"Unverified shard in manifest: {entry.get('file')}")
        shard_path = manifest_shard_path(manifest_path, str(entry["file"]))
        digest = hashlib.sha256()
        shard_rows = 0
        with shard_path.open("rb") as handle:
            for raw_line in handle:
                digest.update(raw_line)
                source_bytes += len(raw_line)
                if not raw_line.strip():
                    continue
                shard_rows += 1
                source_rows += 1
                try:
                    row = json.loads(raw_line)
                    order = (int(row["block_number"]), int(row["transaction_index"]), int(row["log_index"]))
                    if previous_order is not None and order <= previous_order:
                        source_ordering_defects += 1
                    previous_order = order
                    if bool(row.get("removed", False)):
                        removed_rows += 1
                    if str(row.get("address", "")).lower() != MORPHO_ADDRESS:
                        scope_defects += 1
                    topics = json.loads(str(row["topics_json"]))
                    if not isinstance(topics, list) or len(topics) < 2:
                        malformed_rows += 1
                        continue
                    market_id = str(topics[1]).lower()
                    if market_id not in markets:
                        continue
                    event = decode_event(row, market_id)
                    require(event is not None, "Selected market decoder unexpectedly returned None")
                    require(len(topics) == EXPECTED_TOPIC_COUNTS[event["family"]], "Unexpected selected-event topic count")
                    require(len(str(row["data"])[2:]) == EXPECTED_DATA_WORDS[event["family"]] * 64, "Unexpected selected-event data length")
                    block = int(event["block_number"])
                    day_index = bisect.bisect_right(start_blocks, block) - 1
                    require(0 <= day_index < EXPECTED_DAYS, f"Selected event outside UTC buckets: {block}")
                    require(block < start_blocks[day_index + 1], "UTC day assignment crossed boundary")
                    event["day_ordinal"] = day_index
                    event["day_utc"] = str(boundaries[day_index]["boundary_utc"])[:10]
                    key = (block, str(event["transaction_hash"]), int(event["log_index"]))
                    if key in selected_keys:
                        duplicate_selected_keys += 1
                    selected_keys.add(key)
                    selected.append(event)
                    selected_jsonl_bytes += len(raw_line)
                except PrototypeError:
                    raise
                except Exception as exc:
                    raise PrototypeError(f"Malformed raw row in {shard_path.name}: {exc}") from exc
        if shard_rows != int(entry["row_count"]):
            row_count_defects += 1
        if digest.hexdigest() != str(entry["checksum_sha256"]).lower():
            checksum_defects += 1
        if shard_index % 500 == 0:
            print(f"scan_progress shards={shard_index} rows={source_rows} selected={len(selected)}", flush=True)

    expected_source_bytes = sum(int(entry["file_bytes"]) for entry in shards)
    require(source_rows == EXPECTED_ROWS, f"Scanned source rows {source_rows} != {EXPECTED_ROWS}")
    require(source_bytes == expected_source_bytes, "Scanned source bytes differ from manifest shard sum")
    defects = checksum_defects + row_count_defects + removed_rows + scope_defects + malformed_rows + source_ordering_defects + duplicate_selected_keys
    require(defects == 0, f"Immutable source QA failed with {defects} defects")

    selected.sort(key=lambda event: (event["market_id"], event["block_number"], event["transaction_index"], event["log_index"]))
    per_market_sequence: Counter[str] = Counter()
    family_counts: dict[str, Counter[str]] = {market: Counter() for market in markets}
    for event in selected:
        market_id = str(event["market_id"])
        per_market_sequence[market_id] += 1
        event["event_sequence"] = per_market_sequence[market_id]
        family_counts[market_id][str(event["family"])] += 1
    require(all(per_market_sequence[market] > 0 for market in markets), "At least one frozen market has no scoped events")

    evidence = {
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "verified_shards": len(shards),
        "source_rows_scanned": source_rows,
        "source_bytes_scanned": source_bytes,
        "selected_raw_jsonl_bytes": selected_jsonl_bytes,
        "selected_event_rows": len(selected),
        "selected_event_counts_by_market": dict(sorted(per_market_sequence.items())),
        "selected_event_family_counts": {
            market: dict(sorted(counts.items())) for market, counts in sorted(family_counts.items())
        },
        "checksum_defects": checksum_defects,
        "row_count_defects": row_count_defects,
        "removed_rows": removed_rows,
        "scope_defects": scope_defects,
        "malformed_rows": malformed_rows,
        "source_ordering_defects": source_ordering_defects,
        "duplicate_selected_keys": duplicate_selected_keys,
    }
    return selected, evidence


def build_checkpoint_plan(
    path: Path,
    manifest_sha: str,
    archetypes_sha: str,
    events: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    by_market: dict[str, list[dict[str, Any]]] = {market: [] for market in EXPECTED_MARKETS}
    for event in events:
        by_market[str(event["market_id"])].append(event)
    checkpoints: list[dict[str, Any]] = []
    for market in EXPECTED_MARKETS:
        rows = by_market[market]
        require(bool(rows), f"No events for checkpoint plan: {market}")
        median_event = rows[(len(rows) - 1) // 2]
        market_points = (
            ("anchor", EXPECTED_START_BLOCK - 1, "end-of-block state immediately before the allowed replay interval"),
            ("start", int(rows[0]["block_number"]), "end of the first scoped-event block"),
            ("mid", int(median_event["block_number"]), "end of the block containing lower-median ordered event"),
            ("end", EXPECTED_END_BLOCK_EXCLUSIVE - 1, "end of the final block in the allowed replay interval"),
        )
        require(len({point[1] for point in market_points}) == 4, f"Checkpoint blocks are not distinct for {market}")
        for name, block, rationale in market_points:
            checkpoints.append({
                "ordinal": len(checkpoints),
                "market_id": market,
                "checkpoint_name": name,
                "block_number": block,
                "rationale": rationale,
            })
    planned = {
        "version": SCRIPT_VERSION,
        "status": "precommitted_before_rpc",
        "created_at_utc": utc_now(),
        "chain_id": EXPECTED_CHAIN_ID,
        "contract_address": MORPHO_ADDRESS,
        "manifest_sha256": manifest_sha,
        "archetype_csv_sha256": archetypes_sha,
        "selection_rule": "anchor; first scoped-event block; lower-median ordered-event block; final allowed block",
        "ordering": ["block_number", "transaction_index", "log_index"],
        "checkpoints": checkpoints,
    }
    if path.exists():
        existing = load_json(path)
        comparable_keys = (
            "version", "chain_id", "contract_address", "manifest_sha256",
            "archetype_csv_sha256", "selection_rule", "ordering", "checkpoints",
        )
        for key in comparable_keys:
            require(existing.get(key) == planned.get(key), f"Existing checkpoint plan mismatch: {key}")
        plan = existing
    else:
        atomic_write_json(path, planned)
        plan = planned
    return plan, sha256_file(path)


def fetch_rpc_checkpoints(
    args: argparse.Namespace,
    plan: dict[str, Any],
    plan_sha: str,
    manifest_sha: str,
    archetypes_sha: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    identity = {
        "cache_version": CACHE_VERSION,
        "chain_id": EXPECTED_CHAIN_ID,
        "contract_address": MORPHO_ADDRESS,
        "manifest_sha256": manifest_sha,
        "archetype_csv_sha256": archetypes_sha,
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
        cache_path,
        identity,
        MORPHO_ADDRESS,
        POSITION_SELECTOR,
        MARKET_SELECTOR,
        FEE_RECIPIENT_SELECTOR,
    )
    client: RpcClient | None = None
    results: list[dict[str, Any]] = []
    try:
        if args.offline_only:
            def cache_miss(_method: str, _params: list[Any]) -> Any:
                raise PrototypeError("Phase 4 RPC cache miss in --offline-only mode")
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
            results.append({
                "market_id": str(row["market_id"]),
                "checkpoint_name": str(row["checkpoint_name"]),
                "block_number": int(row["block_number"]),
                "total_supply_assets": str(words[0]),
                "total_supply_shares": str(words[1]),
                "total_borrow_assets": str(words[2]),
                "total_borrow_shares": str(words[3]),
                "last_update": words[4],
                "fee": str(words[5]),
                "cache_key_sha256": call.key_sha256(EXPECTED_CHAIN_ID, MORPHO_ADDRESS),
                "result_sha256": hashlib.sha256(result_hex.encode("ascii")).hexdigest(),
            })
        audit = cache.audit()
        session_metrics = session.metrics()
    finally:
        cache.close()
    require(audit["sqlite_integrity"] == "ok", "Phase 4 RPC cache integrity failed")
    require(audit["invalid_entries"] == 0, "Invalid Phase 4 RPC cache entries")
    require(audit["duplicate_key_groups"] == 0, "Duplicate Phase 4 RPC cache keys")
    require(audit["progress_gaps"] == 0 and audit["orphan_progress_rows"] == 0, "Phase 4 RPC checkpoint defects")
    require(len(results) == 12 and audit["cache_entries"] == 12, "Expected exactly 12 bounded market RPC calls")
    for row in results:
        if row["checkpoint_name"] == "anchor":
            require(
                row["total_supply_assets"] == "0"
                and row["total_supply_shares"] == "0"
                and row["total_borrow_assets"] == "0"
                and row["total_borrow_shares"] == "0"
                and int(row["last_update"]) == 0,
                f"Anchor is not an uninitialized zero market: {row['market_id']}",
            )
    evidence = {
        "version": CACHE_VERSION,
        "status": "validated",
        "created_at_utc": utc_now(),
        "chain_id": EXPECTED_CHAIN_ID,
        "contract_address": MORPHO_ADDRESS,
        "manifest_sha256": manifest_sha,
        "archetype_csv_sha256": archetypes_sha,
        "checkpoint_plan_sha256": plan_sha,
        "cache_path": str(cache_path),
        "cache_audit": audit,
        "archive_session_metrics": session_metrics,
        "rpc_transport_metrics": dict(client.metrics) if client is not None else {"offline_only": 1},
        "checkpoints": results,
    }
    atomic_write_json(Path(args.checkpoint_evidence).resolve(), evidence)
    return results, evidence


def unsigned(value: Any) -> int:
    if value is None or value == "":
        return 0
    text = str(value)
    if not text.isdigit():
        raise ValueError(f"Not an unsigned decimal integer: {value!r}")
    return int(text)


def uadd(left: Any, right: Any) -> str:
    return str(unsigned(left) + unsigned(right))


def usub(left: Any, right: Any) -> str:
    result = unsigned(left) - unsigned(right)
    if result < 0:
        raise ValueError(f"Unexplained negative balance: {left} - {right}")
    return str(result)


def usub_floor(left: Any, right: Any) -> str:
    return str(max(0, unsigned(left) - unsigned(right)))


def uvalid(value: Any) -> int:
    return int(value is not None and str(value).isdigit())


def u_is_nonzero(value: Any) -> int:
    return int(unsigned(value) != 0)


class UnsignedSum:
    def __init__(self) -> None:
        self.total = 0

    def step(self, value: Any) -> None:
        if value is not None and value != "":
            self.total += unsigned(value)

    def finalize(self) -> str:
        return str(self.total)


def event_rounding_status(
    family: str,
    assets: Any,
    shares: Any,
    repaid_assets: Any,
    repaid_shares: Any,
    total_supply_assets: Any,
    total_supply_shares: Any,
    total_borrow_assets: Any,
    total_borrow_shares: Any,
) -> str:
    if family not in {"Supply", "Withdraw", "Borrow", "Repay", "Liquidate"}:
        return "not_applicable"
    supply_assets = unsigned(total_supply_assets)
    supply_shares = unsigned(total_supply_shares)
    borrow_assets = unsigned(total_borrow_assets)
    borrow_shares = unsigned(total_borrow_shares)
    if family == "Liquidate":
        expected = to_assets_up(unsigned(repaid_shares), borrow_assets, borrow_shares)
        return "pass" if expected == unsigned(repaid_assets) else "fail"
    event_assets = unsigned(assets)
    event_shares = unsigned(shares)
    if family in {"Supply", "Withdraw"}:
        total_assets, total_shares = supply_assets, supply_shares
    else:
        total_assets, total_shares = borrow_assets, borrow_shares
    if family in {"Supply", "Repay"}:
        ok = (
            event_shares == to_shares_down(event_assets, total_assets, total_shares)
            or event_assets == to_assets_up(event_shares, total_assets, total_shares)
        )
    else:
        ok = (
            event_shares == to_shares_up(event_assets, total_assets, total_shares)
            or event_assets == to_assets_down(event_shares, total_assets, total_shares)
        )
    return "pass" if ok else "fail"


def register_exact_functions(connection: sqlite3.Connection) -> None:
    connection.create_function("uadd", 2, uadd, deterministic=True)
    connection.create_function("usub", 2, usub, deterministic=True)
    connection.create_function("usub_floor", 2, usub_floor, deterministic=True)
    connection.create_function("uvalid", 1, uvalid, deterministic=True)
    connection.create_function("u_is_nonzero", 1, u_is_nonzero, deterministic=True)
    connection.create_function("event_rounding_status", 9, event_rounding_status, deterministic=True)
    connection.create_aggregate("u_sum", 1, UnsignedSum)


def initialize_database(
    path: Path,
    manifest_sha: str,
    archetypes_sha: str,
    boundaries_sha: str,
    archetypes: list[dict[str, str]],
    boundaries: list[dict[str, Any]],
    events: list[dict[str, Any]],
    checkpoints: list[dict[str, Any]],
) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            candidate.unlink()
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA temp_store=FILE")
    connection.execute("PRAGMA foreign_keys=ON")
    register_exact_functions(connection)
    connection.executescript(
        """
        CREATE TABLE prototype_config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE market_dim (
          archetype TEXT NOT NULL,
          market_id TEXT PRIMARY KEY,
          loan_symbol TEXT NOT NULL,
          loan_address TEXT NOT NULL,
          collateral_symbol TEXT NOT NULL,
          collateral_address TEXT NOT NULL,
          first_scoped_event_block INTEGER NOT NULL,
          data_start_utc_day TEXT NOT NULL
        );
        CREATE TABLE day_boundary (
          day_ordinal INTEGER PRIMARY KEY,
          day_utc TEXT NOT NULL,
          day_start_utc TEXT NOT NULL,
          day_end_exclusive_utc TEXT NOT NULL,
          start_block INTEGER NOT NULL,
          end_block_exclusive INTEGER NOT NULL
        );
        CREATE TABLE source_event (
          market_id TEXT NOT NULL,
          event_sequence INTEGER NOT NULL,
          day_ordinal INTEGER NOT NULL,
          day_utc TEXT NOT NULL,
          block_number INTEGER NOT NULL,
          transaction_index INTEGER NOT NULL,
          log_index INTEGER NOT NULL,
          transaction_hash TEXT NOT NULL,
          event_family TEXT NOT NULL,
          owner TEXT NOT NULL,
          caller TEXT NOT NULL,
          assets TEXT,
          shares TEXT,
          interest TEXT,
          fee_shares TEXT,
          repaid_assets TEXT,
          repaid_shares TEXT,
          seized_assets TEXT,
          bad_debt_assets TEXT,
          bad_debt_shares TEXT,
          topics_json TEXT NOT NULL,
          data TEXT NOT NULL,
          PRIMARY KEY (market_id, event_sequence),
          UNIQUE (block_number, transaction_hash, log_index)
        ) WITHOUT ROWID;
        CREATE INDEX source_event_block_ix ON source_event (market_id, block_number, event_sequence);
        CREATE INDEX source_event_day_ix ON source_event (market_id, day_utc);
        CREATE TABLE rpc_checkpoint (
          market_id TEXT NOT NULL,
          checkpoint_name TEXT NOT NULL,
          block_number INTEGER NOT NULL,
          total_supply_assets TEXT NOT NULL,
          total_supply_shares TEXT NOT NULL,
          total_borrow_assets TEXT NOT NULL,
          total_borrow_shares TEXT NOT NULL,
          last_update INTEGER NOT NULL,
          fee TEXT NOT NULL,
          cache_key_sha256 TEXT NOT NULL,
          result_sha256 TEXT NOT NULL,
          PRIMARY KEY (market_id, checkpoint_name)
        ) WITHOUT ROWID;
        """
    )
    config = {
        "script_version": SCRIPT_VERSION,
        "sql_engine": f"SQLite {sqlite3.sqlite_version} via Python {platform.python_version()}",
        "manifest_sha256": manifest_sha,
        "archetype_csv_sha256": archetypes_sha,
        "boundary_json_sha256": boundaries_sha,
        "window_start_utc": "2025-07-09T13:00:00Z",
        "window_end_exclusive_utc": "2026-08-18T00:00:00Z",
        "ordering": "block_number, transaction_index, log_index",
        "numeric_storage": "unsigned decimal TEXT with exact Python bigint SQLite UDFs",
    }
    connection.executemany("INSERT INTO prototype_config VALUES (?, ?)", config.items())
    connection.executemany(
        "INSERT INTO market_dim VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                row["archetype"], row["market_id"], row["loan_symbol"], row["loan_address"].lower(),
                row["collateral_symbol"], row["collateral_address"].lower(),
                int(row["first_scoped_event_block"]), row["data_start_utc_day"],
            )
            for row in archetypes
        ],
    )
    connection.executemany(
        "INSERT INTO day_boundary VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                index,
                str(boundaries[index]["boundary_utc"])[:10],
                boundaries[index]["boundary_utc"],
                boundaries[index + 1]["boundary_utc"],
                int(boundaries[index]["block_number"]),
                int(boundaries[index + 1]["block_number"]),
            )
            for index in range(EXPECTED_DAYS)
        ],
    )
    event_columns = (
        "market_id", "event_sequence", "day_ordinal", "day_utc", "block_number",
        "transaction_index", "log_index", "transaction_hash", "family", "owner", "caller",
        *NUMERIC_FIELDS, "topics_json", "data",
    )
    placeholders = ",".join("?" for _ in event_columns)
    connection.executemany(
        f"INSERT INTO source_event VALUES ({placeholders})",
        [tuple(None if event.get(column) is None else str(event.get(column)) if column in NUMERIC_FIELDS else event.get(column) for column in event_columns) for event in events],
    )
    connection.executemany(
        "INSERT INTO rpc_checkpoint VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                row["market_id"], row["checkpoint_name"], row["block_number"],
                row["total_supply_assets"], row["total_supply_shares"],
                row["total_borrow_assets"], row["total_borrow_shares"],
                row["last_update"], row["fee"], row["cache_key_sha256"], row["result_sha256"],
            )
            for row in checkpoints
        ],
    )
    connection.commit()
    return connection


def dict_rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(row) for row in cursor.fetchall()]


def deterministic_sample(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    sample_days: set[tuple[str, str]] = set()
    markets = [str(row[0]) for row in connection.execute("SELECT market_id FROM market_dim ORDER BY archetype")]
    for market in markets:
        day_rows = connection.execute(
            "SELECT day_utc, status, total_event_count FROM market_day WHERE market_id=? ORDER BY day_ordinal",
            (market,),
        ).fetchall()
        active_index = next(index for index, row in enumerate(day_rows) if row["status"] == "active")
        indices = {0, max(0, active_index - 1), active_index, len(day_rows) // 2, len(day_rows) - 1}
        for index in indices:
            sample_days.add((market, str(day_rows[index]["day_utc"])))
    rows: list[dict[str, Any]] = []
    for market, day in sorted(sample_days):
        row = connection.execute("SELECT * FROM market_day WHERE market_id=? AND day_utc=?", (market, day)).fetchone()
        require(row is not None, "Deterministic sample row missing")
        rows.append(dict(row))
    return rows


def projected_cost(
    scan: dict[str, Any],
    sql_seconds: float,
    database_bytes: int,
    output_rows: int,
) -> dict[str, Any]:
    selected_events = int(scan["selected_event_rows"])
    full_events = EXPECTED_ROWS
    event_ratio = full_events / selected_events
    full_rows = 45 * EXPECTED_DAYS
    row_ratio = full_rows / output_rows
    projected_sql_seconds = sql_seconds * event_ratio * 1.25
    projected_db_bytes = int(database_bytes * max(event_ratio, row_ratio) * 1.25)
    source_gib = int(scan["source_bytes_scanned"]) / (1024**3)
    projected_gib = projected_db_bytes / (1024**3)
    projected_working_set_gib = source_gib + projected_gib
    return {
        "method": "one-pass source scan remains constant; replay/storage scale by exact 45-market Phase 2 event population with 25% headroom",
        "prototype_selected_events": selected_events,
        "known_full_45_market_events": full_events,
        "event_scale_factor": round(event_ratio, 6),
        "prototype_market_day_rows": output_rows,
        "full_45_market_day_rows": full_rows,
        "row_scale_factor": round(row_ratio, 6),
        "prototype_sql_seconds": round(sql_seconds, 6),
        "projected_full_sql_seconds_with_25pct_headroom": round(projected_sql_seconds, 3),
        "prototype_database_bytes": database_bytes,
        "projected_full_database_bytes_with_25pct_headroom": projected_db_bytes,
        "projected_full_database_gib": round(projected_gib, 6),
        "projected_full_working_set_gib_including_existing_source": round(projected_working_set_gib, 6),
        "source_bytes_read_one_pass": int(scan["source_bytes_scanned"]),
        "source_gib_read_one_pass": round(source_gib, 6),
        "gba_bytes_billed": 0,
        "within_8_to_10_gib_cost_gate": projected_working_set_gib < 10,
        "caveat": "Runtime is an engineering projection from local replay throughput, not a billed BigQuery dry run; the exact all-market raw event count is already known from Phase 2.",
    }


def main() -> int:
    args = parse_args()
    started = time.perf_counter()
    manifest_path = Path(args.manifest).resolve()
    boundaries_path = Path(args.boundaries).resolve()
    archetypes_path = Path(args.archetypes).resolve()
    sql_build_path = Path(args.sql_build).resolve()
    sql_qa_path = Path(args.sql_qa).resolve()
    manifest = load_json(manifest_path)
    manifest_sha = sha256_file(manifest_path)
    require(manifest_sha == EXPECTED_MANIFEST_SHA256, "Immutable Phase 2 manifest SHA-256 changed")
    require(manifest.get("status") == "complete" and manifest.get("complete") is True, "Phase 2 manifest not complete")
    require(int(manifest["start_block"]) == EXPECTED_START_BLOCK, "Manifest start block changed")
    require(int(manifest["end_block_exclusive"]) == EXPECTED_END_BLOCK_EXCLUSIVE, "Manifest end block changed")
    require(int(manifest["row_count"]) == EXPECTED_ROWS, "Manifest row count changed")
    require(int(manifest["verified_shard_count"]) == EXPECTED_SHARDS, "Manifest shard count changed")
    boundaries = load_boundaries(boundaries_path)
    archetypes = load_archetypes(archetypes_path)
    archetypes_sha = sha256_file(archetypes_path)
    boundaries_sha = sha256_file(boundaries_path)

    events, scan_evidence = collect_events(
        manifest_path, manifest, boundaries, {row["market_id"] for row in archetypes}
    )
    plan, plan_sha = build_checkpoint_plan(
        Path(args.checkpoint_plan).resolve(), manifest_sha, archetypes_sha, events
    )
    checkpoints, rpc_evidence = fetch_rpc_checkpoints(
        args, plan, plan_sha, manifest_sha, archetypes_sha
    )

    database_path = Path(args.database).resolve()
    connection = initialize_database(
        database_path,
        manifest_sha,
        archetypes_sha,
        boundaries_sha,
        archetypes,
        boundaries,
        events,
        checkpoints,
    )
    sql_started = time.perf_counter()
    try:
        connection.executescript(sql_build_path.read_text(encoding="utf-8-sig"))
        connection.executescript(sql_qa_path.read_text(encoding="utf-8-sig"))
        connection.commit()
        sql_seconds = time.perf_counter() - sql_started
        qa_rows = dict_rows(connection.execute("SELECT * FROM qa_result ORDER BY check_name"))
        checkpoint_rows = dict_rows(connection.execute(
            "SELECT * FROM checkpoint_reconciliation ORDER BY market_id, block_number"
        ))
        family_rows = dict_rows(connection.execute(
            "SELECT * FROM event_family_reconciliation ORDER BY market_id, event_family"
        ))
        flow_rows = dict_rows(connection.execute(
            "SELECT * FROM event_flow_reconciliation ORDER BY market_id, measure"
        ))
        output_rows = int(connection.execute("SELECT COUNT(*) FROM market_day").fetchone()[0])
        inactive_rows = int(connection.execute(
            "SELECT COUNT(*) FROM market_day WHERE status='inactive_pre_first_scoped_event'"
        ).fetchone()[0])
        fee_nonzero = int(connection.execute(
            "SELECT COUNT(*) FROM source_event WHERE event_family='AccrueInterest' AND u_is_nonzero(fee_shares)=1"
        ).fetchone()[0])
        bad_debt_nonzero = int(connection.execute(
            "SELECT COUNT(*) FROM source_event WHERE event_family='Liquidate' AND (u_is_nonzero(bad_debt_assets)=1 OR u_is_nonzero(bad_debt_shares)=1)"
        ).fetchone()[0])
        rounding = dict(connection.execute(
            "SELECT rounding_status, COUNT(*) FROM market_event_state GROUP BY rounding_status"
        ).fetchall())
        sample_rows = deterministic_sample(connection)
        blocking_failures = [row for row in qa_rows if int(row["blocking"]) == 1 and row["status"] != "PASS"]
        require(not blocking_failures, f"Blocking Phase 4 QA failures: {blocking_failures}")
        require(all(int(row["totals_match"]) == 1 for row in checkpoint_rows), "RPC checkpoint mismatch")
        require(output_rows == 3 * EXPECTED_DAYS, "Unexpected market-day row count")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()

    database_bytes = database_path.stat().st_size
    cost = projected_cost(scan_evidence, sql_seconds, database_bytes, output_rows)
    require(bool(cost["within_8_to_10_gib_cost_gate"]), "Projected 45-market build exceeds cost/storage gate")
    atomic_write_csv(Path(args.sample_output).resolve(), sample_rows)
    qa = {
        "version": SCRIPT_VERSION,
        "status": "pass",
        "completed_at_utc": utc_now(),
        "sql_engine": f"SQLite {sqlite3.sqlite_version} through Python stdlib sqlite3",
        "sql_files": {
            "build": str(sql_build_path),
            "build_sha256": sha256_file(sql_build_path),
            "qa": str(sql_qa_path),
            "qa_sha256": sha256_file(sql_qa_path),
        },
        "scope": {
            "markets": list(EXPECTED_MARKETS),
            "window_start_utc": "2025-07-09T13:00:00Z",
            "window_end_exclusive_utc": "2026-08-18T00:00:00Z",
            "days": EXPECTED_DAYS,
            "market_day_rows": output_rows,
            "grain": "market_id x UTC day",
            "ordering": ["block_number", "transaction_index", "log_index"],
        },
        "source_scan": scan_evidence,
        "rpc_evidence": {
            "checkpoint_plan_sha256": plan_sha,
            "checkpoint_evidence_path": str(Path(args.checkpoint_evidence).resolve()),
            "cache_audit": rpc_evidence["cache_audit"],
            "archive_session_metrics": rpc_evidence["archive_session_metrics"],
            "rpc_transport_metrics": rpc_evidence["rpc_transport_metrics"],
        },
        "qa_checks": qa_rows,
        "checkpoint_reconciliation": checkpoint_rows,
        "event_family_reconciliation": family_rows,
        "event_flow_reconciliation": flow_rows,
        "rounding_status_counts": rounding,
        "inactive_market_day_rows": inactive_rows,
        "rare_branch_coverage": {
            "nonzero_fee_shares_events": fee_nonzero,
            "nonzero_bad_debt_events": bad_debt_nonzero,
            "fee_shares_status": "empirically_covered" if fee_nonzero else "implemented_not_empirically_exercised",
            "bad_debt_status": "empirically_covered" if bad_debt_nonzero else "implemented_not_empirically_exercised",
        },
        "cost_and_storage": cost,
        "artifacts": {
            "database_path_ignored": str(database_path),
            "sample_csv": str(Path(args.sample_output).resolve()),
            "sample_rows": len(sample_rows),
        },
        "total_elapsed_seconds": round(time.perf_counter() - started, 6),
        "limitations": [
            "This bounded prototype proves only the three frozen markets and does not validate the future 45-market output.",
            "The first UTC bucket is partial because the accepted Phase 2 interval begins at 2025-07-09T13:00:00Z.",
            "Aggregate collateral is replayed from a proven uninitialized zero anchor; Morpho has no market-level totalCollateral getter for independent RPC reconciliation.",
            "The local cost projection is not a BigQuery dry run and creates no GBA billable bytes.",
            "This artifact does not calculate retention, uplift, reward receipt, wallet cohorts or DRIP causality.",
        ],
    }
    atomic_write_json(Path(args.qa_output).resolve(), qa)
    print(json.dumps({
        "status": "pass",
        "selected_events": len(events),
        "market_day_rows": output_rows,
        "blocking_qa_failures": 0,
        "rpc_checkpoint_matches": sum(int(row["totals_match"]) for row in checkpoint_rows),
        "rpc_checkpoints": len(checkpoint_rows),
        "nonzero_fee_shares_events": fee_nonzero,
        "nonzero_bad_debt_events": bad_debt_nonzero,
        "database_bytes": database_bytes,
        "projected_full_database_gib": cost["projected_full_database_gib"],
        "qa_output": str(Path(args.qa_output).resolve()),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
