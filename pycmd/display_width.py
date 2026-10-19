"""Opt-in legacy Chinese display widths; never rewrite interpreter strings."""
from functools import lru_cache
import re
import unicodedata

@lru_cache(maxsize=4096)
def legacy_wide(char):
    if unicodedata.category(char).startswith(('C','M')):return False
    if unicodedata.east_asian_width(char)!='A':return False
    try:return len(char.encode('cp936'))==2
    except UnicodeEncodeError:return False

def cell_width(char,xp=False):
    if unicodedata.combining(char):return 0
    return 2 if unicodedata.east_asian_width(char) in ('W','F') or xp and legacy_wide(char) else 1

@lru_cache(maxsize=256)
def box_arms(char):
    if len(char)!=1:return None
    name=unicodedata.name(char,'')
    if not name.startswith('BOX DRAWINGS '):return None
    name=name[13:]
    if 'DIAGONAL' in name:return None
    default=next((s for s in ('LIGHT','HEAVY','DOUBLE','SINGLE') if name.startswith(s)), 'LIGHT')
    result={}
    for part in name.split(' AND '):
        style=next((s for s in ('DOUBLE','HEAVY','SINGLE','LIGHT') if s in part),default)
        for word,arms in (('HORIZONTAL','lr'),('VERTICAL','ud'),('LEFT','l'),('RIGHT','r'),('UP','u'),('DOWN','d')):
            if word in part:
                for arm in arms:result[arm]=style
    return result or None

def terminal_character(char):
    """Two narrow cells, with the junction in the right cell; no added bytes in files."""
    if not legacy_wide(char):return char
    arms=box_arms(char)
    if arms:
        left=arms.get('l')
        return ({'DOUBLE':'═','HEAVY':'━'}.get(left,'─') if left else ' ')+char
    if 0x2580<=ord(char)<=0x259f:return char*2
    return char+' '

# Preserve OSC/CSI strings, including titles and color sequences.
CONTROL=re.compile(r'(\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]|\x1b.)')
def terminal_text(text):
    return ''.join(part if part.startswith('\x1b') else ''.join(map(terminal_character,part)) for part in CONTROL.split(text))
