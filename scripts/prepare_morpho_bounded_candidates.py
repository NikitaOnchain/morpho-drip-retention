#!/usr/bin/env python3
"""Build a small exact structural-candidate fixture without rebuilding the full funnel."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from select_morpho_one_position import (
    EVENTS,
    MAX_POSITION_EVENTS,
    MIN_POSITION_EVENTS,
    MORPHO_ADDRESS,
    OWNER_TOPIC_INDEX,
    PairStats,
    market_ids_from_csv,
    structural_funnel,
    topic_address,
    write_candidate_population,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="data/raw/morpho_full_window/manifest.json")
    parser.add_argument("--market-csv", default="data/drip_morpho_markets.csv")
    parser.add_argument("--output", default="data/morpho_phase3_bounded_candidates.json")
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--discovery-pool", type=int, default=40)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not (10 <= args.count <= 20):
        raise RuntimeError("Bounded fixture count must be between 10 and 20")
    if args.discovery_pool < args.count:
        raise RuntimeError("Discovery pool must be at least the requested count")
    manifest_path = Path(args.manifest).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    eligible_markets = market_ids_from_csv(Path(args.market_csv).resolve())
    if manifest.get("status") != "complete" or manifest.get("complete") is not True:
        raise RuntimeError("Full-window manifest is not complete")
    if set(str(value).lower() for value in manifest.get("market_ids", [])) != eligible_markets:
        raise RuntimeError("Manifest market scope does not match the 45-market CSV")

    discovery: dict[tuple[str, str], PairStats] = {}
    selected: dict[tuple[str, str], PairStats] = {}
    selected_markets: set[str] = set()
    accrual_orders: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    frozen = False
    total_rows = 0
    position_rows_for_selected = 0
    previous_order: tuple[int, int, int] | None = None
    shard_root = manifest_path.parent / "shards"

    for entry in manifest["shards"]:
        shard_path = shard_root / str(entry["file"])
        shard_rows = 0
        with shard_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                total_rows += 1
                shard_rows += 1
                order = (int(row["block_number"]), int(row["transaction_index"]), int(row["log_index"]))
                if previous_order is not None and order < previous_order:
                    raise RuntimeError("Ordering violation during bounded fixture scan")
                previous_order = order
                if bool(row.get("removed")):
                    raise RuntimeError("Removed log encountered during bounded fixture scan")
                topics = json.loads(row["topics_json"])
                topic0 = str(topics[0]).lower() if topics else ""
                market_id = str(topics[1]).lower() if len(topics) > 1 else ""
                family = EVENTS.get(topic0)
                if (
                    str(row.get("address", "")).lower() != MORPHO_ADDRESS
                    or family is None
                    or market_id not in eligible_markets
                ):
                    raise RuntimeError("Scope mismatch during bounded fixture scan")
                if family == "AccrueInterest":
                    if not frozen or market_id in selected_markets:
                        accrual_orders[market_id].append(order)
                    continue
                owner_index = OWNER_TOPIC_INDEX[family]
                if len(topics) <= owner_index:
                    raise RuntimeError("Malformed owner topic during bounded fixture scan")
                wallet = topic_address(str(topics[owner_index]))
                key = (market_id, wallet)
                if frozen and key not in selected:
                    continue
                stats = selected.get(key) if frozen else discovery.get(key)
                if stats is None:
                    stats = PairStats(market_id=market_id, wallet=wallet)
                    discovery[key] = stats
                stats.add(family, order, str(row["transaction_hash"]).lower())
                if key in selected:
                    position_rows_for_selected += 1
                if not frozen and family in {"Repay", "Liquidate"}:
                    has_sequence = (
                        stats.first_supply_collateral_order is not None
                        and stats.first_borrow_order is not None
                        and stats.first_supply_collateral_order < stats.first_borrow_order
                        and order > stats.first_borrow_order
                    )
                    accruals = accrual_orders.get(market_id, [])
                    has_accrual = bool(
                        stats.first_borrow_order is not None
                        and any(value > stats.first_borrow_order for value in accruals)
                    )
                    if (
                        key not in selected
                        and has_sequence
                        and has_accrual
                        and MIN_POSITION_EVENTS <= stats.event_count <= MAX_POSITION_EVENTS
                    ):
                        selected[key] = stats
                        selected_markets.add(market_id)
                    if len(selected) >= args.discovery_pool:
                        discovery = dict(selected)
                        frozen = True
        if shard_rows != int(entry["row_count"]):
            raise RuntimeError(f"Shard row-count mismatch: {entry['file']}")

    if total_rows != int(manifest["row_count"]):
        raise RuntimeError("Bounded fixture scan did not cover every manifest row")
    exact, funnel = structural_funnel(selected.values(), accrual_orders)
    exact.sort(key=lambda row: (row.first_order or (0, 0, 0), row.market_id, row.wallet))
    if len(exact) < args.count:
        raise RuntimeError(
            f"Only {len(exact)} exact candidates survived from discovery pool {args.discovery_pool}"
        )
    fixture = exact[: args.count]
    scan_summary = {
        "mode": "bounded_targeted_fixture_scan_not_full_population_funnel",
        "manifest_shards_scanned_for_selected_keys": len(manifest["shards"]),
        "manifest_rows_streamed": total_rows,
        "discovery_pool_target": args.discovery_pool,
        "discovery_pairs_retained": len(selected),
        "exact_structural_candidates_in_pool": len(exact),
        "fixture_candidates": len(fixture),
        "selected_position_rows_observed_after_selection": position_rows_for_selected,
        "global_pair_counts_recomputed": False,
    }
    evidence = write_candidate_population(
        Path(args.output).resolve(),
        fixture,
        manifest_path,
        manifest,
        "bounded_test_structural_candidates",
        scan_summary,
        funnel,
    )
    print(
        json.dumps(
            {
                "output": str(Path(args.output).resolve()),
                "candidate_count": evidence["candidate_count"],
                "candidate_population_sha256": evidence["candidate_population_sha256"],
                "scan_summary": scan_summary,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
