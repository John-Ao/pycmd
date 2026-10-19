import time
import unittest
import os
import threading
from types import SimpleNamespace
from pycmd import Runtime
from pycmd.timeout_command import parse

class TimeoutTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='posix','PTY test requires POSIX')
    def test_terminal_key_and_mode_restoration(self):
        import termios
        master,slave=os.openpty();source=os.fdopen(slave,'rb',buffering=0)
        saved=termios.tcgetattr(source.fileno());rt=Runtime(stdin=source)
        result=[]
        worker=threading.Thread(target=lambda:result.append(rt.command('timeout /t 2')))
        try:
            worker.start();deadline=time.monotonic()+1
            while time.monotonic()<deadline and termios.tcgetattr(source.fileno())[3]&termios.ICANON:time.sleep(.005)
            self.assertFalse(termios.tcgetattr(source.fileno())[3]&termios.ICANON)
            os.write(master,b'x');worker.join(1)
            self.assertFalse(worker.is_alive());self.assertEqual(result,[0])
            self.assertEqual(termios.tcgetattr(source.fileno()),saved)
        finally:
            worker.join(3);source.close();os.close(master)
    def test_arguments_and_redirected_input(self):
        for text,expected in [('/t 1',(1,False)),('/NOBREAK /T 02',(2,True)),('-1',(-1,False))]:
            self.assertEqual(parse(text),expected)
        for text in ('','/t','/t -2','/t 100000','/t 1 /t 2','/bad','1 junk'):
            with self.assertRaises(ValueError):parse(text)
        rt=Runtime();self.assertEqual(rt.command('timeout /t 0'),1)
        self.assertIn(b'Input redirection',rt.streams.table[2].getvalue())

    def test_gui_wait_key_and_nobreak(self):
        import tkinter as tk
        from pycmd.gui import GuiConsole
        for nobreak in (False,True):
            with self.subTest(nobreak=nobreak):
                try:root=tk.Tk()
                except tk.TclError as exc:self.skipTest(str(exc))
                root.withdraw();gui=GuiConsole(root)
                try:
                    gui.start(SimpleNamespace(batch=None,command='timeout /t 1'+(' /nobreak' if nobreak else ''),args=[]),{})
                    start=time.monotonic();sent=False
                    while not gui.done and time.monotonic()-start<3:
                        root.update()
                        if time.monotonic()-start>.15 and not sent:
                            gui.key(SimpleNamespace(keysym='x',char='x',state=0));sent=True
                        time.sleep(.002)
                    elapsed=time.monotonic()-start
                    self.assertTrue(gui.done);self.assertEqual(gui.code,0)
                    self.assertFalse(gui.keys)
                    self.assertEqual(gui.timeout_waiters,0)
                    self.assertGreaterEqual(elapsed,.95 if nobreak else .15)
                    if not nobreak:self.assertLess(elapsed,.8)
                finally:
                    gui.close()
                    if gui.worker:gui.worker.join(2)
