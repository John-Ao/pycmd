"""Parameter/FOR path modifiers, separate from environment substring syntax."""
from datetime import datetime
from pathlib import Path
import ntpath
import os

def resolve(value,state):
    path=Path(value.replace('\\',os.sep));path=path if path.is_absolute() else state.cwd/path
    if path.exists() or os.name=='nt':return path
    current=Path(path.anchor)
    for part in path.parts[1:]:
        if current.is_dir():part=next((p.name for p in current.iterdir() if p.name.casefold()==part.casefold()),part)
        current=current/part
    return current

def apply(value,mods,state,search=None):
    if value.startswith('"'):
        value=value[1:]
        if value.endswith('"'):value=value[:-1]
    if search is not None:
        found=None
        for directory in state.env.get(search,'').split(';'):
            if not directory:continue
            candidate=resolve(directory.strip('"')+os.sep+value,state)
            if candidate.is_file():found=candidate;break
        if found is None:return ''
        value=str(found.resolve())
        if not mods:mods='f'
    if not mods:return value
    mods=mods.lower();path=resolve(value,state);full=str(path.resolve())
    if 's' in mods and path.exists():
        if os.name=='nt':
            import ctypes
            buffer=ctypes.create_unicode_buffer(32768)
            if ctypes.windll.kernel32.GetShortPathNameW(full,buffer,len(buffer)):full=buffer.value
        else:
            from .filesystem import short_name
            parts=[];current=Path(path.anchor)
            for component in path.parts[1:]:
                current=current/component;parts.append(short_name(current))
            full=path.anchor+os.sep.join(parts)
    if 'f' in mods or mods=='s':return full
    drive,tail=ntpath.splitdrive(full)
    parent,name=ntpath.split(tail);stem,extension=ntpath.splitext(name)
    result=[]
    # Combinations follow documented canonical order, regardless of spelling order.
    for mod in 'atzdpnx':
        if mod not in mods:continue
        if mod=='d':result.append(drive)
        elif mod=='p':result.append(parent.rstrip('/\\')+os.sep)
        elif mod=='n':result.append(stem)
        elif mod=='x':result.append(extension)
        elif mod=='z':result.append(str(path.stat().st_size) if path.exists() else '')
        elif mod=='t':result.append(datetime.fromtimestamp(path.stat().st_mtime).strftime('%m/%d/%Y %I:%M %p') if path.exists() else '')
        elif mod=='a':
            from .attributes import get
            flags=get(path) if path.exists() else 0
            result.append(''.join(letter if flags&bit else '-' for bit,letter in [(16,'d'),(1,'r'),(32,'a'),(2,'h'),(4,'s'),(2048,'c'),(4096,'o'),(16384,'e'),(256,'t'),(512,'p'),(1024,'l')]) if path.exists() else '')
    return (' ' if any(c in mods for c in 'atz') else '').join(result)
