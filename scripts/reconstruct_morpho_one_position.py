#!/usr/bin/env python3
"""Bounded Morpho one-position replay from the immutable Phase 2 RPC shards.

The script never calls eth_getLogs and never writes to the sealed Phase 3
selection cache.  Anchor/final state is read from that cache through an
immutable SQLite connection.  The precommitted intermediate checkpoint is
queried through a separate, identity-bound SQLite cache.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sqlite3
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from morpho_archive_rpc_cache import (
    ArchiveRpcCache,
    CachedArchiveSession,
    EXPECTED_CHAIN_ID,
    canonical_json,
    sha256_text,
)
from select_morpho_one_position import (
    EVENTS,
    FEE_RECIPIENT_SELECTOR,
    MARKET_SELECTOR,
    MORPHO_ADDRESS,
    OWNER_TOPIC_INDEX,
    POSITION_SELECTOR,
    RpcClient,
    archive_market_call,
    archive_position_call,
    decode_words,
    topic_address,
    validate_live_chain,
)


SCRIPT_VERSION = "morpho-phase3-one-position-replay-v1"
INTERMEDIATE_CACHE_VERSION = "morpho-phase3-one-position-intermediate-cache-v1"
VIRTUAL_SHARES = 1_000_000
VIRTUAL_ASSETS = 1

EXPECTED_TOPIC_COUNTS = {
    "Supply": 4,
    "Withdraw": 4,
    "Borrow": 4,
    "Repay": 4,
    "SupplyCollateral": 4,
    "WithdrawCollateral": 4,
    "Liquidate": 4,
    "AccrueInterest": 2,
}
EXPECTED_DATA_WORDS = {
    "Supply": 2,
    "Withdraw": 3,
    "Borrow": 3,
    "Repay": 2,
    "SupplyCollateral": 1,
    "WithdrawCollateral": 2,
    "Liquidate": 5,
    "AccrueInterest": 3,
}


class ReconstructionError(RuntimeError):
    """A fail-closed evidence or accounting mismatch."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="data/raw/morpho_full_window/manifest.json")
    parser.add_argument("--selection", default="data/morpho_one_position_selection.json")
    parser.add_argument(
        "--structural-candidates", default="data/morpho_phase3_structural_candidates.json"
    )
    parser.add_argument(
        "--checkpoint-plan", default="data/morpho_one_position_checkpoint_plan.json"
    )
    parser.add_argument(
        "--sealed-selection-cache", default="data/tmp/morpho_phase3_archive_rpc.sqlite"
    )
    parser.add_argument(
        "--intermediate-cache", default="data/tmp/morpho_phase3_one_position_rpc.sqlite"
    )
    parser.add_argument("--rpc-url", default="https://arbitrum-one.public.blastapi.io")
    parser.add_argument("--offline-only", action="store_true")
    parser.add_argument("--retries", type=int, default=8)
    parser.add_argument("--min-request-interval", type=float, default=0.75)
    parser.add_argument(
        "--market-events-output", default="data/morpho_one_position_market_events.csv"
    )
    parser.add_argument("--sample-output", default="data/morpho_one_position_sample.csv")
    parser.add_argument(
        "--qa-output", default="data/morpho_one_position_reconstruction_qa.json"
    )
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ReconstructionError(f"Expected JSON object: {path}")
    return value


def atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="",
    )
    os.replace(part, path)


