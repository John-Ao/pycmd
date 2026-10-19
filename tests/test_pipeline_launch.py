import tempfile
import threading
import unittest
import json
import hashlib
from pathlib import Path
from unittest.mock import patch
from pycmd import Runtime


class PipelineLaunchTests(unittest.TestCase):
    def test_native_launch_observations(self):
        cases=json.loads((Path(__file__).parent/'fixtures/native-pipeline-launch.json').read_text())
        for case in cases:
            with self.subTest(case=case['id']),tempfile.TemporaryDirectory() as tmp:
                for name,script in dict(case['fixtures'],**{'case.bat':case['script']}).items():
                    data=script.replace('\n','\r\n').encode('ascii')
                    expected=case['script_sha256'] if name=='case.bat' else case['fixture_sha256'][name]
                    self.assertEqual(hashlib.sha256(data).hexdigest(),expected)
                    (Path(tmp)/name).write_bytes(data)
                rt=Runtime(cwd=tmp,max_steps=50000)
                self.assertEqual(rt.batch(Path(tmp)/'case.bat'),case['returncode'])
                self.assertEqual(rt.streams.table[1].getvalue().hex(),case['stdout_hex'])
                self.assertEqual(rt.streams.table[2].getvalue().hex(),case['stderr_hex'])

    def observe_before_writer_body(self,outer):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'writer.bat').write_text('@echo off\necho BODY>signal.txt\n')
            (root/'observer.bat').write_text('@echo off\nif exist signal.txt echo EXISTS\nif not exist signal.txt echo MISSING\n')
            released=threading.Event();seen=[];original=Runtime.command
            def command(rt,text,*args,**kwargs):
                if text.strip().startswith('writer.bat'):
                    if not released.wait(3):raise AssertionError('Pipeline stages stopped running concurrently')
                elif text.strip().startswith('observer.bat'):
                    try:
                        seen.append((root/'signal.txt').exists())
                        return original(rt,text,*args,**kwargs)
                    finally:released.set()
                return original(rt,text,*args,**kwargs)
            rt=Runtime(cwd=tmp)
            # Observe while the left BAT has not executed a single instruction.
            with patch.object(Runtime,'command',command):
                result=original(rt,'writer.bat'+outer+' | observer.bat')
            self.assertEqual(result,0)
            self.assertEqual(rt.streams.table[2].getvalue(),b'')
            return seen,rt.streams.table[1].getvalue()

    def test_outer_redirection_precedes_next_launch(self):
        for redirection in (' >signal.txt',' 2>signal.txt'):
            with self.subTest(redirection=redirection):
                self.assertEqual(self.observe_before_writer_body(redirection),([True],b'EXISTS\r\n'))

    def test_body_redirection_is_not_preopened(self):
        self.assertEqual(self.observe_before_writer_body(''),([False],b'MISSING\r\n'))

    def test_failed_launch_closes_pipe(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'writer.bat').write_text('@echo SHOULD_NOT_RUN\n')
            rt=Runtime(cwd=tmp)
            rt.command('writer.bat >missing/file.txt | more')
            self.assertNotIn(b'SHOULD_NOT_RUN',rt.streams.table[1].getvalue())
            self.assertIn(b'cannot find',rt.streams.table[2].getvalue())
            self.assertFalse(rt.streams.owned)
