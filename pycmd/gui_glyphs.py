"""Full-cell legacy glyphs in the text layer, independent of IMAGE overlay."""
import os
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont,ImageTk
from .display_width import box_arms

class LegacyGlyphs:
    def __init__(self,root,cw,ch,fontsize=16):
        self.root=root;self.cw=cw;self.ch=ch;self.cache={};self.font=None
        candidates=[str(Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/consola.ttf'),
                    '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf','/System/Library/Fonts/Menlo.ttc','DejaVuSansMono.ttf']
        for path in candidates:
            try:self.font=ImageFont.truetype(path,fontsize);break
            except OSError:pass
    def draw(self,canvas,char,x,y,width,color):
        if char=='■':
            # Legacy solid tiles fill the cell, including font line spacing.
            canvas.create_rectangle(x,y,x+width,y+self.ch,fill=color,outline='')
            return True
        arms=box_arms(char)
        if arms:
            key=(char,width,color)
            if key not in self.cache:
                glyph=self.border_bitmap(char,width,color)
                self.cache[key]=ImageTk.PhotoImage(glyph,master=self.root)
            # Rasterize at integer cell pixels. Canvas vector strokes can have
            # fractional centers/edge overhangs and depend on damage clipping;
            # a cached tile has explicit coverage for every partial repaint.
            canvas.create_image(x,y,anchor='nw',image=self.cache[key])
            return True
        if self.font is None:return False
        key=(char,width,color)
        if key not in self.cache:
            box=self.font.getbbox(char)
            if box[2]<=box[0] or box[3]<=box[1]:return False
            mask=Image.new('L',(box[2]-box[0],box[3]-box[1]))
            ImageDraw.Draw(mask).text((-box[0],-box[1]),char,font=self.font,fill=255)
            height=min(self.ch-2,mask.height)
            mask=mask.resize((max(1,width-2),max(1,height)))
            glyph=Image.new('RGBA',(width,self.ch));ink=Image.new('RGBA',mask.size,color)
            glyph.paste(ink,(1,(self.ch-height)//2),mask)
            self.cache[key]=ImageTk.PhotoImage(glyph,master=self.root)
        canvas.create_image(x,y,anchor='nw',image=self.cache[key]);return True

    def border_bitmap(self,char,width,color):
        glyph=Image.new('RGBA',(width,self.ch));draw=ImageDraw.Draw(glyph)
        cx=width//2;cy=self.ch//2;gap=max(1,self.ch//10)
        for direction,style in box_arms(char).items():
            offsets=(-gap,gap) if style=='DOUBLE' else (0,)
            for offset in offsets:
                thick=2 if style=='HEAVY' else 1
                if direction in 'lr':
                    end=0 if direction=='l' else width-1
                    draw.line((cx,cy+offset,end,cy+offset),fill=color,width=thick)
                else:
                    end=0 if direction=='u' else self.ch-1
                    draw.line((cx+offset,cy,cx+offset,end),fill=color,width=thick)
        return glyph
