"""Behavioral tests of the executable core; native fixtures remain the final oracle."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from pycmd import Runtime,Environment
from pycmd.replay import ROOT,SMOKE,run_case
from pycmd.syntax import crt_split,batch_split

class CoreTests(unittest.TestCase):
    def run_script(self,text,env=None,delayed=False):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'main.bat';path.write_bytes(('@echo off\r\n'+text.replace('\n','\r\n')).encode('ascii'))
            r=Runtime(env=env,cwd=tmp,delayed=delayed);code=r.batch(path)
            return r,code,r.streams.table[1].getvalue(),r.streams.table[2].getvalue()
    def test_environment_case_insensitivity_preserves_value(self):
        e=Environment({'Mixed':'first'});e['MIXED']='second'
        self.assertEqual(len(e),1);self.assertEqual(e['mixed'],'second')
    def test_percent_block_snapshot_and_delayed_runtime_value(self):
        r,code,out,err=self.run_script('set X=old\n(\nset X=new\necho %X% !X!\n)\n',delayed=True)
        self.assertEqual(out,b'old new\r\n');self.assertEqual(code,0);self.assertEqual(err,b'')
    def test_inserted_delayed_value_is_not_rescanned_as_syntax(self):
        r,code,out,err=self.run_script('echo !VALUE!\n',{'VALUE':'A&echo BAD!X!','X':'CHANGED'},True)
        self.assertEqual(out,b'A&echo BAD!X!\r\n');self.assertEqual(err,b'')
    def test_call_trailing_space_and_hidden_exit_independent(self):
        r,_,out,_=self.run_script('(call)\necho %errorlevel%\n(call )\necho %errorlevel%\n')
        self.assertEqual(out,b'1\r\n0\r\n');self.assertEqual(r.state.external_code,0)
    def test_call_second_percent_expansion(self):
        _,_,out,err=self.run_script('set X=VALUE\ncall echo %%X%%\n')
        self.assertEqual(out,b'VALUE\r\n');self.assertEqual(err,b'')
    def test_status_shadow_does_not_change_if_errorlevel(self):
        r=Runtime(env={'ERRORLEVEL':'shadow'});r.state.errorlevel=7
        r.command('echo %errorlevel% & if errorlevel 7 echo YES')
        self.assertEqual(r.streams.table[1].getvalue(),b'shadow \r\nYES\r\n')
        self.assertEqual(r.state.errorlevel,7)
    def test_endlocal_export_and_directory_scope(self):
        r,_,out,err=self.run_script('set X=outer\nsetlocal\nset X=inner\nendlocal & set OUT=%X%\necho %X% %OUT%\n')
        self.assertEqual(out,b'outer inner\r\n');self.assertFalse(r.state.locals)
    def test_for_shadow_restores_outer_variable(self):
        _,_,out,err=self.run_script('for %%A in (outer) do (\necho %%A\nfor %%A in (inner) do echo %%A\necho %%A\n)\n')
        self.assertEqual(out,b'outer\r\ninner\r\nouter\r\n');self.assertEqual(err,b'')
    def test_finite_for_l_and_budget(self):
        _,_,out,err=self.run_script('for /l %%N in (3,-1,1) do echo %%N\n')
        self.assertEqual(out,b'3\r\n2\r\n1\r\n')
        r=Runtime(max_steps=4);r.command('for /l %N in (1,1,100) do echo %N')
        self.assertIn('Execution step budget exhausted',r.state.unsupported)
    def test_redirection_duplicate_target_does_not_create_old_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=Runtime(cwd=tmp);r.command('echo X >one.txt >two.txt')
            self.assertFalse((Path(tmp)/'one.txt').exists())
            self.assertEqual((Path(tmp)/'two.txt').read_bytes(),b'X  \r\n')
            r.command('echo AFTER');self.assertEqual(r.streams.table[1].getvalue(),b'AFTER\r\n')
    def test_high_handle_collision_persists_after_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=Runtime(cwd=tmp);r.command('echo X 1>a.txt 3>b.txt');r.command('echo AFTER')
            r.streams.close_owned()
            self.assertFalse(r.state.unsupported)
            self.assertEqual((Path(tmp)/'a.txt').read_bytes(),b'X \r\n')
            self.assertEqual((Path(tmp)/'b.txt').read_bytes(),b'AFTER\r\n')
    def test_pipe_child_environment_is_isolated(self):
        r=Runtime(env={'X':'original'})
        self.assertEqual(r.command('set X=child | echo %X%'),0)
        self.assertEqual(r.state.env['X'],'original')
        self.assertEqual(r.streams.table[1].getvalue(),b'original\r\n')
    def test_file_copy_and_type_preserve_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);data=b'\x00\xffA\r\n';(p/'source').write_bytes(data)
            r=Runtime(cwd=p);r.command('copy source target');r.command('type target')
            self.assertEqual((p/'target').read_bytes(),data)
            self.assertTrue(r.streams.table[1].getvalue().endswith(data))
    def test_call_label_return_and_case_insensitive_jump(self):
        _,_,out,err=self.run_script('call :sub\necho AFTER\ngoto END\n:Sub\necho CHILD\nexit /b 7\n:end\necho DONE\n')
        self.assertEqual(out,b'CHILD\r\nAFTER\r\nDONE\r\n');self.assertEqual(err,b'')
    def test_deleted_batch_finishes_parsed_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'case.bat';p.write_bytes(b'@echo off\r\n(del case.bat\r\necho BLOCK)\r\necho NEXT\r\n')
            r=Runtime(cwd=tmp);code=r.batch(p)
            self.assertEqual(r.streams.table[1].getvalue(),b'BLOCK\r\n');self.assertEqual(code,1)
    def test_batch_vs_crt_arguments(self):
        self.assertEqual(batch_split('a,b;c=d "e f"'),['a','b','c','d','"e f"'])
        self.assertEqual(crt_split('a,b;c=d "e f"'),['a,b;c=d','e f'])
    def test_external_process_requires_explicit_transport(self):
        r=Runtime();self.assertEqual(r.command('anything.exe'),125)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'child.py').write_text('raise SystemExit(65)')
            with (p/'in').open('w+b') as inp,(p/'out').open('w+b') as out,(p/'err').open('w+b') as err:
                r=Runtime(env=os.environ,cwd=p,stdin=inp,stdout=out,stderr=err,allow_external=True)
                self.assertEqual(r.command('"'+sys.executable+'" child.py'),65)
                self.assertEqual(r.state.external_code,65);self.assertEqual(r.state.errorlevel,65)
    def test_cli_module_entry(self):
        p=subprocess.run([sys.executable,'-m','pycmd','-c','echo READY'],capture_output=True)
        self.assertEqual(p.returncode,0);self.assertEqual(p.stdout,b'READY\r\n')

class NativeCoreReplayTests(unittest.TestCase):
    def test_reviewed_smoke_has_no_unexplained_mismatches(self):
        fixture=ROOT/'tests/fixtures/round1'
        cases={c['id']:c for c in json.loads((fixture/'cases.json').read_text())['cases']}
        expected=json.loads((ROOT/'tests/expected/round1.json').read_text())['observations']
        rows=[run_case(cases[e['id']],e['profile'],e,fixture) for e in expected if e['id'] in SMOKE]
        self.assertEqual(sum(r['status']=='pass' for r in rows),121)
        self.assertEqual(sum(r['status']=='unsupported' for r in rows),0)
        self.assertFalse([r for r in rows if r['status']=='mismatch'])

if __name__=='__main__':unittest.main()
