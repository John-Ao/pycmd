"""Small structural parser. Preserve caret/quotes until command-specific execution."""
from dataclasses import dataclass, replace
from functools import lru_cache
import re

class Unsupported(Exception):pass
class SyntaxFailure(Exception):pass
class SilentSyntaxFailure(SyntaxFailure):pass
class ParseFailure(SyntaxFailure):pass
@dataclass(frozen=True)
class Node:
    kind: str
    text: str = ''
    children: tuple = ()
    source: str = ''
    source_offset: int = 0

_REM=re.compile(r'@?rem(?:\s|$)',re.I)
_EVENT=re.compile(r'[rR@"^()\n&|]')

# Scans are deliberately not shlex: CMD quotation and caret rules differ.
def structural_events(text):
    quote=False;depth=0;i=0;silent=False;start=0
    while i<len(text):
        match=_EVENT.search(text,i)
        if match is None:break
        i=match.start();ch=match[0]
        if not quote and ch in 'rR@' and not text[start:i].strip() and _REM.match(text,i):
            end=text.find('\n',i)
            if end<0:silent=True;break
            i=end;ch=text[i]
        if ch=='^' and not quote:i+=2;continue
        if ch=='\n':quote=False
        if ch=='"':quote=not quote
        elif not quote:
            if ch=='(':
                prefix=text[start:i].lstrip(' @')
                if '<' in prefix or '>' in prefix:
                    from .io import leading
                    _,prefix=leading(prefix)
                echo_data=re.search(r'(?:^|\bdo\s|\bif\s+[^\n]*?\s)\s*@?echo(?:\s|$)',prefix,re.I)
                if not echo_data:
                    if depth or not prefix or (re.match(r'(?:(?:else|do)\s+)*(?:if|for)\b',prefix,re.I) or re.search(r'\b(?:do|else)\s*$',prefix,re.I)):
                        depth+=1;yield i,'open',depth;start=i+1
            elif ch==')':
                if depth:
                    depth-=1;yield i,'close',depth;start=i+1
            elif ch in '&|\n' and not (ch=='&' and i and text[i-1] in '<>'):
                op=text[i:i+2] if text[i:i+2] in ('&&','||') else ch
                if depth==0:yield i,op,depth
                i+=len(op);start=i;continue
        i+=1
    if depth:raise (SilentSyntaxFailure if silent else SyntaxFailure)('Unclosed parenthesis')

def separators(text):
    for pos,kind,depth in structural_events(text):
        if kind not in ('open','close'):yield pos,kind

def parse(text):
    # Cache syntax only; expansion, redirections and file reads stay live.
    # Large generated commands bypass the bounded cache.
    result=_cached_parse(text) if len(text)<=16384 else _parse_source(text)
    if isinstance(result,tuple):
        kind,args=result
        # A fresh exception avoids retaining frames or sharing tracebacks.
        raise kind(*args)
    return result

@lru_cache(maxsize=4096)
def _cached_parse(text):
    try:return _parse_source(text)
    except SyntaxFailure as exc:
        # Partial multiline blocks recur too; their parse outcome is pure syntax.
        return type(exc),exc.args

def _parse_source(text):
    node=_parse(text)
    cursor=0;children=[]
    for child in node.children:
        source=child.source or child.text
        position=text.find(source,cursor)
        if position<0:position=text.find(source)
        # Offsets belong to this parent, never mutate a cached child.
        children.append(replace(child,source_offset=max(0,position)))
        cursor=max(cursor,position+len(source))
    return replace(node,source=text,children=tuple(children))

