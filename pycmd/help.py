"""Project-authored built-in command help."""
import json
from pathlib import Path

def display(rt,name):
    if name.lower()=='image':
        from .image_command import HELP
        rt.write(HELP);return rt.result(0,0)
    if name.lower()=='ping':
        from .ping_delay import HELP
        rt.write(HELP);return rt.result(0,0)
    if name.lower()=='mode':
        from .console_mode import HELP
        rt.write(HELP);return rt.result(0,0)
    if name.lower()=='cmos':
        from .cmos import HELP
        rt.write(HELP);return rt.result(0)
    data=json.loads(Path(__file__).with_name('help_data.json').read_text())['commands']
    item=data.get(name.lower())
    if item is None:
        rt.write('For more information on a specific command, type command /?\r\n')
        rt.write('  '.join(sorted(k.upper() for k in data))+'\r\n');return rt.result(0)
    rt.write(item['stdout']);rt.write(item['stderr'],2)
    return rt.result(item['code'])
