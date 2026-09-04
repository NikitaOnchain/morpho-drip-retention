"""Explicit offline source routes. Use fresh destinations outside the package.

metrics = accepted SQLite -> metrics/review -> revised figures.
raw-preflight = validate bundle, reproduce Phase 1 and bridge, record raw plan.
raw = full offline raw -> prototype -> full state; separate explicit invocation.
"""
import argparse
import json
import os
import runpy
import shutil
import sys
from pathlib import Path
from release_support import sha, save, require, verify_package

RAW='data/raw/drip_morpho_scope/merkl_opportunities_20260902T115959247853Z.json'
DB='data/tmp/morpho_market_day_full_v1.sqlite'


def invoke(job, script, args):
    old_cwd,old_argv,old_path=Path.cwd(),sys.argv[:],sys.path[:]
    try:
        os.chdir(job)
        sys.path.insert(0,str(job/'scripts'))
        sys.argv=[script,*args]
        try:
            runpy.run_path(str(job/'scripts'/script),run_name='__main__')
        except SystemExit as exc:
            require(exc.code in (None,0),'Command failed: '+script)
    finally:
        os.chdir(old_cwd);sys.argv=old_argv;sys.path=old_path


def raw_commands():
    return [
      ['extract_drip_morpho_scope.py','--raw-snapshot',RAW,
       '--accepted-campaigns','data/drip_morpho_epoch_campaigns.csv','--accepted-markets','data/drip_morpho_markets.csv',
       '--raw-dir','work/scope_raw','--candidate-dir','work/scope_candidate',
       '--comparison-report','work/scope_comparison.json','--manifest','work/scope_manifest.json'],
      ['build_morpho_market_day_prototype.py','--offline-only',
       '--manifest','data/raw/morpho_full_window/manifest.json','--boundaries','data/raw/morpho_full_window/day_boundaries.json',
       '--archetypes','data/morpho_phase4_market_archetypes.csv','--sql-build','sql/10_market_day_prototype.sql','--sql-qa','sql/90_qa_market_day_prototype.sql',
       '--checkpoint-plan','data/morpho_phase4_rpc_checkpoint_plan.json','--checkpoint-evidence','work/phase4_rpc_evidence.json',
       '--rpc-cache','data/tmp/morpho_phase4_market_day_rpc.sqlite','--database','work/prototype.sqlite',
       '--sample-output','work/prototype_sample.csv','--qa-output','work/prototype_qa.json'],
      ['prepare_phase6_preflight.py','--workspace','.',
       '--campaigns','data/drip_morpho_epoch_campaigns.csv','--markets','data/drip_morpho_markets.csv',
       '--reproduction-manifest','work/scope_manifest.json','--comparison','work/scope_comparison.json',
       '--phase2-manifest','data/raw/morpho_full_window/manifest.json','--day-boundaries','data/raw/morpho_full_window/day_boundaries.json',
       '--prototype-qa','data/morpho_market_day_prototype_qa.json',
       '--prototype-build-sql','sql/10_market_day_prototype.sql','--prototype-qa-sql','sql/90_qa_market_day_prototype.sql',
       '--metrics','docs/METRICS.md','--bridge-output','work/bridge.csv','--qa-output','work/preflight_qa.json'],
      ['build_morpho_market_day_full.py','--offline-only',
       '--manifest','data/raw/morpho_full_window/manifest.json','--boundaries','data/raw/morpho_full_window/day_boundaries.json',
       '--markets','data/drip_morpho_markets.csv','--bridge','work/bridge.csv','--metrics','docs/METRICS.md',
       '--prototype-db','work/prototype.sqlite','--core-sql','sql/10_market_day_prototype.sql','--core-qa-sql','sql/90_qa_market_day_prototype.sql',
       '--production-sql','sql/20_market_day_full.sql','--production-qa-sql','sql/90_qa_market_day_full.sql',
       '--checkpoint-plan','data/morpho_phase6_rpc_checkpoint_plan.json','--checkpoint-evidence','work/phase6_rpc_evidence.json',
       '--rpc-cache','data/tmp/morpho_phase6_rpc_checkpoints_v1.sqlite','--building-db','work/full.building.sqlite','--final-db','work/full.sqlite',
       '--build-checkpoint','work/full_checkpoint.json','--sample-output','work/full_sample.csv',
       '--coverage-output','work/full_coverage.csv','--qa-output','work/full_qa.json']]


