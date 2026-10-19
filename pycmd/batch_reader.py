"""LF handling between batch percent expansion and command parsing."""
from .syntax import structural_events, SyntaxFailure

def expanded_record(text):
    # A caret consumes LF, then quotes the following character. Quoted LF is
    # data (the same marker used by physical caret/blank-line continuation).
    out=[];i=0;quote=False
    while i<len(text):
        c=text[i]
        if c=='"':quote=not quote
        if c=='^' and not quote and i+1<len(text):
            if text[i+1]=='\n':
                i+=2
                if i<len(text):
                    out.append('\ue000' if text[i]=='\n' else '^'+text[i]);i+=1
                continue
            out.append(text[i:i+2]);i+=2;continue
        out.append(c);i+=1
    return ''.join(out)

def first_command(text):
    # Unescaped LF ends an ordinary expanded record; inside a block it is a
    # command separator. Structural events only expose depth-zero separators.
    try:
        for pos,kind,depth in structural_events(text):
            if kind=='\n':return text[:pos]
    except SyntaxFailure:pass
    return text