def _parse(text):
    text=text.lstrip(' \t\r\n').rstrip('\r\n')
    if not text.strip():return Node('empty')
    if text.strip()==')':return Node('empty')
    if text.startswith('@'):return Node('quiet',text,(parse(text[1:]),))
    # REM consumes the rest of this physical line before structure is considered.
    if re.match(r'(?:@?rem(?:\s|$)|:)',text,re.I):
        first,sep,rest=text.partition('\n')
        return Node('sequence',children=(Node('command',first),parse(rest))) if sep else Node('command',first)
    from .io import leading
    prefix,tail=leading(text)
    if prefix and re.match(r'(?:@?(?:if|for|call|rem)(?:\s|$)|:)',tail,re.I):
        if re.match(r'(?:@?rem(?:\s|$)|:)',tail,re.I):return parse(tail)
        return Node('block',prefix,(parse(tail),))
    ops=list(separators(text))
    if re.match(r'@?(?:for|if)\s',text,re.I):
        newline=next((pos for pos,op in ops if op=='\n'),None)
        if newline is not None:return Node('sequence',text,(parse(text[:newline]),parse(text[newline+1:])))
        validate_control(text)
        return Node('command',text)
    for j,(pos,op) in enumerate(ops):
        previous=ops[j-1] if j else None
        if previous and not text[previous[0]+len(previous[1]):pos].strip() and previous[1]!='\n':
            raise ParseFailure(op+' was unexpected at this time.')
    for group,kind in [({'&','\n'},'sequence'),({'||'},'or'),({'&&'},'and'),({'|'},'pipe')]:
        selected=[(p,op) for p,op in ops if op in group]
        if selected:
            start=0;children=[]
            for pos,op in selected:
                if start and re.match(r'@?(?:for|if)\s',text[start:].lstrip(),re.I):
                    children.append(parse(text[start:]));return Node(kind,text,tuple(children))
                children.append(parse(text[start:pos]));start=pos+len(op)
            children.append(parse(text[start:]));return Node(kind,text,tuple(children))
    if prefix and tail.startswith('('):return Node('block',prefix,(parse(tail),))
    if text.startswith('('):
        for i,kind,depth in structural_events(text):
            if kind=='close' and depth==0:
                tail=text[i+1:].strip()
                if tail and not re.match(r'\d?[<>]',tail):raise ParseFailure(tail.split()[0]+' was unexpected at this time.')
                return Node('block',tail,(parse(text[1:i]),))
    validate_control(text)
    return Node('command',text)

def validate_control(text):
    raw=text.lstrip(' @')
    name=raw.split(None,1)[0].lower() if raw else ''
    if re.match(r'^\w+\s+/\?(?:\s|$)',raw):return
    if name=='if':
        tail=re.sub(r'^if\s*','',raw,flags=re.I)
        tail=re.sub(r'^/i\s*','',tail,flags=re.I);tail=re.sub(r'^not\s+','',tail,flags=re.I)
        valid=re.match(r'(?:defined|exist|errorlevel|cmdextversion)\s+[^&|\s]+\s+[^&|\s]',tail,re.I) or re.match(r'(?:"[^"]*"|[^\s=]+)[ \t]*==[ \t]*(?:"[^"]*"|[^\s&|]+)\s+[^&|\s]',tail) or re.match(r'\S+\s+(?:equ|neq|lss|leq|gtr|geq)\s+\S+\s+[^&|\s]',tail,re.I)
        if not valid:raise ParseFailure(('&' if '&' in tail else tail.split()[-1] if tail.split() else 'if')+' was unexpected at this time.')
    elif name=='for':
        if not re.search(r'\bin\s*\([\s\S]*\)\s*do\s+[^&|\s]',raw,re.I):
            raise ParseFailure(('&' if '&' in raw else raw.split()[1] if len(raw.split())>1 else 'for')+' was unexpected at this time.')
    from .io import extract
    extract(text)

def unescape(text):
    if '^' not in text:return text.replace('\ue000','\n')
    out=[];quote=False;i=0
    while i<len(text):
        ch=text[i]
        if ch=='"':quote=not quote
        if ch=='^' and not quote and i+1<len(text):i+=1;ch=text[i]
        out.append(ch);i+=1
    return ''.join(out).replace('\ue000','\n')

def crt_split(text):
    """Windows CRT-like argv for an opted-in external process; not CMD tokenization."""
    if '"' not in text and '\\' not in text:
        text=text.strip(' \t')
        return re.split(r'[ \t]+',text) if text else []
    args=[];i=0
    while i<len(text):
        while i<len(text) and text[i] in ' \t':i+=1
        if i==len(text):break
        buf=[];quoted=False
        while i<len(text) and (quoted or text[i] not in ' \t'):
            count=0
            while i<len(text) and text[i]=='\\':count+=1;i+=1
            if i<len(text) and text[i]=='"':
                buf.extend('\\'*(count//2))
                if count%2:buf.append('"')
                elif quoted and i+1<len(text) and text[i+1]=='"':buf.append('"');i+=1
                else:quoted=not quoted
                i+=1
            else:
                buf.extend('\\'*count)
                if i<len(text):buf.append(text[i]);i+=1
        args.append(''.join(buf))
    return args


def batch_split(text):
    """BAT arguments retain quotes and split unquoted comma/semicolon/equal separators."""
    out=[];start=None;quoted=False
    for i,ch in enumerate(text):
        if ch=='"':quoted=not quoted
        if not quoted and ch in ' \t,;=':
            if start is not None:out.append(text[start:i]);start=None
        elif start is None:start=i
    if start is not None:out.append(text[start:])
    return out
