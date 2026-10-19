"""Session and environment-dependent internal commands."""
from datetime import datetime
from pathlib import Path
import os
import re
import shutil
from .syntax import crt_split

NAMES=set('assoc break cls color date dpath ftype keys pause prompt start time title ver verify vol mklink'.split())
def execute(rt,name,arg):
    state=rt.state
    if name in ('break','keys','verify'):
        if arg.strip().lower() not in ('','on','off'):
            if name!='break':rt.write('An incorrect parameter was\r\nentered for the command.\r\n',2)
            return rt.result(1 if name=='verify' else 0,1 if name=='verify' else None)
        if arg:setattr(state,name,arg.strip().lower()=='on')
        elif name in ('verify','keys'):rt.write(name.upper()+' is '+('on' if getattr(state,name,False) else 'off')+'.\r\n')
        return rt.result(0,0 if name=='verify' else None)
    if name=='cls':
        if rt.console is not None:rt.console.call('clear')
        elif getattr(rt.streams.table[1],'isatty',lambda:False)():rt.write('\x1b[2J\x1b[H')
        else:rt.write('\x0c')
        return rt.result(0)
    if name=='title':
        from .console_title import update
        state.title=arg;update(rt,arg);return rt.result(0)
    if name=='prompt':
        if arg:state.env['PROMPT']=arg
        else:state.env.pop('PROMPT',None)
        return rt.result(0,0 if rt.batch_path and rt.batch_path.suffix.lower()=='.cmd' else None)
    if name=='color':
        if not arg:
            state.color=None
            if rt.console is not None:rt.console.call('color',7)
            return rt.result(0)
        if not re.fullmatch('[0-9a-fA-F]{1,2}',arg.strip()):return rt.result(1,1)
        value=int(arg,16)
        if value>>4==value&15:return rt.result(1,1)
        state.color=value
        if rt.console is not None:rt.console.call('color',value)
        return rt.result(0,0)
    if name=='pause':
        rt.write('Press any key to continue . . . ');rt.streams.table[0].read(1);return rt.result(0)
    if name in ('assoc','ftype'):
        table=getattr(state,name+'_table',{});setattr(state,name+'_table',table)
        if '=' in arg:
            key,value=arg.split('=',1)
            if value:table[key.lower()]=value
            else:table.pop(key.lower(),None)
            return rt.result(0,0)
        if arg:
            value=table.get(arg.lower())
            if value is None:
                rt.write(('File association not found for extension ' if name=='assoc' else 'File type not found or no open command associated with ')+arg+'\r\n',2)
                return rt.result(1,1)
            rt.write(arg+'='+value+'\r\n')
        else:
            for key in sorted(table):rt.write(key+'='+table[key]+'\r\n')
        return rt.result(0,0)
    if name in ('date','time'):
        now=getattr(state,'clock',None) or datetime.now()
        query=arg.strip().lower()=='/t'
        if not arg or query:
            if name=='date':rt.write(('' if query else 'The current date is: ')+now.strftime('%a %m/%d/%Y')+'\r\n')
            else:rt.write(('' if query else 'The current time is: ')+now.strftime('%H:%M:%S')+'\r\n')
            # The session clock is isolated; no system time mutation.
            return rt.result(0)
        try:
            if name=='date':
                parsed=None
                for fmt in ('%m/%d/%Y','%Y-%m-%d','%m-%d-%Y'):
                    try:parsed=datetime.strptime(arg.strip(),fmt);break
                    except ValueError:pass
                if parsed is None:raise ValueError()
                state.clock=now.replace(year=parsed.year,month=parsed.month,day=parsed.day)
            else:
                fields=arg.strip().split(':');hour=int(fields[0]);minute=int(fields[1]);second=float(fields[2]) if len(fields)>2 else 0
                state.clock=now.replace(hour=hour,minute=minute,second=int(second),microsecond=int((second%1)*1e6))
        except (ValueError,IndexError):
            rt.write('The system cannot accept the '+name+' entered.\r\n',2);return rt.result(1,1)
        return rt.result(0,0)
    if name=='ver':rt.write('\r\nPython CMD compatibility interpreter [0.2.0]\r\n');return rt.result(0,0)
    if name=='vol':
        if arg and not re.fullmatch(r'[a-zA-Z]:?',arg.strip()):
            rt.write('The filename, directory name, or volume label syntax is incorrect.\r\n',2);return rt.result(1,1)
        rt.write(' Volume in drive '+str(state.cwd.anchor or '/')+' has no label.\r\n');return rt.result(0)
    if name=='dpath':
        if arg==';':state.env.pop('DPATH',None)
        elif arg:state.env['DPATH']=arg
        else:rt.write('DPATH='+state.env.get('DPATH','(null)')+'\r\n')
        return rt.result(0,0 if getattr(rt,'cmd_semantics',False) else None)
    if name=='mklink':
        args=crt_split(arg);option=''
        if args and args[0].startswith('/'):option=args.pop(0).upper()
        if len(args)!=2 or option not in ('','/H','/D','/J'):return rt.result(1,1)
        link,target=map(rt.path,args)
        try:
            if option=='/H':os.link(target,link)
            else:os.symlink(target,link,target_is_directory=option in ('/D','/J'))
        except OSError as exc:rt.write(str(exc)+'\r\n',2);return rt.result(1,1)
        rt.write(('Hardlink' if option=='/H' else 'symbolic link')+' created for '+args[0]+' <<===>> '+args[1]+'\r\n')
        return rt.result(0,0)
    if name=='start':return start(rt,arg)
    raise AssertionError(name)

