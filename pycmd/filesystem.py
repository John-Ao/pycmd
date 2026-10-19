"""File-command parameter handling and Windows-style wildcard transforms."""
from datetime import datetime
import fnmatch
import os
from pathlib import Path
import re
import shutil
from .syntax import crt_split
from . import attributes

NAMES=set('copy del dir erase md mkdir move rd ren rename rmdir type'.split())
def matches(name,mask):
    if mask in ('*','*.*'):return True
    if mask.endswith('.') and '.' not in name:return fnmatch.fnmatchcase(name.casefold(),mask[:-1].casefold())
    # DOS '?' can match missing suffix characters at a dot or end of name.
    regex=''
    for ch in mask:
        if ch=='*':regex+='.*'
        elif ch=='?':regex+='[^.]?'
        else:regex+=re.escape(ch)
    return re.fullmatch(regex,name,re.I) is not None

def short_name(path):
    if os.name=='nt':
        import ctypes
        buffer=ctypes.create_unicode_buffer(32768)
        if ctypes.windll.kernel32.GetShortPathNameW(str(path),buffer,len(buffer)):return Path(buffer.value).name
    stem,sep,ext=path.name.rpartition('.')
    if not sep:stem=path.name;ext=''
    clean=lambda x:re.sub(r'[^A-Z0-9_$~!#%&{}()@`\'-]','',x.upper())
    base=clean(stem);suffix=clean(ext)[:3]
    if len(stem)<=8 and len(ext)<=3 and base==stem.upper() and suffix==ext.upper():return path.name.upper()
    prefix=(base or '_')[:6];number=1
    if len(prefix)<=2:
        units=[ord(ch) for ch in path.name];checksum=units[0] if units else 0
        if len(units)>1:checksum=((units[0]<<8)+units[1])&65535
        for index in range(2,len(units),2):checksum=((checksum>>1)+(((checksum<<7)+units[index])<<8)+(units[index+1] if index+1<len(units) else 0))&65535
        prefix+=format(checksum,'04X')[::-1]
    if path.parent.is_dir():
        for sibling in path.parent.iterdir():
            if sibling.name==path.name:break
            if clean(sibling.stem).startswith(prefix):number+=1
    return prefix+'~'+str(number)+('.'+suffix if suffix else '')

def expand(rt,pattern,recursive=False):
    path=rt.path(pattern.strip('"'));parent=path.parent;mask=path.name
    if not any(ch in mask for ch in '*?'):
        return [path] if path.exists() else []
    if not parent.is_dir():return []
    entries=parent.rglob('*') if recursive else parent.iterdir()
    return sorted((p for p in entries if (matches(p.name,mask) or ('.' in mask and not mask.endswith('.') and matches(short_name(p),mask)))),key=lambda p:str(p).casefold())

def rename_target(name,mask):
    """Observed target cursor rules: star seeks the last exact next literal."""
    if not any(c in mask for c in '*?'):return mask.rstrip('. ')
    source=0;out=[];i=0
    while i<len(mask):
        ch=mask[i]
        if ch=='*':
            following=mask[i+1:i+2]
            end=name.rfind(following,source) if following and following not in '*?' else -1
            if end<0:end=len(name)
            out.append(name[source:end]);source=end
        elif ch=='?':
            if source<len(name) and name[source]!='.':out.append(name[source]);source+=1
        elif ch=='.':
            end=name.find('.',source);source=len(name) if end<0 else end+1;out.append('.')
        else:
            out.append(ch)
            if source<len(name) and name[source]!='.':source+=1
        i+=1
    return ''.join(out).rstrip('. ')

def split_options(arg):
    words=crt_split(arg);opts=[];paths=[]
    for word in words:
        if word.startswith('/') and not Path(word).exists():opts.append(word.lower())
        else:paths.append(word)
    return opts,paths

