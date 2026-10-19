import io
from pathlib import Path
import tempfile
import unittest
from pycmd import Runtime

class TextToolTests(unittest.TestCase):
    def command(self,text,data=b'',traceback=True,env=None):
        rt=Runtime(env=env or {'PATH':'unused'},stdin=io.BytesIO(data),traceback=traceback)
        code=rt.command(text)
        return code,rt.streams.table[1].getvalue(),rt.streams.table[2].getvalue()

    def test_multiple_literal_queries_and_anchors(self):
        data=b'Columns: 80\r\nLines: 25\r\nOther: 1\r\nxColumns: 12\r\n'
        self.assertEqual(self.command('findstr /b /C:"Columns" /C:"Lines"',data),
                         (0,b'Columns: 80\r\nLines: 25\r\n',b''))
        self.assertEqual(self.command('findstr /i /x /c:"a.b"',b'A.B\naxb\nza.b\n'),(0,b'A.B\r\n',b''))
        self.assertEqual(self.command('findstr /e /c:"a.b"',b'za.b\na.bc\n'),(0,b'za.b\r\n',b''))
        self.assertEqual(self.command('findstr /r /c:"a.b"',b'axb\n'),(0,b'axb\r\n',b''))

    def test_query_false_is_data_but_actual_errors_are_diagnosed(self):
        for command in ('find "z"','findstr /c:"z"','echo abc|find "z"'):
            with self.subTest(command=command):
                code,out,err=self.command(command,b'abc\n');self.assertEqual(code,1);self.assertEqual(err,b'')
        code,out,err=self.command('find "x" missing-file.txt')
        self.assertEqual(code,2);self.assertIn(b'Traceback',err)
        code,out,err=self.command('set /a 1/0');self.assertIn(b'Traceback',err)

    def test_wmic_readonly_virtual_profile(self):
        self.assertEqual(self.command('wmic os get Version,OSLanguage /value'),
                         (0,b'\r\nOSLanguage=1033\r\nVersion=10.0.19045\r\n\r\n',b''))
        self.assertEqual(self.command('wmic OS GET Version /VALUE',env={'PATH':'unused','PYCMD_OS_VERSION':'10.0.19044'})[1],
                         b'\r\nVersion=10.0.19044\r\n\r\n')
        for cmd in ('wmic process call create x','wmic os get Caption /value'):
            self.assertEqual(self.command(cmd)[0],125)

    def test_goto_into_block_and_single_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'jump.bat'
            p.write_text('@echo off\ngoto inside\nif 1==0 (\necho BAD\n:inside\necho INSIDE\n)\necho AFTER\n')
            rt=Runtime(traceback=True);self.assertEqual(rt.batch(p),0)
            self.assertEqual(rt.streams.table[1].getvalue(),b'INSIDE\r\nAFTER\r\n')
            self.assertEqual(rt.streams.table[2].getvalue(),b'')
        self.assertNotEqual(self.command(')echo BAD')[0],0)

if __name__=='__main__':unittest.main()
