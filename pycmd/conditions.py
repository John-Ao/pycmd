"""IF's saturating base-0 conversion and overflowing signed comparison."""
import re
from .state import signed32

def number(text):
    if not re.fullmatch(r'[+-]?(?:0[xX][0-9a-fA-F]+|0[0-7]*|[1-9][0-9]*)',text):return None
    sign=-1 if text.startswith('-') else 1
    digits=text.lstrip('+-')
    base=16 if digits.lower().startswith('0x') else 8 if digits.startswith('0') else 10
    return max(-2147483648,min(2147483647,sign*int(digits,base)))

def compare(left,right,operator,ignore=False):
    a,b=number(left),number(right)
    if a is not None and b is not None:diff=signed32(a-b)
    else:
        if ignore:left,right=left.upper(),right.upper()
        diff=(left>right)-(left<right)
    return {'equ':diff==0,'neq':diff!=0,'lss':diff<0,'leq':diff<=0,'gtr':diff>0,'geq':diff>=0}[operator.lower()]


from functools import lru_cache
_BRANCH_EVENT=re.compile(r'["^()]')
_ELSE=re.compile(r'\s+else\s+(.+)',re.I|re.S)

def branches(body):
    if not body.startswith('('):return body,None
    return _cached_branches(body) if len(body)<=16384 else _branches(body)

@lru_cache(maxsize=4096)
def _cached_branches(body):return _branches(body)

def _branches(body):
    # Unlike structural_events, this scan deliberately preserves the IF-specific
    # quote/newline rules. Cache structure only, never the selected condition.
    depth=0;quoted=False;i=0
    while i<len(body):
        match=_BRANCH_EVENT.search(body,i)
        if match is None:break
        i=match.start();ch=match[0]
        if ch=='^' and not quoted:i+=2;continue
        if ch=='"':quoted=not quoted
        elif not quoted:
            if ch=='(':depth+=1
            elif ch==')':
                depth-=1
                if depth==0:
                    alternative=_ELSE.match(body[i+1:])
                    if alternative:return body[:i+1],alternative[1]
                    break
        i+=1
    return body,None
