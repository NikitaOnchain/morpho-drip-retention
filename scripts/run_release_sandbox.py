"""Run one package script with Python audit-hook IO/network guards.

This is an accidental-dependency test, not an OS-level hostile-code sandbox.
Only explicit package/output/bundle roots, Python runtime and system fonts can
be opened. CSV mode additionally rejects SQLite connections.
"""
import argparse
import json
import os
import runpy
import sys
from pathlib import Path
from release_support import save


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--allow',type=Path,action='append',default=[])
    p.add_argument('--receipt',type=Path,required=True)
    p.add_argument('--no-database',action='store_true')
    p.add_argument('script')
    p.add_argument('args',nargs=argparse.REMAINDER)
    a=p.parse_args()
    root=Path(__file__).resolve().parents[1]
    allowed=[root,Path(sys.prefix).resolve(),Path(sys.base_prefix).resolve(),*map(lambda x:x.resolve(),a.allow)]
    if os.environ.get('WINDIR'):
        allowed.append((Path(os.environ['WINDIR'])/'Fonts').resolve())
    if os.environ.get('MORPHO_FONT_DIR'):
        allowed.append(Path(os.environ['MORPHO_FONT_DIR']).resolve())
    counts={'file_opens':0,'sqlite_connections':0,'network_attempts':0,'forbidden_paths':0}
    def audit(event,args):
        if event in ('socket.connect','socket.connect_ex','socket.getaddrinfo','socket.bind'):
            counts['network_attempts']+=1
            raise RuntimeError('Network disabled during release test')
        if event=='sqlite3.connect':
            counts['sqlite_connections']+=1
            if a.no_database:
                raise RuntimeError('CSV-only route attempted a database read')
        if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
            path=Path(os.fsdecode(args[0])).resolve()
            counts['file_opens']+=1
            if not any(path==r or path.is_relative_to(r) for r in allowed):
                counts['forbidden_paths']+=1
                raise RuntimeError('Read/write outside declared package, bundle, output or runtime roots')
    sys.addaudithook(audit)
    sys.argv=[a.script,*a.args]
    exit_code=0
    try:
        runpy.run_path(str(root/a.script),run_name='__main__')
    except SystemExit as exc:
        exit_code=exc.code or 0
    except Exception:
        exit_code=1
        import traceback
        traceback.print_exc()
    save(a.receipt,{'status':'PASS' if exit_code==0 else 'FAIL','exit_code':exit_code,
                    'scope':'Python audit-hook accidental-dependency guard, not OS-level security isolation',
                    'script':a.script,'checks':counts,'original_workspace_not_an_allowed_root':True})
    return exit_code


if __name__=='__main__':
    raise SystemExit(main())
