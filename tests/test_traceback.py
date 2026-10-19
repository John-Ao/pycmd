"""Optional source diagnostics must not change CMD state or ordinary output."""
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from pycmd import Runtime

class TracebackTests(unittest.TestCase):
    def test_call_stack_and_block_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'main.bat').write_text('@echo off\ncall child.bat\nexit /b\n')
            (root/'child.bat').write_text('@echo off\ncall :work\nexit /b\n:work\n(\necho BEFORE\nset /a 1/0\n)\nexit /b\n')
            rt=Runtime(cwd=root,traceback=True);rt.batch(root/'main.bat')
            error=rt.streams.table[2].getvalue().decode()
            self.assertEqual(error.count('Traceback ('),1)
            self.assertIn('main.bat", line 2, in <batch>',error)
            self.assertIn('child.bat", line 2, in <batch>',error)
            self.assertIn('child.bat", line 7, in :work',error)
            self.assertIn('    set /a 1/0',error)
            self.assertEqual(rt.streams.table[1].getvalue(),b'BEFORE\r\n')

    def test_duplicate_commands_have_distinct_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'repeat.bat'
            path.write_text('@echo off\n(\nset /a 1/0\nset /a 1/0\n)\n')
            rt=Runtime(traceback=True);rt.batch(path)
            error=rt.streams.table[2].getvalue().decode()
            self.assertEqual(error.count('Traceback ('),2)
            self.assertIn('line 3,',error);self.assertIn('line 4,',error)

    def test_reused_syntax_keeps_parent_specific_source_locations(self):
        from pycmd.syntax import parse
        first='echo FIRST\nset /a 1/0'
        node=parse(first)
        # Reuse the failing command under a different parent before execution.
        parse('echo SECOND\n\n\nset /a 1/0')
        rt=Runtime(traceback=True);rt.trace_command=first;rt.execute(node)
        error=rt.streams.table[2].getvalue().decode()
        self.assertIn('line 2, in command',error)
        self.assertEqual(error.count('Traceback ('),1)

    def test_cached_parse_failure_uses_current_batch_stack(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('first.bat','second.bat'):
                path=Path(tmp)/name;path.write_text('@echo off\nif\n')
                rt=Runtime(traceback=True);rt.batch(path)
                error=rt.streams.table[2].getvalue().decode()
                self.assertIn(name+'", line 2,',error)
                self.assertEqual(error.count('Traceback ('),1)
                if name=='second.bat':self.assertNotIn('first.bat',error)

    def test_syntax_error_and_missing_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bad.bat'
            for script,needle in [('@echo off\nif\n','line 2,'),('@echo off\n(\n','line 2,'),
                                  ('@echo off\ncall :missing\n','call :missing')]:
                with self.subTest(script=script):
                    path.write_text(script);rt=Runtime(traceback=True);rt.batch(path)
                    error=rt.streams.table[2].getvalue().decode()
                    self.assertEqual(error.count('Traceback ('),1)
                    self.assertIn(needle,error)

    def test_disabled_mode_and_state_are_unchanged(self):
        results=[]
        for enabled in (False,True):
            rt=Runtime(traceback=enabled)
            code=rt.command('set /a 1/0 & echo AFTER')
            results.append((code,rt.state.errorlevel,rt.streams.table[1].getvalue()))
            error=rt.streams.table[2].getvalue()
            self.assertEqual(b'Traceback (' in error,enabled)
        self.assertEqual(results[0],results[1])

    def test_unknown_external_and_redirection_failure(self):
        for command in ('missing.exe','echo X < definitely-missing-input.txt'):
            with self.subTest(command=command):
                rt=Runtime(traceback=True);rt.command(command)
                error=rt.streams.table[2].getvalue().decode()
                self.assertEqual(error.count('Traceback ('),1)
                self.assertIn(command,error)

    def test_child_cmd_and_pipeline_inherit_stack(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'child.bat'
            for command in ('cmd /c set /a 1/0','echo off | set /a 1/0'):
                with self.subTest(command=command):
                    path.write_text('@echo off\n'+command+'\n')
                    rt=Runtime(traceback=True);rt.batch(path)
                    error=rt.streams.table[2].getvalue().decode()
                    self.assertEqual(error.count('Traceback ('),1)
                    self.assertIn('child.bat", line 2,',error)
                    self.assertIn('File "<command>"',error)

    def test_for_f_no_records_is_not_an_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'load.bat'
            path.write_text('@echo off\nfor /f "tokens=1,2,3,4,5 delims= " %%d in (time.txt) do (\nset "%%dlose=%%e"\n)\n')
            for data in (b'',b'\r\n;comment\r\n',b'   \r\n'):
                (root/'time.txt').write_bytes(data)
                outcomes=[]
                for enabled in (False,True):
                    rt=Runtime(cwd=root,traceback=enabled)
                    code=rt.batch(path)
                    outcomes.append((code,rt.state.errorlevel,rt.streams.table[1].getvalue()))
                    self.assertEqual(rt.streams.table[2].getvalue(),b'')
                self.assertEqual(outcomes[0],outcomes[1])
                self.assertEqual(outcomes[1][0],1)
            (root/'time.txt').unlink()
            rt=Runtime(cwd=root,traceback=True);rt.batch(path)
            self.assertIn(b'Traceback (',rt.streams.table[2].getvalue())
            (root/'time.txt').write_text('a1 5 25 61 no\n')
            path.write_text('@echo off\nfor /f %%d in (time.txt) do set /a 1/0\n')
            rt=Runtime(cwd=root,traceback=True);rt.batch(path)
            self.assertIn(b'Traceback (',rt.streams.table[2].getvalue())

    def test_empty_setp_preserves_value_and_status_without_traceback(self):
        for data in (b'',b'\r\n'):
            rt=Runtime(stdin=io.BytesIO(data),env={'X':'old'},traceback=True)
            self.assertEqual(rt.command('set /p X=Prompt:'),1)
            self.assertEqual(rt.state.errorlevel,1)
            self.assertEqual(rt.state.env['X'],'old')
            self.assertEqual(rt.streams.table[2].getvalue(),b'')
            rt.command('set /a 1/0')
            self.assertIn(b'Traceback (',rt.streams.table[2].getvalue())

    def test_nested_explicit_returns_do_not_report_inherited_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'returns.bat'
            for ending in ('exit /b','exit /b 7','goto :eof'):
                path.write_text('@echo off\nset /p X=\ncall :outer\nexit /b\n:outer\nfor /l %%i in (1,1,1) do (\ncall :inner\n)\n'+ending+'\n:inner\n'+ending+'\n')
                results=[]
                for enabled in (False,True):
                    rt=Runtime(stdin=io.BytesIO(b'\r\n'),traceback=enabled)
                    code=rt.batch(path)
                    results.append((code,rt.state.errorlevel,rt.streams.table[1].getvalue()))
                    self.assertEqual(rt.streams.table[2].getvalue(),b'')
                self.assertEqual(results[0],results[1])

    def test_success_does_not_build_expansion_line_maps(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'success.bat'
            path.write_text('@echo off\nset X=OK\ncall :work\nexit /b\n:work\n(\necho %X%\n)\nexit /b\n')
            rt=Runtime(traceback=True)
            with patch.object(rt.diagnostics,'map_unit',side_effect=AssertionError('eager map')):
                self.assertEqual(rt.batch(path),0)
            self.assertEqual(rt.streams.table[1].getvalue(),b'OK\r\n')
            self.assertEqual(rt.streams.table[2].getvalue(),b'')

    def test_deferred_source_uses_snapshot_before_self_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'rewrite.bat'
            path.write_text('@echo off\n(\necho replacement>"%~f0"\nset /a 1/0\n)\n')
            rt=Runtime(cwd=tmp,traceback=True);rt.batch(path)
            error=rt.streams.table[2].getvalue().decode()
            self.assertIn('rewrite.bat", line 4,',error)
            self.assertIn('    set /a 1/0',error)
            self.assertEqual(path.read_bytes(),b'replacement\r\n')

    def test_deferred_physical_lines_keep_nul_and_ctrl_z_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bytes.bat'
            # Ctrl-Z ends a BAT record but does not add a physical LF.
            path.write_bytes(b'@echo off\necho A\x1aset /a 1/0\n')
            rt=Runtime(traceback=True);rt.batch(path)
            self.assertIn(b'bytes.bat", line 2,',rt.streams.table[2].getvalue())
            # A NUL record consumes another physical line before returning.
            path.write_bytes(b'@echo off\necho A\0skip\r\nB\nset /a 1/0\n')
            rt=Runtime(traceback=True);rt.batch(path)
            self.assertIn(b'bytes.bat", line 4,',rt.streams.table[2].getvalue())

    def test_explicit_exit_is_not_an_exception(self):
        rt=Runtime(traceback=True)
        self.assertEqual(rt.command('exit /b 7'),7)
        self.assertEqual(rt.streams.table[2].getvalue(),b'')

    def test_continued_lines_keep_physical_error_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'continued.bat'
            path.write_text('@echo off\n(\necho one^\n two\nset /a 1/0\n)\n')
            rt=Runtime(traceback=True);rt.batch(path)
            error=rt.streams.table[2].getvalue().decode()
            self.assertIn('continued.bat", line 5,',error)
            self.assertIn('    set /a 1/0',error)

    def test_variable_inserted_newline_maps_to_original_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'expanded.bat'
            path.write_text('@echo off\n(\n%COMMANDS%\n)\n')
            rt=Runtime(traceback=True,env={'COMMANDS':'echo OK\nset /a 1/0'})
            rt.batch(path)
            error=rt.streams.table[2].getvalue().decode()
            self.assertIn('expanded.bat", line 3,',error)
            self.assertIn('    %COMMANDS%',error)

    def test_keyboard_interrupt_keeps_nested_batch_frames(self):
        class InterruptedInput(io.BytesIO):
            def read(self, size=-1):raise KeyboardInterrupt()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'interrupt.bat'
            path.write_text('@echo off\ncall :wait\nexit /b\n:wait\nset /p X=READY:\nexit /b\n')
            for enabled in (False,True):
                with self.subTest(enabled=enabled):
                    rt=Runtime(stdin=InterruptedInput(),traceback=enabled)
                    with self.assertRaises(KeyboardInterrupt) as caught:rt.batch(path)
                    # CLI fallback must not print the same interrupt a second time.
                    rt.diagnostics.interrupted(caught.exception)
                    error=rt.streams.table[2].getvalue().decode()
                    if enabled:
                        self.assertEqual(error.count('Traceback ('),1)
                        self.assertIn('interrupt.bat", line 2, in <batch>',error)
                        self.assertIn('interrupt.bat", line 5, in :wait',error)
                        self.assertIn('    set /p X=READY:',error)
                        self.assertTrue(error.endswith('KeyboardInterrupt\r\n'))
                    else:self.assertEqual(error,'')
                    self.assertEqual(rt.batch_frames,[])

    @unittest.skipUnless(sys.platform != 'win32', 'POSIX SIGINT integration')
    def test_cli_sigint_traceback_and_exit_status(self):
        import os
        import select
        import signal
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'interrupt.bat'
            path.write_text('@echo off\ncall :wait\nexit /b\n:wait\nset /p X=READY:\n')
            for enabled in (False,True):
                with self.subTest(enabled=enabled):
                    args=[sys.executable,'-m','pycmd','--batch',str(path)]
                    if enabled:args.append('--traceback')
                    child=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                    try:
                        ready,_,_=select.select([child.stdout],[],[],10)
                        self.assertTrue(ready)
                        self.assertEqual(os.read(child.stdout.fileno(),6),b'READY:')
                        child.send_signal(signal.SIGINT)
                        _,error=child.communicate(timeout=10)
                        self.assertEqual(child.returncode,0xc000013a & 255)
                        self.assertEqual(error.count(b'Traceback ('),int(enabled))
                        if enabled:
                            self.assertIn(b'line 5, in :wait',error)
                            self.assertIn(b'KeyboardInterrupt',error)
                    finally:
                        if child.poll() is None:child.kill()
                        child.communicate()

    def test_cli_switch(self):
        result=subprocess.run([sys.executable,'-m','pycmd','--traceback','-c','set /a 1/0'],capture_output=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'Traceback (most recent call last):',result.stderr)
        self.assertIn(b'File "<command>", line 1',result.stderr)

if __name__=='__main__':unittest.main()
