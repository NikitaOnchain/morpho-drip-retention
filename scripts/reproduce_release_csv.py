"""CSV-only checks and six figures. No production DB, metadata raw, RPC or GBA.

Validates published-table identities and internal arithmetic; this does NOT
reconstruct source events or independently establish onchain completeness.
"""
import argparse
import csv
import json
import platform
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from collections import Counter, defaultdict
from fractions import Fraction as F
from pathlib import Path

from release_support import sha, save, require, verify_accepted


def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def validate(root):
    accepted = json.loads((root/'data/morpho_phase7_analysis_manifest.json').read_text(encoding='utf8'))
    paths = [i for i in accepted['outputs'] if i['path'].endswith('.csv')]
    for item in paths:
        require(sha(root/item['path']) == item['sha256'], 'Frozen CSV changed: '+item['path'])
    data = {Path(i['path']).stem: rows(root/i['path']) for i in paths}
    market = data['morpho_phase7_market_retained_uplift']
    portfolio = data['morpho_phase7_portfolio_retained_uplift']
    series = data['morpho_phase7_checkpoint_series']
    flows = data['morpho_phase7_period_flows']
    concentration = data['morpho_phase7_market_concentration']
    require(len(market) == 540 and len(portfolio) == 108, 'Metric population')
    require(len({r['market_id'] for r in market}) == 45, 'Fixed market population')
    for dataset, keys in [(market, ('market_id','metric','post_checkpoint')),
                          (portfolio, ('scope_id','metric','post_checkpoint')),
                          (series, ('population_type','population_id','metric','target_timestamp_utc')),
                          (flows, ('scope_type','scope_id','period')),
                          (concentration, ('market_id','checkpoint'))]:
        values = [tuple(r[k] for k in keys) for r in dataset]
        require(len(values) == len(set(values)), 'Duplicate published keys')
        require(all(all(v != '' for v in key) for key in values), 'Required key NULL')
    checks = 0
    native_checks = 0
    for r in market + portfolio:
        B, E, Q, P = F(r['baseline_sum_base_units'])/56, F(r['campaign_end_base_units']), F(r['campaign_peak_base_units']), F(r['post_value_base_units'])
        divisor=10**int(r['unit_decimals'] or 0)
        for key,value in [('baseline_mean_native',B/divisor),('campaign_end_native',E/divisor),('campaign_peak_native',Q/divisor),('post_value_native',P/divisor),('campaign_end_uplift_native',(E-B)/divisor),('post_uplift_native',(P-B)/divisor)]:
            require(abs(F(r[key])-value)<=F(1,2*10**12),'Native unit/delta mismatch: '+key)
            native_checks+=1
        for prefix, denominator in [('primary',E-B),('peak',Q-B)]:
            if denominator <= 0:
                require(r[prefix+'_applicability'].startswith('not_applicable') and r[prefix+'_retained_uplift']=='', 'N/A error')
            else:
                require(r[prefix+'_applicability']=='applicable', 'Applicability error')
                require(abs(F(r[prefix+'_retained_uplift'])-(P-B)/denominator)<=F(1,2*10**12), 'Ratio error')
            checks += 1
    groups=defaultdict(dict)
    for r in series:groups[(r['population_type'],r['population_id'],r['metric'])][r['target_timestamp_utc']]=F(r['value_base_units'])
    iso=lambda d:d.strftime('%Y-%m-%dT%H:%M:%SZ')
    start=datetime(2025,7,9,13,tzinfo=timezone.utc);campaign=datetime(2025,9,3,13,tzinfo=timezone.utc)
    bd=[iso(start+timedelta(days=i)) for i in range(1,57)];qd=[iso(campaign+timedelta(days=i)) for i in range(169)]
    checkpoint_checks=0
    for (kind,pop,metric),values in groups.items():
        candidates=[r for r in (market if kind=='archetype_market' else portfolio) if r['metric']==metric and (r['archetype']==pop if kind=='archetype_market' else r['scope_id']==pop)]
        require(len(values)==227 and len(candidates)==3,'Series population mismatch')
        for r in candidates:
            require(sum(values[t] for t in bd)==F(r['baseline_sum_base_units']),'Series baseline mismatch')
            require(values[qd[-1]]==F(r['campaign_end_base_units']),'Series E mismatch')
            require(max(values[t] for t in qd)==F(r['campaign_peak_base_units']),'Series peak mismatch')
            require(values[r['post_timestamp_utc']]==F(r['post_value_base_units']),'Series P mismatch')
            checkpoint_checks+=1
    for r in flows:
        get=lambda k:int(r[k+'_base_units'])
        delta=get('borrow_assets_out')+get('accrued_interest_assets')-get('repay_assets_in')-get('liquidation_repaid_assets')-get('liquidation_bad_debt_assets')
        require(delta==get('closing_debt')-get('opening_debt')==get('expected_debt_delta')==get('observed_debt_delta') and get('reconciliation_residual')==0,'Flow equation')
    concentration_groups=defaultdict(list)
    for r in concentration:concentration_groups[(r['loan_address'],r['checkpoint'])].append(r)
    for (address,checkpoint),group in concentration_groups.items():
        total=sum(int(r['borrowed_assets_base_units']) for r in group)
        p=next(r for r in portfolio if r['metric']=='borrowed_assets' and r['scope_id']==address and r['post_checkpoint']=='p180')
        require(total==int(p['campaign_end_base_units' if checkpoint=='campaign_end' else 'post_value_base_units']),'Concentration total')
        for r in group:require(abs(F(r['share_of_exact_loan_total'])-F(int(r['borrowed_assets_base_units']),total))<=F(1,2*10**12),'Concentration denominator')
    applicable = Counter((r['metric'],r['primary_applicability']) for r in market if r['post_checkpoint']=='p180')
    return [series, market, portfolio, flows, concentration], {
        'csv_files':len(paths), 'metric_rows':len(market)+len(portfolio),
        'ratio_applicability_checks':checks, 'series_rows':len(series),
        'native_unit_delta_checks':native_checks,'checkpoint_metric_reconciliations':checkpoint_checks,
        'flow_equations':len(flows),'concentration_group_totals':len(concentration_groups),
        'concentration_rows':len(concentration), 'flow_rows':len(flows),
        'applicability':{str(k):v for k,v in applicable.items()},
        'input_sha256':{i['path']:sha(root/i['path']) for i in paths}}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--verify-figures', action='store_true')
    a=p.parse_args()
    root=Path(__file__).resolve().parents[1]
    out=a.output.resolve()
    require(not out.exists(), 'Choose a fresh output directory')
    data, report=validate(root)
    import release_chart_renderer as renderer
    import PIL
    names=json.loads((root/'release/chart_contract.json').read_text(encoding='utf8'))['figure_paths']
    renderer.FIGURES={k:out/Path(v).name for k,v in names.items()}
    renderer.render_figures(*data)
    comparison=[{'path':v, 'rendered_sha256':sha(out/Path(v).name),
                 'package_sha256':sha(root/v), 'byte_equal':sha(out/Path(v).name)==sha(root/v)} for v in names.values()]
    if a.verify_figures:
        require(all(r['byte_equal'] for r in comparison), 'Figure bytes differ; check pinned Pillow/fonts; do not silently certify')
    report.update(status='PASS', scope='published CSV identity/internal arithmetic and render only',
                  network_calls=0,database_reads=0,figures=comparison,
                  python=platform.python_version(),pillow=PIL.__version__,
                  font_evidence=renderer.font_evidence(),
                  source_reconstruction='NOT_RUN')
    save(out/'csv_qa.json',report)
    print(json.dumps({k:report[k] for k in ('status','csv_files','metric_rows','ratio_applicability_checks','database_reads')}))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
