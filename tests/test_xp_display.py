import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from pycmd import Runtime
from pycmd.display_width import cell_width,legacy_wide,terminal_text

class Terminal(io.BytesIO):
    def isatty(self):return True

class XpDisplayTests(unittest.TestCase):
    def test_windows_measures_existing_width_before_padding(self):
        import ctypes
        from types import SimpleNamespace
        from pycmd.xp_terminal import XpOutput
        class NativeTerminal(Terminal):
            def fileno(self):return 42
        class Function:
            def __init__(self,fn):self.fn=fn
            def __call__(self,*args):return self.fn(*args)
        for width in (1,2):
            position=[0];sent=[]
            def write(handle,text,length,count,reserved):
                sent.append(text);position[0]+=len(text)*width;count._obj.value=length;return 1
            def info(handle,pointer):
                pointer._obj.size.X=80;pointer._obj.cursor.X=position[0];return 1
            def move(handle,coord):position[0]=coord.X;return 1
            kernel=SimpleNamespace(WriteConsoleW=Function(write),GetConsoleScreenBufferInfo=Function(info),SetConsoleCursorPosition=Function(move))
            adapter=XpOutput(NativeTerminal(),Runtime(),wide=None)
            with patch('pycmd.xp_terminal.os.name','nt'),patch('ctypes.WinDLL',return_value=kernel,create=True),patch.dict('sys.modules',{'msvcrt':SimpleNamespace(get_osfhandle=lambda fd:fd)}):
                adapter.write_text('─')
            self.assertEqual(position[0],2)
            self.assertEqual(sent,['─','──'] if width==1 else ['─'])

    def test_width_policy(self):
        for c in '─│┌┐╔╦╭■α':
            self.assertTrue(legacy_wide(c));self.assertEqual(cell_width(c),1);self.assertEqual(cell_width(c,True),2)
        for c in 'ABC123':self.assertEqual(cell_width(c,True),1)
        self.assertEqual(cell_width('中',True),2)
        self.assertEqual(cell_width('\u0301',True),0)
        self.assertFalse(legacy_wide('\ue000'))
    def test_terminal_border_and_control_sequences(self):
        self.assertEqual(terminal_text('┌─┬─┐\r\n│A│B│'), ' ┌───┬───┐\r\n │A │B │')
        self.assertEqual(terminal_text('\x1b]0;─Title\x07\x1b[31m─\x1b[0m'),'\x1b]0;─Title\x07\x1b[31m──\x1b[0m')
    def test_display_only_and_fork(self):
        with tempfile.TemporaryDirectory() as folder,patch('pycmd.xp_terminal.os.name','posix'):
            out=Terminal();rt=Runtime(cwd=folder,stdout=out,xp=True)
            rt.state.encoding='utf-8'
            rt.command('set "value=─│"')
            rt.command('echo %value%')
            self.assertEqual(out.getvalue(),'── │\r\n'.encode())
            rt.command('echo %value%>saved.txt')
            self.assertEqual(Path(folder,'saved.txt').read_text(),'─│\n')
            self.assertEqual(rt.state.env['value'],'─│')
            child=rt.fork(stdout=rt.streams.table[1]);self.assertTrue(child.xp)
            child.command('echo ─');self.assertTrue(out.getvalue().endswith('──\r\n'.encode()))
    def test_captured_stream_and_already_wide_terminal(self):
        rt=Runtime(xp=True);rt.state.encoding='utf-8';rt.command('echo ─')
        self.assertEqual(rt.streams.table[1].getvalue(),'─\r\n'.encode())
        with patch('pycmd.xp_terminal.os.name','posix'):
            out=Terminal();rt=Runtime(xp=True,stdout=out,env={'PYCMD_TERMINAL_AMBIGUOUS_WIDTH':'2'})
            rt.command('echo ─');self.assertEqual(out.getvalue(),'─\r\n'.encode())
    def test_byte_output_decoder_and_control_channel(self):
        with patch('pycmd.xp_terminal.os.name','posix'):
            out=Terminal();rt=Runtime(xp=True,stdout=out);rt.state.encoding='cp936'
            adapter=rt.streams.table[1];data='─'.encode('cp936')
            adapter.write(data[:1]);adapter.write(data[1:]);self.assertEqual(out.getvalue(),'──'.encode())
            rt.state.unicode_output=True;adapter.write(b'\x1b[6n')
            self.assertTrue(out.getvalue().endswith(b'\x1b[6n'))
            rt.command('title ─Title')
            self.assertTrue(out.getvalue().endswith('\x1b]0;─Title\x07'.encode()))