def execute(rt,name,arg):
    opts,args=split_options(arg)
    if any(o in ('/?','-?') for o in opts):
        rt.write(name.upper()+' - Python CMD compatible file operation\r\n');return rt.result(0)
    if name=='copy':return copy(rt,arg)
    if name=='dir':return directory(rt,opts,args)
    if name in ('md','mkdir'):
        if not args:return syntax(rt)
        code=0
        for item in args:
            target=rt.path(item)
            try:target.mkdir(parents=rt.state.extensions)
            except FileExistsError:rt.write('A subdirectory or file '+item+' already exists.\r\n',2);code=1
            except OSError:rt.write('The directory or file cannot be created.\r\n',2);code=1
        return rt.result(code,code)
    if name in ('rd','rmdir'):
        if not args:return syntax(rt)
        code=0
        for item in args:
            path=rt.path(item)
            if '/s' in opts and '/q' not in opts and not confirm(rt,item+', Are you sure (Y/N)? ',False):continue
            try:
                if not path.exists():raise FileNotFoundError()
                if not path.is_dir():raise NotADirectoryError()
                if path.resolve()==rt.state.cwd.resolve():
                    if '/s' in opts:
                        for entry in path.iterdir():shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
                    rt.write('The process cannot access the file because it is being used by another process.\r\n',2);code=1;continue
                if '/s' in opts:shutil.rmtree(path)
                else:path.rmdir()
            except FileNotFoundError:rt.write('The system cannot find the file specified.\r\n',2);code=1
            except NotADirectoryError:rt.write('The directory name is invalid.\r\n',2);code=1
            except OSError:rt.write('The directory is not empty.\r\n',2);code=145
        return rt.result(code)
    if name=='type':
        if not args or opts:return syntax(rt)
        code=0
        for item in args:
            files=[p for p in expand(rt,item) if not attributes.get(p)&6]
            if not files and rt.read_path(item).exists():files=[rt.read_path(item)]
            if not files:
                rt.write('The system cannot find the file specified.\r\n',2)
                if len(args)>1:rt.write('Error occurred while processing: '+item+'.\r\n',2)
                code=1
            for file in files:
                try:
                    data=file.read_bytes()
                    if data and (len(args)>1 or '*' in item or '?' in item):rt.write('\r\n'+str(file.relative_to(rt.state.cwd)).replace('/','\\')+'\r\n\r\n\r\n',2)
                    rt.streams.write(1,data)
                except OSError:code=1;rt.write('Access is denied.\r\n',2)
        return rt.result(code,code)
    if name in ('del','erase'):
        if not args:return syntax(rt)
        attr=next((o[2:].lstrip(':') for o in opts if o.startswith('/a')),None)
        for item in args:
            files=expand(rt,item,'/s' in opts)
            if not files and len(args)==1:rt.write('Could Not Find '+str(rt.path(item))+'\r\n')
            for file in files:
                if file.is_dir():files.extend(sorted(file.iterdir()));continue
                if attr is not None and not attributes.selected(file,attr):continue
                if attr is None and attributes.get(file)&6:continue
                if '/p' in opts and not confirm(rt,'Delete '+str(file)+' (Y/N)? ',False):continue
                try:
                    if attributes.get(file)&1 and '/f' not in opts and not (attr is not None and 'r' in attr and '-r' not in attr):raise PermissionError()
                    file.unlink()
                except OSError:rt.write(str(file)+'\r\nAccess is denied.\r\n',2)
        return rt.result(0,0)
    if name in ('ren','rename'):
        if len(args)!=2:return syntax(rt)
        if '/' in args[1] or '\\' in args[1]:rt.write('The syntax of the command is incorrect.\r\n',2);return rt.result(1,1)
        files=[p for p in expand(rt,args[0]) if not attributes.get(p)&6 and (p.is_file() or not any(c in args[0] for c in '*?'))];code=0
        if not files:rt.write('The system cannot find the file specified.\r\n',2);return rt.result(1,1)
        for src in files:
            dest=src.parent/rename_target(src.name,args[1])
            if src==dest:continue
            if dest.exists():rt.write('A duplicate file name exists, or the file\r\ncannot be found.\r\n',2);code=1;continue
            try:src.rename(dest)
            except OSError:code=1;rt.write('Access is denied.\r\n',2)
        return rt.result(code,code)
    if name=='move':
        if len(args) not in (1,2):return syntax(rt)
        files=[p for p in expand(rt,args[0]) if not attributes.get(p)&6];target=rt.path(args[1] if len(args)>1 else '.');count=0
        if not files:rt.write('The system cannot find the file specified.\r\n',2);return rt.result(1,1)
        if len(files)>1 and not target.is_dir():
            rt.write('Cannot move multiple files to a single file.\r\n',2);return rt.result(1,1)
        directories=bool(files and files[0].is_dir())
        for src in files:
            dest=target/src.name if target.is_dir() else target
            if src.resolve()==dest.resolve():count+=1;continue
            if dest.exists() and attributes.get(dest)&1:
                rt.write('Access is denied.\r\n',2);continue
            if dest.exists() and '/y' not in opts and not confirm(rt,'Overwrite '+str(dest)+'? (Yes/No/All): '):continue
            try:shutil.move(str(src),str(dest));count+=1
            except OSError:
                message='The system cannot find the path specified.' if not dest.parent.exists() else 'The process cannot access the file because it is being used by another process.' if src.is_dir() and src in dest.parents else 'Access is denied.'
                rt.write(message+'\r\n',2)
        rt.write('        '+str(count)+(' dir(s)' if directories else ' file(s)')+' moved.\r\n');return rt.result(0 if count else 1,0 if count else 1)
    raise AssertionError(name)

