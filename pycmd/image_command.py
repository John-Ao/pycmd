"""Tutorial-compatible IMAGE frontend; rendering is confined to GUI overlay."""
import re
from .syntax import crt_split

HELP=('IMAGE bmpfile X Y [/operation]\r\nIMAGE /d\r\nIMAGE /s X Y Width Height\r\n'
      'Zero-based logical pixels (16 per text row); default SRCCOPY. Requires --gui.\r\n'
      'Operations: TRANSPARENTBLT BLACKNESS DSTINVERT MERGECOPY MERGEPAINT\r\n'
      'NOTSRCCOPY NOTSRCERASE PATCOPY PATPAINT PATINVERT SRCAND SRCCOPY\r\n'
      'SRCERASE SRCINVERT SRCPAINT WHITENESS\r\n')

def parse(arg):
    parts=crt_split(arg)
    if len(parts)==1 and parts[0].lower()=='/d':return ('clear_image',None)
    def numbers(items):
        if any(not re.fullmatch(r'[+-]?[0-9]+',n) for n in items):raise ValueError('IMAGE coordinates must be integers')
        return tuple(map(int,items))
    if parts and parts[0].lower()=='/s':
        if len(parts)!=5:raise ValueError('Expected IMAGE /s X Y Width Height')
        x,y,w,h=numbers(parts[1:])
        if w<=0 or h<=0:raise ValueError('IMAGE dimensions must be positive')
        return ('clear_image',(x,y,x+w,y+h))
    if len(parts) not in (3,4):raise ValueError('Expected IMAGE bmpfile X Y [/operation]')
    x,y=numbers(parts[1:3]);operation='SRCCOPY'
    if len(parts)==4:
        if not parts[3].startswith('/'):raise ValueError('Expected /operation')
        operation=parts[3][1:].upper()
    return ('image',(parts[0],x,y,operation))

def execute(rt,arg):
    if arg.strip()=='/?':rt.write(HELP);return rt.result(0,0)
    try:
        command,value=parse(arg)
        if rt.console is None:raise ValueError('IMAGE requires --gui')
        if command=='image':
            filename,x,y,operation=value
            value=(str(rt.read_path(filename)),x,y,operation)
        rt.console.call(command,value)
        return rt.result(0,0)
    except (OSError,ValueError) as exc:
        rt.write('IMAGE: '+str(exc)+'\r\n',2);return rt.result(1,1)
