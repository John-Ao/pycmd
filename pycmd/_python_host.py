"""Portable Python process adapter: Windows text newlines and full 32-bit exit capture.

Used only when explicitly enabled by the regression runner. Executes the actual
script, never recognizes probe modes or invents observations.
"""
import io
import json
import os
import runpy
import sys
import traceback
record=os.environ.pop('_PYCMD_EXIT_RECORD')
script=sys.argv[1];sys.argv=sys.argv[1:]
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8',newline='\r\n',write_through=True)
sys.stderr=io.TextIOWrapper(sys.stderr.buffer,encoding='utf-8',newline='\r\n',write_through=True)
# Apply the platform default only to text writes; binary I/O remains byte-exact.
import builtins
native_open=builtins.open
native_io_open=io.open
class WindowsOpen:
    def __init__(self,delegate):self.delegate=delegate
    def __call__(self,file,mode='r',buffering=-1,encoding=None,errors=None,newline=None,closefd=True,opener=None):
        if 'b' not in mode and any(ch in mode for ch in 'wax+') and newline is None:newline='\r\n'
        return self.delegate(file,mode,buffering,encoding,errors,newline,closefd,opener)
builtins.open=WindowsOpen(native_open)
io.open=WindowsOpen(native_io_open)
code=0
try:runpy.run_path(script,run_name='__main__')
except SystemExit as exc:
    code=exc.code if isinstance(exc.code,int) else 0 if exc.code is None else 1
    if not isinstance(exc.code,(int,type(None))):print(exc.code,file=sys.stderr)
except BaseException:
    traceback.print_exc();code=1
finally:
    with open(record,'w',encoding='ascii') as out:json.dump({'code':code},out)
sys.exit(code&255)
