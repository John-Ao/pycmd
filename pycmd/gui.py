"""Tk main-thread console with synchronous worker RPC and cancellable input."""
import codecs
import copy
import io
import queue
import threading
import time
from collections import deque
from .gui_model import color, Screen,PALETTE,ROPS

class GuiInput:
    def __init__(self,console):self.console=console;self.pending=bytearray()
    def isatty(self):return True
    def fileno(self):raise io.UnsupportedOperation('GUI has no file descriptor')
    def seekable(self):return False
    def readline(self,size=-1):
        if not self.pending:
            text=self.console.call('input','line')
            self.pending.extend(text.encode(self.console.runtime.state.encoding,errors='replace'))
        end=self.pending.find(b'\n')+1 or len(self.pending)
        if size>=0:end=min(end,size)
        result=bytes(self.pending[:end]);del self.pending[:end];return result
    def read(self,size=-1):
        if size==0:return b''
        if not self.pending:
            text=self.console.call('input','char' if size==1 else 'line')
            self.pending.extend(text.encode(self.console.runtime.state.encoding,errors='replace'))
        end=len(self.pending) if size<0 else min(size,len(self.pending))
        result=bytes(self.pending[:end]);del self.pending[:end];return result

class GuiOutput:
    def __init__(self,console):self.console=console;self.encoding=None;self.decoder=None
    def isatty(self):return True
    def fileno(self):raise io.UnsupportedOperation('GUI has no file descriptor')
    def writable(self):return True
    def flush(self):pass
    def write_text(self,text):self.console.call('write',text,interruptible=False)
    def write(self,data):
        state=self.console.runtime.state
        encoding='utf-16le' if state.unicode_output else state.encoding
        if self.encoding!=encoding:
            self.encoding=encoding;self.decoder=codecs.getincrementaldecoder(encoding)(errors='replace')
        self.write_text(self.decoder.decode(bytes(data)));return len(data)

class GuiMouse:
    def __init__(self,console):self.console=console
    def __enter__(self):self.console.call('mouse',True);return self
    def __exit__(self,*args):self.console.call('mouse',False,interruptible=False)
    def position(self):return self.console.call('position')
    def contains(self,x,y):return 0<=x<self.console.screen.cols and 0<=y<self.console.screen.lines
    def move(self,x,y):self.console.call('move',(x,y))
    def poll(self,timeout):
        self.console.check_interrupt()
        try:event=self.console.mouse_events.get(timeout=timeout)
        except queue.Empty:return None
        # Motion can arrive faster than worker RPCs. Skip stale positions, but
        # stop at the first press so clicks retain their coordinates and order.
        for _ in range(self.console.mouse_events.qsize()):
            if event.button is not None:break
            try:event=self.console.mouse_events.get_nowait()
            except queue.Empty:break
        return event

