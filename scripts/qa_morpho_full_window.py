#!/usr/bin/env python3
"""Independent streaming QA for the authorized Morpho full-window RPC extract."""

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
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from threading import Lock


MORPHO_ADDRESS = "0x6c247b1f6182318877311737bac0844baa518f5e"
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
FAMILIES = list(EVENTS.values())
RPC_USER_AGENT = "Morpho-DRIP-full-window-QA/1.0 (PowerShell-compatible urllib client)"


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_text(text, encoding="utf-8", newline="")
    os.replace(part, path)


def atomic_write_json(path: Path, value: object) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def atomic_write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    with part.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(part, path)


class RpcBatchClient:
    def __init__(
        self,
        url: str,
        batch_size: int = 20,
        retries: int = 8,
        single_workers: int = 12,
        min_request_interval: float = 0.75,
    ) -> None:
        self.url = url
        self.batch_size = batch_size
        self.retries = retries
        self.single_workers = single_workers
        self.min_request_interval = min_request_interval
        self.http_requests = 0
        self.rpc_items = 0
        self.retries_used = 0
        self.response_bytes = 0
        self.batch_fallbacks = 0
        self._batch_supported = True
        self._metrics_lock = Lock()
        self._throttle_lock = Lock()
        self._last_request_started = 0.0

    def block_timestamps(self, block_numbers: list[int]) -> dict[int, int]:
        output: dict[int, int] = {}
        unique = list(dict.fromkeys(block_numbers))
        for offset in range(0, len(unique), self.batch_size):
            chunk = unique[offset : offset + self.batch_size]
            if self._batch_supported:
                output.update(self._block_timestamp_chunk(chunk))
            else:
                output.update(self._individual_timestamp_chunk(chunk))
        return output

    def _before_request(self, rpc_items: int) -> None:
        with self._throttle_lock:
            wait_seconds = self.min_request_interval - (time.monotonic() - self._last_request_started)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            self._last_request_started = time.monotonic()
        with self._metrics_lock:
            self.http_requests += 1
            self.rpc_items += rpc_items

    def _record_retry(self) -> None:
        with self._metrics_lock:
            self.retries_used += 1

    def _record_response(self, response_bytes: int) -> None:
        with self._metrics_lock:
            self.response_bytes += response_bytes

    def _block_timestamp_chunk(self, block_numbers: list[int]) -> dict[int, int]:
        request_id_to_block = {index + 1: block for index, block in enumerate(block_numbers)}
        body = [
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "eth_getBlockByNumber",
                "params": [hex(block), False],
            }
            for request_id, block in request_id_to_block.items()
        ]
        encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self._before_request(len(body))
            try:
                request = urllib.request.Request(
                    self.url,
                    data=encoded,
                    headers={"Content-Type": "application/json", "User-Agent": RPC_USER_AGENT},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=60) as response:
                    raw = response.read()
                self._record_response(len(raw))
                decoded = json.loads(raw)
                if not isinstance(decoded, list):
                    raise RuntimeError("RPC endpoint did not return a batch array")
                result: dict[int, int] = {}
                for item in decoded:
                    if item.get("error") is not None:
                        raise RuntimeError(f"RPC batch item error: {item['error']}")
                    request_id = int(item["id"])
                    block = request_id_to_block[request_id]
                    block_result = item.get("result")
                    if block_result is None:
                        raise RuntimeError(f"Block {block} was not returned")
                    result[block] = int(block_result["timestamp"], 16)
                if len(result) != len(block_numbers):
                    raise RuntimeError("RPC batch response did not cover every requested block")
                return result
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code in {400, 403, 405, 413}:
                    self._batch_supported = False
                    self.batch_fallbacks += 1
                    return self._individual_timestamp_chunk(block_numbers)
                if attempt < self.retries:
                    self._record_retry()
                    retry_after = exc.headers.get("Retry-After")
                    try:
                        retry_after_seconds = float(retry_after) if retry_after is not None else 0.0
                    except ValueError:
                        retry_after_seconds = 0.0
                    time.sleep(max(retry_after_seconds, min(60, 4 * 2**attempt)))
            except (OSError, urllib.error.URLError, json.JSONDecodeError, RuntimeError) as exc:
                last_error = exc
                if attempt < self.retries:
                    self._record_retry()
                    time.sleep(min(8, 2**attempt))
        raise RuntimeError(f"Unrecoverable block-timestamp batch failure: {last_error}")

    def _individual_timestamp_chunk(self, block_numbers: list[int]) -> dict[int, int]:
        with ThreadPoolExecutor(max_workers=self.single_workers) as executor:
            timestamps = list(executor.map(self._single_block_timestamp, block_numbers))
        return dict(zip(block_numbers, timestamps))

    def _single_block_timestamp(self, block_number: int) -> int:
        body = {
            "jsonrpc": "2.0",
            "id": block_number,
            "method": "eth_getBlockByNumber",
            "params": [hex(block_number), False],
        }
        encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self._before_request(1)
            try:
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
                with urllib.request.urlopen(request, timeout=60) as response:
                    raw = response.read()
                self._record_response(len(raw))
                decoded = json.loads(raw)
                if decoded.get("error") is not None:
                    raise RuntimeError(f"RPC item error for block {block_number}: {decoded['error']}")
                block_result = decoded.get("result")
                if block_result is None:
                    raise RuntimeError(f"Block {block_number} was not returned")
                return int(block_result["timestamp"], 16)
            except urllib.error.HTTPError as exc:
                last_error = exc
                if attempt < self.retries:
                    self._record_retry()
                    retry_after = exc.headers.get("Retry-After")
                    try:
                        retry_after_seconds = float(retry_after) if retry_after is not None else 0.0
                    except ValueError:
                        retry_after_seconds = 0.0
                    time.sleep(max(retry_after_seconds, min(60, 4 * 2**attempt)))
            except (OSError, urllib.error.URLError, json.JSONDecodeError, RuntimeError) as exc:
                last_error = exc
                if attempt < self.retries:
                    self._record_retry()
                    time.sleep(min(8, 2**attempt))
        raise RuntimeError(f"Unrecoverable timestamp lookup for block {block_number}: {last_error}")


