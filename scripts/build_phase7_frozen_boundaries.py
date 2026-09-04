#!/usr/bin/env python3
"""Build the exact 13:00 UTC block-boundary map required by metrics v1.0.

This is a bounded block-header lookup only. It never calls eth_getLogs, never
queries GBA, and opens the accepted Phase 6 production database read-only.
Validated block headers are cached in a separate SQLite/WAL database before a
search checkpoint is advanced. Published CSV/JSON/QA outputs are bound by an
immutable manifest and are never overwritten with differing content.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


VERSION = "morpho-phase7-frozen-boundaries-v1"
EXPECTED_CHAIN_ID = 42161
RPC_METHOD = "eth_getBlockByNumber"
DEFAULT_RPC_URL = "https://arb1.arbitrum.io/rpc"
DEFAULT_USER_AGENT = "Morpho-DRIP-phase7-boundaries/1.0"

EXPECTED_PRODUCTION_SHA256 = "80aca74cc5e43db03fd93c69d7ad448ac9afdec5f9566a6b833ec11f7e5c9543"
EXPECTED_METRICS_SHA256 = "2774c0856ca66da4611523289a7e1c4da937ce208cad9799c2f008753eca2ba2"
EXPECTED_BRIDGE_SHA256 = "cbab02426bcd1ac1ad0679156f837e155c5b04e86b63001a9149b0cbae27d305"

BASELINE_START = "2025-07-09T13:00:00Z"
CAMPAIGN_START = "2025-09-03T13:00:00Z"
CAMPAIGN_END = "2026-02-18T13:00:00Z"
POST_CHECKPOINTS = {
    "p30": "2026-03-20T13:00:00Z",
    "p90": "2026-05-19T13:00:00Z",
    "p180": "2026-08-17T13:00:00Z",
}

HEX_32_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")


class BoundaryError(RuntimeError):
    """Fail-closed boundary construction error."""


class IntentionalStop(BoundaryError):
    """Raised after a completed search round for a resume test."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise BoundaryError(f"Naive timestamp is not allowed: {value}")
    return parsed.astimezone(timezone.utc)


def format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def pretty_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    with part.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(part, path)


