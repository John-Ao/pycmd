"""BAT calls use interpreter frames, not the host Python recursion limit."""
import io
from pathlib import Path
import sys
import tempfile
import unittest
from pycmd import Runtime

class DeepCalls(unittest.TestCase):
    def test_expansion_limit_applies_to_each_block_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'block.bat'
            path.write_text('@echo off\n(\nset A=%X%\nset B=%X%\n)\necho OK\n')
            rt=Runtime(cwd=tmp,traceback=True)
            rt.state.env['X']='x'*5000
            self.assertEqual(rt.batch(path),0)
            self.assertEqual(rt.state.env['A'],'x'*5000)
            self.assertEqual(rt.state.env['B'],'x'*5000)
            self.assertEqual(rt.streams.table[2].getvalue(),b'')

    def test_expansion_limit_keeps_inserted_newlines_in_same_buffer(self):
        from pycmd.expansion import percent
        from pycmd.syntax import SyntaxFailure
        rt=Runtime()
        rt.state.env['X']='x'*8187
        with self.assertRaises(SyntaxFailure):
            percent('(\necho %X%\n)',rt.state,per_line=True)
        rt.state.env['X']='x'*4090+'\n'+'x'*4090
        with self.assertRaises(SyntaxFailure):
            percent('(\necho prefix %X%\n)',rt.state,per_line=True)

    def test_deep_return_restores_locals_handles_and_host_limit(self):
        limit=sys.getrecursionlimit()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'deep.bat'
            path.write_text('@echo off\nset MARK=outer\ncall :down 1500 >leaf.txt\necho RETURN=%errorlevel% MARK=%MARK%\nexit /b\n:down\nsetlocal\nset MARK=inner\nset /a N=%1\nif %N%==0 (echo LEAF&exit /b 7)\nset /a N-=1\ncall :down %N%\nexit /b\n')
            rt=Runtime(cwd=tmp,traceback=True,max_steps=100000)
            self.assertEqual(rt.batch(path),0)
            self.assertEqual((Path(tmp)/'leaf.txt').read_bytes(),b'LEAF\r\n')
            self.assertEqual(rt.streams.table[1].getvalue(),b'RETURN=7 MARK=outer\r\n')
            self.assertEqual(rt.streams.table[2].getvalue(),b'')
            self.assertEqual(rt.batch_frames,[]);self.assertEqual(rt.diagnostics.nodes,[])
            self.assertEqual(rt.state.locals,[]);self.assertFalse(rt.streams.owned)
        self.assertEqual(sys.getrecursionlimit(),limit)

    def test_deep_error_has_complete_bat_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'error.bat'
            path.write_text('@echo off\ncall :down 300\nexit /b\n:down\nset /a N=%1\nif %N%==0 (set /a 1/0&exit /b)\nset /a N-=1\ncall :down %N%\nexit /b\n')
            rt=Runtime(cwd=tmp,traceback=True);rt.batch(path)
            error=rt.streams.table[2].getvalue().decode()
            self.assertEqual(error.count('Traceback ('),1)
            self.assertEqual(error.count('in :down'),301)
            self.assertIn('line 6,',error)
            self.assertNotIn('RecursionError',error)
            self.assertEqual(rt.batch_frames,[])

    def test_deep_interrupt_unwinds_suspended_contexts(self):
        class InterruptedInput(io.BytesIO):
            def read(self,size=-1):raise KeyboardInterrupt()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'interrupt.bat'
            path.write_text('@echo off\ncall :down 300 >output.txt\nexit /b\n:down\nsetlocal\nset /a N=%1\nif %N%==0 set /p X=Wait:\nset /a N-=1\ncall :down %N%\nexit /b\n')
            rt=Runtime(cwd=tmp,stdin=InterruptedInput(),traceback=True)
            with self.assertRaises(KeyboardInterrupt):rt.batch(path)
            error=rt.streams.table[2].getvalue().decode()
            self.assertEqual(error.count('Traceback ('),1)
            self.assertEqual(error.count('in :down'),301)
            self.assertIn('KeyboardInterrupt',error)
            self.assertEqual(rt.batch_frames,[]);self.assertEqual(rt.diagnostics.nodes,[])
            self.assertEqual(rt.state.locals,[]);self.assertFalse(rt.streams.owned)
            self.assertNotIn('N',rt.state.env)
            rt.command('echo RESTORED')
            self.assertEqual(rt.streams.table[1].getvalue(),b'RESTORED\r\n')
