#!/usr/bin/env python3
"""Build the bounded Phase 6 eligibility bridge and preflight QA evidence.

This script reads only accepted Phase 1 files plus accepted Phase 2/4 evidence.
It does not scan RPC shards, call an API, build the 45-market daily layer, or
modify frozen metric definitions.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VERSION = "morpho-phase6-preflight-v1"
EXPECTED_PHASE2_MANIFEST_SHA256 = (
    "c8552428187094e5aad725193f2e3023e622ddc4ab37428f1414c375e7d6be58"
)
EXPECTED_MARKETS = 45
EXPECTED_DAYS = 405
EXPECTED_MARKET_DAY_ROWS = EXPECTED_MARKETS * EXPECTED_DAYS
MINIMUM_FREE_BYTES = 10 * 1024**3
MARKET_ID_RE = re.compile(r"^0x[0-9a-f]{64}$")
ADDRESS_RE = re.compile(r"^0x[0-9a-f]{40}$")

BRIDGE_FIELDS = [
    "market_id",
    "epoch",
    "side",
    "epoch_start_utc",
    "epoch_end_utc",
    "loan_symbol",
    "loan_address",
    "collateral_symbol",
    "collateral_address",
    "lltv_1e18",
    "eligibility_mode",
    "shared_pool_eligible",
    "dedicated_market_eligible",
    "shared_campaign_db_id",
    "dedicated_campaign_db_id",
    "dedicated_market_allocation_arb",
]


class PreflightError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    with part.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(part, path)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def csv_payload(rows: list[dict[str, str]]) -> bytes:
    import io

    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=BRIDGE_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def parse_epochs(value: str, market_id: str, side: str) -> list[int]:
    if value == "":
        return []
    parts = value.split(";")
    if any(not part.isdigit() for part in parts):
        raise PreflightError(f"invalid {side}_epochs for {market_id}: {value!r}")
    epochs = [int(part) for part in parts]
    if epochs != sorted(set(epochs)) or any(epoch < 1 or epoch > 12 for epoch in epochs):
        raise PreflightError(f"invalid {side}_epochs for {market_id}: {value!r}")
    return epochs


def one_or_none(rows: list[dict[str, str]], label: str) -> dict[str, str] | None:
    if len(rows) > 1:
        raise PreflightError(f"multiple {label} records: {[row['campaign_db_id'] for row in rows]}")
    return rows[0] if rows else None


def build_bridge(
    campaigns: list[dict[str, str]], markets: list[dict[str, str]]
) -> list[dict[str, str]]:
    shared: dict[tuple[int, str, str], list[dict[str, str]]] = defaultdict(list)
    dedicated: dict[tuple[int, str, str], list[dict[str, str]]] = defaultdict(list)
    for campaign in campaigns:
        epoch = int(campaign["epoch"])
        if campaign["scope"] == "shared_market_pool":
            shared[(epoch, campaign["side"], campaign["target"])].append(campaign)
        elif campaign["scope"] == "dedicated_market":
            dedicated[
                (epoch, campaign["side"], campaign["target_address"].lower())
            ].append(campaign)

    bridge = []
    for market in markets:
        market_id = market["market_id"].lower()
        if not MARKET_ID_RE.fullmatch(market_id):
            raise PreflightError(f"invalid market id {market_id!r}")
        loan_address = market["loan_address"].lower()
        collateral_address = market["collateral_address"].lower()
        if not ADDRESS_RE.fullmatch(loan_address) or not ADDRESS_RE.fullmatch(
            collateral_address
        ):
            raise PreflightError(f"invalid asset address for {market_id}")
        for side in ("supply", "borrow"):
            for epoch in parse_epochs(market[f"{side}_epochs"], market_id, side):
                shared_campaign = one_or_none(
                    shared.get((epoch, side, market["loan_symbol"]), []),
                    f"shared campaign for {(market_id, epoch, side)}",
                )
                dedicated_campaign = one_or_none(
                    dedicated.get((epoch, side, market_id), []),
                    f"dedicated campaign for {(market_id, epoch, side)}",
                )
                if shared_campaign is None and dedicated_campaign is None:
                    raise PreflightError(
                        f"orphan eligibility tuple {(market_id, epoch, side)}"
                    )
                date_source = shared_campaign or dedicated_campaign
                if shared_campaign and dedicated_campaign:
                    if (
                        shared_campaign["start_utc"] != dedicated_campaign["start_utc"]
                        or shared_campaign["end_utc"] != dedicated_campaign["end_utc"]
                    ):
                        raise PreflightError(
                            f"campaign boundary conflict for {(market_id, epoch, side)}"
                        )
                    mode = "shared_plus_dedicated"
                elif shared_campaign:
                    mode = "shared_market_pool"
                else:
                    mode = "dedicated_market"
                bridge.append(
                    {
                        "market_id": market_id,
                        "epoch": str(epoch),
                        "side": side,
                        "epoch_start_utc": date_source["start_utc"],
                        "epoch_end_utc": date_source["end_utc"],
                        "loan_symbol": market["loan_symbol"],
                        "loan_address": loan_address,
                        "collateral_symbol": market["collateral_symbol"],
                        "collateral_address": collateral_address,
                        "lltv_1e18": market["lltv_1e18"],
                        "eligibility_mode": mode,
                        "shared_pool_eligible": "1" if shared_campaign else "0",
                        "dedicated_market_eligible": "1" if dedicated_campaign else "0",
                        "shared_campaign_db_id": (
                            shared_campaign["campaign_db_id"] if shared_campaign else ""
                        ),
                        "dedicated_campaign_db_id": (
                            dedicated_campaign["campaign_db_id"]
                            if dedicated_campaign
                            else ""
                        ),
                        "dedicated_market_allocation_arb": (
                            dedicated_campaign["allocation_arb"]
                            if dedicated_campaign
                            else ""
                        ),
                    }
                )
    bridge.sort(key=lambda row: (row["market_id"], int(row["epoch"]), row["side"]))
    return bridge


def duplicate_count(rows: list[dict[str, str]], fields: tuple[str, ...]) -> int:
    counts = Counter(tuple(row[field] for field in fields) for row in rows)
    return sum(count - 1 for count in counts.values() if count > 1)


def qa(
    args: argparse.Namespace,
    campaigns: list[dict[str, str]],
    markets: list[dict[str, str]],
    bridge: list[dict[str, str]],
    phase2_manifest: dict[str, Any],
    prototype_qa: dict[str, Any],
    reproduction: dict[str, Any],
    comparison: dict[str, Any],
) -> dict[str, Any]:
    market_ids = {row["market_id"].lower() for row in markets}
    bridge_market_ids = {row["market_id"] for row in bridge}
    bridge_keys = {(row["market_id"], row["epoch"], row["side"]) for row in bridge}
    campaign_ids = [row["campaign_db_id"] for row in campaigns]

    relation_counts = Counter()
    for row in bridge:
        if row["shared_campaign_db_id"]:
            relation_counts[row["shared_campaign_db_id"]] += 1
        if row["dedicated_campaign_db_id"]:
            relation_counts[row["dedicated_campaign_db_id"]] += 1

    shared_count_mismatches = []
    dedicated_count_mismatches = []
    market_campaign_orphans = []
    for campaign in campaigns:
        observed = relation_counts[campaign["campaign_db_id"]]
        expected = int(campaign["unique_market_count"])
        if campaign["scope"] == "shared_market_pool" and observed != expected:
            shared_count_mismatches.append(
                {
                    "campaign_db_id": campaign["campaign_db_id"],
                    "expected": expected,
                    "observed": observed,
                }
            )
        elif campaign["scope"] == "dedicated_market" and observed != 1:
            dedicated_count_mismatches.append(
                {
                    "campaign_db_id": campaign["campaign_db_id"],
                    "expected": 1,
                    "observed": observed,
                }
            )
        elif campaign["scope"] != "direct_vault" and observed == 0:
            market_campaign_orphans.append(campaign["campaign_db_id"])

    budget_by_scope: dict[str, int] = defaultdict(int)
    count_by_scope = Counter()
    budget_by_epoch: dict[str, int] = defaultdict(int)
    for campaign in campaigns:
        amount = int(campaign["allocation_arb"])
        budget_by_scope[campaign["scope"]] += amount
        budget_by_epoch[campaign["epoch"]] += amount
        count_by_scope[campaign["scope"]] += 1

    expected_epoch_budgets = {
        "1": 120000,
        "2": 300000,
        "3": 570000,
        "4": 550000,
        "5": 510000,
        "6": 110000,
        "7": 140000,
        "8": 290000,
        "9": 450000,
        "10": 420000,
        "11": 325000,
        "12": 197500,
    }
    observed_epoch_budgets = dict(sorted(budget_by_epoch.items(), key=lambda item: int(item[0])))
    required_bridge_fields = BRIDGE_FIELDS[:11]
    required_nulls = sum(
        1 for row in bridge for field in required_bridge_fields if row[field] == ""
    )
    forbidden_semicolon_cells = sum(
        1 for row in bridge for value in row.values() if ";" in value
    )

    prototype_cost = prototype_qa["cost_and_storage"]
    disk = shutil.disk_usage(args.workspace)
    inputs = []
    for role, path in [
        ("accepted_campaign_scope", args.campaigns),
        ("accepted_market_scope", args.markets),
        ("normalized_eligibility_bridge", args.bridge_output),
        ("immutable_phase2_manifest", args.phase2_manifest),
        ("phase2_day_boundaries", args.day_boundaries),
        ("accepted_phase4_cost_evidence", args.prototype_qa),
        ("phase4_build_sql_template", args.prototype_build_sql),
        ("phase4_qa_sql_template", args.prototype_qa_sql),
        ("frozen_metrics_v1", args.metrics),
    ]:
        inputs.append(
            {
                "role": role,
                "path": str(path.resolve()),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )

    checks = {
        "reproduction_status_match": comparison.get("status") == "match"
        and comparison.get("total_defects") == 0
        and reproduction.get("status") == "reproduced",
        "accepted_campaign_rows_36": len(campaigns) == 36,
        "unique_campaign_db_ids": len(set(campaign_ids)) == len(campaign_ids),
        "accepted_market_rows_45": len(markets) == EXPECTED_MARKETS,
        "unique_market_ids_45": len(market_ids) == EXPECTED_MARKETS,
        "bridge_covers_45_of_45_markets": bridge_market_ids == market_ids,
        "bridge_key_unique": len(bridge_keys) == len(bridge),
        "bridge_has_no_semicolon_lists": forbidden_semicolon_cells == 0,
        "bridge_required_fields_complete": required_nulls == 0,
        "shared_campaign_counts_reconcile": len(shared_count_mismatches) == 0,
        "dedicated_campaign_counts_reconcile": len(dedicated_count_mismatches) == 0,
        "no_market_linked_campaign_orphans": len(market_campaign_orphans) == 0,
        "epochs_1_to_12_present": sorted({int(row["epoch"]) for row in campaigns})
        == list(range(1, 13)),
        "epoch_budgets_reconcile": observed_epoch_budgets == expected_epoch_budgets,
        "campaign_scope_counts_reconcile": dict(count_by_scope)
        == {
            "shared_market_pool": 25,
            "dedicated_market": 4,
            "direct_vault": 7,
        },
        "campaign_scope_budgets_reconcile": dict(budget_by_scope)
        == {
            "shared_market_pool": 3147500,
            "dedicated_market": 330000,
            "direct_vault": 505000,
        },
        "total_budget_reconciles_3982500": sum(budget_by_scope.values()) == 3982500,
        "phase2_snapshot_is_immutable_accepted_version": sha256_file(
            args.phase2_manifest
        )
        == EXPECTED_PHASE2_MANIFEST_SHA256,
        "phase2_manifest_complete": phase2_manifest.get("status") == "complete"
        and phase2_manifest.get("complete") is True
        and phase2_manifest.get("verified_shard_count") == 3157
        and phase2_manifest.get("row_count") == 1231462,
        "expected_market_day_grain_18225": EXPECTED_MARKET_DAY_ROWS == 18225,
        "free_space_gate_10_gib": disk.free >= MINIMUM_FREE_BYTES,
    }
    status = "pass" if all(checks.values()) else "fail"
    return {
        "version": VERSION,
        "status": status,
        "completed_at_utc": utc_now(),
        "scope": {
            "bridge_grain": "market_id x epoch x side",
            "bridge_rows": len(bridge),
            "bridge_unique_keys": len(bridge_keys),
            "distinct_markets": len(bridge_market_ids),
            "distinct_epochs": len({row["epoch"] for row in bridge}),
            "supply_rows": sum(row["side"] == "supply" for row in bridge),
            "borrow_rows": sum(row["side"] == "borrow" for row in bridge),
            "shared_plus_dedicated_rows": sum(
                row["eligibility_mode"] == "shared_plus_dedicated" for row in bridge
            ),
            "duplicate_keys": duplicate_count(
                bridge, ("market_id", "epoch", "side")
            ),
            "required_nulls": required_nulls,
            "semicolon_cells": forbidden_semicolon_cells,
        },
        "campaign_reconciliation": {
            "campaign_rows": len(campaigns),
            "unique_campaign_db_ids": len(set(campaign_ids)),
            "counts_by_scope": dict(count_by_scope),
            "budgets_arb_by_scope": dict(budget_by_scope),
            "market_linked_budget_arb": budget_by_scope["shared_market_pool"]
            + budget_by_scope["dedicated_market"],
            "direct_vault_budget_arb_not_attributed": budget_by_scope["direct_vault"],
            "total_budget_arb": sum(budget_by_scope.values()),
            "budget_arb_by_epoch": observed_epoch_budgets,
            "shared_campaign_count_mismatches": shared_count_mismatches,
            "dedicated_campaign_count_mismatches": dedicated_count_mismatches,
            "market_linked_campaign_orphans": market_campaign_orphans,
            "bridge_orphan_markets": sorted(bridge_market_ids - market_ids),
            "accepted_markets_without_bridge_rows": sorted(market_ids - bridge_market_ids),
            "attribution_policy": {
                "shared_pool_budget": "campaign-level only; never divided or duplicated across bridge rows",
                "dedicated_market_budget": "retained only in dedicated_market_allocation_arb because target is one exact market",
                "direct_vault_505k": "excluded from bridge; no underlying-market attribution without time-aware vault evidence",
            },
        },
        "reproducibility": {
            "comparison_status": comparison.get("status"),
            "comparison_defects": comparison.get("total_defects"),
            "manifest_status": reproduction.get("status"),
            "raw_snapshot_sha256": reproduction.get("api", {}).get(
                "response_sha256"
            ),
            "accepted_csv_files_were_modified": False,
        },
        "full_build_preflight": {
            "target_grain": "market_id x UTC day",
            "markets": EXPECTED_MARKETS,
            "utc_day_buckets": EXPECTED_DAYS,
            "expected_rows": EXPECTED_MARKET_DAY_ROWS,
            "source_shards": phase2_manifest.get("verified_shard_count"),
            "source_event_rows": phase2_manifest.get("row_count"),
            "source_bytes": prototype_cost["source_bytes_read_one_pass"],
            "projected_runtime_seconds_with_25pct_headroom": prototype_cost[
                "projected_full_sql_seconds_with_25pct_headroom"
            ],
            "projected_database_bytes_with_25pct_headroom": prototype_cost[
                "projected_full_database_bytes_with_25pct_headroom"
            ],
            "projected_database_gib": prototype_cost["projected_full_database_gib"],
            "projected_working_set_gib_including_existing_source": prototype_cost[
                "projected_full_working_set_gib_including_existing_source"
            ],
            "minimum_free_bytes_gate": MINIMUM_FREE_BYTES,
            "minimum_free_gib_gate": MINIMUM_FREE_BYTES / 1024**3,
            "observed_free_bytes": disk.free,
            "observed_free_gib": round(disk.free / 1024**3, 6),
            "free_space_gate_pass": disk.free >= MINIMUM_FREE_BYTES,
            "gba_bytes_billed": 0,
            "new_rpc_calls": 0,
            "projection_basis": "accepted three-market SQLite prototype scaled by known 45-market event population with 25% headroom",
            "not_executed": [
                "full 45-market market-day build",
                "new RPC extraction",
                "new GBA query",
                "Phase 7 analysis",
            ],
        },
        "inputs": inputs,
        "checks": checks,
        "limitations": [
            "The preflight validates eligibility normalization and build readiness; it does not validate the unbuilt 45-market daily output.",
            "The 498.223-second runtime and 7.250977-GiB database estimates are engineering projections from Phase 4, not observed Phase 6 build measurements.",
            "The immutable Phase 2 manifest identity is checked here; the 3,157 shards are not rescanned in this bounded step.",
            "Frozen metrics v1.0 are inputs only and were not changed.",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--campaigns", type=Path, required=True)
    parser.add_argument("--markets", type=Path, required=True)
    parser.add_argument("--reproduction-manifest", type=Path, required=True)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--phase2-manifest", type=Path, required=True)
    parser.add_argument("--day-boundaries", type=Path, required=True)
    parser.add_argument("--prototype-qa", type=Path, required=True)
    parser.add_argument("--prototype-build-sql", type=Path, required=True)
    parser.add_argument("--prototype-qa-sql", type=Path, required=True)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--bridge-output", type=Path, required=True)
    parser.add_argument("--qa-output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    reproduction = load_json(args.reproduction_manifest)
    comparison = load_json(args.comparison)
    if reproduction.get("status") != "reproduced" or comparison.get("status") != "match":
        raise PreflightError(
            "Phase 1 API comparison is not an exact semantic match; refusing to build the bridge"
        )
    campaigns = load_csv(args.campaigns)
    markets = load_csv(args.markets)
    bridge = build_bridge(campaigns, markets)
    atomic_write(args.bridge_output, csv_payload(bridge))
    report = qa(
        args,
        campaigns,
        markets,
        bridge,
        load_json(args.phase2_manifest),
        load_json(args.prototype_qa),
        reproduction,
        comparison,
    )
    atomic_write(
        args.qa_output,
        (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "bridge_rows": len(bridge),
                "expected_market_day_rows": EXPECTED_MARKET_DAY_ROWS,
                "qa": str(args.qa_output),
            }
        )
    )
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PreflightError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