def start(rt,arg):
    rest=arg.lstrip();wait=False;initial=False;cwd=rt.state.cwd;title=False
    while rest:
        if rest.startswith('"') and not title:
            end=rest.find('"',1)
            if end<0:return rt.result(1,1)
            rt.state.title=rest[1:end];rest=rest[end+1:].lstrip();title=True;continue
        if not rest.startswith('/'):break
        match=re.match(r'([^\s]+)(?:\s+|$)',rest);option=match[1].lower();rest=rest[match.end():]
        if option in ('/b','/min','/max','/low','/normal','/high','/realtime','/abovenormal','/belownormal'):continue
        if option=='/i':initial=True;continue
        if option=='/wait':wait=True;continue
        if option in ('/d','/affinity','/node'):
            m=re.match(r'("[^"]*"|\S+)\s*',rest)
            if not m:return rt.result(1,1)
            if option=='/d':cwd=rt.path(m[1].strip('"'))
            rest=rest[m.end():];continue
        rt.write('Invalid switch - '+option+'\r\n',2);return rt.result(1,1)
    if not rest:return rt.result(0)
    child=rt.fork(stdin=rt.streams.table[0],stdout=rt.streams.table[1],stderr=rt.streams.table[2]);child.state.cwd=cwd
    if initial:child.state.env=rt.startup_env.copy()
    if wait:
        try:code=child.command(rest)
        finally:child.streams.close_owned()
        rt.state.unsupported.extend(child.state.unsupported)
        return rt.result(code,code)
    # Native streams can be inherited by a separate Python interpreter that outlives us.
    try:
        for fd in (0,1,2):rt.streams.table[fd].fileno()
    except (AttributeError,OSError):
        from threading import Thread
        def run_child():
            try:child.command(rest)
            except KeyboardInterrupt:
                # Runtime already captured the BAT traceback if requested.
                # Closing the GUI is also a normal cancellation of its jobs.
                pass
            finally:child.streams.close_owned()
        job=Thread(target=run_child,name='pycmd-start')
        job.start();rt.jobs.append(job)
    else:
        import subprocess,sys
        host=str(Path(__file__).with_name('_start_host.py'))
        arguments=[sys.executable,host,rest]
        if child.diagnostics.enabled or child.xp or child.terminal_unicode or hasattr(child.state,'codepage'):
            import json
            arguments.append(json.dumps(child.diagnostics.parents if child.diagnostics.enabled else None))
            arguments.append(json.dumps({'xp':child.xp,'terminal_unicode':child.terminal_unicode,'codepage':getattr(child.state,'codepage',None)}))
        job=subprocess.Popen(arguments,cwd=cwd,env=dict(child.state.env),
                             stdin=rt.streams.table[0],stdout=rt.streams.table[1],stderr=rt.streams.table[2])
        rt.jobs.append(job)
    return rt.result(0,0)
