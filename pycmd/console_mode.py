"""MODE CON size subset; success requires an observed size change."""
from contextlib import contextmanager
import os
import re
import time

HELP='MODE CON[:] [COLS=columns] [LINES=lines]\r\nSets console size. ERRORLEVEL: 0 success, 1 failure.\r\n'


def dimensions(arg):
    short=re.fullmatch(r'\s*(?:con\s*:?\s*)?(\d+)\s*,\s*(\d+)\s*',arg,re.I)
    if short:
        cols,lines=map(int,short.groups())
        if not 1<=cols<=32767 or not 1<=lines<=32767:raise ValueError('Invalid console size')
        return {'cols':cols,'lines':lines}
    match=re.match(r'con(?::\s*|\s+|$)',arg.strip(),re.I)
    if not match:raise ValueError('Expected MODE CON [COLS=n] [LINES=n]')
    tail=arg.strip()[match.end():];values={}
    while tail:
        item=re.match(r'(cols|lines)\s*=\s*([0-9]+)(?:\s+|$)',tail,re.I)
        if not item:raise ValueError('Invalid console size parameter')
        key=item[1].lower();value=int(item[2])
        if key in values or not 1<=value<=32767:raise ValueError('Invalid or duplicate console size')
        values[key]=value;tail=tail[item.end():]
    return values


@contextmanager
def console(output):
    if getattr(output,'isatty',lambda:False)():
        yield output
    else:
        # MODE addresses the console even when its textual output is redirected.
        with open('CONOUT$' if os.name=='nt' else '/dev/tty','r+b',buffering=0) as stream:
            yield stream


def posix_size(stream,values):
    fd=stream.fileno();old=os.get_terminal_size(fd)
    cols=values.get('cols',old.columns);lines=values.get('lines',old.lines)
    if not values:return old.columns,old.lines
    if (old.columns,old.lines)==(cols,lines):return cols,lines
    stream.write(f'\x1b[8;{lines};{cols}t'.encode());stream.flush()
    deadline=time.monotonic()+.75
    while True:
        actual=os.get_terminal_size(fd)
        if (actual.columns,actual.lines)==(cols,lines):return cols,lines
        if time.monotonic()>=deadline:
            raise OSError('Terminal did not accept requested size')
        time.sleep(.025)


def windows_size(stream,values):
    import ctypes as C
    import msvcrt
    from .cmos_windows import COORD,RECT,INFO,BOOL
    kernel=C.WinDLL('kernel32',use_last_error=True)
    for name,args in (
        ('GetConsoleScreenBufferInfo',[C.c_void_p,C.POINTER(INFO)]),
        ('SetConsoleScreenBufferSize',[C.c_void_p,COORD]),
        ('SetConsoleWindowInfo',[C.c_void_p,BOOL,C.POINTER(RECT)]),
    ):
        fn=getattr(kernel,name);fn.argtypes=args;fn.restype=BOOL
    handle=msvcrt.get_osfhandle(stream.fileno())
    def check(result):
        if not result:raise OSError('Windows console operation failed (error '+str(C.get_last_error())+')')
    def info():
        result=INFO();check(kernel.GetConsoleScreenBufferInfo(handle,C.byref(result)));return result
    old=info()
    if not values:return old.size.X,old.size.Y
    cols=values.get('cols',old.size.X);lines=values.get('lines',old.size.Y)
    # Grow the buffer before growing the window; shrink it after shrinking the window.
    check(kernel.SetConsoleScreenBufferSize(handle,COORD(max(cols,old.size.X),max(lines,old.size.Y))))
    width=cols if 'cols' in values else old.window.Right-old.window.Left+1
    height=lines if 'lines' in values else old.window.Bottom-old.window.Top+1
    window=RECT(0,0,width-1,height-1)
    check(kernel.SetConsoleWindowInfo(handle,True,C.byref(window)))
    check(kernel.SetConsoleScreenBufferSize(handle,COORD(cols,lines)))
    actual=info()
    if (actual.size.X,actual.size.Y)!=(cols,lines):raise OSError('Console size did not change as requested')
    return cols,lines


def execute(rt,arg):
    if arg.strip()=='/?':rt.write(HELP);return rt.result(0,0)
    try:
        values=dimensions(arg)
        if rt.console is not None:cols,lines=rt.console.call('size',values)
        else:
            with console(rt.streams.table[1]) as stream:
                cols,lines=(windows_size if os.name=='nt' else posix_size)(stream,values)
        if not values:rt.write(f'Columns: {cols}\r\nLines: {lines}\r\n')
        return rt.result(0,0)
    except (OSError,ValueError,AttributeError) as exc:
        rt.write('MODE: '+str(exc)+'\r\n',2)
        return rt.result(1,1)
