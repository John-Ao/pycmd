import json
from pathlib import Path
import tempfile
import unittest
from pycmd import Runtime

class PipeConditions(unittest.TestCase):
    def test_native_if_failures(self):
        base=Path(__file__).resolve().parents[1]/'tests/fixtures/pipe-conditions'
        cases=json.loads((base/'cases.json').read_text())
        native={r['id']:r for r in json.loads((base/'native-results.json').read_text())['results']}
        for case in cases:
            if not case['id'].startswith('if_'):continue
            with self.subTest(case=case['id']),tempfile.TemporaryDirectory() as tmp:
                (Path(tmp)/'case.bat').write_text(case['script'])
                rt=Runtime(cwd=tmp);self.assertEqual(rt.batch(Path(tmp)/'case.bat'),native[case['id']]['returncode'])
                self.assertEqual(rt.streams.table[1].getvalue().hex(),native[case['id']]['stdout_hex'])
                bad='echo' if case['id']=='if_simple' else '('
                self.assertEqual(rt.streams.table[2].getvalue(),(bad+' was unexpected at this time.\r\n').encode())

    def test_delayed_introduction_and_escaped_keyword(self):
        for command in ('echo input | if^ exist NUL echo OK',
                        'echo input | %condition%'):
            rt=Runtime(env={'condition':'if exist NUL echo OK'})
            # command() would expand %condition% in the parent; execute the
            # parsed node directly to model an intentionally deferred percent.
            from pycmd.syntax import parse
            rt.execute(parse(command))
            self.assertEqual(rt.streams.table[1].getvalue(),b'OK\r\n')
            self.assertEqual(rt.streams.table[2].getvalue(),b'')
        rt=Runtime();rt.command('echo input | if 1==1 echo OK')
        self.assertEqual(rt.streams.table[1].getvalue(),b'OK\r\n')

    def test_concatenation_can_produce_valid_condition(self):
        rt=Runtime();rt.command('echo input | if defined 1 geq 1 echo OK')
        self.assertEqual(rt.streams.table[1].getvalue(),b'OK\r\n')
        self.assertEqual(rt.streams.table[2].getvalue(),b'')
