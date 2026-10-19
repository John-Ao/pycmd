"""Consumer-specific byte readers; SET/P is not Python readline."""
import re

def setp(stream,encoding):
    # Console reads return one entered line; BufferedReader.read(size) waits
    # for additional lines until size/EOF and must not be used for a terminal.
    if getattr(stream,'isatty',lambda:False)():
        data=stream.readline(1023)
        value=data.rstrip(b'\r\n').split(b'\0',1)[0]
        return value.decode(getattr(stream,'host_encoding',encoding),errors='replace') if value else None
    data=stream.read(1023)
    # A CR/LF run containing both kinds terminates; consume through its first unlike pair.
    match=re.search(b'\r\n|\n\r',data)
    consumed=match.end() if match else len(data)
    value=data[:match.start()] if match else data
    value=value.rstrip(b'\r\n')
    if consumed<len(data):
        try:
            if stream.seekable():stream.seek(consumed-len(data),1)
        except (OSError,AttributeError):pass
    if not value:return None
    return value.split(b'\0',1)[0].decode(encoding,errors='replace')

def for_lines(data,encoding,command=False):
    # File NUL ends the unfinished record; command-source NUL truncates its C-string chunk.
    if b'\0' in data:
        prefix=data.split(b'\0',1)[0]
        if not command:
            cut=prefix.rfind(b'\n');data=prefix[:cut+1] if cut>=0 else b''
        else:data=prefix
    for line in data.split(b'\n'):
        if line.endswith(b'\r'):line=line[:-1]
        yield line.decode(encoding,errors='replace')


def batch_line(stream):
    """Read a live BAT record, retaining the stream's actual next byte offset.

    CR is ignored; LF and Ctrl-Z terminate records. A nonempty NUL segment
    skips through the next unlike CR/LF pair, then joins a fresh segment.
    An empty NUL segment terminates this reader, including future reads.
    """
    position=stream.tell();raw=stream.readline()
    if b'\0' not in raw and b'\x1a' not in raw:return raw.replace(b'\r',b'')
    stream.seek(position)
    out=bytearray();segment=0
    while True:
        byte=stream.read(1)
        if not byte:return bytes(out)
        if byte==b'\0':
            if segment==0:
                stream.seek(0,2);return bytes(out)
            previous=b''
            while True:
                byte=stream.read(1)
                if not byte:return bytes(out)
                if previous+byte in (b'\r\n',b'\n\r'):break
                previous=byte
            segment=0
        elif byte in (b'\n',b'\x1a'):return bytes(out)+b'\n'
        elif byte!=b'\r':out+=byte;segment+=1


# Re-read file contents at each jump; reuse only their decoded label index.
# A content key also detects same-size rewrites with unchanged timestamps.
from functools import lru_cache
from io import BytesIO

def label_index(data,encoding):
    return _cached_label_index(data,encoding) if len(data)<=1048576 else _label_index(data,encoding)

@lru_cache(maxsize=16)
def _cached_label_index(data,encoding):
    return _label_index(data,encoding)

def _label_index(data,encoding):
    file=BytesIO(data);entries=[]
    while True:
        raw=file.readline()
        if not raw:break
        text=raw.decode(encoding,errors='replace').strip()
        if text.startswith(':'):
            names=text[1:].split()[:1]
            if names:entries.append((names[0].lower(),file.tell()))
    return tuple(entries)
