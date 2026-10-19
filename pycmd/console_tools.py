"""Console CHOICE and the file-copy/keypress subset of XCOPY."""
from contextlib import contextmanager
import os
import re
import shutil
import time
from .syntax import crt_split,Unsupported
from .terminal_input import managed

@contextmanager
def key_reader(rt):
    if rt.console is not None:
        yield lambda timeout:rt.console.call('key',timeout)
        return
    source=managed(rt.streams.table[0]);owned=None
    # FOR/F captures stdout but native key-reading utilities still use the
    # attached console. A child capture runtime has an empty memory stdin.
    if rt.diagnostics.parents and not getattr(source,'isatty',lambda:False)():
        try:owned=open('CONIN$' if os.name=='nt' else '/dev/tty','rb',buffering=0);source=managed(owned)
        except OSError:pass
    try:
        if getattr(source,'isatty',lambda:False)():
            if os.name=='nt':
                import msvcrt
                def read(timeout):
                    deadline=None if timeout is None else time.monotonic()+timeout
                    while not msvcrt.kbhit():
                        if deadline is not None and time.monotonic()>=deadline:return None
                        time.sleep(.01)
                    c=msvcrt.getwch()
                    if c=='\x03':raise KeyboardInterrupt
                    if c in ('\x00','\xe0'):msvcrt.getwch();return ''
                    return c
                yield read
            else:
                import termios,select
                with source.lock:
                    fd=source.fileno();saved=termios.tcgetattr(fd);mode=termios.tcgetattr(fd)
                    mode[3]&=~(termios.ICANON|termios.ECHO)
                    mode[6][termios.VMIN]=1;mode[6][termios.VTIME]=0
                    try:
                        termios.tcsetattr(fd,termios.TCSANOW,mode)
                        def read(timeout):
                            if not source.pending and not select.select([fd],[],[],timeout)[0]:return None
                            return source.read(1).decode(rt.state.encoding,errors='replace')
                        yield read
                    finally:termios.tcsetattr(fd,termios.TCSANOW,saved)
        else:
            def read(timeout):
                if timeout is not None:
                    try:fd=source.fileno()
                    except (AttributeError,OSError):pass
                    else:
                        import select
                        if not select.select([fd],[],[],timeout)[0]:return None
                return source.read(1).decode(rt.state.encoding,errors='replace')
            yield read
    finally:
        if owned:owned.close()

def choice(rt,arg):
    if arg.strip()=='/?':
        rt.write('CHOICE [/C choices] [/N] [/CS] [/T seconds /D choice] [/M message]\r\n');return rt.result(0,0)
    args=crt_split(arg);choices='YN';sensitive=False;hide=False;seconds=None;default=None;message='';i=0
    try:
        while i<len(args):
            token=args[i];i+=1;low=token.lower()
            if low=='/n':hide=True;continue
            if low in ('/cs','/s'):sensitive=True;continue
            m=re.fullmatch(r'/([ctdm])(?::?(.*))?',token,re.I)
            if not m:raise ValueError('Invalid switch: '+token)
            key=m[1].lower();value=m[2]
            if not value:
                value=args[i];i+=1
            if key=='c':choices=value
            elif key=='m':message=value
            elif key=='d':default=value
            elif ',' in value:
                default,value=value.split(',',1);seconds=int(value)
            else:seconds=int(value)
        normalized=choices if sensitive else choices.upper()
        if not choices or len(set(normalized))!=len(choices) or any(not (c.isascii() and c.isalnum() or 128<=ord(c)<=254) for c in choices):raise ValueError('Invalid choices')
        if seconds is not None and not 0<=seconds<=9999:raise ValueError('Invalid timeout')
        if (seconds is None)!=(default is None):raise ValueError('/T and /D must be used together')
        if default is not None and (len(default)!=1 or (default if sensitive else default.upper()) not in normalized):raise ValueError('Invalid default choice')
        rt.write((message+(' ' if not hide else '') if message else '')+('['+','.join(choices)+']?' if not hide else ''))
        deadline=None if seconds is None else time.monotonic()+seconds
        with key_reader(rt) as read:
            while True:
                left=None if deadline is None else max(0,deadline-time.monotonic())
                c=default if left==0 else read(left)
                if c is None:c=default
                if c=='':raise ValueError('No input available')
                if c=='\x03':raise KeyboardInterrupt
                key=c if sensitive else c.upper()
                if key in normalized and len(key)==1:
                    rt.write(c+'\r\n');code=normalized.index(key)+1
                    rt.data_exit_status=True;return rt.result(code,code)
                rt.write('\a')
    except KeyboardInterrupt as exc:
        if rt.console is not None and rt.console.closed.is_set():raise
        rt.diagnostics.interrupted(exc);rt.data_exit_status=True;return rt.result(0,0)
    except (ValueError,IndexError,OSError) as exc:
        rt.write('CHOICE: '+str(exc)+'\r\n',2);return rt.result(255,255)

def xcopy(rt,arg):
    if arg.strip()=='/?':
        rt.write('XCOPY source destination [/W] [/Y] [/Q] [/F] [/L]\r\n');return rt.result(0,0)
    paths=[];flags=set()
    for token in crt_split(arg):
        if re.fullmatch(r'/[wyqfl]',token,re.I):flags.add(token[1:].lower())
        elif re.fullmatch(r'/[A-Za-z-]+(?::.*)?',token):raise Unsupported('XCOPY switch: '+token)
        else:paths.append(token)
    if len(paths)!=2:raise Unsupported('XCOPY requires source and destination (single-file subset)')
    source,target=map(rt.path,paths)
    if 'w' in flags:
        rt.write('Press any key to begin copying file(s) ')
        with key_reader(rt) as read:key=read(None)
        if not key:return rt.result(4,4)
        if key=='\x03':raise KeyboardInterrupt
        rt.write(key+'\r\n')
    if target.is_dir():target=target/source.name
    if source.resolve()==target.resolve():
        rt.write('File cannot be copied onto itself\r\n',2);rt.data_exit_status=True;return rt.result(4,4)
    if not source.is_file():raise Unsupported('XCOPY directories/wildcards are not implemented')
    if target.exists() and 'y' not in flags and 'l' not in flags:raise Unsupported('XCOPY overwrite requires /Y')
    try:
        if 'l' not in flags:shutil.copyfile(source,target)
    except OSError as exc:rt.write('XCOPY: '+str(exc)+'\r\n',2);return rt.result(5,5)
    if 'q' not in flags:rt.write(str(source)+(' -> '+str(target) if 'f' in flags else '')+'\r\n1 File(s) copied\r\n')
    return rt.result(0,0)

def execute(rt,name,arg):return choice(rt,arg) if name=='choice' else xcopy(rt,arg)
