"""Tutorial-compatible CMOS built-in. Coordinates are visible character cells."""
from dataclasses import dataclass
import math
import os
import re
import time
from .syntax import crt_split
from .terminal_input import managed,TerminalInput

HELP=('CMOS c t l [X Y]\r\n'
      'c: 0 left, 1 right, 2 middle, 3 timeout only.\r\n'
      't: seconds; negative waits indefinitely; l is accepted but ignored.\r\n'
      'X Y: optional zero-based final cursor position in the visible window.\r\n'
      'ERRORLEVEL: +(x*1000+y) on click, negative on timeout; x/y are one-based.\r\n'
      'Errors return 0. Requires interactive terminal input and output.\r\n')

class CmosError(Exception):pass

@dataclass(frozen=True)
class Options:
    button:int
    seconds:float
    final:tuple|None

@dataclass(frozen=True)
class Mouse:
    x:int
    y:int
    button:int|None=None  # CMOS numbering; only a fresh press has a button.

def options(arg):
    parts=crt_split(arg)
    if len(parts) not in (3,5):raise CmosError('Expected c t l [X Y]; use CMOS /?')
    if any(not re.fullmatch(r'[+-]?[0-9]+',parts[i]) for i in (0,2)):
        raise CmosError('c and l must be integers')
    if not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)',parts[1]):
        raise CmosError('t must be a finite number of seconds')
    button=int(parts[0]);seconds=float(parts[1])
    if button not in (0,1,2,3) or not math.isfinite(seconds):raise CmosError('Invalid button or timeout')
    if len(parts)==5:
        if any(not re.fullmatch(r'[0-9]+',s) for s in parts[3:]):raise CmosError('X and Y must be nonnegative integers')
        final=tuple(map(int,parts[3:]))
    else:final=None
    return Options(button,seconds,final)

def encoded(position):
    x,y=position
    if x<0 or not 0<=y<999 or (x+1)*1000+y+1>2147483647:
        raise CmosError('Position cannot be represented by the CMOS exit code')
    return (x+1)*1000+y+1

def capture(backend,opt,clock=time.monotonic):
    position=backend.position()
    encoded(position)
    if opt.final is not None and not backend.contains(*opt.final):raise CmosError('Final cursor position is outside the visible window')
    deadline=None if opt.seconds<0 else clock()+opt.seconds
    while True:
        left=None if deadline is None else deadline-clock()
        if left is not None and left<=0:
            result=-encoded(position);break
        event=backend.poll(0.05 if left is None else min(0.05,left))
        if event is None or not backend.contains(event.x,event.y):continue
        position=(event.x,event.y);encoded(position);backend.move(*position)
        if event.button==opt.button:
            result=encoded(position);break
    if opt.final is not None:backend.move(*opt.final)
    return result

def backend_for(source,output):
    if os.name=='nt':
        from .cmos_windows import WindowsMouse
        return WindowsMouse(source,output)
    from .cmos_posix import PosixMouse
    return PosixMouse(source,output)

def execute(rt,arg):
    if arg.strip()=='/?':rt.write(HELP);return rt.result(0)
    try:
        opt=options(arg)
        if rt.console is not None:
            from .gui import GuiMouse
            with GuiMouse(rt.console) as backend:result=capture(backend,opt)
            rt.data_exit_status=True
            return rt.result(result,result)
        source=managed(rt.streams.table[0]);output=rt.streams.table[1]
        if not isinstance(source,TerminalInput) or not getattr(output,'isatty',lambda:False)():
            raise CmosError('Interactive terminal stdin and stdout are required')
        rt.streams.table[0]=source
        with source.lock,backend_for(source,output) as backend:
            result=capture(backend,opt)
        rt.data_exit_status=True
        return rt.result(result,result)
    except (CmosError,OSError,ValueError) as exc:
        rt.write('CMOS: '+str(exc)+'\r\n',2)
        return rt.result(0,0)
