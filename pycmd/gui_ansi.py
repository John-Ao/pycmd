"""Incremental ANSI console control, independent of output write boundaries."""
class Ansi:
    def __init__(self,screen):
        self.screen=screen;self.pending='';self.saved=(0,0)
    def feed(self,c):
        if c=='\x1b':self.pending=c;return True
        if not self.pending:return False
        self.pending+=c
        if self.pending=='\x1b[':return True
        if not self.pending.startswith('\x1b['):self.pending='';return True
        if len(self.pending)>256:self.pending='';return True
        if '@'<=c<='~':
            params=self.pending[2:-1];self.pending=''
            self.control(params,c)
        return True
    def control(self,params,op):
        s=self.screen
        if params=='?25' and op in 'hl':s.cursor_visible=op=='h';return
        try:v=[int(p) if p else 0 for p in params.split(';')]
        except ValueError:return
        n=v[0] or 1
        if op in 'ABCD':
            s.x=max(0,min(s.cols-1,s.x+(n if op=='C' else -n if op=='D' else 0)))
            s.y=max(0,min(s.lines-1,s.y+(n if op=='B' else -n if op=='A' else 0)))
        elif op in ('H','f'):
            s.y=max(0,min(s.lines-1,n-1));s.x=max(0,min(s.cols-1,(v[1] or 1)-1 if len(v)>1 else 0))
        elif op=='G':s.x=max(0,min(s.cols-1,n-1))
        elif op=='s':self.saved=(s.x,s.y)
        elif op=='u':s.x=min(self.saved[0],s.cols-1);s.y=min(self.saved[1],s.lines-1)
        elif op in 'JK':
            mode=v[0];pos=s.y*s.cols+min(s.x,s.cols-1)
            if mode not in (0,1,2):return
            lo,hi=(0,s.cols*s.lines) if op=='J' else (s.y*s.cols,(s.y+1)*s.cols)
            if mode==0:lo=pos
            if mode==1:hi=pos+1
            # Erasing either half of a wide glyph removes the whole glyph.
            if s.cells[lo//s.cols][lo%s.cols][0]=='' and lo%s.cols:lo-=1
            if hi%s.cols and hi<s.cols*s.lines and s.cells[hi//s.cols][hi%s.cols][0]=='':hi+=1
            for i in range(lo,hi):s.cells[i//s.cols][i%s.cols]=(' ',s.fg,s.bg)
        elif op=='m':
            i=0;order=(0,4,2,6,1,5,3,7)
            while i<len(v):
                code=v[i];i+=1
                if code==0:s.fg,s.bg=7,0
                elif code==39:s.fg=7
                elif code==49:s.bg=0
                elif 30<=code<=37:s.fg=order[code-30]
                elif 40<=code<=47:s.bg=order[code-40]
                elif 90<=code<=97:s.fg=order[code-90]+8
                elif 100<=code<=107:s.bg=order[code-100]+8
                elif code in (38,48):
                    color=None
                    if i+3<len(v) and v[i]==2:
                        rgb=v[i+1:i+4];i+=4
                        if all(0<=x<=255 for x in rgb):color='#'+''.join(f'{x:02x}' for x in rgb)
                    elif i+1<len(v) and v[i]==5:
                        index=v[i+1];i+=2
                        if 0<=index<16:color=order[index%8]+(8 if index>=8 else 0)
                        elif 16<=index<=231:
                            q=index-16;levels=(0,95,135,175,215,255)
                            color='#'+''.join(f'{levels[x]:02x}' for x in (q//36,q//6%6,q%6))
                        elif 232<=index<=255:color='#'+f'{8+10*(index-232):02x}'*3
                    if color is not None:
                        if code==38:s.fg=color
                        else:s.bg=color
