"""SGR mouse tracking without curses or an alternate screen."""
from collections import deque
import os
import re
import select
import time
from .cmos import CmosError,Mouse

MODES=(1000,1002,1003,1005,1006,1015,1016)

class Decoder:
    def __init__(self):
        self.buffer=bytearray();self.keys=bytearray();self.events=deque()
        self.cursor=None;self.modes={}

    def feed(self,data):
        self.buffer.extend(data)
        while self.buffer:
            if self.buffer[0]==3:del self.buffer[0];raise KeyboardInterrupt
            if self.buffer[0]!=27:
                self.keys.append(self.buffer.pop(0));continue
            if len(self.buffer)==1:return
            if self.buffer[1]!=91:self.keys.append(self.buffer.pop(0));continue
            match=re.match(rb'\x1b\[[0-?]*[ -/]*[@-~]',self.buffer)
            if not match:
                if len(self.buffer)<128:return
                self.keys.append(self.buffer.pop(0));continue
            packet=match[0];del self.buffer[:len(packet)]
            mouse=re.fullmatch(rb'\x1b\[<([0-9]+);([0-9]+);([0-9]+)([Mm])',packet)
            cursor=re.fullmatch(rb'\x1b\[([0-9]+);([0-9]+)R',packet)
            mode=re.fullmatch(rb'\x1b\[\?([0-9]+);([0-9]+)\$y',packet)
            if mouse:
                button,x,y=map(int,mouse.groups()[:3]);press=None
                if packet[-1:]==b'M' and not button&(32|64|128) and button&3 in (0,1,2):
                    press={0:0,1:2,2:1}[button&3]
                self.events.append(Mouse(x-1,y-1,press))
            elif cursor:self.cursor=(int(cursor[2])-1,int(cursor[1])-1)
            elif mode:self.modes[int(mode[1])]=int(mode[2])
            else:self.keys.extend(packet)

class PosixMouse:
    def __init__(self,source,output):
        self.source=source;self.output=output;self.decoder=Decoder()
        self.saved=None;self.changed=False

    def send(self,data):self.output.write(data);self.output.flush()

    def __enter__(self):
        import termios
        self.fd=self.source.fileno()
        if os.ttyname(self.fd)!=os.ttyname(self.output.fileno()):raise CmosError('stdin and stdout must use the same terminal')
        try:
            self.saved=termios.tcgetattr(self.fd)
            mode=termios.tcgetattr(self.fd)
        except termios.error as exc:raise CmosError(str(exc)) from exc
        mode[0]&=~(termios.ICRNL|termios.INLCR|termios.IGNCR|termios.IXON)
        mode[3]&=~(termios.ICANON|termios.ECHO)
        mode[6][termios.VMIN]=1;mode[6][termios.VTIME]=0
        try:
            termios.tcsetattr(self.fd,termios.TCSANOW,mode)
            self.send(b'\x1b[6n'+b''.join(f'\x1b[?{n}$p'.encode() for n in MODES))
            deadline=time.monotonic()+1.0
            while time.monotonic()<deadline:
                self.read(max(0,deadline-time.monotonic()))
                if self.decoder.cursor is not None and all(n in self.decoder.modes for n in MODES):break
            if self.decoder.cursor is None or any(self.decoder.modes.get(n) not in (1,2,3) for n in (1003,1006)):
                raise CmosError('Terminal does not report cursor position and SGR mouse support')
            self.changed=True
            for n in MODES:
                if self.decoder.modes.get(n)==1:self.send(f'\x1b[?{n}l'.encode())
            self.send(b'\x1b[?1006h\x1b[?1003h')
            self.decoder.events.clear()
            return self
        except BaseException as exc:
            self.__exit__(None,None,None)
            if isinstance(exc,termios.error):raise CmosError(str(exc)) from exc
            raise

    def __exit__(self,*exc):
        import termios
        try:
            if self.changed:
                try:
                    self.send(b'\x1b[?1003l\x1b[?1006l')
                    # A position reply is a barrier after disabling reports.
                    # Consume in-flight packets before handing stdin to SET/P.
                    self.decoder.cursor=None
                    self.send(b'\x1b[6n')
                    deadline=time.monotonic()+0.2
                    while self.decoder.cursor is None and time.monotonic()<deadline:
                        self.read(max(0,deadline-time.monotonic()))
                finally:
                    for n,state in self.decoder.modes.items():
                        if n in MODES and state==1:self.send(f'\x1b[?{n}h'.encode())
        finally:
            try:
                if self.saved is not None:
                    try:termios.tcsetattr(self.fd,termios.TCSANOW,self.saved)
                    except termios.error as error:raise CmosError(str(error)) from error
            finally:
                # Keep keyboard bytes for the next SET/P. Do not replay an
                # incomplete mouse/control response as user-entered text.
                self.source.unread(bytes(self.decoder.keys).replace(b'\r',b'\n'))

    def read(self,timeout):
        if select.select([self.fd],[],[],timeout)[0]:
            data=os.read(self.fd,4096)
            if not data:raise CmosError('Terminal input closed')
            self.decoder.feed(data)

    def poll(self,timeout):
        if not self.decoder.events:self.read(timeout)
        return self.decoder.events.popleft() if self.decoder.events else None

    def position(self):return self.decoder.cursor
    def contains(self,x,y):
        size=os.get_terminal_size(self.output.fileno())
        return 0<=x<size.columns and 0<=y<size.lines
    def move(self,x,y):self.send(f'\x1b[{y+1};{x+1}H'.encode())
