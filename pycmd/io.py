"""Stream table for ordinary redirections; high-slot lifecycle is explicitly gated."""
from contextlib import contextmanager
from dataclasses import dataclass
import io
import re
from .syntax import Unsupported, SyntaxFailure, ParseFailure, unescape

@dataclass
class Redirect:
    target: int
    mode: str
    source: str

def extract(text):
    if '<' not in text and '>' not in text:return text,[]
    out=[];redirects=[];i=0;quote=False;last_end=None
    while i<len(text):
        ch=text[i]
        if ch=='^' and not quote and i+1<len(text):out.extend(text[i:i+2]);i+=2;continue
        if ch=='"':quote=not quote
        if ch not in '<>' or quote:out.append(ch);i+=1;continue
        numbered=bool(out and out[-1].isdigit() and (len(out)==1 or out[-2] in ' \t'))
        target=int(out.pop()) if numbered else (0 if ch=='<' else 1)
        if numbered and last_end is not None and not text[last_end:i-1].strip():
            while out and out[-1] in ' \t':out.pop()
            out.append(' ')
        mode=ch;i+=1
        if ch=='>' and i<len(text) and text[i]=='>':mode='>>';i+=1
        while i<len(text) and text[i] in ' \t':i+=1
        if i<len(text) and text[i]=='&':
            i+=1
            if i>=len(text) or not text[i].isdigit():raise ParseFailure(str(target)+mode+'& was unexpected at this time.')
            source=text[i];i+=1;mode='copy'
        else:
            start=i;q=False
            while i<len(text):
                if text[i]=='^' and not q:i+=2;continue
                if text[i]=='"':q=not q
                elif not q and text[i] in ' \t<>':break
                i+=1
            source=text[start:i]
            if not source or source[0] in '&|':raise ParseFailure((source[:1] or '&')+' was unexpected at this time.')
        # Earlier same-target entries never open their files.
        redirects=[r for r in redirects if r.target!=target]
        redirects.append(Redirect(target,mode,source));last_end=i
    return ''.join(out),redirects

class Streams:
    def __init__(self,stdin=None,stdout=None,stderr=None):
        from .terminal_input import managed
        self.owned=set()
        self.table={0:managed(stdin) if stdin is not None else io.BytesIO(),
                    1:stdout if stdout is not None else io.BytesIO(),
                    2:stderr if stderr is not None else io.BytesIO()}
    def write(self,fd,data):
        self.table[fd].write(data)
        self.table[fd].flush()
    def close_owned(self):
        for stream in self.owned:stream.close()
        self.owned.clear()

    @contextmanager
    def redirected(self,redirects,runtime):
        # Backups live in the SAME logical table as user numbered handles.
        # Saving precedes source resolution, and restoration reads the current slot.
        records=[];opened=[]
        try:
            for r in redirects:
                backup=None
                if r.target in self.table:
                    backup=3
                    while backup in self.table:backup+=1
                    self.table[backup]=self.table[r.target]
                records.append((r.target,backup))
                self.table.pop(r.target,None)
                if r.mode=='copy':
                    source=int(r.source)
                    if source not in self.table:raise HandleCopyError(r.target)
                    stream=self.table[source]
                else:
                    target=unescape(runtime.expand_execution(r.source)).replace('"','')
                    path=runtime.null_path if target.upper()=='NUL' else runtime.read_path(target) if r.mode=='<' else runtime.path(target)
                    stream=open(path,{'<':'rb','>':'wb','>>':'ab'}[r.mode],buffering=0);opened.append(stream);self.owned.add(stream)
                self.table[r.target]=stream
            yield
        finally:
            for target,backup in records:
                if backup is None:self.table.pop(target,None)
                elif backup in self.table:
                    self.table[target]=self.table[backup]
                    self.table.pop(backup,None)
                # A missing backup leaves the current target intact (observed failure path).
            for stream in opened:
                if not any(stream is s for s in self.table.values()):stream.close();self.owned.discard(stream)

class HandleCopyError(OSError):
    def __init__(self,target):self.target=target;super().__init__('Invalid logical handle')


def leading(text):
    """Separate only leading redirections, preserving control-command body grammar."""
    end=0;i=0
    while i<len(text):
        start=i
        while i<len(text) and text[i].isspace():i+=1
        if i+1<len(text) and text[i].isdigit() and text[i+1] in '<>':i+=1
        if i>=len(text) or text[i] not in '<>':return text[:end],text[end:].lstrip()
        op=text[i];i+=1
        if i<len(text) and text[i]==op:i+=1
        while i<len(text) and text[i] in ' \t':i+=1
        if i<len(text) and text[i]=='&':
            i+=1
            if i<len(text):i+=1
        else:
            quote=False
            while i<len(text):
                if text[i]=='^' and not quote:i+=2;continue
                if text[i]=='"':quote=not quote
                elif not quote and text[i] in ' \t<>&|':break
                i+=1
        end=i
    return text[:end],text[end:]
