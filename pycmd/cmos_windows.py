"""Native console mouse input. No desktop hooks or pointer clipping."""
import ctypes as C
from .cmos import CmosError,Mouse

WORD=C.c_uint16
DWORD=C.c_uint32
SHORT=C.c_int16
BOOL=C.c_int32

class COORD(C.Structure):
    _fields_=[('X',SHORT),('Y',SHORT)]
class RECT(C.Structure):
    _fields_=[('Left',SHORT),('Top',SHORT),('Right',SHORT),('Bottom',SHORT)]
class INFO(C.Structure):
    _fields_=[('size',COORD),('cursor',COORD),('attributes',WORD),('window',RECT),('maximum',COORD)]
class KEY(C.Structure):
    _fields_=[('down',BOOL),('repeat',WORD),('virtual',WORD),('scan',WORD),('char',WORD),('control',DWORD)]
class MOUSE(C.Structure):
    _fields_=[('position',COORD),('buttons',DWORD),('control',DWORD),('flags',DWORD)]
class EVENT(C.Union):
    _fields_=[('key',KEY),('mouse',MOUSE),('padding',C.c_byte*16)]
class RECORD(C.Structure):
    _fields_=[('kind',WORD),('event',EVENT)]

class WindowsMouse:
    def __init__(self,source,output):
        import msvcrt
        self.kernel=C.WinDLL('kernel32',use_last_error=True)
        self.input=msvcrt.get_osfhandle(source.fileno())
        self.output=msvcrt.get_osfhandle(output.fileno())
        signatures={
            'GetConsoleMode':([C.c_void_p,C.POINTER(DWORD)],BOOL),
            'SetConsoleMode':([C.c_void_p,DWORD],BOOL),
            'GetConsoleScreenBufferInfo':([C.c_void_p,C.POINTER(INFO)],BOOL),
            'SetConsoleCursorPosition':([C.c_void_p,COORD],BOOL),
            'WaitForSingleObject':([C.c_void_p,DWORD],DWORD),
            'ReadConsoleInputW':([C.c_void_p,C.POINTER(RECORD),DWORD,C.POINTER(DWORD)],BOOL),
            'WriteConsoleInputW':([C.c_void_p,C.POINTER(RECORD),DWORD,C.POINTER(DWORD)],BOOL),
        }
        for name,(args,result) in signatures.items():
            function=getattr(self.kernel,name);function.argtypes=args;function.restype=result
        self.saved=None;self.keys=[];self.buttons=0

    def check(self,result):
        if not result:raise CmosError('Windows console operation failed (error '+str(C.get_last_error())+')')

    def info(self):
        info=INFO();self.check(self.kernel.GetConsoleScreenBufferInfo(self.output,C.byref(info)))
        return info

    def __enter__(self):
        mode=DWORD();self.check(self.kernel.GetConsoleMode(self.input,C.byref(mode)))
        self.info();self.saved=mode.value
        # Enable extended flags, mouse and resize; disable Quick Edit, VT input,
        # line/echo and processed input. Ctrl+C is handled from KEY_EVENT below.
        try:self.check(self.kernel.SetConsoleMode(self.input,(mode.value|0x98)&~0x247))
        except BaseException:
            self.__exit__(None,None,None);raise
        return self

    def __exit__(self,*exc):
        try:
            if self.saved is not None:self.check(self.kernel.SetConsoleMode(self.input,self.saved))
        finally:
            if self.keys:
                records=(RECORD*len(self.keys))(*self.keys);written=DWORD()
                self.check(self.kernel.WriteConsoleInputW(self.input,records,len(records),C.byref(written)))
                if written.value!=len(records):raise CmosError('Could not restore all deferred keyboard events')

    def position(self):
        info=self.info()
        return info.cursor.X-info.window.Left,info.cursor.Y-info.window.Top

    def contains(self,x,y):
        info=self.info();w=info.window
        return 0<=x<=w.Right-w.Left and 0<=y<=w.Bottom-w.Top

    def move(self,x,y):
        w=self.info().window
        self.check(self.kernel.SetConsoleCursorPosition(self.output,COORD(x+w.Left,y+w.Top)))

    def poll(self,timeout):
        result=self.kernel.WaitForSingleObject(self.input,max(1,int(timeout*1000)))
        if result==258:return None
        if result!=0:raise CmosError('Could not wait for console input')
        record=RECORD();read=DWORD()
        self.check(self.kernel.ReadConsoleInputW(self.input,C.byref(record),1,C.byref(read)))
        if not read.value:return None
        if record.kind==1:
            key=record.event.key
            if key.down and (key.char==3 or key.virtual==0x43 and key.control&0xC):raise KeyboardInterrupt
            self.keys.append(record);return None
        if record.kind!=2:return None
        mouse=record.event.mouse
        pressed=mouse.buttons&~self.buttons;self.buttons=mouse.buttons
        button=None
        if mouse.flags in (0,2):
            button=next((c for c,mask in ((0,1),(1,2),(2,4)) if pressed&mask),None)
        w=self.info().window
        return Mouse(mouse.position.X-w.Left,mouse.position.Y-w.Top,button)
