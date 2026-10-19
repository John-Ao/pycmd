import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from pycmd import Runtime


class Terminal(io.BytesIO):
    def isatty(self):return True


class TitleTests(unittest.TestCase):
    def test_windows_uses_unicode_console_api(self):
        from unittest.mock import Mock
        kernel=Mock();rt=Runtime(stdout=Terminal())
        with patch('pycmd.console_title.os.name','nt'),patch('ctypes.WinDLL',return_value=kernel,create=True):
            rt.command('title 计算器')
        kernel.SetConsoleTitleW.assert_called_once_with('计算器')
        self.assertEqual(rt.streams.table[1].getvalue(),b'')

    def test_title_updates_terminal_with_utf8_preserving_errorlevel(self):
        out=Terminal();rt=Runtime(stdout=out);rt.state.errorlevel=17
        rt.state.unicode_output=True
        with patch('pycmd.console_title.os.name','posix'):
            self.assertEqual(rt.command('title 计算器'),0)
        self.assertEqual(rt.state.title,'计算器')
        self.assertEqual(rt.state.errorlevel,17)
        self.assertEqual(out.getvalue(),'\x1b]0;计算器\x07'.encode())

    def test_redirection_does_not_capture_control_sequence(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Terminal();rt=Runtime(cwd=folder,stdout=out)
            with patch('pycmd.console_title.os.name','posix'):
                rt.command('title Test>title.txt')
                rt.command('title Next>nul')
            self.assertEqual(Path(folder,'title.txt').read_bytes(),b'')
            self.assertEqual(out.getvalue(),b'\x1b]0;Test\x07\x1b]0;Next\x07')

    def test_headless_and_control_characters(self):
        rt=Runtime()
        with patch('builtins.open') as opened:rt.command('title Test')
        opened.assert_not_called()
        self.assertEqual(rt.streams.table[1].getvalue(),b'')
        out=Terminal();rt=Runtime(stdout=out)
        from pycmd.console_title import update
        with patch('pycmd.console_title.os.name','posix'):update(rt,'a\x07b\x1bc\n\x9cd')
        self.assertEqual(out.getvalue(),b'\x1b]0;abcd\x07')

    @unittest.skipUnless(os.name=='posix','POSIX PTY')
    def test_real_pty_receives_title(self):
        import pty
        master,slave=pty.openpty()
        try:
            with os.fdopen(os.dup(slave),'wb',buffering=0) as output:
                rt=Runtime(stdout=output)
                rt.command('title Terminal check')
                self.assertEqual(os.read(master,1024),b'\x1b]0;Terminal check\x07')
        finally:os.close(master);os.close(slave)

    def test_terminal_write_failure_preserves_command_semantics(self):
        class Broken(Terminal):
            def write(self,data):raise OSError('closed terminal')
        rt=Runtime(stdout=Broken());rt.state.errorlevel=7
        with patch('pycmd.console_title.os.name','posix'):self.assertEqual(rt.command('title Test'),0)
        self.assertEqual(rt.state.errorlevel,7)


if __name__=='__main__':unittest.main()
