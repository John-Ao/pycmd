import argparse
import os
import sys
from .runtime import Runtime

def main():
    parser=argparse.ArgumentParser(description='Python CMD core (unsupported features return 125)')
    group=parser.add_mutually_exclusive_group()
    group.add_argument('-c','--command');group.add_argument('--batch')
    parser.add_argument('--traceback',action='store_true',help='Show BAT call stacks and source locations on errors')
    parser.add_argument('--gui',action='store_true',help='Run in a Tk console with an independent image overlay')
    parser.add_argument('--fontsize',type=int,default=16,help='GUI font size in logical pixels at 96 DPI (1-128; default: 16)')
    parser.add_argument('--xp',action='store_true',help='Use legacy Chinese double-column display for CP936 ambiguous characters')
    parser.add_argument('--codepage',type=int,help='Initial BAT/data code page (POSIX default: 65001; use 936 for GBK files)')
    parser.add_argument('--delayed',action='store_true')
    parser.add_argument('--no-extensions',action='store_true')
    parser.add_argument('--allow-external',action='store_true')
    parser.add_argument('--max-steps',type=int);parser.add_argument('--timeout',type=float)
    parser.add_argument('--cwd');parser.add_argument('args',nargs='*')
    args=parser.parse_args()
    if not 1<=args.fontsize<=128:parser.error('--fontsize must be between 1 and 128')
    codepage=args.codepage if args.codepage is not None else (65001 if os.name!='nt' else None)
    if codepage is not None:
        import codecs
        try:codecs.lookup('utf-8' if codepage==65001 else 'cp'+str(codepage))
        except LookupError:parser.error('Unknown code page: '+str(codepage))
    kwargs=dict(env=os.environ,cwd=args.cwd,
        extensions=not args.no_extensions,delayed=args.delayed,allow_external=args.allow_external,max_steps=args.max_steps,process_timeout=args.timeout,traceback=args.traceback,xp=args.xp,codepage=codepage,terminal_unicode=os.name!='nt')
    if args.gui:
        try:
            from .gui import run_gui
            code=run_gui(args,kwargs)
        except (ImportError,RuntimeError) as exc:
            print('pycmd GUI: install Tk and pycmd-compat[gui]: '+str(exc),file=sys.stderr);return 1
        except Exception as exc:
            print('pycmd GUI: '+str(exc),file=sys.stderr);return 1
        return code&0xffffffff if os.name=='nt' else code&255
    runtime=Runtime(stdin=sys.stdin.buffer,stdout=sys.stdout.buffer,stderr=sys.stderr.buffer,**kwargs)
    interrupted=False
    try:
        code=runtime.batch(args.batch,args.args) if args.batch else runtime.entry(args.command) if args.command is not None else runtime.interactive()
    except KeyboardInterrupt as exc:
        runtime.diagnostics.interrupted(exc)
        interrupted=True;code=0xc000013a
    finally:runtime.streams.close_owned()
    return 125 if runtime.state.unsupported and not interrupted else (code&0xffffffff if os.name=='nt' else code&255)
if __name__=='__main__':sys.exit(main())
