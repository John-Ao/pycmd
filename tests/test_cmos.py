import ctypes
import io
import os
from pathlib import Path
import re
import select
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from pycmd import Runtime
from pycmd.cmos import CmosError,Mouse,Options,capture,encoded,options
from pycmd.cmos_posix import Decoder
from pycmd.terminal_input import TerminalInput

ROOT=Path(__file__).resolve().parents[1]

class Backend:
    def __init__(self,events=()):self.events=list(events);self.moves=[];self.now=0;self.closed=False
    def __enter__(self):return self
    def __exit__(self,*args):self.closed=True
    def position(self):return (2,3)
    def contains(self,x,y):return 0<=x<80 and 0<=y<24
    def move(self,x,y):self.moves.append((x,y))
    def poll(self,timeout):
        self.now+=timeout
        event=self.events.pop(0) if self.events else None
        if isinstance(event,BaseException):raise event
        return event

class Output(io.BytesIO):
    def isatty(self):return True

class CmosTests(unittest.TestCase):
    def test_demo_dot_position_and_coordinate_comparison(self):
        for x,expected,code in ((20,b'MATCH',0),(5,b'MISMATCH',1)):
            with self.subTest(x=x):
                output=Output()
                backend=Backend([Mouse(x,7,0)])
                rt=Runtime(stdin=TerminalInput(io.BytesIO()),stdout=output)
                def open_backend(*args):
                    screen=output.getvalue()
                    self.assertTrue(screen.startswith(b'\x1b[2J\x1b[H'))
                    rows=screen.removeprefix(b'\x1b[2J\x1b[H').splitlines()
                    self.assertEqual(rows[7],b' '*20+b'.')
                    return backend
                with patch('pycmd.cmos.backend_for',side_effect=open_backend):
                    result=rt.batch(ROOT/'examples/cmos-demo.bat')
                self.assertEqual(result,code)
                self.assertIn(f'Raw: [{(x+1)*1000+8}]'.encode(),output.getvalue())
                self.assertIn(f'X: [{x+1}]  Y: [8]'.encode(),output.getvalue())
                self.assertEqual(output.getvalue().splitlines()[-1],expected)
                self.assertEqual(backend.moves[-1],(0,10))
                self.assertEqual(rt.streams.table[2].getvalue(),b'')

    def test_parameters_and_reserved_error_code(self):
        self.assertEqual(options('3 .5 -10 0 2'),Options(3,.5,(0,2)))
        for arg in ('','0 1','4 1 1','0 nan 1','0 inf 1','0 1 1 -1 0','0 1 1 0','x 2 1'):
            with self.subTest(arg=arg),self.assertRaises(CmosError):options(arg)
        for arg in ('0 1 0','0 1 1','0 1 -8'):
            self.assertEqual(options(arg),Options(0,1,None))
        rt=Runtime();rt.state.errorlevel=17;rt.command('CMOS 0 1 0')
        self.assertEqual(rt.state.errorlevel,0)
        self.assertIn(b'Interactive terminal',rt.streams.table[2].getvalue())

    def test_selected_button_and_snapshot_before_reset(self):
        backend=Backend([Mouse(4,6,1),Mouse(8,9),Mouse(3,11,0)])
        self.assertEqual(capture(backend,Options(0,-1,(0,2)),lambda:backend.now),4012)
        self.assertEqual(backend.moves[-2:],[(3,11),(0,2)])

    def test_timeout_initial_and_last_position(self):
        backend=Backend()
        self.assertEqual(capture(backend,Options(3,0,None),lambda:backend.now),-3004)
        backend=Backend([Mouse(3,11,0)])
        self.assertEqual(capture(backend,Options(3,.1,None),lambda:backend.now),-4012)
        self.assertEqual(encoded((3,11)),4012)
        with self.assertRaises(CmosError):encoded((0,999))

    def test_outside_events_ignored_and_bad_final_rejected(self):
        backend=Backend([Mouse(-1,0,0),Mouse(80,0,0),Mouse(2,3,0)])
        self.assertEqual(capture(backend,Options(0,-1,None),lambda:backend.now),3004)
        self.assertEqual(backend.moves,[(2,3)])
        with self.assertRaises(CmosError):capture(backend,Options(0,0,(80,0)))

    def test_builtin_precedes_batch_and_traceback_does_not_mark_coordinates_as_error(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'cmos.bat').write_text('@echo WRONG\n')
            backend=Backend([Mouse(3,11,0)])
            rt=Runtime(cwd=folder,stdin=TerminalInput(io.BytesIO()),stdout=Output(),traceback=True)
            with patch('pycmd.cmos.backend_for',return_value=backend):rt.command('CmOs 0 -1 1 0 2')
            self.assertEqual(rt.state.errorlevel,4012)
            self.assertEqual(rt.streams.table[1].getvalue(),b'')
            self.assertEqual(rt.streams.table[2].getvalue(),b'')
            self.assertTrue(backend.closed)
        rt=Runtime();rt.command('cMoS /?')
        self.assertIn(b'CMOS c t l',rt.streams.table[1].getvalue())

    def test_decoder_fragmentation_buttons_wheel_and_keyboard(self):
        decoder=Decoder()
        data=b'abc\r\x1b[4;3R\x1b[?1006;2$y\x1b[<0;4;12M\x1b[<0;4;12m\x1b[<33;5;6M\x1b[<64;7;8M\x1b[<2;9;10M\x1b[<1;2;3M'
        for byte in data:decoder.feed(bytes([byte]))
        self.assertEqual(decoder.cursor,(2,3));self.assertEqual(decoder.modes,{1006:2})
        self.assertEqual(decoder.keys,b'abc\r')
        self.assertEqual([e.button for e in decoder.events],[0,None,None,None,1,2])
        self.assertEqual(decoder.events[0],Mouse(3,11,0))

    def test_interrupt_restores_backend_and_generates_traceback(self):
        rt=Runtime(stdin=TerminalInput(io.BytesIO()),stdout=Output(),traceback=True)
        backend=Backend([KeyboardInterrupt()])
        with patch('pycmd.cmos.backend_for',return_value=backend),self.assertRaises(KeyboardInterrupt):
            rt.command('cmos 0 -1 1')
        self.assertTrue(backend.closed)
        self.assertIn(b'KeyboardInterrupt',rt.streams.table[2].getvalue())

    def test_windows_struct_layout_and_mouse_edges(self):
        from pycmd.cmos_windows import RECORD,KEY,MOUSE,INFO,WindowsMouse
        self.assertEqual(ctypes.sizeof(RECORD),20)
        self.assertEqual(RECORD.event.offset,4)
        self.assertEqual(ctypes.sizeof(KEY),16);self.assertEqual(ctypes.sizeof(MOUSE),16)
        events=[]
        for flags,buttons in ((1,1),(0,1),(0,0),(0,2),(0,0),(0,4)):
            record=RECORD();record.kind=2;record.event.mouse.flags=flags;record.event.mouse.buttons=buttons
            record.event.mouse.position.X=13;record.event.mouse.position.Y=25;events.append(record)
        class Kernel:
            def WaitForSingleObject(self,*args):return 0
            def ReadConsoleInputW(self,handle,record,count,read):
                ctypes.memmove(record,ctypes.byref(events.pop(0)),20)
                read._obj.value=1;return 1
        backend=WindowsMouse.__new__(WindowsMouse);backend.kernel=Kernel();backend.input=1;backend.buttons=0
        info=INFO();info.window.Left=10;info.window.Top=20;backend.info=lambda:info
        output=[backend.poll(.1) for _ in range(6)]
        self.assertEqual([e.button for e in output],[None,None,None,1,None,2])
        self.assertEqual((output[0].x,output[0].y),(3,5))

    def test_windows_keyboard_replay_and_mode_restore(self):
        from pycmd.cmos_windows import WindowsMouse,RECORD
        calls=[]
        class Kernel:
            def SetConsoleMode(self,handle,mode):calls.append(('mode',mode));return 1
            def WriteConsoleInputW(self,handle,records,count,written):
                calls.append(('keys',[records[i].event.key.char for i in range(count)]))
                written._obj.value=count;return 1
        backend=WindowsMouse.__new__(WindowsMouse);backend.kernel=Kernel();backend.input=1;backend.saved=0x1f7
        key=RECORD();key.kind=1;key.event.key.char=ord('q');backend.keys=[key]
        backend.__exit__(KeyboardInterrupt,KeyboardInterrupt(),None)
        self.assertEqual(calls,[('mode',0x1f7),('keys',[ord('q')])])

