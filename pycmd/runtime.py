"""Incremental CMD core. Unsupported features remain observable, never silent successes."""
import os
import io
from pathlib import Path
import re
import shutil
import subprocess
from .state import State, Environment, signed32
from .syntax import parse, unescape, crt_split, batch_split, Unsupported, SyntaxFailure, SilentSyntaxFailure, ParseFailure
from .expansion import percent, execution
from .io import Streams, extract, HandleCopyError
from .readers import batch_line

BUILTINS=set('assoc break call cd chdir cls color copy date del dir dpath echo endlocal erase exit for ftype goto if keys md mkdir mklink move path pause popd prompt pushd rd rem ren rename rmdir set setlocal shift start time title type ver verify vol'.split())
BUILTINS.add('cmos')
BUILTINS.add('mode')
BUILTINS.add('ping')
BUILTINS.add('image')
class ExitFlow(Exception):
    def __init__(self,code,session=False):self.code=code;self.session=session
class GotoFlow(Exception):
    def __init__(self,label):self.label=label

class Runtime:
    def __init__(self,env=None,cwd=None,stdin=None,stdout=None,stderr=None,extensions=True,delayed=False,allow_external=False,max_steps=None,python_adapter=False,process_timeout=None,autorun=None,traceback=False,xp=False,codepage=None,terminal_unicode=False):
        from .diagnostics import Diagnostics
        self.diagnostics=Diagnostics(self,traceback)
        self.console=None
        self.xp=xp
        self.terminal_unicode=terminal_unicode
        self.trace_command=""
        self.state=State(env=Environment(env),cwd=Path(cwd or Path.cwd()).resolve(),extensions=extensions,delayed=delayed)
        if codepage is not None:
            import codecs
            encoding='utf-8' if codepage==65001 else 'cp'+str(codepage)
            codecs.lookup(encoding);self.state.encoding=encoding;self.state.codepage=codepage
        self.streams=Streams(stdin,stdout,stderr);self.allow_external=allow_external
        if xp or terminal_unicode:
            from .xp_terminal import attach
            attach(self)
        if terminal_unicode and os.name!='nt':
            from .terminal_input import TerminalInput
            if isinstance(self.streams.table[0],TerminalInput):self.streams.table[0].host_encoding='utf-8'
        self.python_adapter=python_adapter;self.process_timeout=process_timeout;self.autorun=autorun
        self.max_steps=max_steps;self.steps=0;self.batch_path=None;self.transfer=None;self.session_exited=False
        self.null_path=Path(os.devnull);self.batch_frames=[];self.startup_env=self.state.env.copy();self.jobs=[];self.drive_dirs={self.state.cwd.drive.upper():self.state.cwd} if self.state.cwd.drive else {}
    def fork(self,stdin=None,stdout=None,stderr=None):
        child=Runtime(env=dict(self.state.env),cwd=self.state.cwd,stdin=stdin,stdout=stdout,stderr=stderr,
                      extensions=self.state.extensions,delayed=self.state.delayed,allow_external=self.allow_external,
                      max_steps=max(1,self.max_steps-self.steps) if self.max_steps is not None else None,python_adapter=self.python_adapter,process_timeout=self.process_timeout,autorun=self.autorun,traceback=self.diagnostics.enabled,xp=self.xp,codepage=getattr(self.state,'codepage',None),terminal_unicode=self.terminal_unicode)
        child.diagnostics.parents=self.diagnostics.stack()
        child.console=self.console
        child.diagnostics.counter=self.diagnostics.counter
        child.drive_dirs=self.drive_dirs.copy()
        for key in ('assoc_table','ftype_table','clock','title','color','verify','break','keys'):
            if hasattr(self.state,key):
                value=getattr(self.state,key)
                setattr(child.state,key,value.copy() if isinstance(value,dict) else value)
        child.startup_env=child.state.env.copy()
        child.state.encoding=self.state.encoding;child.state.unicode_output=self.state.unicode_output
        return child
    def path(self,name):
        if os.name=='nt' and len(name)>=2 and name[1]==':' and (len(name)==2 or name[2] not in '/\\'):
            return self.drive_dirs.get(name[:2].upper(),Path(name[:2]+'\\'))/name[2:]
        if os.name!='nt':name=name.replace('\\','/')
        if name.rsplit('/',1)[-1].split('.')[0].rstrip(' :').upper()=='NUL':return Path(os.devnull)
        if os.name!='nt':name='/'.join(part if part in ('.','..') or any(c in part for c in '*?') else part.rstrip(' .') for part in name.split('/'))
        p=Path(name);p=p if p.is_absolute() else self.state.cwd/p
        if os.name=='nt' or p.exists():return p
        current=Path(p.anchor)
        for part in p.parts[1:]:
            if current.is_dir():
                found=next((x.name for x in current.iterdir() if x.name.casefold()==part.casefold()),part)
            else:found=part
            current=current/found
        return current
    def read_path(self,name):
        path=self.path(name)
        if path.exists() or any(ch in name for ch in '/\\'):return path
        for directory in self.state.env.get('DPATH','').split(';'):
            if directory:
                candidate=self.path(directory)/name
                if candidate.exists():return candidate
        return path
    def lookup(self,name):
        explicit=any(ch in name for ch in '/\\:')
        pathlist=self.state.env.get('PATH','')
        delimiter=';' if ';' in pathlist or os.name=='nt' else os.pathsep
        directories=[''] if explicit else ['']+pathlist.split(delimiter)
        extensions=[''] if Path(name).suffix else ['']+((self.state.env.get('PATHEXT') or '.COM;.EXE;.BAT;.CMD') if self.state.extensions else '.COM;.EXE;.BAT;.CMD').split(';')
        for directory in directories:
            for ext in extensions:
                path=self.path((directory.strip('"')+'/' if directory else '')+name+ext)
                if path.is_file():return path
        return None
    def echo(self,text):self.write((text+'\r\n')[:8191])
    def write(self,text,fd=1):
        stream=self.streams.table[fd]
        if hasattr(stream,'write_text'):stream.write_text(text)
        else:self.streams.write(fd,text.encode('utf-16le' if self.state.unicode_output else self.state.encoding,errors='replace'))
        if fd==2 and text.strip():self.diagnostics.emit(text)
    def expand_execution(self,text):return execution(text,self.state)
    def result(self,code,saved=None):
        self.state.command_result=code;self.state.process_code=code
        if saved is not None:self.state.errorlevel=signed32(saved)
        return code
    def unsupported(self,exc):
        reason=str(exc);self.state.unsupported.append(reason)
        self.write('pycmd: unsupported: '+reason+'\r\n',2);return self.result(125)
    def interactive(self,banner=True):
        from .echoing import prompt
        if banner:self.dispatch('ver')
        code=0
        while True:
            if self.state.echo:self.write(prompt(self.state))
            raw=self.streams.table[0].readline()
            if not raw:break
            text=raw.decode(getattr(self.streams.table[0],'host_encoding',self.state.encoding),errors='replace').rstrip('\r\n')
            self.trace_command=text
            while True:
                try:parse(text);break
                except SyntaxFailure as exc:
                    if str(exc)!='Unclosed parenthesis':break
                    self.write('More? ');raw=self.streams.table[0].readline()
                    if not raw:
                        self.diagnostics.emit('Unclosed parenthesis');return self.result(1)
                    text+='\n'+raw.decode(getattr(self.streams.table[0],'host_encoding',self.state.encoding),errors='replace').rstrip('\r\n')
            try:code=self.execute(parse(percent(text,self.state,False)))
            except ExitFlow as exc:
                self.session_exited=exc.session
                return self.result(exc.code,exc.code)
            except Unsupported as exc:code=self.unsupported(exc)
            except SyntaxFailure as exc:self.write(str(exc)+'\r\n',2);code=self.result(1)
        return code
    def entry(self,text,flags=()):
        self.state.command_line=self.state.env.get('COMSPEC','cmd.exe')+' '+(' '.join(flags)+' ' if flags else '')+'/c '+text
        self.trace_command=text
        lower=[f.lower() for f in flags]
        overhead=len(self.state.env.get('COMSPEC','cmd.exe'))+len(' /d /c ')+sum(len(f)+1 for f in flags)
        if len(text)+overhead>8191:
            self.write('The command line is too long.\r\n',2);return self.result(1)
        if '/u' in lower:self.state.unicode_output=True
        if '/a' in lower:self.state.unicode_output=False
        if '/q' in lower:self.state.echo=False
        text=text.lstrip()
        if text.startswith('"'):
            end=text.rfind('"')
            enclosed=text[1:end]
            preserve=('/s' not in lower and text.count('"')==2 and any(c.isspace() for c in enclosed)
                      and not any(c in enclosed for c in '&<>()@^|') and self.lookup(enclosed) is not None)
            if not preserve:text=text[1:end]+text[end+1:] if end>0 else text[1:]
        return self.command(text)
    def command(self,text,batch=False):
        self.trace_command=text
        try:
            code=self.execute(parse(percent(text,self.state,batch)))
            if self.transfer:
                path,args=self.transfer;self.transfer=None;code=self.batch(path,args)
            return code
        except Unsupported as exc:return self.unsupported(exc)
        except SilentSyntaxFailure as exc:
            self.diagnostics.emit(str(exc));return self.result(1)
        except ParseFailure as exc:
            self.write(str(exc)+'\r\n',2);return self.result(1)
        except SyntaxFailure as exc:
            if str(exc)=='Unclosed parenthesis':self.diagnostics.emit(str(exc));return self.result(1)
            self.write(str(exc)+'\r\n',2);return self.result(255)
        except ExitFlow as exc:
            self.session_exited=exc.session
            return self.result(exc.code,exc.code)
        except GotoFlow:return self.unsupported(Unsupported('GOTO outside batch'))
    def _drive(self,operation):
        from .execution import drive
        return drive(operation,self.diagnostics.interrupted)
    def execute(self,node):
        return self._drive(self._gen_execute(node))
    def _gen_execute(self,node):
        with self.diagnostics.executing(node):
            serial=self.diagnostics.counter[0]
            self.data_exit_status=False
            code=(yield self._execute_node(node))
            if code and not self.data_exit_status and serial==self.diagnostics.counter[0] and node.kind=='command':
                self.diagnostics.emit('Command returned exit status '+str(code))
            return code
    def _execute(self,node):
        return self._drive(self._execute_node(node))
    def _execute_node(self,node):
        if self.console is not None:self.console.check_interrupt()
        self.steps+=1
        if self.max_steps is not None and self.steps>self.max_steps:raise Unsupported('Execution step budget exhausted')
        if node.kind=='quiet':
            old=getattr(self,'suppress_echo',False);self.suppress_echo=True
            try:return (yield self._gen_execute(node.children[0]))
            finally:self.suppress_echo=old
        if node.kind=='empty':
            self.data_exit_status=True
            return self.state.command_result
        if node.kind=='pipe':
            from .pipeline import run
            return run(self,node)
        if node.kind in ('sequence','and','or'):
            code=self.state.command_result
            for i,child in enumerate(node.children):
                if i and node.kind=='and' and code!=0:break
                if i and node.kind=='or' and code==0:break
                code=(yield self._gen_execute(child))
            return code
        if node.kind=='block':
            _,redirs=extract(node.text)
            try:
                with self.streams.redirected(redirs,self):return (yield self._gen_execute(node.children[0]))
            except HandleCopyError as exc:
                self.write('The handle could not be duplicated\r\nduring redirection of handle '+str(exc.target)+'.\r\n',2);return self.result(1)
            except OSError:
                self.write(self.redirection_error(redirs)+'\r\n',2);return self.result(1)
        return (yield self._gen_simple(node.text))
    def redirection_error(self,redirs):
        for redir in redirs:
            if redir.mode=='<':
                path=self.read_path(unescape(self.expand_execution(redir.source)).replace('"',''))
                if path.parent.is_dir() and not path.exists():return 'The system cannot find the file specified.'
        return 'The system cannot find the path specified.'
    def simple(self,text):
        return self._drive(self._gen_simple(text))
    def _gen_simple(self,text):
        raw=text.lstrip(' \t\r,;=')
        if raw.startswith('@'):raw=raw[1:].lstrip(' \t')
        if not raw or raw.startswith(':'):return self.result(0)
        # Control commands own the grammar of their tail, including body redirections.
        match=re.match(r'([a-z]+)(.*)',raw,re.I|re.S)
        name=match[1].lower() if match else ''
        tail=match[2] if match else ''
        if name in BUILTINS and tail.strip()=='/?':
            from .help import display
            return display(self,name)
        if name in ('if','for','call','rem') and (not tail or tail[0].isspace() or name=='rem' or name=='call' and tail.startswith(':')):
            if name=='rem':return self.result(0)
            if name=='call':
                clean,redirs=extract(tail)
                try:
                    with self.streams.redirected(redirs,self):return (yield self._gen_do_call(clean))
                except HandleCopyError as exc:
                    self.write('The handle could not be duplicated\r\nduring redirection of handle '+str(exc.target)+'.\r\n',2);return self.result(1)
                except OSError:
                    self.write(self.redirection_error(redirs)+'\r\n',2);return self.result(1)
            return (yield getattr(self,'_gen_do_'+name)(tail))
        command,redirs=extract(raw)
        if re.match(r'(?:@?rem(?:\s|$)|:)',command.lstrip(),re.I):return self.result(0)
        try:
            with self.streams.redirected(redirs,self):return (yield self._gen_dispatch(self.expand_execution(unescape(command))))
        except HandleCopyError as exc:
            self.write('The handle could not be duplicated\r\nduring redirection of handle '+str(exc.target)+'.\r\n',2);return self.result(1)
        except OSError:
            self.write(self.redirection_error(redirs)+'\r\n',2);return self.result(1)
    def dispatch(self,text):
        return self._drive(self._gen_dispatch(text))
    def _gen_dispatch(self,text):
        text=text.lstrip(' \t,;=')
        match=re.match(r'([^\s]+)(.*)',text,re.S)
        if not match:return self.result(0)
        token,tail=match.groups();name=token.lower();arg=tail.lstrip(' \t')
        if name in ('timeout','timeout.exe'):
            from .timeout_command import execute
            return execute(self,arg)
        if name in ('choice','choice.exe','xcopy','xcopy.exe'):
            from .console_tools import execute
            return execute(self,name.split('.')[0],arg)
        if name in ('image','image.exe'):
            from .image_command import execute
            return execute(self,arg)
        ping=re.fullmatch(r'ping(?:\.exe)?(/.*)?',token,re.I)
        if ping:
            from .ping_delay import execute
            return execute(self,(ping[1] or '')+tail)
        if name=='mode':
            from .console_mode import execute
            return execute(self,arg)
        if name=='cmos':
            from .cmos import execute
            return execute(self,arg)
        if name.startswith('set/'):
            return self.do_set(token[3:]+tail)
        if name.startswith('goto:'):return (yield self._gen_dispatch('goto '+token[5:]+tail))
        if name.startswith('exit/'):return (yield self._gen_dispatch('exit '+token[4:]+tail))
        if name.startswith(('cd.','cd\\','cd/')) and not name.startswith('cd.exe'):
            return self.directory('cd',token[2:]+tail)
        if name in BUILTINS and arg.strip()=='/?':
            from .help import display
            return display(self,name)
        # ECHO punctuation is consumed by the command, not stripped globally.
        if name.startswith('echo') and len(name)>4 and name[4] in '.(:/;=,' and not (name=='echo.' and self.path('echo').is_file()) and not (name[4]=='.' and name!='echo.' and self.path(token).is_file()):
            self.echo(token[5:]+tail);return self.result(0)
        if name=='echo':
            if arg.strip().lower() in ('on','off'):self.state.echo=arg.strip().lower()=='on'
            elif not arg:self.write('ECHO is '+('on' if self.state.echo else 'off')+'.\r\n')
            else:self.echo(arg)
            return self.result(0)
        if re.fullmatch(r'[a-z]:',name):
            target=self.drive_dirs.get(name.upper(),Path(name+'\\'))
            if not target.is_dir():self.write('The system cannot find the drive specified.\r\n',2);return self.result(1,1)
            self.state.cwd=target;return self.result(0)
        if name=='set':return self.do_set(arg)
        if name=='setlocal':
            if not self.batch_path:return self.result(0)
            self.state.begin_local()
            for option in arg.lower().split():
                if option not in ('enableextensions','disableextensions','enabledelayedexpansion','disabledelayedexpansion'):
                    self.write('Invalid parameter to SETLOCAL command\r\n',2);return self.result(1,1)
                if option.endswith('extensions'):self.state.extensions=option.startswith('enable')
                else:self.state.delayed=option.startswith('enable')
            return self.result(0,0)
        if name=='endlocal':self.state.end_local();return self.result(0)
        if name=='exit':
            parts=arg.split();local=bool(parts and parts[0].lower()=='/b')
            if local:parts=parts[1:]
            code=0 if local and len(self.batch_frames)==1 else self.state.errorlevel
            if parts:
                m=re.match(r'[+-]?\d+',parts[0]);code=signed32(int(m[0])) if m else 0
            self.state.errorlevel=code
            if local and not self.state.extensions and self.batch_path and self.find_label(self.batch_path,'EOF',0) is None:
                self.write('The system cannot find the batch label specified - EOF\r\n',2)
            # Explicit return/exit status is control flow, not a new failure.
            self.data_exit_status=True
            raise ExitFlow(code,not local)
        if name=='goto':
            if not self.batch_path:return self.result(0)
            label=arg.strip().lstrip(':')
            if label.lower()=='eof' and self.state.extensions:
                self.data_exit_status=True
                raise ExitFlow(self.state.errorlevel)
            if self.find_label(self.batch_path,label,0) is None:
                self.write('The system cannot find the batch label specified - '+label+'\r\n',2)
                self.batch_frames[-1]['transferred']=True;return self.result(1,1)
            raise GotoFlow(label)
        if name=='shift':
            offset=0
            if arg:
                if self.state.extensions:
                    if not re.fullmatch(r'/[0-8]',arg.strip()):return self.result(1,1)
                    offset=int(arg.strip()[1])
            if len(self.state.args)>offset:self.state.args.pop(offset)
            return self.result(0)
        if name in ('cd','chdir','pushd','popd'):return self.directory(name,arg)
        if name in ('dir','type','copy','md','mkdir','rd','rmdir','del','erase','ren','rename','move'):return self.files(name,arg)
        if name=='path':
            if arg==';':self.state.env.pop('PATH',None)
            elif arg:self.state.env['PATH']=arg
            else:self.write('PATH='+self.state.env.get('PATH','')+'\r\n')
            return self.result(0,0 if getattr(self,'cmd_semantics',False) else None)
        from .session_commands import NAMES,execute
        if name in NAMES:return execute(self,name,arg)
        if name in BUILTINS:raise Unsupported('Internal command '+name.upper())
        argv=crt_split(text)
        if argv and argv[0].replace('\\','/').rsplit('/',1)[-1].lower() in ('cmd','cmd.exe'):
            return self.cmd_child(text,argv)
        located=self.lookup(argv[0]) if argv else None
        if located and located.suffix.lower() in ('.bat','.cmd'):
            frame=self.batch_frames[-1] if self.batch_frames else None
            head=re.match(r'("[^"]*"|[^\s,;=]+)([\s\S]*)',text)
            rawargs=head[2].strip() if head else ''
            code=(yield self._gen_batch(located,batch_split(rawargs),raw_args=rawargs,argv0=head[1] if head else argv[0]))
            if frame is not None:frame['transferred']=True
            return self.result(code)
        if not argv:return self.result(0)
        if located and located.suffix.lower() not in ('.exe','.com'):
            association=getattr(self.state,'assoc_table',{}).get(located.suffix.lower())
            template=getattr(self.state,'ftype_table',{}).get((association or '').lower())
            if template and not getattr(self,'association_active',False):
                head=re.match(r'("[^"]*"|[^\s]+)([\s\S]*)',text)
                arguments=crt_split(head[2]) if head else []
                def substitute(match):
                    key=match[1]
                    return head[2].lstrip() if key=='*' else str(located) if key in ('0','1') else arguments[int(key)-2] if len(arguments)>=int(key)-1 else ''
                expanded=re.sub(r'%([0-9*])',substitute,template)
                self.association_active=True
                try:return self.command(expanded)
                finally:self.association_active=False
        from .external_tools import execute as tool_execute
        toolcode=tool_execute(self,name.removesuffix('.exe'),arg)
        if toolcode is not None:
            if name.removesuffix('.exe') in ('find','findstr') and toolcode in (0,1):
                self.data_exit_status=True
            self.state.external_code=signed32(toolcode);return self.result(toolcode,toolcode)
        from .process import launch
        try:code=launch(self,text)
        except FileNotFoundError:
            if any(ch in argv[0] for ch in '/\\') and not self.path(argv[0]).parent.exists():
                self.write('The system cannot find the path specified.\r\n',2);return self.result(1,1)
            self.write("'"+(re.match(r'"[^"]*"|\S+',text)[0])+"' is not recognized as an internal or external command,\r\noperable program or batch file.\r\n",2)
            return self.result(1,9009)
        self.state.external_code=signed32(code);return self.result(code,code)
    def cmd_child(self,text,argv,update_hidden=True):
        child=self.fork(stdin=self.streams.table[0],stdout=self.streams.table[1],stderr=self.streams.table[2])
        child.state.delayed=False;child.state.extensions=True
        # /C tail stays a raw command string, never reconstructed from CRT argv.
        match=re.search(r'(?i)(?:^|\s)/([ck])',text)
        prefix=text[:match.start()] if match else text
        options=crt_split(prefix)[1:]
        for option in options:
            lower=option.lower()
            if lower.startswith('/v:'):child.state.delayed=lower=='/v:on'
            elif lower.startswith('/e:'):child.state.extensions=lower=='/e:on'
            elif lower=='/u':child.state.unicode_output=True
            elif lower=='/a':child.state.unicode_output=False
            elif lower=='/q':child.state.echo=False
            elif lower in ('/x','/y'):child.state.extensions=lower=='/x'
            elif lower.startswith('/t:'):
                from .session_commands import execute
                execute(child,'color',option[3:])
            elif lower.startswith('/f:'):pass  # Interactive completion has no batch effect.
            elif lower not in ('/d','/s'):raise Unsupported('CMD option '+option)
        if child.autorun and '/d' not in [x.lower() for x in options]:child.command(child.autorun)
        if not match:
            code=child.interactive()
            self.state.unsupported.extend(child.state.unsupported)
            child.streams.close_owned()
            return self.result(code,code)
        body=text[match.end():].lstrip()
        code=child.entry(body,options)
        if match[1].lower()=='k' and not child.session_exited:code=child.interactive(banner=False)
        self.state.unsupported.extend(child.state.unsupported)
        if update_hidden:self.state.external_code=signed32(code)
        child.streams.close_owned()
        return self.result(code,code)
    def do_set(self,arg):
        if not self.state.extensions and (arg.startswith('"') or arg.lower().startswith(('/a','/p')) or (arg and '=' not in arg)):
            self.write('The syntax of the command is incorrect.\r\n',2);return self.result(1,1)
        if arg.lower().startswith('/a'):
            from .arithmetic import calculate,ArithmeticError
            try:value=calculate(arg[2:].lstrip(),self.state.env)
            except ArithmeticError as exc:
                self.write(exc.message+'\r\n',2);return self.result(1,exc.code)
            if not self.batch_path:self.write(str(value))
            return self.result(0)
        if arg.lower().startswith('/p'):
            from .readers import setp
            text=arg[2:].lstrip()
            if text.startswith('"'):text=text[1:text.rfind('"')] if '"' in text[1:] else text[1:]
            if '=' not in text:self.write('The syntax of the command is incorrect.\r\n',2);return self.result(1,1)
            name,prompt=text.split('=',1);prompt=prompt.lstrip(' \t')
            if prompt.startswith('='):
                self.write('The syntax of the command is incorrect.\r\n',2);return self.result(1,1)
            self.write(prompt)
            value=setp(self.streams.table[0],self.state.encoding)
            if value is None:
                self.data_exit_status=True
                return self.result(1,1)
            if name:
                if value:self.state.env[name]=value
                else:self.state.env.pop(name,None)
            return self.result(0,0)
        if arg.startswith('"'):
            end=arg.rfind('"');arg=arg[1:end] if end>0 else arg[1:]
        if '=' in arg:
            key,val=arg.split('=',1)
            if not key:
                self.write('The syntax of the command is incorrect.\r\n',2);return self.result(1,1)
            if val:self.state.env[key]=val
            else:self.state.env.pop(key,None)
            return self.result(0,0 if getattr(self,'cmd_semantics',False) else None)
        found=False
        for key in sorted(self.state.env,key=str.upper):
            if key.upper().startswith(arg.upper()):self.write(key+'='+self.state.env[key]+'\r\n');found=True
        if not found:
            self.write('Environment variable '+arg+' not defined\r\n',2);return self.result(1,1)
        return self.result(0,0 if getattr(self,'cmd_semantics',False) else None)
    def do_call(self,tail):
        return self._drive(self._gen_do_call(tail))
    def _gen_do_call(self,tail):
        if not tail:return self.result(1,1)
        if not tail.strip():return self.result(0,0)
        text=self.expand_execution(unescape(tail.lstrip()))
        second=percent(text.replace('^','^^'),self.state,batch=True)
        try:node=parse(second)
        except ParseFailure as exc:
            self.write(str(exc)+'\r\n',2);return self.result(1,1)
        if node.kind not in ('command','empty'):return self.result(0,0)
        clean,_=extract(second)
        args=crt_split(clean)
        if not args:return self.result(0,0)
        if args[0].startswith(':'):
            if not self.state.extensions:return self.result(1)
            if not self.batch_path:
                self.write('Invalid attempt to call batch label outside of batch script.\r\n',2)
                return self.result(1,1)
            head=re.match(r'\S+([\s\S]*)',clean);rawargs=head[1].lstrip()
            return (yield self._gen_batch(self.batch_path,batch_split(rawargs),label=args[0][1:],raw_args=rawargs,argv0=args[0]))
        located=self.lookup(args[0])
        if located and located.suffix.lower() in ('.bat','.cmd'):
            head=re.match(r'("[^"]*"|[^\s,;=]+)([\s\S]*)',clean)
            rawargs=head[2].lstrip() if head else ''
            (yield self._gen_batch(located,batch_split(rawargs),raw_args=rawargs,argv0=head[1] if head else args[0]))
            return self.result(self.state.errorlevel)
        if args[0].lower()=='for' and not re.search(r'%[^\s]\s+in\b',clean,re.I):
            bad=re.sub(r'^for\s+','',clean,flags=re.I).split()[0] if len(args)>1 else ''
            self.write(bad+' was unexpected at this time.\r\n',2);return self.result(1,1)
        if args[0].lower() in ('if','for'):
            self.write("'"+args[0]+"' is not recognized as an internal or external command,\r\noperable program or batch file.\r\n",2)
            return self.result(1,1)
        delayed=self.state.delayed;self.state.delayed=False
        try:code=(yield self._gen_simple(clean))
        finally:self.state.delayed=delayed
        return self.result(code,code)
    def do_if(self,tail):
        return self._drive(self._gen_do_if(tail))
    def _gen_do_if(self,tail):
        # Expand condition separately; do not pre-expand the branch body at execution time.
        text=tail.lstrip();negate=False;ignore=False
        if text.lower().startswith('/i '):
            if not self.state.extensions:
                self.write(text[3:].lstrip().split()[0]+' was unexpected at this time.\r\n',2);raise ExitFlow(255)
            ignore=True;text=text[3:].lstrip()
        if text.lower().startswith('not '):negate=True;text=text[4:].lstrip()
        m=re.match(r'(defined|exist|errorlevel|cmdextversion)\s+("[^"]*"|\S+)\s+(.+)',text,re.I|re.S)
        if m:
            kind,operand,body=m.groups();operand=unescape(self.expand_execution(operand))
            if kind.lower() in ('defined','cmdextversion') and not self.state.extensions:
                self.write(operand+' was unexpected at this time.\r\n',2);raise ExitFlow(255)
            if kind.lower()=='defined':condition=operand in self.state.env
            elif kind.lower()=='cmdextversion':condition=2>=int(operand)
            elif kind.lower()=='exist':
                from .filesystem import expand
                condition=bool(expand(self,operand))
            else:
                try:condition=self.state.errorlevel>=int(operand)
                except ValueError:
                    self.write(operand+' was unexpected at this time.\r\n',2);raise ExitFlow(255)
        else:
            m=re.match(r'("[^"]*"|[^\s=]+)[ \t]*==[ \t]*("[^"]*"|[^\s]+)\s+(.+)',text,re.S)
            if m:
                left,right,body=m.groups();left=self.expand_execution(left);right=self.expand_execution(right)
                condition=left.casefold()==right.casefold() if ignore else left==right
            else:
                m=re.match(r'("[^"]*"|\S+)\s+(equ|neq|lss|leq|gtr|geq)\s+("[^"]*"|\S+)\s+(.+)',text,re.I|re.S)
                if not m:
                    self.write('The syntax of the command is incorrect.\r\n',2);raise ExitFlow(255)
                from .conditions import compare
                left,op,right,body=m.groups()
                condition=compare(self.expand_execution(left),self.expand_execution(right),op,ignore)
        from .conditions import branches
        body,alternative=branches(body)
        if condition!=negate:return (yield self._gen_execute(parse(body)))
        return (yield self._gen_execute(parse(alternative))) if alternative is not None else self.result(0)
    def do_for(self,tail):
        return self._drive(self._gen_do_for(tail))
    def _gen_do_for(self,tail):
        tail=re.sub(r"%\^(.)",r"%\1",tail,count=1)
        f=re.fullmatch(r'\s*/f\s+(?:(.*?)\s+)?%([^\s])\s+in\s*\(([\s\S]*?)\)\s*do\s+([\s\S]+)',tail,re.I)
        if f:
            if not self.state.extensions:
                self.write('/f was unexpected at this time.\r\n',2);raise ExitFlow(255)
            from .loops import ForOptions,command_source
            options,name,source,body=f.groups();rawoptions=options or ''
            invalid=re.search(r'(?:tokens|skip)=0(?![0-9xX])',rawoptions,re.I)
            if invalid:
                self.write(rawoptions[invalid.end():]+' was unexpected at this time.\r\n',2);return self.result(1)
            try:options=ForOptions(unescape(rawoptions.strip('\"')))
            except Unsupported:
                self.write(rawoptions+' was unexpected at this time.\r\n',2);return self.result(1)
            source=self.expand_execution(source).strip();command=False;datasets=None
            quote='`' if options.usebackq else "'"
            literal="'" if options.usebackq else '"'
            if source.startswith(quote) and source.endswith(quote):
                child=self.fork();child.state.delayed=False
                producer=unescape(command_source(source[1:-1]))
                if producer.startswith('"') and producer.endswith('"'):producer=producer[1:-1]
                child.command(producer);data=child.streams.table[1].getvalue();command=True
                self.streams.write(2,child.streams.table[2].getvalue())
                self.state.unsupported.extend(child.state.unsupported)
            elif source.startswith(literal) and source.endswith(literal):data=source[1:-1].encode(self.state.encoding,errors='replace')
            else:
                parts=crt_split(source);datasets=[]
                for item in parts:
                    try:datasets.append(self.path(item).read_bytes())
                    except OSError:
                        self.write('The system cannot find the file '+item+'.\r\n',2)
                        return self.result(1,1)
            saved=self.state.for_values.copy();code=1;iterated=False
            try:
                for values in (record for chunk in (datasets if datasets is not None else [data]) for record in options.records(chunk,self.state.encoding,command)):
                    iterated=True
                    for index,value in enumerate(values):self.state.for_values[chr(ord(name)+index)]=value
                    code=(yield self._gen_for_body(body))
            finally:self.state.for_values=saved
            # No input records is a data outcome, not a command failure.
            if not iterated:self.data_exit_status=True
            return self.result(code)
        m=re.fullmatch(r'\s*(.*?)%([^\s])\s+in\s*\((.*?)\)\s*do\s+(.+)',tail,re.I|re.S)
        if not m:
            token=tail.strip().split()[0] if tail.strip() else ''
            self.write(token+' was unexpected at this time.\r\n',2);return self.result(1,1)
        prefix,name,items,body=m.groups();items=self.expand_execution(items)
        options=crt_split(prefix);mode='';root=None;directories_only=False;recursive=False
        i=0
        while i<len(options):
            option=options[i].lower()
            if option=='/d':directories_only=True;mode=mode or '/d'
            elif option=='/r':
                recursive=True;mode='/r'
                if i+1<len(options) and not options[i+1].startswith('/'):i+=1;root=options[i]
            elif option=='/l':mode='/l'
            else:
                self.write(options[i]+' was unexpected at this time.\r\n',2);return self.result(1)
            i+=1
        if mode and not self.state.extensions:
            self.write(mode+' was unexpected at this time.\r\n',2);raise ExitFlow(255)
        if mode=='/l':
            from .conditions import number
            fields=[x for x in re.split(r'[\s,;=]+',items.strip()) if x][:3]
            values_=[number(x) for x in fields]
            values_ += [0]*(3-len(values_))
            if len(values_)!=3 or any(x is None for x in values_):
                self.write('The syntax of the command is incorrect.\r\n',2);return self.result(1,1)
            start,step,end=values_
            def numeric_values():
                current=start
                while (current<=end if step>=0 else current>=end):
                    yield str(current);current=signed32(current+step)
            values=numeric_values()
        else:
            from .filesystem import expand
            from .attributes import get as attrs
            values=[];roots=[self.state.cwd]
            if mode=='/r':
                first=self.path((root or '.').strip('"'));roots=[first]
                if first.is_dir():roots+=sorted((p for p in first.rglob('*') if p.is_dir()),key=str)
            for directory in roots:
                for item in re.findall(r'"[^"]*"|[^\s,;=]+',items):
                    pattern=str(directory/item.strip('"')) if mode=='/r' else item
                    if any(ch in item for ch in '*?'):
                        for path in expand(self,pattern):
                            if (path.is_dir() if directories_only else path.is_file()) and not attrs(path)&6:
                                name_=str(path) if mode=='/r' or Path(item.strip('"')).is_absolute() else str(path.relative_to(self.state.cwd)).replace('/','\\')
                                values.append(('"'+name_+'"') if item.startswith('"') else name_)
                    else:values.append(pattern if mode=='/r' else item)
        previous=self.state.for_values.get(name);code=0
        try:
            for v in values:self.state.for_values[name]=v;code=(yield self._gen_for_body(body))
        finally:
            if previous is None:self.state.for_values.pop(name,None)
            else:self.state.for_values[name]=previous
        return self.result(code)
    def for_body(self,body):
        return self._drive(self._gen_for_body(body))
    def _gen_for_body(self,body):
        node=parse(body)
        from .echoing import emit
        emit(self,node)
        return (yield self._gen_execute(node))
    def directory(self,name,arg):
        if name=='popd':
            if self.state.directories:self.state.cwd=self.state.directories.pop()
            return self.result(0)
        if not arg:self.write(str(self.state.cwd)+'\r\n');return self.result(0)
        change_drive=arg.lower().startswith('/d ') or name=='pushd'
        if os.name=='nt' and re.fullmatch(r'[a-zA-Z]:',arg):
            self.write(str(self.path(arg))+'\r\n');return self.result(0)
        if arg.lower().startswith('/d '):
            if not self.state.extensions:
                self.write('The filename, directory name, or volume label syntax is incorrect.\r\n',2);return self.result(1,1)
            arg=arg[3:].lstrip()
        target=self.path(arg.strip('"')).resolve()
        if not target.is_dir():self.write('The system cannot find the path specified.\r\n',2);return self.result(1,1)
        if name=='pushd':self.state.directories.append(self.state.cwd)
        if target.drive:self.drive_dirs[target.drive.upper()]=target
        if os.name=='nt' and not change_drive and target.drive.upper()!=self.state.cwd.drive.upper():return self.result(0,0)
        self.state.cwd=target;return self.result(0,0)
    def files(self,name,arg):
        from .filesystem import execute
        return execute(self,name,arg)
    def batch(self,path,args=None,label=None,raw_args=None,argv0=None):
        return self._drive(self._gen_batch(path,args,label,raw_args,argv0))
    def _gen_batch(self,path,args=None,label=None,raw_args=None,argv0=None):
        path=Path(path).resolve();old=(self.batch_path,self.state.args,self.state.raw_args)
        old_filename=getattr(self.state,'batch_filename',None);self.state.batch_filename=path
        old_for=self.state.for_values;self.state.for_values={}
        frame={'transferred':False,'trace':{'file':str(path),'line':1,'name':':'+label if label else '<batch>','source':''}};self.batch_frames.append(frame)
        depth=len(self.state.locals);self.batch_path=path
        if old[0] is None:self.cmd_semantics=path.suffix.lower()=='.cmd'
        self.state.args=[argv0 if argv0 is not None else str(path)]+list(args or []);self.state.raw_args=' '.join(args or []) if raw_args is None else raw_args.lstrip()
        offset=0;code=0
        def read_record(file):
            if not self.diagnostics.enabled:return batch_line(file)
            position=file.tell();raw=batch_line(file);end=file.tell()
            frame['trace_read_offset']=position
            # Keep the actual consumed bytes (including skipped NUL/CR/Ctrl-Z),
            # but count physical lines only if a traceback is requested.
            file.seek(position);frame['trace_chunks'].append(file.read(end-position))
            return raw
        try:
            if label is not None:
                offset=self.find_label(path,label,0)
                if offset is None:
                    self.write('The system cannot find the batch label specified - '+label+'\r\n',2);return self.result(1,1)
            while True:
                with path.open('rb') as file:
                    if self.diagnostics.enabled:
                        file.seek(0);frame['trace_prefix']=file.read(offset)
                        frame['trace_start']=offset;frame['trace_chunks']=[]
                        frame['trace']['source']=''
                        frame.pop('trace_raw',None);frame.pop('trace_expanded_lines',None)
                    file.seek(offset);raw=read_record(file);offset=file.tell()
                    if not raw:break
                    text=raw.decode(self.state.encoding,errors='replace').rstrip('\r\n')
                    if self.state.encoding=='utf-8':text=text.removeprefix('\ufeff')
                    frame['trace']['source']=text
                    frame['trace_offsets']=[frame.get('trace_read_offset',0)]
                    while text.endswith('^'):
                        raw=read_record(file);offset=file.tell()
                        continuation=raw.decode(self.state.encoding,errors='replace').rstrip('\r\n')
                        text=text[:-1]+(continuation if continuation else '\ue000')
                        if continuation and not percent(continuation,self.state,True):text+='\ue000'
                        if raw and not continuation:
                            raw=read_record(file);offset=file.tell();text+=raw.decode(self.state.encoding,errors='replace').rstrip('\r\n')
                        if not raw:break
                    from .batch_reader import expanded_record, first_command
                    expanded=expanded_record(percent(text,self.state,True,per_line=True))
                    # Expansion can introduce both block delimiters and a
                    # trailing caret requesting another physical record.
                    while True:
                        if expanded.endswith('^') and (len(expanded)-len(expanded.rstrip('^')))%2:
                            raw=read_record(file);offset=file.tell()
                            if not raw:break
                            frame['trace_offsets'].append(frame.get('trace_read_offset',0))
                            continuation=raw.decode(self.state.encoding,errors='replace').rstrip('\r\n')
                            text+='\n'+continuation
                            expanded=expanded[:-1]+expanded_record(percent(continuation,self.state,True))
                            continue
                        expanded=first_command(expanded)
                        try:parse(expanded);break
                        except SyntaxFailure as exc:
                            if str(exc)!='Unclosed parenthesis':raise
                            raw=read_record(file);offset=file.tell()
                            if not raw:raise SilentSyntaxFailure('Unclosed parenthesis')
                            frame['trace_offsets'].append(frame.get('trace_read_offset',0))
                            continuation=raw.decode(self.state.encoding,errors='replace').rstrip('\r\n')
                            text+='\n'+continuation
                            expanded+='\n'+expanded_record(percent(continuation,self.state,True))
                frame['trace_lines']=text.split('\n')
                frame['trace_unit']=text
                try:
                    if self.diagnostics.enabled:self.diagnostics.prepare_unit(frame,text,expanded)
                    frame['trace_unit']=expanded
                    node=parse(expanded)
                    from .echoing import emit
                    emit(self,node);code=(yield self._gen_execute(node))
                except GotoFlow as jump:
                    new=self.find_label(path,jump.label,offset)
                    if new is None:
                        self.write('The system cannot find the batch label specified - '+jump.label+'\r\n',2);code=self.result(1,1);break
                    offset=new
                if frame['transferred']:break
                if self.transfer:
                    path,newargs=self.transfer;self.transfer=None;self.batch_path=path
                    self.state.args=[str(path)]+newargs;self.state.raw_args=' '.join(newargs);offset=0
        except KeyboardInterrupt as exc:
            self.diagnostics.interrupted(exc)
            raise
        except ExitFlow as exc:
            if exc.session and old[0] is not None:raise
            self.session_exited=exc.session;code=self.result(exc.code,exc.code)
        except Unsupported as exc:code=self.unsupported(exc)
        except SilentSyntaxFailure as exc:self.diagnostics.emit(str(exc));code=self.result(255)
        except SyntaxFailure as exc:self.write(str(exc)+'\r\n',2);code=self.result(255)
        except OSError:self.write('The batch file cannot be found.\r\n',2);code=self.result(1,1)
        finally:
            while len(self.state.locals)>depth:self.state.end_local()
            self.batch_path,self.state.args,self.state.raw_args=old
            self.state.for_values=old_for;self.batch_frames.pop();self.state.batch_filename=old_filename
        return code
    def find_label(self,path,label,start):
        from .readers import label_index
        entries=[offset for name,offset in label_index(path.read_bytes(),self.state.encoding)
                 if name==label.lower()]
        return next((p for p in entries if p>start),entries[0] if entries else None)
