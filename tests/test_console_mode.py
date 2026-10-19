import ctypes
import io
import os
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

from pycmd import Runtime
from pycmd.console_mode import dimensions,posix_size,windows_size


class Terminal(io.BytesIO):
    def fileno(self):return 42


class ConsoleModeTests(unittest.TestCase):
    def test_syntax(self):
        for arg in ('con lines=22 cols=56','CON:COLS = 56 LINES = 22'):
            self.assertEqual(dimensions(arg),{'lines':22,'cols':56})
        self.assertEqual(dimensions('con cols=56'),{'cols':56})
        self.assertEqual(dimensions('con:'),{})
        for arg in ('con cols=0','con lines=-1','con cols=32768','con cols=2 cols=3','con lines=22 junk','console cols=56'):
            with self.subTest(arg=arg),self.assertRaises(ValueError):dimensions(arg)

    def test_resize_verified_and_omitted_dimension_preserved(self):
        output=Terminal()
        with patch('pycmd.console_mode.os.get_terminal_size',side_effect=[os.terminal_size((80,24)),os.terminal_size((56,24))]):
            self.assertEqual(posix_size(output,{'cols':56}),(56,24))
        self.assertEqual(output.getvalue(),b'\x1b[8;24;56t')

    def test_ignored_request_is_failure_and_same_size_needs_no_escape(self):
        output=Terminal()
        with patch('pycmd.console_mode.os.get_terminal_size',return_value=os.terminal_size((80,24))),patch('pycmd.console_mode.time.monotonic',side_effect=[0,1]):
            with self.assertRaises(OSError):posix_size(output,{'lines':22,'cols':56})
        output=Terminal()
        with patch('pycmd.console_mode.os.get_terminal_size',return_value=os.terminal_size((56,22))):
            self.assertEqual(posix_size(output,{'lines':22,'cols':56}),(56,22))
        self.assertEqual(output.getvalue(),b'')

    def test_runtime_errorlevel_and_conditionals(self):
        for failure in (False,True):
            rt=Runtime();rt.state.errorlevel=99
            with patch('pycmd.console_mode.console',return_value=nullcontext(Terminal())),patch(
                'pycmd.console_mode.posix_size',side_effect=OSError('refused') if failure else None,return_value=(56,22)),patch('pycmd.console_mode.os.name','posix'):
                rt.command('MoDe CoN lines=22 cols=56 && echo SUCCESS || echo FAILURE')
            self.assertEqual(rt.state.errorlevel,1 if failure else 0)
            self.assertEqual(rt.streams.table[1].getvalue(),b'FAILURE\r\n' if failure else b'SUCCESS \r\n')
        rt=Runtime();self.assertEqual(rt.command('mode con cols=0'),1)
        self.assertEqual(rt.state.errorlevel,1)
        self.assertEqual(rt.state.unsupported,[])

    def test_no_console_failure_and_help(self):
        rt=Runtime()
        with patch('pycmd.console_mode.console',side_effect=OSError('No console')):
            self.assertEqual(rt.command('mode con cols=56'),1)
        self.assertEqual(rt.state.errorlevel,1)
        rt.command('mode /?')
        self.assertIn(b'MODE CON',rt.streams.table[1].getvalue())

    def test_windows_buffer_window_order_and_failure(self):
        calls=[];size=[80,24]
        def get_info(handle,pointer):
            pointer._obj.size.X,pointer._obj.size.Y=size;return 1
        def buffer(handle,coord):
            calls.append(('buffer',coord.X,coord.Y));size[:]=[coord.X,coord.Y];return 1
        def window(handle,absolute,rect):
            calls.append(('window',rect._obj.Right+1,rect._obj.Bottom+1));return 1
        class Function:
            def __init__(self,fn):self.fn=fn
            def __call__(self,*args):return self.fn(*args)
        kernel=SimpleNamespace(GetConsoleScreenBufferInfo=Function(get_info),SetConsoleScreenBufferSize=Function(buffer),SetConsoleWindowInfo=Function(window))
        with patch.dict('sys.modules',{'msvcrt':SimpleNamespace(get_osfhandle=lambda fd:fd)}),patch.object(ctypes,'WinDLL',return_value=kernel,create=True),patch.object(ctypes,'get_last_error',return_value=87,create=True):
            self.assertEqual(windows_size(Terminal(),{'cols':56,'lines':30}),(56,30))
            self.assertEqual(calls,[('buffer',80,30),('window',56,30),('buffer',56,30)])
            kernel.SetConsoleWindowInfo=Function(lambda *args:0)
            with self.assertRaises(OSError):windows_size(Terminal(),{'cols':70})


if __name__=='__main__':unittest.main()