def main(default_mode=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',choices=['metrics','raw-preflight','raw'],default=default_mode or 'metrics')
    p.add_argument('--bundle',type=Path,required=True)
    p.add_argument('--destination',type=Path,required=True)
    a=p.parse_args()
    root=Path(__file__).resolve().parents[1]
    bundle=a.bundle.resolve(); job=a.destination.resolve()
    require(not job.exists(),'Destination must be new')
    require(not job.is_relative_to(root),'Test/source job must be outside public package')
    require(shutil.disk_usage(root).free>=10*1024**3,'Need at least 10 GiB free')
    package=verify_package(root)
    external=json.loads((root/'release/external_inputs.json').read_text(encoding='utf8'))['files']
    needed=[i for i in external if a.mode!='metrics' or i['route']=='metrics']
    # No implicit fallback to a neighbouring/original workspace.
    for item in needed:
        require((bundle/item['path']).is_file(),'Missing explicit external input: '+item['path'])
        require(sha(bundle/item['path'])==item['sha256'],'Source bundle mismatch: '+item['path'])
    for item in package['files']:
        target=job/item['path'];target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(root/item['path'],target)
    for extra in ['release/manifest.json','release/SHA256SUMS.txt']:
        shutil.copyfile(root/extra,job/extra)
    for item in needed:
        target=job/item['path'];target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(bundle/item['path'],target)
    saved=[]
    if a.mode=='metrics':
        # Run review before producer outputs replace metadata in the private job.
        invoke(job,'review_phase7_headlines.py',['--output','work/headline_review.json'])
        invoke(job,'analyze_phase7_metrics.py',[])
        frozen=json.loads((root/'data/morpho_phase7_analysis_manifest.json').read_text(encoding='utf8'))
        for item in frozen['outputs']:
            if item['path'].endswith('.csv'):
                require(sha(job/item['path'])==item['sha256'],'Reproduced CSV mismatch')
                saved.append(item['path'])
        # Restore only the original accepted analysis manifest in the disposable
        # job for the CSV identity check; generated QA is retained under work.
        shutil.copyfile(job/'data/morpho_phase7_analysis_manifest.json',job/'work/reproduced_analysis_manifest.json')
        shutil.copyfile(root/'data/morpho_phase7_analysis_manifest.json',job/'data/morpho_phase7_analysis_manifest.json')
        for item in frozen['outputs']:
            if item['path'].endswith('.png'):
                shutil.copyfile(root/item['path'],job/item['path'])
        invoke(job,'reproduce_release_csv.py',['--output',str(job/'work/figures'),'--verify-figures'])
    else:
        commands=raw_commands()
        # Parse every command through its real argparse without performing IO.
        for script,*args in commands:
            module=runpy.run_path(str(job/'scripts'/script),run_name='release_cli_validation')
            old=sys.argv;sys.argv=[script,*args]
            try:
                module['parse_args']()
            finally:
                sys.argv=old
        save(job/'raw_commands.json',{'commands':commands,'argparse_status':'PASS','network':'offline-only or raw-snapshot flags'})
        invoke(job,*[commands[0][0],commands[0][1:]])
        if a.mode=='raw':
            invoke(job,commands[1][0],commands[1][1:])
        invoke(job,commands[2][0],commands[2][1:])
        require(sha(job/'work/bridge.csv')==sha(root/'data/drip_morpho_eligibility_bridge.csv'),'Bridge byte mismatch')
        if a.mode=='raw':
            invoke(job,commands[3][0],commands[3][1:])
        # A rebuilt physical SQLite has a new identity. Never bypass the frozen
        # DB gate: logical comparison and review precede any new metric lineage.
    for item in needed:
        require(sha(bundle/item['path'])==item['sha256'],'External input modified')
    verify_package(root)
    report={'status':'PASS','mode':a.mode,'external_inputs_verified':len(needed),
            'package_and_source_bundle_unchanged':True,'network_calls':0,
            'metric_csvs_reproduced':saved,
            'full_raw_build':'RUN' if a.mode=='raw' else 'NOT_RUN',
            'limitation':'No public source download/access test. Raw-preflight is not an end-to-end state rebuild. Rebuilt physical DB requires logical reconciliation before new metric identity.'}
    save(job/'route_qa.json',report)
    print(json.dumps(report))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
