import unittest
from pycmd.gui_model import Screen,color

class AnsiTests(unittest.TestCase):
    def test_tk_truecolor_and_hidden_cursor(self):
        import tkinter as tk
        from pycmd.gui import GuiConsole
        try:root=tk.Tk()
        except tk.TclError as exc:self.skipTest(str(exc))
        root.withdraw();gui=GuiConsole(root)
        try:
            gui.screen.write('\x1b[38;2;12;34;56mX\x1b[?25l')
            gui.render()
            self.assertFalse(gui.canvas.find_withtag('cursor'))
            text=[i for i in gui.canvas.find_all() if gui.canvas.type(i)=='text']
            self.assertEqual(gui.canvas.itemcget(text[0],'fill'),'#0c2238')
            gui.screen.write('\x1b[?25h');gui.render_cursor()
            self.assertTrue(gui.canvas.find_withtag('cursor'))
        finally:gui.close()
    def test_chunk_boundaries_and_truecolor(self):
        text='abc\x1b[2;3H\x1b[38;2;12;34;56m\x1b[48;2;200;201;202mX\x1b[?25l'
        a=Screen(10,4);a.write(text)
        for split in range(len(text)+1):
            b=Screen(10,4);b.write(text[:split]);b.write(text[split:])
            self.assertEqual(b.cells,a.cells)
            self.assertEqual((b.x,b.y,b.cursor_visible),(3,1,False))
        self.assertEqual(a.cells[1][2],('X','#0c2238','#c8c9ca'))
        a.write('\x1b[0m\x1b[?25h');self.assertEqual((a.fg,a.bg,a.cursor_visible),(7,0,True))
    def test_erase_keeps_cursor_image_and_history(self):
        s=Screen(6,3);s.overlay.putpixel((0,0),(1,2,3,255))
        s.write('abcdef\r\nghijkl\r\nmnopqr\x1b[2;3H\x1b[1J')
        self.assertEqual(''.join(c for c,_,_ in s.cells[1]),'   jkl')
        s.write('\x1b[2J');self.assertEqual((s.x,s.y),(2,1))
        self.assertEqual(s.overlay.getpixel((0,0)),(1,2,3,255))
        self.assertTrue(all(c==' ' for row in s.cells for c,_,_ in row))
        self.assertEqual(len(s.history),0)
    def test_movement_wide_erase_and_palette(self):
        s=Screen(8,3);s.write('界AB\x1b[1;2H\x1b[0K')
        self.assertTrue(all(c==' ' for c,_,_ in s.cells[0]))
        s.write('\x1b[999B\x1b[999C');self.assertEqual((s.x,s.y),(7,2))
        s.write('\x1b[s\x1b[H\x1b[u');self.assertEqual((s.x,s.y),(7,2))
        s.write('\x1b[31;104m');self.assertEqual((color(s.fg),color(s.bg)),('#800000','#0000ff'))
        s.write('\x1b[38;5;196m');self.assertEqual(color(s.fg),'#ff0000')
