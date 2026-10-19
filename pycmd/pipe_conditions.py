"""CMD's IF token-concatenation bug when serializing a pipe child."""
import re
from .syntax import parse,SyntaxFailure

HEADER=r'(\s*@?if\s+(?:/i\s+)?(?:not\s+)?)'
TOKEN=r'("[^"]*"|[^\s]+)'

def rebuild(text):
    try:node=parse(text)
    except SyntaxFailure:return text,None
    def visit(node):
        source=node.source or node.text
        if node.kind=='command':
            m=re.match(HEADER+r'(exist|defined)\s+'+TOKEN,source,re.I)
            if not m:m=re.match(HEADER+TOKEN+r'\s+(equ|neq|lss|leq|gtr|geq)\b',source,re.I)
            if not m or '^' in m[0]:return source,None
            tail=source[m.end():]
            candidate=m[1]+m[2]+m[3]+tail
            error=None
            try:parse(candidate)
            except SyntaxFailure:
                token=re.match(r'\s*(\(|\)|"[^"]*"|[^\s()]+)',tail)
                if token:error=token[1]+' was unexpected at this time.'
            return candidate,error
        error=None
        for child in reversed(node.children):
            replacement,issue=visit(child)
            start=child.source_offset;old=child.source or child.text
            source=source[:start]+replacement+source[start+len(old):]
            error=issue or error
        return source,error
    return visit(node)
