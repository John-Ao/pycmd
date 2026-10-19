"""Cross-component regressions beyond the frozen native replay corpus."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from pycmd import Runtime
from pycmd.arithmetic import calculate,ArithmeticError
from pycmd.state import Environment

class RuntimeFeatures(unittest.TestCase):
    def test_reused_if_branches_read_live_condition_and_values(self):
        rt=Runtime(delayed=True);rt.state.echo=False
        command='if "!FLAG!"=="1" (echo TRUE !VALUE!) else (echo FALSE !VALUE!)'
        for flag,value in [('1','first'),('0','second'),('1','third')]:
            rt.state.env['FLAG']=flag;rt.state.env['VALUE']=value
            self.assertEqual(rt.command(command),0)
        self.assertEqual(rt.streams.table[1].getvalue(),b'TRUE first\r\nFALSE second\r\nTRUE third\r\n')
        self.assertEqual(rt.streams.table[2].getvalue(),b'')

    def test_nested_environment_snapshots_preserve_values_and_spelling(self):
        rt=Runtime(env={f'Value{i}':str(i) for i in range(1000)})
        rt.state.env['Mixed']='outer'
        rt.state.begin_local();rt.state.env['mixed']='inner'
        rt.state.begin_local();rt.state.env['MIXED']='deep'
        del rt.state.env['value999'];rt.state.env['temporary']='yes'
        rt.state.end_local()
        self.assertEqual(rt.state.env['mixed'],'inner')
        self.assertEqual(rt.state.env['VALUE999'],'999')
        self.assertIn('mixed',list(rt.state.env))
        self.assertNotIn('temporary',rt.state.env)
        rt.state.end_local()
        self.assertEqual(rt.state.env['mixed'],'outer')
        self.assertIn('Mixed',list(rt.state.env))
        self.assertEqual(rt.state.env.get('value999'),'999')
        self.assertEqual(rt.state.env.get('missing','fallback'),'fallback')
        self.assertEqual(len(rt.state.env),1001)

    def test_echo_comma_is_internal_and_preserves_text(self):
        for command,expected in [('echo,',b'\r\n'),('ECHO,hello',b'hello\r\n'),
                                 ('echo,  hello,',b'  hello,\r\n'),('echo,on',b'on\r\n')]:
            with self.subTest(command=command):
                rt=Runtime();rt.state.echo=False;rt.state.errorlevel=7
                self.assertEqual(rt.command(command),0)
                self.assertEqual(rt.streams.table[1].getvalue(),expected)
                self.assertEqual(rt.streams.table[2].getvalue(),b'')
                self.assertFalse(rt.state.unsupported)
                self.assertFalse(rt.state.echo)
                self.assertEqual(rt.state.errorlevel,7)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);script=root/'comma.bat'
            script.write_bytes(b'@echo off\r\necho,>out.txt\r\n(echo,\r\necho,DONE)\r\n')
            rt=Runtime(cwd=root);self.assertEqual(rt.batch(script),0)
            self.assertEqual((root/'out.txt').read_bytes(),b'\r\n')
            self.assertEqual(rt.streams.table[1].getvalue(),b'\r\nDONE\r\n')
            self.assertFalse(rt.state.unsupported)

    def test_pipe_exceeds_kernel_buffer_and_uses_real_processes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'produce.py').write_text('import sys\nsys.stdout.buffer.write(b"x"*262144)\n')
            (root/'consume.py').write_text('import sys\nprint(len(sys.stdin.buffer.read()))\n')
            rt=Runtime(cwd=root,allow_external=True,python_adapter=True)
            code=rt.command(f'"{sys.executable}" produce.py | "{sys.executable}" consume.py')
            self.assertEqual(code,0)
            self.assertEqual(rt.streams.table[1].getvalue(),b'262144\r\n')
    def test_start_wait_has_separate_environment(self):
        rt=Runtime(env={'X':'parent'})
        rt.command('start "" /b /wait set X=child')
        self.assertEqual(rt.state.env['X'],'parent')
    def test_for_values_are_case_sensitive_and_not_recursive(self):
        rt=Runtime();rt.state.for_values={'A':'%B','B':'wrong','a':'lower'}
        rt.command('echo %A %a')
        self.assertEqual(rt.streams.table[1].getvalue(),b'%B lower\r\n')
    def test_path_parameter_search_and_components(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'bin').mkdir();(root/'bin'/'file.txt').write_text('DATA')
            (root/'case.bat').write_text('@echo off\necho %~$PATH:1\necho %~nx1\n')
            rt=Runtime(cwd=root,env={'PATH':str(root/'bin')})
            rt.batch(root/'case.bat',['file.txt'])
            self.assertEqual(rt.streams.table[1].getvalue(),(str(root/'bin'/'file.txt')+'\r\nfile.txt\r\n').encode())
    def test_help_is_static_package_data_not_test_dependency(self):
        rt=Runtime();rt.command('for /?')
        self.assertIn(b'FOR',rt.streams.table[1].getvalue())
        self.assertFalse(rt.state.unsupported)
    def test_interactive_reader_exit_does_not_consume_next_command(self):
        rt=Runtime(stdin=io.BytesIO(b'@echo off\necho READY\nexit 7\necho BAD\n'))
        self.assertEqual(rt.interactive(banner=False),7)
        self.assertNotIn(b'BAD',rt.streams.table[1].getvalue())
    def test_invalid_arithmetic_commits_completed_assignments(self):
        env=Environment({'N':'8'})
        with self.assertRaises(ArithmeticError):calculate('N=1==1',env)
        self.assertEqual(env['N'],'1')
    def test_case_insensitive_lookup_and_pathext(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'CHILD.BAT').write_text('@echo OK\n')
            rt=Runtime(cwd=root);rt.command('child')
            self.assertEqual(rt.streams.table[1].getvalue(),b'OK\r\n')

    def test_call_label_preserves_raw_arguments_and_script_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);script=root/'main.bat'
            script.write_text('@echo off\ncall :sub one "two words"\nexit /b\n:sub\necho %0 %1 %2 [%*]\necho %~f0\nexit /b 7\n')
            rt=Runtime(cwd=root);rt.batch(script)
            self.assertEqual(rt.streams.table[1].getvalue(),(':sub one "two words" [one "two words"]\r\n'+str(script)+'\r\n').encode())
    def test_leading_redirection_applies_to_entire_control_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt=Runtime(cwd=tmp);rt.state.echo=False
            rt.command('>out.txt for %A in (one two) do echo %A')
            rt.command('echo AFTER')
            self.assertEqual((Path(tmp)/'out.txt').read_bytes(),b'one\r\ntwo\r\n')
            self.assertEqual(rt.streams.table[1].getvalue(),b'AFTER\r\n')
    def test_for_recursive_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'one'/'two').mkdir(parents=True);(root/'file').touch()
            rt=Runtime(cwd=root);rt.state.echo=False;rt.command('for /d /r %D in (*) do echo %D')
            self.assertEqual(set(rt.streams.table[1].getvalue().decode().splitlines()),{str(root/'one'),str(root/'one'/'two')})
    def test_for_f_file_boundaries_reset_skip_and_do_not_join_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'a').write_bytes(b'header\nONE');(root/'b').write_bytes(b'header\nTWO')
            rt=Runtime(cwd=root);rt.state.echo=False;rt.command('for /f "skip=1" %A in (a b) do echo %A')
            self.assertEqual(rt.streams.table[1].getvalue(),b'ONE\r\nTWO\r\n')
    def test_cmd_c_attached_quote_and_k_exit(self):
        rt=Runtime();rt.command('cmd /c"echo OK"')
        self.assertEqual(rt.streams.table[1].getvalue(),b'OK\r\n')
        rt=Runtime(stdin=io.BytesIO(b'echo BAD\n'))
        self.assertEqual(rt.command('cmd /k exit 7'),7)
        self.assertNotIn(b'BAD',rt.streams.table[1].getvalue())

    def test_session_association_is_used_for_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'file.demo').touch()
            rt=Runtime(cwd=root)
            rt.command('assoc .demo=DemoType')
            rt.command('ftype DemoType=echo "%1" %*')
            rt.command('file.demo extra')
            self.assertEqual(rt.streams.table[1].getvalue(),('"'+str(root/'file.demo')+'" extra\r\n').encode())
    def test_explicit_session_autorun_can_be_disabled(self):
        rt=Runtime(autorun='set X=started')
        rt.command('cmd /c echo %X%')
        rt.command('cmd /d /c echo [%X%]')
        self.assertEqual(rt.streams.table[1].getvalue(),b'started\r\n[%X%]\r\n')
        self.assertNotIn('X',rt.state.env)

if __name__=='__main__':unittest.main()
