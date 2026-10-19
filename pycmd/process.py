"""External process transport; raw byte streams are independent of Python text output."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from .syntax import crt_split,Unsupported

def launch(runtime,text):
    argv=crt_split(text)
    if not argv:return 0
    if not runtime.allow_external:raise Unsupported('External launch: '+argv[0])
    if runtime.console is not None and any(hasattr(runtime.streams.table[fd],'console') for fd in (0,1,2)):
        raise Unsupported('GUI external processes require redirected stdin, stdout and stderr; native terminal emulation is not implemented')
    if runtime.python_adapter and argv[0].lower() in ('python.exe','python3.exe'):argv[0]=sys.executable
    located=runtime.lookup(argv[0])
    if located and os.name!='nt':argv[0]=str(located)
    if os.name!='nt' and (located is None or not os.access(located,os.X_OK)):raise FileNotFoundError(argv[0])
    with ExitStack() as stack:
        streams=[];bridges=[]
        for fd in (0,1,2):
            stream=runtime.streams.table[fd]
            try:stream.fileno();native=stream
            except (AttributeError,OSError):
                native=stack.enter_context(tempfile.TemporaryFile())
                if fd==0:
                    start=stream.tell();native.write(stream.read());stream.seek(start);native.seek(0)
                else:start=0
                bridges.append((fd,stream,native,start))
            if fd==0 and native.seekable():
                position=native.tell();native.seek(0,2);native.seek(position)
            streams.append(native)
        env=dict(runtime.state.env);record=None
        command=text if os.name=='nt' else argv
        if runtime.python_adapter and os.name!='nt' and Path(argv[0]).resolve()==Path(sys.executable).resolve() and len(argv)>1 and not argv[1].startswith('-'):
            folder=stack.enter_context(tempfile.TemporaryDirectory(prefix='pycmd-exit-'))
            record=Path(folder)/'exit.json';env['_PYCMD_EXIT_RECORD']=str(record)
            command=[sys.executable,str(Path(__file__).with_name('_python_host.py'))]+argv[1:]
        try:
            code=subprocess.run(command,cwd=runtime.state.cwd,env=env,stdin=streams[0],stdout=streams[1],stderr=streams[2],shell=False,timeout=runtime.process_timeout).returncode
        except subprocess.TimeoutExpired as exc:raise Unsupported('External process timeout: '+argv[0]) from exc
        for fd,stream,native,start in bridges:
            if fd==0:stream.seek(start+native.tell())
            else:native.seek(0);stream.write(native.read())
        if record and record.exists():code=json.loads(record.read_text())['code']
        return code
