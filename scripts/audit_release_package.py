"""Audit actual staging contents; never resolve links against the workspace."""
import argparse
import ast
import csv
import json
import re
from pathlib import Path
from urllib.parse import unquote
from release_support import sha, save, require, verify_package


def audit(root):
    files=sorted(p for p in root.rglob('*') if p.is_file())
    broken=[];private=[];secrets=[];syntax=[];large=[];links=0;forbidden=[]
    for p in files:
        rel=p.relative_to(root).as_posix()
        if any(part in ('raw','tmp','__pycache__','.git') for part in p.relative_to(root).parts) or p.suffix in ('.sqlite','.db','.pem','.key','.part') or p.name.startswith('.env'):
            forbidden.append(rel)
        if p.stat().st_size>5*1024**2:large.append(rel)
        if p.suffix.lower() not in ('.md','.py','.json','.csv','.sql','.ps1','.cjs','.txt'):continue
        s=p.read_text(encoding='utf-8-sig')
        for i,line in enumerate(s.splitlines(),1):
            if re.search(r'[A-Za-z]:[\\/](?:Users|web3|Windows)|/(?:Users|home)/[A-Za-z0-9_]',line):
                private.append({'path':rel,'line':i})
            if re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|://[^\s/:]+:[^\s/@]+@',line):
                secrets.append({'path':rel,'line':i})
        try:
            if p.suffix=='.py':ast.parse(s)
            if p.suffix=='.json':json.loads(s)
            if p.suffix=='.csv':
                parsed=list(csv.reader(s.splitlines()))
                require(not parsed or all(len(r)==len(parsed[0]) for r in parsed),'CSV width')
        except Exception as e:syntax.append({'path':rel,'error':type(e).__name__})
        if p.suffix=='.md':
            s=re.sub(r'```[\s\S]*?```','',s)
            for match in re.finditer(r'!?\[[^\]]*\]\(([^)]+)\)',s):
                target=match.group(1).strip().strip('<>')
                if re.match(r'^[a-z]+:',target) or target.startswith('#'):continue
                target=unquote(target.split('#')[0])
                if not target:continue
                links+=1
                resolved=(p.parent/target).resolve()
                if not resolved.is_relative_to(root) or not resolved.exists():broken.append({'path':rel,'target':target})
    old=json.loads((root/'release/review_link_cases.json').read_text(encoding='utf8'))
    cases=[{'path':i['file'],'original_line':i['line'],'target':i['target'],
            'target_now_in_package':(root/i['file']).parent.joinpath(i['target']).resolve().is_file()} for i in old]
    require(len(cases)==16,'Review link test count changed')
    return {'status':'PASS' if not any((broken,private,secrets,syntax,large,forbidden)) and all(c['target_now_in_package'] for c in cases) else 'FAIL',
            'files':len(files),'bytes':sum(p.stat().st_size for p in files),'local_links_checked':links,
            'broken_links':broken,'review_link_cases':cases,'absolute_path_hits':private,
            'high_signal_secret_hits':secrets,'syntax_errors':syntax,'large_files':large,'forbidden_payloads':forbidden,
            'limitations':['Heuristic secrets only; no dedicated scanner or Git history audit.','External URLs and renderer-specific anchors not checked.','No browser/GitHub renderer or cross-OS font certification.']}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seal',action='store_true')
    a=p.parse_args();root=Path(__file__).resolve().parents[1];result=audit(root)
    if a.seal:
        require(result['status']=='PASS','Package audit failed: '+json.dumps(result))
        save(root/'release/package_audit.json',result)
        files=[{'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(root.rglob('*')) if p.is_file() and p.relative_to(root).as_posix() not in {'release/manifest.json','release/SHA256SUMS.txt'}]
        save(root/'release/manifest.json',{'version':'phase8-revised-rc2','status':'CURRENT — revised release candidate awaiting re-review',
             'self_reference_rule':'manifest excludes itself and SHA256SUMS; SHA256SUMS additionally covers manifest; no other payload omitted','files':files})
        lines=[i['sha256']+'  '+i['path'] for i in files]+[sha(root/'release/manifest.json')+'  release/manifest.json']
        (root/'release/SHA256SUMS.txt').write_text('\n'.join(lines)+'\n',encoding='utf8',newline='\n')
    else:
        manifest=verify_package(root)
        expected={i['path'] for i in manifest['files']}|{'release/manifest.json','release/SHA256SUMS.txt'}
        require({p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}==expected,'Unmanifested or missing package contents')
        for line in (root/'release/SHA256SUMS.txt').read_text(encoding='utf8').splitlines():
            checksum,path=line.split('  ',1);require(sha(root/path)==checksum,'SHA256SUMS mismatch: '+path)
    print(json.dumps(result))
    return 0 if result['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
