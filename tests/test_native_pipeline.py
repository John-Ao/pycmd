import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from pycmd import Runtime

class NativePipeline(unittest.TestCase):
    def test_windows_redirect_reconstruction(self):
        cases=json.loads((Path(__file__).parent/'fixtures/native-pipeline.json').read_text())
        for case in cases:
            with self.subTest(case=case['id']),tempfile.TemporaryDirectory() as tmp:
                data=case['script'].replace('\n','\r\n').encode('ascii')
                self.assertEqual(hashlib.sha256(data).hexdigest(),case['script_sha256'])
                path=Path(tmp)/'case.bat';path.write_bytes(data)
                rt=Runtime(cwd=tmp,max_steps=5000)
                self.assertEqual(rt.batch(path),case['returncode'])
                self.assertEqual(rt.streams.table[1].getvalue().hex(),case['stdout_hex'])
                self.assertEqual(rt.streams.table[2].getvalue().hex(),case['stderr_hex'])
