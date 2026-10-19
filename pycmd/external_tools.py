"""Small portable external-tool adapters; these are not CMD builtins.

Only the basic file-I/O subset is supplied. An explicitly empty PATH disables
name lookup, as it does for native external utilities in the research inventory.
"""
import codecs
from . import attributes
from .syntax import crt_split,Unsupported

def execute(rt,name,arg):
    if name not in ('attrib','chcp','find','findstr','sort','more','wmic'):return None
    if 'PATH' in rt.state.env and not rt.state.env['PATH']:return None
    if name=='wmic':
        from .wmic_command import execute
        return execute(rt,arg)
    if name=='chcp':
        if not arg:rt.write('Active code page: '+str(getattr(rt.state,'codepage',437))+'\r\n');return 0
        try:
            cp=int(arg.strip());encoding='utf-8' if cp==65001 else 'cp'+str(cp);codecs.lookup(encoding)
        except (ValueError,LookupError):rt.write('Invalid code page\r\n',2);return 1
        rt.state.encoding=encoding;rt.state.codepage=cp;rt.write('Active code page: '+str(cp)+'\r\n');return 0
    args=crt_split(arg)
    if name=='attrib':
        from .filesystem import expand
        changes=[];options=[];paths=[]
        for item in args:
            if len(item)==2 and item[0] in '+-' and item[1].lower() in attributes.BITS:changes.append(item.lower())
            elif item.startswith('/'):options.append(item.lower())
            else:paths.append(item)
        if any(o not in ('/s','/d','/l') for o in options):raise Unsupported('ATTRIB option')
        code=0
        for pattern in paths or ['*']:
            files=expand(rt,pattern,'/s' in options)
            for path in files:
                if path.is_dir() and '/d' not in options:continue
                value=attributes.get(path)
                if changes:
                    for change in changes:
                        bit=attributes.BITS[change[1]]
                        value=value|bit if change[0]=='+' else value&~bit
                    attributes.set(path,value)
                else:
                    flags=''.join(letter.upper() if value&attributes.BITS[letter] else ' ' for letter in 'arshi')
                    rt.write(flags+'        '+str(path)+'\r\n')
        return code
    options=[x.lower() for x in args if x.startswith('/')];args=[x for x in args if not x.startswith('/')]
    pattern=None;patterns=[]
    if name=='findstr':
        patterns=[(x[3:],True) for x in crt_split(arg) if x.lower().startswith('/c:')]
    if name in ('find','findstr'):
        if not patterns:
            if not args:rt.write('FIND: Parameter format not correct\r\n',2);return 2
            pattern=args.pop(0)
            patterns=[(p,name=='find' or '/l' in options) for p in (pattern.split() if name=='findstr' else [pattern])]
        else:pattern=''
    data=b''
    if args:
        for name_ in args:
            try:data+=rt.path(name_).read_bytes()
            except OSError:rt.write('The system cannot find the file specified.\r\n',2);return 2
    else:data=rt.streams.table[0].read()
    lines=data.decode(rt.state.encoding,errors='replace').splitlines()
    if name=='sort':
        if any(x not in ('/r','/+1') for x in options):raise Unsupported('SORT option')
        lines.sort(key=str.upper,reverse='/r' in options)
    elif pattern is not None:
        import re
        expressions=[]
        for needle,literal in patterns:
            expression=re.escape(needle) if literal and '/r' not in options else needle
            if name=='findstr':
                if '/b' in options or '/x' in options:expression='^(?:'+expression+')'
                if '/e' in options or '/x' in options:expression='(?:'+expression+')$'
            try:expressions.append(re.compile(expression,re.I if '/i' in options else 0))
            except re.error:rt.write('FINDSTR: Invalid search string\r\n',2);return 2
        found=[]
        for i,line in enumerate(lines,1):
            matched=any(expr.search(line) for expr in expressions)
            if matched!=('/v' in options):found.append((str(i)+':' if '/n' in options else '')+line)
        lines=found
        if '/c' in options:rt.write(str(len(lines))+'\r\n');return 0 if lines else 1
    for line in lines:rt.write(line+'\r\n')
    if name=='more':rt.write('\r\n')
    return 0 if pattern is None or lines else 1