class XpGuiTests(unittest.TestCase):
    def test_border_tiles_cover_cell_edges_at_odd_and_even_sizes(self):
        try:from pycmd.gui_glyphs import LegacyGlyphs
        except ImportError:self.skipTest('Pillow not installed')
        for width,height in ((20,19),(28,29),(38,38)):
            glyphs=LegacyGlyphs(None,width//2,height)
            for char in '─═│║':
                bitmap=glyphs.border_bitmap(char,width,'#ffff00')
                if char in '─═':
                    rows=(height//2,) if char=='─' else (height//2-height//10,height//2+height//10)
                    for y in rows:
                        self.assertTrue(all(bitmap.getpixel((x,y))==(255,255,0,255) for x in range(width)))
                else:
                    cols=(width//2,) if char=='│' else (width//2-height//10,width//2+height//10)
                    for x in cols:
                        self.assertTrue(all(bitmap.getpixel((x,y))==(255,255,0,255) for y in range(height)))

    def test_layout_and_mouse_regions(self):
        try:from pycmd.gui_model import Screen
        except ImportError:self.skipTest('Pillow not installed')
        s=Screen(cols=56,lines=22,xp=True)
        s.write('╔'+'─╦'*9+'─╗')
        self.assertEqual(s.x,42)
        s.write('\r\n'+'│  '*10+'│   │开始│')
        self.assertEqual(s.x,53)
        self.assertEqual(s.cells[1][47][0],'开');self.assertEqual(s.cells[1][49][0],'始')
        s.move(1,1);s.write('A');self.assertEqual(s.cells[1][0][0],' ')
        s=Screen(cols=3,lines=2,xp=True);s.write('─│')
        self.assertEqual((s.x,s.y),(2,1))
    def test_gui_geometry_and_input_width(self):
        try:
            import tkinter as tk
            from pycmd.gui import GuiConsole
        except ImportError:self.skipTest('Tk/Pillow not installed')
        try:root=tk.Tk()
        except tk.TclError as exc:self.skipTest(str(exc))
        root.withdraw();gui=GuiConsole(root)
        try:
            from types import SimpleNamespace
            gui.start(SimpleNamespace(batch=None,command='echo ─│■ & pause',args=[]),dict(xp=True))
            import time
            deadline=time.monotonic()+3
            while not gui.active_input and time.monotonic()<deadline:root.update();time.sleep(.01)
            self.assertIsNotNone(gui.active_input)
            self.assertEqual(gui.screen.cells[0][1][0],'')
            self.assertEqual(gui.screen.cells[0][3][0],'')
            self.assertEqual(gui.screen.cells[0][5][0],'')
            self.assertGreater(len(gui.canvas.find_all()),0)
            cw,ch=gui.screen.cw,gui.screen.ch
            tiles=[item for item in gui.canvas.find_all() if gui.canvas.type(item)=='rectangle'
                   and gui.canvas.coords(item)==[4*cw,0,6*cw,ch]]
            self.assertEqual(len(tiles),1)
            self.assertEqual(gui.canvas.itemcget(tiles[0],'outline'),'')
            # Borders are cached images; the cursor is the only vector line.
            self.assertEqual([i for i in gui.canvas.find_all() if gui.canvas.type(i)=='line'],
                             list(gui.canvas.find_withtag('cursor')))
        finally:
            gui.close();gui.worker.join(1);gui.dispose()

if __name__=='__main__':unittest.main()
