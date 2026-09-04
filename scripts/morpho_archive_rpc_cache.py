#!/usr/bin/env python3
"""Validated, resume-safe SQLite cache for Morpho archive eth_call results."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


CACHE_SCHEMA_VERSION = 1
EXPECTED_CHAIN_ID = 42161
HEX_32_RE = re.compile(r"^0x[0-9a-f]{64}$")
ADDRESS_RE = re.compile(r"^0x[0-9a-f]{40}$")


class CacheIdentityError(RuntimeError):
    """Raised when a cache belongs to a different immutable input or selector."""


class CacheIntegrityError(RuntimeError):
    """Raised when persisted cache/checkpoint evidence fails validation."""


class IntentionalStop(RuntimeError):
    """Raised only after a newly fetched response and its checkpoint are committed."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ArchiveCall:
    rpc_method: str
    abi_method: str
    block_number: int
    market_id: str
    wallet: str
    call_data: str
    expected_words: int

    def key_payload(self, chain_id: int, contract_address: str) -> dict[str, Any]:
        return {
            "chain_id": chain_id,
            "contract_address": contract_address,
            "rpc_method": self.rpc_method,
            "abi_method": self.abi_method,
            "block_number": self.block_number,
            "market_id": self.market_id,
            "wallet": self.wallet,
        }

    def key_sha256(self, chain_id: int, contract_address: str) -> str:
        return sha256_text(canonical_json(self.key_payload(chain_id, contract_address)))

    def request_params(self, contract_address: str) -> list[Any]:
        return [{"to": contract_address, "data": self.call_data}, hex(self.block_number)]

    def validate_request(
        self,
        contract_address: str,
        position_selector: str,
        market_selector: str,
        fee_recipient_selector: str,
    ) -> None:
        if self.rpc_method != "eth_call":
            raise CacheIntegrityError(f"Unsupported archive RPC method: {self.rpc_method}")
        if self.block_number < 0:
            raise CacheIntegrityError(f"Negative block number: {self.block_number}")
        if contract_address != contract_address.lower() or not ADDRESS_RE.fullmatch(contract_address):
            raise CacheIntegrityError(f"Invalid normalized contract address: {contract_address}")
        if self.abi_method == "position":
            if not HEX_32_RE.fullmatch(self.market_id) or not ADDRESS_RE.fullmatch(self.wallet):
                raise CacheIntegrityError("position key requires normalized bytes32 market and address wallet")
            expected_data = "0x" + position_selector + self.market_id[2:] + self.wallet[2:].rjust(64, "0")
            expected_words = 3
        elif self.abi_method == "market":
            if not HEX_32_RE.fullmatch(self.market_id) or self.wallet != "":
                raise CacheIntegrityError("market key requires normalized bytes32 market and empty wallet")
            expected_data = "0x" + market_selector + self.market_id[2:]
            expected_words = 6
        elif self.abi_method == "feeRecipient":
            if self.market_id != "" or self.wallet != "":
                raise CacheIntegrityError("feeRecipient key requires empty market and wallet")
            expected_data = "0x" + fee_recipient_selector
            expected_words = 1
        else:
            raise CacheIntegrityError(f"Unsupported ABI method: {self.abi_method}")
        if self.call_data != expected_data:
            raise CacheIntegrityError(f"Calldata does not match requested ABI method {self.abi_method}")
        if self.expected_words != expected_words:
            raise CacheIntegrityError(f"Unexpected ABI word count for {self.abi_method}")

    def validate_result(self, result: object) -> str:
        if not isinstance(result, str) or not result.startswith("0x"):
            raise CacheIntegrityError(f"{self.abi_method} result is not a hex string")
        normalized = result.lower()
        expected_length = 2 + self.expected_words * 64
        if len(normalized) != expected_length:
            raise CacheIntegrityError(
                f"{self.abi_method} result length {len(normalized)} != expected {expected_length}"
            )
        if any(character not in "0123456789abcdef" for character in normalized[2:]):
            raise CacheIntegrityError(f"{self.abi_method} result contains non-hex characters")
        return normalized


