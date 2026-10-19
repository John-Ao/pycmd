import importlib.util
import io
import os
import sys
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

from pycmd import Runtime
from pycmd.image_command import parse

PIL_AVAILABLE=importlib.util.find_spec('PIL') is not None

class ImageSyntaxTests(unittest.TestCase):
    def test_external_gui_streams_rejected_but_full_redirection_works(self):
        class Output(io.BytesIO):console=True
        with tempfile.TemporaryDirectory() as folder:
            rt=Runtime(cwd=folder,stdout=Output(),allow_external=True)
            rt.console=SimpleNamespace(check_interrupt=lambda:None)
            self.assertEqual(rt.command(f'"{sys.executable}" -c "print(17)"'),125)
            self.assertIn(b'GUI external processes',rt.streams.table[2].getvalue())
            self.assertEqual(rt.command(f'"{sys.executable}" -c "print(17)" <nul >result.txt 2>err.txt'),0)
            self.assertEqual(Path(folder,'result.txt').read_text().strip(),'17')

    def test_parse_and_headless_error(self):
        self.assertEqual(parse('"a b.bmp" 10 50 /srcand'),('image',('a b.bmp',10,50,'SRCAND')))
        self.assertEqual(parse('/s -10 20 30 40'),('clear_image',(-10,20,20,60)))
        for arg in ('/s 1 2','/s 1 2 0 3','a.bmp a 2','a.bmp 1 2 3 4'):
            with self.assertRaises(ValueError):parse(arg)
        rt=Runtime();self.assertEqual(rt.command('image a.bmp 0 0'),1)
        self.assertEqual(rt.state.errorlevel,1);self.assertIn(b'--gui',rt.streams.table[2].getvalue())
        rt.command('image /?');self.assertIn(b'SRCCOPY',rt.streams.table[1].getvalue())

@unittest.skipUnless(PIL_AVAILABLE,'GUI extra requires Pillow')
class GuiModelTests(unittest.TestCase):
    def test_scrollback_anchor_bounds_and_resize(self):
        from pycmd.gui_model import Screen
        screen=Screen(6,3,1,1)
        screen.write('one\r\ntwo\r\nthree\r\nfour')
        self.assertEqual(len(screen.history),1)
        screen.scroll(1)
        def first():return ''.join(c for c,_,_ in screen.visible_rows()[0]).strip()
        self.assertEqual(first(),'one')
        screen.write('\r\nfive');self.assertEqual(first(),'one')
        self.assertEqual(screen.view_offset,2)
        screen.resize(8,3);self.assertTrue(all(len(r)==8 for r in screen.visible_rows()))
        screen.scroll(-100);self.assertEqual(first(),'three')
        screen.scroll(100);screen.clear()
        self.assertEqual(screen.view_offset,0);self.assertEqual(len(screen.history),2)

    def test_overlay_raster_truth_table_and_alpha(self):
        from PIL import Image
        from pycmd.gui_model import Screen
        operations={'BLACKNESS':lambda s,d:0,'WHITENESS':lambda s,d:255,'DSTINVERT':lambda s,d:~d,
            'MERGECOPY':lambda s,d:s,'MERGEPAINT':lambda s,d:~s|d,'NOTSRCCOPY':lambda s,d:~s,
            'NOTSRCERASE':lambda s,d:~(s|d),'PATCOPY':lambda s,d:255,'PATPAINT':lambda s,d:255,
            'PATINVERT':lambda s,d:~d,'SRCAND':lambda s,d:s&d,'SRCCOPY':lambda s,d:s,
            'SRCERASE':lambda s,d:s&~d,'SRCINVERT':lambda s,d:s^d,'SRCPAINT':lambda s,d:s|d}
        for op,fn in operations.items():
            with self.subTest(operation=op):
                screen=Screen(2,2,1,1);screen.write('A');before=[r[:] for r in screen.cells]
                screen.overlay.putpixel((0,0),(0x3c,0x55,0xaa,0))
                screen.draw(Image.new('RGB',(1,1),(0x5a,0xaa,0x55)),0,0,op)
                self.assertEqual(screen.overlay.getpixel((0,0)),tuple(fn(s,d)&255 for s,d in zip((0x5a,0xaa,0x55),(0x3c,0x55,0xaa)))+(255,))
                self.assertEqual(screen.cells,before)
    def test_transparent_black_preserves_destination_clear_and_clip(self):
        from PIL import Image
        from pycmd.gui_model import Screen
        screen=Screen(3,2,1,1);screen.overlay.putpixel((0,0),(1,2,3,128))
        src=Image.new('RGB',(2,1));src.putpixel((1,0),(4,5,6))
        screen.draw(src,0,0,'TRANSPARENTBLT')
        self.assertEqual(screen.overlay.getpixel((0,0)),(1,2,3,128))
        self.assertEqual(screen.overlay.getpixel((1,0)),(4,5,6,255))
        screen.clear_image((0,0,1,1));self.assertEqual(screen.overlay.getpixel((0,0)),(0,0,0,0))
        screen.draw(src,-1,1);self.assertEqual(screen.overlay.getpixel((0,1)),(4,5,6,255))
        screen.clear_image();self.assertIsNone(screen.overlay.getbbox())
    def test_text_scroll_resize_and_overlay_independence(self):
        from pycmd.gui_model import Screen
        screen=Screen(4,2,1,1);screen.overlay.putpixel((0,0),(1,2,3,255))
        screen.write('abc\rZ\r\n1234\r\nQ')
        self.assertEqual(''.join(c for c,_,_ in screen.cells[0]),'1234')
        self.assertEqual(screen.overlay.getpixel((0,0)),(1,2,3,255))
        screen.resize(6,3);self.assertEqual(screen.overlay.getpixel((0,0)),(1,2,3,255))
        overlay=screen.overlay.tobytes()
        screen.clear();self.assertEqual(screen.overlay.tobytes(),overlay);self.assertEqual((screen.x,screen.y),(0,0))
        self.assertTrue(all(c==' ' for row in screen.cells for c,_,_ in row))
        screen.write('你a\rZ');self.assertEqual(screen.cells[0][1][0],' ')
        with self.assertRaises(ValueError):screen.resize(32767,32767)

