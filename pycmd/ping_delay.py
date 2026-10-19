"""Offline compatibility for PING-based batch delays, not a network probe."""
import ipaddress
import re
import socket
import time
from .syntax import crt_split

HELP=('PING [-n count] [-w milliseconds] [-4|-6] loopback\r\n'
      'PING -n 1 -w milliseconds TEST-NET-address\r\n'
      'Delay emulation only; no network packets. Options also accept /.\r\n')
TEST_NETS=tuple(ipaddress.ip_network(net) for net in ('192.0.2.0/24','198.51.100.0/24','203.0.113.0/24'))


def delay(arg):
    tokens=crt_split(arg);values={};target=None;family=None;i=0
    while i<len(tokens):
        token=tokens[i];i+=1
        if token.startswith(('-','/')):
            option=token[1:].lower()
            if option in ('4','6'):
                if family is not None:raise ValueError('Duplicate address family')
                family=int(option);continue
            if option not in ('n','w') or option in values or i==len(tokens):
                raise ValueError('Unsupported or incomplete PING option: '+token)
            raw=tokens[i];i+=1
            if not re.fullmatch(r'[0-9]+',raw):raise ValueError('PING requires an unsigned integer')
            value=int(raw)
            if value>4294967295 or option=='n' and value==0:raise ValueError('PING value out of range')
            values[option]=value
        elif target is None:target=token.lower()
        else:raise ValueError('PING accepts exactly one target')
    if target is None:raise ValueError('Missing PING target')
    if target in ('localhost','localhost.'):
        address=ipaddress.ip_address('::1' if family==6 else '127.0.0.1')
    else:
        try:
            # inet_aton handles historical shorthand such as 127.1 without DNS.
            address=ipaddress.ip_address(target) if ':' in target else ipaddress.ip_address(socket.inet_aton(target))
        except (ValueError,OSError):raise ValueError('Unsupported PING target: '+target) from None
    if family is not None and address.version!=family:raise ValueError('PING address family mismatch')
    if address.is_loopback:return float(values.get('n',4)-1),0
    if address.version==4 and any(address in net for net in TEST_NETS) and values.get('n')==1 and 'w' in values:
        return values['w']/1000,1
    raise ValueError('Unsupported PING: only loopback delays or -n 1 -w with a TEST-NET address are supported')


def execute(rt,arg):
    if arg.strip()=='/?':rt.write(HELP);return rt.result(0,0)
    try:seconds,code=delay(arg)
    except ValueError as exc:
        rt.write('PING: '+str(exc)+'\r\n',2);return rt.result(1,1)
    rt.write(f'PING delay emulation: {seconds:g} seconds (no network packets).\r\n')
    if seconds:
        if rt.console is not None:rt.console.sleep(seconds)
        else:time.sleep(seconds)
    return rt.result(code,code)