class GuiConsole:
    def __init__(self,root,fontsize=16):
        import tkinter as tk
        import tkinter.font as font
        if not 1<=fontsize<=128:raise ValueError('Font size must be between 1 and 128')
        self.fontsize=fontsize
        # Tk scaling is pixels per 1/72-inch point, not a percentage.
        self.dpi_scale=float(root.tk.call('tk','scaling'))*72/96
        self.font_pixels=max(1,int(fontsize*self.dpi_scale+.5))
        self.root=root;self.root.title('pycmd');self.runtime=None
        self.font=font.nametofont('TkFixedFont',root=root).copy()
        self.font.configure(size=-self.font_pixels)
        self.screen=Screen(cell_width=max(1,self.font.measure('M')),cell_height=self.font.metrics('linespace'))
        self.canvas=tk.Canvas(root,highlightthickness=0,background='black',takefocus=True)
        self.scrollbar=tk.Scrollbar(root,orient='vertical',command=self.scroll)
        self.scrollbar.pack(side='right',fill='y')
        self.canvas.pack(side='left',fill='both',expand=True);root.resizable(False,False)
        self.requests=queue.Queue();self.mouse_events=queue.Queue();self.cancel=threading.Event();self.closed=threading.Event()
        self.mouse_active=False;self.active_input=None;self.typed='';self.keys=deque();self.input_snapshot=None
        self.mouse_position=None
        self.dirty=True;self.done=False;self.code=0;self.photo=None;self.worker=None
        self.legacy_glyphs=None
        self.stdin=GuiInput(self);self.stdout=GuiOutput(self);self.stderr=GuiOutput(self)
        self.canvas.bind('<Key>',self.key)
        self.canvas.bind('<<Paste>>',self.paste)
        self.canvas.bind('<Control-v>',self.paste)
        self.canvas.bind('<Control-V>',self.paste)
        self.canvas.bind('<Shift-Insert>',self.paste)
        self.canvas.bind('<Motion>',lambda event:self.mouse(event,None))
        self.canvas.bind('<MouseWheel>',self.wheel)
        self.canvas.bind('<Button-4>',lambda event:self.scroll('scroll',-3,'units'))
        self.canvas.bind('<Button-5>',lambda event:self.scroll('scroll',3,'units'))
        for button,code in ((1,0),(2,2),(3,1)):
            self.canvas.bind(f'<ButtonPress-{button}>',lambda event,c=code:self.mouse(event,c))
        root.protocol('WM_DELETE_WINDOW',self.close)
        self.key_epoch=0
        self.timeout_waiters=0
        self.geometry();self.canvas.focus_set();self.after_id=root.after(10,self.pump)
    def check_interrupt(self):
        if self.closed.is_set():raise KeyboardInterrupt()
        if self.cancel.is_set():self.cancel.clear();raise KeyboardInterrupt()
    def sleep(self,seconds):
        deadline=time.monotonic()+seconds
        while True:
            self.check_interrupt();left=deadline-time.monotonic()
            if left<=0:return
            self.cancel.wait(min(left,.05))
    def call(self,command,value=None,interruptible=True):
        if interruptible:self.check_interrupt()
        if self.closed.is_set():
            if interruptible:raise KeyboardInterrupt()
            return None
        request={'command':command,'value':value,'event':threading.Event(),'result':None,'error':None,'cancelled':False}
        self.requests.put(request)
        while not request['event'].wait(.05):
            if self.closed.is_set():request['cancelled']=True;raise KeyboardInterrupt()
            if interruptible:
                try:self.check_interrupt()
                except KeyboardInterrupt:request['cancelled']=True;raise
        if request['error'] is not None:raise request['error']
        return request['result']
    def complete(self,request,result=None,error=None):
        request['result']=result;request['error']=error;request['event'].set()
    def geometry(self):
        w,h=self.screen.overlay.size;self.canvas.config(width=w,height=h)
        self.root.geometry(f'{w+self.scrollbar.winfo_reqwidth()}x{h}')
    def scroll(self,action,amount,unit=None):
        screen=self.screen
        if action=='moveto':
            top=round(float(amount)*(len(screen.history)+screen.lines))
            screen.view_offset=max(0,min(len(screen.history),len(screen.history)-top))
        else:screen.scroll(-int(amount)*(max(1,screen.lines-1) if unit=='pages' else 1))
        self.dirty=True
        return 'break'
    def wheel(self,event):
        if event.delta:
            steps=max(1,abs(event.delta)//120)
            self.scroll('scroll',-3*steps if event.delta>0 else 3*steps,'units')
        return 'break'
    def image_box(self,box):
        # Shared edge mapping keeps adjacent draw/clear rectangles aligned.
        return tuple(n*self.screen.ch//16 for n in box)
    def operation(self,command,value):
        screen=self.screen
        if command=='write':screen.write(value)
        elif command=='timeout_wait':
            self.timeout_waiters+=1 if value else -1
            return self.key_epoch
        elif command=='title':self.root.title(value)
        elif command=='clear':screen.clear()
        elif command=='color':
            screen.fg=value&15;screen.bg=value>>4
            screen.cells=[[(c,screen.fg,screen.bg) for c,_,_ in row] for row in screen.cells]
        elif command=='size':
            if value:
                screen.resize(value.get('cols',screen.cols),value.get('lines',screen.lines));self.geometry()
            return screen.cols,screen.lines
        elif command=='position':return min(screen.x,screen.cols-1),screen.y
        elif command=='move':
            if self.mouse_active:
                x,y=value
                if not 0<=x<screen.cols or not 0<=y<screen.lines:raise ValueError('Cursor outside console')
                self.mouse_position=(x,y)
            else:screen.move(*value)
            if not self.dirty:self.render_cursor()
        elif command=='mouse':
            if value:
                self.mouse_position=(min(screen.x,screen.cols-1),screen.y)
            elif self.mouse_position is not None:
                # CMOS leaves subsequent output at its last/final position.
                screen.move(*self.mouse_position);self.mouse_position=None
            self.mouse_active=value
            while not self.mouse_events.empty():
                try:self.mouse_events.get_nowait()
                except queue.Empty:break
        elif command=='clear_image':
            if value:
                x,y,r,b=self.image_box(value);w,h=screen.overlay.size
                value=(max(0,x),max(0,y),min(w,r),min(h,b))
                if value[0]>=value[2] or value[1]>=value[3]:return
            screen.clear_image(value)
        elif command=='image':
            from PIL import Image
            filename,x,y,operation=value
            if operation not in ROPS:raise ValueError('Unsupported IMAGE raster operation: '+operation)
            with Image.open(filename) as image:
                if image.format!='BMP':raise ValueError('IMAGE requires a BMP file')
                if image.width*image.height>16000000:raise ValueError('IMAGE exceeds allocation limit')
                x,y,r,b=self.image_box((x,y,x+image.width,y+image.height))
                width,height=r-x,b-y
                if width<=0 or height<=0:return
                ow,oh=screen.overlay.size
                if r<=0 or b<=0 or x>=ow or y>=oh:return
                if width*height>32000000:raise ValueError('Scaled IMAGE exceeds allocation limit')
                image.load()
                # Preserve exact black transparency and bitwise raster colors.
                if image.size!=(width,height):
                    image=image.resize((width,height),getattr(Image,'Resampling',Image).NEAREST)
                screen.draw(image,x,y,operation)
        elif command=='finished':
            self.done=True;self.code=value;self.mouse_active=False
        else:raise ValueError('Unknown GUI operation: '+command)
    def pump(self):
        if self.closed.is_set():return
        if self.active_input and self.active_input.get('deadline') is not None and time.monotonic()>=self.active_input['deadline']:
            self.complete(self.active_input,None);self.active_input=None
        if self.active_input and self.active_input['cancelled']:
            self.active_input=None;self.typed='';self.keys.clear();self.dirty=True
        for _ in range(200):
            try:request=self.requests.get_nowait()
            except queue.Empty:break
            if request['cancelled']:continue
            if request['command'] in ('input','key'):
                if self.active_input:self.complete(request,error=ValueError('Concurrent console input is unsupported'));continue
                if request['command']=='key':
                    request['deadline']=None if request['value'] is None else time.monotonic()+request['value']
                    request['value']='char'
                self.active_input=request;self.typed=''
                self.input_snapshot=(copy.deepcopy(self.screen.cells),self.screen.x,self.screen.y,self.screen.history.copy())
                self.consume_keys();continue
            try:self.complete(request,self.operation(request['command'],request['value']))
            except Exception as exc:self.complete(request,error=ValueError(str(exc)))
            if request['command'] not in ('move','position','mouse'):self.dirty=True
        if self.dirty:self.render();self.dirty=False
        self.after_id=self.root.after(10,self.pump)
    def render(self):
        from PIL import ImageTk
        screen=self.screen;self.canvas.delete('content')
        rows=screen.visible_rows()
        total=len(screen.history)+screen.lines;top=len(screen.history)-screen.view_offset
        self.scrollbar.set(top/total,(top+screen.lines)/total)
        self.canvas.config(background=color(screen.bg))
        for y,row in enumerate(rows):
            for x,(char,fg,bg) in enumerate(row):
                if bg!=screen.bg:self.canvas.create_rectangle(x*screen.cw,y*screen.ch,(x+1)*screen.cw,(y+1)*screen.ch,fill=color(bg),outline='')
        if not screen.view_offset:
            self.photo=ImageTk.PhotoImage(screen.overlay,master=self.root)
            self.canvas.create_image(0,0,anchor='nw',image=self.photo)
        for y,row in enumerate(rows):
            for x,(char,fg,bg) in enumerate(row):
                if char and char!=' ':
                    from .display_width import legacy_wide
                    width=screen.cw*(2 if x+1<screen.cols and row[x+1][0]=='' else 1)
                    if self.legacy_glyphs and legacy_wide(char[0]) and self.legacy_glyphs.draw(self.canvas,char,x*screen.cw,y*screen.ch,width,color(fg)):continue
                    self.canvas.create_text(x*screen.cw,y*screen.ch,anchor='nw',font=self.font,text=char,fill=color(fg))
        # Keep the cursor item alive above independently refreshed content.
        self.canvas.addtag_all('content');self.canvas.dtag('cursor','content')
        self.render_cursor()
    def render_cursor(self):
        screen=self.screen
        if self.done or screen.view_offset or not screen.cursor_visible:
            self.canvas.delete('cursor');return
        col,row=self.mouse_position if self.mouse_active and self.mouse_position is not None else (min(screen.x,screen.cols-1),screen.y)
        x=col*screen.cw;y=row*screen.ch
        coords=(x,y+screen.ch-2,x+screen.cw,y+screen.ch-2)
        if self.canvas.find_withtag('cursor'):
            self.canvas.coords('cursor',*coords)
            self.canvas.itemconfigure('cursor',fill=color(screen.fg))
        else:self.canvas.create_line(*coords,fill=color(screen.fg),tags=('cursor',))
        self.canvas.tag_raise('cursor')
    def mouse(self,event,button):
        self.canvas.focus_set()
        if self.mouse_active and not self.screen.view_offset:
            from .cmos import Mouse
            self.mouse_events.put(Mouse(event.x//self.screen.cw,event.y//self.screen.ch,button))
    def paste(self,event=None):
        try:text=self.root.clipboard_get()
        except Exception:return 'break'
        self.screen.view_offset=0;self.dirty=True
        self.keys.extend(text.replace('\r\n','\n').replace('\r','\n'));self.consume_keys();return 'break'
    def key(self,event):
        self.key_epoch+=1
        if event.state&1 and event.keysym in ('Prior','Next','Home','End'):
            if event.keysym in ('Home','End'):return self.scroll('moveto',0 if event.keysym=='Home' else 1)
            return self.scroll('scroll',-1 if event.keysym=='Prior' else 1,'pages')
        if event.char or event.keysym in ('BackSpace','Return','KP_Enter'):
            self.screen.view_offset=0;self.dirty=True
        if event.keysym.lower()=='c' and event.state&4:
            if not self.done:self.cancel.set()
            self.keys.clear();return 'break'
        if self.timeout_waiters and not self.active_input:return 'break'
        if event.keysym=='BackSpace':self.keys.append('\b')
        elif event.keysym in ('Return','KP_Enter'):self.keys.append('\n')
        elif event.char and not event.state&4:self.keys.extend(event.char)
        self.consume_keys();return 'break'
    def consume_keys(self):
        while self.active_input and self.keys:
            self.key_epoch+=1
            key=self.keys.popleft();request=self.active_input
            if request['value']=='char':
                self.active_input=None;self.complete(request,key);break
            if key=='\b':self.typed=self.typed[:-1]
            elif key=='\n':
                self.screen.write('\r\n');self.active_input=None
                self.complete(request,self.typed+'\r\n');self.typed='';self.dirty=True;break
            elif ord(key)>=32 or key=='\t':self.typed+=key
            cells,x,y,history=self.input_snapshot
            self.screen.history=history.copy()
            self.screen.cells=copy.deepcopy(cells);self.screen.x=x;self.screen.y=y;self.screen.write(self.typed);self.dirty=True
    def close(self):
        if self.closed.is_set():return
        self.closed.set();self.cancel.set()
        self.root.after_cancel(self.after_id);self.root.update_idletasks()
        # Release all Tcl-owned objects on the Tk thread. The interpreter worker
        # may otherwise be the thread that later collects the console cycle.
        self.photo=None;self.font=None;self.legacy_glyphs=None
        self.root.destroy()

    def dispose(self):
        # Run after mainloop/update returns: Tk's callback wrapper still needs
        # root.tk to unregister itself while the close callback is unwinding.
        self.canvas.tk=None;self.scrollbar.tk=None;self.root.tk=None
        self.canvas=None;self.root=None
    def start(self,args,kwargs):
        from .runtime import Runtime
        self.runtime=Runtime(stdin=self.stdin,stdout=self.stdout,stderr=self.stderr,**kwargs)
        self.runtime.console=self
        self.screen.xp=self.runtime.xp
        if self.screen.xp:
            from .gui_glyphs import LegacyGlyphs
            self.legacy_glyphs=LegacyGlyphs(self.root,self.screen.cw,self.screen.ch,self.font_pixels)
        def run():
            code=0
            try:
                rt=self.runtime
                code=rt.batch(args.batch,args.args) if args.batch else rt.entry(args.command) if args.command is not None else rt.interactive()
                if rt.state.unsupported:code=125
            except KeyboardInterrupt as exc:
                self.runtime.diagnostics.interrupted(exc);code=0xc000013a
                if not self.closed.is_set():self.stdout.write_text('\r\n^C\r\n')
            except Exception as exc:
                code=1
                if not self.closed.is_set():self.stderr.write_text('\r\nGUI execution error: '+str(exc)+'\r\n')
            finally:
                self.runtime.streams.close_owned()
                if not self.closed.is_set():
                    self.stdout.write_text(f'\r\n[Process exited: {code}; close window to finish]\r\n')
                    self.call('finished',code,interruptible=False)
        self.worker=threading.Thread(target=run,name='pycmd-interpreter',daemon=True);self.worker.start()


def run_gui(args,kwargs):
    import tkinter as tk
    # Set awareness before creating any Tk windows. System awareness lets older
    # Tk versions render at native DPI without requiring WM_DPICHANGED handling.
    import sys
    if sys.platform=='win32':
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
    root=tk.Tk();console=GuiConsole(root,fontsize=args.fontsize);console.start(args,kwargs)
    try:root.mainloop()
    except KeyboardInterrupt:console.close()
    if console.worker:console.worker.join(timeout=1)
    console.dispose()
    return console.code if console.done else 0xc000013a
