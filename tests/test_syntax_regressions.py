"""Independent regressions for arithmetic, tokenization and interactive input."""
import io
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time
import unittest

from pycmd import Runtime

ROOT = Path(__file__).resolve().parents[1]

class SyntaxRegressions(unittest.TestCase):
    def test_compact_set_switches(self):
        rt = Runtime(stdin=io.BytesIO(b'answer\r\n'))
        rt.command('set/a "N=1+1"')
        rt.command('set/p X=Prompt:')
        self.assertEqual(rt.state.env['N'], '2')
        self.assertEqual(rt.state.env['X'], 'answer')
        self.assertFalse(rt.state.unsupported)

    def test_for_l_accepts_cmd_list_separators(self):
        for numbers in ('1 1 3', '1,1,3', '1;1;3', '1=1=3'):
            with self.subTest(numbers=numbers):
                rt = Runtime(); rt.state.echo = False
                rt.command('for /l %N in (' + numbers + ') do echo %N')
                self.assertEqual(rt.streams.table[1].getvalue(), b'1\r\n2\r\n3\r\n')

    def test_missing_for_end_is_zero(self):
        rt=Runtime();rt.state.echo=False
        rt.command('for /l %N in (1,1,) do echo BAD')
        self.assertEqual(rt.streams.table[1].getvalue(),b'')
        self.assertEqual(rt.streams.table[2].getvalue(),b'')

    def test_decimal_division_commits_integer_prefix(self):
        rt=Runtime();rt.state.echo=False
        rt.command('set /a "N=1.5/0.5"')
        self.assertEqual(rt.state.env['N'],'1')
        self.assertEqual(rt.state.errorlevel,1073750990)
        self.assertEqual(rt.streams.table[2].getvalue(),b'Missing operator.\r\n')

    def test_cls_redirected_form_feed(self):
        rt=Runtime();rt.command('cls')
        self.assertEqual(rt.streams.table[1].getvalue(),b'\x0c')

    def test_for_f_attached_star_captures_remainder(self):
        rt = Runtime(); rt.state.echo = False
        rt.command('for /f "tokens=1*" %A in ("one two three") do echo [%A][%B]')
        rt.command('for /f "tokens=1-2*" %A in ("one two three four") do echo [%A][%B][%C]')
        self.assertEqual(rt.streams.table[1].getvalue(),
                         b'[one][two three]\r\n[one][two][three four]\r\n')


    def test_for_f_star_preserves_empty_remainder_of_nonempty_record(self):
        from pycmd.loops import ForOptions
        self.assertEqual(list(ForOptions('tokens=* delims=0').records(b'000\n0\n\n0012\n','ascii')),
                         [[''],[''],['12']])
        self.assertEqual(list(ForOptions('tokens=1 delims=0').records(b'000\n','ascii')),[])
        rt=Runtime();rt.state.echo=False;rt.state.for_values['A']='outer'
        rt.command('for /f "tokens=* delims=0" %A in ("000") do echo [%A]')
        self.assertEqual(rt.streams.table[1].getvalue(),b'[]\r\n')
        self.assertEqual(rt.state.for_values['A'],'outer')



    @unittest.skipUnless(os.name == 'posix', 'PTY integration uses POSIX terminals')
    def test_setp_returns_after_one_enter_without_eof(self):
        import pty
        master, slave = pty.openpty()
        process = None
        try:
            with tempfile.TemporaryDirectory() as tmp:
                script = Path(tmp)/'input.bat'
                script.write_bytes(b'@echo off\r\nset /p X=READY:\r\necho RESULT=[%X%]\r\nset /p Y=SECOND:\r\n')
                process = subprocess.Popen([sys.executable, '-m', 'pycmd', '--batch', str(script)],
                                           cwd=ROOT, stdin=slave, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE)
                os.close(slave); slave = None
                output = bytearray()
                def until(marker):
                    deadline = time.monotonic()+10
                    while marker not in output:
                        remaining = deadline-time.monotonic()
                        self.assertGreater(remaining, 0, bytes(output))
                        ready, _, _ = select.select([process.stdout], [], [], remaining)
                        self.assertTrue(ready, bytes(output))
                        chunk = os.read(process.stdout.fileno(), 4096)
                        self.assertTrue(chunk, bytes(output))
                        output.extend(chunk)
                until(b'READY:')
                os.write(master, b'1+1\n')
                until(b'RESULT=[1+1]\r\nSECOND:')
                # The terminal is still open: the first read did not wait for EOF.
                self.assertIsNone(process.poll())
                os.write(master, b'done\n')
                _, errors = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0)
                self.assertEqual(errors, b'')
        finally:
            if process is not None:
                if process.poll() is None:process.kill()
                process.communicate()
            os.close(master)
            if slave is not None:os.close(slave)

if __name__ == '__main__':unittest.main()