def syntax(rt):rt.write('The syntax of the command is incorrect.\r\n',2);return rt.result(1,1)
def confirm(rt,prompt,allow_all=True):
    while True:
        rt.write(prompt);raw=rt.streams.table[0].readline()
        reply=raw.decode(rt.state.encoding,errors='replace').strip()
        rt.write(reply+'\r\n')
        if not raw or reply.lower().startswith('n'):return False
        if reply.lower().startswith('y') or (allow_all and reply.lower().startswith('a')):return True
def copy(rt,arg):
    # Keep switches adjacent to each operand: /A and /B are positional.
    tokens=re.findall(r'"[^"]*"|\+|[^\s+]+',arg)
    groups=[];current=[];mode=None;last=None;joined=False;options=[]
    for token in tokens:
        low=token.lower()
        if low in ('/a','/b'):
            mode=low
            if last is not None:last[1]=mode
        elif low.startswith('/') and not Path(token).exists():options.append(low)
        elif token=='+':joined=True
        else:
            item=[token.strip('"'),mode]
            if current and not joined:groups.append(current);current=[]
            current.append(item);last=item;joined=False
    if current:groups.append(current)
    if not groups:return syntax(rt)
    if len(groups)>2 or any(o not in ('/y','/-y','/v','/z','/d','/n') for o in options):return syntax(rt)
    specs=groups[0];targetspec=groups[1][0] if len(groups)>1 else ['.',mode]
    target=rt.path(targetspec[0]);sources=[];failed=False
    for i,(pattern,source_mode) in enumerate(specs):
        found=[rt.null_path] if rt.path(pattern)==rt.null_path else [p for p in expand(rt,pattern) if p.is_file() and not attributes.get(p)&6]
        if not found and i==0:
            if any(ch in pattern for ch in '*?'):
                rt.write(pattern+' \r\n        0 file(s) copied.\r\n');rt.write('The system cannot find the file specified.\r\n',2)
            else:rt.write('The system cannot find the file specified.\r\n')
            return rt.result(1,1)
        sources.extend((p,source_mode) for p in found)
    concatenate=len(specs)>1 or len(sources)>1 and not target.is_dir()
    if len(specs)>1 and len(groups)==1 and sources:target=sources[0][0]
    destination_mode=targetspec[1] or ('/a' if concatenate else '/b')
    count=0;chunks=[];denied=False
    for index,(src,source_mode) in enumerate(sources):
        dest=target/src.name if target.is_dir() else target
        if concatenate and index and src.resolve()==dest.resolve():continue
        if not concatenate and src.resolve()==dest.resolve():
            rt.write('The file cannot be copied onto itself.\r\n');failed=True;continue
        if dest.exists() and attributes.get(dest)&1:
            rt.write('Access is denied.\r\n',2);failed=True;continue
        try:data=src.read_bytes()
        except OSError:rt.write('Access is denied.\r\n',2);failed=True;continue
        source_mode=source_mode or ('/a' if concatenate else '/b')
        if source_mode=='/a':data=data.split(b'\x1a',1)[0]
        if len(sources)>1 or concatenate:rt.write(str(src.relative_to(rt.state.cwd)).replace('/','\\')+'\r\n')
        if concatenate:chunks.append(data);continue
        prompt=('/-y' in options or not rt.batch_path) and '/y' not in options and rt.state.env.get('COPYCMD','').upper()!='/Y'
        if '/-y' in options:prompt=True
        if dest.exists() and prompt:
            display=targetspec[0].rstrip('\\/')+('\\'+src.name if target.is_dir() else '')
            if not confirm(rt,'Overwrite '+display+'? (Yes/No/All): '):denied=True;continue
        try:
            dest.write_bytes(data+(b'\x1a' if destination_mode=='/a' and source_mode=='/a' else b''));attributes.set(dest,32);count+=1
        except OSError:rt.write('The system cannot find the path specified.\r\n',2);failed=True
    if concatenate and chunks:
        dest=target/sources[0][0].name if target.is_dir() else target
        try:
            dest.write_bytes(b''.join(chunks)+(b'\x1a' if destination_mode=='/a' else b''));attributes.set(dest,32);count=1
        except OSError:rt.write('The system cannot find the path specified.\r\n',2);failed=True
    rt.write('        '+str(count)+' file(s) copied.\r\n')
    code=1 if failed else 0
    return rt.result(code,code)