def exact_day_boundaries(
    client: RpcBatchClient,
    start_utc: datetime,
    end_utc: datetime,
    start_block: int,
    end_block: int,
) -> list[dict[str, object]]:
    targets = [start_utc]
    cursor = datetime.combine(start_utc.date() + timedelta(days=1), dt_time.min, tzinfo=timezone.utc)
    while cursor <= end_utc:
        targets.append(cursor)
        cursor += timedelta(days=1)
    if targets[-1] != end_utc:
        targets.append(end_utc)

    target_unix = [int(item.timestamp()) for item in targets[1:]]
    lows = [start_block for _ in target_unix]
    highs = [end_block for _ in target_unix]
    timestamp_cache: dict[int, int] = {}
    while True:
        unresolved = [index for index in range(len(target_unix)) if lows[index] < highs[index]]
        if not unresolved:
            break
        mids = list(dict.fromkeys((lows[index] + highs[index]) // 2 for index in unresolved))
        missing = [block for block in mids if block not in timestamp_cache]
        if missing:
            timestamp_cache.update(client.block_timestamps(missing))
        for index in unresolved:
            mid = (lows[index] + highs[index]) // 2
            if timestamp_cache[mid] >= target_unix[index]:
                highs[index] = mid
            else:
                lows[index] = mid + 1

    blocks = [start_block] + lows
    if blocks[-1] != end_block:
        raise RuntimeError(f"Final UTC boundary resolved to {blocks[-1]}, expected {end_block}")

    verification_blocks = list(dict.fromkeys(blocks[1:] + [block - 1 for block in blocks[1:] if block > 0]))
    missing = [block for block in verification_blocks if block not in timestamp_cache]
    if missing:
        timestamp_cache.update(client.block_timestamps(missing))
    for index, target in enumerate(target_unix, start=1):
        block = blocks[index]
        if timestamp_cache[block] < target or timestamp_cache[block - 1] >= target:
            raise RuntimeError(f"UTC boundary verification failed for {targets[index].isoformat()}")

    return [
        {
            "boundary_utc": target.isoformat().replace("+00:00", "Z"),
            "block_number": block,
        }
        for target, block in zip(targets, blocks)
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rpc-url", default="https://arb1.arbitrum.io/rpc")
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    raw_root = workspace / "data" / "raw" / "morpho_full_window"
    shard_root = raw_root / "shards"
    manifest_path = raw_root / "manifest.json"
    boundaries_path = raw_root / "day_boundaries.json"
    data_root = workspace / "data"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "complete" or manifest.get("complete") is not True:
        raise RuntimeError("Full-window manifest is not complete; QA will not run on a partial extract")
    if manifest.get("contract_address") != MORPHO_ADDRESS:
        raise RuntimeError("Manifest contract address differs from the official scoped address")

    market_ids = {
        row["market_id"].lower()
        for row in csv.DictReader((data_root / "drip_morpho_markets.csv").open(encoding="utf-8", newline=""))
    }
    if len(market_ids) != 45:
        raise RuntimeError(f"Expected 45 market IDs, found {len(market_ids)}")
    if set(manifest.get("event_hashes", [])) != set(EVENTS) or set(manifest.get("market_ids", [])) != market_ids:
        raise RuntimeError("Manifest event-family or eligible-market scope differs from the QA scope")

    start_utc = parse_utc(manifest["start_utc"])
    end_utc = parse_utc(manifest["end_exclusive_utc"])
    start_block = int(manifest["start_block"])
    end_block = int(manifest["end_block_exclusive"])

    if boundaries_path.exists():
        boundary_document = json.loads(boundaries_path.read_text(encoding="utf-8"))
    else:
        client = RpcBatchClient(args.rpc_url)
        boundary_values = exact_day_boundaries(client, start_utc, end_utc, start_block, end_block)
        boundary_document = {
            "source": "official Arbitrum One public RPC batched eth_getBlockByNumber",
            "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "http_requests": client.http_requests,
            "rpc_items": client.rpc_items,
            "retries": client.retries_used,
            "response_bytes": client.response_bytes,
            "batch_fallbacks": client.batch_fallbacks,
            "boundaries": boundary_values,
        }
        atomic_write_json(boundaries_path, boundary_document)
    boundary_rpc_metrics = {
        "http_requests": int(boundary_document.get("http_requests", 0)),
        "rpc_items": int(boundary_document.get("rpc_items", 0)),
        "retries": int(boundary_document.get("retries", 0)),
        "response_bytes": int(boundary_document.get("response_bytes", 0)),
        "batch_fallbacks": int(boundary_document.get("batch_fallbacks", 0)),
    }
    boundaries = boundary_document["boundaries"]

    boundary_blocks = [int(item["block_number"]) for item in boundaries]
    if boundary_blocks[0] != start_block or boundary_blocks[-1] != end_block:
        raise RuntimeError("Cached day boundaries do not match manifest endpoints")
    if any(right <= left for left, right in zip(boundary_blocks, boundary_blocks[1:])):
        raise RuntimeError("Day-boundary blocks are not strictly increasing")

    daily_rows: list[dict[str, object]] = []
    for index in range(len(boundaries) - 1):
        interval_start = parse_utc(str(boundaries[index]["boundary_utc"]))
        interval_end = parse_utc(str(boundaries[index + 1]["boundary_utc"]))
        date_label = interval_start.date().isoformat()
        row: dict[str, object] = {
            "date_utc": date_label,
            "window_start_utc": interval_start.isoformat().replace("+00:00", "Z"),
            "window_end_exclusive_utc": interval_end.isoformat().replace("+00:00", "Z"),
            "start_block": int(boundaries[index]["block_number"]),
            "end_block_exclusive": int(boundaries[index + 1]["block_number"]),
            "event_count": 0,
        }
        for family in FAMILIES:
            row[family] = 0
        daily_rows.append(row)

    manifest_entries = manifest["shards"]
    manifest_files = [entry["file"] for entry in manifest_entries]
    actual_files = sorted(path.name for path in shard_root.glob("*.jsonl"))
    part_files = sorted(path.name for path in shard_root.glob("*.part"))
    unreferenced_files = sorted(set(actual_files) - set(manifest_files))
    missing_files = sorted(set(manifest_files) - set(actual_files))

    seen_keys: set[tuple[int, str, int]] = set()
    total_rows = 0
    removed_logs = 0
    duplicate_keys = 0
    checksum_mismatches = 0
    row_count_mismatches = 0
    shard_family_mismatches = 0
    scope_mismatches = 0
    rows_outside_shard = 0
    ordering_violations = 0
    gaps = 0
    overlaps = 0
    family_counts: Counter[str] = Counter()
    expected_block = start_block
    previous_ordering: tuple[int, int, int] | None = None

    for expected_range_id, entry in enumerate(manifest_entries, start=1):
        if int(entry["range_id"]) != expected_range_id or entry.get("status") != "verified":
            raise RuntimeError(f"Invalid range id/status at manifest position {expected_range_id}")
        from_block = int(entry["from_block"])
        to_block = int(entry["to_block_exclusive"])
        if from_block > expected_block:
            gaps += 1
        elif from_block < expected_block:
            overlaps += 1
        expected_block = to_block
        path = shard_root / entry["file"]
        if not path.exists():
            continue
        if sha256_file(path) != entry["checksum_sha256"].lower():
            checksum_mismatches += 1
        shard_rows = 0
        shard_removed = 0
        shard_families: Counter[str] = Counter()
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                block = int(row["block_number"])
                transaction_hash = str(row["transaction_hash"]).lower()
                log_index = int(row["log_index"])
                transaction_index = int(row["transaction_index"])
                if block < from_block or block >= to_block:
                    rows_outside_shard += 1
                topics = json.loads(row["topics_json"])
                topic0 = str(topics[0]).lower() if topics else ""
                topic1 = str(topics[1]).lower() if len(topics) > 1 else ""
                family = EVENTS.get(topic0)
                if row.get("address") != MORPHO_ADDRESS or family is None or topic1 not in market_ids:
                    scope_mismatches += 1
                else:
                    family_counts[family] += 1
                    shard_families[family] += 1
                key = (block, transaction_hash, log_index)
                if key in seen_keys:
                    duplicate_keys += 1
                else:
                    seen_keys.add(key)
                ordering = (block, transaction_index, log_index)
                if previous_ordering is not None and ordering < previous_ordering:
                    ordering_violations += 1
                previous_ordering = ordering
                if bool(row.get("removed")):
                    removed_logs += 1
                    shard_removed += 1
                day_index = bisect.bisect_right(boundary_blocks, block) - 1
                if day_index < 0 or day_index >= len(daily_rows):
                    raise RuntimeError(f"Block {block} falls outside UTC day boundaries")
                daily = daily_rows[day_index]
                daily["event_count"] = int(daily["event_count"]) + 1
                if family is not None:
                    daily[family] = int(daily[family]) + 1
                total_rows += 1
                shard_rows += 1
        if shard_rows != int(entry["row_count"]) or shard_removed != int(entry["removed_count"]):
            row_count_mismatches += 1
        for family in FAMILIES:
            if shard_families[family] != int(entry["event_family_counts"].get(family, 0)):
                shard_family_mismatches += 1

    if expected_block < end_block:
        gaps += 1
    elif expected_block > end_block:
        overlaps += 1

    manifest_family_mismatches = sum(
        1 for family in FAMILIES if family_counts[family] != int(manifest["event_family_counts"].get(family, 0))
    )
    manifest_aggregate_mismatches = sum(
        [
            total_rows != int(manifest["row_count"]),
            removed_logs != int(manifest["removed_log_count"]),
            len(manifest_entries) != int(manifest["verified_shard_count"]),
            expected_block != end_block,
        ]
    )
    daily_sum = sum(int(row["event_count"]) for row in daily_rows)
    family_sum = sum(family_counts.values())
    daily_reconciliation_mismatches = int(daily_sum != total_rows) + int(family_sum != total_rows)

    qa_pass = all(
        value == 0
        for value in [
            len(part_files),
            len(unreferenced_files),
            len(missing_files),
            gaps,
            overlaps,
            checksum_mismatches,
            row_count_mismatches,
            shard_family_mismatches,
            scope_mismatches,
            rows_outside_shard,
            duplicate_keys,
            removed_logs,
            ordering_violations,
            manifest_family_mismatches,
            manifest_aggregate_mismatches,
            daily_reconciliation_mismatches,
        ]
    )

    family_rows = [
        {"event_family": family, "event_count": family_counts[family], "share_of_events": family_counts[family] / total_rows if total_rows else 0}
        for family in FAMILIES
    ]
    boundary_rows = [
        {"boundary_utc": item["boundary_utc"], "block_number": item["block_number"]}
        for item in boundaries
    ]
    summary = {
        "test": "independent full-window manifest, shard, scope, uniqueness, removed, and UTC-day QA",
        "qa_pass": qa_pass,
        "source": "official Arbitrum One RPC raw shards; no full-window GBA query",
        "start_utc": manifest["start_utc"],
        "end_exclusive_utc": manifest["end_exclusive_utc"],
        "start_block": start_block,
        "end_block_exclusive": end_block,
        "block_count": end_block - start_block,
        "manifest_sha256": sha256_file(manifest_path),
        "verified_shards": len(manifest_entries),
        "actual_shard_files": len(actual_files),
        "total_rows": total_rows,
        "unique_keys": len(seen_keys),
        "duplicate_keys": duplicate_keys,
        "removed_logs": removed_logs,
        "gaps": gaps,
        "overlaps": overlaps,
        "checksum_mismatches": checksum_mismatches,
        "row_count_mismatches": row_count_mismatches,
        "shard_family_mismatches": shard_family_mismatches,
        "scope_mismatches": scope_mismatches,
        "rows_outside_shard": rows_outside_shard,
        "ordering_violations": ordering_violations,
        "part_files": part_files,
        "unreferenced_files": unreferenced_files,
        "missing_files": missing_files,
        "manifest_family_mismatches": manifest_family_mismatches,
        "manifest_aggregate_mismatches": manifest_aggregate_mismatches,
        "daily_reconciliation_mismatches": daily_reconciliation_mismatches,
        "utc_day_rows": len(daily_rows),
        "utc_boundary_rows": len(boundaries),
        "daily_event_sum": daily_sum,
        "family_event_sum": family_sum,
        "event_family_counts": {family: family_counts[family] for family in FAMILIES},
        "boundary_rpc": boundary_rpc_metrics,
        "completed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    atomic_write_csv(
        data_root / "morpho_full_window_daily_event_counts.csv",
        ["date_utc", "window_start_utc", "window_end_exclusive_utc", "start_block", "end_block_exclusive", "event_count", *FAMILIES],
        daily_rows,
    )
    atomic_write_csv(
        data_root / "morpho_full_window_event_family_counts.csv",
        ["event_family", "event_count", "share_of_events"],
        family_rows,
    )
    atomic_write_csv(
        data_root / "morpho_full_window_day_boundaries.csv",
        ["boundary_utc", "block_number"],
        boundary_rows,
    )
    atomic_write_json(data_root / "morpho_full_window_qa_summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 0 if qa_pass else 3


if __name__ == "__main__":
    raise SystemExit(main())
