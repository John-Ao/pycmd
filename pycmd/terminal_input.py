"""One owner for terminal bytes; avoid BufferedReader read-ahead across SET/P."""
from collections import deque
import os
import threading


class TerminalInput:
    def __init__(self,stream):
        self.stream=stream
        self.lock=threading.RLock()
        self.pending=deque()

    def fileno(self):return self.stream.fileno()
    def isatty(self):return True
    def seekable(self):return False
    def __getattr__(self,name):return getattr(self.stream,name)

    def unread(self,data):
        with self.lock:self.pending.extend(data)

    def read(self,size=-1):
        with self.lock:
            if size==0:return b''
            if self.pending:
                count=len(self.pending) if size<0 else min(size,len(self.pending))
                return bytes(self.pending.popleft() for _ in range(count))
            return os.read(self.fileno(),4096 if size<0 else size)

    def readline(self,size=-1):
        with self.lock:
            line=bytearray()
            while size<0 or len(line)<size:
                char=self.read(1)
                if not char:break
                line.extend(char)
                if char==b'\n':break
            return bytes(line)


def managed(stream):
    if isinstance(stream,TerminalInput):return stream
    if getattr(stream,'isatty',lambda:False)():
        try:stream.fileno()
        except (OSError,ValueError,AttributeError):return stream
        return TerminalInput(stream)
    return stream
