"""Read-only OS query subset for the virtual Windows 10 environment.

This does not inspect the Linux host or implement general WMI administration.
"""
import re
from .syntax import crt_split, Unsupported


def execute(rt, arg):
    args=crt_split(arg)
    if len(args)!=4 or [s.lower() for s in args[:2]]!=['os','get'] or args[3].lower() not in ('/value','/format:list'):
        raise Unsupported('WMIC supports only OS GET Version,OSLanguage /VALUE queries')
    values={'version':('Version',rt.state.env.get('PYCMD_OS_VERSION','10.0.19045')),
            'oslanguage':('OSLanguage',rt.state.env.get('PYCMD_OS_LANGUAGE','1033'))}
    properties=args[2].lower().split(',')
    if not properties or any(p not in values for p in properties):
        raise Unsupported('WMIC OS property: '+args[2])
    if not re.fullmatch(r'\d+\.\d+\.\d+',values['version'][1]) or not values['oslanguage'][1].isdigit():
        rt.write('WMIC: Invalid virtual OS profile\r\n',2);return 2
    rt.write('\r\n')
    for prop in sorted(set(properties)):
        name,value=values[prop];rt.write(name+'='+value+'\r\n')
    rt.write('\r\n');return 0
