"""Replay frozen, reviewed observations; never modify or synthesize native expectations."""
import argparse
import io
import json
from pathlib import Path
import tempfile
import sys
from .runtime import Runtime

ROOT=Path(__file__).resolve().parents[1]
SMOKE={'exp_block','exp_nested','exp_endlocal_export','exp_insert_amp_percent','exp_insert_amp_bang',
       'exp_insert_redirect_percent','exp_insert_redirect_bang','exp_insert_percent_percent',
       'exp_insert_percent_bang','exp_insert_bang_percent','exp_insert_bang_bang',
       'redir_order_0','redir_order_1','redir_order_2','redir_order_3','redir_order_4','redir_order_5',
       'redir_restore','batch_chain_call','batch_chain_direct','args_shift','args_separators','for_basic','for_nested',
       'bytes_crlf','bytes_lf','bytes_no_final_newline','bytes_ctrl_z','bytes_nul','echo_0','echo_1','echo_2','echo_3','echo_4'}
def encoded(spec):
    if 'hex' in spec:return bytes.fromhex(spec['hex'])
    text=spec.get('text','')
    if spec.get('crlf',True):text=text.replace('\r\n','\n').replace('\n','\r\n')
    return text.encode(spec.get('encoding','ascii'))
def snapshot(path):
    import hashlib
    from .attributes import get
    return {str(p.relative_to(path)).replace('\\','/'):({'kind':'file','size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'attributes':get(p)}
            if p.is_file() else {'kind':'directory'})
            for p in path.rglob('*')}
def project_snapshot(value):
    if not value:return None
    return {k:v for k,v in value.items() if k in ('kind','size','sha256','attributes')}
def _run_case(case,profile,expected,fixture):
    with tempfile.TemporaryDirectory(prefix='pycmd-replay-') as tmp:
        work=Path(tmp)
        for name,spec in case.get('files',{}).items():
            p=work/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(encoded(spec))
        (work/'probe.py').write_bytes((fixture/'probe.py').read_bytes())
        mode=case['mode'];name=case.get('batch_name','case.bat')
        if mode=='batch':(work/name).write_bytes(encoded(case['script']))
        before=snapshot(work);out=io.BytesIO();err=io.BytesIO()
        env={'PYTHON':sys.executable,'COMSPEC':'cmd.exe','PROMPT':'VALIDATOR$G','COPYCMD':'/Y','PYTHONIOENCODING':'utf-8','PYTHONUTF8':'1',**case.get('env',{})}
        runtime=Runtime(env=env,cwd=work,stdin=io.BytesIO(encoded(case.get('stdin',{'text':''}))),stdout=out,stderr=err,
                        extensions=profile[1]=='1',delayed=profile[3]=='1',max_steps=10000,allow_external=True,python_adapter=True,process_timeout=15)
        if '/u' in case.get('flags',[]):runtime.state.unicode_output=True
        if '/a' in case.get('flags',[]):runtime.state.unicode_output=False
        # Actual external probes run through the explicit portable Python process adapter.
        if mode=='batch':
            from .syntax import batch_split
            code=runtime.batch(work/name,batch_split(case.get('args','')),raw_args=case.get('args',''),argv0=name)
        elif mode=='command':code=runtime.entry(case['command'],case.get('flags',[]))
        else:
            code=runtime.interactive()
        code&=0xffffffff
        runtime.streams.close_owned()
        after=snapshot(work)
        differences=[]
        for stream,value in [('stdout',out.getvalue()),('stderr',err.getvalue())]:
            wanted=bytes.fromhex(expected['streams'][stream]['hex'])
            if value!=wanted:differences.append({'field':stream,'expected_hex':wanted.hex(),'actual_hex':value.hex()})
        if code!=expected['returncode']:differences.append({'field':'returncode','expected':expected['returncode'],'actual':code})
        changes={p:after.get(p) for p in before.keys()|after.keys() if before.get(p)!=after.get(p)}
        native={p:project_snapshot(v.get('after')) for p,v in expected['file_changes'].items()
                if project_snapshot(v.get('before'))!=project_snapshot(v.get('after'))}
        if changes!=native:differences.append({'field':'file_contents','expected':native,'actual':changes})
        return {'id':case['id'],'profile':profile,'status':'unsupported' if runtime.state.unsupported else 'mismatch' if differences else 'pass',
                'unsupported':runtime.state.unsupported,'differences':differences,
                'comparison_scope':'Exact stdout/stderr, returncode, file bytes, DOS attributes and directory presence; timestamps not compared'}
def run_case(case,profile,expected,fixture):
    try:return _run_case(case,profile,expected,fixture)
    except Exception:
        import traceback
        return {'id':case['id'],'profile':profile,'status':'internal_error',
                'unsupported':[],'differences':[], 'traceback':traceback.format_exc()}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=ROOT/'tests', help='Directory containing public fixtures and expected observations')
    parser.add_argument('--round',default='round1');parser.add_argument('--filter');parser.add_argument('--all',action='store_true')
    parser.add_argument('--output',type=Path,default=Path('tests/replay-core-round1.json'))
    parser.add_argument('--jobs',type=int,default=1,help='Independent fixture workers')
    args=parser.parse_args()
    if not (args.data_dir/'expected').is_dir():
        parser.error('Public test data is required; run from the source checkout or pass --data-dir')
    rounds=[p.stem for p in (args.data_dir/'expected').glob('round*.json')] if args.round=='all' else [args.round]
    rounds.sort(key=lambda s:int(''.join(c for c in s if c.isdigit())))
    tasks=[]
    for round_ in rounds:
        fixture=args.data_dir/'fixtures'/round_
        cases={c['id']:c for c in json.loads((fixture/'cases.json').read_text())['cases']}
        expected=json.loads((args.data_dir/'expected'/(round_+'.json')).read_text())['observations']
        selected=[e for e in expected if args.all or (args.filter in e['id'] if args.filter else e['id'] in SMOKE)]
        tasks.extend((round_,cases[e['id']],e,fixture) for e in selected)
    if not tasks:parser.error('No reviewed observations selected')
    def replay(task):
        round_,case,e,fixture=task
        return {'round':round_,**run_case(case,e['profile'],e,fixture)}
    if args.jobs>1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:rows=list(pool.map(replay,tasks))
    else:rows=[replay(task) for task in tasks]
    counts={s:sum(r['status']==s for r in rows) for s in ['pass','mismatch','unsupported','internal_error']}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps({'round':args.round,'counts':counts,'observations':rows},indent=2)+'\n')
    print(json.dumps(counts));print(args.output)
    return 0 if not counts['mismatch'] and not counts['unsupported'] and not counts['internal_error'] else 1
if __name__=='__main__':raise SystemExit(main())
