"""Application-independent input, recursion and time arithmetic regressions."""
from datetime import datetime
import io
from pathlib import Path
import tempfile
import unittest

from pycmd import Runtime


class SyntheticSessions(unittest.TestCase):
    def run_script(self, script, data=b'', traceback=False, clock=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'session.bat'
            path.write_bytes(script.replace('\n', '\r\n').encode('ascii'))
            runtime = Runtime(cwd=tmp, stdin=io.BytesIO(data), traceback=traceback,
                              max_steps=10000)
            if clock is not None:
                runtime.state.clock = clock
            status = runtime.batch(path)
            return status, runtime.streams.table[1].getvalue(), runtime.streams.table[2].getvalue()

    def test_input_loop_empty_lines_and_traceback_parity(self):
        script = '''@echo off
setlocal enabledelayedexpansion
for /l %%I in (1,1,3) do (
set "EXPR=0"
set /p EXPR=
set /a "RESULT=!EXPR!" >nul
echo !RESULT!
)
'''
        for enabled in (False, True):
            with self.subTest(traceback=enabled):
                self.assertEqual(self.run_script(script, b'\r\n\r\n1+1\r\n', enabled),
                                 (0, b'0\r\n0\r\n2\r\n', b''))

    def test_arithmetic_precedence_in_batch_session(self):
        script = '''@echo off
set /a "A=1+1,B=2*3,C=(1+2)*3" >nul
echo %A% %B% %C%
'''
        self.assertEqual(self.run_script(script), (0, b'2 6 9\r\n', b''))

    def test_recursive_call_base_case_and_unwinding(self):
        script = '''@echo off
set N=5
set RESULT=1
call :product
echo %N% %RESULT%
exit /b 0
:product
if %N% equ 0 exit /b 0
set /a RESULT*=N,N-=1 >nul
call :product
exit /b 0
'''
        self.assertEqual(self.run_script(script), (0, b'0 120\r\n', b''))

    def test_time_substrings_are_safe_for_morning_arithmetic(self):
        script = '''@echo off
set "T=%TIME: =0%"
set /a "H=1%T:~0,2%-100,M=1%T:~3,2%-100,S=1%T:~6,2%-100" >nul
echo %H% %M% %S%
'''
        for hour in (0, 8, 9, 10, 23):
            with self.subTest(hour=hour):
                self.assertEqual(self.run_script(script, clock=datetime(2020, 1, 1, hour, 1, 26)),
                                 (0, f'{hour} 1 26\r\n'.encode(), b''))

    def test_elapsed_centiseconds_wrap_at_midnight(self):
        script = '''@echo off
setlocal enabledelayedexpansion
set "T=%START: =0%"
set /a "A=(1!T:~0,2!-100)*360000+(1!T:~3,2!-100)*6000+(1!T:~6,2!-100)*100+(1!T:~9,2!-100)" >nul
set "T=%END: =0%"
set /a "B=(1!T:~0,2!-100)*360000+(1!T:~3,2!-100)*6000+(1!T:~6,2!-100)*100+(1!T:~9,2!-100)" >nul
set /a "ELAPSED=(B-A+8640000)%%8640000" >nul
echo !ELAPSED!
'''
        for start, end in [(' 8:59:59.90', ' 9:00:00.10'),
                           (' 9:59:59.90', '10:00:00.10'),
                           ('23:59:59.90', ' 0:00:00.10')]:
            with self.subTest(start=start):
                prefix = f'@set "START={start}"\n@set "END={end}"\n'
                self.assertEqual(self.run_script(prefix + script), (0, b'20\r\n', b''))
