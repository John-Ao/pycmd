"""Display-only adapter for narrow-ambiguous native terminals in --xp mode."""
import codecs
import os
import threading
from .display_width import terminal_text,legacy_wide

class XpOutput:
    def __init__(self,stream,runtime,wide=False):
        self.stream=stream;self.runtime=runtime;self.wide=wide
        self.lock=threading.RLock();self.encoding=None;self.decoder=None
    def __getattr__(self,name):return getattr(self.stream,name)
    def write_control(self,data):self.stream.write(data);self.stream.flush()
    def write_text(self,text):
        with self.lock:
            if os.name=='nt':
                import ctypes as C,msvcrt
                from .cmos_windows import INFO,COORD
                kernel=C.WinDLL('kernel32',use_last_error=True)
                fn=kernel.WriteConsoleW
                fn.argtypes=[C.c_void_p,C.c_wchar_p,C.c_uint32,C.POINTER(C.c_uint32),C.c_void_p];fn.restype=C.c_int
                infofn=kernel.GetConsoleScreenBufferInfo;infofn.argtypes=[C.c_void_p,C.POINTER(INFO)];infofn.restype=C.c_int
                move=kernel.SetConsoleCursorPosition;move.argtypes=[C.c_void_p,COORD];move.restype=C.c_int
                handle=msvcrt.get_osfhandle(self.stream.fileno())
                def send(value):
                    written=C.c_uint32()
                    if not fn(handle,value,len(value.encode('utf-16le'))//2,C.byref(written),None):raise OSError('Could not write XP console text')
                def info():
                    result=INFO()
                    if not infofn(handle,C.byref(result)):raise OSError('Could not read XP console cursor')
                    return result
                if self.wide is not None:send(text if self.wide else terminal_text(text))
                else:
                    pending=[]
                    for char in text:
                        if not legacy_wide(char):pending.append(char);continue
                        if pending:send(''.join(pending));pending=[]
                        before=info()
                        if before.size.X<2:send(char);continue
                        if before.cursor.X==before.size.X-1:send('\r\n');before=info()
                        send(char);after=info()
                        if (after.cursor.X-before.cursor.X)%before.size.X==1:
                            if not move(handle,before.cursor):raise OSError('Could not position XP console cursor')
                            send(terminal_text(char))
                    if pending:send(''.join(pending))
            else:self.stream.write((text if self.wide else terminal_text(text)).encode('utf-8',errors='replace'))
            self.stream.flush()
    def write(self,data):
        with self.lock:
            if bytes(data).startswith(b'\x1b['):
                self.write_control(data);return len(data)
            encoding='utf-16le' if self.runtime.state.unicode_output else self.runtime.state.encoding
            if encoding!=self.encoding:
                self.encoding=encoding;self.decoder=codecs.getincrementaldecoder(encoding)(errors='replace')
            self.write_text(self.decoder.decode(bytes(data)));return len(data)


def attach(runtime):
    # Windows can measure actual cursor movement. POSIX has no equivalent API;
    # the usual narrow terminal is the default, with an explicit wide override.
    setting=runtime.state.env.get('PYCMD_TERMINAL_AMBIGUOUS_WIDTH','') if runtime.xp else '2'
    if setting not in ('','1','2'):raise ValueError('PYCMD_TERMINAL_AMBIGUOUS_WIDTH must be 1 or 2')
    wide=setting=='2' if setting else (None if os.name=='nt' else False)
    adapters={}
    for fd in (1,2):
        stream=runtime.streams.table[fd]
        if isinstance(stream,XpOutput):
            adapter=XpOutput(stream.stream,runtime,wide);adapter.lock=stream.lock
            runtime.streams.table[fd]=adapter;continue
        if hasattr(stream,'write_text') or not getattr(stream,'isatty',lambda:False)():continue
        if id(stream) not in adapters:adapters[id(stream)]=XpOutput(stream,runtime,wide)
        runtime.streams.table[fd]=adapters[id(stream)]
