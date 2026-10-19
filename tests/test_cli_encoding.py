import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from pycmd import Runtime

ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(os.name=='posix','POSIX CLI encoding')
class CliEncodingTests(unittest.TestCase):
    def terminal_run(self,path,flags=()):
        import pty
        master,slave=pty.openpty()
        try:
            process=subprocess.Popen([sys.executable,'-m','pycmd',*flags,'--batch',str(path)],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=slave,stderr=subprocess.PIPE)
            os.close(slave);slave=None
            output=bytearray()
            while True:
                try:data=os.read(master,4096)
                except OSError:break
                if not data:break
                output.extend(data)
            err=process.communicate(timeout=5)[1]
            self.assertEqual(process.returncode,0,err.decode(errors='replace'))
            return bytes(output)
        finally:
            if slave is not None:os.close(slave)
            os.close(master)
    def test_utf8_batch_title_and_xp_borders(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'mem.bat';path.write_text('@echo off\ntitle 记忆测试\necho ╔─╗\n',encoding='utf-8')
            for flags,expected in (((), '╔─╗'),(('--xp',),' ╔──═╗')):
                with self.subTest(flags=flags):
                    text=self.terminal_run(path,('--traceback',)+flags).decode('utf-8')
                    self.assertIn('\x1b]0;记忆测试\x07',text)
                    self.assertIn(expected,text);self.assertNotIn('Γ',text)
    def test_explicit_gbk_and_redirected_output(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'old.bat';target=Path(folder)/'saved.txt'
            script=f'@echo off\ntitle 中文标题\necho 中文─\necho 中文─>"{target}"\n'
            path.write_bytes(script.encode('cp936'))
            for flags in (('--codepage','936'),('--xp','--codepage','936')):
                text=self.terminal_run(path,flags).decode('utf-8')
                self.assertIn('\x1b]0;中文标题\x07',text);self.assertIn('中文',text)
                self.assertEqual(target.read_bytes(),'中文─\r\n'.encode('cp936'))
    def test_default_utf8_capture_and_explicit_437(self):
        for flags,encoding in (((),'utf-8'),(('--codepage','437'),'cp437')):
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'a.bat';path.write_bytes('@echo off\necho é\nchcp\n'.encode(encoding))
                result=subprocess.run([sys.executable,'-m','pycmd',*flags,'--batch',str(path)],cwd=ROOT,capture_output=True,timeout=5)
                self.assertEqual(result.returncode,0)
                self.assertIn(('é\r\n').encode(encoding),result.stdout)
                self.assertIn(b'65001' if not flags else b'437',result.stdout)
    def test_api_default_stays_437_and_child_inherits_page(self):
        self.assertEqual(Runtime().state.encoding,'cp437')
        rt=Runtime(codepage=936,terminal_unicode=True)
        child=rt.fork();self.assertEqual(child.state.encoding,'cp936');self.assertEqual(child.state.codepage,936)
        class Input(io.BytesIO):
            host_encoding='utf-8'
            def isatty(self):return True
        from pycmd.readers import setp
        self.assertEqual(setp(Input('中文\n'.encode()),'cp936'),'中文')

if __name__=='__main__':unittest.main()
