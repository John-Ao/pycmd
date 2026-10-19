"""FOR /F option state and record token assignment."""
import re
from .readers import for_lines
from .syntax import Unsupported

class ForOptions:
    def __init__(self,text):
        self.delims=' \t';self.eol=';';self.skip=0;self.mask={1};self.slots=1;self.remainder=0;self.usebackq=False
        # delims/eol can contain spaces; next recognized option terminates the value.
        keys=list(re.finditer(r'(?i)(?:^|\s)(tokens=|delims=|eol=|skip=|usebackq\b)',text))
        if text.strip() and not keys:raise Unsupported('FOR /F options: '+text)
        for i,m in enumerate(keys):
            key=m[1].lower();end=keys[i+1].start() if i+1<len(keys) else len(text)
            value=text[m.end():end]
            if key=='usebackq':self.usebackq=True
            elif key=='delims=':self.delims=value
            elif key=='eol=':self.eol=text[m.end():m.end()+1]
            elif key=='skip=':
                try:self.skip=int(value.strip(),0)
                except ValueError:raise Unsupported('FOR /F skip syntax')
                if self.skip<=0:raise Unsupported('FOR /F skip must be positive')
            else:
                self.mask=set();count=0
                specs=value.strip().split(',')
                specs=[part for spec in specs for part in ([spec[:-1],'*'] if len(spec)>1 and spec.endswith('*') else [spec])]
                for spec in specs:
                    if spec=='*':self.remainder=count+1;count+=1;continue
                    def integer(s):return int(s,16) if s.lower().startswith('0x') else int(s,10)
                    try:
                        if '-' in spec:
                            a,b=map(integer,spec.split('-',1));numbers=range(a,b+1)
                        else:numbers=[integer(spec)]
                    except ValueError:raise Unsupported('FOR /F token syntax')
                    for n in numbers:
                        if n==0:raise Unsupported('FOR /F token zero')
                        if 1<=n<=31:self.mask.add(n);count+=1
                self.slots=max(self.slots,count)
    def records(self,data,encoding,command=False):
        for index,line in enumerate(for_lines(data,encoding,command)):
            if index<self.skip or not line:continue
            if self.eol and line.lstrip(self.delims).startswith(self.eol):continue
            if self.delims:
                fields=list(re.finditer('[^'+re.escape(self.delims)+']+',line))
            else:fields=list(re.finditer(r'[\s\S]+',line))
            if not fields:
                # A nonempty record may have an empty remainder after removing
                # leading delimiters. tokens=* still binds that remainder.
                if not self.mask and self.remainder==1:yield ['']*self.slots
                continue
            selected=[m for n,m in enumerate(fields,1) if n in self.mask]
            values=[m[0] for m in selected]
            if self.remainder and len(values)+1==self.remainder:
                start=selected[-1].end() if selected else 0
                while start<len(line) and line[start] in self.delims:start+=1
                values.append(line[start:])
            if not values or not values[0]:continue
            yield values+['']*max(0,self.slots-len(values))


def command_source(text):
    out=[];quote=False;i=0
    while i<len(text):
        ch=text[i]
        if ch=='^' and not quote and i+1<len(text):out.extend(text[i:i+2]);i+=2;continue
        if ch=='"':quote=not quote
        if not quote and ch in ' \t,;=':
            if out and out[-1]!=' ':out.append(' ')
        else:out.append(ch)
        i+=1
    return ''.join(out)
