#!/usr/bin/env python3
"""Rebuild and compare the accepted DRIP x Morpho Phase 1 scope.

The script is deliberately fail-closed: it writes a timestamped raw Merkl
snapshot and candidate CSVs under ignored ``data/raw`` / ``data/tmp`` paths,
then compares them with the accepted CSVs.  It never overwrites the accepted
files.  A non-zero exit means the current API response does not reproduce the
accepted Phase 1 content or violates the frozen extraction contract.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable


VERSION = "drip-morpho-scope-extractor-v1"
API_URL = (
    "https://api.merkl.xyz/v4/opportunities?mainProtocolId=morpho&tags=drip"
    "&campaigns=true&status=PAST&items=100&page=0"
)
CHAIN_ID = 42161
DRIP_CREATOR = "0x7d0a9493edecf7112486319e0fdba72fc7a62468"
ARB_TOKEN = "0x912ce59144191c1204e64559fe8253a0e49e6548"
CAMPAIGN_START = 1756904400  # 2025-09-03T13:00:00Z
EPOCH_SECONDS = 14 * 24 * 60 * 60
EPOCH_COUNT = 12
CAMPAIGN_END = CAMPAIGN_START + EPOCH_COUNT * EPOCH_SECONDS
ROOT_ID_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
MARKET_ID_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

CAMPAIGN_FIELDS = [
    "epoch",
    "start_utc",
    "end_utc",
    "allocation_arb",
    "scope",
    "side",
    "target",
    "unique_market_count",
    "target_address",
    "opportunity_name",
    "campaign_db_id",
    "campaign_id",
    "opportunity_id",
    "source_url",
]
MARKET_FIELDS = [
    "market_id",
    "loan_symbol",
    "loan_address",
    "collateral_symbol",
    "collateral_address",
    "lltv_1e18",
    "supply_epochs",
    "borrow_epochs",
]


class ScopeError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def iso_utc(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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


def fetch_json(url: str, retries: int = 3) -> tuple[bytes, Any, int]:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": f"Morpho-DRIP-research/{VERSION}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                if response.status != 200:
                    raise ScopeError(f"unexpected HTTP status {response.status}")
                content_type = response.headers.get("Content-Type", "")
                if "json" not in content_type.lower():
                    raise ScopeError(f"unexpected Content-Type {content_type!r}")
                payload = response.read()
            parsed = json.loads(payload)
            if not isinstance(parsed, list):
                raise ScopeError("Merkl response must be a JSON array")
            return payload, parsed, attempt
        except (OSError, urllib.error.URLError, json.JSONDecodeError, ScopeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(2 ** (attempt - 1))
    raise ScopeError(f"Merkl request failed after {retries} attempts: {last_error}")


def campaign_epoch(campaign: dict[str, Any]) -> int:
    start = int(campaign["startTimestamp"])
    end = int(campaign["endTimestamp"])
    offset = start - CAMPAIGN_START
    if offset < 0 or offset % EPOCH_SECONDS:
        raise ScopeError(f"campaign {campaign['id']} has a non-epoch start {start}")
    epoch = offset // EPOCH_SECONDS + 1
    if epoch < 1 or epoch > EPOCH_COUNT or end != start + EPOCH_SECONDS:
        raise ScopeError(
            f"campaign {campaign['id']} has invalid epoch bounds {start}..{end}"
        )
    return epoch


def arb_amount(raw_amount: Any) -> str:
    amount = Decimal(str(raw_amount)) / Decimal(10**18)
    if amount != amount.to_integral_value():
        text = format(amount.normalize(), "f")
        return text.rstrip("0").rstrip(".") if "." in text else text
    return str(int(amount))


def root_records(opportunities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    retained: dict[str, dict[str, Any]] = {}
    allowed_types = {
        "MULTILENDSUPPLY",
        "MULTILENDBORROW",
        "MORPHOSUPPLY",
        "ERC20LOGPROCESSOR",
    }
    for opportunity in opportunities:
        for campaign in opportunity.get("campaigns") or []:
            campaign_id = str(campaign.get("campaignId", ""))
            if not ROOT_ID_RE.fullmatch(campaign_id):
                continue
            if int(campaign.get("computeChainId", -1)) != CHAIN_ID:
                continue
            if int(campaign.get("distributionChainId", -1)) != CHAIN_ID:
                continue
            if str(campaign.get("creatorAddress", "")).lower() != DRIP_CREATOR:
                continue
            reward = campaign.get("rewardToken") or {}
            if str(reward.get("address", "")).lower() != ARB_TOKEN:
                continue
            start = int(campaign.get("startTimestamp", -1))
            end = int(campaign.get("endTimestamp", -1))
            if not (CAMPAIGN_START <= start < CAMPAIGN_END and end <= CAMPAIGN_END):
                continue
            if campaign.get("type") not in allowed_types:
                raise ScopeError(
                    f"unexpected retained campaign type {campaign.get('type')!r}"
                )
            db_id = str(campaign.get("id", ""))
            if not db_id.isdigit():
                raise ScopeError(f"invalid campaign database id {db_id!r}")
            record = {"opportunity": opportunity, "campaign": campaign}
            previous = retained.get(db_id)
            if previous is not None:
                left = json.dumps(previous["campaign"], sort_keys=True, separators=(",", ":"))
                right = json.dumps(campaign, sort_keys=True, separators=(",", ":"))
                if left != right or str(previous["opportunity"].get("id")) != str(
                    opportunity.get("id")
                ):
                    raise ScopeError(f"conflicting duplicate campaign database id {db_id}")
            retained[db_id] = record
    rows = list(retained.values())
    if len(rows) != 36:
        raise ScopeError(f"expected 36 retained root campaigns, found {len(rows)}")
    return rows


def market_payloads(campaign: dict[str, Any]) -> list[dict[str, Any]]:
    params = campaign.get("params") or {}
    campaign_type = campaign["type"]
    if campaign_type in {"MULTILENDSUPPLY", "MULTILENDBORROW"}:
        result = []
        seen: set[str] = set()
        for child in params.get("markets") or []:
            market = (child.get("campaignParameters") or {}).copy()
            market_id = str(market.get("market", "")).lower()
            if not MARKET_ID_RE.fullmatch(market_id):
                raise ScopeError(f"invalid child market id {market_id!r}")
            if market_id in seen:
                continue
            seen.add(market_id)
            result.append(market)
        return result
    if campaign_type == "MORPHOSUPPLY":
        return [params]
    return []


def classify(
    campaign: dict[str, Any], opportunity_action: str
) -> tuple[str, str, str, str, list[dict[str, Any]]]:
    campaign_type = campaign["type"]
    params = campaign.get("params") or {}
    markets = market_payloads(campaign)
    if campaign_type in {"MULTILENDSUPPLY", "MULTILENDBORROW"}:
        scope = "shared_market_pool"
        if opportunity_action == "LEND":
            side = "supply"
        elif opportunity_action == "BORROW":
            side = "borrow"
        else:
            raise ScopeError(
                f"shared campaign {campaign['id']} has unexpected opportunity "
                f"action {opportunity_action!r}"
            )
    elif campaign_type == "MORPHOSUPPLY":
        scope, side = "dedicated_market", "supply"
    elif campaign_type == "ERC20LOGPROCESSOR":
        scope, side = "direct_vault", "supply"
    else:  # protected by root_records
        raise ScopeError(f"unsupported campaign type {campaign_type!r}")

    if scope == "direct_vault":
        target = str(params.get("symbolTargetToken", ""))
        target_address = str(params.get("targetToken", ""))
        if target not in {"bbqUSDC", "bbqUSDT0"} or not ADDRESS_RE.fullmatch(
            target_address
        ):
            raise ScopeError(f"unexpected direct-vault target {target} {target_address}")
        return scope, side, target, target_address, markets

    if not markets:
        raise ScopeError(f"campaign {campaign['id']} has no Morpho market payloads")
    symbols = {str(item.get("symbolLoanToken", "")) for item in markets}
    if len(symbols) != 1 or next(iter(symbols)) not in {"USDC", "USD₮0"}:
        raise ScopeError(f"campaign {campaign['id']} has inconsistent loan symbols {symbols}")
    target = next(iter(symbols))
    target_address = "" if scope == "shared_market_pool" else str(markets[0]["market"]).lower()
    return scope, side, target, target_address, markets


def extract(
    opportunities: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    campaigns: list[dict[str, str]] = []
    market_state: dict[str, dict[str, Any]] = {}

    for record in root_records(opportunities):
        opportunity = record["opportunity"]
        campaign = record["campaign"]
        epoch = campaign_epoch(campaign)
        scope, side, target, target_address, markets = classify(
            campaign, str(opportunity.get("action", ""))
        )
        campaigns.append(
            {
                "epoch": str(epoch),
                "start_utc": iso_utc(int(campaign["startTimestamp"])),
                "end_utc": iso_utc(int(campaign["endTimestamp"])),
                "allocation_arb": arb_amount(campaign["amount"]),
                "scope": scope,
                "side": side,
                "target": target,
                "unique_market_count": str(len(markets)),
                "target_address": target_address,
                "opportunity_name": str(opportunity.get("name", "")),
                "campaign_db_id": str(campaign["id"]),
                "campaign_id": str(campaign["campaignId"]),
                "opportunity_id": str(opportunity["id"]),
                "source_url": f"https://api.merkl.xyz/v4/campaigns/{campaign['id']}",
            }
        )
        for payload in markets:
            market_id = str(payload["market"]).lower()
            metadata = {
                "market_id": market_id,
                "loan_symbol": str(payload["symbolLoanToken"]),
                "loan_address": str(payload["loanToken"]),
                "collateral_symbol": str(payload["symbolCollateralToken"]),
                "collateral_address": str(payload["collateralToken"]),
                "lltv_1e18": str(payload["LLTV"]),
            }
            if market_id not in market_state:
                market_state[market_id] = {
                    **metadata,
                    "supply_epochs": set(),
                    "borrow_epochs": set(),
                }
            else:
                current = market_state[market_id]
                for field, value in metadata.items():
                    if field == "market_id":
                        continue
                    if field.endswith("_address"):
                        same = str(current[field]).lower() == value.lower()
                    else:
                        same = str(current[field]) == value
                    if not same:
                        raise ScopeError(
                            f"market {market_id} metadata changed for {field}: "
                            f"{current[field]!r} != {value!r}"
                        )
            market_state[market_id][f"{side}_epochs"].add(epoch)

    scope_order = {"dedicated_market": 0, "direct_vault": 1, "shared_market_pool": 2}
    side_order = {"borrow": 0, "supply": 1}
    target_order = {"bbqUSDC": 0, "bbqUSDT0": 1, "USD₮0": 2, "USDC": 3}
    campaigns.sort(
        key=lambda row: (
            int(row["epoch"]),
            scope_order[row["scope"]],
            side_order[row["side"]],
            target_order[row["target"]],
            row["campaign_db_id"],
        )
    )
    markets_out = []
    for market in market_state.values():
        markets_out.append(
            {
                **{field: str(market[field]) for field in MARKET_FIELDS[:6]},
                "supply_epochs": ";".join(
                    str(value) for value in sorted(market["supply_epochs"])
                ),
                "borrow_epochs": ";".join(
                    str(value) for value in sorted(market["borrow_epochs"])
                ),
            }
        )
    # Preserve the accepted presentation order while keeping market_id as the
    # final deterministic tie-break for repeated collateral symbols.
    markets_out.sort(
        key=lambda row: (
            0 if row["loan_symbol"] == "USD₮0" else 1,
            row["collateral_symbol"].casefold(),
            row["market_id"],
        )
    )
    if len(markets_out) != 45:
        raise ScopeError(f"expected 45 distinct markets, found {len(markets_out)}")
    return campaigns, markets_out


def csv_bytes(rows: list[dict[str, str]], fields: list[str]) -> bytes:
    import io

    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def compare_rows(
    accepted: list[dict[str, str]],
    candidate: list[dict[str, str]],
    key_field: str,
    address_fields: Iterable[str] = (),
) -> dict[str, Any]:
    address_fields = set(address_fields)
    accepted_by_key = {row[key_field].lower(): row for row in accepted}
    candidate_by_key = {row[key_field].lower(): row for row in candidate}
    if len(accepted_by_key) != len(accepted) or len(candidate_by_key) != len(candidate):
        raise ScopeError(f"duplicate {key_field} while comparing CSV rows")
    missing = sorted(set(accepted_by_key) - set(candidate_by_key))
    extra = sorted(set(candidate_by_key) - set(accepted_by_key))
    mismatches = []
    for key in sorted(set(accepted_by_key) & set(candidate_by_key)):
        left, right = accepted_by_key[key], candidate_by_key[key]
        differences = {}
        for field in left:
            left_value, right_value = left[field], right.get(field, "")
            if field in address_fields:
                equal = left_value.lower() == right_value.lower()
            else:
                equal = left_value == right_value
            if not equal:
                differences[field] = {"accepted": left_value, "candidate": right_value}
        if differences:
            mismatches.append({"key": key, "fields": differences})
    return {
        "accepted_rows": len(accepted),
        "candidate_rows": len(candidate),
        "missing_keys": missing,
        "extra_keys": extra,
        "field_mismatches": mismatches,
        "defect_count": len(missing) + len(extra) + len(mismatches),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=API_URL)
    parser.add_argument(
        "--raw-snapshot",
        type=Path,
        help="Use an existing JSON response instead of making a network request.",
    )
    parser.add_argument("--accepted-campaigns", type=Path, required=True)
    parser.add_argument("--accepted-markets", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--comparison-report", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    fetched_at = utc_now()
    if args.raw_snapshot:
        raw_path = args.raw_snapshot
        raw_payload = raw_path.read_bytes()
        opportunities = json.loads(raw_payload)
        if not isinstance(opportunities, list):
            raise ScopeError("Merkl raw snapshot must be a JSON array")
        attempts = 0
        source_mode = "existing_raw_snapshot"
        fetched_at = datetime.fromtimestamp(
            raw_path.stat().st_mtime, timezone.utc
        ).isoformat().replace("+00:00", "Z")
    else:
        stamp = fetched_at.replace("-", "").replace(":", "").replace(".", "")
        raw_payload, opportunities, attempts = fetch_json(args.api_url)
        raw_path = args.raw_dir / f"merkl_opportunities_{stamp}.json"
        atomic_write(raw_path, raw_payload)
        source_mode = "live_api"

    campaigns, markets = extract(opportunities)
    candidate_campaign_path = args.candidate_dir / "drip_morpho_epoch_campaigns.csv"
    candidate_market_path = args.candidate_dir / "drip_morpho_markets.csv"
    atomic_write(candidate_campaign_path, csv_bytes(campaigns, CAMPAIGN_FIELDS))
    atomic_write(candidate_market_path, csv_bytes(markets, MARKET_FIELDS))

    campaign_comparison = compare_rows(
        read_csv(args.accepted_campaigns), campaigns, "campaign_db_id", ["target_address"]
    )
    market_comparison = compare_rows(
        read_csv(args.accepted_markets),
        markets,
        "market_id",
        ["market_id", "loan_address", "collateral_address"],
    )
    defect_count = campaign_comparison["defect_count"] + market_comparison["defect_count"]
    comparison = {
        "version": VERSION,
        "status": "match" if defect_count == 0 else "mismatch",
        "compared_at_utc": utc_now(),
        "api_url": args.api_url,
        "accepted_files_were_modified": False,
        "campaigns": campaign_comparison,
        "markets": market_comparison,
        "total_defects": defect_count,
    }
    comparison_payload = (json.dumps(comparison, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    atomic_write(args.comparison_report, comparison_payload)

    manifest = {
        "version": VERSION,
        "status": "reproduced" if defect_count == 0 else "api_mismatch",
        "fetched_at_utc": fetched_at,
        "api": {
            "url": args.api_url,
            "source_mode": source_mode,
            "attempts": attempts,
            "response_bytes": len(raw_payload),
            "response_sha256": sha256_bytes(raw_payload),
            "raw_snapshot_path": str(raw_path.resolve()),
        },
        "frozen_filter": {
            "chain_id": CHAIN_ID,
            "creator": DRIP_CREATOR,
            "reward_token": ARB_TOKEN,
            "campaign_start_utc": iso_utc(CAMPAIGN_START),
            "campaign_end_exclusive_utc": iso_utc(CAMPAIGN_END),
            "root_campaign_id_format": ROOT_ID_RE.pattern,
            "expected_epochs": EPOCH_COUNT,
            "expected_campaigns": 36,
            "expected_markets": 45,
        },
        "extractor": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256_file(Path(__file__)),
        },
        "accepted": {
            "campaign_csv": str(args.accepted_campaigns.resolve()),
            "campaign_csv_sha256": sha256_file(args.accepted_campaigns),
            "market_csv": str(args.accepted_markets.resolve()),
            "market_csv_sha256": sha256_file(args.accepted_markets),
        },
        "candidate": {
            "campaign_csv": str(candidate_campaign_path.resolve()),
            "campaign_csv_sha256": sha256_file(candidate_campaign_path),
            "market_csv": str(candidate_market_path.resolve()),
            "market_csv_sha256": sha256_file(candidate_market_path),
        },
        "comparison": {
            "report_path": str(args.comparison_report.resolve()),
            "report_sha256": sha256_file(args.comparison_report),
            "total_defects": defect_count,
        },
        "safety": {
            "accepted_csv_overwrite_supported": False,
            "candidate_and_raw_paths_are_gitignored": True,
        },
    }
    atomic_write(
        args.manifest,
        (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
    )
    print(json.dumps({"status": manifest["status"], "defects": defect_count, "manifest": str(args.manifest)}))
    return 0 if defect_count == 0 else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ScopeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