@unittest.skipUnless(os.name=='posix','Requires a POSIX PTY')
class CmosPtyTests(unittest.TestCase):
    def session(self,command,mouse=True,interrupt=False,support=True,prefill=False):
        import fcntl,pty,struct,termios
        master,slave=pty.openpty();process=None
        fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',24,80,0,0))
        original=termios.tcgetattr(slave)
        output=bytearray();offset=0;sent=False;first_sent=False
        try:
            with tempfile.TemporaryDirectory() as folder:
                script=Path(folder)/'test.bat'
                script.write_text('@echo off\n'+('set /p F=FIRST:\necho FIRST=[%F%]\n' if prefill else '')+
                                  command+'\necho RESULT=%errorlevel%\n'+
                                  ('set /p N=NEXT:\necho INPUT=[%N%]\n' if mouse and not interrupt and support else '')+
                                  ('set /p LAST=LAST:\necho LAST=[%LAST%]\n' if prefill else ''))
                def controlling_terminal():
                    os.setsid();fcntl.ioctl(0,termios.TIOCSCTTY,0)
                process=subprocess.Popen([sys.executable,'-m','pycmd','--traceback','--batch',str(script)],
                                         cwd=ROOT,stdin=slave,stdout=slave,stderr=subprocess.PIPE,preexec_fn=controlling_terminal)
                deadline=time.monotonic()+8
                while process.poll() is None and time.monotonic()<deadline:
                    if not select.select([master],[],[],.05)[0]:continue
                    output.extend(os.read(master,65536))
                    if prefill and not first_sent and b'FIRST:' in output:
                        os.write(master,b'first\nqueued\n');first_sent=True
                    while True:
                        match=re.search(rb'\x1b\[(?:6n|\?[0-9]+\$p|\?1003h)',output[offset:])
                        if not match:break
                        offset+=match.end();packet=match[0]
                        if packet==b'\x1b[6n' and support:os.write(master,b'\x1b[4;3R')
                        elif packet.endswith(b'$p') and support:
                            number=int(re.search(rb'[0-9]+',packet)[0])
                            state=1 if number==1002 else 2
                            os.write(master,f'\x1b[?{number};{state}$y'.encode())
                        elif packet==b'\x1b[?1003h' and not sent:
                            sent=True
                            if interrupt:os.write(master,b'\x03')
                            elif mouse:os.write(master,b'\x1b[<35;9;8Mtyped\r\x1b[<0;4;12M\x1b[<0;4;12m')
                self.assertIsNotNone(process.poll(),bytes(output))
                stderr=process.communicate(timeout=2)[1]
                while select.select([master],[],[],0)[0]:output.extend(os.read(master,65536))
                self.assertEqual(termios.tcgetattr(slave),original)
                return bytes(output),stderr,process.returncode
        finally:
            if process is not None and process.poll() is None:process.kill();process.communicate()
            os.close(master);os.close(slave)

    def test_mouse_follow_reset_and_next_setp_keyboard(self):
        out,err,code=self.session('cMoS 0 -1 0 0 2')
        self.assertEqual(code,0);self.assertEqual(err,b'')
        self.assertIn(b'RESULT=4012',out);self.assertIn(b'INPUT=[typed]',out)
        self.assertIn(b'\x1b[8;9H',out);self.assertIn(b'\x1b[3;1H',out)
        self.assertIn(b'\x1b[?1002h',out)

    def test_timeout_uses_initial_cursor(self):
        out,err,code=self.session('cmos 3 .05 1',mouse=False)
        self.assertIn(b'RESULT=-3004',out);self.assertEqual(err,b'');self.assertEqual(code,0)

    def test_setp_before_cmos_does_not_read_ahead_pasted_lines(self):
        out,err,code=self.session('cmos 0 -1 1',prefill=True)
        self.assertEqual(code,0);self.assertEqual(err,b'')
        self.assertIn(b'FIRST=[first]',out);self.assertIn(b'INPUT=[queued]',out)
        self.assertIn(b'LAST=[typed]',out)

    def test_ctrl_c_restores_modes_and_has_traceback(self):
        out,err,code=self.session('cmos 0 -1 1',interrupt=True)
        self.assertIn(b'KeyboardInterrupt',err);self.assertIn(b'cmos 0 -1 1',err)
        self.assertEqual(code,0x3a);self.assertIn(b'\x1b[?1003l',out)

    def test_unsupported_terminal_fails_without_hanging(self):
        out,err,code=self.session('cmos 0 -1 1',mouse=False,support=False)
        self.assertIn(b'RESULT=0',out);self.assertIn(b'CMOS:',err);self.assertEqual(code,0)

if __name__=='__main__':unittest.main()
