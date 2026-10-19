"""Portable TIMEOUT console wait; no subprocess is required."""
import re
import time
from .syntax import crt_split
from .console_tools import key_reader

def parse(arg):
    args=crt_split(arg);seconds=None;nobreak=False;i=0
    while i<len(args):
        value=args[i];i+=1
        if value.lower()=='/nobreak':
            if nobreak:raise ValueError('Duplicate /NOBREAK')
            nobreak=True;continue
        if value.lower()=='/t':
            if i==len(args):raise ValueError('Missing timeout value')
            value=args[i];i+=1
        if seconds is not None or not re.fullmatch(r'-?[0-9]+',value):raise ValueError('Invalid timeout argument')
        seconds=int(value,10)
    if seconds is None or not -1<=seconds<=99999:raise ValueError('Timeout must be between -1 and 99999')
    return seconds,nobreak

def execute(rt,arg):
    if arg.strip()=='/?':
        rt.write('TIMEOUT /T seconds [/NOBREAK]\r\nSeconds: -1 through 99999.\r\n');return rt.result(0,0)
    try:seconds,nobreak=parse(arg)
    except ValueError as exc:rt.write('TIMEOUT: '+str(exc)+'\r\n',2);return rt.result(1,1)
    if not getattr(rt.streams.table[0],'isatty',lambda:False)():
        rt.write('ERROR: Input redirection is not supported, exiting the process immediately.\r\n',2)
        return rt.result(1,1)
    rt.write(('Waiting indefinitely' if seconds<0 else f'Waiting for {seconds} seconds')+
             (', press CTRL+C to quit . . .' if nobreak else ', press a key to continue . . .'))
    deadline=None if seconds<0 else time.monotonic()+seconds
    if rt.console is not None:
        # Observe key activity without competing for the controller's input RPC.
        epoch=rt.console.call('timeout_wait',True)
        try:
            while deadline is None or time.monotonic()<deadline:
                rt.console.check_interrupt()
                if not nobreak and rt.console.key_epoch!=epoch:break
                rt.console.sleep(.02 if deadline is None else min(.02,max(0,deadline-time.monotonic())))
        finally:rt.console.call('timeout_wait',False,interruptible=False)
    elif nobreak:
        while deadline is None or time.monotonic()<deadline:
            time.sleep(.05 if deadline is None else min(.05,max(0,deadline-time.monotonic())))
    else:
        with key_reader(rt) as read:
            left=None if deadline is None else max(0,deadline-time.monotonic())
            if left!=0:read(left)
    rt.write('\r\n');return rt.result(0,0)
