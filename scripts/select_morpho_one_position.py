#!/usr/bin/env python3
"""Deterministically select one Morpho wallet-market position for Phase 3.

This script scans the complete, already-verified Phase 2 RPC shard set. It does
not extract logs again, reconstruct a position, or create SQL. Network access is
limited to bounded read-only calls needed to prove zero-state anchors, obtain
independent final checkpoints, identify historical fee recipients, and timestamp
the selected boundaries.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from morpho_archive_rpc_cache import (
    ArchiveCall,
    ArchiveRpcCache,
    CacheIdentityError,
    CacheIntegrityError,
    CachedArchiveSession,
    EXPECTED_CHAIN_ID,
    IntentionalStop,
    canonical_json,
    sha256_text,
)


MORPHO_ADDRESS = "0x6c247b1f6182318877311737bac0844baa518f5e"
DEFAULT_RPC_URL = "https://arb1.arbitrum.io/rpc"
RPC_USER_AGENT = "Morpho-DRIP-position-selection/1.0"
SELECTOR_CACHE_VERSION = "morpho-phase3-selector-cache-v1"

EVENTS = {
    "0xedf8870433c83823eb071d3df1caa8d008f12f6440918c20d75a3602cda30fe0": "Supply",
    "0xa56fc0ad5702ec05ce63666221f796fb62437c32db1aa1aa075fc6484cf58fbf": "Withdraw",
    "0x570954540bed6b1304a87dfe815a5eda4a648f7097a16240dcd85c9b5fd42a43": "Borrow",
    "0x52acb05cebbd3cd39715469f22afbf5a17496295ef3bc9bb5944056c63ccaa09": "Repay",
    "0xa3b9472a1399e17e123f3c2e6586c23e504184d504de59cdaa2b375e880c6184": "SupplyCollateral",
    "0xe80ebd7cc9223d7382aab2e0d1d6155c65651f83d53c8b9b06901d167e321142": "WithdrawCollateral",
    "0xa4946ede45d0c6f06a0f5ce92c9ad3b4751452d2fe0e25010783bcab57a67e41": "Liquidate",
    "0x9d9bd501d0657d7dfe415f779a620a62b78bc508ddc0891fbbd8b7ac0f8fce87": "AccrueInterest",
}
POSITION_FAMILIES = set(EVENTS.values()) - {"AccrueInterest"}

# Owner location in the event topics array, including topic0 at index 0.
OWNER_TOPIC_INDEX = {
    "Supply": 3,
    "Withdraw": 2,
    "Borrow": 2,
    "Repay": 3,
    "SupplyCollateral": 3,
    "WithdrawCollateral": 2,
    "Liquidate": 3,
}

# First four bytes of official ABI signature hashes, derived with web3_sha3.
POSITION_SELECTOR = "93c52062"  # position(bytes32,address)
MARKET_SELECTOR = "5c60e39a"  # market(bytes32)
FEE_RECIPIENT_SELECTOR = "46904840"  # feeRecipient()
SET_FEE_RECIPIENT_TOPIC = "0x2e979f80fe4d43055c584cf4a8467c55875ea36728fc37176c05acd784eb7a73"

HASH_PREFIX = "morpho-phase3-v1"
MAX_POSITION_EVENTS = 50
MIN_POSITION_EVENTS = 4


class RpcError(RuntimeError):
    pass


@dataclass
class PairStats:
    market_id: str
    wallet: str
    event_count: int = 0
    family_counts: Counter[str] = field(default_factory=Counter)
    first_order: tuple[int, int, int] | None = None
    last_order: tuple[int, int, int] | None = None
    first_transaction_hash: str = ""
    last_transaction_hash: str = ""
    first_supply_collateral_order: tuple[int, int, int] | None = None
    first_borrow_order: tuple[int, int, int] | None = None
    close_orders: list[tuple[int, int, int]] = field(default_factory=list)

    def add(self, family: str, order: tuple[int, int, int], transaction_hash: str) -> None:
        self.event_count += 1
        self.family_counts[family] += 1
        if self.first_order is None or order < self.first_order:
            self.first_order = order
            self.first_transaction_hash = transaction_hash
        if self.last_order is None or order > self.last_order:
            self.last_order = order
            self.last_transaction_hash = transaction_hash
        if family == "SupplyCollateral" and (
            self.first_supply_collateral_order is None or order < self.first_supply_collateral_order
        ):
            self.first_supply_collateral_order = order
        if family == "Borrow" and (self.first_borrow_order is None or order < self.first_borrow_order):
            self.first_borrow_order = order
        if family in {"Repay", "Liquidate"}:
            self.close_orders.append(order)


class RpcClient:
    def __init__(
        self,
        url: str,
        batch_size: int = 20,
        retries: int = 8,
        min_request_interval: float = 0.75,
    ) -> None:
        self.url = url
        self.batch_size = batch_size
        self.retries = retries
        self.min_request_interval = min_request_interval
        self.next_id = 0
        self.last_request_started = 0.0
        self.metrics: Counter[str] = Counter()
        self.error_samples: list[dict[str, Any]] = []

    def _new_id(self) -> int:
        self.next_id += 1
        return self.next_id

    def _before_request(self, rpc_items: int) -> None:
        wait_seconds = self.min_request_interval - (time.monotonic() - self.last_request_started)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        self.last_request_started = time.monotonic()
        self.metrics["http_requests"] += 1
        self.metrics["rpc_items"] += rpc_items

    def _post(self, payload: object) -> object:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self._before_request(len(payload) if isinstance(payload, list) else 1)
            request = urllib.request.Request(
                self.url,
                data=encoded,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": RPC_USER_AGENT,
                    "Connection": "close",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    raw = response.read()
                self.metrics["response_bytes"] += len(raw)
                return json.loads(raw)
            except urllib.error.HTTPError as exc:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                last_error = exc
                body = exc.read().decode("utf-8", errors="replace")[:500]
                if len(self.error_samples) < 20:
                    self.error_samples.append({"kind": "HTTP", "code": exc.code, "body": body})
                if attempt >= self.retries:
                    break
                self.metrics["retries"] += 1
                delay = float(retry_after) if retry_after and retry_after.isdigit() else min(2**attempt, 20)
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if len(self.error_samples) < 20:
                    self.error_samples.append({"kind": type(exc).__name__, "message": str(exc)[:500]})
                if attempt >= self.retries:
                    break
                self.metrics["retries"] += 1
                time.sleep(min(2**attempt, 20))
        raise RpcError(f"RPC transport failed after retries: {last_error}")

    def call(self, method: str, params: list[Any]) -> Any:
        request_id = self._new_id()
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        decoded = self._post(payload)
        if not isinstance(decoded, dict):
            raise RpcError(f"Expected object response for {method}")
        if decoded.get("jsonrpc") != "2.0" or decoded.get("id") != request_id:
            raise RpcError(f"RPC envelope mismatch for {method}")
        if decoded.get("error") is not None:
            raise RpcError(f"RPC {method} error: {decoded['error']}")
        if "result" not in decoded:
            raise RpcError(f"RPC {method} response has no result")
        return decoded["result"]

    def batch(self, calls: list[tuple[str, list[Any]]]) -> list[tuple[bool, Any]]:
        output: list[tuple[bool, Any]] = []
        for offset in range(0, len(calls), self.batch_size):
            chunk = calls[offset : offset + self.batch_size]
            payload: list[dict[str, Any]] = []
            ids: list[int] = []
            for method, params in chunk:
                request_id = self._new_id()
                ids.append(request_id)
                payload.append({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            decoded = self._post(payload)
            if not isinstance(decoded, list):
                self.metrics["batch_fallbacks"] += 1
                for method, params in chunk:
                    try:
                        output.append((True, self.call(method, params)))
                    except RpcError as exc:
                        output.append((False, str(exc)))
                continue
            by_id = {item.get("id"): item for item in decoded if isinstance(item, dict)}
            for request_id in ids:
                item = by_id.get(request_id)
                if item is None:
                    output.append((False, "missing batch response item"))
                elif item.get("error") is not None:
                    output.append((False, str(item["error"])))
                else:
                    output.append((True, item.get("result")))
        return output

    def get_logs_adaptive(self, from_block: int, to_block: int, topic0: str) -> list[dict[str, Any]]:
        pending = [(from_block, to_block)]
        logs: list[dict[str, Any]] = []
        while pending:
            start, end = pending.pop()
            self.metrics["eth_get_logs_ranges_attempted"] += 1
            try:
                result = self.call(
                    "eth_getLogs",
                    [
                        {
                            "address": MORPHO_ADDRESS,
                            "fromBlock": hex(start),
                            "toBlock": hex(end),
                            "topics": [topic0],
                        }
                    ],
                )
                if not isinstance(result, list):
                    raise RpcError("eth_getLogs result is not a list")
                logs.extend(result)
                self.metrics["eth_get_logs_ranges_succeeded"] += 1
            except RpcError:
                if start >= end:
                    raise
                midpoint = (start + end) // 2
                self.metrics["eth_get_logs_range_splits"] += 1
                pending.append((midpoint + 1, end))
                pending.append((start, midpoint))
        return sorted(
            logs,
            key=lambda row: (
                int(str(row["blockNumber"]), 16),
                int(str(row["transactionIndex"]), 16),
                int(str(row["logIndex"]), 16),
            ),
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="data/raw/morpho_full_window/manifest.json")
    parser.add_argument("--market-csv", default="data/drip_morpho_markets.csv")
    parser.add_argument("--output", default="data/morpho_one_position_selection.json")
    parser.add_argument("--rpc-url", default=DEFAULT_RPC_URL)
    parser.add_argument("--offline-only", action="store_true")
    parser.add_argument("--candidate-population", help="Validated structural-candidate JSON; skips shard scan")
    parser.add_argument("--write-candidate-population", help="Atomically persist the structural population after a scan")
    parser.add_argument("--cache", default="data/tmp/morpho_phase3_archive_rpc.sqlite")
    parser.add_argument("--max-new-rpc-calls", type=int)
    parser.add_argument("--bounded-test", action="store_true")
    parser.add_argument("--bounded-report", default="data/morpho_phase3_rpc_cache_bounded_test.json")
    parser.add_argument("--allow-full-archive-pass", action="store_true")
    parser.add_argument("--assume-verified-no-fee-recipient-changes", action="store_true")
    parser.add_argument("--min-request-interval", type=float, default=0.75)
    parser.add_argument("--retries", type=int, default=8)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="")
    os.replace(part, path)


def topic_address(topic: str) -> str:
    normalized = topic.lower()
    if not normalized.startswith("0x") or len(normalized) != 66:
        raise ValueError(f"Invalid indexed address topic: {topic}")
    return "0x" + normalized[-40:]


def encode_position_call(market_id: str, wallet: str) -> str:
    return "0x" + POSITION_SELECTOR + market_id[2:] + wallet[2:].rjust(64, "0")


def encode_market_call(market_id: str) -> str:
    return "0x" + MARKET_SELECTOR + market_id[2:]


def decode_words(result: str, count: int) -> tuple[int, ...]:
    if not isinstance(result, str) or not result.startswith("0x"):
        raise ValueError("eth_call result is not hex")
    payload = result[2:]
    if len(payload) != count * 64:
        raise ValueError(f"Unexpected eth_call result length: {len(payload)}")
    return tuple(int(payload[offset : offset + 64], 16) for offset in range(0, count * 64, 64))


def position_call(market_id: str, wallet: str, block_number: int) -> tuple[str, list[Any]]:
    return (
        "eth_call",
        [{"to": MORPHO_ADDRESS, "data": encode_position_call(market_id, wallet)}, hex(block_number)],
    )


def market_call(market_id: str, block_number: int) -> tuple[str, list[Any]]:
    return (
        "eth_call",
        [{"to": MORPHO_ADDRESS, "data": encode_market_call(market_id)}, hex(block_number)],
    )


def archive_position_call(market_id: str, wallet: str, block_number: int) -> ArchiveCall:
    return ArchiveCall(
        rpc_method="eth_call",
        abi_method="position",
        block_number=block_number,
        market_id=market_id,
        wallet=wallet,
        call_data=encode_position_call(market_id, wallet),
        expected_words=3,
    )


def archive_market_call(market_id: str, block_number: int) -> ArchiveCall:
    return ArchiveCall(
        rpc_method="eth_call",
        abi_method="market",
        block_number=block_number,
        market_id=market_id,
        wallet="",
        call_data=encode_market_call(market_id),
        expected_words=6,
    )


def archive_fee_recipient_call(block_number: int) -> ArchiveCall:
    return ArchiveCall(
        rpc_method="eth_call",
        abi_method="feeRecipient",
        block_number=block_number,
        market_id="",
        wallet="",
        call_data="0x" + FEE_RECIPIENT_SELECTOR,
        expected_words=1,
    )


def get_block_timestamp(client: RpcClient, block_number: int) -> str:
    result = client.call("eth_getBlockByNumber", [hex(block_number), False])
    if not isinstance(result, dict) or result.get("timestamp") is None:
        raise RpcError(f"Missing timestamp for block {block_number}")
    unix = int(str(result["timestamp"]), 16)
    return datetime.fromtimestamp(unix, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def validate_live_chain(client: RpcClient) -> int:
    result = client.call("eth_chainId", [])
    if not isinstance(result, str) or not result.startswith("0x"):
        raise RpcError("eth_chainId result is not hexadecimal")
    try:
        chain_id = int(result, 16)
    except ValueError as exc:
        raise RpcError("eth_chainId result is malformed") from exc
    if chain_id != EXPECTED_CHAIN_ID:
        raise RpcError(f"Wrong RPC chain: expected {EXPECTED_CHAIN_ID}, received {chain_id}")
    client.metrics["chain_id_validations"] += 1
    return chain_id


def canonical_hash(market_id: str, wallet: str) -> tuple[str, str]:
    preimage = f"{HASH_PREFIX}|{market_id.lower()}|{wallet.lower()}"
    return preimage, hashlib.sha256(preimage.encode("ascii")).hexdigest()


def pair_record(row: PairStats) -> dict[str, Any]:
    return {
        "market_id": row.market_id,
        "wallet": row.wallet,
        "event_count": row.event_count,
        "family_counts": dict(sorted(row.family_counts.items())),
        "first_order": list(row.first_order or ()),
        "last_order": list(row.last_order or ()),
        "first_transaction_hash": row.first_transaction_hash,
        "last_transaction_hash": row.last_transaction_hash,
        "first_supply_collateral_order": list(row.first_supply_collateral_order or ()),
        "first_borrow_order": list(row.first_borrow_order or ()),
        "close_orders": [list(value) for value in sorted(row.close_orders)],
    }


def pair_from_record(value: dict[str, Any]) -> PairStats:
    def order(name: str) -> tuple[int, int, int] | None:
        raw = value.get(name, [])
        if raw == []:
            return None
        if not isinstance(raw, list) or len(raw) != 3:
            raise RuntimeError(f"Invalid {name} in candidate population")
        return tuple(int(item) for item in raw)  # type: ignore[return-value]

    market_id = str(value["market_id"]).lower()
    wallet = str(value["wallet"]).lower()
    if len(market_id) != 66 or len(wallet) != 42:
        raise RuntimeError("Malformed market or wallet in candidate population")
    return PairStats(
        market_id=market_id,
        wallet=wallet,
        event_count=int(value["event_count"]),
        family_counts=Counter({str(k): int(v) for k, v in dict(value["family_counts"]).items()}),
        first_order=order("first_order"),
        last_order=order("last_order"),
        first_transaction_hash=str(value["first_transaction_hash"]).lower(),
        last_transaction_hash=str(value["last_transaction_hash"]).lower(),
        first_supply_collateral_order=order("first_supply_collateral_order"),
        first_borrow_order=order("first_borrow_order"),
        close_orders=[tuple(int(item) for item in raw) for raw in value.get("close_orders", [])],
    )


def candidate_population_sha256(candidates: Iterable[PairStats]) -> str:
    records = sorted((pair_record(row) for row in candidates), key=lambda row: (row["market_id"], row["wallet"]))
    return sha256_text(canonical_json(records))


def write_candidate_population(
    path: Path,
    candidates: list[PairStats],
    manifest_path: Path,
    manifest: dict[str, Any],
    population_kind: str,
    scan_summary: dict[str, Any],
    funnel: list[dict[str, int]],
) -> dict[str, Any]:
    ordered = sorted(candidates, key=lambda row: (row.market_id, row.wallet))
    evidence = {
        "schema_version": 1,
        "population_kind": population_kind,
        "manifest_sha256": sha256_file(manifest_path),
        "manifest_rows": int(manifest["row_count"]),
        "manifest_verified_shards": int(manifest["verified_shard_count"]),
        "criteria_sha256": sha256_text(canonical_json(selection_criteria())),
        "candidate_count": len(ordered),
        "candidate_population_sha256": candidate_population_sha256(ordered),
        "scan_summary": scan_summary,
        "candidate_funnel": funnel,
        "candidates": [pair_record(row) for row in ordered],
    }
    atomic_write_json(path, evidence)
    return evidence


def load_candidate_population(
    path: Path, manifest_path: Path, manifest: dict[str, Any]
) -> tuple[list[PairStats], dict[str, Any], list[dict[str, int]], str]:
    evidence = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "schema_version": 1,
        "manifest_sha256": sha256_file(manifest_path),
        "manifest_rows": int(manifest["row_count"]),
        "manifest_verified_shards": int(manifest["verified_shard_count"]),
        "criteria_sha256": sha256_text(canonical_json(selection_criteria())),
    }
    mismatches = [
        f"{key}: file={evidence.get(key)!r} expected={value!r}"
        for key, value in expected.items()
        if evidence.get(key) != value
    ]
    if mismatches:
        raise RuntimeError("Candidate population identity mismatch: " + "; ".join(mismatches))
    candidates = [pair_from_record(dict(value)) for value in evidence.get("candidates", [])]
    actual_hash = candidate_population_sha256(candidates)
    if len(candidates) != int(evidence.get("candidate_count", -1)):
        raise RuntimeError("Candidate population count mismatch")
    if actual_hash != evidence.get("candidate_population_sha256"):
        raise RuntimeError("Candidate population SHA-256 mismatch")
    if len({(row.market_id, row.wallet) for row in candidates}) != len(candidates):
        raise RuntimeError("Duplicate wallet-market keys in candidate population")
    return (
        sorted(candidates, key=lambda row: (row.market_id, row.wallet)),
        dict(evidence.get("scan_summary", {})),
        list(evidence.get("candidate_funnel", [])),
        str(evidence.get("population_kind", "unknown")),
    )


def market_ids_from_csv(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        values = {str(row["market_id"]).lower() for row in csv.DictReader(handle)}
    if len(values) != 45:
        raise RuntimeError(f"Expected 45 unique market IDs, found {len(values)}")
    return values


def scan_history(
    manifest: dict[str, Any], manifest_path: Path, eligible_markets: set[str]
) -> tuple[dict[tuple[str, str], PairStats], dict[str, list[tuple[int, int, int]]], dict[str, Any]]:
    if manifest.get("status") != "complete" or manifest.get("complete") is not True:
        raise RuntimeError("Full-window manifest is not complete")
    if set(str(value).lower() for value in manifest.get("market_ids", [])) != eligible_markets:
        raise RuntimeError("Manifest market scope does not match the 45-market CSV")
    if set(str(value).lower() for value in manifest.get("event_hashes", [])) != set(EVENTS):
        raise RuntimeError("Manifest event-family scope does not match the selection script")

    shard_root = manifest_path.parent / "shards"
    pair_stats: dict[tuple[str, str], PairStats] = {}
    accrual_orders: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    total_rows = 0
    position_rows = 0
    malformed_owner_rows = 0
    scope_mismatches = 0
    removed_rows = 0
    previous_order: tuple[int, int, int] | None = None
    ordering_violations = 0

    for shard_index, entry in enumerate(manifest["shards"], start=1):
        shard_path = shard_root / str(entry["file"])
        shard_rows = 0
        with shard_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                shard_rows += 1
                total_rows += 1
                order = (int(row["block_number"]), int(row["transaction_index"]), int(row["log_index"]))
                if previous_order is not None and order < previous_order:
                    ordering_violations += 1
                previous_order = order
                if bool(row.get("removed")):
                    removed_rows += 1
                topics = json.loads(row["topics_json"])
                topic0 = str(topics[0]).lower() if topics else ""
                market_id = str(topics[1]).lower() if len(topics) > 1 else ""
                family = EVENTS.get(topic0)
                if (
                    str(row.get("address", "")).lower() != MORPHO_ADDRESS
                    or family is None
                    or market_id not in eligible_markets
                ):
                    scope_mismatches += 1
                    continue
                if family == "AccrueInterest":
                    accrual_orders[market_id].append(order)
                    continue
                owner_index = OWNER_TOPIC_INDEX[family]
                if len(topics) <= owner_index:
                    malformed_owner_rows += 1
                    continue
                wallet = topic_address(str(topics[owner_index]))
                pair_key = (market_id, wallet)
                stats = pair_stats.get(pair_key)
                if stats is None:
                    stats = PairStats(market_id=market_id, wallet=wallet)
                    pair_stats[pair_key] = stats
                stats.add(family, order, str(row["transaction_hash"]).lower())
                position_rows += 1
        if shard_rows != int(entry["row_count"]):
            raise RuntimeError(f"Shard row-count mismatch during scan: {entry['file']}")
        if shard_index % 500 == 0:
            print(f"scan_progress shards={shard_index} rows={total_rows} pairs={len(pair_stats)}", flush=True)

    expected_rows = int(manifest["row_count"])
    if total_rows != expected_rows:
        raise RuntimeError(f"Scanned {total_rows} rows, expected {expected_rows}")
    if any([malformed_owner_rows, scope_mismatches, removed_rows, ordering_violations]):
        raise RuntimeError(
            "Input QA failed during selection scan: "
            f"malformed_owner={malformed_owner_rows}, scope={scope_mismatches}, "
            f"removed={removed_rows}, order={ordering_violations}"
        )

    scan_summary = {
        "manifest_shards_scanned": len(manifest["shards"]),
        "manifest_rows_scanned": total_rows,
        "position_event_rows": position_rows,
        "distinct_wallet_market_pairs": len(pair_stats),
        "malformed_owner_rows": malformed_owner_rows,
        "scope_mismatches": scope_mismatches,
        "removed_rows": removed_rows,
        "ordering_violations": ordering_violations,
    }
    return pair_stats, accrual_orders, scan_summary


def structural_funnel(
    pairs: Iterable[PairStats], accrual_orders: dict[str, list[tuple[int, int, int]]]
) -> tuple[list[PairStats], list[dict[str, int]]]:
    current = list(pairs)
    funnel: list[dict[str, int]] = [{"stage": "all_distinct_wallet_market_pairs", "count": len(current)}]

    current = [row for row in current if row.first_supply_collateral_order is not None]
    funnel.append({"stage": "has_supply_collateral", "count": len(current)})

    current = [
        row
        for row in current
        if row.first_borrow_order is not None
        and row.first_supply_collateral_order is not None
        and row.first_supply_collateral_order < row.first_borrow_order
    ]
    funnel.append({"stage": "supply_collateral_before_borrow", "count": len(current)})

    current = [
        row
        for row in current
        if row.first_borrow_order is not None and any(order > row.first_borrow_order for order in row.close_orders)
    ]
    funnel.append({"stage": "later_repay_or_liquidate", "count": len(current)})

    current = [row for row in current if MIN_POSITION_EVENTS <= row.event_count <= MAX_POSITION_EVENTS]
    funnel.append({"stage": "position_event_count_4_to_50", "count": len(current)})

    def has_intervening_accrual(row: PairStats) -> bool:
        assert row.first_borrow_order is not None and row.last_order is not None
        orders = accrual_orders.get(row.market_id, [])
        index = bisect.bisect_right(orders, row.first_borrow_order)
        return index < len(orders) and orders[index][0] <= row.last_order[0]

    current = [row for row in current if has_intervening_accrual(row)]
    funnel.append({"stage": "intervening_accrue_interest", "count": len(current)})
    return current, funnel


def cached_fee_recipient_history(
    session: CachedArchiveSession,
    start_block: int,
    end_block_exclusive: int,
    assume_verified_no_changes: bool,
) -> dict[str, Any]:
    if not assume_verified_no_changes:
        raise RuntimeError(
            "SetFeeRecipient history is not part of the archive eth_call cache. "
            "Use --assume-verified-no-fee-recipient-changes only with the zero-log evidence "
            "recorded in PHASE3_SELECTION_CHECKPOINT.md."
        )
    initial = session.execute(archive_fee_recipient_call(start_block - 1))
    words = decode_words(str(initial), 1)
    initial_address = "0x" + f"{words[0]:064x}"[-40:]
    return {
        "initial_block": start_block - 1,
        "initial_fee_recipient": initial_address,
        "changes": [],
        "all_recipient_addresses": [initial_address],
        "change_history_evidence": {
            "status": "reused_verified_zero_logs",
            "block_interval": [start_block, end_block_exclusive],
            "topic0": SET_FEE_RECIPIENT_TOPIC,
            "source": "PHASE3_SELECTION_CHECKPOINT.md",
        },
    }


def cached_rpc_filter_candidates(
    session: CachedArchiveSession, candidates: list[PairStats], fee_recipients: set[str]
) -> tuple[list[dict[str, Any]], list[dict[str, int]], dict[str, Any]]:
    funnel: list[dict[str, int]] = []
    current = [row for row in candidates if row.wallet not in fee_recipients]
    funnel.append({"stage": "not_historical_fee_recipient", "count": len(current)})

    anchor_available: list[dict[str, Any]] = []
    anchor_nonzero = 0
    anchor_uninitialized_market = 0
    for row in current:
        assert row.first_order is not None
        anchor_block = row.first_order[0] - 1
        position_result = session.execute(archive_position_call(row.market_id, row.wallet, anchor_block))
        market_result = session.execute(archive_market_call(row.market_id, anchor_block))
        position_state = decode_words(str(position_result), 3)
        market_state = decode_words(str(market_result), 6)
        if position_state != (0, 0, 0):
            anchor_nonzero += 1
            continue
        if market_state[4] == 0:
            anchor_uninitialized_market += 1
            continue
        anchor_available.append(
            {
                "stats": row,
                "anchor_block": row.first_order[0] - 1 if row.first_order else None,
                "anchor_position": {
                    "supply_shares": position_state[0],
                    "borrow_shares": position_state[1],
                    "collateral_assets": position_state[2],
                },
                "anchor_market": {
                    "total_supply_assets": market_state[0],
                    "total_supply_shares": market_state[1],
                    "total_borrow_assets": market_state[2],
                    "total_borrow_shares": market_state[3],
                    "last_update": market_state[4],
                    "fee": market_state[5],
                },
            }
        )
    funnel.append({"stage": "anchor_rpc_available", "count": len(current)})
    funnel.append({"stage": "zero_position_anchor", "count": len(anchor_available) + anchor_uninitialized_market})
    funnel.append({"stage": "initialized_market_anchor", "count": len(anchor_available)})

    eligible: list[dict[str, Any]] = []
    for item in anchor_available:
        row = item["stats"]
        assert isinstance(row, PairStats) and row.last_order is not None
        final_block = row.last_order[0]
        position_result = session.execute(archive_position_call(row.market_id, row.wallet, final_block))
        market_result = session.execute(archive_market_call(row.market_id, final_block))
        final_position = decode_words(str(position_result), 3)
        final_market = decode_words(str(market_result), 6)
        if final_market[4] == 0:
            raise CacheIntegrityError(
                f"Final market is uninitialized for {row.market_id} at block {final_block}"
            )
        preimage, digest = canonical_hash(row.market_id, row.wallet)
        eligible.append(
            {
                **{key: value for key, value in item.items() if key != "stats"},
                "market_id": row.market_id,
                "wallet": row.wallet,
                "selection_preimage": preimage,
                "selection_sha256": digest,
                "first_event": {
                    "block_number": row.first_order[0] if row.first_order else None,
                    "transaction_index": row.first_order[1] if row.first_order else None,
                    "log_index": row.first_order[2] if row.first_order else None,
                    "transaction_hash": row.first_transaction_hash,
                },
                "last_event": {
                    "block_number": row.last_order[0],
                    "transaction_index": row.last_order[1],
                    "log_index": row.last_order[2],
                    "transaction_hash": row.last_transaction_hash,
                },
                "final_checkpoint_block": row.last_order[0],
                "position_event_count": row.event_count,
                "event_family_counts": dict(sorted(row.family_counts.items())),
                "first_supply_collateral_order": list(row.first_supply_collateral_order or ()),
                "first_borrow_order": list(row.first_borrow_order or ()),
                "final_position": {
                    "supply_shares": final_position[0],
                    "borrow_shares": final_position[1],
                    "collateral_assets": final_position[2],
                },
                "final_market": {
                    "total_supply_assets": final_market[0],
                    "total_supply_shares": final_market[1],
                    "total_borrow_assets": final_market[2],
                    "total_borrow_shares": final_market[3],
                    "last_update": final_market[4],
                    "fee": final_market[5],
                },
            }
        )
    funnel.append({"stage": "independent_final_rpc_checkpoint_available", "count": len(eligible)})
    diagnostics = {
        "fee_recipient_pairs_excluded": len(candidates) - len(current),
        "anchor_rpc_failures": 0,
        "nonzero_position_anchors": anchor_nonzero,
        "uninitialized_market_anchors": anchor_uninitialized_market,
        "final_rpc_failures": 0,
        "rpc_failure_samples": [],
    }
    return eligible, funnel, diagnostics


def compact_candidate(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "market_id": item["market_id"],
        "wallet": item["wallet"],
        "selection_sha256": item["selection_sha256"],
        "selection_preimage": item["selection_preimage"],
        "anchor_block": item["anchor_block"],
        "final_checkpoint_block": item["final_checkpoint_block"],
        "first_event": item["first_event"],
        "last_event": item["last_event"],
        "position_event_count": item["position_event_count"],
        "event_family_counts": item["event_family_counts"],
        "anchor_position": item["anchor_position"],
        "final_position": item["final_position"],
    }


def main() -> int:
    args = parse_args()
    started = time.monotonic()
    manifest_path = Path(args.manifest).resolve()
    market_csv_path = Path(args.market_csv).resolve()
    output_path = Path(args.output).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    eligible_markets = market_ids_from_csv(market_csv_path)

    population_kind = "complete_structural_population"
    if args.candidate_population:
        structural, scan_summary, funnel, population_kind = load_candidate_population(
            Path(args.candidate_population).resolve(), manifest_path, manifest
        )
        print(
            json.dumps(
                {
                    "candidate_population": str(Path(args.candidate_population).resolve()),
                    "population_kind": population_kind,
                    "candidate_count": len(structural),
                    "candidate_population_sha256": candidate_population_sha256(structural),
                },
                indent=2,
            ),
            flush=True,
        )
    else:
        if args.bounded_test:
            raise RuntimeError("--bounded-test requires --candidate-population; full shard scan is disabled")
        pairs, accrual_orders, scan_summary = scan_history(manifest, manifest_path, eligible_markets)
        structural, funnel = structural_funnel(pairs.values(), accrual_orders)
        structural = sorted(structural, key=lambda row: (row.market_id, row.wallet))
        print(json.dumps({"scan": scan_summary, "structural_funnel": funnel}, indent=2), flush=True)
        if args.write_candidate_population:
            write_candidate_population(
                Path(args.write_candidate_population).resolve(),
                structural,
                manifest_path,
                manifest,
                population_kind,
                scan_summary,
                funnel,
            )
    if args.offline_only:
        return 0
    if not structural:
        raise RuntimeError(f"Candidate population became empty at stage {funnel[-1]['stage']}")
    if args.bounded_test:
        if not (10 <= len(structural) <= 20):
            raise RuntimeError("Bounded test population must contain 10–20 structural candidates")
        if population_kind != "bounded_test_structural_candidates":
            raise RuntimeError("Bounded test refuses a candidate population without bounded-test identity")
    elif not args.allow_full_archive_pass:
        raise RuntimeError(
            "Full archive-state pass is locked. Use --allow-full-archive-pass only after explicit authorization."
        )
    if args.max_new_rpc_calls is not None and args.max_new_rpc_calls < 1:
        raise RuntimeError("--max-new-rpc-calls must be positive")

    population_sha256 = candidate_population_sha256(structural)
    manifest_sha256 = sha256_file(manifest_path)
    identity = {
        "selector_cache_version": SELECTOR_CACHE_VERSION,
        "chain_id": EXPECTED_CHAIN_ID,
        "contract_address": MORPHO_ADDRESS,
        "manifest_sha256": manifest_sha256,
        "manifest_rows": int(manifest["row_count"]),
        "manifest_verified_shards": int(manifest["verified_shard_count"]),
        "manifest_block_interval": [int(manifest["start_block"]), int(manifest["end_block_exclusive"])],
        "candidate_population_kind": population_kind,
        "candidate_population_count": len(structural),
        "candidate_population_sha256": population_sha256,
        "selection_criteria_sha256": sha256_text(canonical_json(selection_criteria())),
        "verified_no_fee_recipient_changes": bool(args.assume_verified_no_fee_recipient_changes),
    }
    client = RpcClient(
        args.rpc_url,
        retries=args.retries,
        min_request_interval=args.min_request_interval,
    )
    validate_live_chain(client)
    cache = ArchiveRpcCache(
        Path(args.cache).resolve(),
        identity,
        MORPHO_ADDRESS,
        POSITION_SELECTOR,
        MARKET_SELECTOR,
        FEE_RECIPIENT_SELECTOR,
    )
    session = CachedArchiveSession(
        client.call,
        cache,
        MORPHO_ADDRESS,
        max_new_rpc_calls=args.max_new_rpc_calls,
    )
    try:
        fee_history = cached_fee_recipient_history(
            session,
            int(manifest["start_block"]),
            int(manifest["end_block_exclusive"]),
            args.assume_verified_no_fee_recipient_changes,
        )
        fee_recipients = set(fee_history["all_recipient_addresses"])
        eligible, rpc_funnel, rpc_diagnostics = cached_rpc_filter_candidates(
            session, structural, fee_recipients
        )
        funnel = list(funnel) + rpc_funnel
    except IntentionalStop as exc:
        audit = cache.audit()
        evidence = {
            "status": "intentional_stop",
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "reason": str(exc),
            "bounded_test": bool(args.bounded_test),
            "candidate_population_count": len(structural),
            "candidate_population_sha256": population_sha256,
            "cache_path": str(Path(args.cache).resolve()),
            "cache_identity_sha256": cache.identity_sha256,
            "session_metrics": session.metrics(),
            "rpc_transport_metrics": dict(client.metrics),
            "cache_audit": audit,
        }
        if args.bounded_test:
            atomic_write_json(Path(args.bounded_report).resolve(), evidence)
        print(json.dumps(evidence, indent=2), flush=True)
        cache.close()
        return 75
    except Exception:
        cache.close()
        raise

    audit = cache.audit()
    if (
        audit["sqlite_integrity"] != "ok"
        or audit["invalid_entries"] != 0
        or audit["duplicate_key_groups"] != 0
        or audit["error_entries"] != 0
        or audit["progress_gaps"] != 0
        or audit["orphan_progress_rows"] != 0
        or audit["wal_mode"] != "wal"
    ):
        cache.close()
        raise CacheIntegrityError(f"Archive RPC cache audit failed: {audit}")

    if args.bounded_test:
        evidence = {
            "status": "bounded_test_complete",
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "source": {
                "manifest_sha256": manifest_sha256,
                "rows": int(manifest["row_count"]),
                "verified_shards": int(manifest["verified_shard_count"]),
                "block_interval": [int(manifest["start_block"]), int(manifest["end_block_exclusive"])],
                "rpc_endpoint": args.rpc_url,
            },
            "candidate_population_kind": population_kind,
            "candidate_population_count": len(structural),
            "candidate_population_sha256": population_sha256,
            "eligible_within_bounded_test": len(eligible),
            "candidate_funnel": funnel,
            "rpc_diagnostics": rpc_diagnostics,
            "session_metrics": session.metrics(),
            "rpc_transport_metrics": dict(client.metrics),
            "cache_audit": audit,
            "limitations": [
                "This validates cache/resume mechanics on a bounded structural-candidate subset only.",
                "It does not complete the 5,575-candidate archive-state pass or select rank 1.",
                "It does not reconstruct a position, build daily state, or start Phase 4.",
            ],
        }
        atomic_write_json(Path(args.bounded_report).resolve(), evidence)
        print(json.dumps(evidence, indent=2), flush=True)
        cache.close()
        return 0

    if not eligible:
        evidence = {
            "status": "blocked_no_candidates",
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": {
                "manifest": str(manifest_path),
                "manifest_sha256": sha256_file(manifest_path),
                "shards": int(manifest["verified_shard_count"]),
                "rows": int(manifest["row_count"]),
                "block_interval": [int(manifest["start_block"]), int(manifest["end_block_exclusive"])],
            },
            "criteria": selection_criteria(),
            "scan_summary": scan_summary,
            "candidate_funnel": funnel,
            "fee_recipient_history": fee_history,
            "rpc_diagnostics": rpc_diagnostics,
            "rpc_metrics": dict(client.metrics),
            "cache_audit": audit,
        }
        atomic_write_json(output_path, evidence)
        print(json.dumps(evidence, indent=2), flush=True)
        cache.close()
        return 2

    eligible.sort(key=lambda row: row["selection_sha256"])
    canonical_lines = [
        "|".join(
            [
                row["selection_sha256"],
                row["market_id"],
                row["wallet"],
                str(row["anchor_block"]),
                str(row["final_checkpoint_block"]),
                str(row["position_event_count"]),
            ]
        )
        for row in eligible
    ]
    candidate_set_sha256 = hashlib.sha256(("\n".join(canonical_lines) + "\n").encode("ascii")).hexdigest()
    selected = eligible[0]
    selected["anchor_timestamp_utc"] = get_block_timestamp(client, int(selected["anchor_block"]))
    selected["first_event_timestamp_utc"] = get_block_timestamp(client, int(selected["first_event"]["block_number"]))
    selected["final_checkpoint_timestamp_utc"] = get_block_timestamp(
        client, int(selected["final_checkpoint_block"])
    )

    evidence = {
        "status": "complete",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "source": {
            "manifest": str(manifest_path),
            "manifest_sha256": sha256_file(manifest_path),
            "verified_shards": int(manifest["verified_shard_count"]),
            "rows": int(manifest["row_count"]),
            "unique_event_keys": int(manifest["row_count"]),
            "block_interval": [int(manifest["start_block"]), int(manifest["end_block_exclusive"])],
            "utc_interval": [manifest["start_utc"], manifest["end_exclusive_utc"]],
            "rpc_endpoint": args.rpc_url,
        },
        "criteria": selection_criteria(),
        "scan_summary": scan_summary,
        "candidate_funnel": funnel,
        "fee_recipient_history": fee_history,
        "rpc_diagnostics": rpc_diagnostics,
        "eligible_candidate_count": len(eligible),
        "eligible_candidate_set_sha256": candidate_set_sha256,
        "selected_rank": 1,
        "selected": compact_candidate(selected)
        | {
            "anchor_timestamp_utc": selected["anchor_timestamp_utc"],
            "first_event_timestamp_utc": selected["first_event_timestamp_utc"],
            "final_checkpoint_timestamp_utc": selected["final_checkpoint_timestamp_utc"],
        },
        "top_ranked_candidates": [compact_candidate(row) for row in eligible[:10]],
        "rpc_metrics": dict(client.metrics),
        "archive_session_metrics": session.metrics(),
        "cache_audit": audit,
        "rpc_error_samples": client.error_samples,
        "limitations": [
            "This selects one accounting-feasibility trace; it does not reconstruct the position.",
            "The selected trace does not establish correctness for all wallets or markets, daily-state completeness, retention, or DRIP impact.",
            "Only the top 10 candidates are embedded; the full eligible set is committed by its count and canonical-set SHA-256.",
        ],
    }
    atomic_write_json(output_path, evidence)
    print(json.dumps(evidence, indent=2), flush=True)
    cache.close()
    return 0


def selection_criteria() -> dict[str, Any]:
    return {
        "pair_grain": "lowercase market_id + lowercase position_owner wallet",
        "position_owner_roles": "onBehalf for ordinary position events; borrower for Liquidate",
        "required_sequence": "SupplyCollateral < Borrow < later Repay or Liquidate in canonical log order",
        "position_event_count": {"minimum": MIN_POSITION_EVENTS, "maximum": MAX_POSITION_EVENTS},
        "intervening_interest": "at least one same-market AccrueInterest after the first Borrow and no later than the final checkpoint block",
        "anchor": "eth_call position and market at first position-event block minus one; position must be exactly (0,0,0) and market initialized",
        "final_checkpoint": "independent eth_call position and market at the block of the pair's last position-changing event",
        "fee_recipient_exclusion": "exclude any wallet active as feeRecipient during the full authorized interval",
        "canonical_order": ["block_number", "transaction_index", "log_index"],
        "hash_preimage": f"{HASH_PREFIX}|<lowercase market_id>|<lowercase wallet>",
        "selection": "ascending lowercase hexadecimal SHA-256; rank 1",
    }


if __name__ == "__main__":
    raise SystemExit(main())
