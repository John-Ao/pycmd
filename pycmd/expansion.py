"""Separate percent expansion of a logical unit from execution-time bang scanning."""
import re

_BANG_EVENT=re.compile(r"[!^]")
from .syntax import Unsupported, SyntaxFailure

def value(expr,state,delayed=False):
    if ':' not in expr or not state.extensions:
        raw=state.dynamic(expr);return raw if len(raw)<=8191 else ''
    name,modifier=expr.split(':',1);raw=state.dynamic(name)
    if not raw:return modifier
    if modifier.startswith('~'):
        parts=modifier[1:].split(',')
        def integer(part):
            part=part.strip()
            if not part:return 0
            sign=-1 if part.startswith('-') else 1;part=part.lstrip('+-')
            return sign*int(part,16 if part.lower().startswith('0x') else 8 if part.startswith('0') else 10)
        try:
            if len(parts)>2:raise ValueError()
            start=integer(parts[0]);start=max(0,len(raw)+start) if start<0 else start
            if len(parts)==1:return raw[start:]
            count=integer(parts[1]);end=len(raw)+count if count<0 else start+count
            return raw[start:max(start,end)]
        except ValueError:return expr
    if '=' in modifier:
        pattern,replacement=modifier.split('=',1)
        if pattern in ('','*'):
            if delayed:return expr
            raise SyntaxFailure('The syntax of the command is incorrect.')
        if pattern.startswith('*'):
            pos=raw.lower().find(pattern[1:].lower())
            return raw if pos<0 else replacement+raw[pos+len(pattern)-1:]
        return re.sub(re.escape(pattern),lambda m:replacement,raw,flags=re.I)
    return expr

def percent(text,state,batch=True,*,per_line=False):
    # A collected BAT block contains multiple reader records. Each record has
    # its own expansion buffer; the block is not one 8191-character line.
    # Split before expansion so inserted newlines do not reset that limit.
    if per_line and '\n' in text:
        return '\n'.join(percent(line,state,batch) for line in text.split('\n'))
    if '%' not in text:return text
    out=[];i=0;expanded=False
    while i<len(text):
        position=text.find('%',i)
        if position<0:out.append(text[i:]);break
        out.append(text[i:position]);i=position
        if batch and i+1<len(text) and text[i+1]=='%':out.append('%');i+=2;continue
        if batch and i+1<len(text) and text[i+1] in '0123456789*':
            key=text[i+1]
            out.append((state.raw_args if state.extensions else '*') if key=='*' else state.args[int(key)] if int(key)<len(state.args) else '')
            i+=2;continue
        if i+1<len(text) and text[i+1]=='~':
            m=re.match(r'%~([fdpnxsatz]*)(?:\$([^:]+):)?([0-9])',text[i:],re.I)
            if m:
                from .modifiers import apply
                index=int(m[3]);raw=state.args[index] if index<len(state.args) else ''
                if index==0 and m[1] and getattr(state,'batch_filename',None):raw=str(state.batch_filename)
                out.append(apply(raw,m[1],state,m[2]) if raw else '');i+=len(m[0]);continue
            if batch:
                raise SyntaxFailure('The following usage of the path operator in batch-parameter\r\nsubstitution is invalid: '+text[i:]+'\r\n\r\n\r\nFor valid formats type CALL /? or FOR /?\r\nThe syntax of the command is incorrect.')
            # FOR modifiers at /C are evaluated with their live binding.
            out.append('%');i+=1;continue
        end=text.find('%',i+1)
        if end<0:
            if not batch:out.append('%')
            i+=1;continue
        expr=text[i+1:end];name=expr.split(':',1)[0]
        known=bool(state.dynamic(name)) or name in state.env
        if not state.extensions and ':' in expr:known=expr in state.env
        if not batch and not known:
            out.append('%');i+=1;continue
        if batch and state.extensions and ':' in expr and not known:
            if name:out.append(expr.split(':',1)[1]);i=end
            else:i+=1
            continue
        expanded=True
        try:v=value(expr,state)
        except SyntaxFailure:
            suffix=text[i+1+expr.index('='):]
            raise SyntaxFailure(suffix+'\r\n was unexpected at this time.\r\nThe syntax of the command is incorrect.')
        if not batch and v==expr and ':' in expr:out.append('%'+expr+'%')
        else:out.append(v)
        i=end+1
    result=''.join(out)
    if expanded and len(result)>8191:raise SyntaxFailure('The input line is too long.\r\nThe syntax of the command is incorrect.')
    return result

def execution(text,state):
    # Substitution is a single scan: inserted FOR values are not scanned as more FOR references.
    if state.for_values and '%' in text:
        from .modifiers import apply
        pattern=None
        if '%~' in text:
            names=''.join(re.escape(k) for k in state.for_values)
            pattern=re.compile(r'%~((?i:[fdpnxsatz]*))(?:\$([^:]+):)?(['+names+'])')
        out=[];i=0
        while i<len(text):
            position=text.find('%',i)
            if position<0:out.append(text[i:]);break
            out.append(text[i:position]);i=position
            if i+1<len(text):
                m=pattern.match(text,i) if pattern else None
                if m:
                    out.append(apply(state.for_values[m[3]],m[1],state,m[2]));i=m.end();continue
                if text[i+1] in state.for_values:out.append(state.for_values[text[i+1]]);i+=2;continue
            out.append(text[i]);i+=1
        text=''.join(out)
    if not state.delayed or '!' not in text:return text
    out=[];i=0
    while i<len(text):
        match=_BANG_EVENT.search(text,i)
        if match is None:out.append(text[i:]);break
        out.append(text[i:match.start()]);i=match.start()
        if text[i]=='^' and i+1<len(text):out.append(text[i+1]);i+=2;continue
        if text[i]=='!':
            while i+1<len(text) and text[i+1]=='!':i+=1
            end=text.find('!',i+1)
            if end<0:i+=1;continue
            expr=text[i+1:end];name=expr.split(':',1)[0]
            out.append(value(expr,state,True))
            i=end if state.extensions and ':' in expr and not state.dynamic(name) else end+1
        else:out.append(text[i]);i+=1
    return ''.join(out)
