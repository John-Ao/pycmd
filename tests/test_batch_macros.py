import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from pycmd import Runtime


class NativeMacros(unittest.TestCase):
    def test_windows_observations(self):
        cases=json.loads((Path(__file__).parent/'fixtures/native-macros.json').read_text())
        for case in cases:
            with self.subTest(case=case['id']),tempfile.TemporaryDirectory() as tmp:
                script=case['script']
                if case.get('line_endings','crlf')=='crlf':script=script.replace('\n','\r\n')
                data=script.encode('ascii')
                self.assertEqual(hashlib.sha256(data).hexdigest(),case['script_sha256'])
                path=Path(tmp)/'case.bat';path.write_bytes(data)
                rt=Runtime(cwd=tmp,max_steps=5000)
                self.assertEqual(rt.batch(path),case['returncode'])
                self.assertEqual(rt.streams.table[1].getvalue().hex(),case['stdout_hex'])
                self.assertEqual(rt.streams.table[2].getvalue().hex(),case['stderr_hex'])
