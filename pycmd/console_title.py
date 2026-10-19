"""Best-effort host title update, separate from redirected command output."""
import os


def update(rt,title):
    if rt.console is not None:
        rt.console.call('title',title);return
    # Embedded/captured sessions retain their logical title without touching the
    # application's controlling terminal.
    terminals=[stream for stream in rt.streams.table.values()
               if getattr(stream,'isatty',lambda:False)()]
    if not terminals:return
    try:
        if os.name=='nt':
            import ctypes as C
            kernel=C.WinDLL('kernel32',use_last_error=True)
            kernel.SetConsoleTitleW.argtypes=[C.c_wchar_p]
            kernel.SetConsoleTitleW.restype=C.c_int
            kernel.SetConsoleTitleW(title)
            return
        # OSC cannot contain terminators or other terminal control characters.
        text=''.join(c for c in title if ord(c)>=32 and not 127<=ord(c)<=159)
        packet=('\x1b]0;'+text+'\x07').encode('utf-8')
        # Saved redirection handles can still point at the original output TTY.
        for fd,stream in rt.streams.table.items():
            if fd!=0 and stream in terminals and getattr(stream,'writable',lambda:True)():
                if hasattr(stream,'write_control'):stream.write_control(packet)
                else:stream.write(packet);stream.flush()
                return
        with open('/dev/tty','wb',buffering=0) as stream:stream.write(packet)
    except (OSError,ValueError):
        # TITLE historically preserves ERRORLEVEL, including in headless runs.
        pass
