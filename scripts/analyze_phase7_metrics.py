#!/usr/bin/env python3
"""Portable Phase 7 producer. Calculations unchanged; see release derivative manifest."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable, Iterator

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:  # pragma: no cover - explicit runtime guard
    raise SystemExit(
        "Pillow is required. Run with the bundled workspace Python documented in scripts/README.md."
    ) from exc


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "tmp" / "morpho_market_day_full_v1.sqlite"
METRICS_PATH = ROOT / "docs" / "METRICS.md"
BRIDGE_PATH = ROOT / "data" / "drip_morpho_eligibility_bridge.csv"
MARKETS_PATH = ROOT / "data" / "drip_morpho_markets.csv"
BOUNDARY_CSV = ROOT / "data" / "morpho_phase7_boundary_map.csv"
BOUNDARY_JSON = ROOT / "data" / "morpho_phase7_boundary_map.json"
BOUNDARY_QA = ROOT / "data" / "morpho_phase7_boundary_qa.json"
BOUNDARY_MANIFEST = ROOT / "data" / "morpho_phase7_boundary_manifest.json"
PHASE6_QA = ROOT / "data" / "morpho_market_day_full_qa.json"
SCOPE_REPRO_MANIFEST = ROOT / "data" / "drip_morpho_scope_reproducibility_manifest.json"

MARKET_METRICS_CSV = ROOT / "data" / "morpho_phase7_market_retained_uplift.csv"
PORTFOLIO_METRICS_CSV = ROOT / "data" / "morpho_phase7_portfolio_retained_uplift.csv"
CHECKPOINT_SERIES_CSV = ROOT / "data" / "morpho_phase7_checkpoint_series.csv"
PERIOD_FLOWS_CSV = ROOT / "data" / "morpho_phase7_period_flows.csv"
CONCENTRATION_CSV = ROOT / "data" / "morpho_phase7_market_concentration.csv"
QA_PATH = ROOT / "data" / "morpho_phase7_analysis_qa.json"
MANIFEST_PATH = ROOT / "data" / "morpho_phase7_analysis_manifest.json"

FIGURE_DIR = ROOT / "figures"
FIGURES = {
    "borrowed_checkpoint_series": FIGURE_DIR / "phase7_borrowed_assets_checkpoints.png",
    "retained_uplift": FIGURE_DIR / "phase7_retained_uplift.png",
    "flow_decomposition": FIGURE_DIR / "phase7_debt_flow_decomposition.png",
    "market_concentration": FIGURE_DIR / "phase7_market_concentration.png",
    "archetypes": FIGURE_DIR / "phase7_archetype_borrowed_assets.png",
    "active_borrowers": FIGURE_DIR / "phase7_active_borrowers.png",
}

EXPECTED = {
    "production_db_sha256": "80aca74cc5e43db03fd93c69d7ad448ac9afdec5f9566a6b833ec11f7e5c9543",
    "frozen_metrics_sha256": "2774c0856ca66da4611523289a7e1c4da937ce208cad9799c2f008753eca2ba2",
    "eligibility_bridge_sha256": "cbab02426bcd1ac1ad0679156f837e155c5b04e86b63001a9149b0cbae27d305",
    "boundary_csv_sha256": "329ca8510fdd73d4623fa9de17b621ef752c383db5fb131ba77a5ffe507aeac9",
    "boundary_json_sha256": "00b888f453a72cf991dd3cd8dc9b52a95e86b8f6956b26fe681b4467b97a11cb",
    "boundary_qa_sha256": "49a91c9507f03bd4c36d4e82d48dbaaf333eb0543d7b2ec8dde5b256bf5eabcf",
    "timestamp_list_sha256": "be8ee9c6c0a80864090d50b2d16737acd58da5c70a184a7728666ca0f3d04959",
    "market_count": 45,
    "boundary_count": 227,
    "baseline_count": 56,
    "campaign_count": 169,
}

SOURCE_START_BLOCK = 355_887_376
SOURCE_START_TS = "2025-07-09T13:00:00Z"
USDC = "0xaf88d065e77c8cc2239327c5edb3a432268e5831"
USDT0 = "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9"
LOAN_DECIMALS = {USDC: 6, USDT0: 6}
ZERO_ADDRESS = "0x" + "0" * 40
ADDRESS_RE = re.compile(r"^0x[0-9a-f]{40}$")
VIRTUAL_SHARES = 1_000_000
VIRTUAL_ASSETS = 1
METRIC_VERSION = "v1.0"
ANALYSIS_VERSION = "morpho-phase7-analysis-v1"

ARCHETYPES = {
    "early_shared_usdc": "0xd09404e9512e1341321c8ae3bd663fab7087582142ac61486635a6c072c2af12",
    "dedicated_syrupusdc": "0xf86f3edd6f16cd8211f4d206866dc4ecd41be6211063ac11f8508e1b7112ef40",
    "late_usdt0": "0x571cb3ac535d61d92026c071ef1df4794d0bbbe1755f916ff640746f81b52af4",
}


class AnalysisError(RuntimeError):
    pass


@dataclass(frozen=True)
class Boundary:
    ordinal: int
    timestamp: str
    roles: tuple[str, ...]
    chosen_block: int
    predecessor_block: int


@dataclass(frozen=True)
class Market:
    market_id: str
    loan_symbol: str
    loan_address: str
    collateral_symbol: str
    collateral_address: str
    loan_decimals: int
    collateral_decimals: int
    archetype: str


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AnalysisError(message)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    with part.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(part, path)


def atomic_json(path: Path, value: object) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def atomic_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    require(bool(rows), f"Refusing to write empty CSV: {path}")
    columns = fields or list(rows[0])
    part = path.with_name(path.name + ".part")
    path.parent.mkdir(parents=True, exist_ok=True)
    with part.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(part, path)


def fraction_decimal(value: Fraction | None, places: int = 12) -> str:
    if value is None:
        return ""
    sign = "-" if value < 0 else ""
    value = abs(value)
    scale = 10**places
    scaled = (value.numerator * scale + value.denominator // 2) // value.denominator
    whole, remainder = divmod(scaled, scale)
    text = f"{whole}.{remainder:0{places}d}".rstrip("0").rstrip(".")
    return sign + text


def native_decimal(value: Fraction | None, decimals: int | None) -> str:
    if value is None:
        return ""
    divisor = 10 ** (decimals or 0)
    return fraction_decimal(value / divisor, 12)


def to_assets_up(shares: int, total_assets: int, total_shares: int) -> int:
    numerator = shares * (total_assets + VIRTUAL_ASSETS)
    denominator = total_shares + VIRTUAL_SHARES
    return (numerator + denominator - 1) // denominator


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def verify_inputs() -> tuple[dict[str, Any], dict[str, str]]:
    for path in [DB_PATH, METRICS_PATH, BRIDGE_PATH, MARKETS_PATH, BOUNDARY_CSV, BOUNDARY_JSON, BOUNDARY_QA, BOUNDARY_MANIFEST, PHASE6_QA, SCOPE_REPRO_MANIFEST]:
        require(path.is_file(), f"Missing required input: {path}")
    hashes = {
        "production_db_sha256": sha256_file(DB_PATH),
        "frozen_metrics_sha256": sha256_file(METRICS_PATH),
        "eligibility_bridge_sha256": sha256_file(BRIDGE_PATH),
        "market_csv_sha256": sha256_file(MARKETS_PATH),
        "boundary_csv_sha256": sha256_file(BOUNDARY_CSV),
        "boundary_json_sha256": sha256_file(BOUNDARY_JSON),
        "boundary_qa_sha256": sha256_file(BOUNDARY_QA),
        "boundary_manifest_sha256": sha256_file(BOUNDARY_MANIFEST),
        "phase6_qa_sha256": sha256_file(PHASE6_QA),
        "scope_reproducibility_manifest_sha256": sha256_file(SCOPE_REPRO_MANIFEST),
    }
    for key in ["production_db_sha256", "frozen_metrics_sha256", "eligibility_bridge_sha256", "boundary_csv_sha256", "boundary_json_sha256", "boundary_qa_sha256"]:
        require(hashes[key] == EXPECTED[key], f"Input fingerprint mismatch for {key}")

    manifest = load_json(BOUNDARY_MANIFEST)
    require(manifest.get("status") == "complete", "Boundary manifest is not complete")
    require(manifest.get("qa_status") == "PASS", "Boundary manifest QA is not PASS")
    identity = manifest.get("identity", {})
    require(identity.get("chain_id") == 42161, "Boundary manifest chain mismatch")
    require(identity.get("timestamp_count") == EXPECTED["boundary_count"], "Boundary timestamp count mismatch")
    require(identity.get("timestamp_list_sha256") == EXPECTED["timestamp_list_sha256"], "Boundary timestamp-list identity mismatch")
    require(identity.get("production_db_sha256") == hashes["production_db_sha256"], "Boundary manifest production identity mismatch")
    require(identity.get("frozen_metrics_sha256") == hashes["frozen_metrics_sha256"], "Boundary manifest metrics identity mismatch")
    require(identity.get("eligibility_bridge_sha256") == hashes["eligibility_bridge_sha256"], "Boundary manifest bridge identity mismatch")
    artifact_hashes = {item["path"]: item["sha256"] for item in manifest.get("artifacts", [])}
    require(artifact_hashes.get("data/morpho_phase7_boundary_map.csv") == hashes["boundary_csv_sha256"], "Boundary CSV is not manifest-bound")
    require(artifact_hashes.get("data/morpho_phase7_boundary_map.json") == hashes["boundary_json_sha256"], "Boundary JSON is not manifest-bound")
    require(artifact_hashes.get("data/morpho_phase7_boundary_qa.json") == hashes["boundary_qa_sha256"], "Boundary QA is not manifest-bound")
    require(load_json(BOUNDARY_QA).get("status") == "PASS", "Boundary QA artifact is not PASS")
    require(str(load_json(PHASE6_QA).get("status", "")).lower() == "pass", "Phase 6 QA artifact is not PASS")
    return manifest, hashes


def load_boundaries() -> list[Boundary]:
    rows: list[Boundary] = []
    with BOUNDARY_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            rows.append(
                Boundary(
                    ordinal=int(raw["ordinal"]),
                    timestamp=raw["target_timestamp_utc"],
                    roles=tuple(raw["roles"].split(";")),
                    chosen_block=int(raw["chosen_block"]),
                    predecessor_block=int(raw["predecessor_block"]),
                )
            )
    require(len(rows) == EXPECTED["boundary_count"], "Expected 227 boundary rows")
    require(len({row.timestamp for row in rows}) == len(rows), "Duplicate boundary timestamps")
    require(all(rows[i].chosen_block < rows[i + 1].chosen_block for i in range(len(rows) - 1)), "Boundary blocks are not strictly increasing")
    require(all(row.predecessor_block + 1 == row.chosen_block for row in rows), "Boundary predecessor/chosen adjacency failed")
    baseline = [row for row in rows if any(role.startswith("baseline_close_") for role in row.roles)]
    campaign = [row for row in rows if any(role.startswith("campaign_snapshot_") for role in row.roles)]
    require(len(baseline) == EXPECTED["baseline_count"], "Baseline checkpoint count mismatch")
    require(len(campaign) == EXPECTED["campaign_count"], "Campaign checkpoint count mismatch")
    return rows


def load_accepted_market_decimals(expected_market_ids: set[str]) -> tuple[dict[str, tuple[int, int]], dict[str, str]]:
    reproducibility = load_json(SCOPE_REPRO_MANIFEST)
    require(reproducibility.get("status") == "reproduced", "Phase 1 reproducibility manifest is not accepted")
    raw_path = ROOT / Path(reproducibility["api"]["raw_snapshot_path"])
    require(raw_path.is_file(), "Accepted Phase 1 raw snapshot is missing")
    raw_sha = sha256_file(raw_path)
    require(raw_sha == reproducibility["api"]["response_sha256"], "Accepted Phase 1 raw snapshot hash mismatch")
    require(reproducibility["accepted"]["market_csv_sha256"] == sha256_file(MARKETS_PATH), "Phase 1 market CSV hash mismatch")
    payload = load_json(raw_path)
    found: dict[str, set[tuple[int, int]]] = defaultdict(set)

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            market_id = str(value.get("market", "")).lower()
            if market_id in expected_market_ids and "decimalsLoanToken" in value and "decimalsCollateralToken" in value:
                found[market_id].add((int(value["decimalsLoanToken"]), int(value["decimalsCollateralToken"])))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    require(set(found) == expected_market_ids, f"Missing accepted decimals for {len(expected_market_ids - set(found))} markets")
    conflicts = {market_id: values for market_id, values in found.items() if len(values) != 1}
    require(not conflicts, f"Conflicting accepted token decimals: {conflicts}")
    return {market_id: next(iter(values)) for market_id, values in found.items()}, {
        "accepted_scope_raw_snapshot_path": raw_path.relative_to(ROOT).as_posix(),
        "accepted_scope_raw_snapshot_sha256": raw_sha,
    }


def load_markets() -> tuple[list[Market], dict[str, str]]:
    archetype_by_market = {market_id: name for name, market_id in ARCHETYPES.items()}
    raw_rows: list[dict[str, str]] = []
    with MARKETS_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        raw_rows = list(csv.DictReader(handle))
    expected_ids = {raw["market_id"].lower() for raw in raw_rows}
    decimals_by_market, decimal_evidence = load_accepted_market_decimals(expected_ids)
    rows: list[Market] = []
    for raw in raw_rows:
        market_id = raw["market_id"].lower()
        loan_address = raw["loan_address"].lower()
        collateral_address = raw["collateral_address"].lower()
        require(loan_address in LOAN_DECIMALS, f"Unexpected loan address: {loan_address}")
        loan_decimals, collateral_decimals = decimals_by_market[market_id]
        require(loan_decimals == LOAN_DECIMALS[loan_address], f"Loan-decimal mismatch for {market_id}")
        rows.append(
            Market(
                market_id=market_id,
                loan_symbol=raw["loan_symbol"],
                loan_address=loan_address,
                collateral_symbol=raw["collateral_symbol"],
                collateral_address=collateral_address,
                loan_decimals=loan_decimals,
                collateral_decimals=collateral_decimals,
                archetype=archetype_by_market.get(market_id, "full_scope_other"),
            )
        )
    require(len(rows) == EXPECTED["market_count"], "Expected 45 markets")
    require(len({row.market_id for row in rows}) == len(rows), "Duplicate market IDs")
    require(set(ARCHETYPES.values()).issubset({row.market_id for row in rows}), "Missing frozen archetype")
    return rows, decimal_evidence


def open_production() -> sqlite3.Connection:
    uri = "file:" + DB_PATH.resolve().as_posix() + "?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only=ON")
    connection.row_factory = sqlite3.Row
    return connection


STATE_FIELDS = [
    "total_supply_assets",
    "total_supply_shares",
    "total_borrow_assets",
    "total_borrow_shares",
    "total_collateral_assets",
]


def collect_market_snapshots(
    connection: sqlite3.Connection,
    markets: list[Market],
    boundaries: list[Boundary],
) -> tuple[dict[str, dict[str, dict[str, int]]], dict[str, int]]:
    all_boundaries = [Boundary(-1, SOURCE_START_TS, ("source_start",), SOURCE_START_BLOCK, SOURCE_START_BLOCK - 1)] + boundaries
    snapshots: dict[str, dict[str, dict[str, int]]] = {b.timestamp: {} for b in all_boundaries}
    rows_scanned = 0
    for market in markets:
        cursor = connection.execute(
            """
            SELECT block_number, total_supply_assets, total_supply_shares,
                   total_borrow_assets, total_borrow_shares, total_collateral_assets
            FROM market_event_state
            WHERE market_id = ?
            ORDER BY event_sequence
            """,
            (market.market_id,),
        )
        iterator = iter(cursor)
        current_row = next(iterator, None)
        current_state = {field: 0 for field in STATE_FIELDS}
        for boundary in all_boundaries:
            while current_row is not None and int(current_row["block_number"]) < boundary.chosen_block:
                current_state = {field: int(current_row[field]) for field in STATE_FIELDS}
                current_row = next(iterator, None)
                rows_scanned += 1
            snapshots[boundary.timestamp][market.market_id] = dict(current_state)
    expected_snapshot_rows = len(all_boundaries) * len(markets)
    observed = sum(len(by_market) for by_market in snapshots.values())
    require(observed == expected_snapshot_rows, "Incomplete market checkpoint grid")
    return snapshots, {"market_event_state_rows_scanned": rows_scanned, "checkpoint_state_rows": observed}


def collect_active_borrowers(
    connection: sqlite3.Connection,
    markets: list[Market],
    boundaries: list[Boundary],
    snapshots: dict[str, dict[str, dict[str, int]]],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    market_ids = {m.market_id for m in markets}
    decimals = {m.market_id: LOAN_DECIMALS[m.loan_address] for m in markets}
    positions: dict[tuple[str, str], int] = {}
    totals_by_market: dict[str, int] = defaultdict(int)
    cursor = connection.execute(
        """
        SELECT market_id, block_number, transaction_index, log_index, event_family,
               owner, shares, repaid_shares, bad_debt_shares
        FROM source_event
        WHERE event_family IN ('Borrow', 'Repay', 'Liquidate')
        ORDER BY block_number, transaction_index, log_index
        """
    )
    iterator = iter(cursor)
    current = next(iterator, None)
    output: dict[str, dict[str, Any]] = {}
    event_count = 0
    negative_defects = 0
    malformed_owners = 0
    share_reconciliation_defects = 0
    max_abs_share_difference = 0

    for boundary in boundaries:
        while current is not None and int(current["block_number"]) < boundary.chosen_block:
            family = current["event_family"]
            market_id = current["market_id"]
            owner = current["owner"]
            require(market_id in market_ids, f"Wallet event outside frozen market population: {market_id}")
            if not ADDRESS_RE.fullmatch(owner) or owner != owner.lower():
                malformed_owners += 1
            key = (market_id, owner)
            before = positions.get(key, 0)
            if family == "Borrow":
                delta = int(current["shares"])
            elif family == "Repay":
                delta = -int(current["shares"])
            else:
                delta = -(int(current["repaid_shares"]) + int(current["bad_debt_shares"]))
            after = before + delta
            if after < 0:
                negative_defects += 1
            require(after >= 0, f"Negative wallet borrow shares at {market_id}/{owner}/{current['block_number']}/{current['log_index']}")
            totals_by_market[market_id] += delta
            if after:
                positions[key] = after
            else:
                positions.pop(key, None)
            event_count += 1
            current = next(iterator, None)

        primary_wallets: set[str] = set()
        shares_only_wallets: set[str] = set()
        primary_by_market: Counter[str] = Counter()
        shares_only_by_market: Counter[str] = Counter()
        for (market_id, owner), shares in positions.items():
            if shares <= 0 or owner == ZERO_ADDRESS or not ADDRESS_RE.fullmatch(owner):
                continue
            shares_only_wallets.add(owner)
            shares_only_by_market[market_id] += 1
            state = snapshots[boundary.timestamp][market_id]
            assets = to_assets_up(shares, state["total_borrow_assets"], state["total_borrow_shares"])
            if assets >= 10 ** decimals[market_id]:
                primary_wallets.add(owner)
                primary_by_market[market_id] += 1

        differences: dict[str, int] = {}
        for market in markets:
            expected_shares = snapshots[boundary.timestamp][market.market_id]["total_borrow_shares"]
            observed_shares = totals_by_market.get(market.market_id, 0)
            diff = observed_shares - expected_shares
            if diff:
                differences[market.market_id] = diff
                share_reconciliation_defects += 1
                max_abs_share_difference = max(max_abs_share_difference, abs(diff))
        require(not differences, f"Wallet/market borrow-share reconciliation failed at {boundary.timestamp}: {differences}")
        output[boundary.timestamp] = {
            "primary_program": len(primary_wallets),
            "shares_only_program": len(shares_only_wallets),
            "primary_by_market": {m.market_id: primary_by_market[m.market_id] for m in markets},
            "shares_only_by_market": {m.market_id: shares_only_by_market[m.market_id] for m in markets},
            "positive_position_count": len(positions),
        }

    excluded_after_p180 = (1 if current is not None else 0) + sum(1 for _ in iterator)
    require(malformed_owners == 0, f"Malformed wallet owner rows: {malformed_owners}")
    return output, {
        "wallet_position_events_replayed": event_count,
        "negative_wallet_share_defects": negative_defects,
        "malformed_owner_events": malformed_owners,
        "checkpoint_market_share_reconciliation_checks": len(boundaries) * len(markets),
        "checkpoint_market_share_reconciliation_defects": share_reconciliation_defects,
        "max_abs_share_difference": max_abs_share_difference,
        "wallet_position_events_after_p180_excluded": excluded_after_p180,
    }


def metric_stats(values: dict[str, int], boundaries: list[Boundary]) -> dict[str, Any]:
    baseline = [b for b in boundaries if any(r.startswith("baseline_close_") for r in b.roles)]
    campaign = [b for b in boundaries if any(r.startswith("campaign_snapshot_") for r in b.roles)]
    role_map = {role: b for b in boundaries for role in b.roles}
    baseline_sum = sum(values[b.timestamp] for b in baseline)
    baseline_mean = Fraction(baseline_sum, len(baseline))
    e_boundary = role_map["campaign_snapshot_168"]
    e_value = values[e_boundary.timestamp]
    campaign_peak = max(values[b.timestamp] for b in campaign)
    peak_boundary = next(b for b in campaign if values[b.timestamp] == campaign_peak)
    result: dict[str, Any] = {
        "baseline_sum": baseline_sum,
        "baseline_count": len(baseline),
        "baseline_mean": baseline_mean,
        "end": e_value,
        "end_timestamp": e_boundary.timestamp,
        "peak": campaign_peak,
        "peak_timestamp": peak_boundary.timestamp,
    }
    for post in ["p30", "p90", "p180"]:
        p_boundary = role_map[post]
        p_value = values[p_boundary.timestamp]
        end_delta = Fraction(e_value) - baseline_mean
        post_delta = Fraction(p_value) - baseline_mean
        peak_delta = Fraction(campaign_peak) - baseline_mean
        primary_applicable = end_delta > 0
        peak_applicable = peak_delta > 0
        result[post] = {
            "value": p_value,
            "timestamp": p_boundary.timestamp,
            "end_delta": end_delta,
            "post_delta": post_delta,
            "peak_delta": peak_delta,
            "primary_applicable": primary_applicable,
            "primary_status": "applicable" if primary_applicable else "not_applicable_no_positive_end_uplift",
            "primary_ratio": post_delta / end_delta if primary_applicable else None,
            "peak_applicable": peak_applicable,
            "peak_status": "applicable" if peak_applicable else "not_applicable_no_positive_peak_uplift",
            "peak_ratio": post_delta / peak_delta if peak_applicable else None,
        }
    return result


def retained_row(
    *,
    scope_type: str,
    scope_id: str,
    market: Market | None,
    metric: str,
    unit_symbol: str,
    unit_address: str,
    decimals: int | None,
    post: str,
    stats: dict[str, Any],
    market_count: int,
) -> dict[str, Any]:
    point = stats[post]
    return {
        "metric_version": METRIC_VERSION,
        "scope_type": scope_type,
        "scope_id": scope_id,
        "market_count": market_count,
        "market_id": market.market_id if market else "",
        "archetype": market.archetype if market else "",
        "loan_symbol": market.loan_symbol if market else (unit_symbol if metric in {"borrowed_assets", "supplied_assets"} else ""),
        "loan_address": market.loan_address if market else (unit_address if metric in {"borrowed_assets", "supplied_assets"} else ""),
        "collateral_symbol": market.collateral_symbol if market else (unit_symbol if metric == "collateral_assets" else ""),
        "collateral_address": market.collateral_address if market else (unit_address if metric == "collateral_assets" else ""),
        "metric": metric,
        "unit_symbol": unit_symbol,
        "unit_address": unit_address,
        "unit_decimals": "" if decimals is None else decimals,
        "post_checkpoint": post,
        "post_timestamp_utc": point["timestamp"],
        "baseline_observation_count": stats["baseline_count"],
        "baseline_sum_base_units": stats["baseline_sum"],
        "baseline_mean_base_units": fraction_decimal(stats["baseline_mean"], 12),
        "baseline_mean_native": native_decimal(stats["baseline_mean"], decimals),
        "campaign_end_base_units": stats["end"],
        "campaign_end_native": native_decimal(Fraction(stats["end"]), decimals),
        "campaign_peak_base_units": stats["peak"],
        "campaign_peak_native": native_decimal(Fraction(stats["peak"]), decimals),
        "campaign_peak_timestamp_utc": stats["peak_timestamp"],
        "post_value_base_units": point["value"],
        "post_value_native": native_decimal(Fraction(point["value"]), decimals),
        "campaign_end_uplift_base_units": fraction_decimal(point["end_delta"], 12),
        "campaign_end_uplift_native": native_decimal(point["end_delta"], decimals),
        "post_uplift_base_units": fraction_decimal(point["post_delta"], 12),
        "post_uplift_native": native_decimal(point["post_delta"], decimals),
        "primary_applicability": point["primary_status"],
        "primary_retained_uplift": fraction_decimal(point["primary_ratio"], 12),
        "peak_applicability": point["peak_status"],
        "peak_retained_uplift": fraction_decimal(point["peak_ratio"], 12),
    }


def build_metrics(
    markets: list[Market],
    boundaries: list[Boundary],
    snapshots: dict[str, dict[str, dict[str, int]]],
    active: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    market_rows: list[dict[str, Any]] = []
    portfolio_rows: list[dict[str, Any]] = []
    series_rows: list[dict[str, Any]] = []
    market_by_id = {m.market_id: m for m in markets}

    for market in markets:
        metrics = {
            "borrowed_assets": {b.timestamp: snapshots[b.timestamp][market.market_id]["total_borrow_assets"] for b in boundaries},
            "supplied_assets": {b.timestamp: snapshots[b.timestamp][market.market_id]["total_supply_assets"] for b in boundaries},
            "collateral_assets": {b.timestamp: snapshots[b.timestamp][market.market_id]["total_collateral_assets"] for b in boundaries},
            "active_borrowers": {b.timestamp: active[b.timestamp]["primary_by_market"][market.market_id] for b in boundaries},
        }
        unit_map = {
            "borrowed_assets": (market.loan_symbol, market.loan_address, LOAN_DECIMALS[market.loan_address]),
            "supplied_assets": (market.loan_symbol, market.loan_address, LOAN_DECIMALS[market.loan_address]),
            "collateral_assets": (market.collateral_symbol, market.collateral_address, market.collateral_decimals),
            "active_borrowers": ("wallets", "", None),
        }
        for metric, values in metrics.items():
            stats = metric_stats(values, boundaries)
            symbol, address, decimals = unit_map[metric]
            for post in ["p30", "p90", "p180"]:
                market_rows.append(
                    retained_row(
                        scope_type="market",
                        scope_id=market.market_id,
                        market=market,
                        metric=metric,
                        unit_symbol=symbol,
                        unit_address=address,
                        decimals=decimals,
                        post=post,
                        stats=stats,
                        market_count=1,
                    )
                )

    loan_groups: dict[str, list[Market]] = defaultdict(list)
    collateral_groups: dict[str, list[Market]] = defaultdict(list)
    for market in markets:
        loan_groups[market.loan_address].append(market)
        collateral_groups[market.collateral_address].append(market)

    aggregate_specs: list[tuple[str, str, list[Market], str, str, int | None]] = []
    for address, members in sorted(loan_groups.items()):
        aggregate_specs.append(("borrowed_assets", address, members, members[0].loan_symbol, address, LOAN_DECIMALS[address]))
        aggregate_specs.append(("supplied_assets", address, members, members[0].loan_symbol, address, LOAN_DECIMALS[address]))
    for address, members in sorted(collateral_groups.items()):
        require(len({m.collateral_decimals for m in members}) == 1, f"Collateral-decimal conflict for {address}")
        aggregate_specs.append(("collateral_assets", address, members, members[0].collateral_symbol, address, members[0].collateral_decimals))

    for metric, scope_id, members, symbol, address, decimals in aggregate_specs:
        state_field = {
            "borrowed_assets": "total_borrow_assets",
            "supplied_assets": "total_supply_assets",
            "collateral_assets": "total_collateral_assets",
        }[metric]
        values = {b.timestamp: sum(snapshots[b.timestamp][m.market_id][state_field] for m in members) for b in boundaries}
        stats = metric_stats(values, boundaries)
        for post in ["p30", "p90", "p180"]:
            portfolio_rows.append(
                retained_row(
                    scope_type="exact_asset_group",
                    scope_id=scope_id,
                    market=None,
                    metric=metric,
                    unit_symbol=symbol,
                    unit_address=address,
                    decimals=decimals,
                    post=post,
                    stats=stats,
                    market_count=len(members),
                )
            )

    for metric, key in [("active_borrowers", "primary_program"), ("active_borrowers_shares_only", "shares_only_program")]:
        values = {b.timestamp: int(active[b.timestamp][key]) for b in boundaries}
        stats = metric_stats(values, boundaries)
        for post in ["p30", "p90", "p180"]:
            portfolio_rows.append(
                retained_row(
                    scope_type="fixed_program",
                    scope_id="45_markets",
                    market=None,
                    metric=metric,
                    unit_symbol="wallets",
                    unit_address="",
                    decimals=None,
                    post=post,
                    stats=stats,
                    market_count=len(markets),
                )
            )

    for boundary in boundaries:
        if any(r.startswith("baseline_close_") for r in boundary.roles):
            phase = "baseline_close"
        elif any(r.startswith("campaign_snapshot_") for r in boundary.roles):
            phase = "campaign_snapshot"
        else:
            phase = boundary.roles[0]
        for address, members in sorted(loan_groups.items()):
            for metric, field in [("borrowed_assets", "total_borrow_assets"), ("supplied_assets", "total_supply_assets")]:
                value = sum(snapshots[boundary.timestamp][m.market_id][field] for m in members)
                series_rows.append(
                    {
                        "metric_version": METRIC_VERSION,
                        "target_timestamp_utc": boundary.timestamp,
                        "boundary_block": boundary.chosen_block,
                        "phase_role": phase,
                        "population_type": "exact_loan_asset_group",
                        "population_id": address,
                        "market_count": len(members),
                        "metric": metric,
                        "value_base_units": value,
                        "value_native": native_decimal(Fraction(value), LOAN_DECIMALS[address]),
                        "unit_symbol": members[0].loan_symbol,
                        "unit_address": address,
                    }
                )
        for metric, key in [("active_borrowers", "primary_program"), ("active_borrowers_shares_only", "shares_only_program")]:
            value = int(active[boundary.timestamp][key])
            series_rows.append(
                {
                    "metric_version": METRIC_VERSION,
                    "target_timestamp_utc": boundary.timestamp,
                    "boundary_block": boundary.chosen_block,
                    "phase_role": phase,
                    "population_type": "fixed_program",
                    "population_id": "45_markets",
                    "market_count": len(markets),
                    "metric": metric,
                    "value_base_units": value,
                    "value_native": value,
                    "unit_symbol": "wallets",
                    "unit_address": "",
                }
            )
        for archetype, market_id in ARCHETYPES.items():
            market = market_by_id[market_id]
            for metric, field, symbol, address, decimals in [
                ("borrowed_assets", "total_borrow_assets", market.loan_symbol, market.loan_address, LOAN_DECIMALS[market.loan_address]),
                ("collateral_assets", "total_collateral_assets", market.collateral_symbol, market.collateral_address, market.collateral_decimals),
            ]:
                value = snapshots[boundary.timestamp][market_id][field]
                series_rows.append(
                    {
                        "metric_version": METRIC_VERSION,
                        "target_timestamp_utc": boundary.timestamp,
                        "boundary_block": boundary.chosen_block,
                        "phase_role": phase,
                        "population_type": "archetype_market",
                        "population_id": archetype,
                        "market_count": 1,
                        "metric": metric,
                        "value_base_units": value,
                        "value_native": native_decimal(Fraction(value), decimals),
                        "unit_symbol": symbol,
                        "unit_address": address,
                    }
                )

    applicability: dict[str, dict[str, int]] = defaultdict(lambda: {"applicable": 0, "not_applicable": 0})
    for row in market_rows:
        if row["post_checkpoint"] != "p180":
            continue
        bucket = "applicable" if row["primary_applicability"] == "applicable" else "not_applicable"
        applicability[row["metric"]][bucket] += 1
    return market_rows, portfolio_rows, series_rows, {"market_applicability": dict(applicability)}


FLOW_FIELDS = [
    "borrow_assets_out",
    "repay_assets_in",
    "accrued_interest_assets",
    "liquidation_repaid_assets",
    "liquidation_bad_debt_assets",
]


def build_period_flows(
    connection: sqlite3.Connection,
    markets: list[Market],
    boundaries: list[Boundary],
    snapshots: dict[str, dict[str, dict[str, int]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    role_map = {role: b for b in boundaries for role in b.roles}
    periods = [
        ("baseline", SOURCE_START_TS, "2025-09-03T13:00:00Z", SOURCE_START_BLOCK, role_map["campaign_snapshot_000"].chosen_block),
        ("incentive", "2025-09-03T13:00:00Z", "2026-02-18T13:00:00Z", role_map["campaign_snapshot_000"].chosen_block, role_map["campaign_snapshot_168"].chosen_block),
        ("post_180", "2026-02-18T13:00:00Z", "2026-08-17T13:00:00Z", role_map["campaign_snapshot_168"].chosen_block, role_map["p180"].chosen_block),
    ]
    market_by_id = {m.market_id: m for m in markets}
    accum: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    event_counts: Counter[str] = Counter()
    cursor = connection.execute(
        """
        SELECT market_id, block_number, event_family, assets, interest,
               repaid_assets, bad_debt_assets
        FROM source_event
        WHERE event_family IN ('Borrow', 'Repay', 'AccrueInterest', 'Liquidate')
        """
    )
    for row in cursor:
        block = int(row["block_number"])
        period_name = next((name for name, _, _, start, end in periods if start <= block < end), None)
        if period_name is None:
            continue
        family = row["event_family"]
        key = (row["market_id"], period_name)
        event_counts[f"{period_name}:{family}"] += 1
        if family == "Borrow":
            accum[key]["borrow_assets_out"] += int(row["assets"])
        elif family == "Repay":
            accum[key]["repay_assets_in"] += int(row["assets"])
        elif family == "AccrueInterest":
            accum[key]["accrued_interest_assets"] += int(row["interest"])
        else:
            accum[key]["liquidation_repaid_assets"] += int(row["repaid_assets"])
            accum[key]["liquidation_bad_debt_assets"] += int(row["bad_debt_assets"])

    rows: list[dict[str, Any]] = []
    period_ts = {name: (start_ts, end_ts) for name, start_ts, end_ts, _, _ in periods}
    state_ts = {
        "baseline": (SOURCE_START_TS, "2025-09-03T13:00:00Z"),
        "incentive": ("2025-09-03T13:00:00Z", "2026-02-18T13:00:00Z"),
        "post_180": ("2026-02-18T13:00:00Z", "2026-08-17T13:00:00Z"),
    }
    residual_defects = 0
    for market in markets:
        for period_name, _, _, start_block, end_block in periods:
            values = accum[(market.market_id, period_name)]
            start_ts, end_ts = state_ts[period_name]
            opening = snapshots[start_ts][market.market_id]["total_borrow_assets"]
            closing = snapshots[end_ts][market.market_id]["total_borrow_assets"]
            expected_delta = (
                values["borrow_assets_out"]
                - values["repay_assets_in"]
                + values["accrued_interest_assets"]
                - values["liquidation_repaid_assets"]
                - values["liquidation_bad_debt_assets"]
            )
            observed_delta = closing - opening
            residual = observed_delta - expected_delta
            if residual:
                residual_defects += 1
            rows.append(
                {
                    "metric_version": METRIC_VERSION,
                    "scope_type": "market",
                    "scope_id": market.market_id,
                    "market_count": 1,
                    "market_id": market.market_id,
                    "archetype": market.archetype,
                    "loan_symbol": market.loan_symbol,
                    "loan_address": market.loan_address,
                    "period": period_name,
                    "period_start_utc": period_ts[period_name][0],
                    "period_end_exclusive_utc": period_ts[period_name][1],
                    "start_block": start_block,
                    "end_block_exclusive": end_block,
                    "opening_debt_base_units": opening,
                    "closing_debt_base_units": closing,
                    **{field + "_base_units": values[field] for field in FLOW_FIELDS},
                    "expected_debt_delta_base_units": expected_delta,
                    "observed_debt_delta_base_units": observed_delta,
                    "reconciliation_residual_base_units": residual,
                    "opening_debt_native": native_decimal(Fraction(opening), LOAN_DECIMALS[market.loan_address]),
                    "closing_debt_native": native_decimal(Fraction(closing), LOAN_DECIMALS[market.loan_address]),
                    **{field + "_native": native_decimal(Fraction(values[field]), LOAN_DECIMALS[market.loan_address]) for field in FLOW_FIELDS},
                    "observed_debt_delta_native": native_decimal(Fraction(observed_delta), LOAN_DECIMALS[market.loan_address]),
                }
            )
    require(residual_defects == 0, f"Debt-flow reconciliation defects: {residual_defects}")

    for loan_address in sorted(LOAN_DECIMALS):
        members = [m for m in markets if m.loan_address == loan_address]
        for period_name, _, _, start_block, end_block in periods:
            market_period = [r for r in rows if r["scope_type"] == "market" and r["loan_address"] == loan_address and r["period"] == period_name]
            aggregate: dict[str, int] = {}
            for field in ["opening_debt", "closing_debt"] + FLOW_FIELDS + ["expected_debt_delta", "observed_debt_delta", "reconciliation_residual"]:
                aggregate[field] = sum(int(r[field + "_base_units"]) for r in market_period)
            rows.append(
                {
                    "metric_version": METRIC_VERSION,
                    "scope_type": "exact_loan_asset_group",
                    "scope_id": loan_address,
                    "market_count": len(members),
                    "market_id": "",
                    "archetype": "",
                    "loan_symbol": members[0].loan_symbol,
                    "loan_address": loan_address,
                    "period": period_name,
                    "period_start_utc": period_ts[period_name][0],
                    "period_end_exclusive_utc": period_ts[period_name][1],
                    "start_block": start_block,
                    "end_block_exclusive": end_block,
                    **{field + "_base_units": aggregate[field] for field in ["opening_debt", "closing_debt"] + FLOW_FIELDS + ["expected_debt_delta", "observed_debt_delta", "reconciliation_residual"]},
                    **{field + "_native": native_decimal(Fraction(aggregate[field]), LOAN_DECIMALS[loan_address]) for field in ["opening_debt", "closing_debt"] + FLOW_FIELDS + ["observed_debt_delta"]},
                }
            )
    return rows, {"period_flow_event_counts": dict(sorted(event_counts.items())), "flow_reconciliation_defects": residual_defects}


def build_concentration(
    markets: list[Market],
    snapshots: dict[str, dict[str, dict[str, int]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checkpoints = {"campaign_end": "2026-02-18T13:00:00Z", "p180": "2026-08-17T13:00:00Z"}
    rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    for loan_address in sorted(LOAN_DECIMALS):
        members = [m for m in markets if m.loan_address == loan_address]
        for checkpoint, timestamp in checkpoints.items():
            values = [(m, snapshots[timestamp][m.market_id]["total_borrow_assets"]) for m in members]
            values.sort(key=lambda item: (-item[1], item[0].market_id))
            total = sum(value for _, value in values)
            cumulative = 0
            hhi = sum(Fraction(value, total) ** 2 for _, value in values) if total else Fraction(0)
            for rank, (market, value) in enumerate(values, 1):
                cumulative += value
                share = Fraction(value, total) if total else Fraction(0)
                rows.append(
                    {
                        "metric_version": METRIC_VERSION,
                        "loan_symbol": market.loan_symbol,
                        "loan_address": loan_address,
                        "checkpoint": checkpoint,
                        "timestamp_utc": timestamp,
                        "market_population": len(members),
                        "rank": rank,
                        "market_id": market.market_id,
                        "collateral_symbol": market.collateral_symbol,
                        "collateral_address": market.collateral_address,
                        "archetype": market.archetype,
                        "borrowed_assets_base_units": value,
                        "borrowed_assets_native": native_decimal(Fraction(value), LOAN_DECIMALS[loan_address]),
                        "share_of_exact_loan_total": fraction_decimal(share, 12),
                        "cumulative_share": fraction_decimal(Fraction(cumulative, total) if total else Fraction(0), 12),
                        "hhi": fraction_decimal(hhi, 12),
                    }
                )
            summary[f"{market_by_symbol(members)}:{checkpoint}"] = {
                "market_count": len(members),
                "total_native": native_decimal(Fraction(total), LOAN_DECIMALS[loan_address]),
                "top1_share": fraction_decimal(Fraction(sum(v for _, v in values[:1]), total) if total else Fraction(0), 12),
                "top3_share": fraction_decimal(Fraction(sum(v for _, v in values[:3]), total) if total else Fraction(0), 12),
                "top5_share": fraction_decimal(Fraction(sum(v for _, v in values[:5]), total) if total else Fraction(0), 12),
                "hhi": fraction_decimal(hhi, 12),
                "top_market_id": values[0][0].market_id if values else "",
                "top_market_collateral": values[0][0].collateral_symbol if values else "",
            }
    return rows, summary


def market_by_symbol(markets: list[Market]) -> str:
    return markets[0].loan_symbol if markets else "unknown"


COUNT_FIELDS = {
    "Supply": "supply_event_count",
    "Withdraw": "withdraw_event_count",
    "Borrow": "borrow_event_count",
    "Repay": "repay_event_count",
    "SupplyCollateral": "supply_collateral_event_count",
    "WithdrawCollateral": "withdraw_collateral_event_count",
    "Liquidate": "liquidate_event_count",
    "AccrueInterest": "accrue_interest_event_count",
}

FLOW_SOURCE_TO_DAILY = {
    ("Supply", "assets"): "supply_assets_in",
    ("Supply", "shares"): "supply_shares_minted",
    ("Withdraw", "assets"): "withdraw_assets_out",
    ("Withdraw", "shares"): "withdraw_shares_burned",
    ("Borrow", "assets"): "borrow_assets_out",
    ("Borrow", "shares"): "borrow_shares_minted",
    ("Repay", "assets"): "repay_assets_in",
    ("Repay", "shares"): "repay_shares_burned",
    ("SupplyCollateral", "assets"): "collateral_assets_in",
    ("WithdrawCollateral", "assets"): "collateral_assets_withdrawn",
    ("AccrueInterest", "interest"): "accrued_interest_assets",
    ("AccrueInterest", "fee_shares"): "accrued_fee_shares",
    ("Liquidate", "repaid_assets"): "liquidation_repaid_assets",
    ("Liquidate", "repaid_shares"): "liquidation_repaid_shares",
    ("Liquidate", "seized_assets"): "liquidation_seized_collateral_assets",
    ("Liquidate", "bad_debt_assets"): "liquidation_bad_debt_assets",
    ("Liquidate", "bad_debt_shares"): "liquidation_bad_debt_shares",
}


def source_reconciliation(connection: sqlite3.Connection) -> dict[str, Any]:
    count_defects: list[dict[str, Any]] = []
    for family, daily_field in COUNT_FIELDS.items():
        source = int(connection.execute("SELECT COUNT(*) FROM source_event WHERE event_family=?", (family,)).fetchone()[0])
        daily = sum(int(row[0]) for row in connection.execute(f"SELECT {daily_field} FROM market_day"))
        if source != daily:
            count_defects.append({"event_family": family, "source": source, "market_day": daily})
    amount_defects: list[dict[str, Any]] = []
    for (family, source_field), daily_field in FLOW_SOURCE_TO_DAILY.items():
        source = sum(int(row[0] or 0) for row in connection.execute(f"SELECT {source_field} FROM source_event WHERE event_family=?", (family,)))
        daily = sum(int(row[0] or 0) for row in connection.execute(f"SELECT {daily_field} FROM market_day"))
        if source != daily:
            amount_defects.append({"event_family": family, "field": source_field, "source": str(source), "market_day": str(daily)})
    require(not count_defects, f"Event-family reconciliation defects: {count_defects}")
    require(not amount_defects, f"Event-amount reconciliation defects: {amount_defects}")
    return {
        "event_family_checks": len(COUNT_FIELDS),
        "event_family_defects": count_defects,
        "event_amount_checks": len(FLOW_SOURCE_TO_DAILY),
        "event_amount_defects": amount_defects,
    }


def audit_csv(rows: list[dict[str, Any]], key_fields: tuple[str, ...], expected_rows: int | None = None) -> dict[str, Any]:
    keys = [tuple(row[field] for field in key_fields) for row in rows]
    duplicates = len(keys) - len(set(keys))
    required_nulls = sum(1 for row in rows for field in key_fields if row[field] in (None, ""))
    if expected_rows is not None:
        require(len(rows) == expected_rows, f"Unexpected row count for key {key_fields}: {len(rows)} != {expected_rows}")
    require(duplicates == 0, f"Duplicate chart-ready keys for {key_fields}")
    require(required_nulls == 0, f"Required NULL/empty key fields for {key_fields}")
    return {"rows": len(rows), "unique_keys": len(set(keys)), "duplicate_keys": duplicates, "required_null_key_fields": required_nulls}


# ---------- Minimal reproducible static chart renderer (Pillow) ----------

INK = "#17202A"
MUTED = "#667085"
GRID = "#E6E9EE"
BLUE = "#356AE6"
GOLD = "#D49A00"
ORANGE = "#DD6B20"
OLIVE = "#788C3A"
PINK = "#B74873"
LIGHT_BLUE = "#B9CDFB"
LIGHT_GOLD = "#F2D894"
WHITE = "#FFFFFF"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path(os.environ.get("WINDIR", "")) / "Fonts" / ("segoeuib.ttf" if bold else "segoeui.ttf"),
        Path(os.environ.get("WINDIR", "")) / "Fonts" / ("arialbd.ttf" if bold else "arial.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def text(draw: ImageDraw.ImageDraw, xy: tuple[float, float], value: str, size: int = 24, fill: str = INK, bold: bool = False, anchor: str | None = None) -> None:
    draw.text(xy, value, font=font(size, bold), fill=fill, anchor=anchor)


def human(value: float, decimals: int = 1) -> str:
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        return f"{value / 1_000_000_000:.{decimals}f}B"
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:.{decimals}f}M"
    if absolute >= 1_000:
        return f"{value / 1_000:.{decimals}f}K"
    return f"{value:.{decimals}f}"


def ratio_label(value: str) -> str:
    if not value:
        return "N/A"
    number = float(value)
    if abs(number) < 0.01:
        return f"{number:.2%}"
    return f"{number:.2f}×"


def parse_ts(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def canvas(title: str, subtitle: str, width: int = 1800, height: int = 1100) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (width, height), WHITE)
    draw = ImageDraw.Draw(image)
    text(draw, (80, 54), title, 38, bold=True)
    text(draw, (80, 108), subtitle, 22, fill=MUTED)
    return image, draw


def axes(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], ymin: float, ymax: float, y_label: str, ticks: int = 4) -> None:
    left, top, right, bottom = box
    draw.line((left, top, left, bottom), fill=INK, width=2)
    draw.line((left, bottom, right, bottom), fill=INK, width=2)
    for i in range(ticks + 1):
        y = bottom - (bottom - top) * i / ticks
        value = ymin + (ymax - ymin) * i / ticks
        draw.line((left, y, right, y), fill=GRID, width=1)
        text(draw, (left - 14, y), human(value), 18, fill=MUTED, anchor="rm")
    text(draw, (left, top - 20), y_label, 19, fill=MUTED)


def save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    image.save(part, format="PNG", optimize=True)
    os.replace(part, path)


def chart_borrowed_series(series_rows: list[dict[str, Any]], portfolio_rows: list[dict[str, Any]]) -> None:
    image, draw = canvas(
        "Borrowed assets at exact aligned checkpoints",
        "Fixed 45-market panel; USDC and USD₮0 remain separate; state immediately before each 13:00 UTC boundary block",
        height=1250,
    )
    grouped = {(r["unit_address"], r["post_checkpoint"]): r for r in portfolio_rows if r["metric"] == "borrowed_assets"}
    for panel_index, (address, symbol) in enumerate([(USDC, "USDC"), (USDT0, "USD₮0")]):
        rows = [r for r in series_rows if r["metric"] == "borrowed_assets" and r["population_id"] == address]
        rows.sort(key=lambda r: r["target_timestamp_utc"])
        left, right = 160, 1700
        top = 210 + panel_index * 500
        bottom = top + 365
        values = [float(r["value_native"]) for r in rows]
        ymax = max(values) * 1.12 if max(values) else 1
        axes(draw, (left, top, right, bottom), 0, ymax, f"{symbol}, native tokens")
        xmin, xmax = parse_ts(rows[0]["target_timestamp_utc"]), parse_ts(rows[-1]["target_timestamp_utc"])
        points = []
        for row, value in zip(rows, values):
            x = left + (parse_ts(row["target_timestamp_utc"]) - xmin) / (xmax - xmin) * (right - left)
            y = bottom - value / ymax * (bottom - top)
            points.append((x, y))
        draw.line(points, fill=BLUE, width=5, joint="curve")
        end_row = grouped[(address, "p180")]
        peak_ts = end_row["campaign_peak_timestamp_utc"]
        key_ts = ["2025-09-03T13:00:00Z", "2026-02-18T13:00:00Z", "2026-03-20T13:00:00Z", "2026-05-19T13:00:00Z", "2026-08-17T13:00:00Z"]
        for ts in key_ts:
            x = left + (parse_ts(ts) - xmin) / (xmax - xmin) * (right - left)
            draw.line((x, top, x, bottom), fill="#9BA5B1", width=2)
        for row, value, point in zip(rows, values, points):
            if row["target_timestamp_utc"] in key_ts:
                draw.ellipse((point[0]-7, point[1]-7, point[0]+7, point[1]+7), fill=BLUE, outline=WHITE, width=2)
            if row["target_timestamp_utc"] == peak_ts:
                draw.ellipse((point[0]-9, point[1]-9, point[0]+9, point[1]+9), fill=GOLD, outline=INK, width=2)
        text(draw, (left, top - 54), f"{symbol} ({32 if address == USDC else 13} markets)", 27, bold=True)
        labels = [("Sep 3", key_ts[0]), ("End", key_ts[1]), ("+30", key_ts[2]), ("+90", key_ts[3]), ("+180", key_ts[4])]
        for label, ts in labels:
            x = left + (parse_ts(ts) - xmin) / (xmax - xmin) * (right - left)
            text(draw, (x, bottom + 18), label, 17, fill=MUTED, anchor="ma")
        text(draw, (right, top - 52), f"Peak {human(float(end_row['campaign_peak_native']))} on {peak_ts[:10]}", 20, fill=GOLD, anchor="ra")
    text(draw, (80, 1190), "Gold dot = campaign peak; blue checkpoint at End is the frozen primary denominator. Post points are +30/+90/+180 only.", 19, fill=MUTED)
    save_png(image, FIGURES["borrowed_checkpoint_series"])


def chart_retention(portfolio_rows: list[dict[str, Any]]) -> None:
    image, draw = canvas(
        "Primary retained uplift and campaign-peak sensitivity",
        "Borrowed assets; aggregate state first within each exact loan token; ratios are not clamped",
        height=1050,
    )
    for panel_index, (address, symbol) in enumerate([(USDC, "USDC"), (USDT0, "USD₮0")]):
        rows = [r for r in portfolio_rows if r["metric"] == "borrowed_assets" and r["scope_id"] == address]
        rows.sort(key=lambda r: ["p30", "p90", "p180"].index(r["post_checkpoint"]))
        primary = [float(r["primary_retained_uplift"]) for r in rows]
        peak = [float(r["peak_retained_uplift"]) for r in rows]
        all_values = primary + peak + [0]
        ymin = min(0, min(all_values))
        ymax = max(1, max(all_values))
        pad = max(0.15, (ymax - ymin) * 0.15)
        ymin -= pad if ymin < 0 else 0
        ymax += pad
        left = 160 + panel_index * 820
        right = left + 650
        top, bottom = 230, 780
        axes(draw, (left, top, right, bottom), ymin, ymax, "retained uplift ratio")
        zero_y = bottom - (0 - ymin) / (ymax - ymin) * (bottom - top)
        draw.line((left, zero_y, right, zero_y), fill=INK, width=2)
        for idx, label in enumerate(["+30", "+90", "+180"]):
            center = left + (idx + 0.5) * (right - left) / 3
            for offset, value, color, series in [(-45, primary[idx], BLUE, "End"), (45, peak[idx], GOLD, "Peak")]:
                y = bottom - (value - ymin) / (ymax - ymin) * (bottom - top)
                bar_left, bar_right = center + offset - 28, center + offset + 28
                draw.rectangle((bar_left, min(zero_y, y), bar_right, max(zero_y, y)), fill=color)
                text(draw, (center + offset, y - 11 if value >= 0 else y + 11), f"{value:.2f}×", 18, fill=INK, bold=True, anchor="mb" if value >= 0 else "ma")
            text(draw, (center, bottom + 22), label, 19, fill=MUTED, anchor="ma")
        text(draw, (left, top - 55), f"{symbol}", 28, bold=True)
    draw.rectangle((650, 885, 680, 910), fill=BLUE)
    text(draw, (694, 897), "Primary: campaign-end uplift", 20, anchor="lm")
    draw.rectangle((1030, 885, 1060, 910), fill=GOLD)
    text(draw, (1074, 897), "Sensitivity: campaign peak uplift", 20, anchor="lm")
    save_png(image, FIGURES["retained_uplift"])


def chart_flow_decomposition(flow_rows: list[dict[str, Any]]) -> None:
    image, draw = canvas(
        "Debt change components by exact loan token",
        "Gross Borrow and interest add debt; Repay, liquidation repayment and bad debt reduce it; native tokens, no USD conversion",
        height=1250,
    )
    components = [
        ("borrow_assets_out_native", "Borrow", BLUE, 1),
        ("accrued_interest_assets_native", "Interest", GOLD, 1),
        ("repay_assets_in_native", "Repay", ORANGE, -1),
        ("liquidation_repaid_assets_native", "Liq. repay", PINK, -1),
        ("liquidation_bad_debt_assets_native", "Bad debt", OLIVE, -1),
    ]
    for panel_index, (address, symbol) in enumerate([(USDC, "USDC"), (USDT0, "USD₮0")]):
        rows = [r for r in flow_rows if r["scope_type"] == "exact_loan_asset_group" and r["loan_address"] == address]
        rows.sort(key=lambda r: ["baseline", "incentive", "post_180"].index(r["period"]))
        signed = [[float(r[field]) * sign for field, _, _, sign in components] for r in rows]
        limit = max(abs(value) for group in signed for value in group) * 1.18 or 1
        left, right = 170, 1700
        top = 220 + panel_index * 470
        bottom = top + 330
        axes(draw, (left, top, right, bottom), -limit, limit, f"{symbol}, native tokens")
        zero_y = bottom - (0 + limit) / (2 * limit) * (bottom - top)
        draw.line((left, zero_y, right, zero_y), fill=INK, width=2)
        group_width = (right - left) / 3
        bar_w = 34
        for gi, (row, values) in enumerate(zip(rows, signed)):
            center = left + (gi + 0.5) * group_width
            for ci, value in enumerate(values):
                x = center + (ci - 2) * 54
                y = bottom - (value + limit) / (2 * limit) * (bottom - top)
                draw.rectangle((x - bar_w/2, min(y, zero_y), x + bar_w/2, max(y, zero_y)), fill=components[ci][2])
            observed = float(row["observed_debt_delta_native"])
            oy = bottom - (observed + limit) / (2 * limit) * (bottom - top)
            draw.polygon([(center+155, oy-9), (center+164, oy), (center+155, oy+9), (center+146, oy)], fill=INK)
            text(draw, (center, bottom + 18), {"baseline":"Baseline", "incentive":"Incentive", "post_180":"Post 180d"}[row["period"]], 18, fill=MUTED, anchor="ma")
        text(draw, (left, top - 50), f"{symbol}", 27, bold=True)
        incentive = next(r for r in rows if r["period"] == "incentive")
        post = next(r for r in rows if r["period"] == "post_180")
        text(
            draw,
            (right, top - 48),
            f"Incentive: interest {human(float(incentive['accrued_interest_assets_native']), 2)}, debt Δ {human(float(incentive['observed_debt_delta_native']), 2)}  ·  "
            f"Post: interest {human(float(post['accrued_interest_assets_native']), 2)}, debt Δ {human(float(post['observed_debt_delta_native']), 2)}",
            18,
            fill=MUTED,
            anchor="ra",
        )
    legend_x = 230
    for field, label, color, sign in components:
        draw.rectangle((legend_x, 1165, legend_x + 24, 1188), fill=color)
        text(draw, (legend_x + 34, 1177), ("+ " if sign > 0 else "− ") + label, 17, anchor="lm")
        legend_x += 225
    draw.polygon([(legend_x, 1165), (legend_x+10, 1175), (legend_x, 1185), (legend_x-10, 1175)], fill=INK)
    text(draw, (legend_x + 20, 1177), "Observed debt change", 17, anchor="lm")
    save_png(image, FIGURES["flow_decomposition"])


def chart_concentration(concentration_rows: list[dict[str, Any]]) -> None:
    image, draw = canvas(
        "Market concentration within each exact loan token",
        "Top eight markets ranked by +180 borrowed assets; bars compare campaign end and +180 shares of the same-token total",
        height=1300,
    )
    for panel_index, (address, symbol) in enumerate([(USDC, "USDC"), (USDT0, "USD₮0")]):
        p180 = [r for r in concentration_rows if r["loan_address"] == address and r["checkpoint"] == "p180"][:8]
        market_ids = [r["market_id"] for r in p180]
        end_map = {r["market_id"]: r for r in concentration_rows if r["loan_address"] == address and r["checkpoint"] == "campaign_end"}
        left, right = 500, 1680
        top = 220 + panel_index * 500
        bottom = top + 400
        draw.line((left, top, left, bottom), fill=INK, width=2)
        draw.line((left, bottom, right, bottom), fill=INK, width=2)
        for tick in range(5):
            share_tick = tick / 4
            x = left + share_tick * (right-left)
            draw.line((x, top, x, bottom), fill=GRID, width=1)
            text(draw, (x, bottom + 14), f"{share_tick:.0%}", 16, fill=MUTED, anchor="ma")
        text(draw, (left, top - 18), "share of exact-token borrowed assets", 19, fill=MUTED)
        row_h = (bottom - top) / 8
        for idx, p_row in enumerate(p180):
            y = top + (idx + 0.5) * row_h
            end_share = float(end_map[p_row["market_id"]]["share_of_exact_loan_total"])
            p_share = float(p_row["share_of_exact_loan_total"])
            draw.line((left, y - 8, left + end_share * (right-left), y - 8), fill=LIGHT_GOLD, width=12)
            draw.line((left, y + 8, left + p_share * (right-left), y + 8), fill=BLUE, width=12)
            label = f"{p_row['collateral_symbol']} · {p_row['market_id'][2:8]}"
            text(draw, (left - 18, y), label, 18, fill=INK, anchor="rm")
            text(draw, (left + p_share * (right-left) + 12, y + 8), f"{p_share:.1%}", 16, fill=BLUE, anchor="lm")
            if end_share >= 0.015:
                text(draw, (left + end_share * (right-left) + 12, y - 8), f"{end_share:.1%}", 15, fill="#9A7200", anchor="lm")
        text(draw, (left, top - 55), f"{symbol} ({32 if address == USDC else 13} markets)", 27, bold=True)
    draw.rectangle((700, 1210, 730, 1225), fill=LIGHT_GOLD)
    text(draw, (742, 1218), "Campaign end", 18, anchor="lm")
    draw.rectangle((980, 1210, 1010, 1225), fill=BLUE)
    text(draw, (1022, 1218), "+180", 18, anchor="lm")
    save_png(image, FIGURES["market_concentration"])


def chart_archetypes(series_rows: list[dict[str, Any]], market_rows: list[dict[str, Any]]) -> None:
    image, draw = canvas(
        "Borrowed assets and collateral for the three frozen archetypes",
        "Each panel uses its own native token and y-scale; no heterogeneous assets are added",
        width=2000,
        height=1700,
    )
    titles = {
        "early_shared_usdc": "Early shared USDC · weETH collateral",
        "dedicated_syrupusdc": "Dedicated syrupUSDC · USDC loan",
        "late_usdt0": "Late USD₮0 · syrupUSDC collateral",
    }
    text(draw, (550, 170), "Borrowed assets", 24, bold=True, anchor="ma")
    text(draw, (1510, 170), "Collateral", 24, bold=True, anchor="ma")
    for row_index, archetype in enumerate(ARCHETYPES):
        row_top = 245 + row_index * 455
        text(draw, (105, row_top - 48), titles[archetype], 25, bold=True)
        for column, metric in enumerate(["borrowed_assets", "collateral_assets"]):
            rows = [r for r in series_rows if r["population_type"] == "archetype_market" and r["population_id"] == archetype and r["metric"] == metric]
            rows.sort(key=lambda r: r["target_timestamp_utc"])
            left = 150 + column * 970
            right = left + 800
            top, bottom = row_top, row_top + 300
            values = [float(r["value_native"]) for r in rows]
            ymax = max(values) * 1.15 if max(values) else 1
            axes(draw, (left, top, right, bottom), 0, ymax, f"{rows[0]['unit_symbol']}, native tokens")
            xmin, xmax = parse_ts(rows[0]["target_timestamp_utc"]), parse_ts(rows[-1]["target_timestamp_utc"])
            points = []
            for row, value in zip(rows, values):
                x = left + (parse_ts(row["target_timestamp_utc"]) - xmin) / (xmax-xmin) * (right-left)
                y = bottom - value / ymax * (bottom-top)
                points.append((x, y))
            draw.line(points, fill=BLUE, width=5)
            retained = next(r for r in market_rows if r["market_id"] == ARCHETYPES[archetype] and r["metric"] == metric and r["post_checkpoint"] == "p180")
            for ts, color in [(retained["campaign_peak_timestamp_utc"], GOLD), ("2026-02-18T13:00:00Z", BLUE), ("2026-08-17T13:00:00Z", PINK)]:
                match = next((point for series_row, point in zip(rows, points) if series_row["target_timestamp_utc"] == ts), None)
                if match:
                    draw.ellipse((match[0]-7,match[1]-7,match[0]+7,match[1]+7),fill=color,outline=INK,width=2)
            text(draw, (right, top - 26), f"+180 retained: {ratio_label(retained['primary_retained_uplift'])}", 17, fill=MUTED, anchor="ra")
            for label, ts in [("Sep 3","2025-09-03T13:00:00Z"),("End","2026-02-18T13:00:00Z"),("+180","2026-08-17T13:00:00Z")]:
                x = left + (parse_ts(ts)-xmin)/(xmax-xmin)*(right-left)
                draw.line((x,top,x,bottom),fill="#9BA5B1",width=2)
                text(draw,(x,bottom+14),label,15,fill=MUTED,anchor="ma")
    text(draw, (80, 1640), "Gold = campaign peak; blue = campaign end; pink = +180. Selection was frozen before outcomes.", 19, fill=MUTED)
    save_png(image, FIGURES["archetypes"])


def chart_active_borrowers(series_rows: list[dict[str, Any]], portfolio_rows: list[dict[str, Any]]) -> None:
    image, draw = canvas(
        "Cross-sectional active borrowers at exact checkpoints",
        "Distinct wallets across 45 markets; primary requires ≥1 native loan token per position; shares-only line shows dust sensitivity",
        height=950,
    )
    primary = [r for r in series_rows if r["population_type"] == "fixed_program" and r["metric"] == "active_borrowers"]
    dust = [r for r in series_rows if r["population_type"] == "fixed_program" and r["metric"] == "active_borrowers_shares_only"]
    primary.sort(key=lambda r:r["target_timestamp_utc"])
    dust.sort(key=lambda r:r["target_timestamp_utc"])
    left, top, right, bottom = 160, 220, 1700, 730
    ymax = max(max(int(r["value_native"]) for r in primary), max(int(r["value_native"]) for r in dust)) * 1.12 or 1
    axes(draw,(left,top,right,bottom),0,ymax,"distinct wallets")
    xmin,xmax=parse_ts(primary[0]["target_timestamp_utc"]),parse_ts(primary[-1]["target_timestamp_utc"])
    point_maps: dict[str, dict[str, tuple[float, float]]] = {}
    for rows,color,width,name in [(dust,GOLD,4,"dust"),(primary,BLUE,6,"primary")]:
        points=[]
        for row in rows:
            x=left+(parse_ts(row["target_timestamp_utc"])-xmin)/(xmax-xmin)*(right-left)
            y=bottom-float(row["value_native"])/ymax*(bottom-top)
            points.append((x,y))
        draw.line(points,fill=color,width=width)
        point_maps[name] = {row["target_timestamp_utc"]: point for row,point in zip(rows,points)}
    for label,ts in [("Sep 3","2025-09-03T13:00:00Z"),("End","2026-02-18T13:00:00Z"),("+30","2026-03-20T13:00:00Z"),("+90","2026-05-19T13:00:00Z"),("+180","2026-08-17T13:00:00Z")]:
        x=left+(parse_ts(ts)-xmin)/(xmax-xmin)*(right-left)
        draw.line((x,top,x,bottom),fill="#9BA5B1",width=2)
        text(draw,(x,bottom+18),label,17,fill=MUTED,anchor="ma")
    retained=next(r for r in portfolio_rows if r["metric"]=="active_borrowers" and r["post_checkpoint"]=="p180")
    for ts,color in [(retained["campaign_peak_timestamp_utc"],GOLD),("2026-02-18T13:00:00Z",BLUE),("2026-08-17T13:00:00Z",PINK)]:
        point=point_maps["primary"][ts]
        draw.ellipse((point[0]-8,point[1]-8,point[0]+8,point[1]+8),fill=color,outline=INK,width=2)
    text(draw,(left,top-52),f"Primary +180 retained uplift: {ratio_label(retained['primary_retained_uplift'])}",22,bold=True)
    text(draw,(right,top-50),f"Peak {int(retained['campaign_peak_native']):,} on {retained['campaign_peak_timestamp_utc'][:10]} · End {int(retained['campaign_end_native']):,} · +180 {int(retained['post_value_native']):,}",18,fill=MUTED,anchor="ra")
    draw.line((620,840,680,840),fill=BLUE,width=6); text(draw,(695,840),"Primary material positions",19,anchor="lm")
    draw.line((1040,840,1100,840),fill=GOLD,width=5); text(draw,(1115,840),"Any positive borrow shares",19,anchor="lm")
    save_png(image, FIGURES["active_borrowers"])


def render_figures(series_rows: list[dict[str, Any]], market_rows: list[dict[str, Any]], portfolio_rows: list[dict[str, Any]], flow_rows: list[dict[str, Any]], concentration_rows: list[dict[str, Any]]) -> None:
    chart_borrowed_series(series_rows, portfolio_rows)
    chart_retention(portfolio_rows)
    chart_flow_decomposition(flow_rows)
    chart_concentration(concentration_rows)
    chart_archetypes(series_rows, market_rows)
    chart_active_borrowers(series_rows, portfolio_rows)


def main() -> int:
    started = time.perf_counter()
    generated_at = utc_now()
    print("[1/8] Verifying immutable inputs and boundary manifest...", flush=True)
    manifest, input_hashes = verify_inputs()
    boundaries = load_boundaries()
    markets, decimal_evidence = load_markets()
    input_hashes.update(decimal_evidence)
    before_db = {"bytes": DB_PATH.stat().st_size, "sha256": input_hashes["production_db_sha256"]}

    print("[2/8] Opening Phase 6 production SQLite read-only/immutable...", flush=True)
    connection = open_production()
    require(connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "Production SQLite integrity_check failed")
    require(int(connection.execute("SELECT COUNT(*) FROM market_dim").fetchone()[0]) == 45, "Production market count mismatch")
    require(int(connection.execute("SELECT COUNT(*) FROM market_day_full").fetchone()[0]) == 18_225, "Production market-day grain mismatch")
    require(int(connection.execute("SELECT COUNT(*) FROM source_event").fetchone()[0]) == 1_231_462, "Production source-event count mismatch")
    anchor_rows = list(connection.execute("SELECT total_supply_assets,total_supply_shares,total_borrow_assets,total_borrow_shares FROM rpc_checkpoint WHERE checkpoint_name='anchor'"))
    require(len(anchor_rows) == 45, "Expected 45 anchor RPC rows")
    require(all(all(int(row[field]) == 0 for field in row.keys()) for row in anchor_rows), "Non-zero Phase 6 anchor blocks wallet replay")

    print("[3/8] Selecting exact checkpoint market states...", flush=True)
    snapshots, snapshot_audit = collect_market_snapshots(connection, markets, boundaries)
    require(all(all(value >= 0 for value in state.values()) for by_market in snapshots.values() for state in by_market.values()), "Negative market checkpoint state")

    print("[4/8] Replaying wallet borrow shares and reconciling every market/checkpoint...", flush=True)
    active, wallet_audit = collect_active_borrowers(connection, markets, boundaries, snapshots)

    print("[5/8] Calculating frozen metrics, flows, and concentration...", flush=True)
    market_rows, portfolio_rows, series_rows, metric_audit = build_metrics(markets, boundaries, snapshots, active)
    flow_rows, flow_audit = build_period_flows(connection, markets, boundaries, snapshots)
    concentration_rows, concentration_summary = build_concentration(markets, snapshots)

    print("[6/8] Running independent source and chart-ready QA...", flush=True)
    source_audit = source_reconciliation(connection)
    csv_audit = {
        "market_retained_uplift": audit_csv(market_rows, ("market_id", "metric", "post_checkpoint"), 45 * 4 * 3),
        "portfolio_retained_uplift": audit_csv(portfolio_rows, ("scope_type", "scope_id", "metric", "post_checkpoint")),
        "checkpoint_series": audit_csv(series_rows, ("target_timestamp_utc", "population_type", "population_id", "metric"), 227 * 12),
        "period_flows": audit_csv(flow_rows, ("scope_type", "scope_id", "period"), 45 * 3 + 2 * 3),
        "market_concentration": audit_csv(concentration_rows, ("loan_address", "checkpoint", "market_id"), 45 * 2),
    }
    require(sum(1 for row in market_rows if row["primary_applicability"] not in {"applicable", "not_applicable_no_positive_end_uplift"}) == 0, "Invalid applicability status")
    require(sum(1 for row in flow_rows if int(row["reconciliation_residual_base_units"]) != 0) == 0, "Flow residuals remain")

    # Aggregate exact-token checkpoint values must equal their market components.
    aggregate_defects = 0
    for boundary in boundaries:
        for address in LOAN_DECIMALS:
            expected_value = sum(snapshots[boundary.timestamp][m.market_id]["total_borrow_assets"] for m in markets if m.loan_address == address)
            observed_row = next(r for r in series_rows if r["target_timestamp_utc"] == boundary.timestamp and r["metric"] == "borrowed_assets" and r["population_id"] == address)
            aggregate_defects += int(int(observed_row["value_base_units"]) != expected_value)
    require(aggregate_defects == 0, "Exact-token aggregate checkpoint reconciliation failed")

    print("[7/8] Publishing chart-ready CSV and figures atomically...", flush=True)
    atomic_csv(MARKET_METRICS_CSV, market_rows)
    atomic_csv(PORTFOLIO_METRICS_CSV, portfolio_rows)
    atomic_csv(CHECKPOINT_SERIES_CSV, series_rows)
    atomic_csv(PERIOD_FLOWS_CSV, flow_rows)
    atomic_csv(CONCENTRATION_CSV, concentration_rows)
    render_figures(series_rows, market_rows, portfolio_rows, flow_rows, concentration_rows)

    connection.close()
    after_db = {"bytes": DB_PATH.stat().st_size, "sha256": sha256_file(DB_PATH)}
    require(after_db == before_db, "Production database changed during Phase 7")
    require(sha256_file(METRICS_PATH) == input_hashes["frozen_metrics_sha256"], "Frozen metrics changed during Phase 7")
    require(sha256_file(BRIDGE_PATH) == input_hashes["eligibility_bridge_sha256"], "Eligibility bridge changed during Phase 7")

    outputs = [MARKET_METRICS_CSV, PORTFOLIO_METRICS_CSV, CHECKPOINT_SERIES_CSV, PERIOD_FLOWS_CSV, CONCENTRATION_CSV, *FIGURES.values()]
    output_manifest = [
        {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in outputs
    ]
    duration = time.perf_counter() - started
    qa = {
        "version": ANALYSIS_VERSION,
        "status": "PASS",
        "generated_at_utc": generated_at,
        "question": "Did DRIP create lending demand that remained after incentives ended?",
        "methodological_status": "observational_before_after_not_causal",
        "identity": {
            "metric_version": METRIC_VERSION,
            "production_db_sha256": input_hashes["production_db_sha256"],
            "frozen_metrics_sha256": input_hashes["frozen_metrics_sha256"],
            "eligibility_bridge_sha256": input_hashes["eligibility_bridge_sha256"],
            "boundary_manifest_sha256": input_hashes["boundary_manifest_sha256"],
            "timestamp_list_sha256": EXPECTED["timestamp_list_sha256"],
        },
        "scope": {
            "markets": 45,
            "usdc_markets": sum(m.loan_address == USDC for m in markets),
            "usdt0_markets": sum(m.loan_address == USDT0 for m in markets),
            "boundaries": len(boundaries),
            "baseline_checkpoints": 56,
            "campaign_checkpoints": 169,
            "post_checkpoints": 3,
            "production_market_days": 18_225,
        },
        "checks": {
            "boundary_manifest_identity": "PASS",
            "production_sqlite_integrity": "ok",
            "production_database_unchanged": before_db == after_db,
            "frozen_metrics_unchanged": True,
            "eligibility_bridge_unchanged": True,
            "checkpoint_state_grid": snapshot_audit,
            "wallet_replay": wallet_audit,
            "source_reconciliation": source_audit,
            "chart_ready_tables": csv_audit,
            "exact_token_aggregate_defects": aggregate_defects,
            "period_flow_reconciliation": flow_audit,
            "phase6_exact_rounding_status_counts": load_json(PHASE6_QA)["rounding_status_counts"],
            "phase6_rare_branch_coverage": load_json(PHASE6_QA)["rare_branch_coverage"],
            "negative_market_checkpoint_balances": 0,
            "unexplained_null_or_duplicate_keys": 0,
        },
        "results": {
            **metric_audit,
            "market_concentration": concentration_summary,
        },
        "limitations": [
            "The design is observational before/after and does not identify a causal DRIP effect.",
            "Eligible-market wallets are not verified reward recipients, and a wallet is not a person.",
            "No wallet cohort retention or wallet concentration is calculated; active borrowers are cross-sectional checkpoint counts.",
            "USDC and USD₮0 are never added; collateral assets are not added across different token addresses.",
            "Non-zero feeShares were not empirically exercised in the accepted Phase 6 source; bad debt was empirically exercised.",
            "No price/USD layer or market-level allocation of shared/direct-vault budgets is used.",
        ],
        "runtime_seconds": round(duration, 3),
        "output_bytes": sum(item["bytes"] for item in output_manifest),
        "outputs": output_manifest,
    }
    atomic_json(QA_PATH, qa)
    final_outputs = output_manifest + [{"path": QA_PATH.relative_to(ROOT).as_posix(), "bytes": QA_PATH.stat().st_size, "sha256": sha256_file(QA_PATH)}]
    analysis_manifest = {
        "version": ANALYSIS_VERSION,
        "status": "complete",
        "created_at_utc": generated_at,
        "metric_version": METRIC_VERSION,
        "script": {"path": Path(__file__).resolve().relative_to(ROOT).as_posix(), "sha256": sha256_file(Path(__file__).resolve())},
        "inputs": input_hashes,
        "boundary_identity_sha256": manifest["identity_sha256"],
        "network": {"rpc_calls": 0, "eth_getlogs_calls": 0, "gba_queries": 0},
        "production_database_access": "SQLite URI mode=ro&immutable=1; PRAGMA query_only=ON",
        "outputs": final_outputs,
        "qa_status": "PASS",
    }
    atomic_json(MANIFEST_PATH, analysis_manifest)
    print(f"[8/8] PASS in {duration:.3f}s; {len(market_rows)} market metric rows; {len(series_rows)} checkpoint-series rows; 6 figures.", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AnalysisError as exc:
        print(f"BLOCKER: {exc}", file=sys.stderr)
        raise SystemExit(2)
