"""Live file semantics must survive reader and label-index optimizations."""
import io
import os
from pathlib import Path
import tempfile
import unittest
from pycmd import Runtime
from pycmd.readers import batch_line

class LiveReaderTests(unittest.TestCase):
    def test_records_preserve_offsets_and_special_bytes(self):
        cases=[
            (b'A\rB\r\nC\n',[(b'AB\n',5),(b'C\n',7),(b'',7)]),
            (b'A\x1aB\n',[(b'A\n',2),(b'B\n',4),(b'',4)]),
            (b'A\0skip\r\nB\nC\n',[(b'AB\n',10),(b'C\n',12),(b'',12)]),
            (b'\0ignored\nA\n',[(b'',11),(b'',11)]),
        ]
        for data,records in cases:
            with self.subTest(data=data):
                stream=io.BytesIO(data)
                for expected,offset in records:
                    self.assertEqual(batch_line(stream),expected)
                    self.assertEqual(stream.tell(),offset)

    def test_label_index_observes_same_size_rewrite_and_append(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'live.bat';data=b':old\necho ONE\n:old\necho TWO\n'
            path.write_bytes(data);rt=Runtime(cwd=tmp)
            first=data.index(b'echo ONE');second=data.index(b'echo TWO')
            self.assertEqual(rt.find_label(path,'OLD',0),first)
            self.assertEqual(rt.find_label(path,'old',first),second)
            self.assertEqual(rt.find_label(path,'old',second),first)
            stamp=path.stat()
            path.write_bytes(data.replace(b':old',b':new'))
            os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
            self.assertIsNone(rt.find_label(path,'old',0))
            self.assertEqual(rt.find_label(path,'new',0),first)
            with path.open('ab') as file:file.write(b':added\necho MORE\n')
            self.assertEqual(rt.find_label(path,'added',0),len(data)+len(b':added\n'))

    def test_label_index_uses_current_codepage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'encoded.bat';path.write_bytes(':测试\necho OK\n'.encode('utf-8'))
            rt=Runtime(codepage=65001)
            self.assertIsNotNone(rt.find_label(path,'测试',0))
            rt.state.encoding='cp437'
            self.assertIsNone(rt.find_label(path,'测试',0))