@unittest.skipUnless(PIL_AVAILABLE and importlib.util.find_spec('tkinter'),'Tk and Pillow required')
class GuiIntegrationTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from pycmd.gui import GuiConsole
        try:self.root=tk.Tk()
        except tk.TclError as exc:self.skipTest(str(exc))
        self.root.withdraw();self.gui=GuiConsole(self.root)
        self.folder=tempfile.TemporaryDirectory()
    def tearDown(self):
        if hasattr(self,'gui'):
            self.gui.close()
            if self.gui.worker:self.gui.worker.join(1)
            self.gui.dispose()
        if hasattr(self,'folder'):self.folder.cleanup()
    def until(self,predicate,seconds=5):
        deadline=time.monotonic()+seconds
        while not predicate() and time.monotonic()<deadline:
            self.root.update();time.sleep(.005)
        self.assertTrue(predicate(),'GUI timed out')
    def start(self,text):
        path=Path(self.folder.name)/'run.bat';path.write_text('@echo off\n'+text)
        args=SimpleNamespace(batch=str(path),command=None,args=[])
        self.gui.start(args,dict(cwd=self.folder.name,traceback=True))
    def screen_text(self):return '\n'.join(''.join(c for c,_,_ in row) for row in self.gui.screen.cells)
    def key(self,char,keysym=None,state=0):
        self.gui.key(SimpleNamespace(char=char,keysym=keysym or char,state=state))
    def test_title_size_image_and_pasted_lines(self):
        from PIL import Image
        Image.new('RGB',(1000,1000),(255,0,0)).save(Path(self.folder.name)/'red.bmp')
        self.start('title GUI title>nul\nmode con lines=22 cols=56\nimage red.bmp 10 50\nset /p A=First:\nset /p B=Second:\necho VALUES=[%A%][%B%]\n')
        self.until(lambda:self.gui.active_input is not None)
        self.assertEqual(self.root.title(),'GUI title')
        self.assertEqual((self.gui.screen.cols,self.gui.screen.lines),(56,22))
        self.assertEqual(self.gui.screen.overlay.getpixel(self.gui.image_box((10,50))),(255,0,0,255))
        self.root.clipboard_clear();self.root.clipboard_append('one\ntwo\n');self.gui.paste()
        self.until(lambda:self.gui.done)
        text=self.screen_text()
        self.assertIn('First:one',text);self.assertIn('Second:two',text);self.assertIn('VALUES=[one][two]',text)
        self.assertEqual(self.gui.code,0)
    def test_fontsize_and_logical_image_coordinates(self):
        from PIL import Image
        import tkinter as tk
        from pycmd.gui import GuiConsole
        source=Image.new('RGB',(16,16),(12,34,56))
        source.paste((0,0,0),(0,0,8,16))
        filename=Path(self.folder.name)/'scale.bmp';source.save(filename)
        heights=[]
        for fontsize in (12,24,36):
            with self.subTest(fontsize=fontsize):
                self.gui.close();self.gui.dispose()
                self.root=tk.Tk();self.root.withdraw()
                self.gui=GuiConsole(self.root,fontsize=fontsize)
                screen=self.gui.screen;ch=screen.ch;heights.append(ch)
                self.assertEqual(int(self.gui.font.cget('size')),-self.gui.font_pixels)
                # A 16x16 bitmap occupies exactly one row in both axes.
                self.gui.operation('image',(str(filename),16,16,'SRCCOPY'))
                self.assertEqual(screen.overlay.getbbox(),(ch,ch,2*ch,2*ch))
                self.gui.operation('clear_image',(16,16,32,32))
                self.assertIsNone(screen.overlay.getbbox())
                self.gui.operation('image',(str(filename),0,0,'TRANSPARENTBLT'))
                self.assertEqual(screen.overlay.getpixel((0,0)),(0,0,0,0))
                self.assertEqual(screen.overlay.getpixel((ch-1,ch-1)),(12,34,56,255))
                self.gui.operation('clear_image',None)
                # Fractional scaling and negative coordinates share edge rounding.
                self.gui.operation('image',(str(filename),-3,-5,'SRCCOPY'))
                self.assertEqual(screen.overlay.getbbox(),(0,0,13*ch//16,11*ch//16))
                self.gui.operation('clear_image',(-3,-5,13,11))
                self.assertIsNone(screen.overlay.getbbox())
        self.assertTrue(heights[0]<heights[1]<heights[2])

    def test_dpi_scales_text_image_and_mouse_together(self):
        import tkinter as tk
        from PIL import Image
        from pycmd.gui import GuiConsole
        original=float(self.root.tk.call('tk','scaling'))
        path=Path(self.folder.name)/'dpi.bmp'
        Image.new('RGB',(16,16),'red').save(path)
        try:
            for scale in (1,1.25,1.5,2):
                self.gui.close();self.gui.dispose()
                self.root=tk.Tk();self.root.withdraw()
                self.root.tk.call('tk','scaling',scale*96/72)
                self.gui=GuiConsole(self.root)
                self.assertEqual(self.gui.fontsize,16)
                self.assertEqual(self.gui.font_pixels,round(16*scale))
                screen=self.gui.screen
                self.gui.operation('image',(str(path),16,16,'SRCCOPY'))
                self.assertEqual(screen.overlay.getbbox(),(screen.ch,screen.ch,screen.ch*2,screen.ch*2))
                self.gui.operation('size',{'cols':56,'lines':22})
                self.assertEqual(screen.overlay.size,(screen.cw*56,screen.ch*22))
                self.gui.mouse_active=True
                self.gui.mouse(SimpleNamespace(x=screen.cw*3+1,y=screen.ch*4+1),0)
                event=self.gui.mouse_events.get_nowait()
                self.assertEqual((event.x,event.y),(3,4))
        finally:self.root.tk.call('tk','scaling',original)

    def test_image_rendered_between_background_and_text(self):
        screen=self.gui.screen
        screen.cells[0][0]=('A',15,1)
        screen.overlay.paste((255,0,0,255),(0,0,screen.cw,screen.ch))
        self.gui.render()
        kinds=[self.gui.canvas.type(item) for item in self.gui.canvas.find_all()]
        self.assertLess(kinds.index('rectangle'),kinds.index('image'))
        self.assertLess(kinds.index('image'),kinds.index('text'))
        self.assertLess(kinds.index('text'),kinds.index('line'))
        self.assertEqual(screen.overlay.getpixel((0,0)),(255,0,0,255))

    def test_cmos_receives_mouse_and_final_cursor(self):
        self.start('cls\ncmos 0 -1 1 0 10\nset P=%errorlevel%\necho P=[%P%]\n')
        self.until(lambda:self.gui.mouse_active)
        screen=self.gui.screen
        self.gui.canvas.event_generate('<ButtonPress-1>',x=20*screen.cw+1,y=7*screen.ch+1)
        # Hidden windows need direct delivery; the public callback uses pixel coordinates.
        self.gui.mouse(SimpleNamespace(x=20*screen.cw+1,y=7*screen.ch+1),0)
        self.until(lambda:self.gui.done)
        self.assertIn('P=[21008]',self.screen_text());self.assertFalse(self.gui.mouse_active)
    def test_choice_deadline_and_next_input(self):
        self.start('choice /c yn /t 1 /d n /n\necho CHOICE=%errorlevel%\nset /p NEXT=Next:\necho NEXT=%NEXT%\n')
        self.until(lambda:self.gui.active_input is not None and self.gui.active_input['value']=='line')
        self.assertIn('CHOICE=2',self.screen_text())
        for c in 'hello':self.key(c)
        self.key('\n','Return');self.until(lambda:self.gui.done)
        self.assertIn('NEXT=hello',self.screen_text())
        self.assertNotIn('Traceback',self.screen_text())
    def test_gui_scroll_history_and_live_mouse(self):
        g=self.gui;s=g.screen
        s.resize(10,3);s.write('one\r\ntwo\r\nthree\r\nfour')
        g.render();g.dirty=False;g.operation('mouse',True)
        g.wheel(SimpleNamespace(delta=120));g.render()
        self.assertEqual(s.view_offset,1)
        self.assertFalse(g.canvas.find_withtag('cursor'))
        g.mouse(SimpleNamespace(x=1,y=1),0)
        self.assertTrue(g.mouse_events.empty())
        self.assertEqual(''.join(c for c,_,_ in s.visible_rows()[0]).strip(),'one')
        g.scroll('moveto',1);g.render()
        self.assertEqual(s.view_offset,0);self.assertTrue(g.canvas.find_withtag('cursor'))
        g.mouse(SimpleNamespace(x=1,y=1),0);self.assertFalse(g.mouse_events.empty())
        g.scroll('scroll',-1,'pages')
        self.key('a');self.assertEqual(s.view_offset,0)

    def test_editing_scrolled_input_does_not_duplicate_history(self):
        self.start('mode con cols=10 lines=3\necho one\necho two\nset /p A=Prompt:\n')
        self.until(lambda:self.gui.active_input is not None)
        for char in 'abcdefghijklmnop':self.key(char)
        count=len(self.gui.screen.history)
        self.key('',keysym='BackSpace');self.key('p')
        self.assertEqual(len(self.gui.screen.history),count)
    def test_mouse_burst_skips_stale_motion_but_preserves_clicks(self):
        from pycmd.gui import GuiMouse
        from pycmd.cmos import Mouse
        backend=GuiMouse(self.gui)
        for i in range(1000):self.gui.mouse_events.put(Mouse(i%80,i%25))
        self.assertEqual(backend.poll(0),Mouse(999%80,999%25))
        for event in (Mouse(1,1),Mouse(2,2,0),Mouse(3,3),Mouse(4,4,1),Mouse(5,5)):
            self.gui.mouse_events.put(event)
        self.assertEqual(backend.poll(0),Mouse(2,2,0))
        self.assertEqual(backend.poll(0),Mouse(4,4,1))
        self.assertEqual(backend.poll(0),Mouse(5,5))
        self.assertIsNone(backend.poll(0))

    def test_cursor_motion_reuses_text_and_image_items(self):
        self.gui.screen.write('Text remains on screen')
        self.gui.render();self.gui.dirty=False
        items=self.gui.canvas.find_all();photo=self.gui.photo
        # Drive the real worker RPC path, including pump dirty tracking.
        worker=threading.Thread(target=lambda:[self.gui.call('move',(i,5)) for i in range(10)])
        worker.start();self.until(lambda:not worker.is_alive());worker.join()
        self.assertEqual(self.gui.canvas.find_all(),items)
        self.assertIs(self.gui.photo,photo)
        cw,ch=self.gui.screen.cw,self.gui.screen.ch
        self.assertEqual(self.gui.canvas.coords('cursor'),[9*cw,6*ch-2,10*cw,6*ch-2])

    def test_mouse_cursor_layer_is_independent_until_cmos_finishes(self):
        screen=self.gui.screen;screen.write('original')
        self.gui.render();self.gui.dirty=False
        cells=[row[:] for row in screen.cells];position=(screen.x,screen.y)
        cursor=self.gui.canvas.find_withtag('cursor')
        content=self.gui.canvas.find_withtag('content');photo=self.gui.photo
        self.gui.operation('mouse',True)
        for point in ((1,2),(7,4),(0,10)):self.gui.operation('move',point)
        self.assertEqual(screen.cells,cells)
        self.assertEqual((screen.x,screen.y),position)
        self.assertEqual(self.gui.canvas.find_withtag('content'),content)
        self.assertIs(self.gui.photo,photo)
        self.gui.render()
        self.assertEqual(self.gui.canvas.find_withtag('cursor'),cursor)
        self.assertEqual(self.gui.canvas.find_all()[-1],cursor[0])
        self.gui.operation('mouse',False)
        self.assertEqual((screen.x,screen.y),(0,10))
        screen.write('next')
        self.assertEqual(''.join(c for c,_,_ in screen.cells[10][:4]),'next')

    def test_ctrl_c_interrupts_input_sleep_and_compute(self):
        # Each subcase gets a fresh console, including its cancellation state.
        for script,ready in (
            ('set /p A=Input:\n',lambda:self.gui.active_input is not None),
            ('ping/n 100 127.1 >nul\n',lambda:self.gui.runtime.steps>0),
            (':again\ngoto again\n',lambda:self.gui.runtime.steps>10),
            ('cmos 0 -1 1\n',lambda:self.gui.mouse_active)):
            with self.subTest(script=script):
                self.start(script);self.until(ready);self.key('\x03','c',4)
                self.until(lambda:self.gui.done)
                self.assertEqual(self.gui.code,0xc000013a)
                self.assertIn('KeyboardInterrupt',self.screen_text())
                self.gui.close();self.gui.worker.join(1)
                self.gui.dispose()
                import tkinter as tk
                from pycmd.gui import GuiConsole
                self.root=tk.Tk();self.root.withdraw();self.gui=GuiConsole(self.root)
    def test_image_errors_partial_clear_and_cls(self):
        from PIL import Image
        Image.new('RGB',(10,10),(255,255,0)).save(Path(self.folder.name)/'a.bmp')
        self.start('image a.bmp 0 0\nimage /s 1 1 3 3\nimage a.bmp 0 0 /BAD\necho ERROR=%errorlevel%\nset /p N=Wait:\ncls\n')
        self.until(lambda:self.gui.active_input is not None)
        self.assertEqual(self.gui.screen.overlay.getpixel(self.gui.image_box((1,1))),(0,0,0,0))
        self.assertEqual(self.gui.screen.overlay.getpixel((0,0)),(255,255,0,255))
        self.assertIn('ERROR=1',self.screen_text())
        overlay=self.gui.screen.overlay.tobytes()
        self.key('\n','Return');self.until(lambda:self.gui.done)
        self.assertEqual(self.gui.screen.overlay.tobytes(),overlay)
        self.assertNotIn('ERROR=1',self.screen_text())

    def test_close_callback_wakes_input_and_cleans_up_on_tk_thread(self):
        errors=[]
        self.root.report_callback_exception=lambda *args:errors.append(args)
        self.start('set /p N=Wait:\n')
        self.until(lambda:self.gui.active_input is not None)
        self.root.after(20,self.gui.close)
        self.root.mainloop()
        self.gui.worker.join(1)
        self.assertFalse(self.gui.worker.is_alive())
        self.assertTrue(self.gui.closed.is_set())
        self.assertEqual(errors,[])

if __name__=='__main__':unittest.main()
