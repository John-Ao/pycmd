"""CMD command echo is formatted syntax, after percent and before bang expansion."""
from datetime import datetime
import re
from .syntax import unescape,parse
from .io import extract

def prompt(state):
    now=datetime.now()
    codes={'a':'&','b':'|','c':'(','f':')','g':'>','l':'<','q':'=','s':' ','$':'$',
           '_':'\r\n','h':'\b','e':'\x1b','p':str(state.cwd),'n':state.cwd.drive[:1],
           'd':now.strftime('%a %m/%d/%Y'),'t':now.strftime('%H:%M:%S.%f')[:11],
           'v':'Python CMD compatibility interpreter','+':'+'*len(state.directories)}
    return re.sub(r'\$(.)',lambda m:codes.get(m[1].lower(),''),state.env.get('PROMPT','$P$G'))

def format_node(node):
    if node.kind=='quiet':return format_node(node.children[0])
    if node.kind=='block':
        body=node.children[0]
        if body.kind=='sequence' and '\n' in body.text:
            texts=[format_node(n).rstrip() for n in body.children]
            result='(\r\n'+('  \r\n '.join(texts))+' \r\n)'
        else:result='('+format_node(body)+')'
        _,redirs=extract(node.text)
        for r in redirs:result+=' '+str(r.target)+(('>&'+r.source) if r.mode=='copy' else r.mode+r.source)
        return result+' '
    if node.kind in ('sequence','and','or','pipe'):
        op={'sequence':'&','and':'&&','or':'||','pipe':'|'}[node.kind]
        return (' '+op+' ').join(format_node(n).rstrip() for n in node.children)+' '
    text=unescape(node.text).lstrip('@').rstrip()
    if re.match(r'if\s',text,re.I):
        text=re.sub(r'\s*==\s*',' == ',text)
        text=re.sub(r'\)(\s+else\s+)',r') \1',text,flags=re.I)
        text=re.sub(r'(?<!\s)\)',' )',text)
    return text+' '

def emit(rt,node):
    if not rt.state.echo or getattr(rt,'suppress_echo',False) or node.kind in ('quiet','empty'):return
    if node.kind=='command' and node.text.lstrip().startswith(':'):return
    delayed=rt.state.delayed;rt.state.delayed=False
    try:text=rt.expand_execution(format_node(node))
    finally:rt.state.delayed=delayed
    rt.write('\r\n'+prompt(rt.state)+text+'\r\n')