class ArchiveRpcCache:
    def __init__(
        self,
        path: Path,
        identity: dict[str, Any],
        contract_address: str,
        position_selector: str,
        market_selector: str,
        fee_recipient_selector: str,
    ) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.identity = identity
        self.identity_json = canonical_json(identity)
        self.identity_sha256 = sha256_text(self.identity_json)
        self.chain_id = int(identity["chain_id"])
        self.contract_address = contract_address
        self.position_selector = position_selector
        self.market_selector = market_selector
        self.fee_recipient_selector = fee_recipient_selector
        self.connection = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA busy_timeout=30000")
        try:
            self._initialize()
        except Exception:
            self.connection.close()
            raise

    def close(self) -> None:
        self.connection.close()

    def _initialize(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS cache_identity (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                schema_version INTEGER NOT NULL,
                identity_json TEXT NOT NULL,
                identity_sha256 TEXT NOT NULL,
                created_at_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rpc_cache (
                chain_id INTEGER NOT NULL,
                contract_address TEXT NOT NULL,
                rpc_method TEXT NOT NULL,
                abi_method TEXT NOT NULL,
                block_number INTEGER NOT NULL,
                market_id TEXT NOT NULL,
                wallet TEXT NOT NULL,
                call_data TEXT NOT NULL,
                expected_words INTEGER NOT NULL,
                result_hex TEXT NOT NULL,
                key_sha256 TEXT NOT NULL UNIQUE,
                response_sha256 TEXT NOT NULL,
                confirmed_at_utc TEXT NOT NULL,
                PRIMARY KEY (
                    chain_id, contract_address, rpc_method, abi_method,
                    block_number, market_id, wallet
                )
            ) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS progress (
                ordinal INTEGER PRIMARY KEY,
                key_sha256 TEXT NOT NULL,
                confirmed_at_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS checkpoint (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                contiguous_through INTEGER NOT NULL,
                last_key_sha256 TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            );
            """
        )
        row = self.connection.execute("SELECT * FROM cache_identity WHERE singleton = 1").fetchone()
        if row is None:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                self.connection.execute(
                    "INSERT INTO cache_identity VALUES (1, ?, ?, ?, ?)",
                    (CACHE_SCHEMA_VERSION, self.identity_json, self.identity_sha256, utc_now()),
                )
                self.connection.execute(
                    "INSERT INTO checkpoint VALUES (1, -1, '', ?)",
                    (utc_now(),),
                )
                self.connection.execute("COMMIT")
            except Exception:
                self.connection.execute("ROLLBACK")
                raise
        else:
            mismatches: list[str] = []
            if int(row["schema_version"]) != CACHE_SCHEMA_VERSION:
                mismatches.append(
                    f"schema_version cached={row['schema_version']} requested={CACHE_SCHEMA_VERSION}"
                )
            if str(row["identity_sha256"]) != self.identity_sha256:
                try:
                    cached = json.loads(str(row["identity_json"]))
                except json.JSONDecodeError:
                    cached = {"unparseable_identity_json": str(row["identity_json"])}
                keys = sorted(set(cached) | set(self.identity))
                for key in keys:
                    if cached.get(key) != self.identity.get(key):
                        mismatches.append(
                            f"{key}: cached={cached.get(key)!r} requested={self.identity.get(key)!r}"
                        )
            if mismatches:
                raise CacheIdentityError("Archive RPC cache identity mismatch; refuse resume: " + "; ".join(mismatches))

    def _response_sha256(self, call: ArchiveCall, result_hex: str) -> str:
        payload = call.key_payload(self.chain_id, self.contract_address) | {
            "call_data": call.call_data,
            "expected_words": call.expected_words,
            "result_hex": result_hex,
        }
        return sha256_text(canonical_json(payload))

    def _validate_call(self, call: ArchiveCall) -> None:
        call.validate_request(
            self.contract_address,
            self.position_selector,
            self.market_selector,
            self.fee_recipient_selector,
        )

    def get(self, call: ArchiveCall) -> str | None:
        self._validate_call(call)
        row = self.connection.execute(
            """
            SELECT * FROM rpc_cache
            WHERE chain_id=? AND contract_address=? AND rpc_method=? AND abi_method=?
              AND block_number=? AND market_id=? AND wallet=?
            """,
            (
                self.chain_id,
                self.contract_address,
                call.rpc_method,
                call.abi_method,
                call.block_number,
                call.market_id,
                call.wallet,
            ),
        ).fetchone()
        if row is None:
            return None
        if str(row["call_data"]) != call.call_data or int(row["expected_words"]) != call.expected_words:
            raise CacheIntegrityError("Cached request metadata does not match the requested ABI method")
        if str(row["key_sha256"]) != call.key_sha256(self.chain_id, self.contract_address):
            raise CacheIntegrityError("Cached key checksum mismatch")
        result = call.validate_result(str(row["result_hex"]))
        expected_hash = self._response_sha256(call, result)
        if str(row["response_sha256"]) != expected_hash:
            raise CacheIntegrityError("Cached response checksum mismatch")
        return result

    def store(self, call: ArchiveCall, result: object) -> str:
        self._validate_call(call)
        normalized = call.validate_result(result)
        response_sha256 = self._response_sha256(call, normalized)
        key_sha256 = call.key_sha256(self.chain_id, self.contract_address)
        values = (
            self.chain_id,
            self.contract_address,
            call.rpc_method,
            call.abi_method,
            call.block_number,
            call.market_id,
            call.wallet,
            call.call_data,
            call.expected_words,
            normalized,
            key_sha256,
            response_sha256,
            utc_now(),
        )
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute(
                """
                INSERT OR IGNORE INTO rpc_cache (
                    chain_id, contract_address, rpc_method, abi_method, block_number,
                    market_id, wallet, call_data, expected_words, result_hex,
                    key_sha256, response_sha256, confirmed_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        persisted = self.get(call)
        if persisted != normalized:
            raise CacheIntegrityError("Concurrent cache row differs from the validated RPC response")
        return normalized

    def advance_checkpoint(self, ordinal: int, call: ArchiveCall) -> None:
        key_sha256 = call.key_sha256(self.chain_id, self.contract_address)
        if self.get(call) is None:
            raise CacheIntegrityError("Cannot advance checkpoint before a validated cache row exists")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            checkpoint = self.connection.execute(
                "SELECT contiguous_through FROM checkpoint WHERE singleton=1"
            ).fetchone()
            if checkpoint is None:
                raise CacheIntegrityError("Missing checkpoint singleton")
            contiguous = int(checkpoint["contiguous_through"])
            existing = self.connection.execute(
                "SELECT key_sha256 FROM progress WHERE ordinal=?", (ordinal,)
            ).fetchone()
            if ordinal <= contiguous:
                if existing is None or str(existing["key_sha256"]) != key_sha256:
                    raise CacheIntegrityError(f"Checkpoint plan mismatch at ordinal {ordinal}")
                self.connection.execute("COMMIT")
                return
            if ordinal != contiguous + 1:
                raise CacheIntegrityError(
                    f"Checkpoint gap: requested ordinal {ordinal}, contiguous through {contiguous}"
                )
            self.connection.execute(
                "INSERT INTO progress (ordinal, key_sha256, confirmed_at_utc) VALUES (?, ?, ?)",
                (ordinal, key_sha256, utc_now()),
            )
            self.connection.execute(
                "UPDATE checkpoint SET contiguous_through=?, last_key_sha256=?, updated_at_utc=? WHERE singleton=1",
                (ordinal, key_sha256, utc_now()),
            )
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def audit(self) -> dict[str, Any]:
        integrity = str(self.connection.execute("PRAGMA integrity_check").fetchone()[0])
        rows = self.connection.execute("SELECT * FROM rpc_cache ORDER BY block_number, abi_method").fetchall()
        invalid_rows = 0
        for row in rows:
            call = ArchiveCall(
                rpc_method=str(row["rpc_method"]),
                abi_method=str(row["abi_method"]),
                block_number=int(row["block_number"]),
                market_id=str(row["market_id"]),
                wallet=str(row["wallet"]),
                call_data=str(row["call_data"]),
                expected_words=int(row["expected_words"]),
            )
            try:
                self._validate_call(call)
                result = call.validate_result(str(row["result_hex"]))
                if str(row["key_sha256"]) != call.key_sha256(self.chain_id, self.contract_address):
                    raise CacheIntegrityError("key checksum mismatch")
                if str(row["response_sha256"]) != self._response_sha256(call, result):
                    raise CacheIntegrityError("checksum mismatch")
            except (CacheIntegrityError, ValueError):
                invalid_rows += 1
        duplicate_key_groups = int(
            self.connection.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT chain_id, contract_address, rpc_method, abi_method,
                           block_number, market_id, wallet, COUNT(*) AS n
                    FROM rpc_cache
                    GROUP BY chain_id, contract_address, rpc_method, abi_method,
                             block_number, market_id, wallet
                    HAVING n > 1
                )
                """
            ).fetchone()[0]
        )
        checkpoint = self.connection.execute("SELECT * FROM checkpoint WHERE singleton=1").fetchone()
        progress_count = int(self.connection.execute("SELECT COUNT(*) FROM progress").fetchone()[0])
        progress_minmax = self.connection.execute("SELECT MIN(ordinal), MAX(ordinal) FROM progress").fetchone()
        orphan_progress = int(
            self.connection.execute(
                """
                SELECT COUNT(*) FROM progress p
                LEFT JOIN rpc_cache r ON r.key_sha256 = p.key_sha256
                WHERE r.key_sha256 IS NULL
                """
            ).fetchone()[0]
        )
        contiguous = int(checkpoint["contiguous_through"]) if checkpoint is not None else -2
        expected_progress = contiguous + 1
        progress_gaps = 0
        if progress_count != expected_progress:
            progress_gaps += abs(progress_count - expected_progress)
        if progress_count:
            if int(progress_minmax[0]) != 0 or int(progress_minmax[1]) != contiguous:
                progress_gaps += 1
        return {
            "sqlite_integrity": integrity,
            "cache_identity_sha256": self.identity_sha256,
            "cache_entries": len(rows),
            "invalid_entries": invalid_rows,
            "duplicate_key_groups": duplicate_key_groups,
            "error_entries": 0,
            "checkpoint_contiguous_through": contiguous,
            "progress_rows": progress_count,
            "progress_gaps": progress_gaps,
            "orphan_progress_rows": orphan_progress,
            "wal_mode": str(self.connection.execute("PRAGMA journal_mode").fetchone()[0]).lower(),
            "synchronous": int(self.connection.execute("PRAGMA synchronous").fetchone()[0]),
        }


class CachedArchiveSession:
    def __init__(
        self,
        rpc_call: Callable[[str, list[Any]], Any],
        cache: ArchiveRpcCache,
        contract_address: str,
        max_new_rpc_calls: int | None = None,
    ) -> None:
        self.rpc_call = rpc_call
        self.cache = cache
        self.contract_address = contract_address
        self.max_new_rpc_calls = max_new_rpc_calls
        self.next_ordinal = 0
        self.cache_hits = 0
        self.new_rpc_calls = 0

    def execute(self, call: ArchiveCall) -> str:
        ordinal = self.next_ordinal
        self.next_ordinal += 1
        cached = self.cache.get(call)
        if cached is not None:
            self.cache_hits += 1
            self.cache.advance_checkpoint(ordinal, call)
            return cached
        if self.max_new_rpc_calls is not None and self.new_rpc_calls >= self.max_new_rpc_calls:
            raise IntentionalStop(
                f"intentional stop before unconfirmed ordinal {ordinal}; "
                f"new_rpc_calls={self.new_rpc_calls}"
            )
        result = self.rpc_call(call.rpc_method, call.request_params(self.contract_address))
        confirmed = self.cache.store(call, result)
        self.cache.advance_checkpoint(ordinal, call)
        self.new_rpc_calls += 1
        if self.max_new_rpc_calls is not None and self.new_rpc_calls >= self.max_new_rpc_calls:
            raise IntentionalStop(
                f"intentional stop after confirmed ordinal {ordinal}; "
                f"new_rpc_calls={self.new_rpc_calls}"
            )
        return confirmed

    def metrics(self) -> dict[str, int]:
        return {
            "planned_calls_seen": self.next_ordinal,
            "cache_hits": self.cache_hits,
            "new_archive_rpc_calls": self.new_rpc_calls,
        }
