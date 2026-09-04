#!/usr/bin/env python3
"""Read-only Phase 8 cross-check, independent of the Phase 7 analysis module.

Recompute checkpoint levels/ratios from accepted production state and rebuild
cross-sectional borrower counts from the production event ledger. No RPC,
production writes, figure generation, or imports from analyze_phase7_metrics.
This same-author preflight is NOT a substitute for independent reviewer signoff.
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
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for part in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def check(test, message):
    if not test:
        raise RuntimeError(message)


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.part')
    with tmp.open('w', encoding='utf-8', newline='\n') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, default=Path('data/release/phase8_headline_verification.json'))
    args = parser.parse_args()
    root = args.root.resolve()
    out = root / args.output
    t0 = time.perf_counter()
    report = {'version': 'phase8-headline-review-v1', 'status': 'RUNNING',
              'review_type': 'same_author_independent_code_path_not_external_signoff',
              'network_calls': 0, 'production_access': 'mode=ro&immutable=1; query_only=ON'}
    try:
        manifest = json.loads((root / 'data/morpho_phase7_analysis_manifest.json').read_text(encoding='utf-8'))
        for item in [manifest['script'], *manifest['outputs']]:
            __import__('release_support').verify_accepted(root, item)
        sources = {'production_db_sha256': 'data/tmp/morpho_market_day_full_v1.sqlite',
                   'frozen_metrics_sha256': 'docs/METRICS.md',
                   'eligibility_bridge_sha256': 'data/drip_morpho_eligibility_bridge.csv',
                   'market_csv_sha256': 'data/drip_morpho_markets.csv',
                   'boundary_json_sha256': 'data/morpho_phase7_boundary_map.json',
                   'boundary_manifest_sha256': 'data/morpho_phase7_boundary_manifest.json'}
        for field, path in sources.items():
            check(digest(root / path) == manifest['inputs'][field], 'Input hash mismatch: ' + path)
        report['source_identities'] = {k: manifest['inputs'][k] for k in sources}
        boundaries = json.loads((root / sources['boundary_json_sha256']).read_text(encoding='utf-8'))['boundaries']
        baseline_start = datetime(2025, 7, 9, 13, tzinfo=timezone.utc)
        campaign_start = datetime(2025, 9, 3, 13, tzinfo=timezone.utc)
        end = datetime(2026, 2, 18, 13, tzinfo=timezone.utc)
        iso = lambda t: t.strftime('%Y-%m-%dT%H:%M:%SZ')
        bdates = [iso(baseline_start + timedelta(days=i)) for i in range(1, 57)]
        qdates = [iso(campaign_start + timedelta(days=i)) for i in range(169)]
        pdates = {'p'+str(d): iso(end + timedelta(days=d)) for d in (30, 90, 180)}
        targets = sorted(set(bdates + qdates + list(pdates.values())))
        check([b['target_timestamp_utc'] for b in boundaries] == targets, 'Frozen timestamp list mismatch')
        for b in boundaries:
            check(b['predecessor_block'] + 1 == b['chosen_block'], 'Boundary adjacency')
            check(b['predecessor_timestamp_unix'] < b['target_timestamp_unix'] <= b['chosen_timestamp_unix'], 'Boundary inequality')
            check(b['chosen_parent_hash'] == b['predecessor_hash'], 'Boundary parent hash')
        db = root / sources['production_db_sha256']
        c = sqlite3.connect('file:' + db.as_posix() + '?mode=ro&immutable=1', uri=True)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA query_only=ON')
        check(c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'SQLite integrity')
        markets = {r['market_id']: dict(r) for r in c.execute('SELECT * FROM market_dim')}
        check(len(markets) == 45, 'Market count')
        states = {date: {} for date in targets}
        fields = ['total_supply_assets', 'total_supply_shares', 'total_borrow_assets', 'total_borrow_shares', 'total_collateral_assets']
        # Separate as-of algorithm: load each ordered timeline, binary-search its
        # block array for each frozen boundary, and select the preceding state.
        for market in markets:
            rows = list(c.execute('SELECT block_number, event_sequence, ' + ','.join(fields) + ' FROM market_event_state WHERE market_id=? ORDER BY event_sequence', (market,)))
            blocks = [r['block_number'] for r in rows]
            check(blocks == sorted(blocks), 'Noncanonical production order')
            for b in boundaries:
                i = bisect.bisect_left(blocks, b['chosen_block']) - 1
                check(i >= 0, 'Missing anchor')
                states[b['target_timestamp_utc']][market] = {f: int(rows[i][f]) for f in fields}
        positions = defaultdict(int)
        active = {}
        dust = {}
        per_market = {}
        iterator = iter(c.execute("SELECT market_id,owner,block_number,event_family,shares,repaid_shares,bad_debt_shares FROM source_event WHERE event_family IN ('Borrow','Repay','Liquidate') ORDER BY block_number,transaction_index,log_index"))
        event = next(iterator, None)
        event_count = 0
        for b in boundaries:
            while event is not None and event['block_number'] < b['chosen_block']:
                key = (event['market_id'], event['owner'])
                family = event['event_family']
                if family == 'Borrow':
                    delta = int(event['shares'])
                elif family == 'Repay':
                    delta = -int(event['shares'])
                else:
                    delta = -int(event['repaid_shares']) - int(event['bad_debt_shares'])
                positions[key] += delta
                check(positions[key] >= 0, 'Negative borrower shares')
                if not positions[key]:
                    del positions[key]
                event_count += 1
                event = next(iterator, None)
            ts = b['target_timestamp_utc']
            primary, share_only = set(), set()
            sums, counts = Counter(), Counter()
            for (market, owner), shares in positions.items():
                sums[market] += shares
                if owner == '0x' + '0' * 40:
                    continue
                state = states[ts][market]
                # divmod makes the up-rounding explicit, without using Phase 7's helper.
                debt, remainder = divmod(shares * (state['total_borrow_assets'] + 1), state['total_borrow_shares'] + 1_000_000)
                debt += bool(remainder)
                share_only.add(owner)
                if debt >= 1_000_000:  # both frozen loan addresses have six decimals
                    primary.add(owner)
                    counts[market] += 1
            for market in markets:
                check(sums[market] == states[ts][market]['total_borrow_shares'], 'Wallet/market share mismatch')
            active[ts], dust[ts], per_market[ts] = len(primary), len(share_only), counts
        levels = {'borrowed_assets': 'total_borrow_assets', 'supplied_assets': 'total_supply_assets', 'collateral_assets': 'total_collateral_assets'}
        compared = 0
        applicability = Counter()
        def compare(row, series):
            nonlocal compared
            baseline_sum = sum(series[t] for t in bdates)
            B = Fraction(baseline_sum, 56)
            E = series[iso(end)]
            Q = max(series[t] for t in qdates)
            P = series[pdates[row['post_checkpoint']]]
            for key, expected in [('baseline_sum_base_units', baseline_sum), ('campaign_end_base_units', E), ('campaign_peak_base_units', Q), ('post_value_base_units', P)]:
                check(int(row[key]) == expected, 'Level mismatch: ' + str((row['scope_id'], row['metric'], row['post_checkpoint'], key)))
            check(row['campaign_peak_timestamp_utc'] == next(t for t in qdates if series[t] == Q), 'Peak timestamp mismatch')
            for name, denominator in [('primary', Fraction(E)-B), ('peak', Fraction(Q)-B)]:
                value = row[name + '_retained_uplift']
                if denominator <= 0:
                    check(value == '' and row[name + '_applicability'].startswith('not_applicable'), 'N/A mismatch')
                else:
                    check(row[name + '_applicability'] == 'applicable', 'Applicability mismatch')
                    check(abs(Fraction(value) - (P-B)/denominator) <= Fraction(1, 2*10**12), 'Ratio mismatch')
            compared += 1
            return {'metric': row['metric'], 'scope_id': row['scope_id'], 'post_checkpoint': row['post_checkpoint'],
                    'B_exact': str(B), 'E': str(E), 'Q': str(Q), 'P': str(P),
                    'primary_ratio_exact': str((P-B)/(E-B)) if E>B else None}
        for row in read_csv(root/'data/morpho_phase7_market_retained_uplift.csv'):
            m, metric = row['market_id'], row['metric']
            series = {t: per_market[t][m] if metric == 'active_borrowers' else states[t][m][levels[metric]] for t in targets}
            compare(row, series)
            if row['post_checkpoint'] == 'p180':
                applicability[(metric, row['primary_applicability'])] += 1
        headlines = []
        for row in read_csv(root/'data/morpho_phase7_portfolio_retained_uplift.csv'):
            metric = row['metric']
            if metric in ('active_borrowers', 'active_borrowers_shares_only'):
                series = active if metric == 'active_borrowers' else dust
            else:
                address_field = 'collateral_address' if metric == 'collateral_assets' else 'loan_address'
                members = [m for m,r in markets.items() if r[address_field].lower() == row['unit_address'].lower()]
                check(members, 'Empty exact-token group')
                series = {t: sum(states[t][m][levels[metric]] for m in members) for t in targets}
            verified = compare(row, series)
            if metric in ('borrowed_assets', 'active_borrowers', 'active_borrowers_shares_only'):
                headlines.append(verified)
        c.close()
        check(digest(db) == manifest['inputs']['production_db_sha256'], 'Production changed')
        report.update(status='PASS', checked_metric_rows=compared, market_checkpoint_share_checks=45*len(targets),
                      wallet_events_replayed=event_count, defects=0, headlines=headlines,
                      applicability={metric: {status: count for (m,status),count in applicability.items() if m == metric} for metric in levels.keys() | {'active_borrowers'}},
                      runtime_seconds=round(time.perf_counter()-t0, 3),
                      environment={'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version},
                      production_unchanged=True)
        save(out, report)
        print(json.dumps({k: report[k] for k in ('status','checked_metric_rows','market_checkpoint_share_checks','defects','runtime_seconds')}))
        return 0
    except Exception as exc:
        report.update(status='BLOCKED', blocker=str(exc), runtime_seconds=round(time.perf_counter()-t0, 3))
        save(out, report)
        print('BLOCKED: ' + str(exc))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