def immutable_write(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.read_bytes() != payload:
            raise BoundaryError(f"Refusing to overwrite differing immutable artifact: {path}")
        return
    atomic_write(path, payload)


def chunks(values: list[int], size: int) -> Iterable[list[int]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def target_population() -> list[dict[str, Any]]:
    roles_by_timestamp: dict[str, list[str]] = {}

    def add(target: datetime, role: str) -> None:
        key = format_utc(target)
        roles_by_timestamp.setdefault(key, []).append(role)

    baseline_start = parse_utc(BASELINE_START)
    campaign_start = parse_utc(CAMPAIGN_START)
    campaign_end = parse_utc(CAMPAIGN_END)

    for index in range(1, 57):
        add(baseline_start + timedelta(days=index), f"baseline_close_{index:02d}")
    for index in range(0, 169):
        add(campaign_start + timedelta(days=index), f"campaign_snapshot_{index:03d}")
    for name, value in POST_CHECKPOINTS.items():
        add(parse_utc(value), name)

    if campaign_start + timedelta(days=168) != campaign_end:
        raise BoundaryError("Campaign duration no longer equals 168 days")

    rows: list[dict[str, Any]] = []
    for ordinal, target_text in enumerate(sorted(roles_by_timestamp, key=parse_utc)):
        target = parse_utc(target_text)
        rows.append(
            {
                "ordinal": ordinal,
                "target_timestamp_utc": target_text,
                "target_timestamp_unix": int(target.timestamp()),
                "roles": roles_by_timestamp[target_text],
            }
        )

    if len(rows) != 227:
        raise BoundaryError(f"Expected 227 distinct timestamps, found {len(rows)}")
    if sum(len(row["roles"]) for row in rows) != 228:
        raise BoundaryError("Expected 228 timestamp roles including the shared campaign-start endpoint")
    if rows[0]["target_timestamp_utc"] != "2025-07-10T13:00:00Z":
        raise BoundaryError("Unexpected first frozen timestamp")
    if rows[-1]["target_timestamp_utc"] != POST_CHECKPOINTS["p180"]:
        raise BoundaryError("Unexpected final frozen timestamp")
    return rows


def read_production_boundaries(path: Path) -> tuple[list[dict[str, Any]], str]:
    uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
        if integrity != "ok":
            raise BoundaryError(f"Production SQLite quick_check failed: {integrity}")
        rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT day_ordinal, day_utc, day_start_utc, day_end_exclusive_utc,
                       start_block, end_block_exclusive
                FROM day_boundary
                ORDER BY day_ordinal
                """
            )
        ]
        if len(rows) != 405:
            raise BoundaryError(f"Production day_boundary count changed: {len(rows)}")
        if connection.execute("SELECT COUNT(*) FROM market_day_full").fetchone()[0] != 18_225:
            raise BoundaryError("Production market_day_full row count changed")
    finally:
        connection.close()
    return rows, sha256_bytes(canonical_json_bytes(rows))


def attach_brackets(
    targets: list[dict[str, Any]], day_boundaries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for target in targets:
        target_unix = int(target["target_timestamp_unix"])
        matches = [
            row
            for row in day_boundaries
            if int(parse_utc(str(row["day_start_utc"])).timestamp()) <= target_unix
            < int(parse_utc(str(row["day_end_exclusive_utc"])).timestamp())
        ]
        if len(matches) != 1:
            raise BoundaryError(
                f"Expected one production-day bracket for {target['target_timestamp_utc']}, found {len(matches)}"
            )
        bracket = matches[0]
        output.append(
            {
                **target,
                "day_ordinal": int(bracket["day_ordinal"]),
                "day_utc": str(bracket["day_utc"]),
                "bracket_start_utc": str(bracket["day_start_utc"]),
                "bracket_end_exclusive_utc": str(bracket["day_end_exclusive_utc"]),
                "bracket_low_block": int(bracket["start_block"]),
                "bracket_high_block": int(bracket["end_block_exclusive"]),
            }
        )
    return output


@dataclass(frozen=True)
class BlockHeader:
    block_number: int
    block_hash: str
    parent_hash: str
    timestamp: int
    result_sha256: str


def validate_block_result(result: object, requested_block: int) -> BlockHeader:
    if not isinstance(result, dict):
        raise BoundaryError(f"Block {requested_block} result is not an object")
    number_hex = result.get("number")
    timestamp_hex = result.get("timestamp")
    block_hash = result.get("hash")
    parent_hash = result.get("parentHash")
    if not isinstance(number_hex, str) or not number_hex.startswith("0x"):
        raise BoundaryError(f"Block {requested_block} has malformed number")
    if int(number_hex, 16) != requested_block:
        raise BoundaryError(f"RPC returned block {int(number_hex, 16)} for request {requested_block}")
    if not isinstance(timestamp_hex, str) or not timestamp_hex.startswith("0x"):
        raise BoundaryError(f"Block {requested_block} has malformed timestamp")
    timestamp = int(timestamp_hex, 16)
    if timestamp < 0:
        raise BoundaryError(f"Block {requested_block} has negative timestamp")
    if not isinstance(block_hash, str) or not HEX_32_RE.fullmatch(block_hash):
        raise BoundaryError(f"Block {requested_block} has malformed hash")
    if not isinstance(parent_hash, str) or not HEX_32_RE.fullmatch(parent_hash):
        raise BoundaryError(f"Block {requested_block} has malformed parent hash")
    return BlockHeader(
        block_number=requested_block,
        block_hash=block_hash.lower(),
        parent_hash=parent_hash.lower(),
        timestamp=timestamp,
        result_sha256=sha256_bytes(canonical_json_bytes(result)),
    )


class BoundaryCache:
    def __init__(self, path: Path, identity: dict[str, Any], targets: list[dict[str, Any]]) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=60, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._create_schema()
        self._bind_identity(identity, targets)

    def close(self) -> None:
        self.connection.close()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            ) WITHOUT ROWID;

            CREATE TABLE IF NOT EXISTS target (
              ordinal INTEGER PRIMARY KEY,
              target_timestamp_utc TEXT NOT NULL UNIQUE,
              target_timestamp_unix INTEGER NOT NULL UNIQUE,
              roles_json TEXT NOT NULL,
              day_ordinal INTEGER NOT NULL,
              day_utc TEXT NOT NULL,
              bracket_start_utc TEXT NOT NULL,
              bracket_end_exclusive_utc TEXT NOT NULL,
              bracket_low_block INTEGER NOT NULL,
              bracket_high_block INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS block_response (
              chain_id INTEGER NOT NULL,
              rpc_method TEXT NOT NULL,
              block_number INTEGER NOT NULL,
              block_hash TEXT NOT NULL,
              parent_hash TEXT NOT NULL,
              block_timestamp INTEGER NOT NULL,
              result_sha256 TEXT NOT NULL,
              valid INTEGER NOT NULL CHECK(valid = 1),
              received_at_utc TEXT NOT NULL,
              PRIMARY KEY(chain_id, rpc_method, block_number)
            ) WITHOUT ROWID;

            CREATE TABLE IF NOT EXISTS search_state (
              ordinal INTEGER PRIMARY KEY REFERENCES target(ordinal),
              low_block INTEGER NOT NULL,
              high_block INTEGER NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('pending_bracket_validation','searching','complete')),
              search_rounds INTEGER NOT NULL DEFAULT 0,
              chosen_block INTEGER,
              predecessor_block INTEGER,
              updated_at_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS checkpoint (
              singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
              completed_targets INTEGER NOT NULL,
              global_round INTEGER NOT NULL,
              status TEXT NOT NULL,
              updated_at_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS rpc_attempt (
              attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
              rpc_method TEXT NOT NULL,
              rpc_item_count INTEGER NOT NULL,
              attempt_index INTEGER NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('success','error')),
              http_status INTEGER,
              response_bytes INTEGER NOT NULL,
              error_class TEXT,
              created_at_utc TEXT NOT NULL
            );
            """
        )

    def _bind_identity(self, identity: dict[str, Any], targets: list[dict[str, Any]]) -> None:
        identity_json = canonical_json_bytes(identity).decode("utf-8")
        existing = self.connection.execute("SELECT value FROM meta WHERE key='identity_json'").fetchone()
        if existing is not None:
            if str(existing[0]) != identity_json:
                raise BoundaryError("Cache identity mismatch; refusing resume")
            saved = [dict(row) for row in self.connection.execute("SELECT * FROM target ORDER BY ordinal")]
            expected = [
                {
                    "ordinal": row["ordinal"],
                    "target_timestamp_utc": row["target_timestamp_utc"],
                    "target_timestamp_unix": row["target_timestamp_unix"],
                    "roles_json": canonical_json_bytes(row["roles"]).decode("utf-8"),
                    "day_ordinal": row["day_ordinal"],
                    "day_utc": row["day_utc"],
                    "bracket_start_utc": row["bracket_start_utc"],
                    "bracket_end_exclusive_utc": row["bracket_end_exclusive_utc"],
                    "bracket_low_block": row["bracket_low_block"],
                    "bracket_high_block": row["bracket_high_block"],
                }
                for row in targets
            ]
            if saved != expected:
                raise BoundaryError("Cached target population differs from the frozen timestamp population")
            return

        created = utc_now()
        with self.connection:
            self.connection.executemany(
                "INSERT INTO meta(key,value) VALUES (?,?)",
                [
                    ("identity_json", identity_json),
                    ("identity_sha256", sha256_bytes(identity_json.encode("utf-8"))),
                    ("created_at_utc", created),
                    ("sealed", "0"),
                ],
            )
            self.connection.executemany(
                """
                INSERT INTO target VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        row["ordinal"], row["target_timestamp_utc"], row["target_timestamp_unix"],
                        canonical_json_bytes(row["roles"]).decode("utf-8"), row["day_ordinal"], row["day_utc"],
                        row["bracket_start_utc"], row["bracket_end_exclusive_utc"],
                        row["bracket_low_block"], row["bracket_high_block"],
                    )
                    for row in targets
                ],
            )
            self.connection.executemany(
                "INSERT INTO search_state VALUES (?,?,?,?,?,?,?,?)",
                [
                    (
                        row["ordinal"], row["bracket_low_block"], row["bracket_high_block"],
                        "pending_bracket_validation", 0, None, None, created,
                    )
                    for row in targets
                ],
            )
            self.connection.execute(
                "INSERT INTO checkpoint VALUES (1,0,0,'initialized',?)", (created,)
            )

    def record_attempt(
        self,
        method: str,
        item_count: int,
        attempt_index: int,
        status: str,
        response_bytes: int,
        http_status: int | None = None,
        error_class: str | None = None,
    ) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO rpc_attempt(
                  rpc_method,rpc_item_count,attempt_index,status,http_status,
                  response_bytes,error_class,created_at_utc
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (method, item_count, attempt_index, status, http_status, response_bytes, error_class, utc_now()),
            )

    def load_blocks(self, block_numbers: Iterable[int]) -> dict[int, BlockHeader]:
        numbers = list(dict.fromkeys(int(value) for value in block_numbers))
        if not numbers:
            return {}
        output: dict[int, BlockHeader] = {}
        for block_chunk in chunks(numbers, 500):
            placeholders = ",".join("?" for _ in block_chunk)
            rows = self.connection.execute(
                f"""
                SELECT block_number,block_hash,parent_hash,block_timestamp,result_sha256
                FROM block_response
                WHERE chain_id=? AND rpc_method=? AND block_number IN ({placeholders})
                """,
                [EXPECTED_CHAIN_ID, RPC_METHOD, *block_chunk],
            )
            for row in rows:
                output[int(row["block_number"])] = BlockHeader(
                    block_number=int(row["block_number"]),
                    block_hash=str(row["block_hash"]),
                    parent_hash=str(row["parent_hash"]),
                    timestamp=int(row["block_timestamp"]),
                    result_sha256=str(row["result_sha256"]),
                )
        return output

    def store_blocks(self, headers: Iterable[BlockHeader]) -> None:
        now = utc_now()
        with self.connection:
            for header in headers:
                existing = self.connection.execute(
                    """
                    SELECT block_hash,parent_hash,block_timestamp,result_sha256
                    FROM block_response WHERE chain_id=? AND rpc_method=? AND block_number=?
                    """,
                    (EXPECTED_CHAIN_ID, RPC_METHOD, header.block_number),
                ).fetchone()
                expected = (
                    header.block_hash, header.parent_hash, header.timestamp, header.result_sha256
                )
                if existing is not None:
                    if tuple(existing) != expected:
                        raise BoundaryError(f"Cached block {header.block_number} conflicts with live RPC")
                    continue
                self.connection.execute(
                    "INSERT INTO block_response VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        EXPECTED_CHAIN_ID, RPC_METHOD, header.block_number, header.block_hash,
                        header.parent_hash, header.timestamp, header.result_sha256, 1, now,
                    ),
                )

    def search_rows(self) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                """
                SELECT t.*,s.low_block,s.high_block,s.status,s.search_rounds,
                       s.chosen_block,s.predecessor_block
                FROM target t JOIN search_state s USING(ordinal)
                ORDER BY t.ordinal
                """
            )
        )

    def update_search(self, updates: list[tuple[int, int, int, str, int]]) -> None:
        now = utc_now()
        with self.connection:
            self.connection.executemany(
                """
                UPDATE search_state
                SET low_block=?,high_block=?,status=?,search_rounds=?,updated_at_utc=?
                WHERE ordinal=?
                """,
                [(low, high, status, rounds, now, ordinal) for ordinal, low, high, status, rounds in updates],
            )
            global_round = max((row[4] for row in updates), default=0)
            complete = self.connection.execute(
                "SELECT COUNT(*) FROM search_state WHERE status='complete'"
            ).fetchone()[0]
            self.connection.execute(
                "UPDATE checkpoint SET completed_targets=?,global_round=?,status='searching',updated_at_utc=? WHERE singleton=1",
                (complete, global_round, now),
            )

    def finalize_boundaries(self, chosen: list[tuple[int, int, int]]) -> None:
        now = utc_now()
        with self.connection:
            self.connection.executemany(
                """
                UPDATE search_state
                SET chosen_block=?,predecessor_block=?,status='complete',updated_at_utc=?
                WHERE ordinal=?
                """,
                [(block, predecessor, now, ordinal) for ordinal, block, predecessor in chosen],
            )
            complete = self.connection.execute(
                "SELECT COUNT(*) FROM search_state WHERE status='complete'"
            ).fetchone()[0]
            self.connection.execute(
                "UPDATE checkpoint SET completed_targets=?,status='complete',updated_at_utc=? WHERE singleton=1",
                (complete, now),
            )
            self.connection.execute(
                "INSERT INTO meta(key,value) VALUES ('completed_at_utc',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (now,),
            )

    def seal(self) -> None:
        with self.connection:
            self.connection.execute("UPDATE meta SET value='1' WHERE key='sealed'")
        self.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def meta(self) -> dict[str, str]:
        return {str(row[0]): str(row[1]) for row in self.connection.execute("SELECT key,value FROM meta")}

    def audit(self) -> dict[str, Any]:
        integrity = self.connection.execute("PRAGMA integrity_check").fetchone()[0]
        attempts = self.connection.execute(
            """
            SELECT COUNT(*) AS http_requests,
                   COALESCE(SUM(rpc_item_count),0) AS rpc_items,
                   COALESCE(SUM(response_bytes),0) AS response_bytes,
                   SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS error_attempts
            FROM rpc_attempt
            """
        ).fetchone()
        duplicate_keys = self.connection.execute(
            """
            SELECT COUNT(*) FROM (
              SELECT chain_id,rpc_method,block_number,COUNT(*) AS n
              FROM block_response GROUP BY 1,2,3 HAVING n>1
            )
            """
        ).fetchone()[0]
        return {
            "sqlite_integrity": integrity,
            "target_rows": self.connection.execute("SELECT COUNT(*) FROM target").fetchone()[0],
            "unique_target_timestamps": self.connection.execute(
                "SELECT COUNT(DISTINCT target_timestamp_utc) FROM target"
            ).fetchone()[0],
            "complete_targets": self.connection.execute(
                "SELECT COUNT(*) FROM search_state WHERE status='complete'"
            ).fetchone()[0],
            "cached_block_headers": self.connection.execute("SELECT COUNT(*) FROM block_response").fetchone()[0],
            "invalid_cache_entries": self.connection.execute(
                "SELECT COUNT(*) FROM block_response WHERE valid<>1"
            ).fetchone()[0],
            "duplicate_cache_keys": duplicate_keys,
            "http_requests": int(attempts[0]),
            "rpc_items": int(attempts[1]),
            "response_bytes": int(attempts[2]),
            "error_attempts": int(attempts[3]),
            "checkpoint": dict(self.connection.execute("SELECT * FROM checkpoint WHERE singleton=1").fetchone()),
        }


class RpcClient:
    def __init__(
        self,
        url: str,
        cache: BoundaryCache,
        batch_size: int,
        retries: int,
        min_request_interval: float,
    ) -> None:
        self.url = url
        self.cache = cache
        self.batch_size = batch_size
        self.retries = retries
        self.min_request_interval = min_request_interval
        self.last_request_started = 0.0
        self.session_cache_hits = 0
        self.session_network_blocks = 0

    def _throttle(self) -> None:
        wait = self.min_request_interval - (time.monotonic() - self.last_request_started)
        if wait > 0:
            time.sleep(wait)
        self.last_request_started = time.monotonic()

    def _post(self, payload: object, method: str, item_count: int) -> object:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        last_error = "unknown"
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                request = urllib.request.Request(
                    self.url,
                    data=encoded,
                    headers={"Content-Type": "application/json", "User-Agent": DEFAULT_USER_AGENT},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=60) as response:
                    raw = response.read()
                    http_status = int(getattr(response, "status", 200))
                decoded = json.loads(raw)
                self.cache.record_attempt(method, item_count, attempt, "success", len(raw), http_status)
                return decoded
            except urllib.error.HTTPError as exc:
                last_error = f"HTTPError:{exc.code}"
                self.cache.record_attempt(method, item_count, attempt, "error", 0, int(exc.code), "HTTPError")
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    delay = float(retry_after) if retry_after is not None else min(30.0, 2.0**attempt)
                except ValueError:
                    delay = min(30.0, 2.0**attempt)
            except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, BoundaryError) as exc:
                last_error = type(exc).__name__
                self.cache.record_attempt(method, item_count, attempt, "error", 0, None, type(exc).__name__)
                delay = min(30.0, 2.0**attempt)
            if attempt < self.retries:
                time.sleep(delay)
        raise BoundaryError(f"Unrecoverable {method} RPC failure after {self.retries + 1} attempts: {last_error}")

    def chain_id(self) -> int:
        decoded = self._post(
            {"jsonrpc": "2.0", "id": "chain-id", "method": "eth_chainId", "params": []},
            "eth_chainId",
            1,
        )
        if not isinstance(decoded, dict) or decoded.get("jsonrpc") != "2.0" or decoded.get("id") != "chain-id":
            raise BoundaryError("Malformed eth_chainId JSON-RPC envelope")
        if decoded.get("error") is not None or not isinstance(decoded.get("result"), str):
            raise BoundaryError("eth_chainId did not return a successful hexadecimal result")
        try:
            value = int(decoded["result"], 16)
        except ValueError as exc:
            raise BoundaryError("Malformed eth_chainId result") from exc
        if value != EXPECTED_CHAIN_ID:
            raise BoundaryError(f"Wrong chain ID: expected {EXPECTED_CHAIN_ID}, got {value}")
        return value

    def blocks(self, block_numbers: Iterable[int]) -> dict[int, BlockHeader]:
        numbers = list(dict.fromkeys(int(value) for value in block_numbers))
        cached = self.cache.load_blocks(numbers)
        self.session_cache_hits += len(cached)
        missing = [number for number in numbers if number not in cached]
        for block_chunk in chunks(missing, self.batch_size):
            id_to_block = {f"block-{number}": number for number in block_chunk}
            body = [
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": RPC_METHOD,
                    "params": [hex(number), False],
                }
                for request_id, number in id_to_block.items()
            ]
            decoded = self._post(body, RPC_METHOD, len(body))
            if not isinstance(decoded, list):
                raise BoundaryError("eth_getBlockByNumber batch response is not an array")
            headers: list[BlockHeader] = []
            seen_ids: set[str] = set()
            for item in decoded:
                if not isinstance(item, dict) or item.get("jsonrpc") != "2.0":
                    raise BoundaryError("Malformed block JSON-RPC envelope")
                request_id = item.get("id")
                if not isinstance(request_id, str) or request_id not in id_to_block or request_id in seen_ids:
                    raise BoundaryError("Unexpected or duplicate block response ID")
                seen_ids.add(request_id)
                if item.get("error") is not None or item.get("result") is None:
                    raise BoundaryError(f"Block RPC item failed for {id_to_block[request_id]}")
                headers.append(validate_block_result(item["result"], id_to_block[request_id]))
            if seen_ids != set(id_to_block):
                raise BoundaryError("Block batch response did not cover all request IDs")
            self.cache.store_blocks(headers)
            cached.update({header.block_number: header for header in headers})
            self.session_network_blocks += len(headers)
        return {number: cached[number] for number in numbers}


def write_checkpoint(path: Path, cache: BoundaryCache, identity_sha: str, status: str, **extra: Any) -> None:
    audit = cache.audit()
    value = {
        "version": VERSION,
        "status": status,
        "identity_sha256": identity_sha,
        "updated_at_utc": utc_now(),
        "target_count": audit["target_rows"],
        "complete_targets": audit["complete_targets"],
        "cached_block_headers": audit["cached_block_headers"],
        "checkpoint": audit["checkpoint"],
        **extra,
    }
    atomic_write(path, pretty_json_bytes(value))


def run_search(
    cache: BoundaryCache,
    client: RpcClient | None,
    checkpoint_path: Path,
    identity_sha: str,
    stop_after_round: int | None,
) -> None:
    rows = cache.search_rows()
    pending = [row for row in rows if row["status"] == "pending_bracket_validation"]
    if pending:
        if client is None:
            raise BoundaryError("Offline cache lacks initial bracket headers")
        blocks = [int(row["low_block"]) for row in pending] + [int(row["high_block"]) for row in pending]
        headers = client.blocks(blocks)
        updates: list[tuple[int, int, int, str, int]] = []
        for row in pending:
            target = int(row["target_timestamp_unix"])
            low = int(row["low_block"])
            high = int(row["high_block"])
            if headers[low].timestamp >= target:
                raise BoundaryError(f"Accepted day start is not below target {row['target_timestamp_utc']}")
            if headers[high].timestamp < target:
                raise BoundaryError(f"Accepted next-day boundary is below target {row['target_timestamp_utc']}")
            updates.append((int(row["ordinal"]), low, high, "searching", int(row["search_rounds"])))
        cache.update_search(updates)
        write_checkpoint(checkpoint_path, cache, identity_sha, "searching", stage="brackets_validated")

    while True:
        rows = cache.search_rows()
        unresolved = [row for row in rows if int(row["high_block"]) - int(row["low_block"]) > 1]
        if not unresolved:
            break
        mids = list(
            dict.fromkeys((int(row["low_block"]) + int(row["high_block"])) // 2 for row in unresolved)
        )
        if client is None:
            headers = cache.load_blocks(mids)
            missing = [number for number in mids if number not in headers]
            if missing:
                raise BoundaryError(f"Offline cache lacks {len(missing)} search headers")
        else:
            headers = client.blocks(mids)
        updates = []
        for row in rows:
            low = int(row["low_block"])
            high = int(row["high_block"])
            rounds = int(row["search_rounds"])
            status = str(row["status"])
            if high - low > 1:
                mid = (low + high) // 2
                target = int(row["target_timestamp_unix"])
                if headers[mid].timestamp >= target:
                    high = mid
                else:
                    low = mid
                rounds += 1
                status = "searching"
            updates.append((int(row["ordinal"]), low, high, status, rounds))
        cache.update_search(updates)
        current_round = max(update[4] for update in updates)
        write_checkpoint(
            checkpoint_path,
            cache,
            identity_sha,
            "searching",
            stage="binary_search",
            global_round=current_round,
            unresolved_targets=sum(1 for update in updates if update[2] - update[1] > 1),
        )
        print(
            f"round={current_round} unresolved={sum(1 for update in updates if update[2] - update[1] > 1)} "
            f"cached_headers={cache.audit()['cached_block_headers']}",
            flush=True,
        )
        if stop_after_round is not None and current_round >= stop_after_round:
            raise IntentionalStop(f"Intentional stop after completed search round {current_round}")

    rows = cache.search_rows()
    already_complete = all(str(row["status"]) == "complete" for row in rows)
    chosen_blocks = [
        int(row["chosen_block"]) if row["chosen_block"] is not None else int(row["high_block"])
        for row in rows
    ]
    validation_blocks = list(dict.fromkeys(chosen_blocks + [number - 1 for number in chosen_blocks]))
    if client is None:
        headers = cache.load_blocks(validation_blocks)
        missing = [number for number in validation_blocks if number not in headers]
        if missing:
            raise BoundaryError(f"Offline cache lacks {len(missing)} adjacent validation headers")
    else:
        headers = client.blocks(validation_blocks)
    finalized: list[tuple[int, int, int]] = []
    for row in rows:
        target = int(row["target_timestamp_unix"])
        chosen = int(row["high_block"])
        predecessor = chosen - 1
        previous_header = headers[predecessor]
        chosen_header = headers[chosen]
        if previous_header.timestamp >= target or chosen_header.timestamp < target:
            raise BoundaryError(f"Exact adjacent-block validation failed for {row['target_timestamp_utc']}")
        if chosen_header.parent_hash != previous_header.block_hash:
            raise BoundaryError(f"Parent hash mismatch across blocks {predecessor}/{chosen}")
        finalized.append((int(row["ordinal"]), chosen, predecessor))
    if not already_complete:
        cache.finalize_boundaries(finalized)
        write_checkpoint(checkpoint_path, cache, identity_sha, "complete", stage="adjacent_validation_complete")


def boundary_rows(cache: BoundaryCache) -> list[dict[str, Any]]:
    rows = cache.search_rows()
    chosen_numbers = [int(row["chosen_block"]) for row in rows]
    all_headers = cache.load_blocks(chosen_numbers + [number - 1 for number in chosen_numbers])
    output: list[dict[str, Any]] = []
    for row in rows:
        chosen = all_headers[int(row["chosen_block"])]
        predecessor = all_headers[int(row["predecessor_block"])]
        output.append(
            {
                "ordinal": int(row["ordinal"]),
                "target_timestamp_utc": str(row["target_timestamp_utc"]),
                "target_timestamp_unix": int(row["target_timestamp_unix"]),
                "roles": json.loads(str(row["roles_json"])),
                "day_utc": str(row["day_utc"]),
                "bracket_start_block": int(row["bracket_low_block"]),
                "bracket_end_block_exclusive": int(row["bracket_high_block"]),
                "predecessor_block": predecessor.block_number,
                "predecessor_hash": predecessor.block_hash,
                "predecessor_timestamp_unix": predecessor.timestamp,
                "predecessor_timestamp_utc": format_utc(datetime.fromtimestamp(predecessor.timestamp, tz=timezone.utc)),
                "chosen_block": chosen.block_number,
                "chosen_hash": chosen.block_hash,
                "chosen_timestamp_unix": chosen.timestamp,
                "chosen_timestamp_utc": format_utc(datetime.fromtimestamp(chosen.timestamp, tz=timezone.utc)),
                "chosen_parent_hash": chosen.parent_hash,
                "predecessor_lt_target": predecessor.timestamp < int(row["target_timestamp_unix"]),
                "chosen_gte_target": chosen.timestamp >= int(row["target_timestamp_unix"]),
                "parent_hash_match": chosen.parent_hash == predecessor.block_hash,
                "chosen_minus_target_seconds": chosen.timestamp - int(row["target_timestamp_unix"]),
                "target_minus_predecessor_seconds": int(row["target_timestamp_unix"]) - predecessor.timestamp,
            }
        )
    return output


def csv_payload(rows: list[dict[str, Any]]) -> bytes:
    fields = [
        "ordinal", "target_timestamp_utc", "roles", "day_utc",
        "bracket_start_block", "bracket_end_block_exclusive",
        "predecessor_block", "predecessor_hash", "predecessor_timestamp_utc",
        "chosen_block", "chosen_hash", "chosen_timestamp_utc",
        "predecessor_lt_target", "chosen_gte_target", "parent_hash_match",
        "chosen_minus_target_seconds", "target_minus_predecessor_seconds",
    ]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        projected = {field: row[field] for field in fields}
        projected["roles"] = ";".join(row["roles"])
        writer.writerow(projected)
    return stream.getvalue().encode("utf-8")


def build_qa(
    cache: BoundaryCache,
    rows: list[dict[str, Any]],
    day_boundaries: list[dict[str, Any]],
    identity: dict[str, Any],
) -> dict[str, Any]:
    target_times = [int(row["target_timestamp_unix"]) for row in rows]
    chosen_blocks = [int(row["chosen_block"]) for row in rows]
    day_boundary_by_time = {
        str(day["day_start_utc"]): int(day["start_block"]) for day in day_boundaries
    }
    day_boundary_by_time.update(
        {str(day["day_end_exclusive_utc"]): int(day["end_block_exclusive"]) for day in day_boundaries}
    )
    intersections = [row for row in rows if row["target_timestamp_utc"] in day_boundary_by_time]
    intersection_mismatches = [
        row
        for row in intersections
        if int(row["chosen_block"]) != day_boundary_by_time[row["target_timestamp_utc"]]
    ]
    checks = {
        "target_count": {"observed": len(rows), "expected": 227},
        "unique_target_timestamps": {"observed": len(set(target_times)), "expected": 227},
        "complete_boundaries": {
            "observed": sum(bool(row["predecessor_lt_target"] and row["chosen_gte_target"]) for row in rows),
            "expected": 227,
        },
        "missing_boundaries": {"observed": 227 - len(rows), "expected": 0},
        "duplicate_target_timestamps": {"observed": len(rows) - len(set(target_times)), "expected": 0},
        "non_monotonic_target_timestamps": {
            "observed": sum(right <= left for left, right in zip(target_times, target_times[1:])),
            "expected": 0,
        },
        "non_monotonic_boundary_blocks": {
            "observed": sum(right <= left for left, right in zip(chosen_blocks, chosen_blocks[1:])),
            "expected": 0,
        },
        "predecessor_failures": {
            "observed": sum(not row["predecessor_lt_target"] for row in rows),
            "expected": 0,
        },
        "chosen_block_failures": {
            "observed": sum(not row["chosen_gte_target"] for row in rows),
            "expected": 0,
        },
        "adjacent_block_number_failures": {
            "observed": sum(int(row["predecessor_block"]) + 1 != int(row["chosen_block"]) for row in rows),
            "expected": 0,
        },
        "parent_hash_failures": {
            "observed": sum(not row["parent_hash_match"] for row in rows),
            "expected": 0,
        },
        "accepted_day_bracket_failures": {
            "observed": sum(
                not (
                    int(row["bracket_start_block"]) <= int(row["chosen_block"])
                    < int(row["bracket_end_block_exclusive"])
                )
                for row in rows
            ),
            "expected": 0,
        },
        "phase2_phase6_exact_timestamp_intersections": {
            "observed": len(intersections),
            "expected": len(intersections),
        },
        "phase2_phase6_intersection_mismatches": {
            "observed": len(intersection_mismatches),
            "expected": 0,
        },
    }
    failed = [name for name, check in checks.items() if check["observed"] != check["expected"]]
    cache_audit = cache.audit()
    cache_failures = []
    if cache_audit["sqlite_integrity"] != "ok":
        cache_failures.append("sqlite_integrity")
    if cache_audit["target_rows"] != 227 or cache_audit["complete_targets"] != 227:
        cache_failures.append("cache_target_completeness")
    if cache_audit["invalid_cache_entries"] != 0 or cache_audit["duplicate_cache_keys"] != 0:
        cache_failures.append("cache_entry_integrity")

    return {
        "version": VERSION,
        "status": "PASS" if not failed and not cache_failures else "FAIL",
        "generated_at_utc": cache.meta().get("completed_at_utc"),
        "definition": "chosen_block is the minimum block whose timestamp is greater than or equal to target_timestamp",
        "identity": identity,
        "checks": checks,
        "failed_checks": failed,
        "cache_failed_checks": cache_failures,
        "cache_audit": cache_audit,
        "timestamp_span": {
            "first": rows[0]["target_timestamp_utc"],
            "last": rows[-1]["target_timestamp_utc"],
        },
        "boundary_block_span": {"first": chosen_blocks[0], "last": chosen_blocks[-1]},
        "timestamp_overshoot_seconds": {
            "min": min(int(row["chosen_minus_target_seconds"]) for row in rows),
            "max": max(int(row["chosen_minus_target_seconds"]) for row in rows),
        },
        "predecessor_gap_seconds": {
            "min": min(int(row["target_minus_predecessor_seconds"]) for row in rows),
            "max": max(int(row["target_minus_predecessor_seconds"]) for row in rows),
        },
        "accepted_boundary_reconciliation": {
            "exact_timestamp_intersections": len(intersections),
            "intersection_mismatches": len(intersection_mismatches),
            "all_targets_inside_accepted_day_brackets": checks["accepted_day_bracket_failures"]["observed"] == 0,
            "note": "The frozen 13:00 timestamps do not coincide with the accepted midnight boundary rows; all 227 are reconciled to their accepted Phase 6 day brackets.",
        },
        "network_scope": {
            "allowed_methods": ["eth_chainId", RPC_METHOD],
            "eth_getlogs_calls": 0,
            "gba_queries": 0,
        },
    }


def published_manifest_valid(manifest_path: Path, identity: dict[str, Any], workspace: Path) -> bool:
    if not manifest_path.exists():
        return False
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "complete" or manifest.get("identity") != identity:
        raise BoundaryError("Existing immutable manifest identity/status mismatch")
    for item in manifest.get("artifacts", []):
        path = workspace / str(item["path"])
        if not path.is_file() or sha256_file(path) != item["sha256"]:
            raise BoundaryError(f"Published artifact fingerprint mismatch: {item['path']}")
    cache_item = manifest.get("cache", {})
    cache_path = workspace / str(cache_item.get("path", ""))
    if not cache_path.is_file() or sha256_file(cache_path) != cache_item.get("sha256"):
        raise BoundaryError("Published boundary cache fingerprint mismatch")
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--rpc-url", default=os.environ.get("ARBITRUM_RPC_URL", DEFAULT_RPC_URL))
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--retries", type=int, default=6)
    parser.add_argument("--rate-limit-seconds", type=float, default=0.5)
    parser.add_argument("--offline-only", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--stop-after-round", type=int)
    parser.add_argument("--production-db", default="data/tmp/morpho_market_day_full_v1.sqlite")
    parser.add_argument("--metrics", default="docs/METRICS.md")
    parser.add_argument("--bridge", default="data/drip_morpho_eligibility_bridge.csv")
    parser.add_argument("--cache", default="data/tmp/morpho_phase7_boundary_cache_v1.sqlite")
    parser.add_argument("--checkpoint", default="data/morpho_phase7_boundary_checkpoint.json")
    parser.add_argument("--map-csv", default="data/morpho_phase7_boundary_map.csv")
    parser.add_argument("--map-json", default="data/morpho_phase7_boundary_map.json")
    parser.add_argument("--qa", default="data/morpho_phase7_boundary_qa.json")
    parser.add_argument("--manifest", default="data/morpho_phase7_boundary_manifest.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = args.workspace.resolve()
    script_path = Path(__file__).resolve()
    production_path = (workspace / args.production_db).resolve()
    metrics_path = (workspace / args.metrics).resolve()
    bridge_path = (workspace / args.bridge).resolve()
    cache_path = (workspace / args.cache).resolve()
    checkpoint_path = (workspace / args.checkpoint).resolve()
    csv_path = (workspace / args.map_csv).resolve()
    json_path = (workspace / args.map_json).resolve()
    qa_path = (workspace / args.qa).resolve()
    manifest_path = (workspace / args.manifest).resolve()

    required = [production_path, metrics_path, bridge_path]
    if any(not path.is_file() for path in required):
        raise BoundaryError("One or more required accepted inputs are missing")

    production_sha = sha256_file(production_path)
    metrics_sha = sha256_file(metrics_path)
    bridge_sha = sha256_file(bridge_path)
    if production_sha != EXPECTED_PRODUCTION_SHA256:
        raise BoundaryError("Accepted Phase 6 production database fingerprint mismatch")
    if metrics_sha != EXPECTED_METRICS_SHA256:
        raise BoundaryError("Frozen metrics v1.0 fingerprint mismatch")
    if bridge_sha != EXPECTED_BRIDGE_SHA256:
        raise BoundaryError("Accepted eligibility bridge fingerprint mismatch")

    targets = target_population()
    day_boundaries, day_boundary_sha = read_production_boundaries(production_path)
    targets = attach_brackets(targets, day_boundaries)
    target_identity_rows = [
        {
            "ordinal": row["ordinal"],
            "target_timestamp_utc": row["target_timestamp_utc"],
            "target_timestamp_unix": row["target_timestamp_unix"],
            "roles": row["roles"],
        }
        for row in targets
    ]
    timestamp_list_sha = sha256_bytes(canonical_json_bytes(target_identity_rows))
    identity = {
        "version": VERSION,
        "chain_id": EXPECTED_CHAIN_ID,
        "rpc_method": RPC_METHOD,
        "boundary_rule": "minimum block_number where block.timestamp >= target_timestamp",
        "timestamp_count": 227,
        "timestamp_list_sha256": timestamp_list_sha,
        "script_sha256": sha256_file(script_path),
        "production_db_sha256": production_sha,
        "frozen_metrics_sha256": metrics_sha,
        "eligibility_bridge_sha256": bridge_sha,
        "production_day_boundary_sha256": day_boundary_sha,
    }
    identity_sha = sha256_bytes(canonical_json_bytes(identity))

    if args.plan_only:
        print(
            json.dumps(
                {
                    "status": "plan_only",
                    "timestamp_count": len(targets),
                    "role_count": sum(len(row["roles"]) for row in targets),
                    "first": targets[0]["target_timestamp_utc"],
                    "last": targets[-1]["target_timestamp_utc"],
                    "timestamp_list_sha256": timestamp_list_sha,
                    "identity_sha256": identity_sha,
                },
                indent=2,
            )
        )
        return 0

    if published_manifest_valid(manifest_path, identity, workspace):
        print(json.dumps({"status": "complete", "manifest": str(manifest_path)}, indent=2))
        return 0

    cache = BoundaryCache(cache_path, identity, targets)
    client: RpcClient | None = None
    started = time.monotonic()
    try:
        if not args.offline_only and cache.meta().get("sealed") != "1":
            client = RpcClient(
                args.rpc_url,
                cache,
                batch_size=args.batch_size,
                retries=args.retries,
                min_request_interval=args.rate_limit_seconds,
            )
            client.chain_id()
        run_search(cache, client, checkpoint_path, identity_sha, args.stop_after_round)
        rows = boundary_rows(cache)
        qa = build_qa(cache, rows, day_boundaries, identity)
        if qa["status"] != "PASS":
            raise BoundaryError(f"Boundary QA failed: {qa['failed_checks']} {qa['cache_failed_checks']}")
        if cache.meta().get("sealed") != "1":
            cache.seal()
        cache_meta = cache.meta()
        completed_at = cache_meta["completed_at_utc"]

        map_json = {
            "version": VERSION,
            "status": "complete",
            "generated_at_utc": completed_at,
            "chain_id": EXPECTED_CHAIN_ID,
            "rpc_method": RPC_METHOD,
            "boundary_rule": identity["boundary_rule"],
            "timestamp_count": len(rows),
            "timestamp_list_sha256": timestamp_list_sha,
            "boundaries": rows,
        }
        csv_bytes = csv_payload(rows)
        json_bytes = pretty_json_bytes(map_json)
        qa_bytes = pretty_json_bytes(qa)
        immutable_write(csv_path, csv_bytes)
        immutable_write(json_path, json_bytes)
        immutable_write(qa_path, qa_bytes)

        artifacts = []
        for path in [csv_path, json_path, qa_path]:
            artifacts.append(
                {
                    "path": path.relative_to(workspace).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
        cache.close()
        cache = None  # type: ignore[assignment]
        cache_sha = sha256_file(cache_path)
        manifest = {
            "version": VERSION,
            "status": "complete",
            "created_at_utc": cache_meta["created_at_utc"],
            "completed_at_utc": completed_at,
            "identity": identity,
            "identity_sha256": identity_sha,
            "cache": {
                "path": cache_path.relative_to(workspace).as_posix(),
                "sha256": cache_sha,
                "journal_mode": "WAL",
                "sealed": True,
            },
            "timestamp_population": {
                "distinct_timestamps": 227,
                "roles": 228,
                "first": rows[0]["target_timestamp_utc"],
                "last": rows[-1]["target_timestamp_utc"],
                "sha256": timestamp_list_sha,
            },
            "rpc_scope": {
                "allowed_methods": ["eth_chainId", RPC_METHOD],
                "eth_getlogs_calls": 0,
                "gba_queries": 0,
                "endpoint_profile": "official Arbitrum One public RPC or user-supplied equivalent; URL is not persisted",
                "rate_limit_seconds": args.rate_limit_seconds,
                "batch_size": args.batch_size,
                "configured_retries": args.retries,
            },
            "qa_status": "PASS",
            "artifacts": artifacts,
        }
        immutable_write(manifest_path, pretty_json_bytes(manifest))
        atomic_write(
            checkpoint_path,
            pretty_json_bytes(
                {
                    "version": VERSION,
                    "status": "complete",
                    "identity_sha256": identity_sha,
                    "updated_at_utc": completed_at,
                    "target_count": 227,
                    "complete_targets": 227,
                    "manifest_sha256": sha256_file(manifest_path),
                }
            ),
        )
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "boundaries": 227,
                    "first_block": rows[0]["chosen_block"],
                    "last_block": rows[-1]["chosen_block"],
                    "cached_block_headers": qa["cache_audit"]["cached_block_headers"],
                    "http_requests": qa["cache_audit"]["http_requests"],
                    "rpc_items": qa["cache_audit"]["rpc_items"],
                    "error_attempts": qa["cache_audit"]["error_attempts"],
                    "session_cache_hits": client.session_cache_hits if client else 0,
                    "session_network_blocks": client.session_network_blocks if client else 0,
                    "elapsed_seconds": round(time.monotonic() - started, 6),
                    "manifest": str(manifest_path),
                },
                indent=2,
            ),
            flush=True,
        )
        return 0
    except IntentionalStop as exc:
        write_checkpoint(checkpoint_path, cache, identity_sha, "intentional_stop", error=str(exc))
        print(str(exc), flush=True)
        return 75
    except Exception as exc:
        write_checkpoint(
            checkpoint_path,
            cache,
            identity_sha,
            "blocked",
            error_class=type(exc).__name__,
            error=str(exc),
        )
        raise
    finally:
        if cache is not None:
            cache.close()


if __name__ == "__main__":
    raise SystemExit(main())
