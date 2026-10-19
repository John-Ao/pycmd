"""GUI state independent of Tk: character cells and an isolated RGBA overlay."""
import unicodedata
from collections import deque
from PIL import Image
from .display_width import cell_width

PALETTE=('#000000','#000080','#008000','#008080','#800000','#800080','#808000','#c0c0c0',
         '#808080','#0000ff','#00ff00','#00ffff','#ff0000','#ff00ff','#ffff00','#ffffff')
ROPS={'BLACKNESS','DSTINVERT','MERGECOPY','MERGEPAINT','NOTSRCCOPY','NOTSRCERASE',
      'PATCOPY','PATPAINT','PATINVERT','SRCAND','SRCCOPY','SRCERASE','SRCINVERT','SRCPAINT','WHITENESS','TRANSPARENTBLT'}

def color(value):return PALETTE[value] if isinstance(value,int) else value

class Screen:
    def __init__(self,cols=80,lines=25,cell_width=10,cell_height=20,xp=False):
        self.xp=xp
        self.cw=cell_width;self.ch=cell_height;self.fg=7;self.bg=0;self.x=0;self.y=0
        self.cols=cols;self.lines=lines;self.cells=self.blank(lines,cols)
        self.overlay=Image.new('RGBA',(cols*self.cw,lines*self.ch))
        self.history=deque(maxlen=10000);self.view_offset=0
        from .gui_ansi import Ansi
        self.ansi=Ansi(self);self.cursor_visible=True
    def blank(self,lines,cols):return [[(' ',self.fg,self.bg) for _ in range(cols)] for _ in range(lines)]
    def clear(self):
        self.cells=self.blank(self.lines,self.cols);self.x=self.y=0
        self.view_offset=0
    def scroll(self,rows):
        self.view_offset=max(0,min(len(self.history),self.view_offset+rows))
    def visible_rows(self):
        if not self.view_offset:return self.cells
        rows=(list(self.history)[-self.view_offset:]+self.cells)[:self.lines]
        result=[]
        for row in rows:
            padded=row[:self.cols]+self.blank(1,max(0,self.cols-len(row)))[0]
            if len(row)>self.cols and row[self.cols][0]=='':padded[-1]=(' ',self.fg,self.bg)
            result.append(padded)
        return result
    def resize(self,cols,lines):
        if not 1<=cols<=1000 or not 1<=lines<=1000 or cols*lines>100000 or cols*self.cw*lines*self.ch>32000000:
            raise ValueError('GUI console size exceeds supported allocation limit')
        cells=self.blank(lines,cols)
        for y in range(min(lines,self.lines)):
            cells[y][:min(cols,self.cols)]=self.cells[y][:min(cols,self.cols)]
        overlay=Image.new('RGBA',(cols*self.cw,lines*self.ch));overlay.paste(self.overlay,(0,0))
        self.cols=cols;self.lines=lines;self.cells=cells;self.overlay=overlay
        self.x=min(self.x,cols-1);self.y=min(self.y,lines-1)
    def newline(self):
        self.y+=1
        if self.y>=self.lines:
            self.history.append(self.cells.pop(0))
            # Bound both row count and memory for unusually wide consoles.
            while len(self.history)>max(1,1000000//self.cols):self.history.popleft()
            if self.view_offset:self.view_offset=min(len(self.history),self.view_offset+1)
            self.cells.extend(self.blank(1,self.cols));self.y=self.lines-1
    def write(self,text):
        for char in text:
            if self.ansi.feed(char):continue
            if char=='\r':self.x=0;continue
            if char=='\n':self.newline();continue
            if char=='\b':self.x=max(0,self.x-1);continue
            if char=='\t':self.write(' '*(8-self.x%8));continue
            if char=='\f':self.clear();continue
            if ord(char)<32 or 127<=ord(char)<=159:continue
            if unicodedata.combining(char):
                if self.x>0:
                    i=self.x-1
                    if not self.cells[self.y][i][0] and i:i-=1
                    c,f,b=self.cells[self.y][i];self.cells[self.y][i]=(c+char,f,b)
                continue
            width=min(self.cols,cell_width(char,self.xp))
            if self.x+width>self.cols:self.x=0;self.newline()
            # Remove either half of any wide glyph overwritten by this character.
            for index in range(self.x,min(self.x+width,self.cols)):
                if self.cells[self.y][index][0]=='' and index:self.cells[self.y][index-1]=(' ',self.fg,self.bg)
                if index+1<self.cols and self.cells[self.y][index+1][0]=='':self.cells[self.y][index+1]=(' ',self.fg,self.bg)
            self.cells[self.y][self.x]=(char,self.fg,self.bg)
            if width==2:self.cells[self.y][self.x+1]=('',self.fg,self.bg)
            self.x+=width
    def move(self,x,y):
        if not 0<=x<self.cols or not 0<=y<self.lines:raise ValueError('Cursor outside console')
        self.x=x;self.y=y
    def clear_image(self,box=None):
        self.overlay.paste((0,0,0,0),box or (0,0,*self.overlay.size))
    def draw(self,source,x,y,operation='SRCCOPY'):
        if operation not in ROPS:raise ValueError('Unknown raster operation')
        left=max(0,x);top=max(0,y);right=min(self.overlay.width,x+source.width);bottom=min(self.overlay.height,y+source.height)
        if left>=right or top>=bottom:return
        box=(left,top,right,bottom)
        src=source.convert('RGB').crop((left-x,top-y,right-x,bottom-y))
        dst=self.overlay.crop(box);s=src.tobytes();d=dst.convert('RGB').tobytes()
        if operation=='TRANSPARENTBLT':
            pixels=bytearray(dst.tobytes())
            for i in range(0,len(s),3):
                if s[i:i+3]!=b'\0\0\0':pixels[i//3*4:i//3*4+4]=s[i:i+3]+b'\xff'
            result=Image.frombytes('RGBA',src.size,bytes(pixels))
        else:
            # P is a fixed white brush. Bitwise operations apply to RGB only.
            functions={
                'BLACKNESS':lambda s,d:0,'WHITENESS':lambda s,d:255,'DSTINVERT':lambda s,d:d^255,
                'MERGECOPY':lambda s,d:s,'MERGEPAINT':lambda s,d:(s^255)|d,
                'NOTSRCCOPY':lambda s,d:s^255,'NOTSRCERASE':lambda s,d:(s|d)^255,
                'PATCOPY':lambda s,d:255,'PATPAINT':lambda s,d:255,'PATINVERT':lambda s,d:d^255,
                'SRCAND':lambda s,d:s&d,'SRCCOPY':lambda s,d:s,'SRCERASE':lambda s,d:s&(d^255),
                'SRCINVERT':lambda s,d:s^d,'SRCPAINT':lambda s,d:s|d}
            result=Image.frombytes('RGB',src.size,bytes(map(functions[operation],s,d))).convert('RGBA')
        self.overlay.paste(result,(left,top))
