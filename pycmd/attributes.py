"""DOS file attributes, persisted as host metadata where available."""
import os
from pathlib import Path

BITS={'r':1,'h':2,'s':4,'d':16,'a':32,'i':8192}
_fallback={}
def get(path):
    path=Path(path)
    if os.name=='nt':return path.stat().st_file_attributes
    try:return int(os.getxattr(path,b'user.pycmd.attributes'))
    except (OSError,AttributeError):return _fallback.get(str(path.resolve()),16 if path.is_dir() else 32)
def set(path,value):
    path=Path(path)
    if os.name=='nt':
        import ctypes
        if not ctypes.windll.kernel32.SetFileAttributesW(str(path),value):raise OSError('Cannot set file attributes')
    else:
        try:os.setxattr(path,b'user.pycmd.attributes',str(value).encode('ascii'))
        except (OSError,AttributeError):_fallback[str(path.resolve())]=value

def selected(path,expression):
    flags=get(path);negate=False
    for ch in expression.lower():
        if ch=='-':negate=True;continue
        if ch not in BITS:continue
        if bool(flags&BITS[ch])==negate:return False
        negate=False
    return True