def directory(rt,opts,args):
    inherited=split_options(rt.state.env.get('DIRCMD',''))[0]
    combined=inherited+opts
    def flag(letter):
        enabled=False
        for option in combined:
            if option=='/'+letter:enabled=True
            elif option=='/-'+letter:enabled=False
        return enabled
    patterns=args or ['*'];bare=flag('b');recursive=flag('s')
    entries=[]
    for pattern in patterns:
        path=rt.path(pattern)
        if path.is_dir():pattern=str(path/'*')
        entries.extend(expand(rt,pattern,recursive))
    attr=None
    for option in combined:
        if option=='/-a':attr=None
        elif option.startswith('/a'):attr=option[2:].lstrip(':')
    if attr is not None:entries=[p for p in entries if attributes.selected(p,attr)]
    else:entries=[p for p in entries if not attributes.get(p)&6]
    def order_fields(options,old_reverse=False):
        fields=[];seen=set()
        for option in options:
            if not option.startswith('/o'):continue
            spec=option[2:].lstrip(':')
            if not spec:spec='n';old_reverse=False
            reverse=old_reverse if not fields else False
            for ch in spec:
                if ch=='-':reverse=True;continue
                if ch in 'nesdg' and ch not in seen:fields.append((ch,reverse));seen.add(ch)
                reverse=False
        return fields
    env_fields=order_fields(inherited)
    fields=order_fields(opts,env_fields[0][1] if env_fields else False) or env_fields or [('n',False)]
    for field,reverse in reversed(fields):
        def key(p):
            return {'n':p.name.casefold(),'e':p.suffix.casefold(),'s':0 if p.is_dir() else p.stat().st_size,'d':p.stat().st_mtime,'g':not p.is_dir()}[field]
        entries.sort(key=key,reverse=reverse)
    if not entries:rt.write('File Not Found\r\n',2);return rt.result(1,1)
    for p in entries:
        name=str(p) if recursive else p.name
        if flag('l'):name=name.lower()
        if bare:rt.write(name+'\r\n')
        else:
            stamp=datetime.fromtimestamp(p.stat().st_mtime).strftime('%m/%d/%Y  %I:%M %p')
            rt.write(stamp+'    '+('<DIR>' if p.is_dir() else str(p.stat().st_size).rjust(14))+' '+name+'\r\n')
    return rt.result(0,0)