def atomic_write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ReconstructionError(f"Refusing to write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    with part.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(part, path)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReconstructionError(message)


def canonical_pair_hash(market_id: str, wallet: str) -> tuple[str, str]:
    preimage = f"morpho-phase3-v1|{market_id.lower()}|{wallet.lower()}"
    return preimage, hashlib.sha256(preimage.encode("ascii")).hexdigest()


def div_up(numerator: int, denominator: int) -> int:
    require(denominator > 0, "Division by zero in share conversion")
    return (numerator + denominator - 1) // denominator


def to_shares_down(assets: int, total_assets: int, total_shares: int) -> int:
    return assets * (total_shares + VIRTUAL_SHARES) // (total_assets + VIRTUAL_ASSETS)


def to_shares_up(assets: int, total_assets: int, total_shares: int) -> int:
    return div_up(assets * (total_shares + VIRTUAL_SHARES), total_assets + VIRTUAL_ASSETS)


def to_assets_down(shares: int, total_assets: int, total_shares: int) -> int:
    return shares * (total_assets + VIRTUAL_ASSETS) // (total_shares + VIRTUAL_SHARES)


def to_assets_up(shares: int, total_assets: int, total_shares: int) -> int:
    return div_up(shares * (total_assets + VIRTUAL_ASSETS), total_shares + VIRTUAL_SHARES)


def decode_address_word(word: int) -> str:
    require(word < 1 << 160, "ABI address word has non-zero high bytes")
    return "0x" + word.to_bytes(20, "big").hex()


def decode_data_words(data: str, expected_words: int) -> list[int]:
    require(isinstance(data, str) and data.startswith("0x"), "Event data is not hexadecimal")
    payload = data[2:].lower()
    require(len(payload) == expected_words * 64, "Unexpected event data length")
    require(all(character in "0123456789abcdef" for character in payload), "Non-hex event data")
    return [int(payload[offset : offset + 64], 16) for offset in range(0, len(payload), 64)]


def decode_event(row: dict[str, Any], selected_market: str) -> dict[str, Any] | None:
    topics = json.loads(str(row["topics_json"]))
    require(isinstance(topics, list) and topics, "topics_json is not a non-empty array")
    topics = [str(topic).lower() for topic in topics]
    family = EVENTS.get(topics[0])
    require(family is not None, f"Unexpected scoped topic0 {topics[0]}")
    require(len(topics) == EXPECTED_TOPIC_COUNTS[family], f"Unexpected topics length for {family}")
    require(len(topics[1]) == 66 and topics[1].startswith("0x"), "Malformed market topic")
    if topics[1] != selected_market:
        return None
    words = decode_data_words(str(row["data"]), EXPECTED_DATA_WORDS[family])
    event: dict[str, Any] = {
        "block_number": int(row["block_number"]),
        "transaction_index": int(row["transaction_index"]),
        "log_index": int(row["log_index"]),
        "transaction_hash": str(row["transaction_hash"]).lower(),
        "address": str(row["address"]).lower(),
        "topics_json": canonical_json(topics),
        "data": str(row["data"]).lower(),
        "family": family,
        "market_id": topics[1],
        "owner": "",
        "caller": "",
        "assets": None,
        "shares": None,
        "interest": None,
        "fee_shares": None,
        "repaid_assets": None,
        "repaid_shares": None,
        "seized_assets": None,
        "bad_debt_assets": None,
        "bad_debt_shares": None,
    }
    if family in OWNER_TOPIC_INDEX:
        event["owner"] = topic_address(topics[OWNER_TOPIC_INDEX[family]])
    if family == "Supply":
        event["caller"] = topic_address(topics[2])
        event["assets"], event["shares"] = words
    elif family == "Withdraw":
        event["caller"] = decode_address_word(words[0])
        event["assets"], event["shares"] = words[1:]
    elif family == "Borrow":
        event["caller"] = decode_address_word(words[0])
        event["assets"], event["shares"] = words[1:]
    elif family == "Repay":
        event["caller"] = topic_address(topics[2])
        event["assets"], event["shares"] = words
    elif family == "SupplyCollateral":
        event["caller"] = topic_address(topics[2])
        event["assets"] = words[0]
    elif family == "WithdrawCollateral":
        event["caller"] = decode_address_word(words[0])
        event["assets"] = words[1]
    elif family == "Liquidate":
        event["caller"] = topic_address(topics[2])
        (
            event["repaid_assets"],
            event["repaid_shares"],
            event["seized_assets"],
            event["bad_debt_assets"],
            event["bad_debt_shares"],
        ) = words
    elif family == "AccrueInterest":
        event["prev_borrow_rate"], event["interest"], event["fee_shares"] = words
    return event


def verify_selection_inputs(
    manifest_path: Path,
    selection_path: Path,
    structural_path: Path,
    checkpoint_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest = load_json(manifest_path)
    selection = load_json(selection_path)
    structural = load_json(structural_path)
    checkpoint = load_json(checkpoint_path)
    manifest_sha = sha256_file(manifest_path)
    selection_sha = sha256_file(selection_path)
    structural_sha = sha256_file(structural_path)
    checkpoint_sha = sha256_file(checkpoint_path)

    require(manifest.get("status") == "complete" and manifest.get("complete") is True, "Manifest is not complete")
    require(int(manifest.get("verified_shard_count", -1)) == 3157, "Manifest shard count changed")
    require(int(manifest.get("row_count", -1)) == 1_231_462, "Manifest row count changed")
    require(int(manifest.get("start_block", -1)) == 355_887_376, "Manifest start block changed")
    require(int(manifest.get("end_block_exclusive", -1)) == 495_647_034, "Manifest end block changed")
    require(selection.get("status") == "complete", "Selection artifact is not complete")
    require(selection["source"]["manifest_sha256"] == manifest_sha, "Selection/manifest SHA mismatch")
    require(int(selection["source"]["verified_shards"]) == int(manifest["verified_shard_count"]), "Selection shard count mismatch")
    require(int(selection["source"]["rows"]) == int(manifest["row_count"]), "Selection row count mismatch")
    require(int(selection.get("eligible_candidate_count", -1)) == 5575, "Eligible candidate count changed")
    require(int(selection.get("selected_rank", -1)) == 1, "Selected rank is not one")

    selected = selection["selected"]
    market_id = str(selected["market_id"]).lower()
    wallet = str(selected["wallet"]).lower()
    preimage, pair_hash = canonical_pair_hash(market_id, wallet)
    require(selected["selection_preimage"] == preimage, "Selection preimage mismatch")
    require(selected["selection_sha256"] == pair_hash, "Selection SHA-256 mismatch")
    require(selection["top_ranked_candidates"][0]["selection_sha256"] == pair_hash, "Rank-1 list mismatch")
    require(selection["top_ranked_candidates"][0]["market_id"] == market_id, "Rank-1 market mismatch")
    require(selection["top_ranked_candidates"][0]["wallet"] == wallet, "Rank-1 wallet mismatch")
    require(market_id in [str(value).lower() for value in manifest["market_ids"]], "Selected market outside manifest scope")

    require(int(structural.get("candidate_count", -1)) == 5575, "Structural population count changed")
    require(structural.get("manifest_sha256") == manifest_sha, "Structural population/manifest mismatch")
    require(
        isinstance(structural.get("candidate_population_sha256"), str)
        and len(structural["candidate_population_sha256"]) == 64,
        "Structural population SHA is malformed",
    )
    matches = [
        row
        for row in structural["candidates"]
        if str(row["market_id"]).lower() == market_id and str(row["wallet"]).lower() == wallet
    ]
    require(len(matches) == 1, "Selected pair is not unique in structural population")
    structural_selected = matches[0]
    require(int(structural_selected["event_count"]) == int(selected["position_event_count"]), "Stored position-event count mismatch")
    require(structural_selected["family_counts"] == selected["event_family_counts"], "Stored family counts mismatch")
    require(structural_selected["first_order"] == [selected["first_event"][key] for key in ("block_number", "transaction_index", "log_index")], "Stored first order mismatch")
    require(structural_selected["last_order"] == [selected["last_event"][key] for key in ("block_number", "transaction_index", "log_index")], "Stored last order mismatch")

    require(checkpoint["selection_sha256"] == pair_hash, "Checkpoint plan belongs to another selection")
    require(checkpoint["market_id"] == market_id and checkpoint["wallet"] == wallet, "Checkpoint plan pair mismatch")
    require(int(checkpoint["anchor"]["block_number"]) == int(selected["anchor_block"]), "Checkpoint anchor mismatch")
    require(int(checkpoint["intermediate"]["block_number"]) == int(selected["first_event"]["block_number"]), "Intermediate is not first-event block")
    require(int(checkpoint["final"]["block_number"]) == int(selected["final_checkpoint_block"]), "Checkpoint final mismatch")
    require(checkpoint["ordering"] == ["block_number", "transaction_index", "log_index"], "Ordering rule changed")

    evidence = {
        "manifest_sha256": manifest_sha,
        "selection_artifact_sha256": selection_sha,
        "structural_candidates_sha256": structural_sha,
        "checkpoint_plan_sha256": checkpoint_sha,
        "manifest_complete": True,
        "manifest_verified_shards": int(manifest["verified_shard_count"]),
        "manifest_rows": int(manifest["row_count"]),
        "eligible_candidates": int(selection["eligible_candidate_count"]),
        "selected_rank": int(selection["selected_rank"]),
        "archive_session_metrics": selection["archive_session_metrics"],
        "declared_selection_cache_audit": selection["cache_audit"],
        "archive_gate_defects": selection["rpc_diagnostics"],
        "selection_preimage": preimage,
        "selection_sha256": pair_hash,
        "structural_selected_record": structural_selected,
    }
    return manifest, selection, structural, checkpoint, evidence


def expected_call_data(abi_method: str, market_id: str, wallet: str) -> tuple[str, int]:
    if abi_method == "position":
        return "0x" + POSITION_SELECTOR + market_id[2:] + wallet[2:].rjust(64, "0"), 3
    if abi_method == "market":
        return "0x" + MARKET_SELECTOR + market_id[2:], 6
    if abi_method == "feeRecipient":
        return "0x" + FEE_RECIPIENT_SELECTOR, 1
    raise ReconstructionError(f"Unsupported sealed-cache ABI method {abi_method}")


def audit_sealed_cache(
    cache_path: Path,
    selection: dict[str, Any],
    structural: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, tuple[int, ...]]]:
    require(cache_path.exists(), f"Missing sealed selection cache: {cache_path}")
    wal_path = Path(str(cache_path) + "-wal")
    require(not wal_path.exists() or wal_path.stat().st_size == 0, "Sealed cache has a non-empty WAL")
    before_sha = sha256_file(cache_path)
    uri = "file:" + cache_path.resolve().as_posix() + "?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        require(integrity == "ok", f"Sealed SQLite integrity is {integrity}")
        identity_row = connection.execute("SELECT * FROM cache_identity WHERE singleton=1").fetchone()
        require(identity_row is not None, "Sealed cache identity is missing")
        identity_json = str(identity_row["identity_json"])
        identity = json.loads(identity_json)
        require(sha256_text(identity_json) == str(identity_row["identity_sha256"]), "Sealed cache identity checksum mismatch")
        expected_identity = {
            "chain_id": EXPECTED_CHAIN_ID,
            "contract_address": MORPHO_ADDRESS,
            "manifest_sha256": selection["source"]["manifest_sha256"],
            "manifest_rows": int(selection["source"]["rows"]),
            "manifest_verified_shards": int(selection["source"]["verified_shards"]),
            "candidate_population_count": int(structural["candidate_count"]),
            "candidate_population_sha256": structural["candidate_population_sha256"],
        }
        for key, value in expected_identity.items():
            require(identity.get(key) == value, f"Sealed cache identity mismatch for {key}")

        invalid = 0
        rows = connection.execute("SELECT * FROM rpc_cache").fetchall()
        for row in rows:
            try:
                abi_method = str(row["abi_method"])
                market_id = str(row["market_id"])
                wallet = str(row["wallet"])
                call_data, expected_words = expected_call_data(abi_method, market_id, wallet)
                require(str(row["rpc_method"]) == "eth_call", "Non-eth_call row")
                require(int(row["chain_id"]) == EXPECTED_CHAIN_ID, "Wrong cached chain")
                require(str(row["contract_address"]) == MORPHO_ADDRESS, "Wrong cached contract")
                require(str(row["call_data"]) == call_data, "Cached calldata mismatch")
                require(int(row["expected_words"]) == expected_words, "Cached ABI word count mismatch")
                result = str(row["result_hex"]).lower()
                require(len(result) == 2 + 64 * expected_words and result.startswith("0x"), "Cached ABI result length mismatch")
                int(result[2:] or "0", 16)
                key_payload = {
                    "chain_id": EXPECTED_CHAIN_ID,
                    "contract_address": MORPHO_ADDRESS,
                    "rpc_method": "eth_call",
                    "abi_method": abi_method,
                    "block_number": int(row["block_number"]),
                    "market_id": market_id,
                    "wallet": wallet,
                }
                key_hash = sha256_text(canonical_json(key_payload))
                require(key_hash == str(row["key_sha256"]), "Cached key checksum mismatch")
                response_payload = key_payload | {
                    "call_data": call_data,
                    "expected_words": expected_words,
                    "result_hex": result,
                }
                require(sha256_text(canonical_json(response_payload)) == str(row["response_sha256"]), "Cached response checksum mismatch")
            except (ReconstructionError, ValueError):
                invalid += 1
        require(invalid == 0, f"Sealed cache has {invalid} invalid rows")

        duplicate_groups = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM (
                  SELECT chain_id, contract_address, rpc_method, abi_method,
                         block_number, market_id, wallet, COUNT(*) n
                  FROM rpc_cache
                  GROUP BY 1,2,3,4,5,6,7 HAVING n > 1
                )
                """
            ).fetchone()[0]
        )
        progress_count, progress_min, progress_max = connection.execute(
            "SELECT COUNT(*), MIN(ordinal), MAX(ordinal) FROM progress"
        ).fetchone()
        checkpoint = connection.execute("SELECT contiguous_through FROM checkpoint WHERE singleton=1").fetchone()
        orphan_progress = int(
            connection.execute(
                "SELECT COUNT(*) FROM progress p LEFT JOIN rpc_cache r ON r.key_sha256=p.key_sha256 WHERE r.key_sha256 IS NULL"
            ).fetchone()[0]
        )
        contiguous = int(checkpoint[0]) if checkpoint is not None else -2
        require(duplicate_groups == 0, "Sealed cache has duplicate key groups")
        require(int(progress_count) == contiguous + 1, "Sealed cache progress count/checkpoint mismatch")
        require(int(progress_min) == 0 and int(progress_max) == contiguous, "Sealed cache progress is not contiguous")
        require(orphan_progress == 0, "Sealed cache has orphan progress rows")

        selected = selection["selected"]
        market_id = selected["market_id"]
        wallet = selected["wallet"]
        blocks = [int(selected["anchor_block"]), int(selected["final_checkpoint_block"])]
        selected_rows = connection.execute(
            """
            SELECT abi_method, block_number, result_hex
            FROM rpc_cache
            WHERE market_id=? AND block_number IN (?,?) AND (wallet=? OR wallet='')
            ORDER BY block_number, abi_method
            """,
            (market_id, blocks[0], blocks[1], wallet),
        ).fetchall()
        require(len(selected_rows) == 4, "Sealed cache lacks exact anchor/final market+position rows")
        states: dict[str, tuple[int, ...]] = {}
        for row in selected_rows:
            label = "anchor" if int(row["block_number"]) == blocks[0] else "final"
            method = str(row["abi_method"])
            states[f"{label}_{method}"] = decode_words(str(row["result_hex"]), 3 if method == "position" else 6)
        require(states["anchor_position"] == (0, 0, 0), "Anchor position is not zero")
        require(states["final_position"] == (0, 0, 0), "Final position is not zero")
        audit = {
            "sqlite_integrity": integrity,
            "sqlite_sha256_before": before_sha,
            "identity_sha256": str(identity_row["identity_sha256"]),
            "cache_entries": len(rows),
            "invalid_entries": invalid,
            "duplicate_key_groups": duplicate_groups,
            "checkpoint_contiguous_through": contiguous,
            "progress_rows": int(progress_count),
            "orphan_progress_rows": orphan_progress,
            "wal_bytes": wal_path.stat().st_size if wal_path.exists() else 0,
            "read_mode": "mode=ro&immutable=1",
        }
    finally:
        connection.close()
    after_sha = sha256_file(cache_path)
    require(before_sha == after_sha, "Read-only sealed-cache verification changed the SQLite file")
    audit["sqlite_sha256_after"] = after_sha
    audit["unchanged"] = True
    return audit, states


def collect_market_events(
    manifest_path: Path,
    manifest: dict[str, Any],
    market_id: str,
    start_block: int,
    end_block_exclusive: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    shards = [
        shard
        for shard in manifest["shards"]
        if int(shard["from_block"]) < end_block_exclusive
        and int(shard["to_block_exclusive"]) > start_block
    ]
    require(shards, "No manifest shards overlap replay range")
    shards.sort(key=lambda row: int(row["from_block"]))
    require(int(shards[0]["from_block"]) <= start_block, "First replay shard starts after replay range")
    require(int(shards[-1]["to_block_exclusive"]) >= end_block_exclusive, "Last replay shard ends before replay range")
    for previous, current in zip(shards, shards[1:]):
        require(int(previous["to_block_exclusive"]) == int(current["from_block"]), "Replay shards have a gap or overlap")

    events: list[dict[str, Any]] = []
    scanned_rows = 0
    verified_bytes = 0
    shard_directory = manifest_path.parent / "shards"
    for shard in shards:
        require(shard["status"] == "verified", f"Replay shard {shard['range_id']} is not verified")
        path = shard_directory / str(shard["file"])
        require(path.exists(), f"Missing replay shard {path}")
        require(path.stat().st_size == int(shard["file_bytes"]), f"Replay shard byte count mismatch: {path.name}")
        require(sha256_file(path) == shard["checksum_sha256"], f"Replay shard checksum mismatch: {path.name}")
        verified_bytes += path.stat().st_size
        with path.open("r", encoding="utf-8") as handle:
            shard_rows = 0
            for line in handle:
                shard_rows += 1
                scanned_rows += 1
                row = json.loads(line)
                block_number = int(row["block_number"])
                if block_number < start_block or block_number >= end_block_exclusive:
                    continue
                require(str(row["address"]).lower() == MORPHO_ADDRESS, "Replay row has wrong contract")
                require(row.get("removed") is False, "Replay row is removed")
                event = decode_event(row, market_id)
                if event is not None:
                    events.append(event)
            require(shard_rows == int(shard["row_count"]), f"Replay shard row count mismatch: {path.name}")

    events.sort(key=lambda row: (row["block_number"], row["transaction_index"], row["log_index"]))
    keys = [(row["block_number"], row["transaction_hash"], row["log_index"]) for row in events]
    order = [(row["block_number"], row["transaction_index"], row["log_index"]) for row in events]
    require(len(keys) == len(set(keys)), "Duplicate event keys in selected-market replay")
    require(len(order) == len(set(order)), "Duplicate deterministic order keys in selected-market replay")
    evidence = {
        "overlapping_verified_shards": len(shards),
        "first_shard_range_id": int(shards[0]["range_id"]),
        "last_shard_range_id": int(shards[-1]["range_id"]),
        "verified_shard_bytes": verified_bytes,
        "scanned_rows_in_overlapping_shards": scanned_rows,
        "selected_market_events": len(events),
        "event_family_counts": dict(sorted(Counter(row["family"] for row in events).items())),
        "unique_event_keys": len(set(keys)),
        "duplicate_event_keys": len(keys) - len(set(keys)),
        "duplicate_order_keys": len(order) - len(set(order)),
    }
    return events, evidence


def state_from_words(position: tuple[int, ...], market: tuple[int, ...]) -> dict[str, int]:
    return {
        "wallet_supply_shares": position[0],
        "wallet_borrow_shares": position[1],
        "wallet_collateral_assets": position[2],
        "total_supply_assets": market[0],
        "total_supply_shares": market[1],
        "total_borrow_assets": market[2],
        "total_borrow_shares": market[3],
        "last_update": market[4],
        "fee": market[5],
    }


def state_assets(state: dict[str, int]) -> dict[str, int]:
    return {
        "wallet_supply_assets_down": to_assets_down(
            state["wallet_supply_shares"], state["total_supply_assets"], state["total_supply_shares"]
        ),
        "wallet_borrow_assets_up": to_assets_up(
            state["wallet_borrow_shares"], state["total_borrow_assets"], state["total_borrow_shares"]
        ),
    }


def rounding_check(event: dict[str, Any], state: dict[str, int]) -> str:
    family = event["family"]
    if family not in {"Supply", "Withdraw", "Borrow", "Repay", "Liquidate"}:
        return "not_applicable"
    if family == "Liquidate":
        expected = to_assets_up(
            int(event["repaid_shares"]), state["total_borrow_assets"], state["total_borrow_shares"]
        )
        return "pass" if expected == int(event["repaid_assets"]) else "fail"
    assets = int(event["assets"])
    shares = int(event["shares"])
    if family in {"Supply", "Withdraw"}:
        total_assets = state["total_supply_assets"]
        total_shares = state["total_supply_shares"]
    else:
        total_assets = state["total_borrow_assets"]
        total_shares = state["total_borrow_shares"]
    if family in {"Supply", "Repay"}:
        matches_assets_input = shares == to_shares_down(assets, total_assets, total_shares)
        matches_shares_input = assets == to_assets_up(shares, total_assets, total_shares)
    else:
        matches_assets_input = shares == to_shares_up(assets, total_assets, total_shares)
        matches_shares_input = assets == to_assets_down(shares, total_assets, total_shares)
    return "pass" if matches_assets_input or matches_shares_input else "fail"


def assert_nonnegative(state: dict[str, int], event: dict[str, Any]) -> None:
    fields = [
        "wallet_supply_shares",
        "wallet_borrow_shares",
        "wallet_collateral_assets",
        "total_supply_assets",
        "total_supply_shares",
        "total_borrow_assets",
        "total_borrow_shares",
    ]
    negatives = {field: state[field] for field in fields if state[field] < 0}
    require(not negatives, f"Negative balance after {event['family']} {event['block_number']}/{event['log_index']}: {negatives}")


def apply_event(event: dict[str, Any], state: dict[str, int], selected_wallet: str) -> str:
    family = event["family"]
    rounding = rounding_check(event, state)
    require(rounding != "fail", f"Assets/shares rounding mismatch at {event['block_number']}/{event['log_index']}")
    is_selected = event["owner"] == selected_wallet
    if family == "Supply":
        assets, shares = int(event["assets"]), int(event["shares"])
        state["total_supply_assets"] += assets
        state["total_supply_shares"] += shares
        if is_selected:
            state["wallet_supply_shares"] += shares
    elif family == "Withdraw":
        assets, shares = int(event["assets"]), int(event["shares"])
        state["total_supply_assets"] -= assets
        state["total_supply_shares"] -= shares
        if is_selected:
            state["wallet_supply_shares"] -= shares
    elif family == "Borrow":
        assets, shares = int(event["assets"]), int(event["shares"])
        state["total_borrow_assets"] += assets
        state["total_borrow_shares"] += shares
        if is_selected:
            state["wallet_borrow_shares"] += shares
    elif family == "Repay":
        assets, shares = int(event["assets"]), int(event["shares"])
        state["total_borrow_assets"] = max(0, state["total_borrow_assets"] - assets)
        state["total_borrow_shares"] -= shares
        if is_selected:
            state["wallet_borrow_shares"] -= shares
    elif family == "SupplyCollateral":
        if is_selected:
            state["wallet_collateral_assets"] += int(event["assets"])
    elif family == "WithdrawCollateral":
        if is_selected:
            state["wallet_collateral_assets"] -= int(event["assets"])
    elif family == "AccrueInterest":
        interest, fee_shares = int(event["interest"]), int(event["fee_shares"])
        state["total_borrow_assets"] += interest
        state["total_supply_assets"] += interest
        state["total_supply_shares"] += fee_shares
    elif family == "Liquidate":
        repaid_assets = int(event["repaid_assets"])
        repaid_shares = int(event["repaid_shares"])
        seized_assets = int(event["seized_assets"])
        bad_debt_assets = int(event["bad_debt_assets"])
        bad_debt_shares = int(event["bad_debt_shares"])
        state["total_borrow_assets"] = max(0, state["total_borrow_assets"] - repaid_assets)
        state["total_borrow_shares"] -= repaid_shares
        state["total_borrow_assets"] -= bad_debt_assets
        state["total_supply_assets"] -= bad_debt_assets
        state["total_borrow_shares"] -= bad_debt_shares
        if is_selected:
            state["wallet_borrow_shares"] -= repaid_shares + bad_debt_shares
            state["wallet_collateral_assets"] -= seized_assets
    else:
        raise ReconstructionError(f"Unsupported event family {family}")
    assert_nonnegative(state, event)
    return rounding


def replay(
    events: list[dict[str, Any]],
    anchor_state: dict[str, int],
    selected_wallet: str,
    intermediate_block: int,
) -> tuple[dict[str, int], dict[str, int], list[dict[str, Any]], dict[str, Any]]:
    state = deepcopy(anchor_state)
    wallet_rows: list[dict[str, Any]] = []
    rounding_counts: Counter[str] = Counter()
    intermediate_state: dict[str, int] | None = None
    selected_keys: list[str] = []
    for index, event in enumerate(events, start=1):
        pre = deepcopy(state)
        rounding = apply_event(event, state, selected_wallet)
        rounding_counts[rounding] += 1
        if event["owner"] == selected_wallet:
            selected_keys.append(
                f"{event['block_number']}|{event['transaction_hash']}|{event['log_index']}"
            )
            wallet_rows.append(
                {
                    "wallet_event_sequence": len(wallet_rows) + 1,
                    "market_event_sequence": index,
                    "block_number": event["block_number"],
                    "transaction_index": event["transaction_index"],
                    "log_index": event["log_index"],
                    "transaction_hash": event["transaction_hash"],
                    "event_family": event["family"],
                    "market_id": event["market_id"],
                    "position_owner": event["owner"],
                    "assets": "" if event["assets"] is None else event["assets"],
                    "shares": "" if event["shares"] is None else event["shares"],
                    "repaid_assets": "" if event["repaid_assets"] is None else event["repaid_assets"],
                    "repaid_shares": "" if event["repaid_shares"] is None else event["repaid_shares"],
                    "seized_assets": "" if event["seized_assets"] is None else event["seized_assets"],
                    "bad_debt_assets": "" if event["bad_debt_assets"] is None else event["bad_debt_assets"],
                    "bad_debt_shares": "" if event["bad_debt_shares"] is None else event["bad_debt_shares"],
                    "rounding_check": rounding,
                    "wallet_supply_shares_before": pre["wallet_supply_shares"],
                    "wallet_supply_shares_after": state["wallet_supply_shares"],
                    "wallet_borrow_shares_before": pre["wallet_borrow_shares"],
                    "wallet_borrow_shares_after": state["wallet_borrow_shares"],
                    "wallet_collateral_assets_before": pre["wallet_collateral_assets"],
                    "wallet_collateral_assets_after": state["wallet_collateral_assets"],
                    "total_supply_assets_before": pre["total_supply_assets"],
                    "total_supply_assets_after": state["total_supply_assets"],
                    "total_supply_shares_before": pre["total_supply_shares"],
                    "total_supply_shares_after": state["total_supply_shares"],
                    "total_borrow_assets_before": pre["total_borrow_assets"],
                    "total_borrow_assets_after": state["total_borrow_assets"],
                    "total_borrow_shares_before": pre["total_borrow_shares"],
                    "total_borrow_shares_after": state["total_borrow_shares"],
                    "is_intermediate_block": event["block_number"] == intermediate_block,
                }
            )
        next_block = events[index]["block_number"] if index < len(events) else None
        if event["block_number"] == intermediate_block and next_block != intermediate_block:
            intermediate_state = deepcopy(state)
    require(intermediate_state is not None, "No selected-market events at precommitted intermediate block")
    evidence = {
        "rounding_checks": dict(sorted(rounding_counts.items())),
        "selected_wallet_event_count": len(wallet_rows),
        "selected_wallet_event_family_counts": dict(
            sorted(Counter(row["event_family"] for row in wallet_rows).items())
        ),
        "selected_wallet_event_keys_sha256": hashlib.sha256(
            "\n".join(selected_keys).encode("ascii")
        ).hexdigest(),
        "negative_balance_defects": 0,
    }
    return intermediate_state, state, wallet_rows, evidence


def fetch_intermediate(
    args: argparse.Namespace,
    selection: dict[str, Any],
    checkpoint: dict[str, Any],
    manifest_sha: str,
    checkpoint_sha: str,
) -> tuple[dict[str, int], dict[str, Any]]:
    selected = selection["selected"]
    market_id = selected["market_id"]
    wallet = selected["wallet"]
    block_number = int(checkpoint["intermediate"]["block_number"])
    identity = {
        "cache_version": INTERMEDIATE_CACHE_VERSION,
        "chain_id": EXPECTED_CHAIN_ID,
        "contract_address": MORPHO_ADDRESS,
        "manifest_sha256": manifest_sha,
        "selection_artifact_sha256": sha256_file(Path(args.selection).resolve()),
        "selection_sha256": selected["selection_sha256"],
        "checkpoint_plan_sha256": checkpoint_sha,
        "intermediate_block": block_number,
        "planned_calls": ["position(bytes32,address)", "market(bytes32)"],
    }
    cache = ArchiveRpcCache(
        Path(args.intermediate_cache).resolve(),
        identity,
        MORPHO_ADDRESS,
        POSITION_SELECTOR,
        MARKET_SELECTOR,
        FEE_RECIPIENT_SELECTOR,
    )
    client: RpcClient | None = None
    try:
        if args.offline_only:
            def cache_miss(_method: str, _params: list[Any]) -> Any:
                raise ReconstructionError("Intermediate cache miss in --offline-only mode")

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
        position_result = session.execute(archive_position_call(market_id, wallet, block_number))
        market_result = session.execute(archive_market_call(market_id, block_number))
        audit = cache.audit()
        session_metrics = session.metrics()
    finally:
        cache.close()
    position = decode_words(position_result, 3)
    market = decode_words(market_result, 6)
    cache_path = Path(args.intermediate_cache).resolve()
    immutable_uri = "file:" + cache_path.as_posix() + "?mode=ro&immutable=1"
    read_only = sqlite3.connect(immutable_uri, uri=True)
    read_only.row_factory = sqlite3.Row
    try:
        identity_created_at = str(
            read_only.execute(
                "SELECT created_at_utc FROM cache_identity WHERE singleton=1"
            ).fetchone()[0]
        )
        persisted_responses = [
            dict(row)
            for row in read_only.execute(
                """
                SELECT abi_method, block_number, market_id, wallet,
                       key_sha256, response_sha256, confirmed_at_utc
                FROM rpc_cache ORDER BY abi_method
                """
            )
        ]
    finally:
        read_only.close()
    evidence = {
        "cache_path": str(cache_path),
        "cache_identity_sha256": sha256_text(canonical_json(identity)),
        "cache_sha256": sha256_file(cache_path),
        "cache_created_at_utc": identity_created_at,
        "persisted_responses": persisted_responses,
        "archive_session": session_metrics,
        "cache_audit": audit,
        "rpc_metrics": dict(client.metrics) if client is not None else {"offline_only": 1},
    }
    return state_from_words(position, market), evidence


def checkpoint_comparison(reconstructed: dict[str, int], rpc: dict[str, int]) -> dict[str, Any]:
    position_fields = [
        "wallet_supply_shares",
        "wallet_borrow_shares",
        "wallet_collateral_assets",
    ]
    market_total_fields = [
        "total_supply_assets",
        "total_supply_shares",
        "total_borrow_assets",
        "total_borrow_shares",
    ]
    fields = position_fields + market_total_fields
    differences = {field: reconstructed[field] - rpc[field] for field in fields}
    return {
        "reconstructed": {field: reconstructed[field] for field in fields} | state_assets(reconstructed),
        "rpc": {field: rpc[field] for field in fields} | state_assets(rpc),
        "differences": differences,
        "position_match": all(differences[field] == 0 for field in position_fields),
        "market_totals_match": all(differences[field] == 0 for field in market_total_fields),
    }


def market_event_csv_rows(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = [
        "block_number",
        "transaction_index",
        "log_index",
        "transaction_hash",
        "family",
        "market_id",
        "owner",
        "caller",
        "assets",
        "shares",
        "interest",
        "fee_shares",
        "repaid_assets",
        "repaid_shares",
        "seized_assets",
        "bad_debt_assets",
        "bad_debt_shares",
        "topics_json",
        "data",
    ]
    return [{field: "" if event.get(field) is None else event.get(field, "") for field in fields} for event in events]


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest).resolve()
    selection_path = Path(args.selection).resolve()
    structural_path = Path(args.structural_candidates).resolve()
    checkpoint_path = Path(args.checkpoint_plan).resolve()
    manifest, selection, structural, checkpoint, selection_evidence = verify_selection_inputs(
        manifest_path, selection_path, structural_path, checkpoint_path
    )
    sealed_audit, sealed_states = audit_sealed_cache(
        Path(args.sealed_selection_cache).resolve(), selection, structural
    )
    selected = selection["selected"]
    market_id = selected["market_id"]
    wallet = selected["wallet"]
    start_block = int(checkpoint["replay_interval"]["from_block_inclusive"])
    end_block = int(checkpoint["replay_interval"]["to_block_exclusive"])
    intermediate_block = int(checkpoint["intermediate"]["block_number"])

    events, shard_evidence = collect_market_events(
        manifest_path, manifest, market_id, start_block, end_block
    )
    anchor_state = state_from_words(sealed_states["anchor_position"], sealed_states["anchor_market"])
    final_rpc_state = state_from_words(sealed_states["final_position"], sealed_states["final_market"])
    intermediate_reconstructed, final_reconstructed, wallet_rows, replay_evidence = replay(
        events, anchor_state, wallet, intermediate_block
    )

    require(len(wallet_rows) == int(selected["position_event_count"]), "Replayed wallet-event count differs from selection")
    require(replay_evidence["selected_wallet_event_family_counts"] == selected["event_family_counts"], "Replayed wallet families differ from selection")
    first = wallet_rows[0]
    last = wallet_rows[-1]
    for label, row, stored in (
        ("first", first, selected["first_event"]),
        ("last", last, selected["last_event"]),
    ):
        require(
            [row["block_number"], row["transaction_index"], row["log_index"], row["transaction_hash"]]
            == [stored["block_number"], stored["transaction_index"], stored["log_index"], stored["transaction_hash"]],
            f"Replayed {label} wallet event differs from selection evidence",
        )

    intermediate_rpc, intermediate_rpc_evidence = fetch_intermediate(
        args,
        selection,
        checkpoint,
        selection_evidence["manifest_sha256"],
        selection_evidence["checkpoint_plan_sha256"],
    )
    anchor_comparison = checkpoint_comparison(anchor_state, anchor_state)
    intermediate_comparison = checkpoint_comparison(intermediate_reconstructed, intermediate_rpc)
    final_comparison = checkpoint_comparison(final_reconstructed, final_rpc_state)
    require(intermediate_rpc["wallet_borrow_shares"] > 0, "Intermediate RPC borrow shares are zero")
    require(intermediate_rpc["wallet_collateral_assets"] > 0, "Intermediate RPC collateral is zero")
    require(intermediate_comparison["position_match"], "Intermediate reconstructed position differs from RPC")
    require(intermediate_comparison["market_totals_match"], "Intermediate reconstructed market totals differ from RPC")
    require(final_comparison["position_match"], "Final reconstructed position differs from RPC")
    require(final_comparison["market_totals_match"], "Final reconstructed market totals differ from RPC")
    require(anchor_state["fee"] == final_rpc_state["fee"], "Market fee changed; scoped replay lacks SetFee")

    atomic_write_csv(Path(args.market_events_output).resolve(), market_event_csv_rows(events))
    atomic_write_csv(Path(args.sample_output).resolve(), wallet_rows)
    qa = {
        "version": SCRIPT_VERSION,
        "status": "pass",
        "scope": {
            "chain_id": EXPECTED_CHAIN_ID,
            "contract_address": MORPHO_ADDRESS,
            "market_id": market_id,
            "wallet": wallet,
            "replay_interval": [start_block, end_block],
            "ordering": ["block_number", "transaction_index", "log_index"],
        },
        "selection_verification": selection_evidence,
        "sealed_selection_cache": sealed_audit,
        "replay_source": shard_evidence,
        "replay": replay_evidence,
        "intermediate_rpc": intermediate_rpc_evidence,
        "checkpoints": {
            "anchor": {"block_number": int(checkpoint["anchor"]["block_number"]), "comparison": anchor_comparison},
            "intermediate": {"block_number": intermediate_block, "comparison": intermediate_comparison},
            "final": {"block_number": int(checkpoint["final"]["block_number"]), "comparison": final_comparison},
        },
        "market_metadata": {
            "anchor_last_update": anchor_state["last_update"],
            "final_last_update": final_rpc_state["last_update"],
            "anchor_fee": anchor_state["fee"],
            "final_fee": final_rpc_state["fee"],
            "fee_unchanged": anchor_state["fee"] == final_rpc_state["fee"],
            "note": "The four stored market totals are replayed and reconciled. lastUpdate is metadata and is not inferred from timestamp-free raw log rows.",
        },
        "outputs": {
            "market_events_csv": str(Path(args.market_events_output).resolve()),
            "wallet_sample_csv": str(Path(args.sample_output).resolve()),
        },
        "defects": {
            "selection": 0,
            "sealed_cache": 0,
            "shard_checksum_or_row_count": 0,
            "duplicate_event_keys": 0,
            "rounding": 0,
            "negative_balances": 0,
            "intermediate_reconciliation": 0,
            "final_reconciliation": 0,
        },
        "limitations": [
            "This is a feasibility proof for one deterministically selected wallet-market pair, not proof for every wallet or all 45 markets.",
            "It does not prove a complete future market-day pipeline, reward receipt, retention, or DRIP causality.",
            "Position assets are checkpoint quotes from shares using the contemporaneous market totals; they are not accumulated Borrow minus Repay amounts.",
        ],
    }
    atomic_write_json(Path(args.qa_output).resolve(), qa)
    print(json.dumps({
        "status": "pass",
        "market_events": len(events),
        "wallet_events": len(wallet_rows),
        "intermediate_position_match": intermediate_comparison["position_match"],
        "intermediate_market_match": intermediate_comparison["market_totals_match"],
        "final_position_match": final_comparison["position_match"],
        "final_market_match": final_comparison["market_totals_match"],
        "qa_output": str(Path(args.qa_output).resolve()),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
