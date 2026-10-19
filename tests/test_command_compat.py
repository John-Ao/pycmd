import io
import json
from pathlib import Path
import tempfile
import unittest
from pycmd import Runtime
from pycmd.console_mode import dimensions
ROOT=Path(__file__).resolve().parents[1]

class CommandCompatibility(unittest.TestCase):
    def test_minimized_conditions(self):
        for case in json.loads((ROOT/'tests/fixtures/conditions.json').read_text()):
            with self.subTest(case=case['id']),tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp)/'case.bat';p.write_bytes(case['script'].replace('\n','\r\n').encode())
                rt=Runtime(cwd=tmp);self.assertEqual(rt.batch(p),0)
                self.assertEqual(rt.streams.table[1].getvalue(),case['expected'].encode())
                self.assertEqual(rt.streams.table[2].getvalue(),b'')
    def test_mode_short_form(self):
        for value in ('40,20','40, 20','con: 40,20'):
            self.assertEqual(dimensions(value),{'cols':40,'lines':20})
        for value in ('0,20','40,-1','40,20,30'):
            with self.assertRaises(ValueError):dimensions(value)
    def test_choice_returns_index_not_failure(self):
        rt=Runtime(stdin=io.BytesIO(b'?b'),traceback=True)
        self.assertEqual(rt.command('choice /c ABC /n'),2)
        self.assertEqual(rt.state.errorlevel,2);self.assertEqual(rt.streams.table[2].getvalue(),b'')
        self.assertEqual(rt.command('choice /c:yn /t 0 /d y'),1)
        self.assertEqual(rt.command('choice /c ab /t 0 /d x'),255)
        rt=Runtime(stdin=io.BytesIO(b'aA'))
        self.assertEqual(rt.command('choice /cs /c Aa /n'),2)
        self.assertEqual(rt.command('choice /cs /c Aa /n'),1)
    def test_copy_nul_and_prompt_without_variable(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt=Runtime(cwd=tmp,traceback=True)
            self.assertEqual(rt.command('copy nul empty.txt >nul'),0)
            self.assertEqual((Path(tmp)/'empty.txt').read_bytes(),b'')
            self.assertEqual(rt.command('<nul set /p "=hello"'),1)
            self.assertEqual(rt.streams.table[1].getvalue(),b'hello')
            self.assertEqual(rt.streams.table[2].getvalue(),b'')
    def test_xcopy_wait_capture_does_not_overwrite_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'a.txt';p.write_bytes(b'original')
            rt=Runtime(cwd=tmp,stdin=io.BytesIO(b'w'),traceback=True)
            self.assertEqual(rt.command('xcopy /w a.txt a.txt 2>nul'),4)
            self.assertEqual(p.read_bytes(),b'original')
            self.assertTrue(rt.streams.table[1].getvalue().endswith(b'w\r\n'))
            self.assertEqual(rt.command('xcopy a.txt b.txt /y /q'),0)
            self.assertEqual((Path(tmp)/'b.txt').read_bytes(),b'original')
            self.assertEqual(rt.command('xcopy a.txt . /y'),4)
            self.assertEqual(p.read_bytes(),b'original')
    def test_for_command_unescapes_redirect_before_child_parse(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt=Runtime(cwd=tmp)
            rt.command('for /f %a in (\'echo hello ^>captured.txt\') do echo WRONG')
            self.assertEqual((Path(tmp)/'captured.txt').read_bytes(),b'hello \r\n')
            self.assertEqual(rt.streams.table[1].getvalue(),b'')
