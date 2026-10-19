"""Independent START child, also usable from a source checkout."""
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pycmd import Runtime
import json
parents=json.loads(sys.argv[2]) if len(sys.argv)>2 else None
options=json.loads(sys.argv[3]) if len(sys.argv)>3 else {}
runtime=Runtime(env=os.environ,stdin=sys.stdin.buffer,stdout=sys.stdout.buffer,stderr=sys.stderr.buffer,allow_external=True,traceback=parents is not None,**options)
if parents is not None:runtime.diagnostics.parents=parents
code=runtime.command(sys.argv[1]);runtime.streams.close_owned()
raise SystemExit(code&255)
